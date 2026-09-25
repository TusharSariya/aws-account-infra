"""Select expensive checks from the full PR diff, including deleted paths."""

import fnmatch
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

SCOPES = {
    "checkov": ["**/*.tf", "**/*.tf.json", ".checkov.yaml"],
    "tflint": ["**/*.tf", "**/*.tf.json", ".tflint.hcl"],
    "trivy": [
        "**/*.tf",
        "**/*.tf.json",
        "**/*.yaml",
        "**/*.yml",
        "**/Dockerfile*",
        ".trivyignore",
        ".trivyignore.yaml",
    ],
    "shell": [
        "scripts/*.sh",
        "scripts/git-hooks/*",
        "mocks/localstack/smoke.sh",
        "tests/**",
        ".shellcheckrc",
    ],
    "localstack": [
        "mocks/localstack/**",
        "scripts/localstack.sh",
        "apps/ecr/court-booker/**",
        "apps/lambda/python/3.14/court-booker/**",
        "apps/lambda/python/3.14/swim-calendar/**",
    ],
}


ROOT = Path(__file__).resolve().parents[1]
SCOPES.update(
    {
        k: v
        for k, v in json.loads((ROOT / "config/ci-selection.json").read_text()).items()
        if v
    }
)
# Shared runner and selection changes invalidate every suite. Dependencies for
# application suites are explicit, including packaging helpers and lockfiles.
APPLICATIONS = {
    "court-booker": [
        "apps/lambda/python/3.14/court-booker/**",
        "apps/ecr/court-booker/bookings.yaml",
        "scripts/lambda-package*.sh",
        "apps/platform/ci_runner/arm-package/**",
    ],
    "iracing-calendar": [
        "apps/lambda/python/3.14/iracing-calendar/**",
        "scripts/iracing-package.py",
    ],
    "swim-calendar": [
        "apps/lambda/python/3.14/swim-calendar/**",
        "scripts/swim-package.py",
    ],
}
SHARED = [
    ".github/actions/**",
    "scripts/ci-relevant-changes.py",
    "config/ci-selection.json",
    ".github/workflows/ci-validation.yml",
    "apps/containers/ci-runner/**",
    "scripts/cache*.py",
    "scripts/dependency_cache.py",
    "scripts/tests/test_dependency_cache.py",
    "scripts/build_cache.py",
    "scripts/build-cache-flags.sh",
    "scripts/tests/test_ci_relevant_changes.py",
]


def matches(paths, patterns):
    return any(
        fnmatch.fnmatchcase(path, pattern)
        or (pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]))
        for path in paths
        for pattern in patterns
    )


def relevant(scope, paths):
    return matches(paths, SCOPES[scope] + SHARED + [f".github/workflows/{scope}.yml"])


def changed_paths(event, event_name):
    if event_name in ("workflow_dispatch", "workflow_call"):
        return None
    if event_name == "pull_request":
        pr = event["pull_request"]
        revision = [f"{pr['base']['sha']}...{pr['head']['sha']}"]
    elif event_name == "push":
        before, after = event["before"], event["after"]
        if before == "0" * 40:
            # A newly created branch has no before tree. Select everything.
            return None
        revision = [before, after]
    else:
        raise ValueError("Unsupported selection event: " + event_name)
    return (
        subprocess.check_output(
            [
                "git",
                "diff",
                "--name-only",
                "--no-renames",
                "-z",
                *revision,
                "--",
            ],
            cwd=ROOT,
        )
        .decode()
        .rstrip("\0")
        .split("\0")
    )


def terraform_directories(paths, units):
    tracked = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "*.tf", "*.tf.json"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    files = [ROOT / p for p in tracked if p and (ROOT / p).is_file()]
    directories = {p.parent.relative_to(ROOT).as_posix() for p in files}
    if paths is None or matches(
        paths,
        SHARED
        + [
            ".checkov.yaml",
            ".tflint.hcl",
            ".github/workflows/checkov.yml",
            ".github/workflows/tflint.yml",
        ],
    ):
        return sorted(directories)
    affected = {
        Path(p).parent.as_posix() for p in paths if p.endswith((".tf", ".tf.json"))
    }
    affected.update(u["path"] for u in units)
    # Resolve local module sources and transitively include consumers. Deleted
    # module paths still reach this graph through the consuming source string.
    dependencies = {}
    for file in files:
        parent = file.parent.relative_to(ROOT).as_posix()
        for source in re.findall(r'\bsource\s*=\s*"(\.[^"]+)"', file.read_text()):
            module = (file.parent / source).resolve().relative_to(ROOT).as_posix()
            dependencies.setdefault(parent, set()).add(module)
    while True:
        expanded = affected | {
            parent for parent, modules in dependencies.items() if modules & affected
        }
        if expanded == affected:
            break
        affected = expanded
    return sorted(directories & affected)


def selection(paths):
    spec = importlib.util.spec_from_file_location(
        "deploy_units", ROOT / "scripts/deploy-units.py"
    )
    deploy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deploy)
    units = deploy.ordered(deploy.load_units())
    selected = (
        [u for u in units if u["ci"]]
        if paths is None
        else deploy.select_units(paths, units)
    )
    for unit in selected:
        if unit["cloud"] != "aws" and (unit["cloud"], unit["id"]) not in {
            ("proxmox", "proxmox-homelab"),
            ("talos", "talos-homelab"),
            ("kubernetes", "kubernetes-homelab"),
        }:
            raise ValueError("No deployment gate for selected unit: " + unit["id"])
    checks = [name for name in SCOPES if paths is None or relevant(name, paths)]
    apps = [
        name
        for name, patterns in APPLICATIONS.items()
        if paths is None
        or matches(paths, patterns + SHARED + [".github/workflows/lambda-package.yml"])
    ]
    for suite, prefix in [
        ("homelab-config-tests", "config-"),
        ("homelab-apps-tests", "apps-"),
    ]:
        # Editing the reusable workflow invalidates every job it implements.
        if paths is None or matches(paths, [f".github/workflows/{suite}.yml"]):
            checks.extend(k for k in SCOPES if k.startswith(prefix) and k not in checks)
        if any(k.startswith(prefix) for k in checks) and suite not in checks:
            checks.append(suite)
    directories = terraform_directories(paths, selected)
    if not directories:
        checks = [k for k in checks if k not in ("checkov", "tflint")]
    return {
        "terraform_dirs": directories,
        "suite": deploy.acceptance_suite(paths or [], selected),
        "storage": str(deploy.storage_checks_required(paths or [], selected)).lower(),
        "checks": checks,
        "applications": apps,
        "units": selected,
        "aws_units": [u for u in selected if u["cloud"] == "aws"],
    }


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    paths = changed_paths(event, os.environ["GITHUB_EVENT_NAME"])
    scope = os.environ.get("CHECK_SCOPE")
    values = (
        {"run": paths is None or relevant(scope, paths)} if scope else selection(paths)
    )
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.writelines(
            key
            + "="
            + (
                value
                if isinstance(value, str)
                else json.dumps(value, separators=(",", ":"))
            )
            + "\n"
            for key, value in values.items()
        )
    print(json.dumps(values, indent=2))


if __name__ == "__main__":
    main()

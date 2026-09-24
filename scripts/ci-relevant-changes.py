"""Select expensive checks from the full PR diff, including deleted paths."""
import fnmatch
import json
import os
import subprocess
from pathlib import Path

SCOPES = {
    "checkov": ["**/*.tf", "**/*.tf.json", ".checkov.yaml"],
    "tflint": ["**/*.tf", "**/*.tf.json", ".tflint.hcl"],
    "trivy": ["**/*.tf", "**/*.tf.json", "**/*.yaml", "**/*.yml", "**/Dockerfile*", ".trivyignore", ".trivyignore.yaml"],
    "shell": ["scripts/*.sh", "scripts/git-hooks/*", "mocks/localstack/smoke.sh", "tests/**", ".shellcheckrc"],
    "localstack": ["mocks/localstack/**", "scripts/localstack.sh", "apps/ecr/court-booker/**", "apps/lambda/python/3.14/court-booker/**", "apps/lambda/python/3.14/swim-calendar/**"],
}


def relevant(scope, paths):
    patterns = SCOPES[scope] + [
        f".github/workflows/{scope}.yml",
        ".github/actions/talos-runner-setup/**",
        ".github/actions/relevant-changes/**",
        "scripts/ci-relevant-changes.py",
    ]
    return any(
        fnmatch.fnmatchcase(path, pattern)
        or (pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]))
        for path in paths for pattern in patterns
    )


def main():
    scope = os.environ["CHECK_SCOPE"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if "pull_request" not in event:
        run = True
    else:
        pr = event["pull_request"]
        # Checkout fetch-depth: 0 supplies both commits and their merge base.
        # No API file-count limit; renames include both old and new paths.
        paths = subprocess.check_output([
            "git", "diff", "--name-only", "--no-renames", "-z",
            f'{pr["base"]["sha"]}...{pr["head"]["sha"]}',
        ]).decode().split("\0")
        run = relevant(scope, paths)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"run={str(run).lower()}\n")
    print(f"{scope}: {'affected inputs; run checks' if run else 'no affected inputs; skip expensive steps'}")


if __name__ == "__main__":
    main()

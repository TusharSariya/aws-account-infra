#!/usr/bin/env python3
"""Deterministically audit pinned Spec Kit and PR #30 traceability artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEATURE = ROOT / "specs/001-safe-service-vending"
PIN = "0.16.4"
REQUIRED_FEATURE = (
    "spec.md",
    "plan.md",
    "tasks.md",
    "research.md",
    "data-model.md",
    "quickstart.md",
    "analyze-report.md",
    "validation.md",
    "checklists/requirements.md",
    "checklists/security.md",
)
PLACEHOLDER = re.compile(
    r"\[(?:FEATURE(?: NAME)?|DATE|###-feature|NEEDS CLARIFICATION|TODO|TKTK)\]|<placeholder>",
    re.IGNORECASE,
)
TASK = re.compile(r"^- \[([x>!\- ])\] (T\d{3})\b(.*)$")
REQUIREMENT = re.compile(r"\b(?:FR|SR)-\d{3}\b")


class AuditError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"invalid JSON {path.relative_to(ROOT)}: {error}") from error


def audit_scaffold(base: Path, label: str) -> None:
    init = load_json(base / ".specify/init-options.json")
    integration = load_json(base / ".specify/integration.json")
    if init.get("speckit_version") != PIN or init.get("integration") != "codex":
        raise AuditError(f"{label}: Spec Kit init is not pinned to Codex {PIN}")
    if init.get("script") != "sh" or not init.get("ai_skills"):
        raise AuditError(f"{label}: shell scripts and Codex skills must be enabled")
    if integration.get("version") != PIN or integration.get("installed_integrations") != ["codex"]:
        raise AuditError(f"{label}: invalid integration state")

    for manifest_name in ("codex.manifest.json", "speckit.manifest.json"):
        manifest = load_json(base / ".specify/integrations" / manifest_name)
        if manifest.get("version") != PIN:
            raise AuditError(f"{label}: {manifest_name} is not pinned to {PIN}")
        for relative, expected in manifest.get("files", {}).items():
            target = base / relative
            if not target.is_file():
                raise AuditError(f"{label}: managed file missing: {relative}")
            if sha256(target) != expected:
                raise AuditError(f"{label}: managed file hash mismatch: {relative}")

    constitution = (base / ".specify/memory/constitution.md").read_text(encoding="utf-8")
    if PLACEHOLDER.search(constitution) or "[PRINCIPLE_" in constitution:
        raise AuditError(f"{label}: constitution contains unresolved placeholders")
    for name in ("spec", "plan", "tasks", "checklist"):
        override = base / f".specify/templates/overrides/{name}-template.md"
        if not override.is_file():
            raise AuditError(f"{label}: missing project template override {override.name}")


def audit_golden_parity() -> None:
    golden = ROOT / "templates/service-stack"
    for source in sorted((ROOT / ".agents/skills").glob("speckit-*/SKILL.md")):
        relative = source.relative_to(ROOT)
        if source.read_bytes() != (golden / relative).read_bytes():
            raise AuditError(f"golden scaffold drift: {relative}")
    for relative in (
        ".specify/init-options.json",
        ".specify/integration.json",
        ".specify/integrations/codex.manifest.json",
        ".specify/integrations/speckit.manifest.json",
        ".specify/workflows/speckit/workflow.yml",
        ".specify/workflows/workflow-registry.json",
    ):
        if (ROOT / relative).read_bytes() != (golden / relative).read_bytes():
            raise AuditError(f"golden scaffold drift: {relative}")


def audit_feature() -> None:
    missing = [name for name in REQUIRED_FEATURE if not (FEATURE / name).is_file()]
    if missing:
        raise AuditError("missing PR #30 artifacts: " + ", ".join(missing))

    combined = ""
    for path in sorted(FEATURE.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = PLACEHOLDER.search(text)
        if match:
            raise AuditError(f"unresolved placeholder in {path.relative_to(ROOT)}: {match.group(0)}")
        combined += "\n" + text

    spec = (FEATURE / "spec.md").read_text(encoding="utf-8")
    tasks = (FEATURE / "tasks.md").read_text(encoding="utf-8")
    requirements = set(REQUIREMENT.findall(spec))
    task_requirements = set(REQUIREMENT.findall(tasks))
    uncovered = sorted(requirements - task_requirements)
    if uncovered:
        raise AuditError("requirements without task coverage: " + ", ".join(uncovered))

    seen: set[str] = set()
    for number, line in enumerate(tasks.splitlines(), start=1):
        if not line.startswith("- [") or " T" not in line:
            continue
        match = TASK.match(line)
        if not match:
            raise AuditError(f"malformed task at tasks.md:{number}")
        status, task_id, detail = match.groups()
        if task_id in seen:
            raise AuditError(f"duplicate task id {task_id}")
        seen.add(task_id)
        if "evidence:" not in detail:
            raise AuditError(f"{task_id} has no evidence reference")
        if status != "x" and ("reason:" not in detail or "gate:" not in detail):
            raise AuditError(f"{task_id} is not complete and lacks reason/gate")
    if not seen:
        raise AuditError("tasks.md contains no auditable tasks")


def audit_contract_paths() -> None:
    forbidden = (
        "specs/upace/openapi.yaml",
        '"specs/*/openapi.yaml"',
        'repo / "specs" / args.spec / "openapi.yaml"',
        "this infrastructure monorepo uses `product/`",
    )
    candidates = [
        path for path in ROOT.rglob("*")
        if path.is_file()
        and path.resolve() != Path(__file__).resolve()
        and ".git" not in path.parts
        and ".repowise" not in path.parts
        and "graphify-out" not in path.parts
        and path.suffix in {".md", ".py", ".sh", ".yml", ".yaml", ".json"}
    ]
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        for value in forbidden:
            if value in text:
                raise AuditError(f"old OpenAPI/product convention in {path.relative_to(ROOT)}: {value}")


def audit_snapshot_parent() -> None:
    snapshot = ROOT / "docs/reviews/pr-30-repository-map.md"
    if not snapshot.is_file():
        raise AuditError("missing reviewed PR #30 repository map")
    text = snapshot.read_text(encoding="utf-8")
    match = re.search(r"Analyzed implementation commit: `([0-9a-f]{40})`", text)
    if not match:
        raise AuditError("repository map lacks a full analyzed implementation commit")
    history = subprocess.run(
        ["git", "log", "-1", "--format=%P", "--", str(snapshot.relative_to(ROOT))],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().split()
    if history and match.group(1) != history[0]:
        raise AuditError(
            f"stale repository map: analyzed {match.group(1)}, expected map commit parent {history[0]}"
        )


def main() -> int:
    audit_scaffold(ROOT, "root")
    audit_scaffold(ROOT / "templates/service-stack", "golden template")
    audit_golden_parity()
    audit_feature()
    audit_contract_paths()
    audit_snapshot_parent()
    print("Spec Kit and PR #30 audit valid")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as error:
        print(f"audit failed: {error}")
        raise SystemExit(1)

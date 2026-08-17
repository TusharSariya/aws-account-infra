#!/usr/bin/env python3
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "README.md",
    "specs/README.md",
    ".specify/integration.json",
    ".specify/integrations/codex.manifest.json",
    ".specify/integrations/speckit.manifest.json",
    ".specify/memory/constitution.md",
    ".specify/templates/overrides/spec-template.md",
    ".specify/templates/overrides/plan-template.md",
    ".specify/templates/overrides/tasks-template.md",
    ".specify/templates/overrides/checklist-template.md",
    ".agents/skills/speckit-specify/SKILL.md",
    ".agents/skills/speckit-plan/SKILL.md",
    ".agents/skills/speckit-tasks/SKILL.md",
    ".agents/skills/speckit-analyze/SKILL.md",
    ".agents/skills/speckit-converge/SKILL.md",
    "tooling/repository-intelligence.json",
    "scripts/repository-intelligence.sh",
    ".github/workflows/test.yml",
    ".github/ISSUE_TEMPLATE/access-step-up.yml",
)


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    wrappers = (ROOT / "CLAUDE.md", ROOT / "GEMINI.md")
    invalid = [path.name for path in wrappers if "AGENTS.md" not in path.read_text()]
    manifest_errors = []
    for name in ("codex.manifest.json", "speckit.manifest.json"):
        manifest = json.loads((ROOT / ".specify/integrations" / name).read_text())
        if manifest.get("version") != "0.16.4":
            manifest_errors.append(f"{name} version")
        for relative, expected in manifest.get("files", {}).items():
            target = ROOT / relative
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                manifest_errors.append(relative)
    constitution = (ROOT / ".specify/memory/constitution.md").read_text()
    placeholders = re.findall(r"\[(?:PROJECT_NAME|PRINCIPLE_[^]]+|SECTION_[^]]+|CONSTITUTION_VERSION)\]", constitution)
    if missing or invalid or manifest_errors or placeholders:
        if missing:
            print("missing repository contract files: " + ", ".join(missing))
        if invalid:
            print("wrappers do not reference AGENTS.md: " + ", ".join(invalid))
        if manifest_errors:
            print("invalid managed Spec Kit files: " + ", ".join(manifest_errors))
        if placeholders:
            print("constitution has placeholders: " + ", ".join(placeholders))
        return 1
    print("repository contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

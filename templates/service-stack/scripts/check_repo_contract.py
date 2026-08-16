#!/usr/bin/env python3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "README.md",
    "specs/README.md",
    ".github/workflows/test.yml",
    ".github/ISSUE_TEMPLATE/access-step-up.yml",
)


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    wrappers = (ROOT / "CLAUDE.md", ROOT / "GEMINI.md")
    invalid = [path.name for path in wrappers if "AGENTS.md" not in path.read_text()]
    if missing or invalid:
        if missing:
            print("missing repository contract files: " + ", ".join(missing))
        if invalid:
            print("wrappers do not reference AGENTS.md: " + ", ".join(invalid))
        return 1
    print("repository contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

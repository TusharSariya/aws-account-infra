#!/usr/bin/env python3
"""Print the stable spec version or a channel-specific package version."""
from __future__ import annotations

import argparse
from pathlib import Path

def spec_version(spec_file: Path) -> str:
    in_info = False
    for line in spec_file.read_text().splitlines():
        if line.startswith("info:"):
            in_info = True
            continue
        if in_info:
            if line.startswith("  version:"):
                return line.split(":", 1)[1].strip().strip("'\"")
            if line and not line.startswith(" "):
                break
    raise SystemExit(f"no info.version in {spec_file}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("--channel", choices=("stable", "candidate"), default="stable")
    parser.add_argument("--run", default="0")
    parser.add_argument("--pr", default="0")
    parser.add_argument("--ecosystem", choices=("python", "npm"), default="python")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    version = spec_version(repo / "contracts" / "openapi" / args.spec / "openapi.yaml")
    if args.channel == "stable":
        print(version)
        return
    if args.ecosystem == "python":
        # PEP 440: 0.1.0.dev123+pr45
        print(f"{version}.dev{args.run}+pr{args.pr}")
        return
    # npm semver pre-release: 0.1.0-pr.45.123
    print(f"{version}-pr.{args.pr}.{args.run}")


if __name__ == "__main__":
    main()

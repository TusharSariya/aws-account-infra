#!/usr/bin/env python3
"""Small dependency-free interface to deploy-units.json."""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_units():
    with (ROOT / "deploy-units.json").open(encoding="utf-8") as handle:
        return json.load(handle)["units"]


def changed_files(base, head):
    command = ["git", "diff", "--name-only", base, head, "--"]
    return subprocess.check_output(command, cwd=ROOT, text=True).splitlines()


def ordered(units):
    by_id = {unit["id"]: unit for unit in units}
    result, visiting = [], set()

    def visit(unit):
        if unit["id"] in {item["id"] for item in result}:
            return
        if unit["id"] in visiting:
            raise SystemExit(f"dependency cycle at {unit['id']}")
        visiting.add(unit["id"])
        for dependency in unit["dependencies"]:
            if dependency not in by_id:
                raise SystemExit(f"unknown dependency {dependency!r} for {unit['id']}")
            visit(by_id[dependency])
        visiting.remove(unit["id"])
        result.append(unit)

    for candidate in units:
        visit(candidate)
    return result


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("id")
    changed_parser = subparsers.add_parser("changed")
    changed_parser.add_argument("base")
    changed_parser.add_argument("head")
    args = parser.parse_args()
    units = ordered(load_units())

    if args.command == "get":
        unit = next((item for item in units if item["id"] == args.id), None)
        if unit is None:
            raise SystemExit(f"unknown deploy unit: {args.id}")
        print(json.dumps(unit))
        return

    files = changed_files(args.base, args.head)
    global_change = any(
        path in {"deploy-units.json", "scripts/deploy-units.py", "scripts/infra.sh"}
        or path.startswith(".github/workflows/tofu-")
        for path in files
    )
    selected = [
        unit for unit in units
        if unit["ci"] and (global_change or any(path.startswith(prefix) for path in files for prefix in unit["watch"]))
    ]
    print(json.dumps(selected, separators=(",", ":")))


if __name__ == "__main__":
    main()

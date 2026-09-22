#!/usr/bin/env python3
"""Back up and transfer retained Helm state; no infrastructure apply or deletion.

Run with CI applies quiescent. Source removed blocks additionally forbid uninstall.
Interrupted transfers retain duplicate ownership until rerun; stop all applies and
inspect private backups before proceeding. No force-push or serial bypass exists.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
MOVES = {
    "homelab": {"tailscale_operator", "pihole", "lifecycle", "argo", "jobs"},
    "homelab-ci": {"kueue", "queue", "arc", "runners"},
}


def canonical(value):
    # OpenTofu serializes independent checks from a map in nondeterministic
    # order. Preserve every value while comparing that set independent of order.
    value = copy.deepcopy(value)
    if isinstance(value.get("check_results"), list):
        for check in value["check_results"]:
            if isinstance(check.get("objects"), list):
                check["objects"].sort(key=lambda item: json.dumps(item, sort_keys=True))
        value["check_results"].sort(key=lambda item: json.dumps(item, sort_keys=True))
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    args.private.mkdir(mode=0o700, parents=True, exist_ok=False)

    def run(root, *command):
        result = subprocess.run(
            ["tofu", "-chdir=" + str(ROOT / "live/kubernetes" / root), *command],
            capture_output=True,
            timeout=120,
        )
        if result.returncode:
            (args.private / (root + "-failure.log")).write_bytes(
                result.stdout + result.stderr
            )
            raise RuntimeError("State operation failed; inspect private diagnostics")
        return result.stdout

    def pull(root):
        state = json.loads(run(root, "state", "pull"))
        (args.private / (root + "-before.json")).write_text(json.dumps(state, indent=2))
        return state

    destination = "homelab-management"
    target = pull(
        destination
    )  # Initialize/import always_on into its real backend first.
    sources = {name: pull(name) for name in MOVES}
    after = copy.deepcopy(target)
    target_ids = {(r.get("module"), r["type"], r["name"]) for r in after["resources"]}
    for name, state in sources.items():
        transferring = [
            r
            for r in state["resources"]
            if r["type"] == "helm_release"
            and r["name"] in MOVES[name]
            and not r.get("module")
        ]
        if {r["name"] for r in transferring} != MOVES[name]:
            raise ValueError(
                "Source state does not match the reviewed migration inventory"
            )
        for resource in transferring:
            key = (resource.get("module"), resource["type"], resource["name"])
            if key in target_ids:
                raise ValueError(
                    "Destination already owns a transferred address; inspect interrupted migration"
                )
            target_ids.add(key)
            after["resources"].append(resource)
        state["resources"] = [r for r in state["resources"] if r not in transferring]
        state["serial"] += 1
    after["serial"] += 1
    planned = {destination: after, **sources}
    for name, state in planned.items():
        (args.private / (name + "-after.json")).write_text(json.dumps(state, indent=2))
    if args.push:
        # Re-read every lineage/serial before the first write. Each push also uses
        # the backend lock and normal lineage/serial checks; never --force.
        for name in planned:
            before = json.loads((args.private / (name + "-before.json")).read_text())
            current = json.loads(run(name, "state", "pull"))
            if canonical(current) != canonical(before):
                raise RuntimeError("Concurrent state change; do not transfer")
        for name in [destination, *MOVES]:
            run(
                name,
                "state",
                "push",
                "-lock-timeout=60s",
                str((args.private / (name + "-after.json")).resolve()),
            )
            (args.private / (name + "-pushed")).touch()
    print(
        "Helm state transfer "
        + ("completed" if args.push else "prepared only")
        + "; private backups: "
        + str(args.private)
    )


if __name__ == "__main__":
    main()

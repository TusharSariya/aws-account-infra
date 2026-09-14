#!/usr/bin/env python3
"""Small dependency-free interface to deploy-units.json."""

import argparse
import json
import os
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


def select_units(files, units):
    global_change = any(
        path in {"deploy-units.json", "scripts/deploy-units.py", "scripts/infra.sh"}
        or path.startswith(".github/workflows/tofu-") for path in files)
    return [unit for unit in units if unit["ci"] and
            (global_change or any(path.startswith(prefix) for path in files for prefix in unit["watch"]))]


def acceptance_suite(files, selected):
    both = any(unit['cloud'] in ('talos', 'proxmox', 'kubernetes') for unit in selected) or any(
        path.startswith(('.github/actions/talos-', '.github/workflows/homelab-acceptance',
                         'scripts/homelab-capacity-',
                         '.github/workflows/homelab-worker-maintenance'))
        or path == 'scripts/homelab-readiness.sh' for path in files)
    network = both or 'scripts/homelab-cilium-validate.sh' in files
    pvc = both or 'scripts/homelab-storage-validate.py' in files
    return 'all' if network and pvc else 'network' if network else 'pvc' if pvc else 'none'


def storage_checks_required(files, selected):
    return any(unit['cloud'] in ('proxmox', 'talos', 'kubernetes') for unit in selected) or any(
        path.startswith(('apps/platform/storage/', 'charts/homelab-capacity/',
                         'scripts/tests/storage/', 'scripts/tests/test_capacity', 'scripts/homelab-capacity-',
                         '.github/workflows/homelab-capacity-', 'config/environments/proxmox/homelab/capacity/',
                         'openspec/changes/add-homelab-workload-scheduling/'))
        or path in ('scripts/tests/test_capacity.py', 'scripts/tests/test_physical_capacity.py',
                    'scripts/tests/test_capacity_chart.py', 'scripts/tests/test_capacity_collectors.py', 'scripts/install-homelab-capacity.sh',
                    '.github/workflows/storage-foundation.yml') for path in files)


def acceptance_gate(needs, apply_requested, reboot_requested):
    if needs['detect']['result'] != 'success':
        raise ValueError('Deployment/acceptance selection failed')
    outputs = needs['detect']['outputs']
    units = json.loads(outputs['units'])
    if outputs.get('storage') == 'true' and needs.get('storage-foundation', {}).get('result') != 'success':
        raise ValueError('Selected storage checks must succeed, including test-only changes')
    if units and not apply_requested:
        raise ValueError('Infrastructure changes require the apply label and a successful CI apply before merge')
    apply_expected = bool(units) and apply_requested
    if apply_expected and needs['apply']['result'] != 'success':
        raise ValueError('Requested apply must succeed')
    if needs['apply']['result'] not in ('success', 'skipped'):
        raise ValueError('Apply failed or was cancelled')
    first = needs['apply'].get('outputs', {}).get('needs_worker_reboot') == 'true'
    reboot_expected = first or (apply_expected and reboot_requested and
                               any(u['id'] == 'talos-homelab' for u in units))
    if reboot_expected and needs['worker-maintenance']['result'] != 'success':
        raise ValueError('Explicit worker persistence rehearsal required; request worker-reboot with apply')
    if needs['worker-maintenance']['result'] not in ('success', 'skipped'):
        raise ValueError('Worker maintenance failed or was cancelled')
    if outputs['suite'] != 'none' and needs['acceptance']['result'] != 'success':
        raise ValueError('Selected acceptance must succeed, including test-only changes')
    if needs['acceptance']['result'] not in ('success', 'skipped'):
        raise ValueError('Acceptance failed or was cancelled')


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("id")
    for command in ('changed', 'acceptance', 'storage'):
        changed_parser = subparsers.add_parser(command)
        changed_parser.add_argument('base')
        changed_parser.add_argument('head')
    subparsers.add_parser('acceptance-gate')
    args = parser.parse_args()
    if args.command == 'acceptance-gate':
        try:
            acceptance_gate(json.loads(os.environ['NEEDS_JSON']),
                            os.environ['APPLY_REQUESTED'] == 'true',
                            os.environ['REBOOT_REQUESTED'] == 'true')
        except ValueError as error:
            raise SystemExit(str(error))
        return
    units = ordered(load_units())

    if args.command == "get":
        unit = next((item for item in units if item["id"] == args.id), None)
        if unit is None:
            raise SystemExit(f"unknown deploy unit: {args.id}")
        print(json.dumps(unit))
        return

    files = changed_files(args.base, args.head)
    selected = select_units(files, units)
    if args.command == 'storage':
        print(str(storage_checks_required(files, selected)).lower())
    elif args.command == 'acceptance':
        print(acceptance_suite(files, selected))
    else:
        print(json.dumps(selected, separators=(",", ":")))


if __name__ == "__main__":
    main()

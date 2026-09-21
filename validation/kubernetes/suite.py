#!/usr/bin/env python3
"""Repeatable manual Kubernetes validation, executed outside the target cluster."""

import argparse
import json
import time
import fcntl
from pathlib import Path
import secrets
import signal
import sys

from core import Blocked, Run, load_profile, path, read_json
from scenarios import SCENARIOS

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "preflight", "run", "cleanup"))
    parser.add_argument("--profile", type=Path, default=ROOT / "profiles/pilot.json")
    parser.add_argument(
        "--scenarios", default="smoke", help="Comma-separated scenario IDs or all"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "runs")
    parser.add_argument(
        "--run-dir", type=Path, help="Existing run directory; required by cleanup"
    )
    args = parser.parse_args(argv)
    if args.command == "list":
        for name in SCENARIOS:
            print(name)
        for item in read_json(ROOT / "coverage.json"):
            print(f"{item['id']} [deferred] {item['prerequisite']}")
        return 0
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    p = load_profile(args.profile)
    deferred = read_json(ROOT / "coverage.json")
    requested = (
        list(SCENARIOS) if args.scenarios == "all" else args.scenarios.split(",")
    )
    unknown = set(requested) - set(SCENARIOS) - {i["id"] for i in deferred}
    if unknown:
        parser.error("Unknown scenarios: " + ", ".join(sorted(unknown)))
    if args.command == "cleanup":
        if not args.run_dir:
            parser.error("cleanup requires --run-dir")
        state = read_json(args.run_dir / "run.json")
        if state["profile"] != p:
            parser.error("Cleanup profile differs from persisted run profile")
        r = Run(p, args.run_dir.resolve(), state["id"])
        r.uid = state["cluster_uid"]
        allowed = {p["namespace"], p["consolidation_namespace"]}
        if not set(state["namespaces"]) <= allowed:
            parser.error("Run journal has namespaces outside profile")
        r.namespaces = state["namespaces"]
        r.initial_volume_uids = state.get("initial_volume_uids")
        r.allocated_volumes = state.get("allocated_volumes", [])
        previous = args.run_dir / "report.json"
        if previous.exists():
            r.results = read_json(previous)["results"]
        event_file = args.run_dir / "events.jsonl"
        if event_file.exists():
            r.events = [
                json.loads(line) for line in event_file.read_text().splitlines() if line
            ]
            r.started = time.monotonic() - max(
                (e["elapsed"] for e in r.events), default=0
            )
    else:
        run_id = "kv-" + secrets.token_hex(8)
        directory = args.output.resolve() / run_id
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        r = Run(p, directory, run_id)
        r.state()
    print(f"Run: {r.id}\nEvidence: {r.directory}", flush=True)
    # Serializes cooperating suite processes without modifying controller lifecycle locks.
    lockdir = path("~/.local/state/kubernetes-validation")
    lockdir.mkdir(parents=True, exist_ok=True)
    with (lockdir / (p["name"] + ".lock")).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            r.execute(
                "preflight",
                lambda _: (_ for _ in ()).throw(
                    Blocked("Another validation run holds the target lock")
                ),
            )
            return r.report()
        if args.command == "cleanup":
            r.execute("cleanup-retry", lambda run: run.cleanup())
            return r.report()
        try:
            r.execute("preflight", lambda run: run.preflight())
            if args.command == "preflight":
                return r.report()
            if r.results[-1]["status"] != "passed":
                for name in requested:
                    r.results.append(
                        {
                            "name": name,
                            "status": "blocked",
                            "detail": "Preflight did not pass",
                        }
                    )
                return r.report()
            # A live smoke is mandatory in this run before any broader scenario.
            selected = ["smoke"] + [n for n in requested if n != "smoke"]
            smoke_passed = False
            for name in selected:
                if name not in SCENARIOS:
                    item = next(i for i in deferred if i["id"] == name)
                    r.results.append(
                        {
                            "name": name,
                            "status": "blocked",
                            "detail": item["prerequisite"] + " " + item["issue"],
                        }
                    )
                    continue
                if name != "smoke" and not smoke_passed:
                    r.results.append(
                        {
                            "name": name,
                            "status": "blocked",
                            "detail": "Live smoke did not pass",
                        }
                    )
                    continue
                print(f"Running {name}", flush=True)
                r.execute(name, SCENARIOS[name])
                if name == "smoke":
                    smoke_passed = r.results[-1]["status"] == "passed"
                r.execute("cleanup-" + name, lambda run: run.cleanup())
                if r.results[-1]["status"] != "passed":
                    for remaining in selected[selected.index(name) + 1 :]:
                        r.results.append(
                            {
                                "name": remaining,
                                "status": "blocked",
                                "detail": "Previous cleanup failed",
                            }
                        )
                    break
        except KeyboardInterrupt:
            r.results.append(
                {
                    "name": "interruption",
                    "status": "failed",
                    "detail": "Run interrupted; retry cleanup with this run directory",
                }
            )
            recorded = {result["name"] for result in r.results}
            for name in dict.fromkeys(["smoke", *requested]):
                if name not in recorded:
                    r.results.append(
                        {
                            "name": name,
                            "status": "blocked",
                            "detail": "Run interrupted before this scenario",
                        }
                    )
        finally:
            if args.command == "run":
                r.execute("final-cleanup", lambda run: run.cleanup())
                for item in deferred:
                    if item["id"] not in requested:
                        r.results.append(
                            {
                                "name": item["id"],
                                "status": "deferred",
                                "detail": item["prerequisite"] + " " + item["issue"],
                            }
                        )
                r.report()
        return r.report()


if __name__ == "__main__":
    sys.exit(main())

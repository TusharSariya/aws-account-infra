#!/usr/bin/env python3
"""Capture comparable GitHub run timings; label cold and warm evidence explicitly."""

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path


def elapsed(start, end):
    if not start or not end:
        return None
    value = (
        datetime.fromisoformat(end.replace("Z", "+00:00"))
        - datetime.fromisoformat(start.replace("Z", "+00:00"))
    ).total_seconds()
    return value if value >= 0 else None


def report(run, jobs, cache_state, startup):
    if run["status"] != "completed":
        raise ValueError("Only completed runs are comparable")
    attempt = run.get("run_attempt", 1)
    start = run.get("run_started_at") if attempt > 1 else run["created_at"]
    rows = []
    for job in jobs:
        # GitHub includes successful reused jobs in a failed-job rerun, with
        # their original execution timestamps. They cost nothing this attempt.
        reused = bool(attempt > 1 and start and job.get("started_at") and
                      elapsed(start, job["started_at"]) is None)
        allocated = bool(job.get("runner_name")) and not reused
        rows.append(
            {
                "name": job["name"],
                "conclusion": job["conclusion"],
                "runner": job.get("runner_name"),
                "reused_from_previous_attempt": reused,
                "queue_seconds": elapsed(job.get("created_at"), job.get("started_at")) if allocated else None,
                "execution_seconds": elapsed(
                    job.get("started_at"), job.get("completed_at")
                ) if allocated else None,
            }
        )
    return {
        "run_id": run["id"],
        "run_attempt": attempt,
        "timing_start": start,
        "url": run["html_url"],
        "source_revision": run["head_sha"],
        "cache_state": cache_state,
        "conclusion": run["conclusion"],
        "elapsed_seconds": elapsed(
            start,
            max(
                (j["completed_at"] for j in jobs if j.get("completed_at")), default=None
            ),
        ),
        "runner_seconds": sum(j["execution_seconds"] or 0 for j in rows),
        "jobs": rows,
        "startup_first_observations": startup,
        "limitations": "Queue time is GitHub created_at to started_at, including scheduling. Reruns start at run_started_at; reused earlier jobs are excluded from this attempt's runner time. Jobs without an allocated runner and inconsistent timestamps are excluded from timing totals. Startup timestamps are first observations, bounded by reconciliation cadence. Compare identical jobs/revisions and cold/warm cohorts separately.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=int)
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--cache-state", required=True, choices=["cold", "warm", "unknown"])
    parser.add_argument("--startup", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.attempt is not None and args.attempt < 1:
        parser.error("--attempt must be positive")
    base = "repos/TusharSariyaOrg/aws-account-infra/actions/runs/" + str(args.run_id)
    metadata = base + "/attempts/" + str(args.attempt) if args.attempt else base
    run = json.loads(subprocess.check_output(["gh", "api", metadata]))
    jobs_url = base + "/attempts/" + str(run.get("run_attempt", 1)) + "/jobs?per_page=100"
    pages = json.loads(
        subprocess.check_output(
            ["gh", "api", "--paginate", "--slurp", jobs_url]
        )
    )
    jobs = [j for page in pages for j in page["jobs"]]
    startup = {p.name: json.loads(p.read_text()) for p in args.startup}
    args.output.write_text(
        json.dumps(report(run, jobs, args.cache_state, startup), indent=2) + "\n"
    )


if __name__ == "__main__":
    main()

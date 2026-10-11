"""Explicit, bounded one-off turnout bootstrap, checkpointed in the shared cache."""

import copy
import math

from . import backfill, turnout
from .api import Zwift
from .auth import Auth
from .errors import ContractError, RateLimited
from .storage import Busy

MAX_BATCHES = 100
MAX_AGE = 86400


def progress(state, target, now):
    rows = copy.deepcopy(target.get("turnout", []))
    for row in rows:
        row.setdefault(
            "band", row.get("turnout_division", [None])[0] == "score" or None
        )
    _, counts = turnout.apply(rows, state, now)
    index = turnout.family_index(state.get("turnout_events", {}))
    pending = [
        row
        for row in rows
        if turnout.evidence(row, state.get("turnout_events", {}), now, index=index)[1]
    ]
    retries = state.get("turnout_retries", {})
    due = [row for row in pending if retries.get(row["id"], 0) <= now.timestamp()]
    retry = min((retries[row["id"]] for row in pending if row not in due), default=0)
    return counts | {
        "target_events": len(rows),
        "pending_editions": len(pending),
        "ready_events": len(due),
        "next_retry": retry,
    }


def refresh(store, parameters, http, now, run_id):
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 256:
        raise ContractError("Invalid bootstrap execution ID")
    try:
        store.claim()
    except Busy:
        return {"status": "running", "wait_seconds": 60, "reason": "busy"}
    try:
        state, etag = store.read(backfill.STATE)
        if not state:
            legacy, _ = store.read("private.json")
            state = copy.deepcopy(legacy.get("history", {})) | {"version": 1}
        if state.get("version") != 1:
            raise ContractError("Unknown historical state version")
        job = state.get("bootstrap", {})
        if job.get("run_id") != run_id:
            if job.get("status") == "running" and now.timestamp() < job["deadline"]:
                return {"status": "conflict"}
            target, _ = store.read(backfill.TARGETS)
            if (
                "turnout" not in target
                or now.timestamp() - target.get("updated", 0) > 86400
            ):
                return {"status": "no_targets"}
            job = state["bootstrap"] = {
                "run_id": run_id,
                "status": "running",
                "started": now.timestamp(),
                "deadline": now.timestamp() + MAX_AGE,
                "batches": 0,
                "requests": 0,
                "stalled_batches": 0,
                "target": copy.deepcopy(target),
            }
        target = job["target"]
        if any(not row.get("name") for row in target.get("turnout", [])):
            latest, _ = store.read(backfill.TARGETS)
            names = {row["id"]: row.get("name") for row in latest.get("turnout", [])}
            for row in target.get("turnout", []):
                if names.get(row["id"]):
                    row["name"] = names[row["id"]]
        backfill.seed(state, target, now)

        def save(value):
            nonlocal etag
            etag = store.private_write(
                backfill.STATE, backfill.bounded(value, target), etag
            )

        def finish(status, report):
            job.update(status=status, report=report, updated=now.timestamp())
            save(state)
            return {
                "status": status,
                "run_id": run_id,
                "batches": job["batches"],
                "requests": job["requests"],
                "reserved_requests": job["batches"] * 120,
                "turnout": report,
                "duration": backfill.status(state, target),
            }

        report = progress(state, target, now)
        if job["status"] != "running":
            return finish(job["status"], report)

        def done(report):
            discovery_done = not any(
                row.get("name") for row in target.get("turnout", [])
            ) or (
                state.get("scan", {}).get("complete")
                and state.get("scan", {}).get("turnout_discovery_version") == 1
            )
            return (
                discovery_done
                and not report["pending_editions"]
                and (
                    len(backfill.coverage(state, target))
                    == len(target.get("signatures", {}))
                    or (
                        state.get("scan", {}).get("complete")
                        and not any(
                            not row.get("start")
                            or backfill.instant(row["start"])
                            <= now - backfill.timedelta(days=1)
                            for row in state.get("pending", {}).values()
                        )
                    )
                )
            )

        if done(report):
            return finish("complete", report)
        if job["batches"] >= MAX_BATCHES or now.timestamp() >= job["deadline"]:
            return finish("limited", report)
        if job["stalled_batches"] >= 3:
            return finish("stalled", report)
        retry = max(
            state.get("retry_after", 0),
            report["next_retry"] if not report["ready_events"] else 0,
        )
        if retry > now.timestamp():
            save(state)
            return {
                "status": "running",
                "wait_seconds": min(3600, max(60, math.ceil(retry - now.timestamp()))),
                "reason": "cooldown",
                "turnout": report,
            }
        # Reserve before authentication: crashes and replay never refund allowance.
        job["batches"] += 1
        save(state)
        before = state.get("successful_units", 0)
        try:
            token = Auth(http, parameters, store).access()
            api = Zwift(http, token)
            turnout.populate(api, state, target, now, budget=40)
            if target.get("signatures") or any(
                row.get("name") for row in target.get("turnout", [])
            ):
                backfill.run_batch(api, state, target, now, save, full_scan=True)
        except RateLimited as exc:
            state["retry_after"] = now.timestamp() + exc.seconds
        # Duration transactions may restore a deep-copied checkpoint on interruption.
        job = state["bootstrap"]
        progressed = state.get("successful_units", 0) > before
        if progressed:
            job["stalled_batches"] = 0
        elif state.get("retry_after", 0) <= now.timestamp():
            job["stalled_batches"] += 1
        job["requests"] += 120 - http.remaining
        if progressed:
            state["last_success"] = now.timestamp()
        report = progress(state, target, now)
        result = finish("complete" if done(report) else "running", report)
        return result | {"wait_seconds": 10}
    finally:
        store.release()

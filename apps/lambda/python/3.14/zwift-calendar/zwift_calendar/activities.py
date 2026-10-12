"""Checkpointed private activity discovery and in-memory FIT processing."""

import hashlib
import json
import time

from .errors import BudgetExceeded, ContractError, UpstreamError
from .power import fit_curve, weight

STATE = "power-state.json"


def collect_power(
    api,
    profile,
    previous,
    now,
    *,
    checkpoint=lambda state: None,
    clock=time.monotonic,
    budget=90,
    file_limit=10,
    page_limit=20,
):
    if previous and previous.get("version") != 1:
        raise ContractError("Unknown power cache version")
    state = {
        "version": 1,
        "activities": {
            k: dict(v)
            for k, v in previous.get("activities", {}).items()
            if weight(v["completed"], now)
        },
        "scan": previous.get("scan"),
        "last_complete": previous.get("last_complete"),
    }
    deadline, failures, processed, pages = clock() + budget, 0, 0, 0
    http = getattr(api, "http", None)
    old_deadline = getattr(http, "deadline", None)
    if isinstance(old_deadline, (int, float)):
        http.deadline = min(old_deadline, deadline)

    def check():
        if clock() >= deadline:
            raise BudgetExceeded("Activity collection budget exhausted")

    profile_id = profile.get("fields", {}).get("profile.profileId")
    discovery_complete = False
    try:
        if type(profile_id) is not int:
            raise ContractError("Activity profile unavailable")
        # Offset APIs have no stable cursor. Locate the previous scan's head
        # anchor on every continuation, adjusting for newly inserted activities.
        scan = state["scan"] or {"head": None, "offset": 0, "anchor_offset": 0}
        state["scan"] = scan
        offset, shift = 0, 0
        resume = bool(scan["head"] and scan["offset"])
        if resume:
            offset = scan.get("anchor_offset", 0)
        while pages < page_limit:
            check()
            rows = api.activities(profile_id, offset)
            if not isinstance(rows, list):
                raise ContractError("Invalid activities page")
            pages += 1
            ids = [str(r["id"]) for r in rows]
            for row in rows:
                completed = row.get("endDate")
                if row.get("sport") != "CYCLING" or not completed:
                    continue
                if not weight(completed, now):
                    continue
                identity = str(row["id"])
                # No FIT URLs or raw metadata are persisted. Updated activity
                # metadata invalidates derived data, including previously empty FITs.
                fingerprint = hashlib.sha256(
                    json.dumps(
                        {
                            k: row.get(k)
                            for k in (
                                "endDate",
                                "lastSaveDate",
                                "lastUpdated",
                                "fitFileBucket",
                                "fitFileKey",
                                "distanceInMeters",
                                "durationInMilliseconds",
                            )
                        },
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                cached = state["activities"].get(identity, {})
                if cached.get("fingerprint") != fingerprint:
                    state["activities"][identity] = {
                        "completed": completed,
                        "fingerprint": fingerprint,
                        "pending": True,
                        # Keep supported in-window evidence while a changed file
                        # is queued or failing; report the degraded collection.
                        "curve": cached.get("curve", {}),
                    }
            if not rows:
                discovery_complete = True
                state["scan"] = None
                state["last_complete"] = now.isoformat()
                break
            if resume:
                if scan["head"] in ids:
                    shift = offset + ids.index(scan["head"])
                    offset = max(0, scan["offset"] + shift - 25)
                    resume = False
                    scan["anchor_offset"] = 0
                else:
                    offset += len(rows)
                    scan["anchor_offset"] = max(0, offset - 25)
            else:
                if scan["head"] is None:
                    scan["head"] = ids[0]
                offset += len(rows)
                scan["offset"] = offset - shift
            checkpoint(state)
        # Retry least recently attempted files first; one bad file cannot starve
        # the rest of the window. At most ten downloads, never ten total rides.
        pending = sorted(
            state["activities"].items(),
            key=lambda pair: (pair[1].get("attempted", ""), pair[0]),
        )
        for identity, activity in pending:
            if not activity.get("pending") or processed >= file_limit:
                continue
            check()
            processed += 1
            activity["attempted"] = now.isoformat()
            try:
                raw = api.activity_fit(profile_id, int(identity))
                activity["curve"] = fit_curve(raw, check)
                activity["pending"] = False
                activity.pop("failed", None)
            except BudgetExceeded:
                raise
            except UpstreamError, ContractError:
                failures += 1
                activity["failed"] = True
            checkpoint(state)
    except BudgetExceeded:
        pass
    except UpstreamError, ContractError, KeyError, TypeError, ValueError:
        failures += 1
    finally:
        if isinstance(old_deadline, (int, float)):
            http.deadline = old_deadline
    checkpoint(state)
    pending = sum(a.get("pending", False) for a in state["activities"].values())
    report = {
        "activity_pages": pages,
        "fit_attempts": processed,
        "activity_failures": failures,
        "pending_activities": pending,
        "discovery_complete": discovery_complete,
        "collection_degraded": bool(
            failures or any(a.get("failed") for a in state["activities"].values())
        ),
        "collection_incomplete": not discovery_complete or pending > 0,
        "in_window_activities": len(state["activities"]),
        "confirmed_no_activities": discovery_complete and not state["activities"],
    }
    return state, report

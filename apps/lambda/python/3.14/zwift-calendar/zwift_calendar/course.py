"""Resolve event length without inventing a loop or cancelling climbing."""

import gzip
import json
import math
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def routes():
    with gzip.open(Path(__file__).parent / "data/routes.json.gz", "rt") as handle:
        return json.load(handle)["routes"]


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def resolve(event, catalog=None):
    identity, target, laps, _ = event["signature"]
    route = (routes() if catalog is None else catalog).get(str(identity))
    info = event.get("course", {})
    explicit = positive(target)
    if not explicit and (type(laps) is not int or laps < 0):
        raise ValueError("Invalid lap count")
    if not route:
        if not explicit:
            raise ValueError("Course distance unavailable")
        ascent = info.get("ascent")
        return {
            "segments": [],
            "coarse_distance": target,
            "coarse_ascent": ascent if positive(ascent) else 0,
            "distance": target,
            "course_source": "coarse totals"
            if positive(ascent)
            else "distance only; elevation unavailable",
        }
    lap_distance = route["distance"]
    lead = route.get("lead_distance", 0)
    lead_ascent = route.get("lead_ascent", 0)
    if not explicit:
        if laps > 1 and not route["lap"]:
            raise ValueError("Repeated course is not a verified lap")
        target = lead + lap_distance * max(1, laps)
    if target <= 0 or target > 1000000:
        raise ValueError("Course distance outside model limits")
    if target > lead + lap_distance + 1 and not route["lap"]:
        # A total distance establishes length, but a point-to-point profile
        # cannot establish the continuation's gradients or ascent.
        return {
            "segments": [],
            "coarse_distance": target,
            "coarse_ascent": 0,
            "distance": target,
            "course_source": "distance only; non-loop continuation elevation unavailable",
        }
    profile = route.get("segments")
    # Route IDs encode their normal direction. Explicit reversal needs a
    # verified reversed route ID; an event lead-in cannot simply be reversed.
    if info.get("reverse"):
        profile = None
    if not profile:
        # Totals can be scaled only for complete verified laps. Partial ascent
        # cannot be inferred from a uniform share of the full route ascent.
        whole = max(0, target - lead) / lap_distance
        ascent = (
            lead_ascent + route["ascent"] * round(whole)
            if target >= lead
            and not info.get("reverse")
            and abs(whole - round(whole)) < 0.001
            else None
        )
        return {
            "segments": [],
            "coarse_distance": target,
            "coarse_ascent": ascent or 0,
            "distance": target,
            "course_source": "coarse distance/ascent totals"
            if ascent is not None
            else "distance only; partial-course elevation unavailable",
        }
    lead_used = min(lead, target)
    # Profiles describe the route proper, not the event lead-in. Keep a labelled
    # coarse lead-in once, with full known ascent only when all of it is ridden.
    remaining, segments = target - lead_used, []
    while remaining > 0.001:
        for distance, rise, surface in profile:
            used = min(remaining, distance)
            if used > 0:
                segments.append((used, rise * used / distance, surface))
                remaining -= used
            if remaining <= 0.001:
                break
        if not route["lap"]:
            if remaining > 1:
                raise ValueError("Profile does not cover course")
            break
    return {
        "segments": segments,
        "coarse_distance": lead_used,
        "coarse_ascent": lead_ascent if lead_used == lead else 0,
        "distance": target,
        "course_source": "elevation profile + coarse event lead-in"
        if lead_used
        else "elevation profile",
    }

"""Solve finish time against duration-dependent power; public metadata only."""

import math
import os

from .course import resolve
from .physics import coarse, travel


def reserve(estimate, margin):
    seconds = estimate["seconds"]
    low, high = math.floor(seconds * (1 - margin)), math.ceil(seconds * (1 + margin))
    return estimate | {
        "lower_seconds": low,
        "upper_seconds": high,
        "reserved_seconds": math.ceil(high / 300) * 300,
        "margin": margin,
    }


def margin(wide=False):
    value = float(
        os.environ.get(
            "ZWIFT_WIDE_MARGIN" if wide else "ZWIFT_MEASURED_MARGIN",
            "0.4" if wide else "0.2",
        )
    )
    if not 0 <= value <= 1:
        raise ValueError("Invalid planning margin")
    return value


def unavailable(reason, *, failure=False):
    return {
        "seconds": None,
        "reserved_seconds": None,
        "source": "finish time unavailable: " + reason,
        "category": "start-only",
        "samples": 0,
        "calculation_failed": failure,
    }


def predict(event, curve, body, collection):
    try:
        course = resolve(event)
    except ValueError, TypeError, KeyError:
        return unavailable("course distance or lap configuration unresolved")
    weight, height = body.get("weight_kg"), body.get("height_cm")
    if not (
        type(weight) in (int, float)
        and type(height) in (int, float)
        and 30 <= weight <= 250
        and 100 <= height <= 230
    ):
        return unavailable("current rider dimensions unavailable")

    def time_at(seconds):
        power = curve.watts(seconds)
        return travel(course["segments"], power, weight, height) + coarse(
            course["coarse_distance"], course["coarse_ascent"], power, weight, height
        )

    try:
        lo, hi = 1, 172800
        if time_at(hi) > hi:
            raise ValueError("Outside model duration limit")
        for _ in range(18):
            mid = (lo + hi) / 2
            if time_at(mid) > mid:
                lo = mid
            else:
                hi = mid
        seconds = math.ceil(hi)
        evidence = curve.evidence(seconds)
        source = evidence["power_source"]
        label = (
            "100 W FTP-based default"
            if source == "default"
            else source + " recent riding power"
        )
        wide = (
            source != "measured"
            or evidence["sparse"]
            or course["course_source"] != "elevation profile"
            or collection.get("collection_incomplete")
            or collection.get("collection_degraded")
        )
        return reserve(
            {
                "seconds": seconds,
                "source": label + "; " + course["course_source"],
                "category": source,
                "samples": 0,
                **evidence,
                "course_source": course["course_source"],
                "collection_incomplete": bool(collection.get("collection_incomplete")),
                "collection_degraded": bool(collection.get("collection_degraded")),
                "distance_m": round(course["distance"], 1),
            },
            margin(wide),
        )
    except ValueError, OverflowError, ZeroDivisionError, KeyError:
        return unavailable("course calculation failed", failure=True)

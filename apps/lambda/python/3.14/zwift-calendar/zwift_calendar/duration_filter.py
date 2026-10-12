"""Hide races whose upper planning duration exceeds the rider's time budget."""

MAX_RACE_SECONDS = 150 * 60


def apply(events):
    kept = []
    filtered = {"banded": 0, "unbanded": 0}
    unknown = 0
    for event in events:
        duration = event["duration"]
        upper = duration.get("upper_seconds", duration["seconds"])
        race = event.get("event_kind", "race") == "race"
        if race and upper is not None and upper > MAX_RACE_SECONDS:
            filtered["banded" if event["band"] is not None else "unbanded"] += 1
        else:
            kept.append(event)
            unknown += race and upper is None
    return kept, {
        "maximum_upper_seconds": MAX_RACE_SECONDS,
        "filtered": sum(filtered.values()),
        "filtered_by_calendar": filtered,
        "unknown_races_retained": unknown,
    }

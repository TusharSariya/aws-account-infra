"""Calendar blocks from published durations, never from invented lap speeds."""

from datetime import datetime, timedelta

from .api import ContractError


def positive_minutes(value):
    if type(value) is not int or value <= 0:
        raise ContractError("Invalid published session duration")
    return value


def race_duration(round_, descriptor=None):
    """Prefer the descriptor's whole-session block to the race-only time limit."""
    minutes = (descriptor or {}).get("session_minutes")
    limit = round_.get("race_time_limit")
    if limit is not None:
        positive_minutes(limit)
    if minutes is not None:
        positive_minutes(minutes)
        if limit and not round_.get("race_lap_limit") and minutes < limit:
            raise ContractError("Session duration is shorter than the timed race")
        return {
            "minutes": minutes,
            "source": "race_time_descriptors.session_minutes",
            "kind": "session_time_cap"
            if limit and round_.get("race_lap_limit") and minutes >= limit
            else "session_estimate",
        }
    if limit:
        return {
            "minutes": limit,
            "source": "race_time_limit",
            "kind": "race_time_cap"
            if round_.get("race_lap_limit")
            else "race_time_limit",
        }
    return None


def catalog_duration(entry):
    distance = entry.get("expected_distance")
    if distance and distance["unit"] == "hours":
        return {
            "minutes": positive_minutes(distance["value"] * 60),
            "source": "reviewed_catalog.expected_distance",
            "kind": "race_time_limit",
        }
    return None


def end_time(start, duration):
    if duration is None:
        return None
    return (
        datetime.fromisoformat(start) + timedelta(minutes=duration["minutes"])
    ).isoformat()


def describe(duration):
    minutes = duration["minutes"]
    hours, remainder = divmod(minutes, 60)
    length = " ".join(
        part
        for part in (f"{hours}h" if hours else "", f"{remainder}m" if remainder else "")
        if part
    )
    if duration["kind"] == "session_estimate":
        return (
            f"Calendar block: {length}, using iRacing's published session duration "
            "including session overhead. End time is estimated; actual finish may vary."
        )
    if duration["kind"] == "session_time_cap":
        return (
            f"Calendar block: {length}, using iRacing's published session time cap "
            "including session overhead. This is a maximum planned block, not an "
            "expected finish; the lap limit may end the race much earlier."
        )
    suffix = (
        "The lap limit may end the race much earlier. "
        if duration["kind"] == "race_time_cap"
        else ""
    )
    return (
        f"Calendar block: {length}, using the published race time limit. "
        + suffix
        + "Practice, qualifying and session overhead are not included because a "
        "full session duration is unavailable. Actual finish may vary."
    )

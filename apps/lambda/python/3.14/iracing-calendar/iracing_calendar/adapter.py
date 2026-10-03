"""Normalize observed iRacing schedule contracts without inferring race starts."""

from datetime import UTC, date, datetime, time, timedelta

from .api import ContractError
from .catalog import SOURCE, coverage_report, parse_inventory
from .duration import catalog_duration, end_time, race_duration

PAVED = {"oval", "sports_car", "formula_car"}
API_SOURCE = "https://members-ng.iracing.com/data/series/season_schedule"


def instant(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ContractError("Race start lacks a timezone")
    return result.astimezone(UTC)


def starts(round_, include_repeating=False):
    return sorted(session_blocks(round_, include_repeating))


def session_blocks(round_, include_repeating=False):
    """Keep each start paired with its own descriptor's published duration."""
    lower = datetime.combine(date.fromisoformat(round_["start_date"]), time(), UTC)
    upper = instant(round_["week_end_time"])
    if upper < lower:
        raise ContractError("Invalid round boundaries")
    output = {}
    descriptors = round_["race_time_descriptors"]
    for descriptor in descriptors:
        if descriptor.get("timezone", "UTC") not in ("UTC", "Etc/UTC", "GMT"):
            raise ContractError("Unobserved recurrence timezone; verify API contract")
        if not descriptor["repeating"]:
            values = [instant(t) for t in descriptor["session_times"]]
        elif include_repeating:
            interval = descriptor["repeat_minutes"]
            limit = descriptor["end_offset_minutes"]
            if not isinstance(interval, int) or interval <= 0 or not 0 <= limit <= 1440:
                raise ContractError("Invalid recurrence bounds")
            values = []
            for offset in descriptor["day_offset"]:
                if not isinstance(offset, int) or not 0 <= offset <= 366:
                    raise ContractError("Invalid recurrence day offset")
                day = date.fromisoformat(descriptor["start_date"]) + timedelta(
                    days=offset
                )
                midnight = datetime.combine(day, time(), UTC)
                current = datetime.combine(
                    day, time.fromisoformat(descriptor["first_session_time"]), UTC
                )
                while current <= midnight + timedelta(minutes=limit):
                    if lower <= current <= upper:
                        values.append(current)
                    current += timedelta(minutes=interval)
        else:
            continue
        if any(not lower <= value <= upper for value in values):
            raise ContractError("Explicit race start outside its published round")
        duration = race_duration(round_, descriptor)
        for value in values:
            if value in output and output[value] != duration:
                raise ContractError("Conflicting durations for the same race start")
            output[value] = duration
    return output


def round_key(season, round_):
    return f"api:{season['series_id']}:{season['season_id']}:{round_['race_week_num']}:{'fixed' if season['fixed_setup'] else 'open'}"


def normalize(seasons, catalog, html, now):
    report = coverage_report(catalog, parse_inventory(html, catalog["year"]))
    if report["new"] or report["missing"] or report["disagreements"]:
        raise ContractError(
            "Official catalog changed; run catalog report and review mappings"
        )
    events, coverage = [], set()
    mapped = {}
    observed = set()
    for entry in catalog["events"]:
        for mapping in entry["api_mappings"]:
            key = (mapping["series_id"], mapping["season_id"], mapping["race_week_num"])
            if key in mapped:
                raise ContractError("Ambiguous special-event identity mapping")
            mapped[key] = (entry, mapping)
    seen = set()
    for season in seasons:
        if season["season_id"] in seen:
            raise ContractError("Duplicate API season")
        seen.add(season["season_id"])
        scope = f"api-season:{season['season_id']}"
        coverage.add(scope)
        round_numbers = set()
        for round_ in season["schedules"]:
            if round_["race_week_num"] in round_numbers:
                raise ContractError("Duplicate API round")
            round_numbers.add(round_["race_week_num"])
            if round_["category"] not in PAVED:
                continue
            if (
                round_["season_id"] != season["season_id"]
                or round_["series_id"] != season["series_id"]
            ):
                raise ContractError("API round identity mismatch")
            key = (season["series_id"], season["season_id"], round_["race_week_num"])
            special, mapping = mapped.get(key, (None, None))
            if special:
                if (
                    round_["track"]["track_id"] != mapping["track_id"]
                    or season["fixed_setup"] != mapping["fixed_setup"]
                ):
                    raise ContractError(
                        f"Special track/setup conflict: {special['name']}"
                    )
                if not special["start"] <= round_["start_date"] < special["end"]:
                    raise ContractError(f"Special date conflict: {special['name']}")
                distance = special["expected_distance"]
                if (
                    distance
                    and distance["unit"] == "hours"
                    and round_["race_time_limit"] != distance["value"] * 60
                ):
                    raise ContractError(f"Special duration conflict: {special['name']}")
                observed.add(special["id"])
            sessions = round_.get("event_sessions")
            if sessions is not None and not any(
                s["type_name"] == "Race" for s in sessions
            ):
                continue
            descriptors = round_["race_time_descriptors"]
            irregular = any(not d["repeating"] for d in descriptors)
            if not irregular and not special:
                continue
            if irregular and len(season["schedules"]) == 1 and not special:
                raise ContractError(
                    f"Unreviewed standalone API race identity: {season['season_id']}"
                )
            blocks = session_blocks(round_, include_repeating=bool(special))
            values = sorted(blocks)
            identity = round_key(season, round_)
            track = round_["track"]
            classes = ["irregular"] if irregular else []
            sources = [f"{API_SOURCE}?season_id={season['season_id']}"]
            if special:
                classes.append("special")
                sources += special["source_urls"]
            for tour in catalog.get("full_length_tours", []):
                if (
                    season["season_year"] == tour["year"]
                    and season["series_id"] == tour["series_id"]
                    and round_["category"] in tour["categories"]
                ):
                    classes.append("full_length_tour")
                    sources += tour["source_urls"]
            laps, minutes = round_["race_lap_limit"], round_["race_time_limit"]
            length = (
                f"{laps} laps"
                if laps
                else f"{minutes} minutes"
                if minutes
                else "Unpublished"
            )
            name = round_["series_name"]
            if special and special["name"] not in name:
                name = f"{name} - {special['name']}"
            if season["fixed_setup"] and "Fixed" not in name:
                name += " - Fixed"
            for index, start in enumerate(values or [None]):
                duration = blocks[start] if start else race_duration(round_)
                events.append(
                    {
                        "id": f"{identity}|{index}",
                        "round_id": identity,
                        "api_round_id": identity,
                        "api_identity": {
                            "series_id": season["series_id"],
                            "season_id": season["season_id"],
                            "race_week_num": round_["race_week_num"],
                            "track_id": track["track_id"],
                            "fixed_setup": season["fixed_setup"],
                        },
                        "coverage": scope,
                        "name": name,
                        "track": track["track_name"]
                        + (
                            " - " + track["config_name"]
                            if track.get("config_name")
                            else ""
                        ),
                        "start": start.isoformat() if start else round_["start_date"],
                        "duration": duration,
                        "end": end_time(start.isoformat(), duration)
                        if start
                        else (
                            instant(round_["week_end_time"]).date() + timedelta(days=1)
                        ).isoformat(),
                        "all_day": start is None,
                        "length": length,
                        "cars": ", ".join(
                            str(x) for x in season.get("car_class_ids", [])
                        ),
                        "eligibility": f"License group {season.get('license_group', 'unpublished')}",
                        "description": "Published race-session start; includes any attached practice/qualifying. "
                        + ("Fixed setup." if season["fixed_setup"] else "Open setup."),
                        "classification": classes,
                        "sources": sorted(set(sources)),
                        "provenance": {
                            "starts": "race_time_descriptors",
                            "special_id": special["id"] if special else None,
                        },
                    }
                )
    report["unresolved"] = []
    report["unpublished_api"] = []
    report["undated"] = []
    for entry in catalog["events"]:
        if entry["discipline"] not in {"Oval", "Sports Car", "Formula Car"}:
            continue
        coverage.add(f"special:{catalog['year']}")
        if entry["id"] in observed:
            continue
        if entry["api_mappings"]:
            raise ContractError(
                f"Mapped special absent from API coverage: {entry['name']}"
            )
        report["unpublished_api"].append(entry["name"])
        if not entry["start"]:
            report["undated"].append(entry["name"])
            continue
        identity = "special:" + entry["id"]
        events.append(
            {
                "id": identity + "|0",
                "round_id": identity,
                "coverage": f"special:{catalog['year']}",
                "name": entry["name"],
                "track": entry["track"] or "Track unpublished",
                "start": entry["start"],
                "end": entry["end"],
                "all_day": True,
                "duration": catalog_duration(entry),
                "length": "Unpublished",
                "cars": "",
                "eligibility": "",
                "description": "Official date confirmed; API race schedule not yet published.",
                "classification": ["special"],
                "sources": entry["source_urls"],
                "provenance": {"starts": None, "special_id": entry["id"]},
            }
        )
    report["publication_ready"] = True
    report["inclusion_reasons"] = {
        kind: sum(kind in e["classification"] for e in events)
        for kind in ["irregular", "special", "full_length_tour"]
    }
    return events, sorted(coverage), report


def extract(api, catalog, fetch, now, previous=None):
    active = api.get("series/seasons", include_series="true")
    if not isinstance(active, list) or not active:
        raise ContractError("Active season inventory missing")
    seasons = {s["season_id"]: s for s in active}
    required = {m["season_id"] for e in catalog["events"] for m in e["api_mappings"]}
    required.update(
        e["api_identity"]["season_id"]
        for e in (previous or {}).get("events", [])
        if e.get("api_identity")
    )
    archive = api.get("series/stats_series")
    metadata = {s["season_id"]: s for series in archive for s in series["seasons"]}
    # Completed annual tours can still have rounds inside the retention window.
    required.update(
        s["season_id"]
        for s in metadata.values()
        if s["season_year"] == now.year
        and s.get("season_short_name") == f"{now.year} Season"
    )
    for season_id in sorted(required - seasons.keys()):
        if season_id not in metadata:
            raise ContractError(f"Published season identity disappeared: {season_id}")
        response = api.get("series/season_schedule", season_id=season_id)
        if response.get("success") is not True or response["season_id"] != season_id:
            raise ContractError("Incomplete season schedule response")
        seasons[season_id] = metadata[season_id] | {"schedules": response["schedules"]}
    from .announcements import supplement

    events, coverage, report = normalize(
        list(seasons.values()), catalog, fetch.get(SOURCE), now
    )
    report["announcements"] = supplement(events, catalog, fetch, now)
    return events, coverage, report

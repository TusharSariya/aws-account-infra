"""Persist reviewed legacy round identities and expose every preview difference."""

import json
from pathlib import Path

from .api import ContractError


def migrate(previous, incoming, coverage):
    reviewed = json.loads(
        Path(__file__).with_name("catalogs").joinpath("migration.json").read_text()
    )
    mapping = reviewed["round_ids"] | previous.get("uid_migration", {})
    old = previous.get("events", [])
    unknown = {
        e["round_id"]
        for e in old
        if not e.get("api_identity") and e["coverage"] in reviewed["legacy_coverage"]
    } - set(mapping.values())
    if unknown:
        raise ContractError(
            "Unreviewed legacy identities; regenerate migration preview: "
            + ", ".join(sorted(unknown))
        )
    # A catalog date placeholder becoming a verified API race keeps its UID.
    placeholders = {
        e.get("provenance", {}).get("special_id"): e["round_id"]
        for e in old
        if e["all_day"] and e.get("provenance", {}).get("special_id")
    }
    for event in sorted(incoming, key=lambda e: e["start"]):
        special = event.get("provenance", {}).get("special_id")
        if (
            special in placeholders
            and event.get("api_identity")
            and event["round_id"] not in mapping
        ):
            legacy = placeholders.pop(special)
            if legacy not in mapping.values():
                mapping[event["round_id"]] = legacy
    output = [
        e | {"round_id": mapping.get(e["round_id"], e["round_id"])} for e in incoming
    ]
    return output, sorted(set(coverage) | set(reviewed["legacy_coverage"])), mapping


def differences(previous, result):
    old = {e["id"]: e for e in previous.get("events", [])}
    new = {e["id"]: e for e in result["events"]}
    return {
        "added": [
            {"id": key, "name": new[key]["name"], "start": new[key]["start"]}
            for key in sorted(new.keys() - old.keys())
        ],
        "removed": [
            {"id": key, "name": old[key]["name"], "start": old[key]["start"]}
            for key in sorted(old.keys() - new.keys())
        ],
        "name_changes": [
            {"id": key, "before": old[key]["name"], "after": new[key]["name"]}
            for key in sorted(new.keys() & old.keys())
            if old[key]["name"] != new[key]["name"]
        ],
        "start_changes": [
            {
                "id": key,
                "name": new[key]["name"],
                "before": old[key]["start"],
                "after": new[key]["start"],
            }
            for key in sorted(new.keys() & old.keys())
            if new[key]["start"] != old[key]["start"]
        ],
        "end_changes": [
            {
                "id": key,
                "name": new[key]["name"],
                "before": old[key].get("end"),
                "after": new[key].get("end"),
                "duration": new[key].get("duration"),
            }
            for key in sorted(new.keys() & old.keys())
            if new[key].get("end") != old[key].get("end")
        ],
    }

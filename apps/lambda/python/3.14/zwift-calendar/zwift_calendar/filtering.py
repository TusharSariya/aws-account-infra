"""Select one advertised score band per public race, at its own start time."""

import math
import re
from collections import Counter
from datetime import timedelta

from .api import instant
from .errors import ContractError, UnsupportedRule
from .rules import evaluate, parse

BAND = re.compile(r"^(\d{1,4})\s*[-–]\s*(\d{1,4})$")
TYPES = {"RACE", "TIME_TRIAL"}


def signature(event, group):
    return [
        group.get("routeId", event.get("routeId")),
        group.get("distanceInMeters", 0),
        group.get("laps", 0),
        event["eventType"],
    ]


def select(events, profile, now):
    output, excluded = [], Counter()
    for event in events:
        if event.get("sport") != "CYCLING" or event.get("eventType") not in TYPES:
            excluded["not_individual_cycling_race"] += 1
            continue
        if (
            event.get("privateEvent")
            or event.get("unlisted")
            or event.get("restricted")
            or event.get("eventSecret")
            or event.get("type") == "EVENT_TYPE_TEAM_TIME_TRIAL"
        ):
            excluded["restricted"] += 1
            continue
        tt_options = event.get("timeTrialOptions") or {}
        if not isinstance(tt_options, dict) or tt_options.get("teamTimeTrial"):
            excluded["not_individual_cycling_race"] += 1
            continue
        groups = event.get("eventSubgroups")
        if not isinstance(groups, list) or not groups:
            raise ContractError("Race subgroups missing")
        expression = event.get("accessExpression")
        try:
            tree = parse(expression)
        except UnsupportedRule:
            excluded["unsupported_rule"] += 1
            continue
        metric = "max30" if "scoring.max30" in expression else "current"
        score = profile.get(metric)
        provisional = (
            score is None
            and profile.get("current") is None
            and profile.get("max30") is None
        )
        if provisional:
            score = 100
        if score is None:
            excluded["required_score_missing"] += 1
            continue
        candidates = []
        for group in groups:
            if not isinstance(group, dict) or type(group.get("id")) is not int:
                raise ContractError("Invalid subgroup identity")
            band = BAND.fullmatch(group.get("rangeAccessLabel") or "")
            if not band:
                continue
            lower, upper = map(int, band.groups())
            if not 0 <= lower < upper <= 1000:
                excluded["invalid_score_band"] += 1
                continue
            # Display labels have adjoining endpoints. Entry expressions resolve
            # inclusive/exclusive boundaries; prefer the lower band if both allow.
            if not lower <= score <= upper:
                continue
            values = profile["fields"] | {
                "subgroup.label": group.get("label"),
                "scoring.current": 100 if provisional else profile.get("current"),
                "scoring.max30": 100 if provisional else profile.get("max30"),
            }
            rules = set(event.get("rulesSet", [])) | set(group.get("rulesSet", []))
            if {"LADIES_ONLY", "WOMEN_ONLY"} & rules and values.get(
                "profile.male"
            ) is not False:
                continue
            if "MEN_ONLY" in rules and values.get("profile.male") is not True:
                continue
            access_rules = group.get("accessRules") or []
            if not isinstance(access_rules, list) or any(
                rule != {"name": "scored.race", "result": True} for rule in access_rules
            ):
                excluded["unsupported_group_rules"] += 1
                continue
            if group.get("accessValidationResult") is False:
                excluded["upstream_ineligible"] += 1
                continue
            try:
                allowed = evaluate(tree, values) is True
            except UnsupportedRule:
                excluded["unsupported_rule"] += 1
                continue
            if not allowed:
                continue
            start = instant(group.get("eventSubgroupStart"))
            if not now <= start < now + timedelta(days=14):
                continue
            duration = group.get("durationInSeconds", 0)
            if (
                type(duration) not in (int, float)
                or not math.isfinite(duration)
                or not 0 <= duration <= 86400
            ):
                raise ContractError("Invalid published duration")
            sig = signature(event, group)
            candidates.append(
                (
                    upper,
                    upper - lower,
                    group["id"],
                    {
                        "id": f"{event['id']}-{group['id']}",
                        "event_id": event["id"],
                        "subgroup_id": group["id"],
                        "name": event["name"],
                        "group": group.get("subgroupLabel", str(group["label"])),
                        "band": f"{lower}-{upper}",
                        "start": start.isoformat(),
                        "published_seconds": duration,
                        "signature": sig,
                        "requirements": sorted(rules),
                        "provisional": provisional,
                        "time_trial": event["eventType"] == "TIME_TRIAL",
                        "url": f"https://www.zwift.com/events/view/{event['id']}",
                    },
                )
            )
        if candidates:
            output.append(min(candidates, key=lambda c: c[:3])[3])
        else:
            excluded["no_matching_group"] += 1
    return output, dict(excluded)

"""Select eligible races and the shortest recognized special-event rides."""

import math
import re
from collections import Counter
from datetime import timedelta
from zoneinfo import ZoneInfo

from .api import instant
from .campaigns import EXCLUDED_CAMPAIGNS, campaign
from .errors import ContractError, UnsupportedRule
from .rules import evaluate, parse
from .turnout import division

BAND = re.compile(r"^(\d{1,4})\s*[-–]\s*(\d{1,4})(?: Max)?$")
TYPES = {"RACE", "TIME_TRIAL"}
RIDING_TIMEZONE = ZoneInfo("America/St_Johns")


def within_riding_hours(start):
    return 6 <= start.astimezone(RIDING_TIMEZONE).hour < 23


def signature(event, group):
    return [
        group.get("routeId", event.get("routeId")),
        group.get("distanceInMeters", 0),
        group.get("laps", 0),
        event["eventType"],
    ]


def eligibility(event, group, values, *, banded):
    """Use local rules for bands; authenticated server verdicts for legacy categories."""
    verdict = group.get("accessValidationResult")
    if verdict is not None and type(verdict) is not bool:
        raise UnsupportedRule("Invalid upstream eligibility verdict")
    if verdict is False:
        return False
    rules = group.get("accessRules")
    rules = [] if rules is None else rules
    if not isinstance(rules, list):
        raise UnsupportedRule("Invalid subgroup access rules")
    if any(
        not isinstance(rule, dict) or rule.get("result") is not True for rule in rules
    ):
        raise UnsupportedRule("Unresolved subgroup access rules")
    if not banded and verdict is True:
        # The authenticated feed evaluates powerCurves/category/age constraints
        # against this account. Never infer a legacy category from Racing Score.
        return True
    if any(rule != {"name": "scored.race", "result": True} for rule in rules):
        raise UnsupportedRule("Unsupported subgroup access rules")
    expression = event.get("accessExpression")
    if not expression or (isinstance(expression, str) and not expression.strip()):
        if banded or rules or event.get("categoryEnforcement"):
            raise UnsupportedRule("Missing eligibility expression")
        return True
    return evaluate(parse(expression), values) is True


def shortest(candidates):
    """Compare published distances/times, then explicit Short labels; never lap counts across routes."""
    if len(candidates) <= 1:
        return candidates
    if all(row["signature"][1] > 0 for row in candidates):
        return [min(candidates, key=lambda r: (r["signature"][1], r["subgroup_id"]))]
    if all(row["published_seconds"] > 0 for row in candidates):
        return [
            min(candidates, key=lambda r: (r["published_seconds"], r["subgroup_id"]))
        ]
    labels = [
        re.match(r"^(short|standard|long)\b", r["group_name"], re.IGNORECASE)
        for r in candidates
    ]
    if all(labels):
        rank = {"short": 0, "standard": 1, "long": 2}
        return [
            min(
                zip(candidates, labels, strict=True),
                key=lambda pair: (rank[pair[1][1].lower()], pair[0]["subgroup_id"]),
            )[0]
        ]
    # Unknown length is not permission to silently choose an arbitrary route.
    return []


def select(events, profile, now):
    output, excluded = [], Counter()
    for event in events:
        special = campaign(event)
        if special in EXCLUDED_CAMPAIGNS:
            excluded["excluded_campaign"] += 1
            continue
        ride = event.get("eventType") == "GROUP_RIDE" and special is not None
        if event.get("sport") != "CYCLING" or (
            event.get("eventType") not in TYPES and not ride
        ):
            excluded["outside_event_scope"] += 1
            continue
        if (
            event.get("privateEvent")
            or event.get("unlisted")
            or event.get("restricted")
            or event.get("eventSecret")
            or event.get("visible") is False
            or event.get("type") == "EVENT_TYPE_TEAM_TIME_TRIAL"
        ):
            excluded["restricted"] += 1
            continue
        tt_options = event.get("timeTrialOptions") or {}
        if not isinstance(tt_options, dict) or tt_options.get("teamTimeTrial"):
            excluded["outside_event_scope"] += 1
            continue
        groups = event.get("eventSubgroups")
        if not isinstance(groups, list) or not groups:
            raise ContractError("Event subgroups missing")
        expression = event.get("accessExpression")
        expression = "" if expression is None else expression
        if not isinstance(expression, str):
            excluded["unsupported_rule"] += 1
            continue
        metric = "max30" if "scoring.max30" in expression else "current"
        score = profile.get(metric)
        provisional = profile.get("current") is None and profile.get("max30") is None
        if provisional:
            score = 100
        candidates = []
        for group in groups:
            if not isinstance(group, dict) or type(group.get("id")) is not int:
                raise ContractError("Invalid subgroup identity")
            start = instant(group.get("eventSubgroupStart"))
            if not now <= start < now + timedelta(days=14):
                continue
            if not within_riding_hours(start):
                excluded["outside_riding_hours"] += 1
                continue
            raw_band = group.get("rangeAccessLabel")
            band = BAND.fullmatch(raw_band) if isinstance(raw_band, str) else None
            lower = upper = None
            if raw_band is not None and raw_band != "":
                if not band:
                    excluded["invalid_score_band"] += 1
                    continue
                lower, upper = map(int, band.groups())
                if not 0 <= lower < upper <= 1000:
                    excluded["invalid_score_band"] += 1
                    continue
                if raw_band.endswith(" Max") and metric != "max30":
                    excluded["unsupported_rule"] += 1
                    continue
                if score is None or not lower <= score <= upper:
                    continue
            values = profile["fields"] | {
                "subgroup.label": group.get("label"),
                "scoring.current": 100 if provisional else profile.get("current"),
                "scoring.max30": 100 if provisional else profile.get("max30"),
            }
            rules = set(event.get("rulesSet") or []) | set(group.get("rulesSet") or [])
            if {"LADIES_ONLY", "WOMEN_ONLY"} & rules and values.get(
                "profile.male"
            ) is not False:
                continue
            if "MEN_ONLY" in rules and values.get("profile.male") is not True:
                continue
            try:
                allowed = eligibility(event, group, values, banded=band is not None)
            except UnsupportedRule:
                excluded["unsupported_rule"] += 1
                continue
            if not allowed:
                continue
            duration = group.get("durationInSeconds", 0)
            if (
                type(duration) not in (int, float)
                or not math.isfinite(duration)
                or not 0 <= duration <= 86400
            ):
                raise ContractError("Invalid published duration")
            pace = group.get("toPaceValue")
            pace = (
                pace
                if type(pace) in (int, float) and math.isfinite(pace) and pace > 0
                else None
            )
            candidates.append(
                {
                    "id": f"{event['id']}-{group['id']}",
                    "event_id": event["id"],
                    "parent_id": event.get("parentId"),
                    "turnout_division": division(group),
                    "subgroup_id": group["id"],
                    "name": event["name"],
                    "group": group.get("subgroupLabel") or str(group.get("label", "")),
                    "group_name": group.get("name") or "",
                    "band": f"{lower}-{upper}" if band else None,
                    "start": start.isoformat(),
                    "published_seconds": duration,
                    "signature": signature(event, group),
                    "course": {
                        "ascent": group.get(
                            "elevationGainInMeters", event.get("elevationGainInMeters")
                        ),
                        "reverse": group.get(
                            "routeReverse", event.get("routeReverse", False)
                        ),
                    },
                    "requirements": sorted(rules),
                    "provisional": provisional and band is not None,
                    "time_trial": event["eventType"] == "TIME_TRIAL",
                    "special_event": special,
                    "event_kind": "special_ride" if ride else "race",
                    "score_basis": metric if band else None,
                    "advertised_pace_upper": pace,
                    "url": f"https://www.zwift.com/events/view/{event['id']}",
                }
            )
        if ride and candidates:
            chosen = shortest(candidates)
            if not chosen:
                excluded["shortest_route_unknown"] += 1
            output.extend(chosen)
        elif candidates:
            banded = [r for r in candidates if r["band"]]
            if banded:

                def band_order(row):
                    lo, hi = map(int, row["band"].split("-"))
                    return hi, hi - lo, row["subgroup_id"]

                output.append(min(banded, key=band_order))
            else:
                # Prefer the lowest advertised pace among eligible legacy/open
                # groups. No pace is an unknown difficulty, not zero watts/kg.
                output.append(
                    min(
                        candidates,
                        key=lambda r: (
                            r["advertised_pace_upper"] or math.inf,
                            r["subgroup_id"],
                        ),
                    )
                )
        else:
            excluded["no_matching_group"] += 1
    return output, dict(excluded)

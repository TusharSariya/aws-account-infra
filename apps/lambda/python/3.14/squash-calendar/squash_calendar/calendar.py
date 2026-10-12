"""Whole-season events, immutable pre-match previews, and RFC 5545 output."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from squash_calendar.model import VERSION, fit, probability
from squash_calendar.source import season

ZONE = ZoneInfo("America/St_Johns")


def start_time(fixture, manifest):
    return datetime.fromisoformat(f"{fixture['date']}T{manifest['time']}").replace(
        tzinfo=ZONE
    )


def player_matches(data, pid):
    return sorted(
        [m for m in data["matches"] if pid in (m["home"], m["away"])],
        key=lambda m: (m["date"], m["id"]),
        reverse=True,
    )


def result_line(m, pid, names):
    opponent = m["away"] if m["home"] == pid else m["home"]
    games = m["games"] if m["home"] == pid else [(b, a) for a, b in m["games"]]
    score = ", ".join(f"{a}-{b}" for a, b in games)
    return f"{m['date']} {'W' if m['winner'] == pid else 'L'} vs {names.get(opponent, 'Player ' + opponent)}: {score}"


def preview(data, pid, opponent, model):
    names = data["names"]
    mine, theirs = player_matches(data, pid), player_matches(data, opponent)
    h2h = [m for m in mine if opponent in (m["home"], m["away"])]
    won = sum(m["winner"] == pid for m in h2h)
    details = [f"Accessible head-to-head: {won} wins, {len(h2h) - won} losses."]
    details += [result_line(m, pid, names) for m in h2h[:5]]
    for who, matches in ((pid, mine), (opponent, theirs)):
        details += [
            f"Last {min(5, len(matches))} accessible completed matches - {names.get(who, who)}:"
        ]
        details += [result_line(m, who, names) for m in matches[:5]] or [
            "No accessible completed matches."
        ]

    def latest(matches, who):
        result = {}
        for m in matches:
            other = m["away"] if m["home"] == who else m["home"]
            result.setdefault(other, m)
        return result

    a, b = latest(mine, pid), latest(theirs, opponent)
    common = sorted(
        set(a) & set(b),
        key=lambda p: (min(a[p]["date"], b[p]["date"]), p),
        reverse=True,
    )[:3]
    details += ["Recent common opponents (latest result per player):"]
    for p in common:
        details += [
            f"{names.get(pid, pid)}: {result_line(a[p], pid, names)}",
            f"{names.get(opponent, opponent)}: {result_line(b[p], opponent, names)}",
        ]
    if not common:
        details += ["No accessible common-opponent results."]
    p = probability(model, pid, opponent)
    return {
        "as_of": data["as_of"],
        "ratings": {
            pid: data["ratings"].get(pid),
            opponent: data["ratings"].get(opponent),
        },
        "probability": round(p * 100) if p is not None else None,
        "details": "\n".join(details),
        "backtest": data.get("backtest", {}),
        "coverage": data["coverage"],
    }


def reconcile(old, data, now, manifest=None):
    manifest = manifest or season()
    events = deepcopy(old)
    model = fit(data["matches"], now.astimezone(ZONE).date()) if data else None
    active = set()
    for fixture in manifest["fixtures"]:
        key, pid, opp = fixture["id"], manifest["player"], fixture["opponent"]
        active.add(key)
        previous = old.get(key, {})
        start = start_time(fixture, manifest)
        prior_preview = previous.get("preview")
        # A changed opponent/date is a changed match context; don't reuse another preview.
        same_context = previous.get("fixture") == fixture
        if now < start:
            pre = (
                preview(data, pid, opp, model)
                if data
                else (prior_preview if same_context else None)
            )
        else:
            pre = (
                prior_preview
                if same_context
                and prior_preview
                and datetime.fromisoformat(prior_preview["as_of"]) < start
                else None
            )
        exact = [
            m
            for m in (data or {}).get("matches", [])
            if m["date"] == fixture["date"]
            and m["division"] == manifest["division"]
            and {m["home"], m["away"]} == {pid, opp}
        ]
        result = (
            result_line(exact[0], pid, data["names"])
            if len(exact) == 1
            else previous.get("result")
            if data is None and same_context
            else None
        )
        item = {
            "fixture": deepcopy(fixture),
            "start": start.isoformat(),
            "end": (
                start + timedelta(minutes=manifest["duration_minutes"])
            ).isoformat(),
            "opponent_name": manifest["players"][opp]["name"],
            "preview": pre,
            "result": result,
            "status": "CONFIRMED",
            "source": manifest["source"],
        }
        content = json.dumps(item, sort_keys=True)
        digest = hashlib.sha256(content.encode()).hexdigest()
        changed = previous.get("digest") != digest
        item.update(
            digest=digest,
            sequence=previous.get("sequence", -1) + int(changed),
            modified=now.isoformat() if changed else previous["modified"],
        )
        events[key] = item
    for key in set(old) - active:
        if events[key]["status"] != "CANCELLED":
            events[key].update(
                status="CANCELLED",
                digest=None,
                sequence=events[key]["sequence"] + 1,
                modified=now.isoformat(),
            )
    return events


def description(item, now):
    fixture, pre = item["fixture"], item["preview"]
    started = now >= datetime.fromisoformat(item["start"])
    lines = [
        "ASC Fall 2026 - Tuesday Division, Team 2, position 6.",
        "6:30-7:00 p.m. Newfoundland time. PDF fixture is authoritative.",
        f"Schedule source: {item['source']['filename']} (pages 1-2)",
        f"Source SHA-256: {item['source']['sha256']}",
    ]
    if pre:
        stale = min(
            now, datetime.fromisoformat(item["start"])
        ) - datetime.fromisoformat(pre["as_of"]) > timedelta(hours=48)
        lines += [
            f"{'Frozen pre-match preview' if started else 'Preview'} as of {pre['as_of']}."
        ]
        for pid, value in pre["ratings"].items():
            name = "Tushar Sariya" if pid == "491725" else item["opponent_name"]
            lines += [
                f"{name} - official Universal Squash Rating: {value:.2f}"
                + (" (stale)" if stale else "")
                if value is not None
                else f"{name} - official Universal Squash Rating unavailable."
            ]
        if stale:
            lines += [
                "Enrichment is over 48 hours old; win estimate suppressed until refresh."
            ]
        elif pre["probability"] is None:
            lines += ["Insufficient accessible history for an estimate."]
        else:
            lines += [
                f"Own model estimate: Tushar {pre['probability']}% / {item['opponent_name']} {100 - pre['probability']}%."
            ]
        lines += [
            f"Model: {VERSION}. At least 5 matches each and a connected match graph required.",
            "Indicative estimate, not an official rating or calibrated betting odds.",
            pre["details"],
            pre["coverage"],
        ]
        test = pre["backtest"]
        if test.get("sample_count"):
            lines += [
                f"Chronological backtest: Brier {test['brier']:.3f}, n={test['sample_count']} (lower is better; no same-day training)."
            ]
    elif started:
        lines += [
            "No pre-match preview was captured before this match. No retrospective win estimate generated."
        ]
    else:
        lines += ["Club Locker enrichment unavailable; scheduled fixture preserved."]
    if item["result"]:
        lines += ["Verified matching result: " + item["result"]]
    elif started:
        lines += [
            "No uniquely matching result verified for this PDF fixture; substitute results are not attached."
        ]
    lines += [
        "Sources:",
        "https://clublocker.com/divisions/6498/schedule",
        "https://clublocker.com/users/491725/home",
        f"https://clublocker.com/users/{fixture['opponent']}/home",
    ]
    return "\n".join(lines)


def render(events, now):
    calendar = Calendar()
    calendar.add("prodid", "-//ASC Personal Squash Calendar//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", "Tushar — ASC Squash")
    calendar.add("x-wr-timezone", "America/St_Johns")
    for key, item in sorted(events.items()):
        event = Event()
        event.add("uid", key + "@squash-calendar")
        for field, value in (
            ("dtstart", item["start"]),
            ("dtend", item["end"]),
            ("dtstamp", item["modified"]),
            ("last-modified", item["modified"]),
        ):
            event.add(field, datetime.fromisoformat(value).astimezone(UTC))
        event.add("sequence", item["sequence"])
        event.add(
            "summary",
            f"Squash vs {item['opponent_name']} - Court {item['fixture']['court']}",
        )
        event.add("location", f"Avalon Squash Club - Court {item['fixture']['court']}")
        event.add("description", description(item, now))
        event.add("status", item["status"])
        event.add("transp", "OPAQUE")
        event.add("url", "https://clublocker.com/divisions/6498/schedule")
        calendar.add_component(event)
    return calendar.to_ical().decode()

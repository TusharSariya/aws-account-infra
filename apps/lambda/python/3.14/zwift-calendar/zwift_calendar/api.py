"""Observed public events and authenticated score/result contracts."""

import math
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from .errors import AuthenticationError, ContractError
from .transport import API


def instant(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except ValueError, TypeError:
        raise ContractError("Invalid upstream timestamp") from None


def score_value(data):
    if not isinstance(data, dict) or not isinstance(data.get("scores"), dict):
        raise ContractError("Invalid score response")
    score = data["scores"].get("ZWIFT_PUBLIC_SCORE")
    if score is None:
        return None
    if not isinstance(score, dict) or "value" not in score:
        raise ContractError("Invalid score entry")
    value = score["value"]
    if value is None:
        return None
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not 0 <= value <= 1000
    ):
        raise ContractError("Invalid score value")
    return value


class Zwift:
    def __init__(self, transport, token=None):
        self.http, self.token = transport, token

    def get(self, path, *, authenticated=False):
        return self.http.request(
            API + path, token=self.token if authenticated else None
        )

    def profile(self, now):
        data = self.get("profiles/me", authenticated=True)
        if (
            not isinstance(data, dict)
            or type(data.get("id")) is not int
            or type(data.get("male")) is not bool
        ):
            raise ContractError("Invalid account profile")
        current = score_value(self.get("scoring/current", authenticated=True))
        maximum = score_value(self.get("scoring/max30", authenticated=True))
        if current is not None and maximum is not None and maximum < current:
            raise ContractError("Inconsistent current and maximum scores")
        return {
            "current": current,
            "max30": maximum,
            "retrieved_at": now.timestamp(),
            "fields": {
                "profile.profileId": data["id"],
                "profile.male": data["male"],
                "profile.playerType": data.get("playerType"),
                "profile.age": data.get("age"),
            },
        }

    def upcoming(self, until):
        if not self.token:
            raise AuthenticationError(
                "Complete event discovery requires authentication"
            )
        output, cursors = {}, set()
        query = {
            "from": int((until - timedelta(days=14)).timestamp() * 1000),
            "limit": 50,
        }
        for _ in range(400):
            page = self.get("event-feed?" + urlencode(query), authenticated=True)
            if (
                not isinstance(page, dict)
                or not isinstance(page.get("data"), list)
                or "cursor" not in page
            ):
                raise ContractError("Invalid event-feed page")
            for entry in page["data"]:
                row = entry.get("event") if isinstance(entry, dict) else None
                if not isinstance(row, dict) or type(row.get("id")) is not int:
                    raise ContractError("Invalid event identity")
                instant(row.get("eventStart"))
                # The live feed overlaps pages as its inventory changes. Keep
                # the latest observation; opaque cursor repetition still fails.
                output[row["id"]] = row
            cursor = page["cursor"]
            if not cursor:
                return list(output.values())
            if (
                not isinstance(cursor, str)
                or len(cursor) > 2048
                or cursor in cursors
                or not page["data"]
            ):
                raise ContractError("Invalid event-feed cursor")
            cursors.add(cursor)
            query = {"cursor": cursor, "limit": 50}
        raise ContractError("Event pagination limit reached")

    def history_page(self, since, cursor=None):
        query = (
            {"cursor": cursor, "limit": 50}
            if cursor
            else {"from": int(since.timestamp() * 1000), "limit": 50}
        )
        data = self.get("event-feed?" + urlencode(query), authenticated=True)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("data"), list)
            or "cursor" not in data
        ):
            raise ContractError("Invalid historical page")
        rows = []
        for item in data["data"]:
            event = item.get("event") if isinstance(item, dict) else None
            if not isinstance(event, dict) or type(event.get("id")) is not int:
                raise ContractError("Invalid historical identity")
            instant(event.get("eventStart"))
            rows.append(event)
        next_cursor = data["cursor"]
        if next_cursor and (
            not isinstance(next_cursor, str)
            or len(next_cursor) > 2048
            or not rows
            or next_cursor == cursor
        ):
            raise ContractError("Invalid historical cursor")
        return rows, next_cursor or None

    def event(self, event_id):
        if type(event_id) is not int or event_id <= 0:
            raise ContractError("Invalid historical event identity")
        data = self.get(f"public/events/{event_id}")
        if not isinstance(data, dict) or data.get("id") != event_id:
            raise ContractError("Historical event identity mismatch")
        return data

    def results(self, subgroup_id):
        data = self.get(
            f"race-results/summary?event_subgroup_id={int(subgroup_id)}",
            authenticated=True,
        )
        if not isinstance(data, dict) or not isinstance(
            data.get("firstEntries", []), list
        ):
            raise ContractError("Invalid race results response")
        return data.get("firstEntries", [])

    def finisher_count(self, subgroup_id):
        """Count qualified finishers only after reaching an empty results page."""
        seen, count = set(), 0
        for start in range(0, 2500, 25):
            data = self.get(
                "race-results/entries?"
                + urlencode(
                    {"event_subgroup_id": subgroup_id, "start": start, "limit": 25}
                ),
                authenticated=True,
            )
            rows = data.get("entries") if isinstance(data, dict) else None
            if not isinstance(rows, list) or len(rows) > 25:
                raise ContractError("Invalid complete results page")
            if not rows:
                return count
            for row in rows:
                if not isinstance(row, dict) or type(row.get("profileId")) is not int:
                    raise ContractError("Invalid finisher identity")
                identity = row["profileId"]
                if identity in seen or row.get("eventSubgroupId") != subgroup_id:
                    raise ContractError("Repeated or mismatched finisher")
                seen.add(identity)
                elapsed = (row.get("activityData") or {}).get("durationInMilliseconds")
                if (
                    type(row.get("qualified")) is not bool
                    or type(row.get("rank")) is not int
                ):
                    raise ContractError("Invalid finisher status")
                if row["qualified"] and (
                    type(elapsed) not in (int, float) or not math.isfinite(elapsed)
                ):
                    raise ContractError("Invalid finisher duration")
                if (
                    row.get("qualified") is True
                    and type(row.get("rank")) is int
                    and row["rank"] > 0
                    and type(elapsed) in (int, float)
                    and math.isfinite(elapsed)
                    and elapsed > 0
                    and not row.get("flaggedCheating")
                    and not row.get("flaggedSandbagging")
                ):
                    count += 1
        raise ContractError("Complete results pagination limit reached")

"""Allowlisted public Club Locker reads; no profile-history entitlement bypass."""

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from importlib.resources import files

import httpx

BASE = "https://api.ussquash.com/resources/"


class SourceError(Exception):
    """Safe operational failure without response bodies or credentials."""


def season():
    return json.loads(files("squash_calendar").joinpath("season.json").read_text())


def match_date(value):
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError, TypeError:
            continue
    raise SourceError("Invalid match date")


def normalize(row, card):
    """Scorecard wid1/oid1 and wset/oset are winner/loser oriented.

    The separate profile endpoint uses home/visitor IDs with winner-first scores.
    Normalize each contract independently; H/V only identifies the winning team here."""
    if (
        row.get("status") != "C"
        or row.get("SportID") != 3
        or row.get("EventName") != "Singles"
        or row.get("winner") not in ("H", "V")
        or row.get("wid2")
        or row.get("oid2")
    ):
        return None
    home, away = str(row.get("wid1") or ""), str(row.get("oid1") or "")
    if not home or not away or home == away or home == "0" or away == "0":
        return None
    games = []
    for i in range(1, 6):
        a, b = row.get(f"wset{i}") or 0, row.get(f"oset{i}") or 0
        if not isinstance(a, int) or not isinstance(b, int) or a < 0 or b < 0:
            return None
        if a or b:
            # Completed best-of-five games; reject defaults/retirements and partials.
            if max(a, b) < 11 or abs(a - b) < 2 or (max(a, b) > 11 and abs(a - b) != 2):
                return None
            games.append((a, b))
    wins = sum(a > b for a, b in games)
    losses = len(games) - wins
    if max(wins, losses) != 3 or min(wins, losses) > 2:
        return None
    if wins != 3:
        return None
    # A subsequent game after the deciding third win indicates an inconsistent row.
    if max(sum(a > b for a, b in games[:-1]), sum(b > a for a, b in games[:-1])) >= 3:
        return None
    return {
        "id": str(row["id"]),
        "date": card["date"],
        "division": card["division"],
        "home": home,
        "away": away,
        "winner": home,
        "games": games,
        "url": f"https://clublocker.com/leagues/scorecard/{card['id']}",
    }


class ClubLocker:
    def __init__(self, client=None, remaining=lambda: 600_000):
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(15, connect=5), follow_redirects=False
        )
        self.remaining = remaining

    def close(self):
        self.client.close()

    def get(self, path):
        for attempt in range(3):
            if self.remaining() < 30_000:
                raise SourceError("Refresh time budget exhausted")
            try:
                response = self.client.get(BASE + path)
                if response.status_code in (401, 403):
                    raise SourceError("Public data access unavailable")
                if (
                    response.status_code == 429 or response.status_code >= 500
                ) and attempt < 2:
                    time.sleep(0.5 * 2**attempt)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError, ValueError:
                if attempt == 2:
                    raise SourceError("Public data request failed") from None
        raise SourceError("Public data request failed")

    def rows(self, path):
        rows = self.get(path)
        if not isinstance(rows, list):
            raise SourceError("Unexpected public data schema")
        return rows

    def collect(self, now, previous=None, manifest=None):
        try:
            return self._collect(now, manifest)
        except KeyError, TypeError, ValueError, AttributeError:
            raise SourceError("Unexpected public data schema") from None

    def _collect(self, now, manifest=None):
        manifest = manifest or season()
        ratings, names = {}, {}
        # Pin both identity and membership, failing closed on an ambiguous roster.
        for pid, player in manifest["players"].items():
            roster = self.rows(f"teams/{player['team']}/players")
            exact = [
                r
                for r in roster
                if str(r.get("playerid")) == pid
                and " ".join(r.get("player", "").split()) == player["roster_name"]
                and r.get("teamid") == player["team"]
                and str(r.get("TeamPosition")) == "6"
            ]
            if len(exact) != 1:
                raise SourceError("Pinned player roster identity changed")
            names[pid] = player["name"]
            values = [
                r.get("rating")
                for r in self.rows(f"res/user/{pid}/ratings")
                if r.get("sportId") == 3 and r.get("ratingTypeId") == 1
            ]
            valid = [
                float(x)
                for x in values
                if isinstance(x, (float, int)) and math.isfinite(x) and x > 0
            ]
            ratings[pid] = valid[0] if len(valid) == 1 else None

        cutoff = (now.date() - timedelta(days=731)).isoformat()
        cards = {}
        for sid in manifest["seasons"]:
            for division in self.rows(f"leagues/info/{sid}"):
                if division.get("OrganizationID") != 10234 or "ASC" not in division.get(
                    "SeasonDescr", ""
                ):
                    raise SourceError("Unexpected league identity")
                did = division["Leagueid"]
                for row in self.rows(f"divisions/playerStandings/{did}"):
                    pid, label = str(row.get("playerid1") or ""), row.get("player1", "")
                    parts = label.split(",", 1)
                    if pid and len(parts) == 2:
                        names.setdefault(
                            pid, " ".join((parts[1] + " " + parts[0]).split())
                        )
                for row in self.rows(f"divisions/schedule/{did}/"):
                    day = match_date(row["matchdate"])
                    if (
                        cutoff <= day < now.date().isoformat()
                        and row.get("Score_Entered") == "Confirmed"
                    ):
                        cards[str(row["scorecardid"])] = {
                            "id": row["scorecardid"],
                            "date": day,
                            "division": did,
                        }

        # Fetch completed scorecards again so official corrections replace cached results.
        def read(card):
            return [
                m
                for r in self.rows(f"leagues/scorecards/{card['id']}/list")
                if (m := normalize(r, card)) is not None
            ]

        with ThreadPoolExecutor(max_workers=4) as pool:
            batches = list(pool.map(read, cards.values()))
        matches = {}
        for batch in batches:
            for match in batch:
                if match["id"] in matches and matches[match["id"]] != match:
                    raise SourceError("Conflicting duplicate match")
                matches[match["id"]] = match
        # Sanitized, authorized own-profile export adds tournament/box matches;
        # public scorecards always win when the same upstream ID appears in both.
        seed = json.loads(
            files("squash_calendar").joinpath("own_history.json").read_text()
        )
        names.update({k: v for k, v in seed["names"].items() if k not in names})
        for match in seed["matches"]:
            if cutoff <= match["date"] < now.date().isoformat():
                matches.setdefault(match["id"], match)
        if not matches:
            raise SourceError("No completed accessible results")
        return {
            "as_of": now.isoformat(),
            "ratings": ratings,
            "names": names,
            "matches": sorted(matches.values(), key=lambda m: (m["date"], m["id"])),
            "coverage": "Public ASC team leagues plus a dated own-profile export; restricted opponent history excluded.",
        }

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from booker.schedule import WEEKDAYS, normalize_weekday, parse_hhmm

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_BOOKINGS_PATH = PACKAGE_DIR.parent / "bookings.yaml"
VISIBILITIES = ("public", "private")


@dataclass(frozen=True)
class WeeklyRule:
    activity: str
    weekday: str
    time: str
    duration_min: int
    people: int
    enabled: bool
    visibility: str = "public"
    title: str | None = None


@dataclass(frozen=True)
class BookingsConfig:
    timezone: str
    horizon_hours: int
    gym_id: int
    university_id: int
    calendar_url: str
    activities: dict[str, str]
    equipment_ids: dict[str, int]
    weekly: list[WeeklyRule]
    path: Path

    def activity_label(self, key: str) -> str:
        try:
            return self.activities[key]
        except KeyError as exc:
            known = ", ".join(sorted(self.activities))
            raise ValueError(f"unknown activity {key!r}; expected one of: {known}") from exc

    def equipment_id(self, key: str) -> int:
        try:
            return self.equipment_ids[key]
        except KeyError as exc:
            known = ", ".join(sorted(self.equipment_ids))
            raise ValueError(f"unknown activity {key!r}; expected equipment id for: {known}") from exc

    def visibility_for(self, activity: str, local_start: datetime) -> tuple[str, str | None]:
        """Classify a slot by the private weekly rules, enabled or not.

        Disabled rules still count so that turning a rule off never makes its
        earlier bookings public. `local_start` is wall-clock time in `timezone`.
        """
        weekday = WEEKDAYS[local_start.weekday()]
        slot = (local_start.hour, local_start.minute)
        for rule in self.weekly:
            if rule.visibility != "private" or rule.activity != activity or rule.weekday != weekday:
                continue
            rule_time = parse_hhmm(rule.time)
            if (rule_time.hour, rule_time.minute) == slot:
                return "private", rule.title
        return "public", None


def load_bookings(path: Path | None = None) -> BookingsConfig:
    bookings_path = path or Path(os.environ.get("BOOKINGS_PATH", DEFAULT_BOOKINGS_PATH))
    raw: dict[str, Any] = yaml.safe_load(bookings_path.read_text(encoding="utf-8"))
    activities = {str(key): str(label) for key, label in (raw.get("activities") or {}).items()}
    equipment_ids = {str(key): int(value) for key, value in (raw.get("equipment_ids") or {}).items()}
    missing_ids = sorted(set(activities) - set(equipment_ids))
    if missing_ids:
        raise ValueError(f"activities missing equipment_ids: {', '.join(missing_ids)}")
    weekly: list[WeeklyRule] = []
    for item in raw.get("weekly") or []:
        activity = str(item["activity"])
        if activity not in activities:
            raise ValueError(f"weekly rule activity {activity!r} is not in activities")
        hhmm = str(item["time"])
        parse_hhmm(hhmm)
        visibility = str(item.get("visibility", "public"))
        if visibility not in VISIBILITIES:
            raise ValueError(f"weekly rule visibility {visibility!r} must be public or private")
        title = str(item.get("title") or "").strip() or None
        weekly.append(
            WeeklyRule(
                activity=activity,
                weekday=normalize_weekday(str(item["weekday"])),
                time=hhmm,
                duration_min=int(item.get("duration_min", 60)),
                people=int(item.get("people", 1)),
                enabled=bool(item.get("enabled", False)),
                visibility=visibility,
                title=title,
            )
        )
    return BookingsConfig(
        timezone=str(raw["timezone"]),
        horizon_hours=int(raw.get("horizon_hours", 72)),
        gym_id=int(raw["gym_id"]),
        university_id=int(raw["university_id"]),
        calendar_url=str(raw["calendar_url"]),
        activities=activities,
        equipment_ids=equipment_ids,
        weekly=weekly,
        path=bookings_path,
    )

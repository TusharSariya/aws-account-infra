from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from booker.schedule import normalize_weekday, parse_hhmm

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_BOOKINGS_PATH = PACKAGE_DIR.parent / "bookings.yaml"


@dataclass(frozen=True)
class WeeklyRule:
    activity: str
    weekday: str
    time: str
    duration_min: int
    people: int
    enabled: bool


@dataclass(frozen=True)
class BookingsConfig:
    timezone: str
    horizon_hours: int
    gym_id: int
    university_id: int
    calendar_url: str
    activities: dict[str, str]
    weekly: list[WeeklyRule]
    path: Path

    def activity_label(self, key: str) -> str:
        try:
            return self.activities[key]
        except KeyError as exc:
            known = ", ".join(sorted(self.activities))
            raise ValueError(f"unknown activity {key!r}; expected one of: {known}") from exc


def load_bookings(path: Path | None = None) -> BookingsConfig:
    bookings_path = path or Path(os.environ.get("BOOKINGS_PATH", DEFAULT_BOOKINGS_PATH))
    raw: dict[str, Any] = yaml.safe_load(bookings_path.read_text(encoding="utf-8"))
    activities = {str(key): str(label) for key, label in (raw.get("activities") or {}).items()}
    weekly: list[WeeklyRule] = []
    for item in raw.get("weekly") or []:
        activity = str(item["activity"])
        if activity not in activities:
            raise ValueError(f"weekly rule activity {activity!r} is not in activities")
        hhmm = str(item["time"])
        parse_hhmm(hhmm)
        weekly.append(
            WeeklyRule(
                activity=activity,
                weekday=normalize_weekday(str(item["weekday"])),
                time=hhmm,
                duration_min=int(item.get("duration_min", 60)),
                people=int(item.get("people", 1)),
                enabled=bool(item.get("enabled", False)),
            )
        )
    return BookingsConfig(
        timezone=str(raw["timezone"]),
        horizon_hours=int(raw.get("horizon_hours", 72)),
        gym_id=int(raw["gym_id"]),
        university_id=int(raw["university_id"]),
        calendar_url=str(raw["calendar_url"]),
        activities=activities,
        weekly=weekly,
        path=bookings_path,
    )

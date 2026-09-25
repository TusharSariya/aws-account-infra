from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


class BookingFailed(RuntimeError):
    """Lambda-facing failure. CloudWatch Errors increment when this is raised."""

    def __init__(self, result: "BookingResult") -> None:
        self.result = result
        super().__init__(json.dumps(result.as_dict()))


BOOKED = "booked"
ALREADY_HELD = "already_held"
CLOSED = "closed"
FULL = "full"
AUTH_FAIL = "auth_fail"
MEMBERSHIP = "membership"
UNEXPECTED_UI = "unexpected_ui"
LATE = "late"
DRY_RUN = "dry_run"
CANCELLED = "cancelled"
# Cancel found nothing to release (or a different reservation holds the slot).
NOT_FOUND = "not_found"


@dataclass(frozen=True)
class BookingResult:
    status: str
    message: str
    target_date: str = ""
    activity: str = ""
    time: str = ""
    reserve_clicks: int = 0
    reservation_id: str | None = None
    calendar_reservation: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def ok(self) -> bool:
        return self.status in {BOOKED, ALREADY_HELD, DRY_RUN, CANCELLED, NOT_FOUND}

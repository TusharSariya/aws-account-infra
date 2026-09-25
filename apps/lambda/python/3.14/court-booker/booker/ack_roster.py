"""Per-court friend roster from one SSM SecureString; addresses never reach logs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from booker.secrets import _client_kwargs


class RosterError(RuntimeError):
    """Missing or malformed roster parameter. Messages never include roster values."""


@dataclass(frozen=True)
class RosterEntry:
    name: str
    email: str

    def __repr__(self) -> str:
        return f"RosterEntry(name={self.name!r}, email='***')"


def _ssm_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "ssm",
        config=Config(
            connect_timeout=2,
            read_timeout=3,
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
        **_client_kwargs(),
    )


def _valid_email(value: str) -> bool:
    local, _, domain = value.partition("@")
    return (
        bool(local)
        and "." in domain
        and len(value) <= 254
        and not any(c.isspace() or c in "<>,;\"" for c in value)
    )


def parse_roster(payload: str) -> dict[str, list[RosterEntry]]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise RosterError("roster parameter is not valid JSON") from None
    if not isinstance(data, dict):
        raise RosterError("roster JSON must be an object keyed by activity")
    roster: dict[str, list[RosterEntry]] = {}
    for activity, rows in data.items():
        if not isinstance(rows, list):
            raise RosterError(f"roster for {activity!r} must be a list")
        entries: list[RosterEntry] = []
        seen: set[str] = set()
        for index, row in enumerate(rows):
            row = row if isinstance(row, dict) else {}
            name = str(row.get("name") or "").strip()
            email = str(row.get("email") or "").strip()
            if not name or len(name) > 100 or not _valid_email(email):
                raise RosterError(f"roster entry {activity}[{index}] needs a name and email")
            if email.lower() in seen:
                continue
            seen.add(email.lower())
            entries.append(RosterEntry(name=name, email=email))
        roster[str(activity)] = entries
    return roster


def load_roster(parameter_name: str | None = None, client=None) -> dict[str, list[RosterEntry]]:
    name = parameter_name or os.environ.get("ACK_ROSTER_PARAMETER", "").strip()
    if not name:
        raise RosterError("ACK_ROSTER_PARAMETER is not set")
    client = client or _ssm_client()
    payload = client.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    return parse_roster(payload)

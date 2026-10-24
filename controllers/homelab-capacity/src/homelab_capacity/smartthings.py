"""Bounded SmartThings requests. Never retry a switch write automatically."""

import base64
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .journal import Journal


class SmartThings:
    def __init__(self, credentials, *, opener=urlopen, clock=time.time):
        self.path = Path(credentials).expanduser()
        self.opener, self.clock = opener, clock

    def credentials(self):
        if self.path.stat().st_mode & 0o077:
            raise PermissionError("SmartThings credentials must be private (0600)")
        return json.loads(self.path.read_text())

    @staticmethod
    def server_expiry(data):
        # Explicit PAT policy: trust API authentication, not an invented deadline.
        # OAuth still uses the provider's expires_in and refresh protocol.
        return data.get("expiry_policy") == "server" and not all(
            data.get(k) for k in ("refresh_token", "client_id", "client_secret")
        )

    def health(self):
        data = self.credentials()
        return {
            "expires_at": None if self.server_expiry(data) else data.get("expires_at", 0),
            "remaining_seconds": (
                None if self.server_expiry(data)
                else int(data.get("expires_at", 0) - self.clock())
            ),
            "renewable": all(
                data.get(k) for k in ("refresh_token", "client_id", "client_secret")
            ),
            "refresh_verified": bool(data.get("last_refreshed_at")),
            "refresh_uncertain": bool(data.get("refresh_pending")),
        }

    def token(self, *, force_refresh=False):
        # Refresh is serialized and atomically persisted, including token rotation.
        journal = Journal(self.path.parent)
        with journal.locked("smartthings-token.lock"):
            data = self.credentials()
            renewable = all(
                data.get(k) for k in ("refresh_token", "client_id", "client_secret")
            )
            if data.get("refresh_pending"):
                raise RuntimeError(
                    "OAuth refresh outcome uncertain; reauthorization required"
                )
            margin = 3600 if renewable else 60
            if not force_refresh and (
                self.server_expiry(data)
                or data.get("expires_at", 0) > self.clock() + margin
            ):
                return data["access_token"]
            if not all(
                data.get(k) for k in ("refresh_token", "client_id", "client_secret")
            ):
                raise RuntimeError("SmartThings authorization expired; reauthorize")
            body = urlencode(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": data["refresh_token"],
                    "client_id": data["client_id"],
                }
            ).encode()
            auth = base64.b64encode(
                (data["client_id"] + ":" + data["client_secret"]).encode()
            ).decode()
            endpoint = data.get(
                "token_endpoint", "https://api.smartthings.com/v1/oauth/token"
            )
            if endpoint not in {
                "https://api.smartthings.com/oauth/token",
                "https://api.smartthings.com/v1/oauth/token",
            }:
                raise ValueError("Untrusted OAuth token endpoint")
            data["refresh_pending"] = True
            journal.write(self.path.name, data)
            result = self.send(
                Request(
                    endpoint,
                    data=body,
                    headers={
                        "Authorization": "Basic " + auth,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
            )
            data.update(
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token", data["refresh_token"]),
                expires_at=self.clock() + int(result["expires_in"]),
                last_refreshed_at=self.clock(),
                refresh_pending=False,
                token_endpoint=endpoint,
            )
            journal.write(self.path.name, data)
            return data["access_token"]

    def send(self, request):
        try:
            with self.opener(request, timeout=15) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            # Never log response bodies, tokens, or cloud account details.
            raise RuntimeError(
                "SmartThings request failed; outcome requires observation"
            ) from None

    def request(self, path, body=None):
        return self.send(
            Request(
                "https://api.smartthings.com/v1/" + path,
                data=None if body is None else json.dumps(body).encode(),
                headers={
                    "Authorization": "Bearer " + self.token(),
                    "Content-Type": "application/json",
                },
            )
        )

    def discover(self):
        # Follow only paths on the fixed API origin; do not leak credentials to links.
        result = self.request("devices")
        if result.get("_links", {}).get("next"):
            raise RuntimeError(
                "Paginated discovery: narrow the account inventory before commissioning"
            )
        return [
            {
                "device_id": d["deviceId"],
                "label": d.get("label"),
                "components": d.get("components", []),
            }
            for d in result["items"]
        ]

    def status(self, outlet):
        device = quote(outlet["device_id"], safe="")
        component = quote(outlet["component_id"], safe="")
        health = self.request(f"devices/{device}/health")
        value = self.request(
            f"devices/{device}/components/{component}/capabilities/switch/status"
        )["switch"]
        if health.get("state") != "ONLINE" or value.get("value") not in {"on", "off"}:
            raise RuntimeError("SmartThings outlet is offline or unknown")
        stamp = datetime.fromisoformat(value["timestamp"]).timestamp()
        if stamp > self.clock() + 5:
            raise RuntimeError("SmartThings timestamp is in the future")
        return {
            "state": value["value"],
            "changed_at": stamp,
            "observed_at": self.clock(),
        }

    def switch(self, outlet, state):
        if state not in {"on", "off"}:
            raise ValueError("Explicit switch state required")
        device = quote(outlet["device_id"], safe="")
        result = self.request(
            f"devices/{device}/commands",
            {
                "commands": [
                    {
                        "component": outlet["component_id"],
                        "capability": "switch",
                        "command": state,
                        "arguments": [],
                    }
                ]
            },
        )
        if (
            len(result.get("results", [])) != 1
            or result["results"][0].get("status") != "ACCEPTED"
        ):
            raise RuntimeError("SmartThings did not accept command; observe outcome")
        return result["results"][0]["id"]

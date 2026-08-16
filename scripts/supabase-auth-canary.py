#!/usr/bin/env python3
"""Operator-only Supabase Auth canary.

Credentials are accepted only through environment variables populated by asm-exec.
Response bodies are deliberately never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


class CanaryError(RuntimeError):
    pass


def request(url: str, key: str, path: str, payload: dict, bearer: str | None = None) -> tuple[int, dict]:
    headers = {"apikey": key, "Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(
        f"{url.rstrip('/')}/auth/v1/{path}",
        method="POST",
        headers=headers,
        data=json.dumps(payload).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.load(response) if response.length != 0 else {}
            return response.status, body
    except urllib.error.HTTPError as exc:
        try:
            error = json.load(exc)
        except (json.JSONDecodeError, UnicodeDecodeError):
            error = {}
        # Return only a non-sensitive machine code. Never propagate provider messages,
        # which can echo submitted addresses or other request context.
        return exc.code, {"error_code": error.get("error_code") or error.get("code")}


def run(redirect_url: str) -> None:
    names = (
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_CANARY_EMAIL",
        "SUPABASE_CANARY_PASSWORD",
    )
    values = {name: os.environ.pop(name, "") for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise CanaryError("missing asm-exec runtime variables: " + ", ".join(missing))
    url = values["SUPABASE_URL"]
    key = values["SUPABASE_PUBLISHABLE_KEY"]
    email = values["SUPABASE_CANARY_EMAIL"]
    password = values["SUPABASE_CANARY_PASSWORD"]

    signup_canary = f"public-signup-canary+{uuid.uuid4().hex}@example.com"
    status, _ = request(url, key, "signup", {"email": signup_canary, "password": password})
    if status // 100 == 2:
        raise CanaryError("public signup unexpectedly succeeded")

    status, login = request(
        url,
        key,
        "token?grant_type=password",
        {"email": email, "password": password},
    )
    if status // 100 != 2 or not login.get("access_token") or not login.get("refresh_token"):
        raise CanaryError(
            f"operator password login failed with HTTP {status} ({login.get('error_code') or 'no-code'})"
        )

    status, refreshed = request(
        url,
        key,
        "token?grant_type=refresh_token",
        {"refresh_token": login["refresh_token"]},
    )
    if status // 100 != 2 or not refreshed.get("access_token") or not refreshed.get("refresh_token"):
        raise CanaryError(f"session refresh failed with HTTP {status}")

    encoded_redirect = urllib.parse.quote(redirect_url, safe="")
    status, _ = request(
        url,
        key,
        f"recover?redirect_to={encoded_redirect}",
        {"email": email},
    )
    if status // 100 != 2:
        raise CanaryError(f"password recovery request failed with HTTP {status}")

    status, _ = request(url, key, "logout", {}, bearer=refreshed["access_token"])
    if status // 100 != 2:
        raise CanaryError(f"logout failed with HTTP {status}")

    status, _ = request(
        url,
        key,
        "token?grant_type=refresh_token",
        {"refresh_token": refreshed["refresh_token"]},
    )
    if status // 100 == 2:
        raise CanaryError("logged-out refresh token remained usable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redirect-url", required=True)
    args = parser.parse_args()
    if not args.redirect_url.startswith("https://"):
        parser.error("--redirect-url must use HTTPS")
    try:
        run(args.redirect_url)
    except CanaryError as exc:
        print(f"Auth canary failed: {exc}", file=sys.stderr)
        return 1
    print("operator-only Auth canary passed: signup, login, refresh, recovery, logout, revocation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

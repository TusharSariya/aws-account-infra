#!/usr/bin/env python3
"""Run the operator Auth canary against an isolated local Supabase stack."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKDIR = ROOT / "canaries" / "supabase-auth"


def load_hosted_canary():
    spec = importlib.util.spec_from_file_location(
        "supabase_auth_canary", ROOT / "scripts" / "supabase-auth-canary.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def admin_request(url: str, secret_key: str, path: str, method: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"{url.rstrip('/')}/auth/v1/admin/{path}",
        method=method,
        headers={
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload).encode() if payload is not None else None,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response) if response.length != 0 else {}


def status() -> dict:
    result = subprocess.run(
        ["supabase", "status", "--workdir", str(WORKDIR), "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def value(values: dict, *names: str) -> str:
    for name in names:
        if values.get(name):
            return str(values[name])
    raise RuntimeError("local Supabase status omitted required runtime output")


def main() -> int:
    operator_id = None
    url = ""
    secret = ""
    try:
        subprocess.run(
            [
                "supabase",
                "start",
                "--workdir",
                str(WORKDIR),
                "--exclude",
                "analytics,edge-runtime,functions,imgproxy,realtime,storage,studio,vector",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        values = status()
        url = value(values, "API_URL", "api_url")
        publishable = value(values, "PUBLISHABLE_KEY", "ANON_KEY", "anon_key")
        secret = value(values, "SECRET_KEY", "SERVICE_ROLE_KEY", "service_role_key")
        email = f"operator-canary+{uuid.uuid4().hex}@example.com"
        password = f"Aa1!{uuid.uuid4().hex}"
        operator = admin_request(
            url,
            secret,
            "users",
            "POST",
            {"email": email, "password": password, "email_confirm": True},
        )
        operator_id = operator["id"]
        os.environ.update(
            {
                "SUPABASE_URL": url,
                "SUPABASE_PUBLISHABLE_KEY": publishable,
                "SUPABASE_CANARY_EMAIL": email,
                "SUPABASE_CANARY_PASSWORD": password,
            }
        )
        load_hosted_canary().run("https://auth-canary.example.com/auth/callback")
        print("local operator-only Auth canary passed")
        return 0
    except RuntimeError as exc:
        print(f"local Auth canary failed: {exc}", file=sys.stderr)
        return 1
    except (KeyError, urllib.error.HTTPError, subprocess.CalledProcessError) as exc:
        print(f"local Auth canary failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if operator_id and url and secret:
            try:
                admin_request(url, secret, f"users/{operator_id}", "DELETE")
            except Exception:
                print("warning: local canary operator cleanup failed", file=sys.stderr)
        subprocess.run(
            ["supabase", "stop", "--workdir", str(WORKDIR), "--no-backup"],
            check=False,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())

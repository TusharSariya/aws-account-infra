#!/usr/bin/env python3
"""Mint a short-lived GitHub App token and exec OpenTofu without printing it.

Invoke this script only beneath asm-exec so GITHUB_APP_PEM is populated from a
dynamic Secrets Manager reference inside this child process.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request



def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _app_jwt(app_id: str, pem: str) -> str:
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps({"iat": now - 30, "exp": now + 540, "iss": app_id}, separators=(",", ":")).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    key_path = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", prefix="github-app-", delete=False) as handle:
            key_path = handle.name
            os.chmod(key_path, 0o600)
            handle.write(pem)
        signature = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=signing_input,
            check=True,
            capture_output=True,
        ).stdout
    finally:
        if key_path:
            os.unlink(key_path)
    return f"{header}.{payload}.{_b64url(signature)}"


def installation_token(app_id: str, installation_id: str, pem: str) -> str:
    app_jwt = _app_jwt(app_id, pem)
    request = urllib.request.Request(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {app_jwt}",
            "User-Agent": "aws-account-infra-repository-vending",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not print the response body: GitHub may include sensitive request context.
        raise RuntimeError(f"GitHub App token request failed with HTTP {exc.code}") from exc
    token = payload.get("token")
    if not token:
        raise RuntimeError("GitHub App token response contained no token")
    return str(token)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")

    pem = os.environ.pop("GITHUB_APP_PEM", "")
    if not pem:
        print("GITHUB_APP_PEM was not resolved by asm-exec", file=sys.stderr)
        return 2
    token = installation_token(args.app_id, args.installation_id, pem)
    del pem

    child_environment = os.environ.copy()
    child_environment["GITHUB_TOKEN"] = token
    os.execvpe(command[0], command, child_environment)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())

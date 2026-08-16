#!/usr/bin/env python3
"""Explicit operator-only restore for a paused Supabase project."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("service_id")
    parser.add_argument("--catalog-sha", required=True)
    parser.add_argument("--confirm-project-ref", required=True)
    args = parser.parse_args()
    current_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if args.catalog_sha != current_sha:
        print("catalog SHA does not match the checked-out commit", file=sys.stderr)
        return 2
    if subprocess.run(
        ["git", "diff", "--quiet", "--", "catalog/catalog.json", "catalog/services"],
        cwd=ROOT,
    ).returncode:
        print("restore requires clean, committed catalog inputs", file=sys.stderr)
        return 2
    catalog = json.loads((ROOT / "catalog/catalog.json").read_text(encoding="utf-8"))
    service = catalog["services"].get(args.service_id)
    target = service and service.get("external_services", {}).get("supabase")
    if not target:
        print("service has no Supabase binding", file=sys.stderr)
        return 2
    if target["lifecycle"] in ("purge_requested", "purged"):
        print("restore is forbidden after purge has been requested", file=sys.stderr)
        return 2
    project_ref = target.get("project_ref")
    if not project_ref or project_ref != args.confirm_project_ref:
        print("confirmed project ref does not match the immutable catalog ref", file=sys.stderr)
        return 2
    token = os.environ.pop("SUPABASE_ACCESS_TOKEN", "")
    if not token:
        print("SUPABASE_ACCESS_TOKEN must be resolved at runtime by asm-exec", file=sys.stderr)
        return 2
    request = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{project_ref}/restore",
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=b"{}",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status // 100 != 2:
                print(f"restore failed with HTTP {response.status}", file=sys.stderr)
                return 1
    except urllib.error.HTTPError as exc:
        print(f"restore failed with HTTP {exc.code}", file=sys.stderr)
        return 1
    print(f"restore requested for {args.service_id} at catalog {args.catalog_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Write only the scoped coordinator credential to a private laptop kubeconfig."""

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubectl", required=True)
    parser.add_argument("--admin-kubeconfig", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.destination.exists():
        raise ValueError(
            "Existing credential must be deliberately rotated, not overwritten"
        )
    args.destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.destination.parent.stat().st_mode & 0o077:
        raise ValueError("Credential directory must be private")
    command = [args.kubectl, "--kubeconfig", args.admin_kubeconfig]

    def read(*argv):
        result = subprocess.run(
            command + list(argv), capture_output=True, timeout=30, check=True
        )
        return json.loads(result.stdout)

    secret = read(
        "get",
        "secret",
        "retained-host-coordinator",
        "-n",
        "homelab-platform",
        "-o",
        "json",
    )
    if (
        secret["type"] != "kubernetes.io/service-account-token"
        or secret["metadata"]["annotations"]["kubernetes.io/service-account.name"]
        != "retained-host-coordinator"
    ):
        raise ValueError("Unexpected credential identity")
    token = base64.b64decode(secret["data"]["token"]).decode()
    original = read("config", "view", "--raw", "--minify", "-o", "json")
    cluster = original["clusters"][0]
    value = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [cluster],
        "users": [{"name": "retained-host-coordinator", "user": {"token": token}}],
        "contexts": [
            {
                "name": "coordinator",
                "context": {
                    "cluster": cluster["name"],
                    "user": "retained-host-coordinator",
                },
            }
        ],
        "current-context": "coordinator",
    }
    with args.destination.open("x") as stream:
        json.dump(value, stream)
    print("Scoped coordinator kubeconfig written privately")


if __name__ == "__main__":
    main()

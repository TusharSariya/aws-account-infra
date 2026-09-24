#!/usr/bin/env python3
"""Create a 15-minute node bootstrap token without printing credentials."""

import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import secrets
import subprocess

CLUSTER_UID = "43b9d80f-4676-49c0-84ab-87d3666691dc"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument(
        "--node",
        choices=["ubuntu-enrollment-validation", "ubuntu-gpu-01"],
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    command = [args.kubectl, "--kubeconfig", args.kubeconfig, "--request-timeout=20s"]
    ns = json.loads(
        subprocess.check_output(
            command + ["get", "namespace", "kube-system", "-o", "json"]
        )
    )
    if ns["metadata"]["uid"] != CLUSTER_UID:
        raise SystemExit("Wrong cluster: refusing bootstrap")
    # The kubeconfig itself stays on the trusted operator machine.
    cfg = json.loads(
        subprocess.check_output(
            command + ["config", "view", "--raw", "--minify", "-o", "json"]
        )
    )
    ca = cfg["clusters"][0]["cluster"].get("certificate-authority-data")
    if not ca:
        raise SystemExit("Use a kubeconfig with an embedded trusted CA")
    os.umask(0o077)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Refuse overwriting an operator's private vars or existing token.
    with args.output.open("x") as output:
        token_id = secrets.token_hex(3)
        token_secret = secrets.token_hex(8)
        expiration = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=15)
        ).isoformat()
        secret = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "bootstrap-token-" + token_id,
                "namespace": "kube-system",
            },
            "type": "bootstrap.kubernetes.io/token",
            "stringData": {
                "token-id": token_id,
                "token-secret": token_secret,
                "expiration": expiration,
                "usage-bootstrap-authentication": "true",
                "auth-extra-groups": "system:bootstrappers:ubuntu-worker",
                "description": "Short-lived enrollment for " + args.node,
            },
        }
        subprocess.run(
            command + ["create", "-f", "-"],
            input=json.dumps(secret),
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        json.dump(
            {
                "worker_enrollment_ca": base64.b64decode(ca).decode(),
                "worker_enrollment_bootstrap_token": token_id + "." + token_secret,
            },
            output,
            indent=2,
        )
    print(
        "Private enrollment variables written; token expires in 15 minutes. Node CSR requires explicit verification."
    )


if __name__ == "__main__":
    main()

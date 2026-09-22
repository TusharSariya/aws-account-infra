#!/usr/bin/env python3
"""Verify private Argo core, authenticated access and zero application adoption."""

import argparse
import base64
import http.client
import json
import socket
import ssl
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    b = Path.home() / ".local/share/main-control-plane/private"
    k = [
        str(b / "kubectl"),
        "--kubeconfig",
        str(b / "kubeconfig"),
        "--request-timeout=30s",
        "-n",
        "argocd",
    ]

    def obj(*a):
        return json.loads(subprocess.check_output(k + list(a) + ["-o", "json"]))

    for kind, name in [
        ("deployment", "argocd-server"),
        ("deployment", "argocd-repo-server"),
        ("deployment", "argocd-redis"),
        ("statefulset", "argocd-application-controller"),
    ]:
        subprocess.run(
            k + ["rollout", "status", kind + "/" + name, "--timeout=300s"], check=True
        )
        live = obj("get", kind, name)
        assert live["spec"].get("replicas", 1) == 1, name
        assert live.get("status", {}).get("readyReplicas", 0) == 1, name
    assert not obj("get", "applications")["items"]
    assert not obj(
        "get",
        "secrets",
        "-l",
        "argocd.argoproj.io/secret-type in (repository,repo-creds,cluster)",
    )["items"]
    projects = obj("get", "appprojects")["items"]
    assert {x["metadata"]["name"] for x in projects} == {"default", "platform"}
    assert all(
        not x["spec"].get("sourceRepos") and not x["spec"].get("destinations")
        for x in projects
    )
    secret = obj("get", "secret", "argocd-secret")["data"]
    cert = base64.b64decode(secret["tls.crt"]).decode()
    password = base64.b64decode(
        obj("get", "secret", "argocd-initial-admin-secret")["data"]["password"]
    ).decode()
    context = ssl.create_default_context(cadata=cert)
    proc = subprocess.Popen(
        k + ["port-forward", "svc/argocd-server", "18443:443"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def request(path, payload=None, token=None):
        data = json.dumps(payload).encode() if payload is not None else b""
        method = "POST" if payload is not None else "GET"
        headers = f"{method} {path} HTTP/1.1\r\nHost: argocd-server\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n"
        if token:
            headers += "Authorization: Bearer " + token + "\r\n"
        with (
            socket.create_connection(("127.0.0.1", 18443), 15) as raw,
            context.wrap_socket(raw, server_hostname="argocd-server") as tls,
        ):
            tls.sendall((headers + "\r\n").encode() + data)
            response = http.client.HTTPResponse(tls)
            response.begin()
            body = response.read()
            assert response.status == 200, response.status
            return json.loads(body)

    try:
        time.sleep(3)
        token = request("/api/v1/session", {"username": "admin", "password": password})[
            "token"
        ]
        assert not request("/api/v1/applications", token=token).get("items")
        assert not request("/api/v1/repositories", token=token).get("items")
        result = {
            "component": "argocd",
            "passed": True,
            "completed": datetime.now(timezone.utc).isoformat(),
            "checks": [
                "four active controllers ready",
                "verified TLS and authenticated admin API",
                "zero Applications/repositories/cluster credentials",
                "closed projects",
            ],
        }
        args.output.write_text(json.dumps(result, indent=2))
        print(
            "Argo core and authenticated administrative access passed; no applications adopted"
        )
    finally:
        proc.terminate()
        proc.wait(timeout=15)


if __name__ == "__main__":
    main()

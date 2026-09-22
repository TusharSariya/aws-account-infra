"""Private laptop operator commands; never require sleeping Kubernetes services."""

import argparse
import json
import uuid
import subprocess
import time
from pathlib import Path
from .config import INVENTORY, load
from .journal import Journal


def forward(args, config, journal):
    if (
        args.host != "primary"
        or not args.service
        or not args.admin_kubeconfig
        or not 1024 <= args.local_port <= 65535
    ):
        raise ValueError(
            "Forward requires primary, an administrative service, --admin-kubeconfig and a local port >=1024"
        )
    token = "forward-" + str(uuid.uuid4())
    with journal.locked("operator.lock"):
        holds = journal.read("primary-holds.json", {})
        holds[token] = "administrative port forward: " + args.service
        journal.write("primary-holds.json", holds)
    try:
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            state = journal.read("primary.json", {})
            if state.get("paused") or state.get("phase") == "blocked":
                raise RuntimeError("Host is paused or blocked; inspect powerctl status")
            observed = journal.read("observations.json", {})
            if time.time() - observed.get(
                "observed_at", 0
            ) < 60 and "primary" in observed.get("admission_ready", []):
                break
            time.sleep(2)
        else:
            raise RuntimeError("Host did not become ready within 20 minutes")
        namespace = "argocd" if args.service == "argocd" else "monitoring"
        service = "argocd-server" if args.service == "argocd" else args.service
        ports = {
            "argocd": 443,
            "grafana": 3000,
            "prometheus": 9090,
            "loki": 3100,
            "alertmanager": 9093,
        }
        subprocess.run(
            [
                str(Path(config["kubectl"]).expanduser()),
                "--kubeconfig",
                str(Path(args.admin_kubeconfig).expanduser()),
                "-n",
                namespace,
                "port-forward",
                "--address=127.0.0.1",
                "service/" + service,
                str(args.local_port) + ":" + str(ports[args.service]),
            ],
            check=True,
        )
    finally:
        with journal.locked("operator.lock"):
            holds = journal.read("primary-holds.json", {})
            holds.pop(token, None)
            journal.write("primary-holds.json", holds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "action",
        choices=[
            "status",
            "wake",
            "shutdown",
            "pause",
            "resume",
            "hold",
            "release",
            "forward",
        ],
    )
    parser.add_argument("host", choices=sorted(INVENTORY))
    parser.add_argument("--token", help="Durable hold identifier; required for release")
    parser.add_argument(
        "--service", choices=["grafana", "prometheus", "loki", "alertmanager", "argocd"]
    )
    parser.add_argument("--local-port", type=int, default=3000)
    parser.add_argument(
        "--admin-kubeconfig",
        help="Separate operator credential for administrative port forwarding",
    )
    parser.add_argument("--reason", default="operator maintenance")
    args = parser.parse_args()
    config = load(args.config)
    journal = Journal(config["journal"])
    if args.action == "forward":
        return forward(args, config, journal)
    if args.action == "status":
        print(
            json.dumps(
                {
                    "state": journal.read(args.host + ".json", {}),
                    "observation": journal.read("observations.json", {}),
                    "holds": journal.read(args.host + "-holds.json", {}),
                },
                indent=2,
            )
        )
        return
    with journal.locked("operator.lock"):
        if args.action in {"hold", "release"}:
            holds = journal.read(args.host + "-holds.json", {})
            token = args.token or str(uuid.uuid4())
            if args.action == "hold":
                if token in holds and holds[token] != args.reason:
                    raise ValueError("Hold token already owned by another purpose")
                holds[token] = args.reason
            else:
                if not args.token or token not in holds:
                    raise ValueError("Existing hold token required")
                del holds[token]
            journal.write(args.host + "-holds.json", holds)
            print(token)
        else:
            request = journal.read(args.host + "-command.json", {})
            result = journal.read(args.host + "-command-result.json", {})
            if request and result.get("id") != request["id"]:
                raise RuntimeError("Previous operator command is still pending")
            ident = str(uuid.uuid4())
            journal.write(
                args.host + "-command.json", {"id": ident, "action": args.action}
            )
            print(
                json.dumps({"request": ident, "action": args.action, "host": args.host})
            )


if __name__ == "__main__":
    main()

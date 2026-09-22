#!/usr/bin/env python3
"""Capture and re-query retained monitoring data across a worker/host restart."""

import argparse
import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["capture", "check"])
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--smoke", type=Path, required=True)
    args = p.parse_args()
    b = Path.home() / ".local/share/main-control-plane/private"
    k = [
        str(b / "kubectl"),
        "--kubeconfig",
        str(b / "kubeconfig"),
        "--request-timeout=30s",
        "-n",
        "monitoring",
    ]
    procs = []

    def get(port, path, **query):
        url = f"http://127.0.0.1:{port}{path}?" + urllib.parse.urlencode(query)
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.load(response)

    try:
        for service, port, remote in [
            ("prometheus", 19190, 9090),
            ("loki", 13200, 3100),
        ]:
            procs.append(
                subprocess.Popen(
                    k + ["port-forward", "svc/" + service, f"{port}:{remote}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        time.sleep(3)
        claims = json.loads(subprocess.check_output(k + ["get", "pvc", "-o", "json"]))[
            "items"
        ]
        bindings = {
            c["metadata"]["name"]: [c["metadata"]["uid"], c["spec"]["volumeName"]]
            for c in claims
        }
        volumes = json.loads(subprocess.check_output(k + ["get", "pv", "-o", "json"]))[
            "items"
        ]
        volume_uids = {
            v["metadata"]["name"]: v["metadata"]["uid"]
            for v in volumes
            if v["metadata"]["name"] in {value[1] for value in bindings.values()}
        }
        if args.action == "capture":
            assert not args.evidence.exists()
            smoke = json.loads(args.smoke.read_text())
            assert smoke["passed"]
            record = {
                "time": time.time() - 30,
                "log_marker": smoke["log_marker"],
                "bindings": bindings,
                "volume_uids": volume_uids,
            }
            record["metric"] = get(
                19190,
                "/api/v1/query",
                query='up{job="monitoring"}',
                time=record["time"],
            )["data"]["result"]
            assert len(record["metric"]) == 5
            assert all(x["value"][1] == "1" for x in record["metric"])
            record["captured"] = True
            args.evidence.write_text(json.dumps(record, indent=2))
            print("Captured five historical metrics, log marker and claim bindings")
        else:
            record = json.loads(args.evidence.read_text())
            assert bindings == record["bindings"]
            assert volume_uids == record["volume_uids"]
            metrics = get(
                19190,
                "/api/v1/query",
                query='up{job="monitoring"}',
                time=record["time"],
            )["data"]["result"]
            assert sorted(
                metrics, key=lambda x: json.dumps(x["metric"], sort_keys=True)
            ) == sorted(
                record["metric"], key=lambda x: json.dumps(x["metric"], sort_keys=True)
            ), "Historical metrics changed or disappeared"
            logs = get(
                13200,
                "/loki/api/v1/query_range",
                query='{namespace="monitoring"} |= "' + record["log_marker"] + '"',
                start=str(int((record["time"] - 1800) * 1e9)),
                end=str(int((record["time"] + 30) * 1e9)),
            )["data"]["result"]
            assert len(logs) >= 2, "Both pre-restart Pod log streams must survive"
            targets = get(19190, "/api/v1/targets")["data"]["activeTargets"]
            assert len(targets) == 8 and all(
                t["health"] == "up"
                or (
                    t["labels"].get("job") == "kubelet"
                    and t["labels"].get("node") == "talos-worker-02"
                    and t["labels"].get("power_intent") == "sleep"
                )
                for t in targets
            ), [(t["labels"], t["health"]) for t in targets]
            record.update(passed=True, checked=time.time())
            args.evidence.write_text(json.dumps(record, indent=2))
            print(
                "Historical metrics/logs, awake scrape targets, intentional sleep and unchanged claims verified"
            )
    finally:
        for proc in procs:
            proc.terminate()
            proc.wait(timeout=15)


if __name__ == "__main__":
    main()

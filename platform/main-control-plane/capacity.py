#!/usr/bin/env python3
"""Measure host/guest reserves while the bounded main-cluster workload runs."""

import argparse
import json
import re
import subprocess
import time
from pathlib import Path


def available(text):
    return int(re.search(r"^MemAvailable:\s+(\d+)", text, re.MULTILINE)[1]) * 1024


def passes(samples):
    if len(samples) < 5:
        return False
    swap_seconds = 0
    for index, sample in enumerate(samples):
        if min(sample["host_available"], sample["guest_available"]) < 512 * 1024**2:
            return False
        if index:
            prev = samples[index - 1]
            dt = sample["time"] - prev["time"]
            delta = sample["swap_bytes"] - prev["swap_bytes"]
            if not 0 < dt <= 45 or delta < 0:
                return False
            swap_seconds = swap_seconds + dt if delta / dt >= 65536 else 0
            if swap_seconds >= 60:
                return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert args.seconds >= 60
    private = Path.home() / ".local/share/main-control-plane/private"
    talos = [
        str(private / "talosctl"),
        "--talosconfig",
        str(private / "talosconfig"),
        "-e",
        "10.0.0.221",
        "-n",
        "10.0.0.221",
    ]
    samples = []
    end = time.monotonic() + args.seconds
    while True:
        vmstat = dict(
            line.split() for line in Path("/proc/vmstat").read_text().splitlines()
        )
        guest = subprocess.check_output(talos + ["read", "/proc/meminfo"], text=True)
        samples.append(
            {
                "time": time.time(),
                "host_available": available(Path("/proc/meminfo").read_text()),
                "guest_available": available(guest),
                "swap_bytes": (int(vmstat["pswpin"]) + int(vmstat["pswpout"])) * 4096,
            }
        )
        if time.monotonic() >= end:
            break
        time.sleep(15)
    result = {
        "passed": passes(samples),
        "samples": samples,
        "seconds": args.seconds,
        "scope": "capacity only; workload health and independence are separate checks",
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if not result["passed"]:
        raise SystemExit("Capacity gate failed")
    print("Capacity reserves and swapping gate passed")


if __name__ == "__main__":
    main()

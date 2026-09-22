#!/usr/bin/env python3
"""Render the reviewed configuration in observe mode; never enables power effects."""

import argparse
import json
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    base = ROOT / "platform/automatic-power"
    config = json.loads((base / "coordinator.example.json").read_text())
    # One reviewed value drives both AI idling and physical host retirement.
    lifecycle = yaml.safe_load(
        (
            ROOT / "config/environments/kubernetes/homelab/lifecycle-values.yaml"
        ).read_text()
    )
    config["idle_seconds"] = lifecycle["config"]["idleTimeoutSeconds"]
    config["gateways"] = json.loads((base / "gateways.json").read_text())
    ci = ROOT / "config/environments/kubernetes/homelab-ci"
    config["capacity"] = {
        "pool": yaml.safe_load((ci / "pool-values.yaml").read_text()),
        "catalog": json.loads((ci / "runner-catalog.json").read_text()),
    }
    with args.destination.open("x") as stream:
        json.dump(config, stream, indent=2)
    print("Observe-only coordinator configuration rendered")


if __name__ == "__main__":
    main()

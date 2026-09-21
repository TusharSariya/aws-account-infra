#!/usr/bin/env python3
"""Render actual kube-burner templates with deterministic iteration for CI schema checks."""

import json
from pathlib import Path
import sys

from core import Run, load_profile
from scenarios import burner_config


def main():
    destination = Path(sys.argv[1]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    profile = load_profile(Path(__file__).parent / "profiles/pilot.json")
    run = Run(profile, destination, "kv-0123456789abcdef")
    run.case = "load-bursts"
    for count in profile["load"]["bursts"]:
        _, config_file = burner_config(run, count)
        config = json.loads(config_file.read_text())
        template = Path(config["jobs"][0]["objects"][0]["objectTemplate"])
        template.write_text(
            template.read_text()
            .replace("{{.Iteration}}", "0")
            .replace("{{.RunID}}", "00000000-0000-0000-0000-000000000000")
        )
    print(destination)


if __name__ == "__main__":
    main()

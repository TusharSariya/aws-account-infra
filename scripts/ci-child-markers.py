"""Fail when a selected suite child did not record a successful step.

Consolidated suites run several children as guarded steps in one job. Each
child step appends its name to "$RUNNER_TEMP/$MARKER_FILE" as its last command,
so the marker exists only when the step ran and succeeded. A selected child
whose step silently skipped therefore fails the job instead of passing the gate.
"""

import json
import os
from pathlib import Path


def missing(selected, prefix, ran, exempt=()):
    wanted = {c for c in selected if c.startswith(prefix) and c not in exempt}
    return sorted(wanted - set(ran))


def main():
    marker = Path(os.environ["RUNNER_TEMP"], os.environ["MARKER_FILE"])
    ran = marker.read_text().split() if marker.exists() else []
    exempt = os.environ.get("MARKER_EXEMPT", "").split()
    absent = missing(
        json.loads(os.environ["SELECTED_CHECKS"]),
        os.environ["MARKER_PREFIX"],
        ran,
        exempt,
    )
    if absent:
        raise SystemExit("Selected children did not run: " + ", ".join(absent))
    print("PASS: ran " + ", ".join(sorted(set(ran))))


if __name__ == "__main__":
    main()

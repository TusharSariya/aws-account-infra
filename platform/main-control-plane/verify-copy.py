#!/usr/bin/env python3
import hashlib
import json
import subprocess
from pathlib import Path

base = Path("/var/lib/main-control-plane/vm")
receipt = json.loads((base / "copy.json").read_text())
assert receipt["source_stopped"] is True
assert receipt["virtual_size"] == 100 * 1024**3
for name in ["system.qcow2", "OVMF_CODE.fd", "OVMF_VARS.fd"]:
    h = hashlib.sha256()
    with (base / name).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    assert h.hexdigest() == receipt["sha256"][name], name
assert (base / "OVMF_VARS.fd").stat().st_size == 540672
assert (base / "OVMF_CODE.fd").stat().st_size + 540672 == 4 * 1024**2
subprocess.run(
    ["qemu-img", "check", "-f", "qcow2", str(base / "system.qcow2")], check=True
)

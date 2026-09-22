#!/usr/bin/env python3
"""Exercise the source firmware pair on Ubuntu without any cluster disk or NIC."""

import hashlib
import json
import socket
import subprocess
import time
from pathlib import Path

base = Path.home() / ".local/share/main-control-plane/firmware-probe"
base.mkdir(parents=True, exist_ok=False, mode=0o700)
ssh = [
    "ssh",
    "-o",
    "BatchMode=yes",
    "-i",
    str(Path.home() / ".ssh/main-proxmox"),
    "root@10.0.0.224",
]
for name, cmd in [
    ("OVMF_CODE.fd", "cat /usr/share/pve-edk2-firmware/OVMF_CODE_4M.secboot.fd"),
    ("OVMF_VARS.fd", "head -c 540672 /dev/pve/vm-100-disk-0"),
]:
    with (base / name).open("xb") as f:
        subprocess.run(ssh + [cmd], stdout=f, check=True)
assert (base / "OVMF_CODE.fd").stat().st_size == 3653632
assert (base / "OVMF_VARS.fd").stat().st_size == 540672
qmp = base / "qmp.sock"
with (base / "stderr.log").open("w") as log:
    proc = subprocess.Popen(
        [
            "qemu-system-x86_64",
            "-name",
            "main-firmware-probe",
            "-machine",
            "q35,accel=kvm,smm=on",
            "-cpu",
            "host",
            "-smp",
            "2",
            "-m",
            "128",
            "-nodefaults",
            "-net",
            "none",
            "-display",
            "none",
            "-drive",
            f"if=pflash,format=raw,unit=0,readonly=on,file={base}/OVMF_CODE.fd",
            "-drive",
            f"if=pflash,format=raw,unit=1,file={base}/OVMF_VARS.fd",
            "-global",
            "driver=cfi.pflash01,property=secure,value=on",
            "-qmp",
            f"unix:{qmp},server=on,wait=off",
        ],
        stderr=log,
    )
    try:
        for _ in range(50):
            if qmp.exists():
                break
            assert proc.poll() is None, "Firmware rejected; inspect stderr.log"
            time.sleep(0.1)
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(10)
            sock.connect(str(qmp))
            stream = sock.makefile("rwb", buffering=0)
            json.loads(stream.readline())
            for cmd in ["qmp_capabilities", "query-status", "quit"]:
                stream.write(json.dumps({"execute": cmd}).encode() + b"\n")
                while True:
                    reply = json.loads(stream.readline())
                    assert "error" not in reply, reply
                    if "return" in reply:
                        if cmd == "query-status":
                            assert reply["return"]["running"] is True
                        break
        assert proc.wait(timeout=10) == 0
    finally:
        # This disposable process has no cluster disk or network.
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)
(base.parent / "firmware-proven.json").write_text(
    json.dumps(
        {
            "passed": True,
            "code_sha256": hashlib.sha256(
                (base / "OVMF_CODE.fd").read_bytes()
            ).hexdigest(),
            "scope": "QEMU accepts source pflash pair; Talos boot still requires offline cutover",
        },
        indent=2,
    )
    + "\n"
)
print("Firmware pair accepted by laptop QEMU; main cluster untouched")

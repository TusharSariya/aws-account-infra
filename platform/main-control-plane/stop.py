#!/usr/bin/env python3
"""Ask firmware for ACPI shutdown; never force-kill a stateful guest."""

import json
import socket
import time

with socket.socket(socket.AF_UNIX) as conn:
    conn.settimeout(10)
    conn.connect("/var/lib/main-control-plane/vm/qmp.sock")
    stream = conn.makefile("rwb", buffering=0)
    json.loads(stream.readline())
    for command in ("qmp_capabilities", "system_powerdown"):
        stream.write(json.dumps({"execute": command}).encode() + b"\n")
        while True:
            reply = json.loads(stream.readline())
            if "error" in reply:
                raise RuntimeError(reply)
            if "return" in reply:
                break
    conn.settimeout(180)
    while stream.readline():
        time.sleep(0.1)

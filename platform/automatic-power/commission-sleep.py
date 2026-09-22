#!/usr/bin/env python3
"""One manual, guarded sleep for commissioning wake-only operation.

Run on the laptop with the coordinator service stopped. This is not an idle
controller or an acceptance override: it records a manual test and never writes
automatic-shutdown acceptance. It retains the normal platform recovery journal.
"""

import argparse
import json
from pathlib import Path
import subprocess
import time

from homelab_capacity.config import load
from homelab_capacity.coordinator import Coordinator
from homelab_capacity.lifecycle import State


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", choices=["primary", "secondary"], required=True)
    parser.add_argument(
        "--operation",
        default="commissioning",
        help="Unique private journal name for this reviewed test",
    )
    args = parser.parse_args()
    config = load(args.config)
    if any(mode != "observe" for mode in config["modes"].values()):
        raise RuntimeError("Commissioning begins only from explicit observe mode")
    if (
        subprocess.run(
            [
                "systemctl",
                "--user",
                "is-active",
                "--quiet",
                "homelab-coordinator.service",
            ]
        ).returncode
        == 0
    ):
        raise RuntimeError("Stop the coordinator before manual commissioning")
    subprocess.run(
        ["systemctl", "is-active", "--quiet", "main-control-plane.service"], check=True
    )
    if not Path("/var/lib/main-control-plane/source-fenced").is_file():
        raise RuntimeError("Original control plane has not been fenced")
    independence = Path.home() / ".local/share/main-control-plane/independence.json"
    if json.loads(independence.read_text()).get("passed") is not True:
        raise RuntimeError("Laptop independence has not passed")
    controller = Coordinator(config)
    host, journal = args.host, controller.journal
    name = host + "-" + args.operation + ".json"
    journal.path(name)  # Reject paths and unsafe journal names before any effect.
    with journal.locked():
        if journal.read(name):
            raise RuntimeError(
                "Existing commissioning record requires review; never repeat blindly"
            )
        objects = controller.kube.inventory()
        obs = controller.observation(host, objects)
        if (
            not (
                obs.identity_ok
                and obs.ready
                and obs.complete
                and obs.host_empty
                and obs.retirement_ready
            )
            or obs.demand
            or obs.blockers
        ):
            raise RuntimeError(
                "Manual sleep preflight found demand, activity, or incomplete readiness"
            )
        receipt = {"host": host, "started": time.time(), "phase": "quiescing"}
        journal.write(name, receipt)
        deadline = time.monotonic() + 1200
        try:
            while time.monotonic() < deadline:
                objects = controller.kube.inventory()
                obs = controller.observation(host, objects)
                if obs.demand or obs.blockers or not obs.complete:
                    raise RuntimeError(
                        "Demand changed before manual shutdown commit; restore the saved platform"
                    )
                if obs.quiesced:
                    break
                controller.platform.quiesce(host, objects)
                time.sleep(2)
            else:
                raise RuntimeError("Platform did not quiesce before the deadline")
            # Re-observe immediately before the irreversible shutdown request.
            obs = controller.observation(host, controller.kube.inventory())
            if obs.demand or obs.blockers or not obs.quiesced or not obs.complete:
                raise RuntimeError("Final activity gate failed")
            receipt["phase"] = "worker-shutdown-requested"
            journal.write(name, receipt)
            controller.management.talos(host, "shutdown", "--wait=false")
            while time.monotonic() < deadline:
                pve = controller.management.pve(host)
                if (
                    pve["status"] == "stopped"
                    and not pve["other_running"]
                    and not pve["users"]
                ):
                    break
                time.sleep(5)
            else:
                raise RuntimeError("Worker or host sessions did not stop gracefully")
            receipt["phase"] = "host-shutdown-requested"
            journal.write(name, receipt)
            controller.management.pve(host, "poweroff")
            while time.monotonic() < deadline:
                if controller.management.power(host).get_power().power == "off":
                    break
                time.sleep(5)
            else:
                raise RuntimeError("IMM did not confirm physical power off")
            receipt.update(phase="off", verified_off=time.time())
            journal.write(name, receipt)
            journal.write(
                host + ".json",
                State(
                    phase="off", reason="Manual commissioning sleep confirmed"
                ).to_dict(),
            )
            print(
                host
                + ": original worker and physical host gracefully stopped; saved restoration remains pending"
            )
        except Exception:
            journal.write(
                host + ".json",
                State(
                    phase="blocked",
                    reason="Manual commissioning interrupted; inspect commissioning and platform journals",
                ).to_dict(),
            )
            raise


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Routed Wi-Fi TAP. Never bridge the wireless interface or NAT cluster traffic."""

import argparse
import ipaddress
import json
import os
import subprocess
from pathlib import Path

BRIDGE = "maincpbr"
TAP = "maincptap"
WIFI = "wlp5s0b1"
STATE = Path("/var/lib/main-control-plane/network-state.json")
REAL = ["10.0.0.221", "10.0.0.231"]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def sysctl(key, value):
    run("sysctl", "-qw", f"net.ipv4.conf.{key}={value}")


def up(addresses, owner, test=False):
    if not test and not Path("/var/lib/main-control-plane/source-fenced").is_file():
        raise RuntimeError("Source fencing receipt missing; real addresses prohibited")
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if STATE.exists():
        saved = json.loads(STATE.read_text())
        if saved.get("boot_id") == boot_id:
            raise RuntimeError("Network already owned; inspect or run down first")
        # Kernel objects vanished on reboot. Do not replay stale nft rule handles.
        STATE.unlink()
    run("ip", "link", "show", WIFI, stdout=subprocess.DEVNULL)
    if (
        subprocess.run(
            ["ip", "link", "show", BRIDGE], check=False, capture_output=True
        ).returncode
        == 0
    ):
        raise RuntimeError("Unowned bridge exists")
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    old = {
        key: Path(f"/proc/sys/net/ipv4/conf/{WIFI}/{key}").read_text().strip()
        for key in ("forwarding", "send_redirects")
    }
    STATE.write_text(
        json.dumps(
            {"addresses": addresses, "old": old, "test": test, "boot_id": boot_id}
        )
    )
    try:
        run("ip", "link", "add", BRIDGE, "type", "bridge")
        run("ip", "addr", "add", "169.254.221.1/32", "dev", BRIDGE)
        run("ip", "link", "set", BRIDGE, "up")
        run("ip", "tuntap", "add", "dev", TAP, "mode", "tap", "user", owner)
        run("ip", "link", "set", TAP, "master", BRIDGE)
        run("ip", "link", "set", TAP, "up")
        for iface in (WIFI, BRIDGE):
            sysctl(f"{iface}.forwarding", "1")
            sysctl(f"{iface}.send_redirects", "0")
        # Explicit proxy entries on Wi-Fi advertise only these two /32s.
        # Bridge proxy ARP lets the unchanged /24 guest reach LAN peers/gateway.
        sysctl(f"{BRIDGE}.proxy_arp", "1")
        for addr in addresses:
            run("ip", "route", "add", f"{addr}/32", "dev", BRIDGE)
            run("ip", "neigh", "add", "proxy", addr, "dev", WIFI)
        # The retained pilot installs a second forward hook with policy drop.
        # An accept in our own hook cannot override that later drop. Add only
        # exact main-bridge/address exceptions there; never change its policy.
        pilot = subprocess.run(
            ["nft", "-j", "list", "chain", "inet", "tp103_forward", "forward"],
            check=False,
            capture_output=True,
            text=True,
        )
        if pilot.returncode == 0:
            ips = ", ".join(addresses)
            run(
                "nft",
                "-f",
                "-",
                input=f'''insert rule inet tp103_forward forward iifname "{BRIDGE}" oifname "{WIFI}" ip saddr {{ {ips} }} accept comment "maincp-owned"
insert rule inet tp103_forward forward iifname "{WIFI}" oifname "{BRIDGE}" ip daddr {{ {ips} }} accept comment "maincp-owned"
''',
            )
            rules = json.loads(
                run(
                    "nft",
                    "-j",
                    "list",
                    "chain",
                    "inet",
                    "tp103_forward",
                    "forward",
                    capture_output=True,
                ).stdout
            )
            saved = json.loads(STATE.read_text())
            saved["pilot_handles"] = [
                entry["rule"]["handle"]
                for entry in rules["nftables"]
                if entry.get("rule", {}).get("comment") == "maincp-owned"
            ]
            STATE.write_text(json.dumps(saved))
        ips = ", ".join(addresses)
        run(
            "nft",
            "-f",
            "-",
            input=f'''table inet main_control_plane {{
 chain forward {{
  type filter hook forward priority -10; policy accept;
  iifname "{BRIDGE}" oifname "{WIFI}" ip saddr {{ {ips} }} accept
  iifname "{WIFI}" oifname "{BRIDGE}" ip daddr {{ {ips} }} accept
  iifname "{BRIDGE}" drop
  oifname "{BRIDGE}" drop
 }}
}}\n''',
        )
    except Exception:
        down()
        raise


def reconnect():
    if (
        not STATE.exists()
        or not Path("/var/lib/main-control-plane/source-fenced").exists()
    ):
        return
    saved = json.loads(STATE.read_text())
    if saved["test"]:
        return
    run("ip", "link", "show", BRIDGE, stdout=subprocess.DEVNULL)
    for iface in (WIFI, BRIDGE):
        sysctl(f"{iface}.forwarding", "1")
        sysctl(f"{iface}.send_redirects", "0")
    sysctl(f"{BRIDGE}.proxy_arp", "1")
    for addr in saved["addresses"]:
        run("ip", "route", "replace", f"{addr}/32", "dev", BRIDGE)
        run("ip", "neigh", "replace", "proxy", addr, "dev", WIFI)


def down():
    if not STATE.exists():
        return
    if (
        subprocess.run(
            ["fuser", "/var/lib/main-control-plane/vm/system.qcow2"],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    ):
        raise RuntimeError("QEMU still has the disk open; refusing network withdrawal")
    state = json.loads(STATE.read_text())
    for handle in state.get("pilot_handles", []):
        run(
            "nft",
            "delete",
            "rule",
            "inet",
            "tp103_forward",
            "forward",
            "handle",
            str(handle),
        )
    for addr in state["addresses"]:
        subprocess.run(["ip", "neigh", "del", "proxy", addr, "dev", WIFI], check=False)
        subprocess.run(["ip", "route", "del", f"{addr}/32", "dev", BRIDGE], check=False)
    subprocess.run(
        ["nft", "delete", "table", "inet", "main_control_plane"], check=False
    )
    subprocess.run(["ip", "link", "del", TAP], check=False)
    subprocess.run(["ip", "link", "del", BRIDGE], check=False)
    for key, value in state["old"].items():
        sysctl(f"{WIFI}.{key}", value)
    STATE.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["up", "down", "test-up", "reconnect"])
    parser.add_argument("--owner", default="tushar")
    parser.add_argument("--test-addresses", nargs=2)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("root required")
    if args.action == "down":
        if (
            subprocess.run(
                ["systemctl", "is-active", "--quiet", "main-control-plane.service"],
                check=False,
            ).returncode
            == 0
        ):
            parser.error("Stop the main VM before withdrawing addresses")
        down()
    elif args.action == "reconnect":
        reconnect()
    elif args.action == "up":
        up(REAL, args.owner)
    else:
        if not args.test_addresses or len(set(args.test_addresses)) != 2:
            parser.error(
                "two distinct, independently checked unused LAN test addresses required"
            )
        for addr in args.test_addresses:
            if ipaddress.ip_address(addr) not in ipaddress.ip_network(
                "10.0.0.0/24"
            ) or addr in REAL + [
                "10.0.0.0",
                "10.0.0.255",
                "10.0.0.1",
                "10.0.0.181",
                "10.0.0.222",
                "10.0.0.223",
                "10.0.0.224",
                "10.0.0.225",
                "10.0.0.230",
            ]:
                parser.error("invalid or protected test address")
        up(args.test_addresses, args.owner, test=True)


if __name__ == "__main__":
    main()

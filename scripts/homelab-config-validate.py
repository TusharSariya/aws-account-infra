#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Validate non-secret two-PVE inputs against generated Talos configurations."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/environments/proxmox/homelab/talos"
CP, PRIMARY, SECONDARY = "talos-cp-01", "talos-worker-01", "talos-worker-02"
NODES = (CP, PRIMARY, SECONDARY)
SCHEMATIC = {
    CP: "ce4c980550dd2ab1b17bbf2b08801c7eb59418eafe8f279833297925d67c7515",
    PRIMARY: "3b7472aeaf4f801ab6c24b777111445a0dcbb77b2be8e36e8d712cc2f9dc3dc9",
    SECONDARY: "8e8827b5b91420728f8415f3dc200fbf23b425ec07bf27cdc92a676367ee9edf",
}
IDENTITY = {
    CP: (100, "10.0.0.221", "02:42:00:00:01:00", 1),
    PRIMARY: (102, "10.0.0.222", "02:42:00:00:01:02", 2),
    SECONDARY: (103, "10.0.0.225", "02:42:00:00:01:03", 2),
}
CAPACITY = {CP: (2, 4, [100]), PRIMARY: (38, 112, [320, 1200]), SECONDARY: (38, 112, [320])}


def require(condition, description):
    if not condition:
        raise ValueError(description)


def load_vms(root, tfvars, extra=()):
    # Evaluate typed public inputs without initializing remote state or a provider.
    with tempfile.TemporaryDirectory(prefix="homelab-inputs-") as scratch:
        shutil.copyfile(root / "variables.tf", Path(scratch) / "variables.tf")
        result = subprocess.run(
            ["tofu", "-chdir=" + scratch, "console", "-no-color", "-var-file=" + str(tfvars), *extra],
            input="jsonencode(var.vms)\n", text=True, capture_output=True, check=True,
        )
    # Other tfvars entries belong to declarations outside variables.tf; OpenTofu
    # emits harmless undeclared-variable warnings before the encoded value.
    values = [line for line in result.stdout.splitlines() if line.startswith('"{')]
    require(len(values) == 1, "Expected exactly one encoded VM input value")
    return json.loads(json.loads(values[0]))


def check(primary_vms, secondary_vms, inventory, documents):
    require(set(primary_vms) == {PRIMARY}, "Primary PVE node set drift")
    require(set(secondary_vms) == {SECONDARY}, "Secondary PVE node set drift")
    laptop = json.loads((ROOT / "platform/main-control-plane/vm.json").read_text())
    require(laptop["owner"] == "ubuntu-qemu-systemd" and laptop["host"] == "10.0.0.181", "Laptop ownership drift")
    # VM ID here is historical identity only; the source must never return to the PVE map.
    cp = {**laptop, "vm_id": laptop["source_vm_id"], "startup_order": 1,
          "iso_file_id": "local:iso/talos-v1.13.9-qemu-amd64.iso"}
    vms = {CP: cp, **primary_vms, **secondary_vms}
    require({node["name"] for node in inventory["nodes"]} == set(vms) and len(inventory["nodes"]) == 3,
            "Talos and physical ownership inventories differ")
    require(inventory["kubernetes_version"] == "v1.36.3", "Kubernetes pin drift")
    require(inventory["endpoint"] == "https://10.0.0.231:6443" and inventory["talos_endpoint"] == "10.0.0.221",
            "Endpoint drift")
    for node in inventory["nodes"]:
        name, vm = node["name"], vms[node["name"]]
        is_cp = name == CP
        require((vm["vcpus"], vm["memory_gib"], vm["disks_gib"]) == CAPACITY[name], name + ": capacity drift")
        require((vm["vm_id"], vm["ipv4_address"], vm["mac_address"], vm["startup_order"]) == IDENTITY[name], name + ": identity drift")
        suffix = "qemu" if is_cp else "qemu-gvisor"
        require(vm["iso_file_id"] == f"local:iso/talos-v1.13.9-{suffix}-amd64.iso" and vm["guest_agent"], name + ": ISO/agent drift")
        require(vm["on_boot"], name + ": autostart drift")
        config, *extra = documents[name]
        machine, cluster = config["machine"], config["cluster"]
        require(machine["kubelet"].get("extraConfig", {}).get("serverTLSBootstrap") is True, name + ": serving certificate bootstrap missing")
        require(machine["type"] == ("controlplane" if is_cp else "worker"), name + ": role drift")
        require(machine["kubelet"]["image"].endswith(":v1.36.3"), name + ": kubelet version drift")
        require("workload.security/sandbox" not in machine["nodeLabels"] and
                "workload.security/sandbox" not in machine.get("nodeTaints", {}) and
                "workload.security/sandbox" not in machine["kubelet"].get("extraArgs", {}).get("register-with-taints", ""),
                name + ": obsolete sandbox isolation marker")
        require(machine["install"]["disk"] == "/dev/sda" and not machine["install"].get("wipe", False), name + ": unsafe OS disk")
        prefix = f"factory.talos.dev/metal-installer/{SCHEMATIC[name]}:v1.13.9@sha256:"
        require(machine["install"]["image"] == node["installer"] and machine["install"]["image"].startswith(prefix), name + ": installer drift")
        require(re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", node["installer"]) is not None,
                name + ": installer must have a complete SHA-256 digest")
        require(machine["certSANs"] == [vm["ipv4_address"]] and machine["kubelet"]["nodeIP"]["validSubnets"] == [vm["ipv4_address"] + "/32"], name + ": address drift")
        require(cluster["network"]["cni"]["name"] == "none" and not cluster["proxy"].get("disabled", False), name + ": CNI/proxy drift")
        require(cluster["controlPlane"]["endpoint"] == inventory["endpoint"] and not cluster.get("allowSchedulingOnControlPlanes", False), name + ": control-plane drift")
        labels = machine["nodeLabels"]
        require(labels.get("workload.security/" + ("trusted" if is_cp else "shared")) == "true", name + ": security label missing")
        if name == PRIMARY:
            require(machine.get("kernel", {}).get("modules") == [{"name": "binfmt_misc"}], name + ": ARM kernel module drift")
            require(machine.get("sysctls", {}).get("user.max_user_namespaces") == "11255", name + ": gVisor prerequisite drift")
            volumes = [item for item in extra if item.get("kind") == "UserVolumeConfig"]
            require(len(volumes) == 1 and volumes[0]["name"] == "local-path-provisioner" and
                    "disk.dev_path == '/dev/sdb'" in volumes[0]["provisioning"]["diskSelector"]["match"] and
                    "!system_disk" in volumes[0]["provisioning"]["diskSelector"]["match"],
                    "primary local storage must be preserved on the data disk")
            require(labels.get("homelab.tfdraw.dev/worker-role") == "primary" and labels.get("homelab.tfdraw.dev/storage") == "local-primary", "primary stable labels drift")
        if name == SECONDARY:
            require(labels.get("homelab.tfdraw.dev/worker-role") == "secondary" and "homelab.tfdraw.dev/storage" not in labels, "secondary stable labels drift")
            require(machine.get("sysctls", {}).get("user.max_user_namespaces") == "11255",
                    "secondary gVisor user-namespace prerequisite missing")
            require(not machine.get("registries", {}).get("mirrors"), "secondary registry mirrors are deferred")
            require(not machine.get("disks"), "secondary extra disk provisioning is deferred")
            require(not any(item.get("kind") in {"UserVolumeConfig", "RawVolumeConfig"} for item in extra),
                    "secondary local data volumes are deferred")
        if not is_cp:
            require(labels.get("homelab.tfdraw.dev/stateless-compute") == "true", name + ": stateless label missing")
        kinds = {item.get("kind"): item for item in extra}
        require(kinds["HostnameConfig"]["hostname"] == name, name + ": hostname drift")
        require(kinds["LinkAliasConfig"]["selector"]["match"] == f'mac(link.permanent_addr) == "{vm["mac_address"]}"', name + ": MAC drift")
        require(kinds["LinkConfig"]["addresses"] == [{"address": vm["ipv4_address"] + "/24"}] and kinds["LinkConfig"]["routes"] == [{"gateway": "10.0.0.1"}], name + ": static network drift")
        require(("Layer2VIPConfig" in kinds) == is_cp, name + ": VIP placement drift")
        if is_cp:
            require(kinds["Layer2VIPConfig"]["name"] == "10.0.0.231" and kinds["Layer2VIPConfig"]["link"] == "homelab", "VIP identity drift")
        require(not machine.get("network", {}).get("kubespan", {}).get("enabled", False) and "KubeSpanConfig" not in kinds, "KubeSpan unexpectedly enabled")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-dir", required=True, type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    generated = args.generated_dir.expanduser().resolve()
    require(ROOT not in generated.parents and generated != ROOT and generated.stat().st_mode & 0o077 == 0,
            "Generated configs must be private and outside the checkout")
    primary_vms = load_vms(ROOT / "live/proxmox/homelab", CONFIG.parent / "vms.tfvars")
    secondary_vms = load_vms(ROOT / "live/proxmox/homelab-secondary", CONFIG.parent / "secondary/vms.tfvars", ("-var=node_name=secondary-pve",))
    inventory, documents = json.loads((CONFIG / "cluster.json").read_text()), {}
    spec = importlib.util.spec_from_file_location("talos_generator", ROOT / "scripts/homelab-talos-config.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    binary = generator.cli()
    with tempfile.TemporaryDirectory(prefix="talos-validation-") as diagnostics:
        for node in inventory["nodes"]:
            path = generated / (node["name"] + ".machineconfig.yaml")
            require(not path.is_symlink() and path.stat().st_mode & 0o077 == 0, "Machine config permissions are too broad")
            generator.run(binary, ["validate", "--config", path, "--mode", "metal", "--strict"], Path(diagnostics) / "validation.log")
            documents[node["name"]] = list(yaml.safe_load_all(path.read_text()))
    check(primary_vms, secondary_vms, inventory, documents)
    client_path = generated / "talosconfig"
    require(not client_path.is_symlink() and client_path.stat().st_mode & 0o077 == 0, "Talos client config permissions are too broad")
    context = yaml.safe_load(client_path.read_text())["contexts"][inventory["name"]]
    require(context["endpoints"] == ["10.0.0.221"] and context["nodes"] == ["10.0.0.221"], "Talos client must use the control plane")
    for filename in ["talos-secrets.yaml", "talosconfig", *[name + ".machineconfig.yaml" for name in NODES]]:
        require(subprocess.run(["git", "check-ignore", "--quiet", "--no-index", filename], cwd=ROOT).returncode == 0, "Missing secret exclusion")
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    require(not any(Path(p).name in {"talos-secrets.yaml", "talosconfig"} or p.endswith(".machineconfig.yaml") for p in tracked), "Secret artifact is tracked")
    if args.self_test:
        changed = copy.deepcopy(documents)
        changed_inventory = copy.deepcopy(inventory)
        changed[SECONDARY][0]["machine"]["install"]["image"] = changed[SECONDARY][0]["machine"]["install"]["image"][:-1]
        for node in changed_inventory["nodes"]:
            if node["name"] == SECONDARY:
                node["installer"] = node["installer"][:-1]
        try:
            check(primary_vms, secondary_vms, changed_inventory, changed)
        except ValueError as error:
            require("complete SHA-256 digest" in str(error), "Digest self-test failed for an unrelated reason")
        else:
            raise ValueError("Validation self-test failed to reject a truncated installer digest")
        print("PASS: malformed installer digest rejected even when generated config matches inventory")
        changed = copy.deepcopy(documents)
        changed[SECONDARY][0]["machine"]["install"]["disk"] = "/dev/sdb"
        try:
            check(primary_vms, secondary_vms, inventory, changed)
        except ValueError:
            pass
        else:
            raise ValueError("Validation self-test failed to reject disk drift")
        for field, value in [("memory_gib", 113), ("disks_gib", [320, 200])]:
            changed_vms = copy.deepcopy(secondary_vms)
            changed_vms[SECONDARY][field] = value
            try:
                check(primary_vms, changed_vms, inventory, documents)
            except ValueError:
                pass
            else:
                raise ValueError("Validation self-test failed to reject " + field + " drift")
        for mutation in ("mirror", "volume", "storage-label", "gvisor-sysctl"):
            changed = copy.deepcopy(documents)
            machine = changed[SECONDARY][0]["machine"]
            if mutation == "mirror":
                machine["registries"] = {"mirrors": {"docker.io": {"endpoints": ["https://cache-registry.homelab.tfdraw.dev"]}}}
            elif mutation == "volume":
                changed[SECONDARY].append({"kind": "UserVolumeConfig", "name": "cache"})
            elif mutation == "storage-label":
                machine["nodeLabels"]["homelab.tfdraw.dev/storage"] = "local-secondary"
            else:
                machine["sysctls"]["user.max_user_namespaces"] = "0"
            try:
                check(primary_vms, secondary_vms, inventory, changed)
            except ValueError:
                pass
            else:
                raise ValueError("Validation self-test failed to reject secondary " + mutation)
        print("PASS: secondary OS disk, memory, cache disk, mirror, data volume, storage-label and gVisor prerequisite drift rejected")
    print("PASS: two-PVE, three-node capacities, identities, static networking, labels, and secret exclusions")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        print("FAIL: " + (str(error) if isinstance(error, ValueError) and not isinstance(error, yaml.YAMLError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)

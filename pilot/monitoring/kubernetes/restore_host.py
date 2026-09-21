"""Restore only the host exporter and localhost forwards from private recovery state."""

import argparse
import base64
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import BASE, PROFILE, get, identity, run
from install import reader, unit
from access import configure_forwards

ROOT = Path(__file__).resolve().parent


def restore(private):
    identity(admin=True)
    # Match the restored cluster's credentials without displaying their values.
    secret = get("secret", "host-telemetry", "-n", "pilot-monitoring", admin=True)[
        "data"
    ]
    for key, name in [("token", "host-token"), ("ca.crt", "host.crt")]:
        if (
            base64.b64decode(secret[key]).strip()
            != (private / name).read_bytes().strip()
        ):
            raise RuntimeError(
                "Private host credentials do not match the restored cluster"
            )
    if not (private / "host.key").is_file():
        raise RuntimeError("Missing host telemetry private key")
    for slot in PROFILE["slots"].values():
        if not (Path(slot["state"]).expanduser() / "desired.json").is_file():
            raise RuntimeError("Restore the host lifecycle state before the exporter")
    if (BASE / "private").exists():
        raise RuntimeError(
            "Host private directory already exists; refusing to overwrite it"
        )
    for name in ["source", "data/exporter", "config/proofs"]:
        (BASE / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copytree(private, BASE / "private")
    for path in (BASE / "private").rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    for filename in ["exporter.py", "common.py", "profile.json"]:
        shutil.copyfile(ROOT.parent / filename, BASE / "source" / filename)
    # The restricted kubeconfig uses absolute certificate paths; rebase them locally.
    config = BASE / "private/reader.kubeconfig"
    if config.exists():
        data = json.loads(config.read_text())
        for user in data["users"]:
            user["user"]["client-certificate"] = str(BASE / "private/reader.crt")
            user["user"]["client-key"] = str(BASE / "private/reader.key")
        for cluster in data["clusters"]:
            if "certificate-authority" in cluster["cluster"]:
                cluster["cluster"]["certificate-authority"] = str(
                    BASE / "private/ca.crt"
                )
        config.write_text(json.dumps(data))
    reader()  # Renews the restricted client if expired; never installs host monitoring.
    (BASE / "kubernetes-mode").touch()
    unit("exporter", f"/usr/bin/python3 {BASE}/source/exporter.py")
    configure_forwards()
    run(["systemctl", "--user", "enable", "--now", "pilot-exporter"])
    print(
        "Host exporter and localhost forwards restored; run health and acceptance checks"
    )


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "private", type=Path, help="Recovery backup's host-monitoring-private directory"
    )
    restore(parser.parse_args().private.expanduser())

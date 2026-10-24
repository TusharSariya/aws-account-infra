#!/usr/bin/env python3
"""Deploy reviewed controller sources through a fixed, frozen-host SSH receiver."""

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

PACKAGE = "controllers/homelab-capacity/src/homelab_capacity/"
EXTRAS = {
    "platform/automatic-power/pve-helper.py",
    "platform/automatic-power/install-pve-helper.py",
    "platform/automatic-power/deploy.py",
}


def digest(data):
    return hashlib.sha256(data.encode()).hexdigest()


def validate(payload):
    if not re.fullmatch(r"[0-9a-f]{40}", payload["revision"]):
        raise ValueError("Expected a full Git commit ID")
    files = payload["files"]
    if not EXTRAS.issubset(files) or PACKAGE + "coordinator.py" not in files:
        raise ValueError("Incomplete deployment")
    for name, data in files.items():
        if name not in EXTRAS and not re.fullmatch(
            re.escape(PACKAGE) + r"[a-z_]+\.py", name
        ):
            raise ValueError("Unexpected deployment path")
        if digest(data) != payload["hashes"][name]:
            raise ValueError("Source checksum mismatch")
        compile(data, name, "exec")
    return files


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, timeout=180, **kwargs)


def receive(payload):
    files = validate(payload)
    home = Path.home()
    base = home / ".local/share/homelab-capacity"
    source = base / "retained/src/homelab_capacity"
    config = json.loads(
        (home / ".config/homelab-capacity/coordinator.json").read_text()
    )
    power = json.loads(Path(config["power_config"]).expanduser().read_text())
    sys.path.insert(0, str(source.parent))
    from homelab_capacity.interlock import Interlock

    release = base / "releases" / (payload["revision"] + "-" + uuid.uuid4().hex[:8])
    release.mkdir(mode=0o700, parents=True)
    for name, data in files.items():
        p = release / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)
    locks = [Interlock(power["lock_dir"], h) for h in ("primary", "secondary")]
    with contextlib.ExitStack() as stack:
        for lock in locks:
            stack.enter_context(lock.locked())
            record = lock.read()
            if record["pending"] or not any(
                token.startswith("ci-freeze-") and hold["acknowledged"]
                for token, hold in record["holds"].items()
            ):
                raise RuntimeError("Both hosts require acknowledged CI freezes")
        shutil.copytree(source, release / "before-source")
        run("systemctl", "--user", "stop", "homelab-coordinator.service")
        try:
            staged = release / "new-package"
            staged.mkdir()
            for name, data in files.items():
                if name.startswith(PACKAGE):
                    (staged / Path(name).name).write_text(data)
            old_source = release / "replaced-package"
            source.rename(old_source)
            try:
                staged.rename(source)
            except BaseException:
                old_source.rename(source)
                raise
            helper = release / "platform/automatic-power/install-pve-helper.py"
            for host in ("primary", "secondary"):
                run("python3", str(helper), host)
            for name, data in files.items():
                if name.startswith(PACKAGE) and digest(
                    (source / Path(name).name).read_text()
                ) != digest(data):
                    raise RuntimeError("Installed source differs")
            for address in ("10.0.0.224", "10.0.0.223"):
                result = run(
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-i",
                    str(home / ".ssh/main-proxmox"),
                    "root@" + address,
                    "sha256sum /usr/local/lib/homelab-power/helper.py",
                    capture_output=True,
                )
                if (
                    result.stdout.split()[0]
                    != payload["hashes"]["platform/automatic-power/pve-helper.py"]
                ):
                    raise RuntimeError("Installed Proxmox helper differs")
        finally:
            # Failures retain the durable CI freeze, never leave the service stopped.
            run("systemctl", "--user", "start", "homelab-coordinator.service")
    time.sleep(5)
    run("systemctl", "--user", "is-active", "--quiet", "homelab-coordinator.service")
    receipt = {
        "revision": payload["revision"],
        "hashes": payload["hashes"],
        "verified_at": time.time(),
    }
    (base / "deployed.json").write_text(json.dumps(receipt, indent=2) + "\n")
    receiver = base / "ci-deploy.py"
    temporary = receiver.with_suffix(".new")
    temporary.write_text(files["platform/automatic-power/deploy.py"])
    temporary.chmod(0o700)
    temporary.replace(receiver)
    print(json.dumps(receipt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receive", action="store_true")
    parser.add_argument("--target")
    parser.add_argument("--ssh-config", required=False)
    args = parser.parse_args()
    os.umask(0o077)
    if args.receive:
        receive(json.loads(sys.stdin.read(2_000_001)))
        return
    if not args.target:
        parser.error("--target is required")
    root = Path(__file__).resolve().parents[2]
    run(
        "git",
        "-C",
        str(root),
        "diff",
        "--quiet",
        "HEAD",
        "--",
        PACKAGE,
        *sorted(EXTRAS),
    )
    revision = run(
        "git", "-C", str(root), "rev-parse", "HEAD", capture_output=True
    ).stdout.strip()
    files = {
        p.relative_to(root).as_posix(): p.read_text()
        for p in (root / PACKAGE).glob("*.py")
    }
    files.update({name: (root / name).read_text() for name in EXTRAS})
    payload = {
        "revision": revision,
        "files": files,
        "hashes": {n: digest(s) for n, s in files.items()},
    }
    validate(payload)
    options = ["-F", args.ssh_config] if args.ssh_config else []
    result = run(
        "ssh",
        *options,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=15",
        args.target,
        input=json.dumps(payload),
        capture_output=True,
    )
    print(result.stdout)


if __name__ == "__main__":
    main()

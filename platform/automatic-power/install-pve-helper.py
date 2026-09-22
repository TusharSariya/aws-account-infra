#!/usr/bin/env python3
"""Install a fixed forced-command key on registered Proxmox hosts from the laptop."""

import argparse
import json
from pathlib import Path
import re
import subprocess

HOSTS = {
    "primary": ("10.0.0.224", 102, "2ae5ec87-3879-4a3a-a90d-ca017642dbe8"),
    "secondary": ("10.0.0.223", 103, "58203485-9d12-4205-9345-ca4e96148c65"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", choices=HOSTS)
    args = parser.parse_args()
    address, vm, uuid = HOSTS[args.host]
    private = Path.home() / ".config/homelab-capacity"
    key = private / "retained-pve"
    if not key.exists():
        subprocess.run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(key),
                "-C",
                "homelab-retained-power",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    public = key.with_suffix(".pub").read_text().strip()
    if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+ homelab-retained-power", public):
        raise ValueError("Unexpected coordinator public key")
    payload = {
        "helper": Path(__file__).with_name("pve-helper.py").read_text(),
        "config": {"vm": vm, "system_uuid": uuid},
        "key": public,
    }
    # Fixed bootstrap program only; the generated key is then forced to helper.py.
    installer = r"""
import json,sys,pathlib,os
p=json.load(sys.stdin)
b=pathlib.Path('/usr/local/lib/homelab-power'); b.mkdir(mode=0o755,exist_ok=True)
h=b/'helper.py'; h.write_text(p['helper']); h.chmod(0o755)
c=pathlib.Path('/etc/homelab-power.json')
if c.exists():
    assert json.loads(c.read_text()) == p['config'], 'Refusing changed host identity'
c.write_text(json.dumps(p['config'])+'\n'); c.chmod(0o600)
a=pathlib.Path('/root/.ssh/authorized_keys'); old=a.read_text()
line='restrict,command="/usr/local/lib/homelab-power/helper.py" '+p['key']
existing=[x for x in old.splitlines() if p['key'].split()[1] in x]
assert not existing or existing == [line], 'Existing key has different restrictions'
if not existing:
    with a.open('a') as f: f.write(('\n' if old and not old.endswith('\n') else '')+line+'\n')
a.chmod(0o600)
"""
    import shlex

    subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
            "-i",
            str(Path.home() / ".ssh/main-proxmox"),
            "root@" + address,
            "python3 -c " + shlex.quote(installer),
        ],
        input=json.dumps(payload),
        text=True,
        check=True,
        timeout=40,
    )
    print("Installed fixed retained-worker management on " + args.host)


if __name__ == "__main__":
    main()

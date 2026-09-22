#!/usr/bin/env python3
"""One-time quiesced Pi-hole copy; preserves the worker claim and private recovery.
Run only after u-pihole is verified mounted and the retained destination is Bound.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

IMAGE = "python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6"
NS = "homelab-services"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    args.journal.mkdir(mode=0o700, parents=True, exist_ok=False)
    k = ["kubectl", "--kubeconfig", args.kubeconfig, "--request-timeout=30s"]

    def run(*cmd, data=None):
        return subprocess.check_output(k + list(cmd), input=data, timeout=360)

    def get(resource, name, namespace=NS):
        return json.loads(run("get", resource, name, "-n", namespace, "-o", "json"))

    original = get("deployment", "pihole")
    source = get("pvc", "pihole")
    target = get("pvc", "pihole-laptop")
    assert source["metadata"]["uid"] == "7738ef98-4f83-4e86-89ac-119b6676ad62"
    assert (
        target["status"]["phase"] == "Bound"
        and target["spec"]["volumeName"] == "laptop-pihole"
    )
    assert original["spec"]["replicas"] == 1
    podspec = original["spec"]["template"]["spec"]
    volume = next(v for v in podspec["volumes"] if v["name"] == "config")
    assert volume["persistentVolumeClaim"]["claimName"] == "pihole"
    assert (
        source["metadata"].get("annotations", {}).get("helm.sh/resource-policy")
        == "keep"
    )
    for name, value in [
        ("deployment", original),
        ("source", source),
        ("destination", target),
    ]:
        (args.journal / (name + ".json")).write_text(json.dumps(value, indent=2))
    (args.journal / "intent.json").write_text(json.dumps({"phase": "quiescing"}))
    patch = [
        {"op": "test", "path": "/metadata/uid", "value": original["metadata"]["uid"]},
        {
            "op": "test",
            "path": "/metadata/resourceVersion",
            "value": original["metadata"]["resourceVersion"],
        },
        {"op": "replace", "path": "/spec/replicas", "value": 0},
    ]
    run(
        "-n",
        NS,
        "patch",
        "deployment",
        "pihole",
        "--type=json",
        "-p",
        json.dumps(patch),
    )
    run(
        "-n",
        NS,
        "wait",
        "pods",
        "-l",
        "app=pihole,release=pihole",
        "--for=delete",
        "--timeout=180s",
    )
    for suffix, node, claim, readonly in [
        ("source", "talos-worker-01", "pihole", True),
        ("destination", "talos-cp-01", "pihole-laptop", False),
    ]:
        pod = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"namespace": NS, "name": "pihole-copy-" + suffix},
            "spec": {
                "restartPolicy": "Never",
                "automountServiceAccountToken": False,
                "nodeSelector": {"kubernetes.io/hostname": node},
                "tolerations": [
                    {
                        "key": "node-role.kubernetes.io/control-plane",
                        "operator": "Exists",
                        "effect": "NoSchedule",
                    }
                ],
                "containers": [
                    {
                        "name": "copy",
                        "image": IMAGE,
                        "command": ["python", "-c", "import time; time.sleep(3600)"],
                        "resources": {
                            "requests": {"cpu": "50m", "memory": "64Mi"},
                            "limits": {"cpu": "500m", "memory": "128Mi"},
                        },
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": True,
                        },
                        "volumeMounts": [
                            {"name": "data", "mountPath": "/data", "readOnly": readonly}
                        ],
                    }
                ],
                "volumes": [
                    {
                        "name": "data",
                        "persistentVolumeClaim": {
                            "claimName": claim,
                            "readOnly": readonly,
                        },
                    }
                ],
            },
        }
        run("create", "-f", "-", data=json.dumps(pod).encode())
        run(
            "-n",
            NS,
            "wait",
            "pod/pihole-copy-" + suffix,
            "--for=condition=Ready",
            "--timeout=180s",
        )
    assert (
        run(
            "-n",
            NS,
            "exec",
            "pihole-copy-destination",
            "--",
            "python",
            "-c",
            'from pathlib import Path; print(len(list(Path("/data").iterdir())))',
        ).strip()
        == b"0"
    ), "Destination is not empty"
    archive = args.journal / "pihole.tar"
    with archive.open("wb") as out:
        subprocess.run(
            k
            + [
                "-n",
                NS,
                "exec",
                "pihole-copy-source",
                "--",
                "tar",
                "--numeric-owner",
                "-cpf",
                "-",
                "-C",
                "/data",
                ".",
            ],
            stdout=out,
            check=True,
            timeout=180,
        )
    (args.journal / "archive.sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "\n"
    )
    with archive.open("rb") as src:
        subprocess.run(
            k
            + [
                "-n",
                NS,
                "exec",
                "-i",
                "pihole-copy-destination",
                "--",
                "tar",
                "--numeric-owner",
                "-xpf",
                "-",
                "-C",
                "/data",
            ],
            stdin=src,
            check=True,
            timeout=180,
        )
    digest = 'import hashlib,json,pathlib; root=pathlib.Path("/data"); print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()},sort_keys=True))'
    hashes = [
        run("-n", NS, "exec", "pihole-copy-" + suffix, "--", "python", "-c", digest)
        for suffix in ["source", "destination"]
    ]
    assert hashes[0] == hashes[1], "Copied file hashes differ"
    (args.journal / "files.json").write_bytes(hashes[0])
    for suffix in ["source", "destination"]:
        run(
            "-n",
            NS,
            "delete",
            "pod",
            "pihole-copy-" + suffix,
            "--wait=true",
            "--timeout=60s",
        )
    (args.journal / "intent.json").write_text(
        json.dumps({"phase": "copied", "files_verified": True})
    )
    print(
        "Consistent Pi-hole data copied and checksummed. Source remains retained; apply the reviewed Helm claim/placement cutover next."
    )


if __name__ == "__main__":
    main()

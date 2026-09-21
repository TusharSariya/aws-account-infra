"""Approve only the pinned control plane's serving CSR during explicit maintenance."""

import base64
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "monitoring"))
from common import get, identity, kubectl, run

NODE = "talos-v93-t3u"


def approve():
    identity(admin=True)
    for csr in get("csr", admin=True)["items"]:
        spec = csr["spec"]
        if (
            spec["signerName"] != "kubernetes.io/kubelet-serving"
            or spec["username"] != "system:node:" + NODE
        ):
            continue
        if csr.get("status", {}).get("conditions"):
            continue
        if set(spec["usages"]) not in [
            {"digital signature", "server auth"},
            {"digital signature", "key encipherment", "server auth"},
        ]:
            raise RuntimeError("Unexpected control-plane CSR usages")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.pem"
            path.write_bytes(base64.b64decode(spec["request"]))
            detail = run(
                ["openssl", "req", "-in", str(path), "-noout", "-text", "-verify"]
            )
            subject = run(
                [
                    "openssl",
                    "req",
                    "-in",
                    str(path),
                    "-noout",
                    "-subject",
                    "-nameopt",
                    "RFC2253",
                ]
            ).strip()
        dns = set(re.findall(r"DNS:([^,\s]+)", detail))
        ips = set(re.findall(r"IP Address:([^,\s]+)", detail))
        if (
            dns != {NODE}
            or ips != {"10.0.2.15"}
            or subject != "subject=CN=system:node:" + NODE + ",O=system:nodes"
        ):
            raise RuntimeError("Unexpected control-plane serving CSR identity/SANs")
        identity(admin=True)
        kubectl("certificate", "approve", csr["metadata"]["name"], admin=True)
        print(
            "Approved the verified control-plane kubelet serving certificate",
            flush=True,
        )


if __name__ == "__main__":
    approve()

"""Approve serving renewal only for accepted, fixed node identities and SANs.

Initial client bootstrap remains explicitly inspected by an operator. Kubernetes
handles client rotation through the node-scoped selfnodeclient binding.
"""

import base64
import datetime
import ipaddress
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

SIGNER = "kubernetes.io/kubelet-serving"


def valid_serving_request(csr, profile, node):
    spec = csr["spec"]
    if (
        not profile.get("acceptedNodeUID")
        or not node
        or node["metadata"]["uid"] != profile["acceptedNodeUID"]
        or spec.get("signerName") != SIGNER
        or spec.get("username") != "system:node:" + profile["node"]
        or "system:nodes" not in spec.get("groups", [])
        or any(
            c["type"] in {"Approved", "Denied", "Failed"}
            for c in csr.get("status", {}).get("conditions", [])
        )
    ):
        return False
    usages = set(spec.get("usages", []))
    if (
        not {"digital signature", "server auth"}
        <= usages
        <= {"digital signature", "server auth", "key encipherment"}
    ):
        return False
    duration = spec.get("expirationSeconds", 86400)
    if not 600 <= duration <= 31536000:
        return False
    try:
        request = x509.load_pem_x509_csr(
            base64.b64decode(spec["request"], validate=True)
        )
        if not request.is_signature_valid:
            return False
        expected = x509.Name(
            [
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "system:nodes"),
                x509.NameAttribute(
                    NameOID.COMMON_NAME, "system:node:" + profile["node"]
                ),
            ]
        )
        if sorted((a.oid.dotted_string, a.value) for a in request.subject) != sorted(
            (a.oid.dotted_string, a.value) for a in expected
        ):
            return False
        key = request.public_key()
        if not (
            isinstance(key, rsa.RSAPublicKey)
            and key.key_size >= 2048
            or isinstance(key, ec.EllipticCurvePublicKey)
            and key.key_size >= 256
        ):
            return False
        names = request.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        for extension in request.extensions:
            if not isinstance(extension.value, x509.SubjectAlternativeName):
                return False
        allowed_ip = ipaddress.ip_address(profile["nodeIP"])
        if not names:
            return False
        for name in names:
            if isinstance(name, x509.DNSName):
                if name.value != profile["node"]:
                    return False
            elif isinstance(name, x509.IPAddress):
                if name.value != allowed_ip:
                    return False
            else:
                return False
        return True
    except (ValueError, KeyError, TypeError, x509.ExtensionNotFound):
        return False


def reconcile_serving(kube, profiles):
    accepted = {
        p["node"]: p for p in profiles if p.get("acceptedNodeUID") and p.get("nodeIP")
    }
    if not accepted:
        return
    nodes = {name: kube.call("/api/v1/nodes/" + name) for name in accepted}
    base = "/apis/certificates.k8s.io/v1/certificatesigningrequests"
    for csr in kube.call(base)["items"]:
        name = csr["spec"].get("username", "").removeprefix("system:node:")
        if name not in accepted or not valid_serving_request(
            csr, accepted[name], nodes[name]
        ):
            continue
        conditions = csr.get("status", {}).get("conditions", []) + [
            {
                "type": "Approved",
                "status": "True",
                "reason": "AcceptedUbuntuNode",
                "message": "Serving CSR matches accepted node UID, identity and fixed SANs",
                "lastUpdateTime": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            }
        ]
        kube.call(
            base + "/" + csr["metadata"]["name"] + "/approval",
            "PATCH",
            [
                {
                    "op": "test",
                    "path": "/metadata/uid",
                    "value": csr["metadata"]["uid"],
                },
                {
                    "op": "test",
                    "path": "/metadata/resourceVersion",
                    "value": csr["metadata"]["resourceVersion"],
                },
                {
                    "op": "add",
                    "path": "/status",
                    "value": {**csr.get("status", {}), "conditions": conditions},
                },
            ],
        )

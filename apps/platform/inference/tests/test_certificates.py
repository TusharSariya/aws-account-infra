import base64
import ipaddress
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from certificates import valid_serving_request
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest


def request(ip="10.0.0.226", dns="ubuntu-gpu-01"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(
                        NameOID.COMMON_NAME, "system:node:ubuntu-gpu-01"
                    ),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "system:nodes"),
                ]
            )
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(dns), x509.IPAddress(ipaddress.ip_address(ip))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return {
        "spec": {
            "signerName": "kubernetes.io/kubelet-serving",
            "username": "system:node:ubuntu-gpu-01",
            "groups": ["system:nodes"],
            "usages": ["digital signature", "key encipherment", "server auth"],
            "request": base64.b64encode(
                csr.public_bytes(serialization.Encoding.PEM)
            ).decode(),
        }
    }


PROFILE = {
    "node": "ubuntu-gpu-01",
    "nodeIP": "10.0.0.226",
    "acceptedNodeUID": "accepted",
}
NODE = {"metadata": {"uid": "accepted"}}


def test_serving_rotation_for_verified_node_only():
    assert valid_serving_request(request(), PROFILE, NODE)


@pytest.mark.parametrize(
    "field,value",
    [
        ("username", "system:node:attacker"),
        ("signerName", "kubernetes.io/kube-apiserver-client"),
        ("usages", ["client auth"]),
        ("request", "invalid"),
    ],
)
def test_reject_wrong_identity_signer_usage_or_encoding(field, value):
    csr = request()
    csr["spec"][field] = value
    assert not valid_serving_request(csr, PROFILE, NODE)


def test_reject_extra_names_and_replaced_node():
    assert not valid_serving_request(request(ip="10.0.0.221"), PROFILE, NODE)
    assert not valid_serving_request(request(dns="*.example.com"), PROFILE, NODE)
    assert not valid_serving_request(
        request(), PROFILE, {"metadata": {"uid": "replacement"}}
    )
    csr = request()
    csr["status"] = {"conditions": [{"type": "Denied"}]}
    assert not valid_serving_request(csr, PROFILE, NODE)

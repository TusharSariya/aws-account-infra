"""Safety contracts for portable-pilot manifests and acceptance gates."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "monitoring"))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


render = module("portable_render", ROOT / "monitoring/kubernetes/render.py")
argo = module("portable_argo", ROOT / "argocd/bootstrap.py")


tls = module("portable_tls", ROOT / "vm/kubelet_tls.py")


class PortableTests(unittest.TestCase):
    def test_serving_csr_approval_is_limited_to_pinned_identity(self):
        csr = {
            "metadata": {"name": "test-csr"},
            "spec": {
                "signerName": "kubernetes.io/kubelet-serving",
                "username": "system:node:talos-v93-t3u",
                "usages": ["digital signature", "server auth"],
                "request": "cHVibGljLWNzcg==",
            },
        }
        with (
            patch.object(tls, "identity"),
            patch.object(tls, "get", return_value={"items": [csr]}),
            patch.object(
                tls,
                "run",
                side_effect=[
                    "DNS:talos-v93-t3u, IP Address:10.0.2.15",
                    "subject=CN=system:node:talos-v93-t3u,O=system:nodes",
                ],
            ),
            patch.object(tls, "kubectl") as write,
        ):
            tls.approve()
            write.assert_called_once_with(
                "certificate", "approve", "test-csr", admin=True
            )
        with (
            patch.object(tls, "identity"),
            patch.object(tls, "get", return_value={"items": [csr]}),
            patch.object(
                tls,
                "run",
                side_effect=[
                    "DNS:talos-v93-t3u, IP Address:10.0.0.1",
                    "subject=CN=system:node:talos-v93-t3u,O=system:nodes",
                ],
            ),
            patch.object(tls, "kubectl") as write,
        ):
            with self.assertRaisesRegex(RuntimeError, "identity/SANs"):
                tls.approve()
            write.assert_not_called()
        csr["spec"]["username"] = "system:node:foreign"
        with (
            patch.object(tls, "identity"),
            patch.object(tls, "get", return_value={"items": [csr]}),
            patch.object(tls, "kubectl") as write,
        ):
            tls.approve()
            write.assert_not_called()

    def test_storage_is_exclusively_retained_and_prebound_to_management(self):
        objects = render.render()
        pvs = [o for o in objects if o["kind"] == "PersistentVolume"]
        self.assertEqual(len(pvs), 5)
        for pv in pvs:
            spec = pv["spec"]
            name = spec["claimRef"]["name"]
            self.assertEqual(spec["capacity"]["storage"], render.SIZES[name])
            self.assertEqual(spec["persistentVolumeReclaimPolicy"], "Retain")
            self.assertEqual(spec["local"]["path"], "/var/mnt/pilot-" + name)
            self.assertEqual(
                spec["nodeAffinity"]["required"]["nodeSelectorTerms"][0][
                    "matchExpressions"
                ][0]["values"],
                [render.NODE],
            )

    def test_no_administrative_credential_or_public_service_in_pods(self):
        for obj in render.render():
            if obj["kind"] == "Service":
                self.assertEqual(obj["spec"]["type"], "ClusterIP")
            if obj["kind"] == "Deployment":
                pod = obj["spec"]["template"]["spec"]
                name = obj["metadata"]["name"]
                self.assertEqual(
                    pod["automountServiceAccountToken"], name in ["alloy", "prometheus"]
                )
                self.assertNotIn("hostPath", json.dumps(pod))
                self.assertNotIn("kubeconfig", json.dumps(pod))
                self.assertFalse(pod.get("hostNetwork", False))
                self.assertIn("@sha256:", pod["containers"][0]["image"])

    def test_scoped_log_reader_cannot_read_secrets_or_mutate(self):
        roles = [
            o
            for o in render.render()
            if o["kind"] == "Role" and o["metadata"]["name"] == "pilot-log-reader"
        ]
        self.assertEqual(
            {r["metadata"]["namespace"] for r in roles}, {"prototype-slot", "pilot-app"}
        )
        for r in roles:
            self.assertEqual(r["rules"][0]["resources"], ["pods", "pods/log"])
            self.assertEqual(r["rules"][0]["verbs"], ["get", "list", "watch"])
        configs = {
            o["metadata"]["name"]: o["data"]
            for o in render.render()
            if o["kind"] == "ConfigMap"
        }
        self.assertIn("pilot-observe", configs["alloy"]["alloy.alloy"])
        self.assertNotIn("kubeconfig", configs["alloy"]["alloy.alloy"])
        self.assertNotIn("loki.source.journal", configs["alloy"]["alloy.alloy"])

    def test_no_application_or_repository_secret_in_core_bootstrap(self):
        with (
            patch.object(argo, "gate"),
            patch.object(argo, "identity"),
            patch.object(argo, "kubectl") as calls,
        ):
            argo.bootstrap()
        for call in calls.call_args_list:
            self.assertNotIn("application.yaml", " ".join(call.args))
            self.assertNotIn("pilot-git-repository", call.kwargs.get("data", ""))
        self.assertNotIn(
            "kind: Application\n", (ROOT / "argocd/project.yaml").read_text()
        )
        self.assertFalse(argo.capacity([]))

    def test_resource_budgets_are_preserved(self):
        pods = {
            o["metadata"]["name"]: o["spec"]["template"]["spec"]["containers"][0]
            for o in render.render()
            if o["kind"] == "Deployment"
        }
        for name, memory, cpu, requested in [
            ("prometheus", 384, 150, 128),
            ("loki", 384, 100, 128),
            ("alloy", 256, 100, 64),
            ("grafana", 512, 100, 256),
            ("alertmanager", 96, 50, 32),
        ]:
            self.assertEqual(
                pods[name]["resources"],
                {
                    "requests": {"cpu": f"{cpu}m", "memory": f"{requested}Mi"},
                    "limits": {"cpu": "1", "memory": f"{memory}Mi"},
                },
            )


if __name__ == "__main__":
    unittest.main()

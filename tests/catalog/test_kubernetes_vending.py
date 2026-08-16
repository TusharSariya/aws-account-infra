import copy
import importlib.util
import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("kubernetes_vending", ROOT / "scripts/kubernetes-vending.py")
vending = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(vending)


def resources(phase="all"):
    return vending.render_target("homelab", phase=phase)


def test_native_bundle_has_fail_closed_baseline_and_no_tenant_storage():
    native = resources("native")
    kinds = {item["kind"] for item in native}
    assert "ValidatingAdmissionPolicy" in kinds
    assert "ValidatingAdmissionPolicyBinding" in kinds
    assert "PersistentVolumeClaim" not in kinds
    policy = next(item for item in native if item["kind"] == "ValidatingAdmissionPolicy")
    assert policy["spec"]["failurePolicy"] == "Fail"
    assert any("kind is platform-owned or prohibited" in check["message"] for check in policy["spec"]["validations"])
    binding = next(item for item in native if item["kind"] == "ValidatingAdmissionPolicyBinding")
    assert binding["spec"]["validationActions"] == ["Deny"]


def test_namespaces_pin_restricted_psa_and_start_default_denied():
    native = resources("native")
    namespaces = [item for item in native if item["kind"] == "Namespace"]
    assert namespaces
    for namespace in namespaces:
        labels = namespace["metadata"]["labels"]
        assert labels["pod-security.kubernetes.io/enforce"] == "restricted"
        assert labels["pod-security.kubernetes.io/enforce-version"] == "v1.35"
        name = namespace["metadata"]["name"]
        assert any(
            item["kind"] == "NetworkPolicy"
            and item["metadata"].get("namespace") == name
            and item["metadata"]["name"] == "default-deny"
            for item in native
        )


def test_argocd_default_project_is_locked_and_projects_are_allowlists():
    argo = resources("argocd")
    default = next(item for item in argo if item["kind"] == "AppProject" and item["metadata"]["name"] == "default")
    assert default["spec"] == {
        "sourceRepos": [], "destinations": [], "clusterResourceWhitelist": [], "namespaceResourceWhitelist": []
    }
    forbidden = {"Secret", "PersistentVolumeClaim", "NetworkPolicy", "Role", "RoleBinding", "ServiceMonitor"}
    for project in [item for item in argo if item["kind"] == "AppProject" and item["metadata"]["name"] != "default"]:
        allowed = {entry["kind"] for entry in project["spec"]["namespaceResourceWhitelist"]}
        assert not (allowed & forbidden)
        assert "*" not in allowed


def test_active_routes_use_exact_https_listener_and_same_namespace_backend():
    native = resources("native")
    routes = [item for item in native if item["kind"] == "HTTPRoute"]
    assert routes
    for route in routes:
        assert len(route["spec"]["hostnames"]) == 1
        assert route["spec"]["parentRefs"][0]["sectionName"] == "https"
        assert "namespace" not in route["spec"]["rules"][0]["backendRefs"][0]


def test_argo_sync_is_pruning_self_healing_and_bounded():
    applications = [item for item in resources("argocd") if item["kind"] == "Application"]
    assert applications
    for application in applications:
        policy = application["spec"]["syncPolicy"]
        assert policy["automated"]["prune"] is True
        assert policy["automated"]["selfHeal"] is True
        assert policy["retry"]["limit"] == 5


def test_suspended_target_has_no_route_or_application():
    catalog_data = vending.service_catalog.build_catalog()
    service = copy.deepcopy(catalog_data["services"]["court-booker"])
    service["kubernetes"]["homelab"]["lifecycle"] = "suspended"
    rendered = vending.tenant_resources(
        "court-booker", service, "homelab", catalog_data["kubernetes_clusters"]["homelab"]
    )
    assert not any(item["kind"] in {"HTTPRoute", "Application"} for item in rendered)
    namespace = next(item for item in rendered if item["kind"] == "Namespace")
    assert namespace["metadata"]["labels"][vending.ACTIVE_LABEL] == "false"


def test_catalog_fqdn_egress_is_exact_and_https_only():
    catalog_data = vending.service_catalog.build_catalog()
    service = copy.deepcopy(catalog_data["services"]["court-booker"])
    service["kubernetes"]["homelab"]["egress"]["dns_names"] = ["api.example.com"]
    rendered = vending.tenant_resources(
        "court-booker", service, "homelab", catalog_data["kubernetes_clusters"]["homelab"]
    )
    policy = next(item for item in rendered if item["kind"] == "CiliumNetworkPolicy")
    assert policy["spec"]["egress"][0]["toFQDNs"] == [{"matchName": "api.example.com"}]
    assert policy["spec"]["egress"][0]["toPorts"][0]["ports"] == [
        {"port": "443", "protocol": "TCP"}
    ]


def test_generated_manifests_contain_contracts_but_no_secret_values():
    native_text = (ROOT / "ansible/roles/kubernetes_tenants/files/homelab-native.yaml").read_text()
    assert "court-booker-credentials" in native_text
    assert "kind: Secret\n" not in native_text
    list(yaml.safe_load_all(native_text))


def test_live_capacity_fails_closed_when_headroom_is_insufficient(monkeypatch):
    catalog_data = vending.service_catalog.build_catalog()
    node = {
        "items": [{"status": {"allocatable": {
            "cpu": "2500m", "memory": "6Gi", "ephemeral-storage": "16Gi", "pods": "45"
        }}}]
    }
    responses = [node, {"items": []}]

    def fake_kubectl(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(responses.pop(0)), stderr="")

    monkeypatch.setattr(vending, "_kubectl", fake_kubectl)
    try:
        vending._verify_live_capacity("unused", "homelab", catalog_data)
    except vending.ReconcilePending as exc:
        assert "below reviewed budget" in str(exc)
    else:
        raise AssertionError("insufficient live capacity must leave reconciliation pending")

import copy
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("service_catalog", ROOT / "scripts/service-catalog.py")
catalog = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(catalog)


def test_catalog_is_valid_and_deterministic():
    rendered = catalog.build_catalog()
    assert rendered["version"] == 2
    assert set(rendered["services"]) == {"court-booker", "platform"}
    assert set(rendered["kubernetes_clusters"]) == {"homelab"}
    assert rendered["services"]["court-booker"]["kubernetes"]["homelab"]["gpu_mode"] == "none"
    assert all(len(service_id) <= 57 for service_id in rendered["services"])
    assert rendered["services"]["court-booker"]["repository"]["spec_layout"] == "root"
    assert rendered["services"]["platform"]["repository"]["spec_layout"] == "product"
    assert rendered["services"]["court-booker"]["repository"]["agent_data_access"] == "none"


def test_v1_and_v2_normalize_to_the_same_internal_shape():
    v1 = catalog.load_manifest(ROOT / "catalog/services/court-booker.yaml")
    v2 = catalog.normalize_manifest(v1)
    already_v2 = copy.deepcopy(v2)
    assert catalog.normalize_manifest(already_v2) == v2
    assert v2["version"] == 2
    assert v2["provisioner"] == "service-v2"
    assert v2["external_services"] == {}
    assert v2["repository"]["required_status_checks"] == ["test", "tofu-plan"]


def test_v2_allows_external_only_service(tmp_path):
    manifest = {
        "version": 2,
        "provisioner": "service-v2",
        "service": {
            "uid": "4fa03054-6f90-4f96-bd58-b9b6c08aa07c",
            "id": "auth-canary",
            "display_name": "Auth Canary",
            "owner": "platform",
        },
        "repository": {
            "identity": "TusharSariya/auth-canary",
            "name": "auth-canary",
            "visibility": "private",
            "template": "service-stack-template",
            "migration": "template",
            "protection_profile": "service",
            "spec_layout": "root",
            "required_status_checks": ["test"],
            "agent_data_access": "none",
        },
        "accounts": {},
        "kubernetes": {},
        "external_services": {
            "supabase": {
                "lifecycle": "active",
                "organization_id": "example-org",
                "project_name": "auth-canary",
                "project_ref": None,
                "region": "us-east-1",
                "plan": "free",
                "storage": "disabled",
                "backup_profile": "none",
                "auth": {
                    "mode": "operator-only",
                    "site_url": "https://auth-canary.example.com",
                    "redirect_urls": ["https://auth-canary.example.com/auth/callback"],
                    "public_signup": False,
                },
            }
        },
    }
    path = tmp_path / "auth-canary.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    assert catalog.load_manifest(path) == manifest


def test_committed_v2_canary_example_matches_schema():
    manifest = catalog.load_manifest(ROOT / "catalog/examples/supabase-auth-canary.yaml")
    assert manifest["external_services"]["supabase"]["storage"] == "disabled"
    assert manifest["repository"]["agent_data_access"] == "none"


def test_schema_is_the_shape_authority(tmp_path):
    manifest = copy.deepcopy(catalog.build_catalog()["services"]["court-booker"])
    manifest["unexpected"] = True
    path = tmp_path / "court-booker.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(catalog.CatalogError, match="Additional properties"):
        catalog.load_manifest(path)


def test_provisioned_account_identity_is_immutable():
    previous = {
        "services": {
            "svc": {
                "accounts": {
                    "prod": {"account_id": "123456789012", "name": "Svc-Prod", "root_email": "old@example.com"}
                }
            }
        }
    }
    current = copy.deepcopy(previous)
    current["services"]["svc"]["accounts"]["prod"]["name"] = "Renamed"
    with pytest.raises(catalog.CatalogError, match="name.*immutable"):
        catalog.check_immutable(previous, current)


def test_account_key_cannot_be_deleted():
    previous = {"services": {"svc": {"accounts": {"dev": {"account_id": None}}}}}
    current = {"services": {"svc": {"accounts": {}}}}
    with pytest.raises(catalog.CatalogError, match="cannot be deleted"):
        catalog.check_immutable(previous, current)


@pytest.mark.parametrize(
    ("old", "new"),
    [("active", "active"), ("active", "suspended"), ("suspended", "archived"), ("archived", "archived")],
)
def test_forward_lifecycle_transitions_are_allowed(old, new):
    previous = catalog.build_catalog()
    current = copy.deepcopy(previous)
    previous["services"]["court-booker"]["kubernetes"]["homelab"]["lifecycle"] = old
    current["services"]["court-booker"]["kubernetes"]["homelab"]["lifecycle"] = new
    catalog.check_immutable(previous, current)


@pytest.mark.parametrize(("old", "new"), [("suspended", "active"), ("archived", "suspended"), ("archived", "active")])
def test_reverse_lifecycle_transition_requires_override(old, new):
    previous = catalog.build_catalog()
    current = copy.deepcopy(previous)
    previous["services"]["court-booker"]["kubernetes"]["homelab"]["lifecycle"] = old
    current["services"]["court-booker"]["kubernetes"]["homelab"]["lifecycle"] = new
    with pytest.raises(catalog.CatalogError, match="requires operator override"):
        catalog.check_immutable(previous, current)
    catalog.check_immutable(previous, current, allow_lifecycle_reversal=True)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("service", "uid"), "4fa03054-6f90-4f96-bd58-b9b6c08aa07c", "catalog UID"),
        (("repository", "identity"), "TusharSariya/renamed", "repository identity"),
        (("kubernetes", "homelab", "ecr_repository"), "renamed", "ECR repository"),
        (("kubernetes", "homelab", "ingress_hostname"), "renamed.example.com", "hostname"),
    ],
)
def test_activated_kubernetes_identity_is_immutable(path, value, message):
    previous = catalog.build_catalog()
    current = copy.deepcopy(previous)
    item = current["services"]["court-booker"]
    for key in path[:-1]:
        item = item[key]
    item[path[-1]] = value
    with pytest.raises(catalog.CatalogError, match=message):
        catalog.check_immutable(previous, current)


def test_capacity_accounts_for_the_entire_merged_catalog():
    rendered = catalog.build_catalog()
    services = copy.deepcopy(rendered["services"])
    services["third"] = copy.deepcopy(services["court-booker"])
    services["third"]["service"]["id"] = "third"
    services["fourth"] = copy.deepcopy(services["court-booker"])
    services["fourth"]["service"]["id"] = "fourth"
    services["fifth"] = copy.deepcopy(services["court-booker"])
    services["fifth"]["service"]["id"] = "fifth"
    with pytest.raises(catalog.CatalogError, match="exceeds requests_cpu capacity"):
        catalog._validate_capacity(services, rendered["kubernetes_clusters"])


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("active", "suspended"),
        ("suspended", "archived"),
        ("archived", "purge_requested"),
        ("purge_requested", "purged"),
    ],
)
def test_supabase_forward_lifecycle_transitions_are_allowed(old, new):
    previous = catalog.build_catalog()
    current = copy.deepcopy(previous)
    target = {
        "lifecycle": old,
        "organization_id": "example-org",
        "project_name": "canary-project",
        "region": "us-east-1",
    }
    previous["services"]["court-booker"]["external_services"]["supabase"] = target
    current["services"]["court-booker"]["external_services"]["supabase"] = {
        **target,
        "lifecycle": new,
    }
    catalog.check_immutable(previous, current)


def test_supabase_reverse_lifecycle_requires_override():
    previous = catalog.build_catalog()
    current = copy.deepcopy(previous)
    target = {
        "lifecycle": "archived",
        "organization_id": "example-org",
        "project_name": "canary-project",
        "region": "us-east-1",
    }
    previous["services"]["court-booker"]["external_services"]["supabase"] = target
    current["services"]["court-booker"]["external_services"]["supabase"] = {
        **target,
        "lifecycle": "active",
    }
    with pytest.raises(catalog.CatalogError, match="requires operator override"):
        catalog.check_immutable(previous, current)


def test_supabase_identity_is_immutable_after_activation():
    previous = catalog.build_catalog()
    current = copy.deepcopy(previous)
    target = {
        "lifecycle": "active",
        "organization_id": "example-org",
        "project_name": "canary-project",
        "project_ref": "abcdefghijklmnopqrst",
        "region": "us-east-1",
    }
    previous["services"]["court-booker"]["external_services"]["supabase"] = target
    current["services"]["court-booker"]["external_services"]["supabase"] = {
        **target,
        "project_ref": "bcdefghijklmnopqrstu",
    }
    with pytest.raises(catalog.CatalogError, match="project_ref.*immutable"):
        catalog.check_immutable(previous, current)


def test_catalog_identity_is_immutable_without_kubernetes_target():
    previous = catalog.build_catalog()
    current = copy.deepcopy(previous)
    previous["services"]["court-booker"]["kubernetes"] = {}
    current["services"]["court-booker"]["kubernetes"] = {}
    current["services"]["court-booker"]["service"]["uid"] = (
        "4fa03054-6f90-4f96-bd58-b9b6c08aa07c"
    )
    with pytest.raises(catalog.CatalogError, match="catalog UID.*immutable"):
        catalog.check_immutable(previous, current)

import argparse
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "external_provider_reconciler", ROOT / "scripts/external-provider-reconciler.py"
)
reconciler = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(reconciler)
SHA = "a" * 40


def service_manifest(lifecycle="active"):
    return {
        "service": {"uid": "4fa03054-6f90-4f96-bd58-b9b6c08aa07c", "id": "canary"},
        "external_services": {
            "supabase": {
                "lifecycle": lifecycle,
                "project_name": "canary-project",
                "project_ref": None,
            }
        },
    }


def args(tmp_path, **overrides):
    values = {
        "service_id": "canary",
        "adapter": "fake",
        "journal": "file",
        "journal_file": str(tmp_path / "journal.json"),
        "journal_table": None,
        "backend_config": None,
        "aws_region": "us-east-1",
        "fake_state_dir": str(tmp_path / "provider"),
        "catalog_sha": SHA,
        "confirm_purge": None,
        "canary": False,
        "force": False,
        "lease_seconds": 60,
        "fail_after": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def write_catalog(tmp_path, lifecycle="active"):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"services": {"canary": service_manifest(lifecycle)}}))
    reconciler.CATALOG = path


def test_fake_reconcile_records_desired_and_applied_commits(tmp_path):
    write_catalog(tmp_path)
    result = reconciler.reconcile(args(tmp_path))
    assert result["stage"] == "complete"
    assert result["desired_commit_sha"] == SHA
    assert result["applied_commit_sha"] == SHA
    assert result["result"]["project_ref"]


def test_checkpointed_operation_can_replay_after_process_failure(tmp_path):
    write_catalog(tmp_path)
    with pytest.raises(reconciler.ReconcileError, match="injected failure"):
        reconciler.reconcile(args(tmp_path, fail_after="planned"))
    first = json.loads((tmp_path / "journal.json").read_text())
    operation_id = first["4fa03054-6f90-4f96-bd58-b9b6c08aa07c#supabase"]["operation_id"]
    result = reconciler.reconcile(args(tmp_path))
    assert result["operation_id"] == operation_id
    assert result["stage"] == "complete"


def test_purge_requires_uid_and_exact_catalog_sha(tmp_path):
    write_catalog(tmp_path, "purge_requested")
    with pytest.raises(reconciler.ReconcileError, match="confirm-purge"):
        reconciler.reconcile(args(tmp_path))
    confirmation = f"4fa03054-6f90-4f96-bd58-b9b6c08aa07c:{SHA}"
    result = reconciler.reconcile(args(tmp_path, confirm_purge=confirmation))
    assert result["result"] == {"purged": True}


def test_journal_contains_no_provider_credentials(tmp_path, monkeypatch):
    write_catalog(tmp_path)
    monkeypatch.setenv("SUPABASE_ACCESS_TOKEN", "sentinel-access-token")
    monkeypatch.setenv("TF_VAR_database_password", "sentinel-database-password")
    reconciler.reconcile(args(tmp_path))
    journal = (tmp_path / "journal.json").read_text()
    assert "sentinel-access-token" not in journal
    assert "sentinel-database-password" not in journal


def test_second_reconciler_cannot_take_live_lease(tmp_path):
    journal = reconciler.FileJournal(tmp_path / "journal.json")
    journal.acquire("binding", "owner-one", 60)
    with pytest.raises(reconciler.ReconcileError, match="locked"):
        journal.acquire("binding", "owner-two", 60)


def test_live_adapter_fails_closed_when_rollout_gates_are_closed(tmp_path, monkeypatch):
    write_catalog(tmp_path)
    gates = tmp_path / "gates.json"
    gates.write_text(json.dumps({"harvester_credential_rotated": False}))
    monkeypatch.setattr(reconciler, "GATES", gates)
    with pytest.raises(reconciler.ReconcileError, match="gates are closed"):
        reconciler.reconcile(args(tmp_path, adapter="tofu"))


def test_gate_file_is_explicitly_fail_closed():
    gates = json.loads((ROOT / "catalog/external-provider-gates.json").read_text())
    assert gates["version"] == 1
    assert all(value is False for key, value in gates.items() if key != "version")

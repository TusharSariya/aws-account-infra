from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_supabase_provider_is_pinned_and_module_has_no_shell_escape():
    module = ROOT / "modules/external/supabase_project"
    versions = (module / "versions.tf").read_text()
    source = "\n".join(path.read_text() for path in module.glob("*.tf"))
    assert 'version = "= 1.9.1"' in versions
    assert "local-exec" not in source
    assert "remote-exec" not in source
    assert "supabase_storage" not in source
    assert "supabase_apikeys" not in source


def test_sensitive_state_control_has_independent_journal_and_state_lock_tables():
    source = (
        ROOT / "live/aws/organization/external-control/main.tf"
    ).read_text()
    assert 'resource "aws_dynamodb_table" "journal"' in source
    assert 'resource "aws_dynamodb_table" "state_locks"' in source
    assert "point_in_time_recovery" in source
    assert 'sse_algorithm     = "aws:kms"' in source
    assert "DenyStateDeletion" in source
    assert "DenyKeyDeletion" in source


def test_supabase_backend_example_uses_remote_locking_and_kms():
    backend = (ROOT / "live/external/supabase/backend.hcl.example").read_text()
    assert "dynamodb_table" in backend
    assert "kms_key_id" in backend
    assert "encrypt        = true" in backend


def test_restore_is_bound_to_clean_catalog_and_forbidden_during_purge():
    source = (ROOT / "scripts/supabase-restore.py").read_text()
    assert '"git", "diff", "--quiet"' in source
    assert '"purge_requested", "purged"' in source

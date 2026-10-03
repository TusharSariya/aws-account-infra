import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]


def test_only_sync_gets_exact_parameter_reads_and_token_writes():
    auth = (ROOT / "modules/aws/swimming-calendar/auth.tf").read_text()
    assert 'role  = aws_iam_role.lambda["sync"].id' in auth
    assert re.findall(r'Action\s*=\s*\["([^"]+)"\]', auth) == [
        "ssm:GetParameter",
        "ssm:PutParameter",
    ]
    assert "Resource = values(local.oauth_parameter_arns)" in auth
    assert 'Resource = local.oauth_parameter_arns["tokens"]' in auth
    assert 'resource "aws_kms_key"' not in auth
    assert 'resource "aws_secretsmanager_secret"' not in auth
    module = ROOT / "modules/aws/swimming-calendar"
    assert not any(
        'data "aws_ssm_parameter"' in p.read_text() for p in module.glob("*.tf")
    )
    config = (module / "main.tf").read_text()
    assert 'each.key == "sync" && var.oauth_parameters != null' in config
    assert "IRACING_CLIENT_PARAMETER" in config and "IRACING_TOKEN_PARAMETER" in config


def test_ci_migrates_before_retirement_and_refreshes_after_apply():
    workflow = (ROOT / ".github/workflows/tofu-apply.yml").read_text()
    migration = workflow.index("- name: Migrate iRacing OAuth")
    apply = workflow.index("- name: Apply AWS and Proxmox prerequisites")
    initialize = workflow.index("- name: Initialize iRacing calendar after apply")
    assert migration < apply < initialize
    guard = workflow[migration:apply]
    assert "python -m iracing_calendar.cli auth migrate" in guard
    assert "continue-on-error" not in guard and "|| true" not in guard

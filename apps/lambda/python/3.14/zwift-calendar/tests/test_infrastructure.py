import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]


def test_private_parameters_never_enter_state_or_feed_permissions():
    policy = (ROOT / "modules/aws/swimming-calendar/parameters.tf").read_text()
    assert 'role  = aws_iam_role.lambda["sync"].id' in policy
    assert re.findall(r'Action\s*=\s*\["([^"]+)"\]', policy) == [
        "ssm:GetParameter",
        "ssm:PutParameter",
    ]
    assert "var.sync_parameter_writes" in policy
    config = (
        ROOT / "live/aws/staging/workloads/lambda/python/zwift-calendar/main.tf"
    ).read_text()
    assert "sync_parameter_writes    = [local.tokens_parameter]" in config
    module = ROOT / "modules/aws/swimming-calendar"
    assert not any(
        'data "aws_ssm_parameter"' in p.read_text() for p in module.glob("*.tf")
    )
    shared = (module / "main.tf").read_text()
    assert ': ["${aws_s3_bucket.snapshot.arn}/current.json"]' in shared
    assert 'refresh_schedule         = "cron(0 * * * ? *)"' in config
    assert 'refresh_timezone         = "UTC"' in config


def test_deploy_unit_tracks_runtime_and_initializes_after_apply():
    manifest = json.loads((ROOT / "deploy-units.json").read_text())
    units = manifest["units"]
    unit = next(u for u in units if u["id"] == "aws-staging-zwift-calendar")
    assert "apps/lambda/python/3.14/zwift-calendar/" in unit["watch"]
    workflow = (ROOT / ".github/workflows/tofu-apply.yml").read_text()
    assert workflow.index(
        "- name: Initialize Zwift calendar after apply"
    ) > workflow.index("- name: Apply AWS and Proxmox prerequisites")
    assert (
        "python -m zwift_calendar.cli sync --function zwift-calendar-sync" in workflow
    )

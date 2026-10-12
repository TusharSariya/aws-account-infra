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
    assert (
        '[for key in var.feed_object_keys : "${aws_s3_bucket.snapshot.arn}/${key}"]'
        in shared
    )
    assert 'default     = ["current.json"]' in (module / "variables.tf").read_text()
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


def test_two_exact_routes_share_feed_integration_without_extra_aws_storage():
    config = (
        ROOT / "live/aws/staging/workloads/lambda/python/zwift-calendar/main.tf"
    ).read_text()
    assert 'route                    = "/calendars/zwift-banded.ics"' in config
    assert 'additional_routes        = ["/calendars/zwift-unbanded.ics"]' in config
    module = (ROOT / "modules/aws/swimming-calendar/main.tf").read_text()
    route = module.split('resource "aws_apigatewayv2_route" "additional_feed"')[
        1
    ].split('resource "aws_lambda_permission"')[0]
    assert 'route_key = "GET ${each.value}"' in route
    assert "aws_apigatewayv2_integration.feed.id" in route
    permission = module.split('resource "aws_lambda_permission" "additional_api"')[1]
    assert "/*/GET${each.value}" in permission
    assert 'aws_lambda_function.app["feed"].function_name' in permission
    variables = (
        (ROOT / "modules/aws/swimming-calendar/variables.tf")
        .read_text()
        .split('variable "additional_routes"')[1]
    )
    assert "default     = []" in variables


def test_power_cache_is_private_to_sync_and_model_settings_are_explicit():
    config = (
        ROOT / "live/aws/staging/workloads/lambda/python/zwift-calendar/main.tf"
    ).read_text()
    sync_keys = next(line for line in config.splitlines() if "sync_object_keys" in line)
    feed_keys = next(line for line in config.splitlines() if "feed_object_keys" in line)
    assert "power-state.json" in sync_keys and "power-state.json" not in feed_keys
    history = (
        ROOT / "live/aws/staging/workloads/lambda/python/zwift-calendar/history.tf"
    ).read_text()
    assert "power-state.json" not in history
    for setting in (
        "ZWIFT_MEASURED_MARGIN",
        "ZWIFT_WIDE_MARGIN",
        "ZWIFT_DEFAULT_POWER_CURVE",
    ):
        assert setting in config

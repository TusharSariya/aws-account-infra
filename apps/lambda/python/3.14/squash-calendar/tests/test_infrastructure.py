import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]


def test_independent_public_service_and_two_local_time_refreshes():
    root = ROOT / "live/aws/staging/workloads/lambda/python/squash-calendar"
    main = (root / "main.tf").read_text()
    assert '"/calendars/squash.ics"' in main
    assert '"cron(15 3 * * ? *)"' in main
    assert '"cron(30 16 ? * TUE *)"' in main
    assert "sync_parameter_reads" not in main
    module = (ROOT / "modules/aws/swimming-calendar/main.tf").read_text()
    assert "for_each = var.additional_refresh_schedules" in module
    assert "schedule_expression_timezone = var.refresh_timezone" in module
    units = json.loads((ROOT / "deploy-units.json").read_text())["units"]
    unit = next(u for u in units if u["id"] == "aws-staging-squash-calendar")
    assert "scripts/squash-package.py" in unit["watch"]

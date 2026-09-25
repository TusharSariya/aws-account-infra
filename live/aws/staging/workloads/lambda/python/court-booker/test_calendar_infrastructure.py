"""Guard the workflow boundary: publication retries cannot repeat booking."""
from pathlib import Path
import re

ROOT = Path(__file__).parent


def state_body(source, name):
    start = re.search(rf"\b{re.escape(name)}\s*=\s*\{{", source).end()
    depth = 1
    end = start
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end - 1]


def test_publication_failure_cannot_reenter_booking():
    source = (ROOT / "sfn.tf").read_text()
    assert re.search(r"TimeoutSeconds\s*=\s*300", source)
    book = state_body(source, "Book")
    publish = state_body(source, "PublishCalendar")
    assert '"PublishCalendarIfSuccessful"' in book
    assert re.search(r"Retry\s*=", publish)
    assert set(re.findall(r'Next\s*=\s*"([^"]+)"', publish)) == {
        "Complete", "CalendarPublicationFailed"
    }
    failure = state_body(source, "CalendarPublicationFailed")
    assert '"booking confirmed, calendar publication failed"' in failure
    assert 'Type  = "Fail"' in failure


def test_success_missing_metadata_is_still_published_and_dry_runs_skip():
    choice = state_body((ROOT / "sfn.tf").read_text(), "PublishCalendarIfSuccessful")
    assert "calendar_reservation" not in choice
    for status in ("booked", "already_held", "cancelled"):
        assert f'StringEquals = "{status}"' in choice
    assert '$.dry_run' in choice
    assert 'BooleanEquals = true' in choice
    assert choice.index('Next = "Complete"') < choice.index('Next = "PublishCalendar"')


def test_gateway_logs_do_not_include_paths_or_keys():
    stage = (ROOT / "calendar.tf").read_text()
    log_format = next(line for line in stage.splitlines() if 'format ' in line and 'jsonencode' in line)
    assert "$context.requestId" in log_format
    assert not any(field in log_format.lower() for field in ("path", "url", "query", "token", "key", "authoriz"))


def _braced(source, start):
    open_ = source.index("{", start)
    depth, end = 1, open_ + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[open_ + 1:end - 1]


def test_feed_serves_exactly_public_and_private_routes():
    source = (ROOT / "calendar.tf").read_text()
    routes = _braced(source, source.index("calendar_routes = "))
    assert re.findall(r'route_key\s*=\s*"([^"]+)"', routes) == [
        "GET /calendars/public/bookings.ics",
        "GET /calendars/private/{key}/bookings.ics",
    ]
    # Lambda permissions are per route, not a wildcard over every calendar path.
    assert re.findall(r'source_arn\s*=\s*"\$\{[^}]+\}([^"]+)"', routes) == [
        "/*/GET/calendars/public/bookings.ics",
        "/*/GET/calendars/private/*/bookings.ics",
    ]
    assert "/calendars/{token}" not in source
    route = _braced(source, source.index('resource "aws_apigatewayv2_route" "calendar"'))
    permission = _braced(source, source.index('resource "aws_lambda_permission" "calendar_gateway"'))
    assert "for_each  = local.calendar_routes" in route
    assert "for_each      = local.calendar_routes" in permission
    assert "each.value.source_arn" in permission


def test_feed_reads_only_calendar_items_and_its_private_key():
    source = (ROOT / "calendar.tf").read_text()
    assert "SUBSCRIPTIONS" not in source
    params = _braced(source, source.index("calendar_parameters = "))
    assert re.findall(r"(\w+)\s*=\s*aws_ssm_parameter\.(\w+)\.arn", params) == [
        ("feed", "calendar_private_key"),
        ("reconcile", "my_y"),
    ]
    assert "CALENDAR_PRIVATE_KEY_PARAMETER = aws_ssm_parameter.calendar_private_key.name" in source
    assert 'variable = "kms:ViaService"' in source


def test_private_key_parameter_starts_closed_and_is_never_managed_by_tofu():
    source = (ROOT / "parameter.tf").read_text()
    resource = _braced(source, source.index('resource "aws_ssm_parameter" "calendar_private_key"'))
    assert 'name        = "/staging/court-booker-api/calendar-private-key"' in resource
    assert 'type        = "SecureString"' in resource
    assert 'key_id      = "alias/aws/ssm"' in resource
    assert 'value       = "UNSET"' in resource
    assert "ignore_changes = [value]" in resource
    for path in ROOT.glob("*.tf"):
        assert "\u2014" not in path.read_text(), path

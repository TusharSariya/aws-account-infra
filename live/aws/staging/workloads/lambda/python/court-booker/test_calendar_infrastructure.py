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
    next_lines = re.findall(r"Next\s*=\s*([^\n]+)", publish)
    targets = {t for line in next_lines for t in re.findall(r'"([^"]+)"', line)}
    # AckWindowStarted is only wired in when local.ack_enabled; it never reaches Book.
    assert targets == {"Complete", "CalendarPublicationFailed", "AckWindowStarted"}
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


def test_gateway_logs_do_not_include_subscription_paths():
    stage = (ROOT / "calendar.tf").read_text()
    log_format = next(line for line in stage.splitlines() if 'format ' in line and 'jsonencode' in line)
    assert "$context.requestId" in log_format
    assert not any(field in log_format.lower() for field in ("path", "url", "query", "token", "authoriz"))

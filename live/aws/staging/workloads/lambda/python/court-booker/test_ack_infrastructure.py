"""Static guards for the friend ACK window. Cheap text checks of the .tf files."""
from pathlib import Path
import re

from test_calendar_infrastructure import state_body

ROOT = Path(__file__).parent
ACKS = (ROOT / "acks.tf").read_text()
SFN = (ROOT / "sfn.tf").read_text()


def block_body(source, header):
    start = source.index(header + " {") + len(header) + 2
    depth, end = 1, start
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end - 1]


def policy(name):
    return block_body(ACKS, f'data "aws_iam_policy_document" "{name}"')


def test_every_ack_resource_is_gated():
    for match in re.finditer(r'^resource "([^"]+)" "([^"]+)" \{\n((?:  #[^\n]*\n)*)  (\w+)', ACKS, re.M):
        kind, name, _, first = match.groups()
        assert first in {"count", "for_each"}, f"{kind}.{name} is not gated on local.ack_enabled"
    assert re.search(r'ack_enabled\s*=\s*var\.ack_mode != "off" && local\.zip_ready', (ROOT / "locals.tf").read_text())


def test_booking_workflow_ack_states_only_when_enabled():
    assert re.search(r"ack_start_choice\s*=\s*local\.ack_enabled \?", SFN)
    assert re.search(r"ack_booker_states\s*=\s*local\.ack_enabled \?", SFN)
    assert re.search(r'Next\s*=\s*local\.ack_enabled \? "AckWindowStarted" : "Complete"', SFN)
    assert "choice if choice != null" in SFN
    assert "}, local.ack_booker_states)" in SFN
    start = state_body(SFN, "StartAckWindow")
    assert "ExecutionAlreadyExistsException" in start
    assert '"$.ack_error"' in start
    assert set(re.findall(r'Next\s*=\s*"([^"]+)"', start)) == {"PublishCalendar"}


def test_await_acks_never_retries_handler_errors():
    await_acks = state_body(ACKS, "AwaitAcks")
    assert "waitForTaskToken" in await_acks
    assert "Retry = local.ack_lambda_retry" in await_acks
    assert '"States.Timeout"' in await_acks and 'Next = "Expire"' in await_acks
    retry = ACKS[ACKS.index("ack_lambda_retry = ["):ACKS.index("ack_leading_keys")]
    assert "States.ALL" not in retry


def test_cancel_only_via_expire_choice_and_never_before_timeout():
    assert ACKS.count('Next = "CancelBooking"') == 1
    choice = state_body(ACKS, "ExpiryOutcome")
    assert '"$.expiry.cancel", BooleanEquals = true, Next = "CancelBooking"' in choice
    cancel = state_body(ACKS, "CancelBooking")
    assert 'InputPath  = "$.expiry.cancel_event"' in cancel
    assert 'Next = "NotifyCancelFailed"' in cancel


def test_ack_api_role_cannot_write_or_read_roster():
    api = policy("ack_api")
    assert "dynamodb:PutItem" not in api
    assert "ssm:GetParameter" not in api
    assert "ses:" not in api
    assert "states:SendTaskSuccess" in api


def test_dynamodb_access_is_scoped_to_ack_partitions():
    for doc in ("ack_workflow", "ack_api"):
        body = policy(doc)
        assert "dynamodb:LeadingKeys" in body
        assert "local.ack_leading_keys" in body
    assert 'ack_leading_keys = ["BOOKING#*", "TOKEN#*"]' in ACKS

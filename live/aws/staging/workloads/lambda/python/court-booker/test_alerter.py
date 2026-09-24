import json

from alerter import explain_failure, format_email, parse_lambda_cause


CAUSE = json.dumps(
    {
        "errorMessage": json.dumps(
            {
                "status": "closed",
                "message": "no start time 8:00pm",
                "target_date": "2026-08-17",
                "activity": "court2",
                "time": "20:00",
                "reserve_clicks": 0,
            }
        ),
        "errorType": "BookingFailed",
    }
)


def test_parse_nested_booking_failed():
    parsed = parse_lambda_cause(CAUSE, "BookingFailed")
    assert parsed["status"] == "closed"
    assert parsed["message"] == "no start time 8:00pm"
    assert parsed["activity"] == "court2"


def test_no_start_time_is_taken_not_generic_fail():
    headline, blurb = explain_failure(
        {"status": "closed", "message": "no start time 8:00pm", "error": "BookingFailed"}
    )
    assert headline == "slot not listed (likely taken)"
    assert "dropdown" in blurb


def test_full_is_already_taken():
    headline, blurb = explain_failure(
        {"status": "full", "message": "8:00pm has no open spots", "error": "BookingFailed"}
    )
    assert headline == "slot already taken"
    assert "already booked" in blurb


def test_chromium_crash_is_not_a_taken_slot():
    headline, blurb = explain_failure(
        {"status": "", "message": "BrowserContext.new_page: Target crashed", "error": "Error"}
    )
    assert headline == "Chromium crashed"
    assert "not a taken slot" in blurb


def test_sfn_email_uses_human_subject():
    execution = {
        "executionArn": "arn:aws:states:us-east-1:1:execution:court-booker:run-1",
        "input": json.dumps(
            {"source": "weekly", "activity": "court2", "weekday": "Mon", "time": "20:00"}
        ),
        "error": "BookingFailed",
        "cause": CAUSE,
    }
    subject, body = format_email(
        {"AlarmName": "court-booker-failed", "NewStateValue": "ALARM"},
        execution,
        [{"headline": "slot not listed (likely taken)", "message": "no start time 8:00pm"}],
        "us-east-1",
    )
    assert subject == "Court booker: court2 Mon 20:00 — slot not listed (likely taken)"
    assert "Someone else probably took it" in body or "dropdown" in body
    assert "Threshold Crossed" not in body
    assert "AWSAccountId" not in body
    assert "Attempts:" in body


def test_api_alarm_names_are_recognized():
    from alerter import _is_sfn_alarm

    assert _is_sfn_alarm({"AlarmName": "court-booker-api-failed"})
    for name, expected in [("throttles", "throttled"), ("scheduler-target-errors", "schedule failed")]:
        subject, _ = format_email({"AlarmName": f"court-booker-api-{name}"}, None, [], "us-east-1")
        assert expected in subject


def test_publication_failure_does_not_report_booking_failure():
    subject, body = format_email(
        {"AlarmName": "court-booker-api-failed"},
        {"error": "CalendarPublicationFailed", "cause": "booking confirmed, calendar publication failed"},
        [], "us-east-1",
    )
    assert "booking confirmed, calendar publication failed" in subject
    assert "do not repeat the booking" in body


def test_calendar_and_timeout_alarms_have_distinct_messages():
    for suffix, expected in [
        ("calendar-feed-errors", "calendar feed failed"),
        ("calendar-reconcile-errors", "calendar reconciliation failed"),
        ("calendar-writer-errors", "calendar publication failed"),
        ("timed-out", "workflow timed out"),
    ]:
        subject, _ = format_email({"AlarmName": f"court-booker-api-{suffix}"}, None, [], "us-east-1")
        assert expected in subject


def test_async_failure_destination_redacts_request_and_response(monkeypatch):
    import alerter

    emails = []

    class Ses:
        def send_email(self, **kwargs):
            emails.append(kwargs)

    monkeypatch.setenv("ALERT_FROM", "a@example.test")
    monkeypatch.setenv("ALERT_TO", "a@example.test")
    monkeypatch.setattr(alerter.boto3, "client", lambda name, **kwargs: Ses())
    alerter.lambda_handler({
        "requestContext": {"condition": "RetriesExhausted"},
        "requestPayload": {"token": "must-not-leak"},
        "responsePayload": {"errorMessage": "secret upstream payload"},
    }, None)
    assert len(emails) == 1
    rendered = json.dumps(emails)
    assert "reconciliation failed" in rendered
    assert "must-not-leak" not in rendered
    assert "secret upstream" not in rendered


def test_swimming_alert_does_not_claim_a_booking_failed():
    for name in ("swim-calendar-sync-errors", "swim-calendar-feed-errors", "swim-calendar-failed-delivery",
                 "paul-reynolds-swim-calendar-sync-errors", "paul-reynolds-swim-calendar-feed-errors",
                 "paul-reynolds-swim-calendar-failed-delivery"):
        subject, body = format_email({"AlarmName": name, "NewStateValue": "ALARM"}, None, [], "us-east-1")
        assert subject.startswith("Swimming calendar alarm:")
        assert "Court booker failed" not in body
        assert name in body


def test_iracing_alarm_identifies_service():
    subject, body = format_email({"AlarmName": "iracing-calendar-feed-errors", "NewStateValue": "ALARM"}, None, [], "us-east-1")
    assert subject.startswith("iRacing calendar")
    assert "eight days" in body

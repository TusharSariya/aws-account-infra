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

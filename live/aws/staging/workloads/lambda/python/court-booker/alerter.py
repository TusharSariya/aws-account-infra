"""SNS → SES bridge for court-booker CloudWatch alarms.

Looks up the failed Step Functions run so the mail can say "slot taken"
instead of dumping the raw alarm JSON.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

STATUS_BLURB = {
    "full": "Someone else already booked that slot (no spots remaining).",
    "closed": "The listing was still locked, or that start time was not on the board.",
    "auth_fail": "My Y email or password was rejected.",
    "membership": "Upace asked for an active membership.",
    "unexpected_ui": "The page did not match the expected booking flow.",
    "late": "The weekly job ran on a day that is not the 72-hour unlock.",
}


def lambda_handler(event, context):  # noqa: ARG001
    alert_from = os.environ["ALERT_FROM"]
    alert_to = os.environ["ALERT_TO"]
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    machine_arn = os.environ.get("STATE_MACHINE_ARN", "")
    sfn = boto3.client("stepfunctions", region_name=region)
    ses = boto3.client("ses", region_name=region)

    for record in event.get("Records", []):
        sns = record.get("Sns") or {}
        payload = _parse_alarm(sns.get("Message") or "")
        execution = _latest_failed_execution(sfn, machine_arn) if _is_sfn_alarm(payload) else None
        attempts = _attempt_summaries(sfn, execution) if execution else []
        subject, body = format_email(payload, execution, attempts, region)
        ses.send_email(
            Source=alert_from,
            Destination={"ToAddresses": [alert_to]},
            Message={
                "Subject": {"Data": subject[:990], "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )
    return {"ok": True}


def format_email(
    payload: dict[str, Any],
    execution: dict[str, Any] | None,
    attempts: list[dict[str, str]],
    region: str,
) -> tuple[str, str]:
    alarm = str(payload.get("AlarmName") or "court-booker")
    state = str(payload.get("NewStateValue") or "")
    if state and state != "ALARM":
        return f"Court booker {state.lower()}: {alarm}", _ok_body(payload)

    if alarm == "court-booker-throttles":
        return "Court booker: Lambda was throttled", _simple_body(
            "The court-booker Lambda was throttled, so a booking attempt never ran.",
            payload,
        )
    if alarm == "court-booker-scheduler-target-errors":
        return "Court booker: schedule failed to start", _simple_body(
            "EventBridge Scheduler could not start the court-booker state machine.",
            payload,
        )

    failure = _failure_from_execution(execution) if execution else {}
    headline, blurb = explain_failure(failure)
    slot = _slot_line(execution, failure)
    subject = f"Court booker: {slot} — {headline}" if slot else f"Court booker: {headline}"

    lines = [
        f"Court booker failed: {headline}",
        "",
        blurb,
    ]
    if slot:
        lines.extend(["", f"Slot: {slot}"])
        if failure.get("target_date"):
            lines.append(f"Date: {failure['target_date']}")
        if failure.get("message"):
            lines.append(f"Detail: {failure['message']}")
    if attempts:
        lines.extend(["", "Attempts:"])
        for index, attempt in enumerate(attempts, start=1):
            lines.append(f"  {index}. {attempt['headline']} — {attempt['message']}")
    if execution:
        arn = execution.get("executionArn") or ""
        lines.extend(
            [
                "",
                f"Execution: https://{region}.console.aws.amazon.com/states/home?region={region}#/v2/executions/details/{arn}",
                f"Logs: https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:log-groups/log-group/$252Faws$252Flambda$252Fcourt-booker",
            ]
        )
    lines.extend(["", f"CloudWatch alarm: {alarm}"])
    return subject[:990], "\n".join(lines).strip() + "\n"


def explain_failure(failure: dict[str, str]) -> tuple[str, str]:
    status = (failure.get("status") or "").strip()
    message = (failure.get("message") or "").strip()
    error = (failure.get("error") or "").strip()
    combined = f"{message} {error}".lower()

    if status == "full" or "no open spots" in message.lower():
        return "slot already taken", STATUS_BLURB["full"]
    if status == "closed" and "no start time" in message.lower():
        return "slot not listed (likely taken)", (
            "That start time was not in the dropdown. Someone else probably "
            "took it, or that court does not offer that time."
        )
    if status in STATUS_BLURB:
        headline = {
            "closed": "listing still locked",
            "auth_fail": "login failed",
            "membership": "membership required",
            "unexpected_ui": "unexpected page",
            "late": "ran on the wrong day",
        }[status]
        return headline, STATUS_BLURB[status]
    if any(
        token in combined
        for token in ("target crashed", "assertion error", "connection closed", "single-process")
    ):
        return "Chromium crashed", "The browser died in Lambda before it could book. This is not a taken slot."
    if error and error != "BookingFailed":
        return error, message or "The Lambda raised before it returned a booking status."
    if message:
        return message, "The booking job failed after three attempts."
    return "booking failed after 3 attempts", "The state machine gave up. Check the execution for the Lambda error."


def parse_lambda_cause(cause: str, error: str = "") -> dict[str, str]:
    result = {"status": "", "message": "", "error": error, "activity": "", "time": "", "target_date": ""}
    if not cause:
        return result
    try:
        outer = json.loads(cause)
    except json.JSONDecodeError:
        result["message"] = cause.strip()
        return result
    if not isinstance(outer, dict):
        result["message"] = str(outer)
        return result

    result["error"] = str(outer.get("errorType") or error or "")
    raw_message = outer.get("errorMessage", cause)
    if isinstance(raw_message, str):
        try:
            inner = json.loads(raw_message)
        except json.JSONDecodeError:
            result["message"] = raw_message.strip()
            return result
    elif isinstance(raw_message, dict):
        inner = raw_message
    else:
        result["message"] = str(raw_message)
        return result

    if isinstance(inner, dict):
        for key in ("status", "message", "activity", "time", "target_date"):
            if inner.get(key) is not None:
                result[key] = str(inner[key])
    return result


def _parse_alarm(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"AlarmName": "", "NewStateValue": "ALARM", "raw": raw}
    return payload if isinstance(payload, dict) else {"AlarmName": "", "raw": raw}


def _is_sfn_alarm(payload: dict[str, Any]) -> bool:
    return str(payload.get("AlarmName") or "") == "court-booker-failed"


def _latest_failed_execution(sfn, machine_arn: str) -> dict[str, Any] | None:
    if not machine_arn:
        return None
    listed = sfn.list_executions(stateMachineArn=machine_arn, statusFilter="FAILED", maxResults=1)
    summaries = listed.get("executions") or []
    if not summaries:
        return None
    return sfn.describe_execution(executionArn=summaries[0]["executionArn"])


def _attempt_summaries(sfn, execution: dict[str, Any]) -> list[dict[str, str]]:
    arn = execution.get("executionArn")
    if not arn:
        return []
    history = sfn.get_execution_history(
        executionArn=arn,
        reverseOrder=False,
        maxResults=50,
    )
    attempts = []
    for event in history.get("events") or []:
        if event.get("type") != "TaskFailed":
            continue
        details = event.get("taskFailedEventDetails") or {}
        parsed = parse_lambda_cause(details.get("cause") or "", details.get("error") or "")
        headline, _ = explain_failure(parsed)
        attempts.append({"headline": headline, "message": parsed.get("message") or parsed.get("error") or "failed"})
    return attempts


def _failure_from_execution(execution: dict[str, Any]) -> dict[str, str]:
    parsed = parse_lambda_cause(execution.get("cause") or "", execution.get("error") or "")
    if not parsed.get("activity") or not parsed.get("time"):
        parsed.update({k: v for k, v in _slot_from_input(execution.get("input") or "").items() if v})
    return parsed


def _slot_from_input(raw: str) -> dict[str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        "activity": str(payload.get("activity") or ""),
        "time": str(payload.get("time") or ""),
        "weekday": str(payload.get("weekday") or ""),
    }


def _slot_line(execution: dict[str, Any] | None, failure: dict[str, str]) -> str:
    activity = failure.get("activity") or ""
    time_value = failure.get("time") or ""
    weekday = ""
    if execution:
        weekday = _slot_from_input(execution.get("input") or "").get("weekday") or ""
    parts = [p for p in (activity, weekday, time_value) if p]
    return " ".join(parts)


def _simple_body(summary: str, payload: dict[str, Any]) -> str:
    alarm = payload.get("AlarmName") or ""
    return f"{summary}\n\nCloudWatch alarm: {alarm}\n"


def _ok_body(payload: dict[str, Any]) -> str:
    return f"{payload.get('AlarmName', '')} is {payload.get('NewStateValue', '')}.\n"

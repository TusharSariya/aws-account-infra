import base64
import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import pytest
from booker import ack_api, ack_workflow
from booker.ack_repository import (
    CANCEL_FAILED,
    CANCELLED,
    CONFIRMED,
    EXPIRED,
    PENDING,
    AckRepository,
    send_task_success,
)
from booker.ack_roster import RosterEntry, RosterError, load_roster, parse_roster
from booker.config import load_bookings
from botocore.exceptions import ClientError
from moto import mock_aws

BOOKINGS = Path(__file__).resolve().parents[5] / "ecr/court-booker/bookings.yaml"
NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
OWNER_EMAIL = "owner@example.com"
BASE_URL = "https://calendar.example.com/"
ROSTER = {
    "court1": [
        RosterEntry("Al <b>& Co</b>", "al@example.com"),
        RosterEntry("Bea", "bea@example.com"),
        RosterEntry("Cy", "cy@example.com"),
    ]
}
BOOKING = {
    "status": "booked",
    "message": "reservation complete",
    "target_date": "2026-09-28",
    "activity": "court1",
    "time": "17:00",
    "reserve_clicks": 1,
    "reservation_id": "123",
    "calendar_reservation": {"reservation_id": "123", "equipment_id": 7412},
}


class FakeSes:
    def __init__(self, fail_after=None):
        self.sent = []
        self.attempts = []
        self.fail_after = fail_after

    def send_email(self, **kwargs):
        self.attempts.append(kwargs)
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise ClientError(
                {"Error": {"Code": "MessageRejected", "Message": "bad x@example.com"}},
                "SendEmail",
            )
        self.sent.append(kwargs)

    def to(self, email):
        return [m for m in self.sent if m["Destination"]["ToAddresses"] == [email]]


class FakeSfn:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def send_task_success(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise ClientError({"Error": {"Code": self.error, "Message": "x"}}, "SendTaskSuccess")


def make_repo():
    db = boto3.resource(
        "dynamodb",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    table = db.create_table(
        TableName="acks-test-" + uuid.uuid4().hex,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": k, "AttributeType": "S"} for k in ("PK", "SK")
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return AckRepository(table)


@pytest.fixture
def repo():
    with mock_aws():
        yield make_repo()


@pytest.fixture
def config():
    return load_bookings(BOOKINGS)


def prepare(repo, config, now=NOW, **event):
    return ack_workflow.prepare(
        {"action": "prepare", "booking": BOOKING, "ack_window_hours": 24, "ack_required": 2, **event},
        repository=repo,
        config=config,
        now=now,
    )


def invite(repo, ses=None, sfn=None, task_token="task-1", roster=ROSTER, now=NOW):
    ses = ses if ses is not None else FakeSes()
    ack_workflow.send_invites(
        {"action": "send_invites", "reservation_id": "123", "task_token": task_token},
        repository=repo,
        roster=roster,
        mailer=ack_workflow.Mailer(ses, "bot@example.com"),
        sfn=sfn or FakeSfn(),
        owner_email=OWNER_EMAIL,
        base_url=BASE_URL,
        now=now,
    )
    return ses


def link_token(ses, email):
    text = ses.to(email)[-1]["Content"]["Simple"]["Body"]["Text"]["Data"]
    return re.search(r"https://calendar\.example\.com/acks/(\S+)", text).group(1)


@pytest.fixture
def window(repo, config):
    prepare(repo, config)
    ses = invite(repo)
    tokens = {e.email: link_token(ses, e.email) for e in ROSTER["court1"]}
    tokens["owner"] = link_token(ses, OWNER_EMAIL)
    return tokens


def call(repo, sfn, token, method="GET", body=None, now=NOW, b64=False):
    event = {"requestContext": {"http": {"method": method}}, "pathParameters": {"token": token}}
    if body is not None:
        event["body"] = base64.b64encode(body.encode()).decode() if b64 else body
        event["isBase64Encoded"] = b64
    return ack_api.serve(event, repo, sfn, now)


def meta(repo):
    return repo.get_meta("123")


# prepare


def test_prepare_deadline_is_window_or_six_hours_before_slot(repo, config):
    out = prepare(repo, config)
    assert out == {
        "reservation_id": "123",
        "activity": "court1",
        "date": "2026-09-28",
        "time": "17:00",
        "timeout_seconds": 86400,
        "deadline": "2026-09-25T12:00:00Z",
    }
    # Slot is 17:00 NDT (19:30Z); a 120 h window is capped at slot - 6 h.
    capped = prepare(make_repo(), config, ack_window_hours=120)
    assert capped["deadline"] == "2026-09-28T13:30:00Z"
    stored = meta(repo)
    assert stored["state"] == PENDING and stored["ack_count"] == 0 and stored["required"] == 2
    assert stored["slot_label"] == "Mon Sep 28 17:00 (Court 1)"
    assert stored["deadline_label"] == "Fri Sep 25 09:30 NDT"
    assert stored["equipment_id"] == 7412


def test_prepare_is_idempotent(repo, config):
    first = prepare(repo, config)
    later = prepare(repo, config, now=NOW + timedelta(hours=1), ack_window_hours=48)
    assert later["deadline"] == first["deadline"]
    assert later["timeout_seconds"] == 86400 - 3600


def test_prepare_timeout_floor(repo, config):
    slot_soon = datetime(2026, 9, 28, 19, 0, tzinfo=UTC)  # 30 min before a 17:00 NDT slot
    out = prepare(repo, config, now=slot_soon)
    assert out["timeout_seconds"] == 60
    assert out["deadline"] == "2026-09-28T19:01:00Z"
    retry = prepare(repo, config, now=slot_soon + timedelta(minutes=5))
    assert retry["timeout_seconds"] == 60


def test_prepare_requires_booked_result(repo, config):
    with pytest.raises(ValueError):
        ack_workflow.prepare(
            {"booking": {**BOOKING, "status": "already_held"}}, repository=repo, config=config, now=NOW
        )


# send_invites


def test_send_invites_emails_each_invitee_once(repo, config):
    prepare(repo, config)
    ses = invite(repo)
    assert len(ses.sent) == 4
    friend = ses.to("bea@example.com")[0]
    assert friend["FromEmailAddress"] == "bot@example.com"
    assert friend["Content"]["Simple"]["Subject"]["Data"] == (
        "Court booked: Mon Sep 28 17:00 (Court 1) - are you in?"
    )
    body = ses.to("al@example.com")[0]["Content"]["Simple"]["Body"]
    assert "Al &lt;b&gt;&amp; Co&lt;/b&gt;" in body["Html"]["Data"]
    assert "<b>" not in body["Html"]["Data"]
    assert "Fri Sep 25 09:30 NDT" in body["Text"]["Data"]
    assert ses.to(OWNER_EMAIL)[0]["Content"]["Simple"]["Subject"]["Data"].endswith("keep it?")

    again = invite(repo, task_token="task-2")
    assert again.sent == []
    assert meta(repo)["task_token"] == "task-2"
    assert len(repo.list_invitees("123")) == 4


def test_send_invites_resumes_after_mail_failure(repo, config, caplog):
    prepare(repo, config)
    failed = FakeSes(fail_after=1)
    with pytest.raises(ack_workflow.MailError) as exc:
        invite(repo, ses=failed)
    assert "@" not in str(exc.value)
    failed.sent = failed.attempts
    unsent = link_token(failed, "bea@example.com")
    retry = invite(repo, task_token="task-2")
    sent_to = [m["Destination"]["ToAddresses"][0] for m in retry.sent]
    assert sent_to == ["bea@example.com", "cy@example.com", OWNER_EMAIL]
    # The never-delivered token is dead; the resent one works.
    assert call(repo, FakeSfn(), unsent)["statusCode"] == 404
    assert call(repo, FakeSfn(), link_token(retry, "bea@example.com"))["statusCode"] == 200
    assert len(repo.list_invitees("123")) == 4
    assert "@" not in caplog.text


def test_send_invites_after_confirmation_resumes_new_task(repo, config, window):
    sfn = FakeSfn()
    call(repo, sfn, window["owner"], "POST", "response=accept")
    retry_sfn = FakeSfn()
    ses = invite(repo, sfn=retry_sfn, task_token="task-2")
    assert ses.sent == []
    assert retry_sfn.calls == [{"taskToken": "task-2", "output": '{"outcome": "kept"}'}]


# API


def test_get_renders_form_and_never_mutates(repo, window):
    table = repo.table
    before = sorted(table.scan()["Items"], key=lambda i: (i["PK"], i["SK"]))
    response = call(repo, FakeSfn(), window["bea@example.com"])
    assert response["statusCode"] == 200
    assert response["headers"]["Cache-Control"] == "no-store"
    assert response["headers"]["Referrer-Policy"] == "no-referrer"
    assert response["headers"]["Content-Type"] == "text/html; charset=utf-8"
    assert '<form method="post">' in response["body"]
    assert 'name="response" value="accept"' in response["body"]
    assert 'name="response" value="decline"' in response["body"]
    assert "Mon Sep 28 17:00 (Court 1)" in response["body"]
    after = sorted(table.scan()["Items"], key=lambda i: (i["PK"], i["SK"]))
    assert before == after


def test_quorum_confirms_once_and_third_sees_full(repo, window):
    sfn = FakeSfn()
    first = call(repo, sfn, window["al@example.com"], "POST", "response=accept")
    assert "You&#x27;re in." in first["body"]
    assert sfn.calls == []
    second = call(repo, sfn, window["bea@example.com"], "POST", "response=accept", b64=True)
    assert second["statusCode"] == 200
    assert sfn.calls == [{"taskToken": "task-1", "output": '{"outcome": "confirmed"}'}]
    assert meta(repo)["state"] == CONFIRMED and meta(repo)["ack_count"] == 2
    third = call(repo, sfn, window["cy@example.com"], "POST", "response=accept")
    assert "Court is full" in third["body"]
    assert len(sfn.calls) == 1
    assert meta(repo)["ack_count"] == 2
    assert "response" not in repo.get_invitee("123", third_id(repo, "cy@example.com"))


def third_id(repo, email):
    return next(i["invitee_id"] for i in repo.list_invitees("123") if i["email"] == email)


def test_double_click_is_idempotent(repo, window):
    sfn = FakeSfn()
    call(repo, sfn, window["al@example.com"], "POST", "response=accept")
    again = call(repo, sfn, window["al@example.com"], "POST", "response=accept")
    assert again["statusCode"] == 200
    assert "You already answered." in again["body"]
    assert meta(repo)["ack_count"] == 1 and meta(repo)["state"] == PENDING
    assert sfn.calls == []


def test_decline_does_not_count(repo, window):
    sfn = FakeSfn()
    call(repo, sfn, window["al@example.com"], "POST", "response=decline")
    call(repo, sfn, window["bea@example.com"], "POST", "response=accept")
    assert meta(repo)["ack_count"] == 1 and meta(repo)["state"] == PENDING
    flip = call(repo, sfn, window["al@example.com"], "POST", "response=accept")
    assert "You already answered." in flip["body"]
    assert meta(repo)["ack_count"] == 1


def test_owner_override_keeps_court(repo, window):
    sfn = FakeSfn()
    page = call(repo, sfn, window["owner"])
    assert "Keep it anyway" in page["body"]
    call(repo, sfn, window["owner"], "POST", "response=decline")
    assert meta(repo)["state"] == PENDING  # "let friends decide" changes nothing
    kept = call(repo, sfn, window["owner"], "POST", "response=accept")
    assert "Kept." in kept["body"]
    assert meta(repo)["state"] == CONFIRMED and meta(repo)["outcome"] == "kept"
    assert sfn.calls == [{"taskToken": "task-1", "output": '{"outcome": "kept"}'}]


def test_unknown_and_expired_tokens_are_404(repo, window):
    sfn = FakeSfn()
    assert call(repo, sfn, "x" * 43)["statusCode"] == 404
    assert call(repo, sfn, "../../etc")["statusCode"] == 404
    assert call(repo, sfn, "")["statusCode"] == 404
    late = NOW + timedelta(days=30)
    assert call(repo, sfn, window["al@example.com"], now=late)["statusCode"] == 404
    assert call(repo, sfn, window["al@example.com"], "POST", "response=accept", now=late)["statusCode"] == 404
    assert meta(repo)["ack_count"] == 0


def test_bad_form_body_is_400(repo, window):
    for body in ("response=maybe", "", "response=accept&response=decline"):
        assert call(repo, FakeSfn(), window["al@example.com"], "POST", body)["statusCode"] == 400
    bad_b64_event = {
        "requestContext": {"http": {"method": "POST"}},
        "pathParameters": {"token": window["al@example.com"]},
        "body": "!!!",
        "isBase64Encoded": True,
    }
    assert ack_api.serve(bad_b64_event, repo, FakeSfn(), NOW)["statusCode"] == 400


def test_friend_after_deadline_sees_closed(repo, window):
    sfn = FakeSfn()
    page = call(repo, sfn, window["al@example.com"], "POST", "response=accept", now=NOW + timedelta(hours=25))
    assert "closed" in page["body"]
    assert meta(repo)["ack_count"] == 0


def test_ack_racing_expire_only_one_wins(repo, window, monkeypatch):
    sfn = FakeSfn()
    call(repo, sfn, window["al@example.com"], "POST", "response=accept")
    original = repo.get_meta
    raced = []

    def get_meta_then_expire(reservation_id):
        item = original(reservation_id)
        if not raced:
            raced.append(True)
            ack_workflow.expire({"reservation_id": "123"}, repository=repo, mode="enforce", now=NOW)
        return item

    monkeypatch.setattr(repo, "get_meta", get_meta_then_expire)
    page = call(repo, sfn, window["bea@example.com"], "POST", "response=accept")
    monkeypatch.undo()
    assert "closed" in page["body"]
    assert meta(repo)["state"] == EXPIRED and meta(repo)["ack_count"] == 1
    assert sfn.calls == []


def test_expire_after_quorum_loses(repo, window):
    sfn = FakeSfn()
    call(repo, sfn, window["al@example.com"], "POST", "response=accept")
    call(repo, sfn, window["bea@example.com"], "POST", "response=accept")
    out = ack_workflow.expire({"reservation_id": "123"}, repository=repo, mode="enforce", now=NOW)
    assert out["expired"] is False and out["cancel"] is False
    assert meta(repo)["state"] == CONFIRMED


def test_callback_errors_for_closed_tasks_are_swallowed(repo, window, caplog):
    caplog.set_level(logging.INFO)
    sfn = FakeSfn(error="TaskTimedOut")
    page = call(repo, sfn, window["owner"], "POST", "response=accept")
    assert page["statusCode"] == 200 and meta(repo)["state"] == CONFIRMED
    assert "task-1" not in caplog.text
    for token in window.values():
        assert token not in caplog.text
    assert send_task_success(FakeSfn(error="TaskDoesNotExist"), "t", "confirmed") is False
    assert send_task_success(FakeSfn(error="InvalidToken"), "t", "confirmed") is False
    with pytest.raises(ClientError):
        send_task_success(FakeSfn(error="AccessDeniedException"), "t", "confirmed")


# expire / notify


@pytest.mark.parametrize("mode,cancel", [("enforce", True), ("notify_only", False)])
def test_expire_cancels_only_in_enforce_mode(repo, window, mode, cancel):
    out = ack_workflow.expire({"reservation_id": "123"}, repository=repo, mode=mode, now=NOW)
    assert out == {
        "expired": True,
        "cancel": cancel,
        "cancel_event": {
            "source": "adhoc",
            "activity": "court1",
            "date": "2026-09-28",
            "time": "17:00",
            "cancel": True,
            "expected_reservation_id": "123",
        },
    }
    assert meta(repo)["state"] == EXPIRED
    retry = ack_workflow.expire({"reservation_id": "123"}, repository=repo, mode=mode, now=NOW)
    assert retry == out


def notify(repo, kind, ses=None):
    ses = ses or FakeSes()
    ack_workflow.notify(
        {"action": "notify", "reservation_id": "123", "kind": kind},
        repository=repo,
        mailer=ack_workflow.Mailer(ses, "bot@example.com"),
        owner_email=OWNER_EMAIL,
        now=NOW,
    )
    return ses


def test_notify_cancelled_sets_state_and_emails_everyone(repo, window):
    ack_workflow.expire({"reservation_id": "123"}, repository=repo, mode="enforce", now=NOW)
    ses = notify(repo, "cancelled")
    assert meta(repo)["state"] == CANCELLED
    assert len(ses.sent) == 4
    assert ses.sent[0]["Content"]["Simple"]["Subject"]["Data"] == "Court released: Mon Sep 28 17:00 (Court 1)"
    notify(repo, "cancelled")
    assert meta(repo)["state"] == CANCELLED


def test_notify_cancel_failed_emails_owner_only(repo, window):
    ack_workflow.expire({"reservation_id": "123"}, repository=repo, mode="enforce", now=NOW)
    ses = notify(repo, "cancel_failed")
    assert meta(repo)["state"] == CANCEL_FAILED
    assert [m["Destination"]["ToAddresses"] for m in ses.sent] == [[OWNER_EMAIL]]
    assert "cancel manually" in ses.sent[0]["Content"]["Simple"]["Subject"]["Data"]


def test_notify_confirmed_lists_players_and_keeps_state(repo, window):
    sfn = FakeSfn()
    call(repo, sfn, window["al@example.com"], "POST", "response=accept")
    call(repo, sfn, window["bea@example.com"], "POST", "response=accept", now=NOW + timedelta(minutes=1))
    ses = notify(repo, "confirmed")
    assert meta(repo)["state"] == CONFIRMED
    assert len(ses.sent) == 4
    html_body = ses.sent[0]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert "Playing: Al &lt;b&gt;&amp; Co&lt;/b&gt;, Bea" in html_body
    ack_workflow.expire({"reservation_id": "123"}, repository=repo, mode="enforce", now=NOW)
    assert meta(repo)["state"] == CONFIRMED


def test_notify_rejects_unknown_kind(repo, window):
    with pytest.raises(ValueError):
        notify(repo, "surprise")


# roster


def test_roster_parses_and_hides_addresses():
    roster = parse_roster(json.dumps({"court1": [{"name": "Al", "email": "al@example.com"}]}))
    assert roster["court1"][0].email == "al@example.com"
    assert "al@example.com" not in repr(roster)
    for bad in ("[]", "{", '{"court1": [{"name": "Al"}]}', '{"court1": [{"name": "", "email": "a@b.c"}]}'):
        with pytest.raises(RosterError) as exc:
            parse_roster(bad)
        assert "@" not in str(exc.value)


def test_roster_reads_secure_parameter():
    class FakeSsm:
        def get_parameter(self, **kwargs):
            self.kwargs = kwargs
            return {"Parameter": {"Value": '{"court2": [{"name": "Bea", "email": "bea@example.com"}]}'}}

    ssm = FakeSsm()
    roster = load_roster("/staging/court-booker-api/ack-roster", client=ssm)
    assert ssm.kwargs == {"Name": "/staging/court-booker-api/ack-roster", "WithDecryption": True}
    assert roster["court2"][0].name == "Bea"

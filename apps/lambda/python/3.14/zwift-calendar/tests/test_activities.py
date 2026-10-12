import copy
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest

from zwift_calendar.activities import collect_power
from zwift_calendar.api import Zwift
from zwift_calendar.errors import ContractError, UpstreamError
from zwift_calendar.power import PowerCurve
from zwift_calendar.transport import Transport

NOW = datetime(2026, 10, 12, tzinfo=UTC)
PROFILE = {"fields": {"profile.profileId": 1}}


def row(identity):
    return {
        "id": identity,
        "sport": "CYCLING",
        "endDate": (NOW - timedelta(days=1)).isoformat(),
        "fitFileKey": "private-url",
    }


def api_for(rows):
    api = Mock()
    api.activities.side_effect = lambda profile, start: rows[start : start + 50]
    api.activity_fit.return_value = b"fit"
    return api


def test_more_than_ten_resume_without_total_cap_and_private_cache(monkeypatch):
    monkeypatch.setattr(
        "zwift_calendar.activities.fit_curve", lambda *args: {"60": 150}
    )
    rows = [row(i) for i in range(125)]
    api = api_for(rows)
    saved = []
    state, report = collect_power(
        api,
        PROFILE,
        {},
        NOW,
        page_limit=1,
        checkpoint=lambda s: saved.append(copy.deepcopy(s)),
    )
    assert report["fit_attempts"] == 10 and report["pending_activities"] == 40
    assert report["collection_incomplete"] and not report["discovery_complete"]
    # New activity during offset pagination must not skip the old boundary.
    rows.insert(0, row(200))
    for _ in range(15):
        state, report = collect_power(api, PROFILE, state, NOW, page_limit=3)
    assert len(state["activities"]) == 126
    assert not any(a["pending"] for a in state["activities"].values())
    state, report = collect_power(api, PROFILE, state, NOW)
    assert not report["collection_incomplete"]
    assert "private-url" not in json.dumps(saved)
    assert api.activity_fit.call_count == 126


def test_failure_retries_and_default_never_claims_confirmed_absence(monkeypatch):
    api = api_for([row(1)])
    api.activity_fit.side_effect = UpstreamError("failed")
    state, report = collect_power(api, PROFILE, {}, NOW)
    assert report["collection_degraded"] and report["pending_activities"] == 1
    assert not report["confirmed_no_activities"]
    assert PowerCurve(list(state["activities"].values()), NOW).default
    api.activity_fit.side_effect = None
    monkeypatch.setattr(
        "zwift_calendar.activities.fit_curve", lambda *args: {"60": 150}
    )
    state, report = collect_power(api, PROFILE, state, NOW)
    assert not report["collection_degraded"] and not report["collection_incomplete"]
    assert not PowerCurve(list(state["activities"].values()), NOW).default
    # A discovery failure can still use the successful cached effort.
    api.activities.side_effect = UpstreamError("offline")
    state, report = collect_power(api, PROFILE, state, NOW)
    assert report["collection_degraded"] and not report["discovery_complete"]
    assert not PowerCurve(list(state["activities"].values()), NOW).default
    state, report = collect_power(api, PROFILE, state, NOW + timedelta(days=28))
    assert state["activities"] == {}
    assert not report["confirmed_no_activities"]


def test_empty_inventory_and_budget_checkpoint():
    api = api_for([])
    state, report = collect_power(api, PROFILE, {}, NOW)
    assert report["confirmed_no_activities"] and not report["collection_incomplete"]
    times = iter([0, 91])
    state, report = collect_power(api, PROFILE, {}, NOW, clock=lambda: next(times))
    assert not report["confirmed_no_activities"] and report["collection_incomplete"]
    assert state["scan"] is not None


def test_changed_recordings_reprocessed_noncycling_ignored(monkeypatch):
    monkeypatch.setattr(
        "zwift_calendar.activities.fit_curve", lambda *args: {"60": 150}
    )
    rows = [
        row(1),
        row(2) | {"sport": "RUNNING"},
        row(3) | {"endDate": None},
        row(4) | {"endDate": (NOW - timedelta(days=28)).isoformat()},
    ]
    api = api_for(rows)
    state, _ = collect_power(api, PROFILE, {}, NOW)
    assert len(state["activities"]) == 1
    rows[0]["lastSaveDate"] = "changed"
    state, _ = collect_power(api, PROFILE, state, NOW)
    assert api.activity_fit.call_count == 2


def test_fit_download_is_bounded_unauthenticated_and_redirects_rejected():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com"})

    http = Transport(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(UpstreamError):
        http.download_fit("https://zwift-fit.s3.amazonaws.com/a.fit")
    assert "Authorization" not in requests[0].headers
    with pytest.raises(ContractError):
        http.download_fit("https://127.0.0.1/a.fit")
    api = Zwift(Mock(), "secret")
    api.http.request.return_value = {
        "id": 2,
        "fitFileBucket": "evil.example/x",
        "fitFileKey": "x",
    }
    with pytest.raises(ContractError):
        api.activity_fit(1, 2)


def encoded_fit(watts):
    """A genuine tiny FIT file with definition, records and valid CRCs."""
    import struct

    from fitdecode.utils import compute_crc

    # Local message 0, global record (20), timestamp(253 uint32), power(7 uint16).
    body = bytearray(
        bytes([0x40, 0, 0])
        + struct.pack("<H", 20)
        + bytes([2, 253, 4, 0x86, 7, 2, 0x84])
    )
    for i, power in enumerate(watts):
        body.extend(struct.pack("<BIH", 0, 1000000000 + i, power))
    header = struct.pack("<BBHI4s", 14, 0x20, 2140, len(body), b".FIT")
    header += struct.pack("<H", compute_crc(header))
    data = header + body
    return data + struct.pack("<H", compute_crc(data))


def test_actual_fit_decode_and_corruption():
    from zwift_calendar.power import fit_curve

    data = encoded_fit([200] * 30 + [0] * 30)
    assert fit_curve(data) == {"60": 100}
    with pytest.raises(ContractError):
        fit_curve(data[:-4] + b"xxxx")


def test_profile_converts_units_without_storing_ftp_score_as_power():
    http = Mock()
    http.request.side_effect = [
        {"id": 1, "male": True, "weight": 75000, "height": 1830, "ftp": 999},
        {"scores": {}},
        {"scores": {}},
    ]
    profile = Zwift(http, "token").profile(NOW)
    assert profile["body"] == {"weight_kg": 75, "height_cm": 183}
    assert "ftp" not in json.dumps(profile)

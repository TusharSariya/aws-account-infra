from datetime import UTC, datetime

import pytest
from booker.calendar_contract import normalize_reservation, utc_datetime


@pytest.mark.parametrize(
    ("local", "utc"),
    [
        ("2026-01-12 17:00:00", "2026-01-12T20:30:00+00:00"),
        ("2026-07-13 17:00:00", "2026-07-13T19:30:00+00:00"),
        ("2026-11-01T01:30:00-02:30", "2026-11-01T04:00:00+00:00"),
        ("2026-11-01T01:30:00-03:30", "2026-11-01T05:00:00+00:00"),
    ],
)
def test_newfoundland_offsets(local, utc):
    assert utc_datetime(local).isoformat() == utc


@pytest.mark.parametrize("local", ["2026-03-08 02:30:00", "2026-11-01 01:30:00"])
def test_transition_times_require_explicit_offset(local):
    with pytest.raises(ValueError, match="requires an offset"):
        utc_datetime(local)


def test_normalized_reservation_preserves_actual_duration():
    result = normalize_reservation(
        reservation_id=123,
        equipment_id=7412,
        court="Court 1",
        start="2026-01-12 17:00:00",
        end="2026-01-12 18:30:00",
    )
    assert result["reservation_id"] == "123"
    assert result["start"] == "2026-01-12T20:30:00+00:00"
    assert result["end"] == "2026-01-12T22:00:00+00:00"


def test_rejects_nonpositive_duration():
    with pytest.raises(ValueError, match="end must follow"):
        normalize_reservation(
            reservation_id=123,
            equipment_id=7412,
            court="Court 1",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 1, tzinfo=UTC),
        )

from pathlib import Path

from booker.config import load_bookings

BOOKINGS = Path(__file__).resolve().parents[5] / "ecr/court-booker/bookings.yaml"


def test_default_bookings_yaml():
    config = load_bookings(BOOKINGS)
    assert config.timezone == "America/St_Johns"
    assert config.horizon_hours == 72
    assert config.gym_id == 785
    assert config.equipment_ids["court1"] == 7412
    assert config.equipment_ids["court2"] == 12739
    assert config.weekly[0].time == "17:00"

    assert [(r.activity, r.weekday, r.time) for r in config.weekly if r.enabled] == [
        ("court1", "Wed", "09:00"),
    ]

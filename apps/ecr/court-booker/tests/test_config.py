from pathlib import Path

from booker.config import load_bookings

ROOT = Path(__file__).resolve().parents[1]


def test_default_bookings_yaml():
    config = load_bookings(ROOT / "bookings.yaml")
    assert config.timezone == "America/St_Johns"
    assert config.horizon_hours == 72
    assert config.gym_id == 785
    assert "court1" in config.activities
    assert config.activity_label("court1").startswith("3-1")
    assert config.weekly[0].weekday == "Mon"
    assert config.weekly[0].time == "17:00"
    assert config.weekly[0].enabled is False
    assert config.weekly[1].activity == "court2"
    assert config.weekly[1].time == "20:00"
    assert config.weekly[1].enabled is True

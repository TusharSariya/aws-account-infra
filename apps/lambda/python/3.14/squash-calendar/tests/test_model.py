from datetime import date

import pytest

from squash_calendar.model import backtest, fit, probability


def matches(a="a", b="b", winner="a", n=10, day="2026-10-01"):
    return [
        {"id": str(i), "date": day, "home": a, "away": b, "winner": winner}
        for i in range(n)
    ]


def test_symmetry_recency_regularization_and_minimum_support():
    history = matches()
    model = fit(history, date(2026, 10, 12))
    p = probability(model, "a", "b")
    assert 0.5 < p < 1
    assert probability(model, "b", "a") == pytest.approx(1 - p)
    assert probability(fit(history[:4], date(2026, 10, 12)), "a", "b") is None
    old = probability(fit(history, date(2027, 10, 12)), "a", "b")
    assert 0.5 < old < p
    assert sum(model[0].values()) == pytest.approx(0, abs=1e-6)


def test_disconnected_graph_and_future_results():
    history = matches() + matches("c", "d", "c")
    assert probability(fit(history, date(2026, 10, 12)), "a", "c") is None
    history += matches("a", "b", "b", 100, "2026-10-13")
    assert probability(fit(history, date(2026, 10, 12)), "a", "b") > 0.5


def test_chronological_backtest_never_trains_on_same_day():
    history = matches()
    assert backtest(history)["sample_count"] == 0
    history += matches(n=2, day="2026-10-02")
    outcome = backtest(history)
    assert outcome["sample_count"] == 2
    assert 0 < outcome["brier"] < 0.25

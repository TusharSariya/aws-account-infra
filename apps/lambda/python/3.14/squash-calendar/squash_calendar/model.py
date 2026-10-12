"""Regularized Bradley-Terry, independent of official ratings."""

import math
from collections import Counter, defaultdict
from datetime import date, timedelta

VERSION = "bradley-terry-v1; half-life=180d; L2=1"


def logistic(value):
    return 1 / (1 + math.exp(-max(-40, min(40, value))))


def fit(matches, day):
    cutoff = day - timedelta(days=731)
    history = [m for m in matches if cutoff <= date.fromisoformat(m["date"]) < day]
    counts, neighbors = Counter(), defaultdict(set)
    strengths, weighted = {}, []
    for m in history:
        a, b = m["home"], m["away"]
        counts.update((a, b))
        neighbors[a].add(b)
        neighbors[b].add(a)
        strengths[a] = strengths[b] = 0.0
        weight = 2 ** (-(day - date.fromisoformat(m["date"])).days / 180)
        weighted.append((a, b, float(m["winner"] == a), weight))
    # The logistic Hessian is bounded by the weighted graph Laplacian / 4.
    # This conservative global step converges to the unique L2-regularized optimum.
    degree = Counter()
    for a, b, _, w in weighted:
        degree[a] += w
        degree[b] += w
    step = 1 / (1 + max(degree.values(), default=0) / 2)
    for _ in range(1000):
        gradient = dict(strengths)  # derivative of 0.5 * lambda * sum(s^2)
        for a, b, y, w in weighted:
            error = w * (logistic(strengths[a] - strengths[b]) - y)
            gradient[a] += error
            gradient[b] -= error
        change = max((abs(step * v) for v in gradient.values()), default=0)
        for pid in strengths:
            strengths[pid] -= step * gradient[pid]
        if change < 1e-7:
            break
    return strengths, counts, neighbors


def probability(model, a, b):
    strengths, counts, neighbors = model
    if counts[a] < 5 or counts[b] < 5:
        return None
    visited, todo = {a}, [a]
    while todo:
        for neighbor in neighbors[todo.pop()]:
            if neighbor not in visited:
                visited.add(neighbor)
                todo.append(neighbor)
    if b not in visited:
        return None
    return logistic(strengths[a] - strengths[b])


def backtest(matches):
    """Group by date so no result on the prediction date enters training."""
    days = defaultdict(list)
    for match in matches:
        days[match["date"]].append(match)
    errors = []
    for day, heldout in sorted(days.items()):
        model = fit(matches, date.fromisoformat(day))
        for m in heldout:
            p = probability(model, m["home"], m["away"])
            if p is not None:
                errors.append((p - (m["winner"] == m["home"])) ** 2)
    return {
        "sample_count": len(errors),
        "brier": sum(errors) / len(errors) if errors else None,
    }

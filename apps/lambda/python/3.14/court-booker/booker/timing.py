from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


def log_timing(op: str, step: str, *, step_ms: float, elapsed_ms: float, **extra: Any) -> None:
    payload = {
        "timing": True,
        "op": op,
        "step": step,
        "step_ms": round(step_ms, 1),
        "elapsed_ms": round(elapsed_ms, 1),
        **extra,
    }
    print(json.dumps(payload), flush=True)


class Stopwatch:
    """Print JSON timing lines for CloudWatch. Never attach secrets."""

    def __init__(self, op: str, **extra: Any) -> None:
        self.op = op
        self.extra = extra
        self._t0 = time.perf_counter()
        self._last = self._t0

    def mark(self, step: str, **extra: Any) -> None:
        now = time.perf_counter()
        log_timing(
            self.op,
            step,
            step_ms=(now - self._last) * 1000,
            elapsed_ms=(now - self._t0) * 1000,
            **self.extra,
            **extra,
        )
        self._last = now

    @contextmanager
    def step(self, name: str, **extra: Any) -> Iterator[None]:
        try:
            yield
        finally:
            self.mark(name, **extra)

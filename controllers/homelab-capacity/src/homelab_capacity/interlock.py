"""Shared, durable per-host exclusion for maintenance and physical effects.

The directory is the IMM lock directory, not a second coordinator-specific lock.
Uncertain writes stay pending until an independent observation proves completion.
"""

import threading
import time
import uuid
from contextlib import contextmanager

from .journal import Journal


class PowerBlocked(RuntimeError):
    pass


_held = threading.local()


class Interlock:
    def __init__(self, directory, host):
        self.journal = Journal(directory)
        self.host = host
        self.name = host + "-interlock.json"
        self.key = str(self.journal.directory.resolve()) + "/" + host

    @contextmanager
    def locked(self):
        held = getattr(_held, "keys", set())
        if self.key in held:
            yield
            return
        with self.journal.locked(self.host + ".lock"):
            _held.keys = held | {self.key}
            try:
                yield
            finally:
                _held.keys = held

    def read(self):
        return self.journal.read(self.name, {"holds": {}, "pending": None})

    @contextmanager
    def guard(self):
        with self.locked():
            record = self.read()
            if record["holds"]:
                raise PowerBlocked("Maintenance requested; power changes inhibited")
            if record["pending"]:
                raise PowerBlocked(
                    "Unresolved power operation; observe before proceeding"
                )
            yield

    def begin(self, action, **evidence):
        # Caller holds guard across the write and the external request.
        with self.guard():
            record = self.read()
            record["pending"] = dict(
                action=action, id=str(uuid.uuid4()), at=time.time(), **evidence
            )
            self.journal.write(self.name, record)

    def settle(self, action):
        with self.locked():
            record = self.read()
            if record["pending"] and record["pending"]["action"] == action:
                record["last_completed"] = record["pending"] | {
                    "completed_at": time.time()
                }
                record["pending"] = None
                self.journal.write(self.name, record)

    def acquire(self, token, reason):
        if not token or not reason:
            raise ValueError("Maintenance token and reason are required")
        with self.locked():
            record = self.read()
            old = record["holds"].get(token)
            if old and old["reason"] != reason:
                raise ValueError("Maintenance token already has another purpose")
            # Only the coordinator acknowledges, after checking lifecycle state.
            record["holds"].setdefault(token, {"reason": reason, "acknowledged": False})
            self.journal.write(self.name, record)
            return record["holds"][token]

    def acknowledge(self, *, settled):
        with self.locked():
            record = self.read()
            if settled and not record["pending"]:
                for hold in record["holds"].values():
                    hold["acknowledged"] = True
                self.journal.write(self.name, record)

    def release(self, token):
        with self.locked():
            record = self.read()
            if token not in record["holds"]:
                raise ValueError("Existing maintenance token required")
            del record["holds"][token]
            self.journal.write(self.name, record)

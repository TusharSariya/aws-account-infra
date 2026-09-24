"""Crash-durable request scheduling. SQLite owns slots, attempts and fairness."""

import contextlib
import hashlib
import json
import sqlite3
import time
import uuid

POLICIES = {"gpu-preferred", "gpu-required", "cpu-only"}
TERMINAL = {"succeeded", "failed", "expired", "interrupted"}


def backend_order(profile):
    # Operator ordering only breaks ties within a policy tier.
    tier = 0 if profile["kind"] == "gpu" else 1 if profile.get("desktop") else 2
    return tier, profile.get("priority", 0), profile["id"]


class Store:
    def __init__(self, path, *, limit=1024, retention_limit=512):
        self.path, self.limit, self.retention_limit = str(path), limit, retention_limit
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS requests (
                  id TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL,
                  policy TEXT NOT NULL, lane TEXT NOT NULL, retry_safe INTEGER NOT NULL,
                  stream INTEGER NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
                  deadline REAL, backend TEXT, attempt INTEGER NOT NULL DEFAULT 0,
                  result TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS attempts (
                  request TEXT NOT NULL, number INTEGER NOT NULL, backend TEXT NOT NULL,
                  generation TEXT NOT NULL, started REAL NOT NULL, state TEXT NOT NULL,
                  PRIMARY KEY(request, number));
                CREATE TABLE IF NOT EXISTS fairness (backend TEXT PRIMARY KEY, live INTEGER NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_slot ON requests(backend)
                  WHERE state IN ('running', 'uncertain');
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextlib.contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def submit(
        self,
        payload,
        *,
        policy="gpu-preferred",
        lane="batch",
        retry_safe=False,
        request_id=None,
        stream=False,
        now=None,
    ):
        if (
            policy not in POLICIES
            or lane not in {"live", "batch"}
            or (stream and lane != "live")
        ):
            raise ValueError("Invalid policy, lane or streaming mode")
        now = time.time() if now is None else now
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(body.encode()) > 65536:
            raise ValueError("Request exceeds 64 KiB")
        digest = hashlib.sha256(
            json.dumps([body, policy, lane, bool(retry_safe), stream]).encode()
        ).hexdigest()
        key = request_id or str(uuid.uuid4())
        if (
            len(key) > 128
            or not key
            or any(
                c
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                for c in key
            )
        ):
            raise ValueError("Invalid Idempotency-Key")
        with self.transaction() as db:
            old = db.execute("SELECT * FROM requests WHERE id=?", (key,)).fetchone()
            if old:
                if old["digest"] != digest:
                    raise ValueError("Idempotency-Key reused with different work")
                return dict(old)
            count = db.execute(
                "SELECT count(*) FROM requests WHERE state IN ('queued','running','uncertain')"
            ).fetchone()[0]
            total = db.execute("SELECT count(*) FROM requests").fetchone()[0]
            if count >= self.limit or total >= self.retention_limit:
                raise OverflowError("Queue or retained-result capacity reached")
            db.execute(
                "INSERT INTO requests(id,digest,payload,policy,lane,retry_safe,stream,state,created,deadline) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    digest,
                    body,
                    policy,
                    lane,
                    bool(retry_safe),
                    stream,
                    "queued",
                    now,
                    now + 30 if lane == "live" else None,
                ),
            )
            return dict(
                db.execute("SELECT * FROM requests WHERE id=?", (key,)).fetchone()
            )

    def get(self, key):
        with contextlib.closing(self.connect()) as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (key,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def expire_queued(db, now):
        db.execute(
            "UPDATE requests SET state='expired',error='Admission exceeded 30 seconds' WHERE state='queued' AND deadline<=?",
            (now,),
        )

    def pending(self):
        with self.transaction() as db:
            self.expire_queued(db, time.time())
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM requests WHERE state='queued' ORDER BY created,id"
                )
            ]

    def claim(self, profiles, now=None):
        """One slot per healthy backend; process GPUs before desktop/server CPUs."""
        now = time.time() if now is None else now
        claimed = []
        with self.transaction() as db:
            self.expire_queued(db, now)
            for profile in sorted(profiles, key=backend_order):
                if not profile.get("healthy") or not profile.get("generation"):
                    continue
                backend = profile["id"]
                if db.execute(
                    "SELECT 1 FROM requests WHERE backend=? AND state IN ('running','uncertain')",
                    (backend,),
                ).fetchone():
                    continue
                candidates = [
                    r
                    for r in db.execute(
                        "SELECT * FROM requests WHERE state='queued' ORDER BY created,id"
                    )
                    if json.loads(r["payload"])["model"] == profile["model"]
                    and (
                        profile["kind"] == "gpu"
                        and r["policy"] != "cpu-only"
                        or profile["kind"] == "cpu"
                        and r["policy"] != "gpu-required"
                    )
                ]
                live = [r for r in candidates if r["lane"] == "live"]
                batch = [r for r in candidates if r["lane"] == "batch"]
                if not candidates:
                    continue
                row = db.execute(
                    "SELECT live FROM fairness WHERE backend=?", (backend,)
                ).fetchone()
                turns = row[0] if row else 0
                selected = live[0] if live and (not batch or turns < 3) else batch[0]
                db.execute(
                    "INSERT INTO fairness VALUES(?,?) ON CONFLICT(backend) DO UPDATE SET live=excluded.live",
                    (backend, min(turns + 1, 3) if selected["lane"] == "live" else 0),
                )
                db.execute(
                    "UPDATE requests SET state='running',backend=?,attempt=attempt+1 WHERE id=?",
                    (backend, selected["id"]),
                )
                db.execute(
                    "INSERT INTO attempts VALUES(?,?,?,?,?,'running')",
                    (
                        selected["id"],
                        selected["attempt"] + 1,
                        backend,
                        profile["generation"],
                        now,
                    ),
                )
                claimed.append(
                    dict(
                        db.execute(
                            "SELECT * FROM requests WHERE id=?", (selected["id"],)
                        ).fetchone()
                    )
                )
        return claimed

    def complete(self, key, attempt, result):
        encoded = json.dumps(result)
        if len(encoded.encode()) > 1024 * 1024:
            raise ValueError("Result exceeds 1 MiB")
        with self.transaction() as db:
            # Only the current attempt may publish, once. A late result can settle uncertainty.
            changed = db.execute(
                "UPDATE requests SET state='succeeded',result=?,error=NULL WHERE id=? AND attempt=? AND state IN ('running','uncertain')",
                (encoded, key, attempt),
            ).rowcount
            if changed:
                db.execute(
                    "UPDATE attempts SET state='succeeded' WHERE request=? AND number=?",
                    (key, attempt),
                )
            return bool(changed)

    def failed(self, key, attempt, reason, *, terminated):
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM requests WHERE id=? AND attempt=? AND state IN ('running','uncertain')",
                (key, attempt),
            ).fetchone()
            if not row:
                return
            state = "uncertain"
            if terminated:
                state = (
                    "interrupted"
                    if row["stream"]
                    else "queued"
                    if row["retry_safe"] and attempt < 3
                    else "failed"
                )
            db.execute(
                "UPDATE requests SET state=?,error=? WHERE id=?",
                (state, reason[:512], key),
            )
            db.execute(
                "UPDATE attempts SET state=? WHERE request=? AND number=?",
                (state, key, attempt),
            )

    def recover(self):
        with self.transaction() as db:
            db.execute(
                "UPDATE requests SET state='uncertain',error='Controller restarted during execution' WHERE state='running'"
            )
            db.execute("UPDATE attempts SET state='uncertain' WHERE state='running'")

    def fenced_by_reboot(self, profiles):
        """A new Pod UID alone is NOT fencing: disconnected nodes can retain old processes."""
        with contextlib.closing(self.connect()) as db:
            rows = list(
                db.execute(
                    "SELECT r.id,r.attempt,r.backend,a.generation FROM requests r JOIN attempts a ON a.request=r.id AND a.number=r.attempt WHERE r.state='uncertain'"
                )
            )
        by_id = {p["id"]: p for p in profiles}
        for row in rows:
            p = by_id.get(row["backend"])
            if (
                p
                and p.get("nodeReady", p.get("healthy"))
                and p.get("generation")
                and (
                    (
                        len(p["generation"].split("/")) == 3
                        and len(row["generation"].split("/")) == 3
                        and p["generation"].split("/")[0]
                        == row["generation"].split("/")[0]
                        and p["generation"].split("/")[1]
                        and row["generation"].split("/")[1]
                        and p["generation"].split("/")[1]
                        != row["generation"].split("/")[1]
                    )
                    or p.get("terminated")
                    and p["generation"] == row["generation"]
                )
            ):
                self.failed(
                    row["id"],
                    row["attempt"],
                    "Prior execution fenced by verified node reboot",
                    terminated=True,
                )

    def occupied(self, backend):
        with contextlib.closing(self.connect()) as db:
            return (
                db.execute(
                    "SELECT 1 FROM requests WHERE backend=? AND state IN ('running','uncertain')",
                    (backend,),
                ).fetchone()
                is not None
            )

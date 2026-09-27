"""Model catalog: technical facts and per-backend copies, SQLite with the batch gateway's discipline."""
import fcntl
import sqlite3
import time

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS models (
  name TEXT PRIMARY KEY, architecture TEXT, weight_bytes INTEGER NOT NULL, native_max INTEGER NOT NULL,
  bytes_per_token INTEGER NOT NULL, fixed_cache INTEGER NOT NULL, exact INTEGER NOT NULL DEFAULT 0,
  fit_override INTEGER NOT NULL DEFAULT 0, added_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS copies (
  model TEXT NOT NULL, backend TEXT NOT NULL, digest TEXT NOT NULL, pulled_at REAL NOT NULL,
  PRIMARY KEY (model, backend));
CREATE TABLE IF NOT EXISTS pulls (
  model TEXT NOT NULL, backend TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL, status TEXT NOT NULL,
  PRIMARY KEY (model, backend, started_at));
"""


class Catalog:
    def __init__(self, path):
        self.path = str(path)
        self.lock = open(self.path + '.lock', 'a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # One router process per state volume.
        with self.connect() as db:
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def record_model(self, name, weight_bytes, native_max, bytes_per_token, fixed_cache, architecture, exact):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO models (name, architecture, weight_bytes, native_max, bytes_per_token, fixed_cache, exact, added_at)'
                       ' VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET architecture=excluded.architecture,'
                       ' weight_bytes=excluded.weight_bytes, native_max=excluded.native_max, bytes_per_token=excluded.bytes_per_token,'
                       ' fixed_cache=excluded.fixed_cache, exact=excluded.exact',
                       (name, architecture, weight_bytes, native_max, bytes_per_token, fixed_cache, int(exact), time.time()))
            db.execute('COMMIT')

    def record_copy(self, name, backend, digest):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO copies (model, backend, digest, pulled_at) VALUES (?, ?, ?, ?)'
                       ' ON CONFLICT(model, backend) DO UPDATE SET digest=excluded.digest, pulled_at=excluded.pulled_at',
                       (name, backend, digest, time.time()))
            db.execute('COMMIT')

    def remove(self, name):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM copies WHERE model = ?', (name,))
            db.execute('DELETE FROM models WHERE name = ?', (name,))
            db.execute('COMMIT')

    def set_override(self, name, enabled):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE models SET fit_override = ? WHERE name = ?', (int(bool(enabled)), name)).rowcount
            db.execute('COMMIT')
        return changed == 1

    def model(self, name):
        with self.connect() as db:
            row = db.execute('SELECT * FROM models WHERE name = ?', (name,)).fetchone()
        return dict(row) if row else None

    def copies(self, name=None):
        with self.connect() as db:
            if name is None:
                rows = db.execute('SELECT * FROM copies ORDER BY model, backend').fetchall()
            else:
                rows = db.execute('SELECT * FROM copies WHERE model = ? ORDER BY backend', (name,)).fetchall()
        return [dict(r) for r in rows]

    def models(self):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM models ORDER BY name').fetchall()
        return [dict(r) for r in rows]

    def pull_started(self, name, backend):
        started = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO pulls (model, backend, started_at, status) VALUES (?, ?, ?, ?)', (name, backend, started, 'running'))
            db.execute('COMMIT')
        return started

    def pull_finished(self, name, backend, started, status):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE pulls SET finished_at = ?, status = ? WHERE model = ? AND backend = ? AND started_at = ?',
                       (time.time(), status, name, backend, started))
            db.execute('COMMIT')

"""SQLite persistence layer.

A single SQLite database file (stored on the Railway volume) holds API keys,
request logs, counters and dashboard settings.  The database uses WAL mode so
reads never block writes, and every connection is cached per thread.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    key_hash      TEXT    NOT NULL UNIQUE,
    key_prefix    TEXT    NOT NULL,
    key_last4     TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    last_used_at  TEXT,
    revoked       INTEGER NOT NULL DEFAULT 0,
    revoked_at    TEXT,
    request_count INTEGER NOT NULL DEFAULT 0,
    image_count   INTEGER NOT NULL DEFAULT 0,
    bytes_in      INTEGER NOT NULL DEFAULT 0,
    bytes_out     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS api_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id  INTEGER,
    key_label   TEXT    NOT NULL DEFAULT 'admin',
    endpoint    TEXT    NOT NULL,
    method      TEXT    NOT NULL,
    source      TEXT,
    status_code INTEGER NOT NULL,
    success     INTEGER NOT NULL,
    bytes_in    INTEGER NOT NULL DEFAULT 0,
    bytes_out   INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_requests_created ON api_requests (created_at);
CREATE INDEX IF NOT EXISTS idx_api_requests_key     ON api_requests (api_key_id);
CREATE INDEX IF NOT EXISTS idx_api_requests_success ON api_requests (success);
"""


def utcnow() -> str:
    """UTC timestamp in ISO-8601 with a trailing Z."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Database:
    """Thread-safe SQLite wrapper (one connection per thread)."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # -- connection handling ------------------------------------------------
    @property
    def path(self) -> Path:
        return self._path

    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._path), timeout=30.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        cur = self.connect().cursor()
        try:
            yield cur
        finally:
            cur.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        """Serialised write transaction."""
        with self._write_lock:
            conn = self.connect()
            cur = conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                yield cur
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                cur.close()

    # -- schema -------------------------------------------------------------
    def init_schema(self) -> None:
        with self._write_lock:
            conn = self.connect()
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO counters (name, value) VALUES (?, 0)",
                ("images_processed",),
            )
            conn.execute(
                "INSERT OR IGNORE INTO counters (name, value) VALUES (?, 0)",
                ("api_requests",),
            )

    # -- helpers ------------------------------------------------------------
    def get_counter(self, name: str) -> int:
        with self.cursor() as cur:
            cur.execute("SELECT value FROM counters WHERE name = ?", (name,))
            row = cur.fetchone()
        return int(row["value"]) if row else 0

    def increment_counter(self, name: str, amount: int = 1) -> None:
        if amount == 0:
            return
        with self.transaction() as cur:
            cur.execute(
                "INSERT INTO counters (name, value) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value = value + excluded.value",
                (name, amount),
            )

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.cursor() as cur:
            cur.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cur.fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.transaction() as cur:
            cur.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, value, utcnow()),
            )

    def all_settings(self) -> dict[str, str]:
        with self.cursor() as cur:
            cur.execute("SELECT key, value FROM app_settings")
            return {row["key"]: row["value"] for row in cur.fetchall()}


_database: Optional[Database] = None
_db_lock = threading.Lock()


def get_db() -> Database:
    """Return the process-wide database handle."""
    global _database
    if _database is None:
        with _db_lock:
            if _database is None:
                _database = Database(get_settings().db_path)
    return _database


def init_db() -> Database:
    """Create the schema (idempotent) and return the database handle."""
    db = get_db()
    db.init_schema()
    return db


def reset_db() -> None:
    """Testing helper - drop the cached database handle."""
    global _database
    with _db_lock:
        if _database is not None:
            _database.close()
        _database = None


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None

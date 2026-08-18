# db.py
# Local SQLite persistence for streamlit-ui (BACKLOG #64, Card 3).
#
# DB path: /data/streamlit-ui/streamlit-ui.db (bind-mounted from
# streamlit-ui-stack/data on the host).
#
# All schema migrations are idempotent (CREATE TABLE IF NOT EXISTS).
# No plain-text credentials are stored — only bcrypt hashes (and those
# are reserved for the v2 multi-user model; v1.0 admin is via env vars).
#
# Threading note: streamlit runs each script rerun on the main thread but
# concurrent users cause concurrent sqlite connections from the same
# process. We use sqlite3 with check_same_thread=False and serialize
# writes via a threading.Lock to avoid "database is locked" errors.

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(os.environ.get(
    "STREAMLIT_UI_DB",
    "/data/streamlit-ui/streamlit-ui.db",
))

# Serialize writes across streamlit's concurrent reruns.
_WRITE_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    """Open a sqlite3 connection with sane defaults.

    check_same_thread=False is required because streamlit's WebSocket
    workers share one Python process and may call get_db() concurrently.
    We serialize writes via _WRITE_LOCK below; reads can run in parallel.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Foreign keys are off by default in sqlite3; enable them so the
    # user_id FK in chat_sessions / playbook_runs actually constrains.
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL mode gives us better concurrent-read-while-writing behavior.
    # Without it, the second connection to the DB gets SQLITE_BUSY.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    title       TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    last_active TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS playbook_runs (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    playbook    TEXT NOT NULL,
    inventory   TEXT NOT NULL,
    target      TEXT,
    mode        TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at  TEXT,
    finished_at TEXT,
    exit_code   INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS playbook_run_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    ts         TEXT DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    payload    TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES playbook_runs(id)
);

CREATE TABLE IF NOT EXISTS ui_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def init_schema() -> None:
    """Run idempotent schema migrations. Called once from Home.py at startup."""
    with _WRITE_LOCK:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def get_db() -> sqlite3.Connection:
    """Return a connection. Caller is responsible for closing it (or use
    `with db() as conn:`). The connection is opened per-call so callers
    don't need to worry about cross-thread state.
    """
    return _connect()


# Convenience context manager for callers that prefer `with`.
from contextlib import contextmanager  # noqa: E402  (down here to avoid noise at top)


@contextmanager
def db():
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def get_or_create_user(username: str, password_hash: str | None = None) -> int:
    """Return the user's id, creating a row on first call. Idempotent.

    For v1.0 single-admin, this is called once on first successful login.
    The admin password_hash is whatever the operator set via env
    (bcrypt hash if available, plain text never stored).
    """
    with _WRITE_LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if row:
                return row["id"]
            cur = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),  # type: ignore[arg-type]
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

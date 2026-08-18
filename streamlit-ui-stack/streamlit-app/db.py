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
    id                TEXT PRIMARY KEY,           -- X-Hermes-Session-Id UUID
    user_id           INTEGER NOT NULL,
    title             TEXT,
    -- Per-turn handle for chaining. start_chat stores the resp_... from
    -- /v1/responses; continue_chat reads this and passes it back as
    -- previous_response_id. Card 5 added this column on top of Card 3's
    -- schema (which only had id/user_id/title/created_at/last_active).
    last_response_id  TEXT,
    -- Soft-delete flag. If Hermes's DELETE /api/sessions/<id> fails,
    -- 7_Chat_Sessions.py sets archived=1 so the row stays out of the
    -- default list but isn't physically destroyed.
    archived          INTEGER DEFAULT 0,
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    last_active       TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    -- Per-turn message log for chat display. Hermes does NOT expose
    -- message bodies via /api/sessions/<id> (Card 5 verified: the
    -- endpoint only returns session-level metadata, not the transcript),
    -- so we persist locally for re-render on page reload + on subsequent
    -- page opens. Bodies stay on the customer's box — they are NEVER
    -- sent to Loki (privacy contract, BACKLOG #64 v1.0).
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    role            TEXT NOT NULL,                 -- 'user' | 'assistant'
    content         TEXT NOT NULL,
    response_id     TEXT,                          -- assistant turns only
    tool_calls_json TEXT,                          -- JSON; assistant turns only
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
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
    """Run idempotent schema migrations. Called once from Home.py at startup.

    Card 5 added chat_sessions.last_response_id AFTER Card 3's initial
    schema shipped. CREATE TABLE IF NOT EXISTS won't add a column to an
    existing table, so we also try ALTER TABLE ... ADD COLUMN here and
    swallow the "duplicate column" error. Result: fresh DBs get the
    column from the CREATE; existing DBs get it from the ALTER.
    """
    with _WRITE_LOCK:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
            # Idempotent column additions for Card 5.
            for ddl in (
                "ALTER TABLE chat_sessions ADD COLUMN last_response_id TEXT",
                "ALTER TABLE chat_sessions ADD COLUMN archived INTEGER DEFAULT 0",
                # chat_messages is a NEW table for Card 5 — covered by the
                # CREATE TABLE IF NOT EXISTS above, no ALTER needed.
            ):
                try:
                    conn.execute(ddl)
                    conn.commit()
                except sqlite3.OperationalError as e:
                    # "duplicate column name" = column already exists,
                    # which is the expected state on every run after the
                    # first. Anything else is a real error worth surfacing.
                    if "duplicate column" not in str(e):
                        raise
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


# ---------------------------------------------------------------------------
# Card 5 — chat session / message persistence helpers
# ---------------------------------------------------------------------------
#
# These are thin wrappers around the chat_sessions + chat_messages tables.
# Kept here (not in hermes_client.py) because they're SQLite-only concerns —
# hermes_client.py stays purely about talking to the Hermes gateway.

from datetime import datetime, timezone  # noqa: E402


def _now_iso() -> str:
    """UTC timestamp in ISO 8601 (no microseconds) for last_active fields."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def create_chat_session(
    session_id: str,
    user_id: int,
    title: str | None,
    last_response_id: str | None,
) -> None:
    """Insert a new chat_sessions row. Idempotent on the PK (replace)."""
    with _WRITE_LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO chat_sessions "
                "(id, user_id, title, last_response_id, created_at, last_active) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
                (session_id, user_id, title, last_response_id, _now_iso()),
            )
            conn.commit()
        finally:
            conn.close()


def update_chat_session_response(
    session_id: str,
    last_response_id: str,
    title: str | None = None,
) -> None:
    """Update the last_response_id + last_active for a session.

    If `title` is provided AND the session currently has no title, set it.
    We don't overwrite an existing title — the user may have renamed it.
    """
    with _WRITE_LOCK:
        conn = _connect()
        try:
            if title is not None:
                conn.execute(
                    "UPDATE chat_sessions SET "
                    "  last_response_id = ?, "
                    "  last_active = ?, "
                    "  title = COALESCE(NULLIF(title, ''), ?) "
                    "WHERE id = ?",
                    (last_response_id, _now_iso(), title, session_id),
                )
            else:
                conn.execute(
                    "UPDATE chat_sessions SET "
                    "  last_response_id = ?, "
                    "  last_active = ? "
                    "WHERE id = ?",
                    (last_response_id, _now_iso(), session_id),
                )
            conn.commit()
        finally:
            conn.close()


def list_chat_sessions(user_id: int, *, include_archived: bool = False) -> list[dict]:
    """Return all chat_sessions for a user, newest first.

    Excludes archived rows by default (delete_session flips the
    archived flag if the Hermes DELETE fails — see 7_Chat_Sessions.py).
    """
    with _WRITE_LOCK:
        conn = _connect()
        try:
            sql = (
                "SELECT id, title, last_response_id, created_at, last_active "
                "FROM chat_sessions "
                "WHERE user_id = ? "
            )
            if not include_archived:
                sql += "AND archived = 0 "
            sql += "ORDER BY COALESCE(last_active, created_at) DESC"
            cur = conn.execute(sql, (user_id,))
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def get_chat_session(session_id: str, user_id: int) -> dict | None:
    """Return a single chat_sessions row (scoped to user_id). None if absent."""
    with _WRITE_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT id, title, last_response_id, created_at, last_active "
                "FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def add_chat_message(
    session_id: str,
    role: str,
    content: str,
    *,
    response_id: str | None = None,
    tool_calls_json: str | None = None,
) -> int:
    """Insert one row into chat_messages. Returns the new row id."""
    with _WRITE_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "INSERT INTO chat_messages "
                "(session_id, role, content, response_id, tool_calls_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, response_id, tool_calls_json),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def list_chat_messages(session_id: str) -> list[dict]:
    """Return all chat_messages for a session, oldest first."""
    with _WRITE_LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT id, role, content, response_id, tool_calls_json, created_at "
                "FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def delete_chat_session(session_id: str, user_id: int) -> bool:
    """Delete a chat session row (and its messages via ON DELETE CASCADE).

    Scoped to user_id so user A can't delete user B's session.
    Returns True if a row was deleted.
    """
    with _WRITE_LOCK:
        conn = _connect()
        try:
            # Delete messages first — sqlite's ON DELETE CASCADE only
            # fires for FK enforcement enabled (which we do), but doing
            # it explicitly keeps the DB tidy regardless.
            conn.execute(
                "DELETE FROM chat_messages WHERE session_id = ?", (session_id,)
            )
            cur = conn.execute(
                "DELETE FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

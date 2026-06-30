"""Shared pytest fixtures for kb-stack unit tests.

The tests target server.py directly, importing the module so we can call
the tool functions without going over MCP/HTTP. We monkeypatch DB_PATH
to a tmp file and re-run init_db() so each test session gets a fresh
schema. The FTS5 triggers are part of init_db.sql, so the FTS index
stays in sync with kb_entries throughout.
"""

from __future__ import annotations

import os
import sys
import pathlib

import pytest

# Make the mcp/ dir importable so `import server` resolves.
HERE = pathlib.Path(__file__).resolve().parent
MCP_DIR = HERE.parent / "mcp"
sys.path.insert(0, str(MCP_DIR))

import server as kb_server  # noqa: E402


@pytest.fixture()
def kb_db(monkeypatch, tmp_path):
    """Fresh in-memory-equivalent DB for each test.

    We use a real file (not :memory:) so the FTS5 triggers behave the
    same as in production. The file lives in tmp_path and is cleaned up
    automatically.
    """
    db_path = tmp_path / "kb_test.db"
    monkeypatch.setattr(kb_server, "DB_PATH", str(db_path))
    # init_db reads SCHEMA_PATH at call time, so the in-tree init_db.sql
    # is the one that gets applied.
    kb_server.init_db()
    yield str(db_path)
    # tmp_path is auto-cleaned; explicit close for tidiness.

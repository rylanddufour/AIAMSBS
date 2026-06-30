"""Delete entries and verify they're gone from both kb_entries and kb_fts."""

from __future__ import annotations

import sqlite3

import pytest

import server as kb_server


def test_delete_returns_envelope_with_deleted_record(kb_db):
    entry = kb_server.kb_add(
        content="throwaway fact about delete testing",
        entry_type="fact",
        tags=["throwaway"],
    )
    result = kb_server.kb_delete(entry["id"])
    assert result["status"] == "deleted"
    assert result["entry_id"] == entry["id"]
    assert result["rows"] == 1
    assert result["deleted_record"]["id"] == entry["id"]
    assert "delete testing" in result["deleted_record"]["content"]


def test_delete_removes_row_from_kb_entries(kb_db):
    entry = kb_server.kb_add(content="x", entry_type="fact")
    kb_server.kb_delete(entry["id"])
    # Verify directly via SQL — kb_list shouldn't see it either.
    listed = kb_server.kb_list()
    assert all(e["id"] != entry["id"] for e in listed)


def test_delete_removes_row_from_kb_fts(kb_db):
    """The kb_ad trigger should remove the entry from the FTS index too."""
    entry = kb_server.kb_add(
        content="uniquedeleteterm about kubernetes",
        entry_type="runbook",
    )
    # Sanity: searchable before delete.
    pre = kb_server.kb_search("uniquedeleteterm")
    assert any(h["id"] == entry["id"] for h in pre)
    # Delete and confirm gone from FTS5.
    kb_server.kb_delete(entry["id"])
    post = kb_server.kb_search("uniquedeleteterm")
    assert not any(h["id"] == entry["id"] for h in post)
    # Direct query against kb_fts rowid to be sure.
    conn = sqlite3.connect(kb_db)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM kb_fts WHERE rowid=?", (entry["id"],))
    count = cur.fetchone()[0]
    conn.close()
    assert count == 0


def test_delete_nonexistent_entry(kb_db):
    result = kb_server.kb_delete(99999)
    assert result["error"] == "not found"
    assert result["entry_id"] == 99999


def test_delete_does_not_affect_other_entries(kb_db):
    keep = kb_server.kb_add(content="keep this fact", entry_type="fact")
    drop = kb_server.kb_add(content="drop this fact", entry_type="fact")
    kb_server.kb_delete(drop["id"])
    # The kept entry must still be searchable.
    results = kb_server.kb_search("keep")
    assert any(h["id"] == keep["id"] for h in results)
    # And the deleted one must not.
    results = kb_server.kb_search("drop")
    assert not any(h["id"] == drop["id"] for h in results)

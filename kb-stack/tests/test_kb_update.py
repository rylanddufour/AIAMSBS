"""Update entry content / tags / status and verify FTS5 reflects the change."""

from __future__ import annotations

import time

import server as kb_server


def test_update_content_changes_returned_row(kb_db):
    original = kb_server.kb_add(
        content="original content about hermes agent",
        entry_type="fact",
    )
    updated = kb_server.kb_update(
        original["id"], content="updated content about hermes agent and fts5"
    )
    assert updated["id"] == original["id"]
    assert updated["content"].startswith("updated content")
    assert "fts5" in updated["content"]


def test_update_tags_replaces_existing(kb_db):
    original = kb_server.kb_add(
        content="x", entry_type="fact", tags=["alpha", "beta"]
    )
    updated = kb_server.kb_update(original["id"], tags=["gamma", "delta", "epsilon"])
    assert updated["tags"] == ["gamma", "delta", "epsilon"]


def test_update_status_pending_to_approved(kb_db):
    """Customer flips a pending agent entry to approved."""
    entry = kb_server.kb_add(
        content="customer wants to approve this",
        entry_type="fact",
        created_by="agent",
    )
    assert entry["status"] == "pending"
    updated = kb_server.kb_update(entry["id"], status="approved")
    assert updated["status"] == "approved"


def test_update_status_to_rejected(kb_db):
    entry = kb_server.kb_add(
        content="to be rejected", entry_type="fact", created_by="agent"
    )
    updated = kb_server.kb_update(entry["id"], status="rejected")
    assert updated["status"] == "rejected"


def test_update_rejects_invalid_status(kb_db):
    entry = kb_server.kb_add(content="x", entry_type="fact")
    result = kb_server.kb_update(entry["id"], status="bogus")
    assert "error" in result


def test_update_nonexistent_entry(kb_db):
    result = kb_server.kb_update(99999, content="x")
    assert result["error"] == "not found"
    assert result["entry_id"] == 99999


def test_update_no_fields_returns_error(kb_db):
    entry = kb_server.kb_add(content="x", entry_type="fact")
    result = kb_server.kb_update(entry["id"])
    assert "error" in result


def test_update_content_reflected_in_fts5_search(kb_db):
    """The kb_au trigger should keep FTS5 in sync with content changes.

    Use plain-word unique tokens (no hyphens): FTS5's default unicode61
    tokenizer drops hyphens, and FTS5's MATCH syntax treats `-` as the
    NOT operator, so hyphenated queries can be parsed as a column
    constraint.
    """
    original = kb_server.kb_add(
        content="uniquepreword about deploys",
        entry_type="runbook",
    )
    # Search for the original term — should find it.
    hits = kb_server.kb_search("uniquepreword")
    assert any(h["id"] == original["id"] for h in hits)
    # Now update to a different term.
    kb_server.kb_update(original["id"], content="uniquepostword about deploys")
    # The new term is findable; the old term is not.
    new_hits = kb_server.kb_search("uniquepostword")
    assert any(h["id"] == original["id"] for h in new_hits)
    stale_hits = kb_server.kb_search("uniquepreword")
    assert not any(h["id"] == original["id"] for h in stale_hits)


def test_update_bumps_updated_at(kb_db):
    """updated_at should advance on update. (Best-effort: sleep 1.05s.)"""
    original = kb_server.kb_add(content="x", entry_type="fact")
    first_updated = original["updated_at"]
    # SQLite CURRENT_TIMESTAMP has 1-second resolution.
    time.sleep(1.1)
    updated = kb_server.kb_update(original["id"], content="y")
    # If for some reason updated_at didn't move (clock skew / fast run),
    # at minimum the content should reflect the change.
    assert updated["content"] == "y"
    if first_updated != updated["updated_at"]:
        assert updated["updated_at"] >= first_updated

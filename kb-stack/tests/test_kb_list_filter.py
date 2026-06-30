"""List entries with mixed status / source_type and verify filters."""

from __future__ import annotations

import pytest

import server as kb_server


def _add_mixed_fixture(kb_db):
    """Seed a small mixed-status, mixed-source dataset.

    Returns the source ids so other tests can reuse.
    """
    skill = kb_server.kb_add_source(name="aiamsbs skill", source_type="skill")
    customer_doc = kb_server.kb_add_source(
        name="customer network doc", source_type="customer_doc"
    )
    runtime = kb_server.kb_add_source(name="runtime log", source_type="runtime")

    # 3 agent entries (pending) — one per source.
    kb_server.kb_add(
        content="alpha runbook",
        entry_type="runbook",
        source_id=skill["id"],
    )
    kb_server.kb_add(
        content="alpha fact",
        entry_type="fact",
        source_id=customer_doc["id"],
    )
    kb_server.kb_add(
        content="alpha gotcha",
        entry_type="gotcha",
        source_id=runtime["id"],
    )
    # 1 customer entry (auto-approved, source_id NULL).
    kb_server.kb_add(
        content="alpha customer fact", entry_type="fact", created_by="customer"
    )
    return skill, customer_doc, runtime


def test_list_no_filters_returns_all(kb_db):
    _add_mixed_fixture(kb_db)
    all_entries = kb_server.kb_list()
    assert len(all_entries) == 4


def test_list_filter_by_status_pending(kb_db):
    _add_mixed_fixture(kb_db)
    pending = kb_server.kb_list(status="pending")
    # 3 agent entries are pending; 1 customer entry is approved.
    assert len(pending) == 3
    assert all(e["status"] == "pending" for e in pending)


def test_list_filter_by_status_approved(kb_db):
    _add_mixed_fixture(kb_db)
    approved = kb_server.kb_list(status="approved")
    assert len(approved) == 1
    assert approved[0]["status"] == "approved"
    assert approved[0]["created_by"] == "customer"


def test_list_filter_by_source_type(kb_db):
    _add_mixed_fixture(kb_db)
    skill_entries = kb_server.kb_list(source_type="skill")
    # Only one entry has a skill source.
    assert len(skill_entries) == 1
    assert "runbook" in skill_entries[0]["content"]


def test_list_combined_status_and_source_type(kb_db):
    _add_mixed_fixture(kb_db)
    pending_skills = kb_server.kb_list(source_type="skill", status="pending")
    assert len(pending_skills) == 1
    assert pending_skills[0]["entry_type"] == "runbook"


def test_list_pagination(kb_db):
    """limit + offset give proper pagination."""
    for i in range(7):
        kb_server.kb_add(content=f"entry {i:02d}", entry_type="fact")
    page1 = kb_server.kb_list(limit=3, offset=0)
    page2 = kb_server.kb_list(limit=3, offset=3)
    page3 = kb_server.kb_list(limit=3, offset=6)
    assert len(page1) == 3
    assert len(page2) == 3
    assert len(page3) == 1
    # No overlap between pages.
    page1_ids = {e["id"] for e in page1}
    page2_ids = {e["id"] for e in page2}
    page3_ids = {e["id"] for e in page3}
    assert page1_ids.isdisjoint(page2_ids)
    assert page2_ids.isdisjoint(page3_ids)
    assert page1_ids.isdisjoint(page3_ids)


def test_list_rejects_invalid_status(kb_db):
    result = kb_server.kb_list(status="bogus")
    assert isinstance(result, list)
    assert "error" in result[0]


def test_list_rejects_invalid_source_type(kb_db):
    result = kb_server.kb_list(source_type="bogus")
    assert isinstance(result, list)
    assert "error" in result[0]


def test_list_excludes_sourceless_entries_when_filtering_source_type(kb_db):
    """INNER JOIN excludes entries with source_id NULL when filtering."""
    skill = kb_server.kb_add_source(name="x", source_type="skill")
    kb_server.kb_add(content="from skill", entry_type="fact", source_id=skill["id"])
    kb_server.kb_add(content="sourceless fact", entry_type="fact", created_by="customer")
    results = kb_server.kb_list(source_type="skill")
    contents = {r["content"] for r in results}
    # Only the skill-sourced entry is included.
    assert "from skill" in contents
    assert "sourceless fact" not in contents


def test_list_includes_sourceless_entries_when_no_source_filter(kb_db):
    """No source_type filter means sourceless entries are included too."""
    skill = kb_server.kb_add_source(name="x", source_type="skill")
    kb_server.kb_add(content="from skill", entry_type="fact", source_id=skill["id"])
    kb_server.kb_add(content="sourceless fact", entry_type="fact", created_by="customer")
    results = kb_server.kb_list()
    contents = {r["content"] for r in results}
    assert "from skill" in contents
    assert "sourceless fact" in contents

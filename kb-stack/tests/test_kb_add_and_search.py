"""Add entries of different types, then FTS5 search and verify BM25 ranking."""

from __future__ import annotations

import pytest

import server as kb_server


def test_add_creates_pending_status_for_agent(kb_db):
    """Agent-written entries default to status='pending' (Level 0 trust)."""
    result = kb_server.kb_add(
        content="Grafana 13 + Loki timeseries bug: use [1m] instead of [$__interval].",
        entry_type="gotcha",
        tags=["grafana", "loki"],
        created_by="agent",
    )
    assert result["status"] == "pending"
    assert result["trust_level_at_creation"] == 0
    assert result["created_by"] == "agent"
    assert result["tags"] == ["grafana", "loki"]
    assert result["entry_type"] == "gotcha"
    assert "id" in result


def test_add_creates_approved_status_for_customer(kb_db):
    """Customer-written entries are auto-approved (Level 3 trust)."""
    result = kb_server.kb_add(
        content="Our network range is 192.168.0.0/16.",
        entry_type="fact",
        created_by="customer",
    )
    assert result["status"] == "approved"
    assert result["trust_level_at_creation"] == 3


def test_add_rejects_invalid_entry_type(kb_db):
    result = kb_server.kb_add(content="x", entry_type="bogus")
    assert "error" in result
    assert "entry_type" in result["error"]


def test_add_rejects_invalid_created_by(kb_db):
    result = kb_server.kb_add(content="x", entry_type="fact", created_by="alien")
    assert "error" in result


def test_search_finds_matching_entry(kb_db):
    kb_server.kb_add(
        content="Promtail syslog only accepts TCP, not UDP. Use port 1514.",
        entry_type="gotcha",
        tags=["loki", "promtail"],
    )
    kb_server.kb_add(
        content="Grafana 13 dashboard import from grafana.com #6287.",
        entry_type="fact",
        tags=["grafana"],
    )
    results = kb_server.kb_search("promtail syslog")
    assert len(results) >= 1
    # The promtail entry should be the top hit (it contains both terms).
    assert "promtail" in results[0]["content"].lower()


def test_search_ranks_more_relevant_entry_higher(kb_db):
    """The entry that matches more query terms should rank first (lower BM25)."""
    # This entry contains all three terms.
    kb_server.kb_add(
        content="Grafana Loki queries: use bar gauge or logs panel, not timeseries.",
        entry_type="gotcha",
    )
    # This entry only contains one.
    kb_server.kb_add(
        content="Docker compose restarts policies: unless-stopped.",
        entry_type="fact",
    )
    results = kb_server.kb_search("grafana loki queries", limit=5)
    assert len(results) >= 1
    # The grafana-loki entry must be in the result set and rank first.
    top = results[0]
    assert "grafana" in top["content"].lower()
    assert "loki" in top["content"].lower()
    # BM25 returns lower-is-better; "rank" should be a float.
    assert "rank" in top
    assert isinstance(top["rank"], (int, float))


def test_search_respects_limit(kb_db):
    for i in range(5):
        kb_server.kb_add(
            content=f"Common runbook step {i} for kubernetes deploys.",
            entry_type="runbook",
        )
    results = kb_server.kb_search("kubernetes", limit=3)
    assert len(results) == 3


def test_search_with_source_type_filter(kb_db):
    """source_types filter restricts to entries from matching sources."""
    # Create a skill source and a runtime source.
    skill_src = kb_server.kb_add_source(
        name="AIAMSBS skill", source_type="skill"
    )
    runtime_src = kb_server.kb_add_source(
        name="Runtime observation", source_type="runtime"
    )
    kb_server.kb_add(
        content="skill-authored runbook about hermes agent",
        entry_type="runbook",
        source_id=skill_src["id"],
    )
    kb_server.kb_add(
        content="runtime observation about hermes agent memory",
        entry_type="fact",
        source_id=runtime_src["id"],
    )
    # Filter to runtime only — the skill entry should be excluded.
    results = kb_server.kb_search("hermes", source_types=["runtime"])
    assert all("runtime" in r["content"].lower() for r in results)
    # And the skill entry should NOT be in the result set.
    assert not any("skill-authored" in r["content"] for r in results)

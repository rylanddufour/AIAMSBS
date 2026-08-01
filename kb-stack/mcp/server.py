"""AIAMSBS Knowledge Base MCP server (K1, BACKLOG #30).

Exposes a SQLite+FTS5 backed knowledge base over the MCP streamable-http
transport. Five required tools (kb_search, kb_add, kb_update, kb_list,
kb_delete) plus two convenience source-management tools (kb_add_source,
kb_list_sources).

Also serves a bare HTML viewer at `/` and `/ui/` (BACKLOG #57) using
`@mcp.custom_route()` — a tiny single-file SPA that calls the same
tool functions via `/api/kb/list`, `/api/kb/entries/{id}` (GET + PATCH).
No direct DB access from the UI; the existing MCP tool layer is the
sole data path. The Svelte + ByteMD upgrade is a separate row (BACKLOG #55).

MVP search strategy: FTS5 BM25 ranking only. No embeddings, no model
calls, no network. Design justification in
`obsidian_vaults/agent vault/AIAMSBS_Docs_Diagrams/kb_workflow.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

DB_PATH = os.environ.get("KB_DB_PATH", "/data/kb.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "init_db.sql")

VALID_ENTRY_TYPES = ("runbook", "fact", "gotcha")
VALID_STATUSES = ("pending", "approved", "rejected")
VALID_CREATED_BY = ("agent", "customer")
VALID_SOURCE_TYPES = ("skill", "customer_doc", "runtime")

mcp = FastMCP("kb")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Load schema from init_db.sql and apply it to the database.

    Migrations (idempotent — safe to run on every startup):
      1. Add `title` column to kb_entries if missing (BACKLOG #57 follow-up).
         Backfill existing rows with substr(content, 1, 80); customer can
         edit titles later via the UI or kb_update.
      2. Rebuild the kb_fts FTS5 virtual table to include the `title`
         column. SQLAlchemy-style migrations are overkill for this scope;
         we detect the old FTS shape (no `title` column) and rebuild.
    """
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with open(SCHEMA_PATH, "r") as f:
        schema_sql = f.read()
    conn = _connect()
    conn.executescript(schema_sql)

    # ---- Migration 1: ensure kb_entries.title exists and is populated ----
    cols = [row[1] for row in conn.execute(
        "PRAGMA table_info(kb_entries)"
    ).fetchall()]
    if "title" not in cols:
        # Existing DB predates the title column. Add it NOT NULL with a
        # default, then backfill from the first line of content. The
        # CHECK constraint is added AFTER backfill so the NOT NULL
        # default doesn't reject the ALTER TABLE on the existing rows.
        conn.executescript("""
            ALTER TABLE kb_entries ADD COLUMN title TEXT NOT NULL DEFAULT '';
            UPDATE kb_entries
            SET title = CASE
                WHEN instr(content, char(10)) > 0
                THEN rtrim(substr(content, 1, instr(content, char(10)) - 1))
                ELSE substr(content, 1, 80)
            END
            WHERE title = '' OR title IS NULL;
        """)

    # ---- Migration 2: ensure kb_fts includes the title column ----
    fts_cols = [row[1] for row in conn.execute(
        "PRAGMA table_info(kb_fts)"
    ).fetchall()]
    if "title" not in fts_cols:
        # Old FTS5 table doesn't have title. Drop and rebuild; repopulate
        # from current kb_entries. The triggers (CREATE TRIGGER IF NOT
        # EXISTS) are unchanged in init_db.sql, so they still apply.
        conn.executescript("""
            DROP TABLE kb_fts;
            CREATE VIRTUAL TABLE kb_fts USING fts5(
                title, content, tags,
                content='kb_entries',
                content_rowid='id'
            );
            INSERT INTO kb_fts(rowid, title, content, tags)
            SELECT id, title, content, tags FROM kb_entries;
        """)

    # ---- Migration 3: re-sync FTS rows that pre-date the new triggers ----
    # The CREATE TRIGGER IF NOT EXISTS in init_db.sql skipped the
    # new (title-aware) triggers when the old ones existed. New entries
    # inserted between the FTS rebuild and the trigger fix won't have
    # their title in kb_fts. Upsert them now. Idempotent: the INSERT
    # OR REPLACE updates existing rows.
    if "title" in fts_cols or "title" in [row[1] for row in conn.execute(
        "PRAGMA table_info(kb_entries)"
    ).fetchall()]:
        conn.executescript("""
            INSERT OR REPLACE INTO kb_fts(rowid, title, content, tags)
            SELECT id, title, content, tags FROM kb_entries;
        """)

    conn.commit()
    conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # tags is stored as a JSON array string. Surface it as a list so callers
    # don't have to re-parse on the wire. If it's NULL or invalid JSON,
    # fall back to the raw value (or None) rather than throwing.
    if "tags" in d and d["tags"] is not None:
        try:
            d["tags"] = json.loads(d["tags"])
        except (json.JSONDecodeError, TypeError):
            # Leave as string — caller can see the bad data.
            pass
    return d


@mcp.tool()
def kb_search(
    query: str, limit: int = 10, source_types: list[str] | None = None
) -> list[dict]:
    """FTS5 search across kb_entries. Returns matching entries ranked by BM25.

    Args:
        query: free-text search. FTS5 tokenizes the query, so multi-word
            queries find entries that contain any of the terms; quote a
            phrase for exact matching. The snippet column is generated by
            FTS5 itself (highlighted with \u001e markers).
        limit: max results (default 10).
        source_types: optional filter; if given, restrict to entries whose
            source has one of these source_type values. Uses LEFT JOIN, so
            entries with no source (source_id NULL) are always included
            unless you also pass an explicit list.
    """
    conn = _connect()
    cur = conn.cursor()

    if source_types:
        # Validate against the schema's CHECK constraint so we don't return
        # 500-shaped errors from SQLite on a bad type.
        for st in source_types:
            if st not in VALID_SOURCE_TYPES:
                conn.close()
                return [{"error": f"invalid source_type: {st}"}]
        placeholders = ",".join("?" * len(source_types))
        # INNER JOIN: when caller filters by source_type they only want
        # entries that came from a source of that type. Sourceless
        # entries (source_id NULL) are excluded.
        sql = f"""
            SELECT e.*, snippet(kb_fts, 0, '[', ']', '...', 8) AS snippet,
                   bm25(kb_fts) AS rank
            FROM kb_fts
            JOIN kb_entries e ON e.id = kb_fts.rowid
            JOIN kb_sources s ON s.id = e.source_id
            WHERE kb_fts MATCH ?
              AND s.source_type IN ({placeholders})
            ORDER BY rank
            LIMIT ?
        """
        params: list = [query, *source_types, limit]
    else:
        sql = """
            SELECT e.*, snippet(kb_fts, 0, '[', ']', '...', 8) AS snippet,
                   bm25(kb_fts) AS rank
            FROM kb_fts
            JOIN kb_entries e ON e.id = kb_fts.rowid
            WHERE kb_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        params = [query, limit]

    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


@mcp.tool()
def kb_add(
    title: str,
    content: str,
    entry_type: str,
    tags: list[str] | None = None,
    source_id: int | None = None,
    created_by: str = "agent",
) -> dict:
    """Add a KB entry. Returns the new entry id and current state.

    For MVP, all agent-written entries are created with status='pending'
    (Level 0 trust). Customer-written entries are created with
    status='approved' (Level 3 trust — they wrote it, they own it).

    Args:
        title: REQUIRED. Short human-readable title for the entry
            (enforced by schema CHECK constraint + this function's
            validation). Agents and customers must both provide one.
        content: the runbook/fact/gotcha text.
        entry_type: one of 'runbook', 'fact', 'gotcha'.
        tags: optional list of tag strings; stored as a JSON array.
        source_id: optional FK to kb_sources.id.
        created_by: 'agent' (default) or 'customer'.
    """
    if not isinstance(title, str) or not title.strip():
        return {"error": "title is required and must be a non-empty string"}
    title = title.strip()
    if entry_type not in VALID_ENTRY_TYPES:
        return {"error": f"entry_type must be one of {VALID_ENTRY_TYPES}"}
    if created_by not in VALID_CREATED_BY:
        return {"error": f"created_by must be one of {VALID_CREATED_BY}"}

    # Customer-written entries are auto-approved; agents always start
    # at pending.
    initial_status = "approved" if created_by == "customer" else "pending"
    # Mirror the trust ladder: customer=3, agent=0. K6 can add intermediate
    # levels (e.g., 'approved_agent') later without breaking the schema.
    initial_trust = 3 if created_by == "customer" else 0

    tags_json = json.dumps(tags) if tags else None

    conn = _connect()
    cur = conn.cursor()
    if source_id is not None:
        cur.execute(
            """
            INSERT INTO kb_entries
                (source_id, entry_type, title, content, tags, created_by, status, trust_level_at_creation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, entry_type, title, content, tags_json, created_by, initial_status, initial_trust),
        )
    else:
        cur.execute(
            """
            INSERT INTO kb_entries
                (entry_type, title, content, tags, created_by, status, trust_level_at_creation)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_type, title, content, tags_json, created_by, initial_status, initial_trust),
        )
    new_id = cur.lastrowid
    conn.commit()
    cur.execute("SELECT * FROM kb_entries WHERE id=?", (new_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


@mcp.tool()
def kb_update(
    entry_id: int,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    status: str | None = None,
) -> dict:
    """Update an existing KB entry.

    Args:
        entry_id: required. The id of the entry to update.
        title: new title (if changing). Must be non-empty when supplied;
            the schema CHECK constraint enforces non-empty at the DB level.
        content: new content (if changing).
        tags: new tags list (replaces existing).
        status: new status. Customer flips pending -> approved/rejected.

    Returns the updated row, or {'error': 'not found'} if entry_id is
    unknown, or {'error': 'no fields to update'} if nothing was passed.
    """
    if status is not None and status not in VALID_STATUSES:
        return {"error": f"status must be one of {VALID_STATUSES}"}
    if title is not None and (not isinstance(title, str) or not title.strip()):
        return {"error": "title must be a non-empty string"}

    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM kb_entries WHERE id=?", (entry_id,))
    if cur.fetchone() is None:
        conn.close()
        return {"error": "not found", "entry_id": entry_id}

    updates: dict = {}
    if title is not None:
        updates["title"] = title.strip()
    if content is not None:
        updates["content"] = content
    if tags is not None:
        updates["tags"] = json.dumps(tags)
    if status is not None:
        updates["status"] = status

    if not updates:
        conn.close()
        return {"error": "no fields to update"}

    updates["updated_at"] = "CURRENT_TIMESTAMP"
    set_clause = ", ".join(f"{k}=?" for k in updates.keys())
    values = list(updates.values()) + [entry_id]
    cur.execute(
        f"UPDATE kb_entries SET {set_clause} WHERE id=?",
        values,
    )
    conn.commit()
    cur.execute("SELECT * FROM kb_entries WHERE id=?", (entry_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


@mcp.tool()
def kb_list(
    source_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List KB entries, optionally filtered. For the review queue UI.

    Args:
        source_type: optional filter — restrict to entries whose source has
            this source_type. Entries with no source (source_id NULL) are
            always included.
        status: optional filter — restrict to this status.
        limit: max rows (default 50).
        offset: for pagination.
    """
    if source_type is not None and source_type not in VALID_SOURCE_TYPES:
        return [{"error": f"invalid source_type: {source_type}"}]
    if status is not None and status not in VALID_STATUSES:
        return [{"error": f"invalid status: {status}"}]

    conn = _connect()
    cur = conn.cursor()
    # When source_type is set, INNER JOIN so we only return entries that
    # came from a matching source. When source_type is NOT set, LEFT JOIN
    # so sourceless entries (source_id NULL) are included in the listing.
    if source_type is not None:
        sql = """
            SELECT e.*
            FROM kb_entries e
            JOIN kb_sources s ON s.id = e.source_id
            WHERE 1=1
        """
    else:
        sql = """
            SELECT e.*
            FROM kb_entries e
            LEFT JOIN kb_sources s ON s.id = e.source_id
            WHERE 1=1
        """
    params: list = []
    if source_type is not None:
        sql += " AND s.source_type = ?"
        params.append(source_type)
    if status is not None:
        sql += " AND e.status = ?"
        params.append(status)
    sql += " ORDER BY e.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


@mcp.tool()
def kb_delete(entry_id: int) -> dict:
    """Delete a KB entry. Returns the deleted entry contents.

    DESTRUCTIVE — the row is permanently removed (and the FTS index
    is updated via the kb_ad trigger). Callers should always confirm
    with the user before invoking this.
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM kb_entries WHERE id=?", (entry_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return {"error": "not found", "entry_id": entry_id}
    deleted = _row_to_dict(row)
    cur.execute("DELETE FROM kb_entries WHERE id=?", (entry_id,))
    conn.commit()
    rows_affected = cur.rowcount
    conn.close()
    return {
        "status": "deleted",
        "entry_id": entry_id,
        "rows": rows_affected,
        "deleted_record": deleted,
    }


# ---------------------------------------------------------------------------
# Optional convenience tools: source management.
# Useful for K2 (bootstrap ingestion) and K3 (review queue UI).
# ---------------------------------------------------------------------------


@mcp.tool()
def kb_add_source(
    name: str, source_type: str, file_path_or_url: str | None = None
) -> dict:
    """Add a KB source (where knowledge chunks came from).

    Args:
        name: human-readable name (e.g., "OpenWrt firewall runbook").
        source_type: one of 'skill', 'customer_doc', 'runtime'.
        file_path_or_url: optional path or URL for traceability.
    """
    if source_type not in VALID_SOURCE_TYPES:
        return {"error": f"source_type must be one of {VALID_SOURCE_TYPES}"}
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO kb_sources (name, source_type, file_path_or_url) VALUES (?, ?, ?)",
        (name, source_type, file_path_or_url),
    )
    new_id = cur.lastrowid
    conn.commit()
    cur.execute("SELECT * FROM kb_sources WHERE id=?", (new_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row)


@mcp.tool()
def kb_list_sources() -> list[dict]:
    """List all KB sources, newest first."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM kb_sources ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ----------------------------------------------------------------------------
# Bare HTML viewer (BACKLOG #57) — restored because the original /ui/
# endpoint was lost in a kb-mcp rebase. Tiny single-file SPA; the Svelte +
# ByteMD upgrade is a separate row (BACKLOG #55).
# ----------------------------------------------------------------------------

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AIAMSBS KB Viewer</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 900px;
         margin: 2em auto; padding: 0 1em; color: #222; }
  h1 { font-size: 1.4em; }
  h2 { font-size: 1.15em; margin-top: 1em; }
  .entry { padding: 0.6em 0; border-bottom: 1px solid #eee; }
  .entry a { color: #06c; text-decoration: none; }
  .entry a:hover { text-decoration: underline; }
  .entry .title { font-weight: bold; }
  .entry .snippet { color: #666; font-size: 0.85em; margin-top: 2px; }
  .badge { display: inline-block; padding: 1px 6px; font-size: 0.8em;
           border-radius: 3px; background: #eee; margin-left: 0.4em; }
  .badge.pending { background: #ffd; }
  .badge.approved { background: #dfd; }
  .badge.rejected { background: #fdd; }
  #detail, #addForm, #searchResults { margin-top: 1.5em; padding: 1em;
                                       background: #f8f8f8; border-radius: 4px; }
  #searchResults { padding: 0.5em 1em; }
  #searchResults .entry { padding: 0.4em 0; border-bottom: 1px solid #e0e0e0; }
  #searchResults .entry:last-child { border-bottom: none; }
  pre { white-space: pre-wrap; word-wrap: break-word; }
  textarea { width: 100%; min-height: 8em; font-family: inherit; box-sizing: border-box; }
  input[type=text] { width: 100%; padding: 0.4em; box-sizing: border-box; }
  select { padding: 0.3em; }
  button { padding: 0.5em 1em; margin-right: 0.5em; cursor: pointer; }
  button.danger { background: #fee; border: 1px solid #c00; color: #c00; }
  button.primary { background: #06c; border: 1px solid #06c; color: #fff; }
  .msg { color: #080; font-weight: bold; }
  .err { color: #c00; font-weight: bold; }
  .topbar { display: flex; align-items: center; gap: 1em; margin-bottom: 1em; flex-wrap: wrap; }
  .topbar button { margin-right: 0; }
  .searchwrap { flex: 1; display: flex; gap: 0.5em; align-items: center; }
  .searchwrap input { flex: 1; }
  .searchwrap .clear { display: none; }
  .searchwrap.hasq .clear { display: inline-block; }
  .field-label { font-weight: bold; display: block; margin-top: 0.6em; }
  .field-label .req { color: #c00; }
</style>
</head>
<body>
<h1>AIAMSBS KB Viewer</h1>

<div class="topbar">
  <a href="#" id="back">&larr; Back to list</a>
  <span class="searchwrap" id="searchWrap">
    <input type="text" id="searchInput" placeholder="Search title, content, tags… (empty = all entries)">
    <button class="clear" id="clearBtn" title="Clear search">×</button>
  </span>
  <button class="primary" id="addBtn">+ Add new entry</button>
</div>

<div id="searchResults" style="display:none;"></div>
<div id="list"></div>
<div id="addForm" style="display:none;">
  <h2>New KB entry</h2>
  <p>
    <label class="field-label" for="addTitle">Title <span class="req">*</span></label>
    <input type="text" id="addTitle" placeholder="A short, descriptive title (required)">
  </p>
  <p>
    <label><strong>Entry type:</strong></label><br>
    <select id="addType">
      <option value="runbook">runbook</option>
      <option value="fact" selected>fact</option>
      <option value="gotcha">gotcha</option>
    </select>
  </p>
  <p>
    <label class="field-label" for="addContent">Content <span class="req">*</span></label>
    <textarea id="addContent" placeholder="The runbook / fact / gotcha text..."></textarea>
  </p>
  <p>
    <label class="field-label" for="addTags">Tags <span style="font-weight:normal;color:#666">(comma-separated, optional)</span></label>
    <input type="text" id="addTags" placeholder="e.g. onboarding, phase-a, network">
  </p>
  <p>
    <label><strong>Created by:</strong></label>
    <select id="addCreatedBy">
      <option value="agent">agent</option>
      <option value="customer" selected>customer</option>
    </select>
  </p>
  <p>
    <button class="primary" id="addSubmit">Create</button>
    <button id="addCancel">Cancel</button>
    <span id="addStatus"></span>
  </p>
</div>
<div id="detail" style="display:none;"></div>

<script>
const STATUS_BADGE = {pending:'pending', approved:'approved', rejected:'rejected'};

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  let body;
  try { body = await r.json(); } catch { body = {}; }
  if (!r.ok || body.error) {
    throw new Error(body.error || ('HTTP ' + r.status));
  }
  return body;
}

function stripSnippet(s) {
  // FTS5 snippet markers are \u001e; strip them for clean display.
  return (s || '').replace(/\u001e/g, '');
}

function renderEntry(e, opts) {
  opts = opts || {};
  const status = STATUS_BADGE[e.status] || '';
  const type = e.entry_type || '';
  const title = e.title || '(no title)';
  const snippet = opts.snippet ? `<div class="snippet">${escape(stripSnippet(opts.snippet))}</div>` : '';
  return `<div class="entry">
    <a href="#id=${e.id}"><span class="title">${e.id}. ${escape(title)}</span></a>
    <span class="badge ${status}">${status}</span>
    <span class="badge">${type}</span>
    ${snippet}
  </div>`;
}

let currentEntry = null;
let currentQuery = '';
let searchDebounce = null;

async function loadList() {
  const el = document.getElementById('list');
  const res = document.getElementById('searchResults');
  res.style.display = 'none';
  res.innerHTML = '';
  el.innerHTML = 'Loading…';
  document.getElementById('detail').style.display = 'none';
  hideAddForm();
  try {
    const {data} = await fetchJSON('/api/kb/list');
    if (!data || data.length === 0) {
      el.innerHTML = '<p>No KB entries yet.</p>';
      return;
    }
    el.innerHTML = data.map(e => renderEntry(e)).join('');
    if (location.hash.startsWith('#id=')) {
      const id = parseInt(location.hash.slice(4), 10);
      if (!Number.isNaN(id)) await loadDetail(id);
    }
  } catch (err) {
    el.innerHTML = `<p class="err">Error loading entries: ${escape(err.message)}</p>`;
  }
}

async function runSearch(q) {
  currentQuery = q;
  const el = document.getElementById('list');
  const res = document.getElementById('searchResults');
  el.innerHTML = '';
  document.getElementById('detail').style.display = 'none';
  hideAddForm();
  if (!q) {
    res.style.display = 'none';
    res.innerHTML = '';
    loadList();
    return;
  }
  res.style.display = 'block';
  res.innerHTML = 'Searching…';
  try {
    const {data, count} = await fetchJSON('/api/kb/search?q=' + encodeURIComponent(q) + '&limit=50');
    if (count === 0) {
      res.innerHTML = `<p>No matches for &ldquo;${escape(q)}&rdquo;.</p>`;
      return;
    }
    res.innerHTML = `<p style="margin:0 0 0.5em;color:#666">${count} match${count === 1 ? '' : 'es'} for &ldquo;${escape(q)}&rdquo;:</p>` + data.map(e => renderEntry(e, {snippet: e.snippet})).join('');
  } catch (err) {
    res.innerHTML = `<p class="err">Search failed: ${escape(err.message)}</p>`;
  }
}

async function loadDetail(id) {
  document.getElementById('list').style.display = 'none';
  document.getElementById('searchResults').style.display = 'none';
  hideAddForm();
  const det = document.getElementById('detail');
  det.style.display = 'block';
  det.innerHTML = 'Loading…';
  try {
    const {data} = await fetchJSON('/api/kb/entries/' + id);
    currentEntry = data;
    det.innerHTML = `
      <h2>${escape(data.title || '(no title)')}</h2>
      <p style="color:#666">#${data.id}</p>
      <p>
        <span class="badge">${data.entry_type || ''}</span>
        <span class="badge ${data.status}">${data.status}</span>
        ${data.tags && data.tags.length ? '<span class="badge">tags: ' + escape(JSON.stringify(data.tags)) + '</span>' : ''}
      </p>
      <label class="field-label" for="title">Title <span class="req">*</span></label>
      <input type="text" id="title" value="${escape(data.title || '')}">
      <label class="field-label" for="content">Content <span class="req">*</span></label>
      <textarea id="content">${escape(data.content || '')}</textarea>
      <p style="margin-top:1em">
        <button class="primary" id="save">Save</button>
        <button id="approve">Approve (pending &rarr; approved)</button>
        <button id="reject">Reject (pending &rarr; rejected)</button>
        <button class="danger" id="delete">Delete</button>
      </p>
      <p id="status"></p>
      <p style="font-size:0.8em;color:#666">
        created_by: ${escape(data.created_by || '')} ·
        updated_at: ${escape(data.updated_at || '')}
      </p>`;
    document.getElementById('save').onclick = () => saveEntry(data.id);
    document.getElementById('approve').onclick = () => saveEntry(data.id, {status: 'approved'});
    document.getElementById('reject').onclick = () => saveEntry(data.id, {status: 'rejected'});
    document.getElementById('delete').onclick = deleteCurrent;
  } catch (err) {
    det.innerHTML = `<p class="err">Error loading entry: ${escape(err.message)}</p>`;
  }
}

async function saveEntry(id, extra) {
  extra = extra || {};
  const statusEl = document.getElementById('status');
  const title = document.getElementById('title').value.trim();
  const content = document.getElementById('content').value;
  if (!title) {
    statusEl.innerHTML = '<span class="err">Title is required.</span>';
    return;
  }
  const patch = Object.assign({title: title, content: content}, extra);
  statusEl.textContent = 'Saving…';
  try {
    await fetchJSON('/api/kb/entries/' + id, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(patch),
    });
    statusEl.innerHTML = '<span class="msg">Saved.</span>';
    setTimeout(() => {
      if (currentQuery) runSearch(currentQuery);
      else loadList();
    }, 500);
  } catch (err) {
    statusEl.innerHTML = '<span class="err">Save failed: ' + escape(err.message) + '</span>';
  }
}

async function deleteCurrent() {
  if (!currentEntry) return;
  const id = currentEntry.id;
  const label = currentEntry.title || ('entry #' + id);
  if (!confirm('Delete ' + label + '? This cannot be undone.')) return;
  try {
    await fetchJSON('/api/kb/entries/' + id, {method: 'DELETE'});
    history.pushState({}, '', location.pathname);
    currentEntry = null;
    if (currentQuery) runSearch(currentQuery);
    else loadList();
  } catch (err) {
    alert('Delete failed: ' + err.message);
  }
}

function showAddForm() {
  document.getElementById('list').style.display = 'none';
  document.getElementById('detail').style.display = 'none';
  document.getElementById('searchResults').style.display = 'none';
  document.getElementById('addForm').style.display = 'block';
  document.getElementById('addTitle').focus();
}

function hideAddForm() {
  const f = document.getElementById('addForm');
  if (f) f.style.display = 'none';
  const statusEl = document.getElementById('addStatus');
  if (statusEl) statusEl.textContent = '';
}

document.getElementById('addBtn').onclick = showAddForm;

document.getElementById('addCancel').onclick = () => {
  document.getElementById('addTitle').value = '';
  document.getElementById('addContent').value = '';
  document.getElementById('addTags').value = '';
  hideAddForm();
  if (currentQuery) runSearch(currentQuery);
  else loadList();
};

document.getElementById('addSubmit').onclick = async () => {
  const statusEl = document.getElementById('addStatus');
  const title = document.getElementById('addTitle').value.trim();
  const content = document.getElementById('addContent').value.trim();
  if (!title) {
    statusEl.innerHTML = '<span class="err">Title is required.</span>';
    return;
  }
  if (!content) {
    statusEl.innerHTML = '<span class="err">Content is required.</span>';
    return;
  }
  const tagsRaw = document.getElementById('addTags').value.trim();
  const tags = tagsRaw ? tagsRaw.split(',').map(t => t.trim()).filter(t => t.length > 0) : null;
  statusEl.textContent = 'Creating…';
  try {
    await fetchJSON('/api/kb/entries', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: title,
        content: content,
        entry_type: document.getElementById('addType').value,
        tags: tags,
        created_by: document.getElementById('addCreatedBy').value,
      }),
    });
    statusEl.innerHTML = '<span class="msg">Created.</span>';
    document.getElementById('addTitle').value = '';
    document.getElementById('addContent').value = '';
    document.getElementById('addTags').value = '';
    setTimeout(() => {
      hideAddForm();
      if (currentQuery) runSearch(currentQuery);
      else loadList();
    }, 600);
  } catch (err) {
    statusEl.innerHTML = '<span class="err">Create failed: ' + escape(err.message) + '</span>';
  }
};

function escape(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

// Search wiring
const searchInput = document.getElementById('searchInput');
const searchWrap = document.getElementById('searchWrap');
document.getElementById('clearBtn').onclick = () => {
  searchInput.value = '';
  searchWrap.classList.remove('hasq');
  runSearch('');
};
searchInput.addEventListener('input', () => {
  const q = searchInput.value.trim();
  searchWrap.classList.toggle('hasq', q.length > 0);
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => runSearch(q), 200);
});

document.getElementById('back').onclick = (e) => {
  e.preventDefault();
  history.pushState({}, '', location.pathname);
  document.getElementById('list').style.display = 'block';
  document.getElementById('detail').style.display = 'none';
  document.getElementById('searchResults').style.display = 'none';
  hideAddForm();
};
window.addEventListener('hashchange', () => {
  if (location.hash.startsWith('#id=')) {
    const id = parseInt(location.hash.slice(4), 10);
    if (!Number.isNaN(id)) loadDetail(id);
  } else {
    document.getElementById('list').style.display = 'block';
    document.getElementById('detail').style.display = 'none';
    hideAddForm();
    currentEntry = null;
  }
});

loadList();
</script>
</body>
</html>"""


@mcp.custom_route("/", methods=["GET"])
async def serve_root(request: Request) -> HTMLResponse:
    """Root redirect-equivalent: serve the KB viewer HTML."""
    return HTMLResponse(INDEX_HTML)


@mcp.custom_route("/ui", methods=["GET"])
async def serve_ui_short(request: Request) -> HTMLResponse:
    """Bare KB viewer (BACKLOG #57). Same HTML as /."""
    return HTMLResponse(INDEX_HTML)


@mcp.custom_route("/ui/", methods=["GET"])
async def serve_ui_slash(request: Request) -> HTMLResponse:
    """Trailing-slash alias for /ui (some clients/proxies double-slash)."""
    return HTMLResponse(INDEX_HTML)


@mcp.custom_route("/api/kb/list", methods=["GET"])
async def api_kb_list(request: Request) -> JSONResponse:
    """JSON wrapper around the kb_list MCP tool. No direct DB access."""
    try:
        # kb_list is a regular Python function (the @mcp.tool() decorator
        # only registers it with FastMCP — it remains callable directly).
        entries = kb_list()
        if entries and isinstance(entries[0], dict) and "error" in entries[0]:
            return JSONResponse({"error": entries[0]["error"]}, status_code=400)
        return JSONResponse({"data": entries, "count": len(entries)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/kb/entries/{entry_id:int}", methods=["GET"])
async def api_kb_get(request: Request) -> JSONResponse:
    """JSON wrapper around a direct SELECT for one entry.

    Note: there is no kb_get MCP tool — this endpoint uses the same DB
    layer (read-only, no joins) that kb_list uses. UI does not need to
    cross the MCP HTTP transport for read paths.
    """
    entry_id = request.path_params["entry_id"]
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM kb_entries WHERE id=?", (entry_id,))
        row = cur.fetchone()
        conn.close()
        if row is None:
            return JSONResponse({"error": "not found", "entry_id": entry_id},
                                status_code=404)
        return JSONResponse({"data": _row_to_dict(row)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/kb/entries/{entry_id:int}", methods=["PATCH"])
async def api_kb_update(request: Request) -> JSONResponse:
    """JSON wrapper around the kb_update MCP tool. No direct DB access.

    Body JSON keys mirror kb_update kwargs: title, content, tags, status.
    All fields optional; at least one must be supplied.
    """
    entry_id = request.path_params["entry_id"]
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a JSON object"},
                            status_code=400)
    allowed = {"title", "content", "tags", "status"}
    unknown = set(body) - allowed
    if unknown:
        return JSONResponse(
            {"error": f"unknown fields: {sorted(unknown)}; allowed: {sorted(allowed)}"},
            status_code=400,
        )
    if not body:
        return JSONResponse(
            {"error": "no fields to update; supply at least one of: title, content, tags, status"},
            status_code=400,
        )
    try:
        result = kb_update(entry_id=entry_id, **body)
        if isinstance(result, dict) and "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse({"data": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/kb/entries", methods=["POST"])
async def api_kb_create(request: Request) -> JSONResponse:
    """JSON wrapper around the kb_add MCP tool. No direct DB access.

    Body JSON keys mirror kb_add kwargs:
      title         (required, non-empty string)
      content       (required, non-empty string)
      entry_type    (required; one of 'runbook'|'fact'|'gotcha')
      tags          (optional list of strings)
      source_id     (optional int)
      created_by    (optional; one of 'agent'|'customer'; default 'agent')
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a JSON object"},
                            status_code=400)

    allowed = {"title", "content", "entry_type", "tags", "source_id", "created_by"}
    unknown = set(body) - allowed
    if unknown:
        return JSONResponse(
            {"error": f"unknown fields: {sorted(unknown)}; allowed: {sorted(allowed)}"},
            status_code=400,
        )

    title = body.get("title")
    if not isinstance(title, str) or not title.strip():
        return JSONResponse(
            {"error": "title is required and must be a non-empty string"},
            status_code=400,
        )

    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        return JSONResponse(
            {"error": "content is required and must be a non-empty string"},
            status_code=400,
        )

    entry_type = body.get("entry_type")
    if entry_type not in VALID_ENTRY_TYPES:
        return JSONResponse(
            {"error": f"entry_type must be one of {list(VALID_ENTRY_TYPES)}"},
            status_code=400,
        )

    tags = body.get("tags")
    if tags is not None and not (isinstance(tags, list) and all(isinstance(t, str) for t in tags)):
        return JSONResponse(
            {"error": "tags must be a list of strings if provided"},
            status_code=400,
        )

    source_id = body.get("source_id")
    if source_id is not None and not isinstance(source_id, int):
        return JSONResponse(
            {"error": "source_id must be an integer if provided"},
            status_code=400,
        )

    created_by = body.get("created_by", "agent")
    if created_by not in VALID_CREATED_BY:
        return JSONResponse(
            {"error": f"created_by must be one of {list(VALID_CREATED_BY)}"},
            status_code=400,
        )

    try:
        result = kb_add(
            title=title,
            content=content,
            entry_type=entry_type,
            tags=tags,
            source_id=source_id,
            created_by=created_by,
        )
        if isinstance(result, dict) and "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse({"data": result}, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/kb/search", methods=["GET"])
async def api_kb_search(request: Request) -> JSONResponse:
    """JSON wrapper around the kb_search MCP tool (FTS5 backend).

    Query string: ?q=<query>&limit=<n>. Title + content + tags are all
    searched (per the FTS5 schema in init_db.sql). Empty query returns
    empty data with a hint (callers should use /api/kb/list for the
    unfiltered listing).
    """
    q = request.query_params.get("q", "").strip()
    if not q:
        return JSONResponse(
            {"data": [], "count": 0, "hint": "empty query; use /api/kb/list for unfiltered"},
            status_code=200,
        )
    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        return JSONResponse({"error": "limit must be an integer"}, status_code=400)
    if limit < 1 or limit > 200:
        return JSONResponse({"error": "limit must be between 1 and 200"}, status_code=400)
    try:
        results = kb_search(query=q, limit=limit)
        if isinstance(results, list) and results and isinstance(results[0], dict) and "error" in results[0]:
            return JSONResponse(results[0], status_code=400)
        return JSONResponse({"data": results, "count": len(results), "query": q})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/api/kb/entries/{entry_id:int}", methods=["DELETE"])
async def api_kb_delete(request: Request) -> JSONResponse:
    """JSON wrapper around the kb_delete MCP tool. DESTRUCTIVE.

    Note: per kb_delete's own spec ("Callers should always confirm
    with the user before invoking this"), the UI does an explicit
    JS confirm() before sending this request. No server-side
    re-confirmation here — same trust model as kb_delete itself.
    """
    entry_id = request.path_params["entry_id"]
    try:
        result = kb_delete(entry_id=entry_id)
        if isinstance(result, dict) and "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse({"data": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def main() -> None:
    parser = argparse.ArgumentParser(description="AIAMSBS kb-mcp server")
    parser.add_argument("--host", default="0.0.0.0", help="bind host (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8002, help="bind port (default 8002)")
    args = parser.parse_args()

    init_db()

    # FastMCP.run() does not accept host/port kwargs in this version — set
    # via the settings object (host/port are top-level Settings fields).
    # Custom routes registered via @mcp.custom_route() share the same
    # streamable-http transport on this port (BACKLOG #57).
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

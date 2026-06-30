PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- A "source" is where a chunk of knowledge came from — a skill file, a
-- customer document, or a runtime observation. Entries reference their source
-- (or are standalone, source_id NULL) so the trust review UI can show
-- provenance.
CREATE TABLE IF NOT EXISTS kb_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL CHECK(source_type IN ('skill', 'customer_doc', 'runtime')),
  file_path_or_url TEXT,
  indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A "entry" is one discrete fact / runbook / gotcha. Trust flows upward:
-- agents start at status=pending, trust_level=0; customer approval moves
-- status to 'approved' (and the trust ladder can promote trust_level in
-- a later K6 card).
CREATE TABLE IF NOT EXISTS kb_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER REFERENCES kb_sources(id) ON DELETE CASCADE,
  entry_type TEXT NOT NULL CHECK(entry_type IN ('runbook', 'fact', 'gotcha')),
  content TEXT NOT NULL,
  tags TEXT,  -- JSON array
  created_by TEXT NOT NULL CHECK(created_by IN ('agent', 'customer')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
  trust_level_at_creation INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kb_entries_status ON kb_entries(status);
CREATE INDEX IF NOT EXISTS idx_kb_entries_source ON kb_entries(source_id);
CREATE INDEX IF NOT EXISTS idx_kb_entries_type ON kb_entries(entry_type);

-- External-content FTS5 index. We index `content` (the entry body) and
-- `tags` (the JSON array as a string) so tag-based and free-text searches
-- both hit the same BM25-ranked table. The `content='kb_entries'` and
-- `content_rowid='id'` options make this a *contentless* mirror table —
-- we keep the FTS index in sync via triggers instead of letting FTS5
-- write into kb_entries directly.
CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
  content,
  tags,
  content='kb_entries',
  content_rowid='id'
);

-- Keep the FTS index in sync with kb_entries. The delete-then-insert
-- pattern in the update trigger is the documented FTS5 "external
-- content" approach: we never let FTS5 see the row twice.
CREATE TRIGGER IF NOT EXISTS kb_ai AFTER INSERT ON kb_entries BEGIN
  INSERT INTO kb_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS kb_ad AFTER DELETE ON kb_entries BEGIN
  INSERT INTO kb_fts(kb_fts, rowid, content, tags) VALUES('delete', old.id, old.content, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS kb_au AFTER UPDATE ON kb_entries BEGIN
  INSERT INTO kb_fts(kb_fts, rowid, content, tags) VALUES('delete', old.id, old.content, old.tags);
  INSERT INTO kb_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
END;

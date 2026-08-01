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
--
-- Title is REQUIRED (CHECK constraint on non-empty) per Ryland 2026-07-29:
-- agents and customers must both provide a title when creating an entry.
-- The Python init_db() migration handles existing rows that pre-date
-- the title column by backfilling from the first line of content.
CREATE TABLE IF NOT EXISTS kb_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER REFERENCES kb_sources(id) ON DELETE CASCADE,
  entry_type TEXT NOT NULL CHECK(entry_type IN ('runbook', 'fact', 'gotcha')),
  title TEXT NOT NULL CHECK(title != ''),
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

-- External-content FTS5 index. We index `title`, `content` (the entry
-- body), and `tags` (the JSON array as a string) so title-based,
-- tag-based, and free-text searches all hit the same BM25-ranked table.
-- The `content='kb_entries'` and `content_rowid='id'` options make this
-- a *contentless* mirror table — we keep the FTS index in sync via
-- triggers instead of letting FTS5 write into kb_entries directly.
CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
  title,
  content,
  tags,
  content='kb_entries',
  content_rowid='id'
);

-- Keep the FTS index in sync with kb_entries. The delete-then-insert
-- pattern in the update trigger is the documented FTS5 "external
-- content" approach: we never let FTS5 see the row twice.
--
-- Pattern: DROP TRIGGER IF EXISTS + CREATE TRIGGER (not IF NOT EXISTS).
-- This ensures old trigger definitions (from a pre-title schema) get
-- replaced with the new title-aware definitions. CREATE TRIGGER IF
-- NOT EXISTS alone would skip the new ones because the old ones match
-- the name — that was the bug fix in commit da38e0b's follow-up.
DROP TRIGGER IF EXISTS kb_ai;
CREATE TRIGGER kb_ai AFTER INSERT ON kb_entries BEGIN
  INSERT INTO kb_fts(rowid, title, content, tags) VALUES (new.id, new.title, new.content, new.tags);
END;
DROP TRIGGER IF EXISTS kb_ad;
CREATE TRIGGER kb_ad AFTER DELETE ON kb_entries BEGIN
  INSERT INTO kb_fts(kb_fts, rowid, title, content, tags) VALUES('delete', old.id, old.title, old.content, old.tags);
END;
DROP TRIGGER IF EXISTS kb_au;
CREATE TRIGGER kb_au AFTER UPDATE ON kb_entries BEGIN
  INSERT INTO kb_fts(kb_fts, rowid, title, content, tags) VALUES('delete', old.id, old.title, old.content, old.tags);
  INSERT INTO kb_fts(rowid, title, content, tags) VALUES (new.id, new.title, new.content, new.tags);
END;

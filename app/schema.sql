-- ResilientEdTech — on-device SQLite schema
-- Offline-first, single-device store. One file (e.g. app/data/resilient.db).
-- Curriculum reference data (dskp.json, tech_tools.json, differentiation_scaffolds.json)
-- stays as versioned JSON files on disk — NOT in this DB.
--
-- Apply with:  sqlite3 app/data/resilient.db < app/schema.sql
-- Notes:
--   * JSON-shaped fields are stored as TEXT holding JSON (SQLite has no native
--     JSON type; use json_extract() to query if ever needed).
--   * Timestamps are ISO-8601 TEXT in UTC (datetime('now')).
--   * "sync_state" columns exist so a future central-server sync (PostgreSQL)
--     can flush rows when connectivity appears — harmless while purely offline.

PRAGMA journal_mode = WAL;      -- better durability + concurrent reads
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- teacher — local profile(s) on this device. Usually a single row.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teacher (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT,
  school        TEXT,
  lang          TEXT NOT NULL DEFAULT 'en',      -- 'en' | 'ms'
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- upload — every lesson-plan file brought in (photo / PDF / DOCX / TXT) and the
-- text the CV/OCR pipeline extracted from it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS upload (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id     INTEGER REFERENCES teacher(id) ON DELETE SET NULL,
  filename       TEXT NOT NULL,
  stored_path    TEXT NOT NULL,                  -- path on local disk
  size_bytes     INTEGER,
  source_type    TEXT,                           -- image | pdf | docx | text
  method         TEXT,                           -- e.g. 'OCR (Tesseract)'
  extracted_text TEXT,
  ocr_confidence REAL,                           -- mean 0-100, nullable
  processed      INTEGER NOT NULL DEFAULT 0,     -- 0 pending, 1 done, 2 archived
  uploaded_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_upload_teacher ON upload(teacher_id);

-- ---------------------------------------------------------------------------
-- lesson_plan — one row per generated plan (the whole run for a lesson).
-- The Analyst output and the Pedagogy Architect's revised plan + differentiation
-- are stored as JSON blobs so the schema doesn't churn as the agent output
-- shape evolves. The few fields you query/sort/print by are promoted to columns.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lesson_plan (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id         INTEGER REFERENCES teacher(id) ON DELETE SET NULL,
  upload_id          INTEGER REFERENCES upload(id) ON DELETE SET NULL,
  lang               TEXT NOT NULL DEFAULT 'en',  -- language the plan was generated in

  -- Promoted, queryable fields (mirror the RPH/ERPH header)
  title              TEXT,
  subject            TEXT,
  form               TEXT,                        -- class / year
  topic              TEXT,
  duration           TEXT,

  -- Inputs captured at generation time
  original_text      TEXT,                        -- the lesson text fed in
  constraints_json   TEXT,                        -- JSON array, e.g. ["No internet","One device only"]

  -- Agent outputs (JSON blobs; see shapes in schemas.py)
  analyst_json       TEXT,                        -- score, alignments, gaps, recommendations, standards
  revised_plan_json  TEXT,                        -- objectives, phases, tools, materials, assessment, alignment_note
  differentiation_json TEXT,                      -- {intro, note, tiers:[{tier,malay,tp,items}]}
  erph_json          TEXT,                        -- ERPH-specific fields: tema, kbat_level, kbat[], pbd, langkah2, penutup

  -- Provenance (from the offline engine)
  alignment_score    INTEGER,                     -- promoted from analyst_json for sorting
  powered_by         TEXT,                        -- 'Llama 3.2 3B (on-device)' | 'rule-based'
  plan_source        TEXT,                        -- 'model' | 'rule-based'
  diff_source        TEXT,                        -- 'model' | 'rule-based'

  -- Sync bookkeeping (no-op while offline-only)
  sync_state         TEXT NOT NULL DEFAULT 'local', -- 'local' | 'pending' | 'synced'
  synced_at          TEXT,

  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_plan_teacher ON lesson_plan(teacher_id);
CREATE INDEX IF NOT EXISTS idx_plan_created ON lesson_plan(created_at);
CREATE INDEX IF NOT EXISTS idx_plan_sync    ON lesson_plan(sync_state);

-- ---------------------------------------------------------------------------
-- faq_query — the FAQ Coach interactions (per teacher question / tool tap).
-- Cheap to keep; useful for "recently asked" and offline analytics.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS faq_query (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id   INTEGER REFERENCES teacher(id) ON DELETE SET NULL,
  plan_id      INTEGER REFERENCES lesson_plan(id) ON DELETE SET NULL,
  lang         TEXT NOT NULL DEFAULT 'en',
  question     TEXT NOT NULL,
  answer_json  TEXT,                              -- {term, explanation, steps[], lowResource, alternatives[]}
  powered_by   TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_faq_plan ON faq_query(plan_id);

-- ---------------------------------------------------------------------------
-- job — the DB-backed background worker queue (extraction / generation).
-- Survives restarts; the worker polls this table. Already present in the app.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  kind         TEXT NOT NULL,                     -- 'extract' | 'analyse' | 'design' | 'sync'
  upload_id    INTEGER REFERENCES upload(id) ON DELETE CASCADE,
  plan_id      INTEGER REFERENCES lesson_plan(id) ON DELETE CASCADE,
  status       TEXT NOT NULL DEFAULT 'queued',    -- queued | running | finished | failed
  result_json  TEXT,                              -- summary payload or {error:...}
  attempts     INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_job_status ON job(status);

-- ---------------------------------------------------------------------------
-- app_meta — key/value for schema version, engine mode, last-sync marker, etc.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_meta (
  key        TEXT PRIMARY KEY,
  value      TEXT
);
INSERT OR IGNORE INTO app_meta(key, value) VALUES ('schema_version', '1');

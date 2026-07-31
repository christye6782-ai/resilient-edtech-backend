# On-device database — SQLite schema

The prototype uses **SQLite** as its on-device store: one file (`app/data/resilient.db`),
no server, fully offline. Curriculum reference data (`dskp.json`, `tech_tools.json`,
`differentiation_scaffolds.json`) stays as versioned JSON files — not in the DB.

Apply the schema:

```bash
sqlite3 app/data/resilient.db < app/schema.sql
```

## Tables

| Table | Holds |
|---|---|
| `teacher` | Local teacher profile(s) + language preference. Usually one row. |
| `upload` | Every lesson-plan file brought in + the CV/OCR-extracted text and confidence. |
| `lesson_plan` | One row per generated run: promoted header fields (title/subject/form/topic/duration) + the Analyst, revised-plan, differentiation, and ERPH outputs as JSON blobs, plus `powered_by`/`plan_source` provenance. |
| `faq_query` | FAQ Coach interactions (question + answer JSON). |
| `job` | DB-backed background worker queue (extract / analyse / design / sync). |
| `app_meta` | key/value: schema version, engine mode, last-sync marker. |

## Design choices

- **JSON blobs for agent output.** The Analyst / Pedagogy Architect / differentiation
  shapes evolve; storing them as JSON TEXT avoids schema churn. The handful of fields
  you sort, print, or list by (title, subject, alignment_score, created_at) are promoted
  to real columns + indexed.
- **`sync_state` columns** are present but inert while offline-only. When you add the
  optional central-server sync, the worker flushes `sync_state='pending'` rows to
  PostgreSQL and marks them `'synced'` — no schema change needed later.
- **WAL journal mode** for durability + concurrent reads (the worker polls `job` while
  the UI reads plans).
- **Reference data stays as files.** `dskp.json` etc. are read-only, human-editable, and
  version-controlled — better as files than rows.

## If you later add central sync (many schools)

Mirror `lesson_plan` (+ `teacher`, `upload`) into **PostgreSQL** on a server. SQLite stays
the offline source of truth on each device; the `job` worker pushes pending rows when a
connection appears. Postgres handles concurrent multi-school writes, JSON columns, and
district reporting. No cloud dependency is introduced on the classroom device.

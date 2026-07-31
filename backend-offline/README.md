# ResilientEdTech — Localized Offline Agentic AI (backend)

A **fully offline, on-device agentic AI** for planning technology-rich lessons in
rural and remote schools. Every agent runs on **one device with no internet** —
no cloud tier, no network call anywhere in the stack. "Localized" in two senses:

- **On-device / local** — the model (Llama 3.2 3B via Ollama) and the whole
  pipeline run on the teacher's machine. Nothing ever leaves the classroom.
- **Culturally localized** — tuned to the Malaysian curriculum (DSKP, scheme of
  work, textbook, KSSR performance levels) and Bahasa Melayu.

**Agentic** — an autonomous pipeline of specialist agents cooperates to turn a
raw lesson plan into a constraint-proof, differentiated, curriculum-aligned one.

## The agents

1. **The Analyst** — scores the plan against DSKP / scheme of work / textbook and
   surfaces the gaps.  (`agents/analyst.py`, `POST /api/analyse`)
2. **The Pedagogy Architect** — rebuilds the lesson around the school's
   constraints **and** splits it into KSSR readiness tiers (Remedial TP1–2, Core
   TP3–4, Enrichment TP5–6) in one pass.  (`agents/pedagogy_architect.py`,
   `POST /api/design`)
3. **The FAQ Coach** — explains any suggested tool with offline how-to steps and
   no-tech alternatives.  (`agents/faq.py`, `POST /api/faq`)

(`agents/auditor.py` remains as a helper the Pedagogy Architect reuses, and a
deprecated `POST /api/audit` alias returns just the plan for back-compat.)

## Two offline engine tiers

Every agent calls `llm.structured_call()`, which resolves to one of two tiers —
**both fully offline**:

```
ENGINE_MODE = auto   →  on-device Llama (if reachable) → rule-based
ENGINE_MODE = local  →  on-device Llama → rule-based
ENGINE_MODE = basic  →  rule-based only
```

When the model is unavailable (no Ollama, or the lowest-spec hardware),
`structured_call()` returns `None` and each agent falls back to a deterministic
**rule-based** engine built from the bundled knowledge bases — so the app always
produces a complete answer, even on a bare device. `powered_by` on every result
reports which tier answered (`Llama 3.2 3B (on-device)` or `rule-based`).

## System requirements

- **Python** 3.10+ with the packages in `requirements.txt`
  (FastAPI, Uvicorn, Pydantic, `ollama`, OpenCV-headless, pytesseract, pypdf,
  python-docx, reportlab).
- **On-device model (optional but recommended):** [Ollama](https://ollama.com)
  with `llama3.2:3b` pulled (`ollama pull llama3.2:3b`). ~2–3 GB on disk; runs on
  a modern laptop / mini-PC. Without it, the app runs in rule-based `basic` mode.
- **OCR (optional):** Tesseract, for reading photographed / scanned lesson plans.
- **Internet:** none required at runtime. (Only the one-time model + package
  download needs a connection.)

## Run

```bash
cp .env.example .env         # defaults are fine for a local run
pip install -r requirements.txt
ollama pull llama3.2:3b      # optional — enables the on-device model tier
uvicorn app.main:app --reload
# open http://127.0.0.1:5000
```

## Knowledge bases (the "localized" data)

All bundled, all offline — expand these to improve rule-based quality:

- `app/data/dskp.json` — DSKP topics, content & learning standards.
- `app/data/tech_tools.json` — low-resource / offline-capable teaching tools.
- `app/data/differentiation_scaffolds.json` — KSSR tier templates + scaffolds.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/health`   | Status + active engine tier (`local`/`basic`), always `offline: true`. |
| GET  | `/api/engine`   | Current mode + on-device model availability. |
| POST | `/api/engine`   | Switch mode at runtime (`auto`/`local`/`basic`). |
| POST | `/api/extract`  | CV/OCR: photo/PDF/DOCX/TXT → lesson text. |
| POST | `/api/analyse`  | The Analyst. |
| POST | `/api/design`   | The Pedagogy Architect — revised plan **+** differentiation tiers. |
| POST | `/api/audit`    | Deprecated — plan only (back-compat). |
| POST | `/api/faq`      | The FAQ Coach. |

## What changed from the earlier "hybrid" build

The cloud tier and all network/connectivity code were removed. `config.py` and
`llm.py` now know only the on-device and rule-based tiers; `/api/health` no longer
reports connectivity (it reports `offline: true`). Everything else — the agents,
the Pedagogy Architect merge, the schemas, the CV pipeline — is unchanged.

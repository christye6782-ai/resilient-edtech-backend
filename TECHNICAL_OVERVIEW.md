# ResilientEdTech — Technical Overview

*A reference for article writing. Covers positioning, architecture, the agent
pipeline, system requirements, the offline engine, and the computer-vision
pipeline. Figures in this document reflect the current **Localized Offline
Agentic AI** build.*

---

## 1. What it is

ResilientEdTech is a **Localized Offline Agentic AI** assistant that helps
teachers in rural and remote schools turn an existing lesson plan into a
technology-rich, differentiated, curriculum-aligned one — running entirely on a
single device with **no internet connection at any point at runtime**.

"Localized" carries two meanings deliberately:

- **On-device / local compute** — the language model and the entire agent
  pipeline execute on the teacher's own machine. No data ever leaves the
  classroom; there is no cloud dependency.
- **Culturally localized** — the system is tuned to the Malaysian national
  curriculum (DSKP content & learning standards, the scheme of work, prescribed
  textbooks, and KSSR performance levels *Tahap Penguasaan* TP1–TP6) and is fully
  bilingual in English and Bahasa Melayu.

"Agentic" refers to the autonomous multi-agent pipeline: specialist AI agents
each own a well-scoped task and hand their output to the next.

## 2. The problem it addresses

Rural classrooms frequently operate under hard constraints: no internet, a
single shared device, one screen, limited or no mains electricity, and mixed
student readiness within one room. Generic AI lesson tools assume connectivity
and uniform resources. ResilientEdTech instead treats those constraints as
first-class inputs and designs lessons that remain technology-integrated *within*
them — while never requiring a connection itself.

## 3. Architecture at a glance

```
                         ┌─────────────────────────────────────────┐
                         │            One device (offline)          │
  Teacher's lesson plan  │                                          │
  (typed, or a photo) ──►│  CV / OCR pipeline  ─►  extracted text   │
                         │                                          │
                         │        Agent pipeline (agentic):         │
                         │   1) Analyst  ─►  2) Pedagogy Architect   │
                         │                    ─►  3) FAQ Coach       │
                         │                                          │
                         │   Engine: Llama 3.2 3B (Ollama)  ──┐      │
                         │           rule-based fallback  ◄───┘      │
                         └─────────────────────────────────────────┘
                                          │
                                 Revised, differentiated,
                                 DSKP-aligned lesson plan  ─►  printable RPH
```

- **Backend:** FastAPI application served by Uvicorn.
- **Frontend:** HTML/CSS/JavaScript, no build step; served as static files by the
  same app so the whole thing is one local process.
- **Model:** Llama 3.2 3B served locally by Ollama, using JSON-schema–constrained
  structured output. A deterministic rule-based engine is the fallback.
- **Computer vision:** OpenCV pre-processing + Tesseract OCR to read photographed
  or scanned handwritten plans.

## 4. The agent pipeline

| # | Agent | Responsibility | Endpoint |
|---|---|---|---|
| 1 | **The Analyst** | Scores the uploaded plan against DSKP, the scheme of work and the textbook; detects standards; lists gaps and recommendations. | `POST /api/analyse` |
| 2 | **The Pedagogy Architect** | Rebuilds the lesson to work within the school's stated constraints while keeping meaningful, offline-capable technology **and** splits the hands-on/formative step into three KSSR readiness tiers (Remedial TP1–2, Core TP3–4, Enrichment TP5–6) — in a single model call. | `POST /api/design` |
| 3 | **The FAQ Coach** | Explains any suggested tool in plain language with step-by-step offline setup and no-tech alternatives. | `POST /api/faq` |

The Pedagogy Architect is a deliberate **consolidation** of two earlier roles
(an "Auditor" that redesigned the lesson and a "Differentiation Strategist" that
tiered it). Merging them removes a whole model round-trip — a meaningful saving
when inference runs on a local 3B model — and is safe because differentiation
operates directly on the plan the redesign produces. The Analyst stays separate
(it *evaluates* rather than *generates*, and mixing critique with generation
makes small models grade their own work leniently), as does the FAQ Coach (it is
reactive, fired per teacher question). *Presentation roles are decoupled from
execution agents:* the UI may still show the individual helpers even though the
backend serves the plan and tiers from one call.

## 5. The offline engine (resilience by design)

Every agent calls a single function, `structured_call()`, which resolves to one
of two tiers — **both fully offline**:

```
ENGINE_MODE = auto   →  on-device Llama (if reachable) → rule-based
ENGINE_MODE = local  →  on-device Llama → rule-based
ENGINE_MODE = basic  →  rule-based only
```

If the model is unavailable — no Ollama installed, or the device is too
low-spec — `structured_call()` returns `None`, and each agent falls back to a
deterministic rule-based engine built from the bundled knowledge bases. The
result: the application **always** produces a complete plan, from a well-equipped
laptop down to a bare device with no model at all. Each response records a
`powered_by` field (`Llama 3.2 3B (on-device)` or `rule-based`) for transparency.

The Pedagogy Architect additionally degrades *partially*: because its combined
output schema is larger (and small models occasionally emit partly-invalid JSON),
it salvages the plan and the differentiation tiers independently — keeping a
valid model-generated plan even if the tiers must be synthesised from the
scaffold playbook, and vice-versa.

## 6. Computer-vision / OCR pipeline

A teacher can photograph a handwritten plan. The pipeline
(`app/cv_service.py`) runs: grayscale → denoise → deskew → adaptive threshold →
Tesseract OCR, returning the extracted text, a mean OCR confidence score, and a
preview of the pre-processed image the system "saw". PDF, DOCX and TXT uploads are
parsed directly. All of this runs locally.

## 7. Knowledge bases (the localized data)

Three bundled JSON files ground the agents and power the rule-based fallback —
all offline, all extensible:

- `dskp.json` — DSKP topics with content and learning standards.
- `tech_tools.json` — low-resource / offline-capable teaching tools, each with
  its internet and device requirements, a step-by-step how-to, and a no-tech
  alternative.
- `differentiation_scaffolds.json` — KSSR performance-level tier templates and
  scaffold moves.

## 8. Output

The revised plan renders on screen as structured cards and prints as a
standardized **RPH (Rancangan Pengajaran Harian)** document with the conventional
fields — subject/class/date/time header, content & learning standards, objectives,
success criteria, a phased PdP activity table, differentiation tiers, teaching
aids (BBM), cross-curricular elements (EMK), assessment, and a reflection section
— in whichever language (EN/BM) is active.

## 9. System requirements

**Runtime — no internet required.**

| Component | Requirement |
|---|---|
| OS | Windows, macOS or Linux (a modern laptop or mini-PC) |
| Python | 3.10 or newer |
| Python packages | FastAPI, Uvicorn, Pydantic, `ollama`, opencv-python-headless, pytesseract, pypdf, python-docx, reportlab (see `requirements.txt`) |
| On-device model *(recommended)* | Ollama with `llama3.2:3b` pulled (~2–3 GB on disk). Without it, the app runs in rule-based `basic` mode. |
| OCR *(optional)* | Tesseract, to read photographed/scanned plans |
| Internet | **None at runtime.** A connection is needed only once, to download the packages and the model. |

**Approximate footprint:** the model is the dominant cost (~2–3 GB); the
application code, dependencies and knowledge bases are small. Inference speed
depends on CPU/GPU, but a 3B model is chosen specifically to run acceptably on
commodity hardware without a dedicated GPU.

## 10. Design & UX notes

The interface presents the pipeline as a left-hand "workflow rail" of named
agents that light up as each stage completes, an on-device AI identity badge
(with an on-device ↔ rule-based mode switch and a privacy statement), a
constraints selector, and a dedicated results screen. It is fully bilingual
(EN/BM), responsive down to a phone-width layout, and prints to the standardized
RPH document.

---

*Note on provenance: this build removed an earlier optional cloud tier to commit
fully to the offline, on-device positioning. If you reference version history in
the article, the current system is offline-only by design; connectivity is not
part of the runtime data path.*

# Hybrid AI engine — backend wiring

This adds **online + offline (hybrid)** AI to the three agents, on top of the
existing offline-first design. Nothing about the agents' behaviour, schemas or
the rule-based fallback changes — only *where* the model answer comes from.

```
ENGINE_MODE = auto   →  CLOUD (if online & key set) → LOCAL Ollama → rule-based
ENGINE_MODE = cloud  →  CLOUD → rule-based
ENGINE_MODE = local  →  LOCAL Ollama → rule-based
ENGINE_MODE = basic  →  rule-based only
```

Because `structured_call()` still returns `None` when no model tier succeeds,
the agents' existing fallback path handles "no internet **and** no Ollama"
exactly as before. The app always produces a complete answer.

---

## How to apply

These files are **drop-in replacements** under `ResilientEdTech/app/`. Copy them
over the originals (keep a backup / commit first):

| Replace | With |
|---|---|
| `app/config.py`        | `backend-hybrid/app/config.py` |
| `app/llm.py`           | `backend-hybrid/app/llm.py` |
| `app/main.py`          | `backend-hybrid/app/main.py` |
| `app/agents/analyst.py`| `backend-hybrid/app/agents/analyst.py` |
| `app/agents/auditor.py`| `backend-hybrid/app/agents/auditor.py` |
| `app/agents/faq.py`    | `backend-hybrid/app/agents/faq.py` |
| `.env.example`         | `backend-hybrid/.env.example` |

The agent files differ from the originals by **two lines each**: the import
gains `powered_by_label`, and the success branch sets
`powered_by = powered_by_label()` instead of the hardcoded `"Llama 3.2 3B"`, so
the result honestly reports whether the cloud or the on-device model answered.

No new dependencies are required. The cloud call uses `httpx` if it's installed
(it ships with FastAPI's test client) and otherwise falls back to the standard
library, so it runs as-is.

Then:

```bash
cp .env.example .env          # add CLOUD_API_KEY if you want the cloud tier
uvicorn app.main:app --reload
```

---

## What each file does

- **`config.py`** — adds `ENGINE_MODE` plus the cloud-tier settings
  (`CLOUD_API_KEY`, `CLOUD_BASE_URL`, `CLOUD_MODEL`, timeouts). Cloud is only
  "configured" when a key is present.
- **`llm.py`** — the real work. A tiered `structured_call()` that walks the tier
  order for the active mode, an OpenAI-compatible `_cloud_chat()`, a cheap
  socket-based `internet_reachable()` probe for `auto` mode, `resolve_engine()`
  / `engine_status()` for inspection, and `get_mode()` / `set_mode()` for the
  runtime switch. `llm_status()` is kept as an alias so nothing else breaks.
- **`main.py`** — `/api/health` now reports `engine_mode`, `active_engine`
  (`cloud`/`local`/`basic`), `online`, and per-tier detail. New
  **`GET /api/engine`** and **`POST /api/engine {"mode": "..."}"`** read/switch
  the mode at runtime.

---

## Frontend contract (for the AI-engine indicator)

The redesigned UI's top-bar indicator maps 1:1 onto these endpoints:

- **On load** → `GET /api/health`, read `active_engine` + `online`:
  - `cloud` → "Online · cloud AI"  (teal dot)
  - `local` → "Offline · on-device" (amber dot)
  - `basic` → "Basic mode"          (grey dot)
- **Mode popover selection** (Automatic / On-device only / Basic) →
  `POST /api/engine {"mode": "auto" | "local" | "basic"}`, then re-render from
  the returned `engine_status()`.

Paste-ready snippet for `frontend/js/app.js`:

```js
async function refreshEngine() {
  const h = await fetch('/api/health').then(r => r.json());
  // h.active_engine: 'cloud' | 'local' | 'basic'; h.online: bool; h.engine_mode
  renderEnginePill(h.active_engine, h.online, h.engine_mode);
}
async function setEngineMode(mode) {            // 'auto' | 'cloud' | 'local' | 'basic'
  const s = await fetch('/api/engine', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  }).then(r => r.json());
  renderEnginePill(s.resolved, s.cloud.online, s.mode);
}
```

> The HTML redesign (`ResilientEdTech Redesign B.dc.html`) currently *simulates*
> these states client-side for the demo. Wiring it to the live endpoints is just
> swapping the simulated toggle for the two calls above.

---

## Optional next step — deferred sync

The existing DB-backed `jobs` worker is the natural place for true offline→online
sync: queue analyses made offline and flush them when `internet_reachable()`
returns true. Not included here (it's a feature, not a wiring change), but the
seam is ready.

# ResilientEdTech 🌾💡

**AI lesson-planning assistant for teachers in rural areas** — plan technology-rich
lessons that still work under real-world constraints (no internet, one device, one
screen, no electricity…), while staying aligned to the **DSKP**, the **scheme of
work**, and the **textbook**.

Built around three AI agents and a computer-vision document pipeline.

---

## The three agents

| Agent | Role |
|-------|------|
| **1 · The Analyst** | Reads the teacher's uploaded lesson plan and checks it against the DSKP, scheme of work and textbook topics — reporting an alignment score, the content/learning standards detected, gaps and recommendations. |
| **2 · The Auditor** | Takes the constraints the school faces and redesigns the lesson so it *keeps* meaningful technology integration but works entirely within those constraints. Produces a complete, **printable** lesson plan. |
| **3 · FAQ** | Explains any term or tool the Auditor suggests (e.g. *"What is Plickers?"*) and gives step-by-step, low-resource execution guidance. |

**Input:** (1) teacher uploads their own lesson plan, (2) teacher selects the
constraint(s) faced.
**Output:** a revised lesson with the best possible technology integration for those
constraints, still aligned to DSKP, textbook and scheme of work.

---

## How the Computer Vision fits in

A rural teacher often only has a **photo** of a handwritten or printed plan. The
backend connects to a CV pipeline (`app/cv_service.py`):

```
upload → OpenCV pre-processing (grayscale → denoise → deskew → adaptive threshold)
       → Tesseract OCR → extracted text + confidence + a preview of what the model "saw"
```

PDF, DOCX and TXT uploads are also supported (text extracted directly). The preview
image lets the teacher see exactly what the vision model read.

---

## Architecture

```
ResilientEdTech/
├── app/                     # FastAPI backend
│   ├── main.py              # API routes + serves the frontend
│   ├── cv_service.py        # Computer-vision / OCR pipeline
│   ├── llm.py               # Ollama / Llama 3.2 3B wrapper
│   ├── agents/              # The three agents
│   │   ├── analyst.py
│   │   ├── auditor.py
│   │   └── faq.py
│   └── data/                # DSKP + ed-tech knowledge bases
├── frontend/                # HTML + CSS + vanilla JS
├── samples/                 # A sample lesson plan to try
├── environment.yml          # Anaconda environment
└── requirements.txt         # pip alternative
```

- **Backend:** FastAPI, served by **Uvicorn**
- **Frontend:** HTML, CSS, JavaScript (no build step)
- **AI:** **Llama 3.2 3B** running locally via **Ollama**, with Ollama structured (JSON-schema) output — fully offline, nothing leaves the machine
- **CV:** OpenCV + Tesseract OCR

> The app **runs even without Ollama** using a built-in rule-based fallback, so you can
> demo it immediately. Start Ollama and pull Llama 3.2 3B for full, curriculum-aware AI responses.

---

## Quick start (Anaconda)

```bash
# 1. Create and activate the environment
conda env create -f environment.yml
conda activate resilient-edtech

# 2. (Recommended) install the local AI model
#    Install Ollama from https://ollama.com, then:
ollama pull llama3.2:3b
#    Ollama serves the model at http://localhost:11434 automatically.

# 3. Run the server
uvicorn app.main:app --reload
#   or just:  run.bat   (Windows)  /  ./run.sh  (macOS/Linux)

# 4. Open the app
#   http://127.0.0.1:5000
```

## Maintenance tasks

- Cleanup old uploads (files are stored under `data/uploads`):

```bash
python scripts/cleanup_uploads.py --days 30
```

- List uploads (admin endpoint, optional `ADMIN_KEY` in environment for protection):

```
GET /admin/uploads
```

## Notes on secure storage

- Uploads are stored under `data/uploads` (not served by the frontend static files).
- For production-like deployments, run the app under a system service account and
   restrict filesystem permissions on `data/uploads` to that account only.

## Running the persistent worker (offline-friendly)

The repo includes a lightweight DB-backed worker that polls the `jobs` table and
processes queued tasks. It works without Redis and survives restarts.

Run directly:

```bash
python scripts/worker.py
```

Run both the server and worker together locally:

```bash
# Windows
run_all.bat

# macOS/Linux
./run_all.sh
```

Linux systemd unit example: enable the unit at `/etc/systemd/system/resilient-worker.service` and run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now resilient-worker
```

Windows: use `Task Scheduler` or `nssm` to run `scripts\run_worker_windows.bat` as a service.



> No Ollama? The app still runs in rule-based mode. Settings live in `.env`
> (`copy .env.example .env`) — change `OLLAMA_MODEL`, `OLLAMA_HOST`, etc. there.

Prefer pip? `pip install -r requirements.txt` instead of the conda env (you'll still
need the **Tesseract** engine for OCR — see below).

### Installing the Tesseract OCR engine

`pytesseract` is only a wrapper; install the engine itself:

- **conda:** `conda install -c conda-forge tesseract` (already in `environment.yml`)
- **Windows installer:** <https://github.com/UB-Mannheim/tesseract/wiki> — then set
  `TESSERACT_CMD` in `.env` to e.g. `C:\Program Files\Tesseract-OCR\tesseract.exe`
- **macOS:** `brew install tesseract` · **Debian/Ubuntu:** `sudo apt install tesseract-ocr`

Without it, image OCR is skipped but PDF/DOCX/TXT and pasted text still work.

---

## Using it

1. **Upload** a photo / PDF / DOCX of your lesson plan (or use `samples/sample_lesson_plan.txt`),
   and tag the subject / form / topic.
2. **Select the constraints** your school faces.
3. Click **Analyse & Revise**. The Analyst scores alignment; the Auditor returns a
   revised, printable plan.
4. Click **🖨️ Print lesson plan**, or tap any suggested tool / use the **FAQ** panel
   to learn what it is and how to run it.

---

## API reference

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET`  | `/api/health` | Status + whether Llama 3.2 3B (Ollama) is live |
| `POST` | `/api/extract` | CV/OCR: upload → text (`multipart/form-data`, field `file`) |
| `POST` | `/api/analyse` | Agent 1 — Analyst |
| `POST` | `/api/audit` | Agent 2 — Auditor |
| `POST` | `/api/faq` | Agent 3 — FAQ |

Interactive docs at `http://127.0.0.1:5000/docs` once running.

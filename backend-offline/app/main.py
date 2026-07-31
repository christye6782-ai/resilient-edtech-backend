"""ResilientEdTech — FastAPI backend (Localized Offline Agentic AI build).

Run with:  uvicorn app.main:app --host 127.0.0.1 --port 5000 --reload
Then open: http://127.0.0.1:5000

Everything runs on ONE device with no internet:
  * The agents are powered by Llama 3.2 3B via Ollama (on-device), with a
    rule-based fallback — no cloud tier, no network call anywhere.
  * /api/health reports the active engine tier (on-device / basic) and the
    selected mode.
  * GET/POST /api/engine lets the UI read and switch the engine mode at runtime
    (auto | local | basic) — this is what the top-bar AI-engine indicator binds
    to.
"""
from __future__ import annotations

import logging
import time
import io
from pathlib import Path
from reportlab.pdfgen import canvas

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, cv_service
from . import db as dbmod
from . import rag as ragmod
from .agents import analyst, auditor, faq, pedagogy_architect
from .config import FRONTEND_DIR, DATA_DIR, settings
from .llm import engine_status, get_mode, set_mode
from .schemas import (
    AnalystRequest,
    AnalystResult,
    AuditorRequest,
    AuditorResult,
    DesignRequest,
    DesignResult,
    ExtractionResult,
    FaqRequest,
    FaqResult,
    FeedbackRequest,
    FeedbackResult,
)
import os

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="ResilientEdTech",
    version=__version__,
    description="AI lesson-planning assistant for rural-school teachers — "
    "Analyst, Auditor and FAQ agents with a CV/OCR upload pipeline.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB

# Friendly labels for each resolved engine tier.
_ENGINE_LABELS = {
    "local": "Llama 3.2 3B (on-device)",
    "basic": "rule-based",
}


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health() -> dict:
    eng = engine_status()
    resolved = eng["resolved"]  # local | basic
    return {
        "status": "ok",
        "version": __version__,
        # Engine state
        "engine_mode": eng["mode"],            # selected preference
        "active_engine": resolved,             # what will actually serve a request
        "active_label": _ENGINE_LABELS.get(resolved, "rule-based"),
        "offline": True,                       # always — no network path exists
        # Back-compat with the original health shape:
        "llm_enabled": resolved != "basic",
        "model": settings.ollama_model,
        "host": settings.ollama_host,
        # Per-tier detail
        "local": eng["local"],
    }


class EngineModeRequest(BaseModel):
    mode: str  # auto | local | basic


@app.get("/api/engine")
def get_engine() -> dict:
    """Current engine mode + per-tier availability (for the UI indicator)."""
    return engine_status()


@app.post("/api/engine")
def post_engine(req: EngineModeRequest) -> dict:
    """Switch the engine mode at runtime (auto | local | basic)."""
    try:
        set_mode(req.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return engine_status()


@app.post("/api/extract", response_model=ExtractionResult)
async def extract(file: UploadFile = File(...)) -> ExtractionResult:
    """CV/OCR pipeline: turn an uploaded lesson plan (image/PDF/DOCX/TXT) into text."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 15 MB).")
    # persist uploaded file to local storage
    storage_dir = Path(DATA_DIR) / "uploads"
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"upload_{int(time.time())}_{file.filename}"
    with open(stored_path, "wb") as fh:
        fh.write(content)

    # record upload metadata and run extraction synchronously
    dbmod.init_db()
    upload_id = dbmod.insert_upload(file.filename or "", str(stored_path), len(content))
    res = cv_service.extract_from_upload(file.filename or "", content)
    conf = getattr(res, "confidence", None)
    dbmod.update_upload_extraction(upload_id, res.text or "", conf)
    return res


@app.post("/api/extract-async")
async def extract_async(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict:
    """Accept upload and queue a background extraction job; returns job id."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 15 MB).")

    storage_dir = Path(DATA_DIR) / "uploads"
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"upload_{int(time.time())}_{file.filename}"
    with open(stored_path, "wb") as fh:
        fh.write(content)

    dbmod.init_db()
    upload_id = dbmod.insert_upload(file.filename or "", str(stored_path), len(content))
    job_id = dbmod.insert_job("extract", upload_id)

    def _worker(jid: int, fname: str, data: bytes):
        try:
            dbmod.update_job_status(jid, "running")
            res = cv_service.extract_from_upload(fname, data)
            dbmod.update_upload_extraction(upload_id, res.text or "", getattr(res, "confidence", None))
            dbmod.update_job_status(jid, "finished", {"extracted_words": len((res.text or "").split())})
        except Exception as e:
            dbmod.update_job_status(jid, "failed", {"error": str(e)})

    background_tasks.add_task(_worker, job_id, file.filename or "", content)
    return {"job_id": job_id, "upload_id": upload_id}


@app.get("/api/job/{job_id}")
def get_job(job_id: int):
    dbmod.init_db()
    j = dbmod.get_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job not found")
    return j


@app.post("/api/export")
def export_pdf(req: AnalystRequest):
    """Generate a simple PDF from lesson text (returns application/pdf)."""
    text = req.lesson_text or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="lesson_text is required.")
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer)
    width, height = 595, 842  # A4 in points
    margin = 40
    y = height - margin
    p.setFont("Helvetica", 12)
    for line in text.splitlines():
        if y < margin:
            p.showPage()
            y = height - margin
            p.setFont("Helvetica", 12)
        p.drawString(margin, y, line[:90])
        y -= 14
    p.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=lesson_plan.pdf"})


@app.post("/admin/cleanup")
def admin_cleanup(days: int = 30):
    """Delete uploaded files older than `days` and mark DB entries processed=2."""
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(days=days)
    dbmod.init_db()
    conn = dbmod.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, stored_path, uploaded_at FROM uploads WHERE uploaded_at IS NOT NULL")
    rows = cur.fetchall()
    removed = 0
    for r in rows:
        try:
            uploaded_at = datetime.fromisoformat(r[2])
        except Exception:
            continue
        if uploaded_at < cutoff:
            p = Path(r[1])
            if p.exists():
                try:
                    p.unlink()
                    removed += 1
                except Exception:
                    pass
            cur.execute("UPDATE uploads SET processed = 2 WHERE id = ?", (r[0],))
    conn.commit()
    conn.close()
    return {"removed_files": removed}


@app.get("/admin/uploads")
def admin_list_uploads(limit: int = 200, key: str | None = None):
    """Return a list of recent uploads. If `ADMIN_KEY` env var is set, require `key` to match."""
    admin_key = os.getenv("ADMIN_KEY")
    if admin_key and admin_key != "" and key != admin_key:
        raise HTTPException(status_code=403, detail="forbidden")
    dbmod.init_db()
    return {"uploads": dbmod.list_uploads(limit)}


@app.post("/api/analyse", response_model=AnalystResult)
def analyse(req: AnalystRequest) -> AnalystResult:
    """Agent 1 — The Analyst."""
    if not req.lesson_text.strip():
        raise HTTPException(status_code=400, detail="lesson_text is required.")
    return analyst.analyse(req)


@app.post("/api/design", response_model=DesignResult)
def design(req: DesignRequest) -> DesignResult:
    """Merged agent — The Pedagogy Architect (Auditor + Differentiation).

    One call returns the revised, constraint-proof lesson plan AND its three
    KSSR readiness tiers (Remedial / Core / Enrichment). This replaces the
    separate audit + differentiation steps with a single model round-trip.
    """
    if not req.lesson_text.strip():
        raise HTTPException(status_code=400, detail="lesson_text is required.")
    return pedagogy_architect.design(req)


@app.post("/api/audit", response_model=AuditorResult, deprecated=True)
def audit(req: AuditorRequest) -> AuditorResult:
    """DEPRECATED — kept for back-compat. Prefer /api/design, which also returns
    the differentiation tiers in the same call. This returns only the plan."""
    if not req.lesson_text.strip():
        raise HTTPException(status_code=400, detail="lesson_text is required.")
    d = pedagogy_architect.design(
        DesignRequest(
            lesson_text=req.lesson_text, constraints=req.constraints,
            subject=req.subject, form=req.form, topic=req.topic,
            analyst_summary=req.analyst_summary, lang=req.lang,
        )
    )
    return AuditorResult(revised_plan=d.revised_plan, powered_by=d.powered_by)


@app.post("/api/faq", response_model=FaqResult)
def ask_faq(req: FaqRequest) -> FaqResult:
    """Agent 3 — FAQ."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question is required.")
    return faq.answer(req)


# --------------------------------------------------------------------------- #
# Recent plans — persistent lesson history (SQLite, on-device, no login).
# A single implicit local teacher (teacher_id=1) owns the history by default;
# pass ?teacher_id=N only if a shared device ever adds a profile picker.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Teacher profiles — no-password local profiles for a shared device.
# --------------------------------------------------------------------------- #

@app.get("/api/teachers")
def api_list_teachers() -> dict:
    """All local profiles (id=1 is the default). Used by the profile picker."""
    dbmod.init_db()
    return {"teachers": dbmod.list_teachers()}


@app.post("/api/teachers")
def api_create_teacher(body: dict) -> dict:
    """Create a new profile from {"name": "..."}. No password."""
    name = (body or {}).get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    dbmod.init_db()
    return dbmod.insert_teacher(name)


@app.delete("/api/teachers/{teacher_id}")
def api_delete_teacher(teacher_id: int) -> dict:
    """Delete a profile and its plans. The default profile (id=1) cannot be removed."""
    dbmod.init_db()
    if not dbmod.delete_teacher(teacher_id):
        raise HTTPException(status_code=400, detail="cannot delete this profile.")
    return {"deleted": True, "id": teacher_id}


@app.get("/api/rag/status")
def api_rag_status() -> dict:
    """RAG readiness: embed model present, indexed counts, corpus manifest."""
    return ragmod.status()


@app.post("/api/rag/reindex")
def api_rag_reindex(force: bool = False) -> dict:
    """Embed + index the curriculum corpus (one-time / after corpus changes).
    Requires the embedding model: `ollama pull nomic-embed-text`."""
    return ragmod.index_curriculum(force=force)


@app.get("/api/plans")
def api_list_plans(teacher_id: int = 1, limit: int = 50) -> dict:
    """List saved lesson-plan runs (newest first) for the local teacher."""
    dbmod.init_db()
    return {"plans": dbmod.list_plans(teacher_id=teacher_id, limit=limit)}


@app.post("/api/plans")
def api_save_plan(rec: dict, teacher_id: int = 1) -> dict:
    """Persist one completed run. Body is the full client plan record."""
    if not isinstance(rec, dict) or not rec:
        raise HTTPException(status_code=400, detail="plan record is required.")
    dbmod.init_db()
    saved = dbmod.insert_plan(rec, teacher_id=teacher_id)
    # Level 3 (P2): index the saved lesson so it can personalise future designs.
    # No-op unless the embedding model is present; never blocks the save.
    try:
        text = " ".join(str(rec.get(k, "")) for k in ("subject", "form", "topic", "title", "lessonText"))
        ragmod.index_lesson(saved["id"], teacher_id, text,
                            meta={"subject": rec.get("subject"), "year": None})
    except Exception:  # noqa: BLE001
        pass
    return saved


@app.get("/api/plans/{plan_id}")
def api_get_plan(plan_id: int) -> dict:
    """Full saved record (with parsed payload) for reopening a past plan."""
    dbmod.init_db()
    p = dbmod.get_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="plan not found")
    return p


@app.delete("/api/plans/{plan_id}")
def api_delete_plan(plan_id: int) -> dict:
    """Delete one saved plan."""
    dbmod.init_db()
    if not dbmod.delete_plan(plan_id):
        raise HTTPException(status_code=404, detail="plan not found")
    return {"deleted": True, "id": plan_id}


# --------------------------------------------------------------------------- #
# Level 4 — reflective feedback. A teacher marks how a past plan actually went;
# the aggregate feeds the Architect on the next design (see reflection_context).
# --------------------------------------------------------------------------- #

@app.post("/api/plans/{plan_id}/feedback", response_model=FeedbackResult)
def api_save_feedback(plan_id: int, req: FeedbackRequest) -> FeedbackResult:
    """Upsert how this plan went. One feedback row per plan."""
    dbmod.init_db()
    if dbmod.get_plan(plan_id) is None:
        raise HTTPException(status_code=404, detail="plan not found")
    tid = req.teacher_id or 1
    dbmod.upsert_feedback(
        plan_id, tid, req.rating, req.tools_worked, req.tools_flopped,
        req.notes, req.taught_on,
    )
    # L5: refresh the consolidated profile so the next design uses the clean
    # summary rather than the growing raw feedback list.
    try:
        dbmod.consolidate(tid)
    except Exception:  # noqa: BLE001
        pass
    row = dbmod.get_feedback(plan_id) or {}
    return FeedbackResult(
        plan_id=plan_id, rating=row.get("rating"),
        tools_worked=row.get("tools_worked") or [], tools_flopped=row.get("tools_flopped") or [],
        notes=row.get("notes") or "", taught_on=row.get("taught_on") or "",
        updated_at=row.get("updated_at"),
    )


@app.get("/api/plans/{plan_id}/feedback")
def api_get_feedback(plan_id: int) -> dict:
    """Read back the feedback for one plan (empty object if none yet)."""
    dbmod.init_db()
    return {"feedback": dbmod.get_feedback(plan_id)}


@app.get("/api/reflection")
def api_reflection(teacher_id: int = 1) -> dict:
    """The teacher's aggregated reflection digest (what's worked / flopped)."""
    dbmod.init_db()
    return dbmod.reflection_digest(teacher_id)


@app.get("/api/teachers/{teacher_id}/profile")
def api_get_profile(teacher_id: int) -> dict:
    """Read the consolidated Level-5 teaching profile (null if not built yet)."""
    dbmod.init_db()
    return {"profile": dbmod.get_profile(teacher_id)}


@app.post("/api/teachers/{teacher_id}/profile")
def api_consolidate_profile(teacher_id: int) -> dict:
    """(Re)build the consolidated profile from this teacher's feedback + plans."""
    dbmod.init_db()
    return {"profile": dbmod.consolidate(teacher_id)}


@app.get("/api/teachers/{teacher_id}/suggestion")
def api_suggestion(teacher_id: int) -> dict:
    """Level 6 — a proactive 'usual setup' the UI can offer before the teacher
    starts (pre-tick constraints, name go-to tools). A nudge, not auto-apply."""
    dbmod.init_db()
    return dbmod.suggestion(teacher_id)


# --------------------------------------------------------------------------- #
# Frontend (static files). Mounted last so /api/* takes precedence.
# --------------------------------------------------------------------------- #

@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

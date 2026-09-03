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
from typing import Optional
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
from .config import FRONTEND_DIR, DATA_DIR, UPLOADS_DIR, settings
from .llm import engine_status, get_mode, set_mode, get_model, set_model, MODEL_CHOICES
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
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("resilient-edtech.api")

app = FastAPI(
    title="ResilientEdTech",
    version=__version__,
    description="AI lesson-planning assistant for rural-school teachers — "
    "Analyst, Auditor and FAQ agents with a CV/OCR upload pipeline.",
)

# --------------------------------------------------------------------------- #
# CORS.
#
# This was previously allow_origins=["*"], which is unsafe for a local app with
# no authentication. The localhost binding does NOT protect against it: if a
# teacher has the app running and then visits any web page, that page's
# JavaScript can call http://127.0.0.1:5000 from their browser, and a wildcard
# origin tells the browser to hand back the response. With /api/export that is
# a drive-by copy of the whole database; with DELETE /api/plans it is silent
# data loss.
#
# The interface is served from the same origin as the API, so CORS is not
# needed for normal operation. Only explicit localhost origins are allowed, for
# the case where the HTML is opened separately during development.
# --------------------------------------------------------------------------- #
_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5000", "http://localhost:5000",
    "http://127.0.0.1:8000", "http://localhost:8000",
    "http://127.0.0.1:5500", "http://localhost:5500",
]
if os.getenv("RET_ALLOWED_ORIGINS"):
    _ALLOWED_ORIGINS += [
        o.strip() for o in os.getenv("RET_ALLOWED_ORIGINS", "").split(",") if o.strip()
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
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


class EngineModelRequest(BaseModel):
    model: str  # an Ollama tag, e.g. llama3.1:8b


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


@app.get("/api/engine/model")
def get_engine_model() -> dict:
    """Active on-device model + the choices the UI can offer."""
    return {"model": get_model(), "choices": MODEL_CHOICES}


@app.post("/api/engine/model")
def post_engine_model(req: EngineModelRequest) -> dict:
    """Switch the on-device model at runtime (must be pulled locally already)."""
    try:
        set_model(req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"model": get_model(), "choices": MODEL_CHOICES, "engine": engine_status()}


def _safe_upload_name(raw: str) -> str:
    """Reduce an uploaded filename to something safe to join onto a directory.

    `UploadFile.filename` is supplied by the client, and it was being embedded
    directly into the stored path. A name like "../../../evil.bat" escapes the
    uploads folder, giving a write-anywhere primitive — which, combined with the
    permissive CORS that used to be set here, was reachable from any web page
    the teacher happened to have open.

    Keep only the final path component, and only characters that cannot be
    interpreted as path syntax on Windows or POSIX.
    """
    name = os.path.basename(str(raw or "").replace("\\", "/")).strip()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    name = name.lstrip(".") or "upload"          # no leading dots / empty names
    return name[:120]                            # keep well under path limits


@app.post("/api/extract", response_model=ExtractionResult)
async def extract(file: UploadFile = File(...)) -> ExtractionResult:
    """CV/OCR pipeline: turn an uploaded lesson plan (image/PDF/DOCX/TXT) into text."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 15 MB).")
    # persist uploaded file to local storage
    storage_dir = Path(UPLOADS_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"upload_{int(time.time())}_{_safe_upload_name(file.filename)}"
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

    storage_dir = Path(UPLOADS_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"upload_{int(time.time())}_{_safe_upload_name(file.filename)}"
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
    result = pedagogy_architect.design(req)

    # Optional Critic debate (USE_CRITIC=1): a senior-teacher agent raises
    # objections and the Architect revises to answer them. Wrapped so a missing
    # model, bad JSON, or any error just returns the original plan.
    if os.getenv("USE_CRITIC") == "1":
        try:
            from .agents import critic
            from .config import load_tech_tools
            result, transcript = critic.debate(result, req, load_tech_tools())
            if transcript:
                logger.info("critic debate: %s", transcript)
        except Exception:  # noqa: BLE001
            pass
    return result


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


@app.get("/api/export")
def api_export_data():
    """Download every piece of teacher data as one zip.

    Nothing backs up %LOCALAPPDATA% on a school PC, so a reimage would destroy
    months of lesson history. This gives a teacher a single file they can copy
    to a USB stick.

    The database is snapshotted through SQLite's backup API rather than copied
    off disk: a plain file copy taken while a write is in flight can produce a
    corrupt archive, which is worse than no backup at all because it is not
    obvious until restore.
    """
    import sqlite3
    import tempfile
    import zipfile

    dbmod.init_db()
    buf = io.BytesIO()
    stamp = time.strftime("%Y-%m-%d")

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "resilient.db"
        src = dbmod.get_conn()
        try:
            dst = sqlite3.connect(str(snapshot))
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snapshot, "resilient.db")
            uploads = Path(UPLOADS_DIR)
            if uploads.exists():
                for f in uploads.rglob("*"):
                    if f.is_file():
                        z.write(f, f"uploads/{f.relative_to(uploads)}")
            z.writestr("RESTORE.txt", (
                "Resilient EdTech - data backup\n"
                f"Created: {stamp}\n\n"
                "CONTENTS\n"
                "  resilient.db   All lesson plans, teacher profiles and feedback.\n"
                "  uploads/       Lesson files and photographs you uploaded.\n\n"
                "HOW TO RESTORE\n"
                "  1. Close Resilient EdTech.\n"
                "  2. Open the data folder shown in the app's System tab\n"
                "     (usually %LOCALAPPDATA%\\ResilientEdTech).\n"
                "  3. Copy resilient.db and the uploads folder from this zip\n"
                "     into it, replacing what is there.\n"
                "  4. Start the app again.\n\n"
                "Keep this file somewhere other than the classroom PC. If that\n"
                "machine is reimaged or replaced, this zip is the only copy.\n"
            ))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="resilient-edtech-backup-{stamp}.zip"'},
    )


@app.get("/api/diagnostics")
def api_diagnostics() -> dict:
    """One-shot health snapshot for the in-app System panel.

    Aggregates what an administrator (often the teacher themselves, with no IT
    support) needs to answer "why isn't this working?" — engine tier, model
    readiness, curriculum index state, and where the database actually lives.
    Deliberately unauthenticated: this is an offline single-device app, nothing
    here leaves the machine, and a lost password would brick the only person
    able to fix it.
    """
    import platform
    import sys

    eng = engine_status()
    try:
        rag = ragmod.status()
    except Exception as exc:  # noqa: BLE001
        rag = {"error": str(exc)}

    # Database: size on disk + row counts, so a blank app is distinguishable
    # from a broken one.
    db_info: dict = {"path": str(dbmod.DB_PATH)}
    try:
        db_info["size_kb"] = round(dbmod.DB_PATH.stat().st_size / 1024, 1) if dbmod.DB_PATH.exists() else 0
        c = dbmod.get_conn()
        cur = c.cursor()
        counts = {}
        for t in ("plans", "teachers", "plan_feedback", "teacher_profile", "rag_vectors"):
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                counts[t] = cur.fetchone()[0]
            except Exception:  # noqa: BLE001 — table may not exist yet
                counts[t] = None
        c.close()
        db_info["rows"] = counts
    except Exception as exc:  # noqa: BLE001
        db_info["error"] = str(exc)

    # OCR is optional; report it rather than failing when Tesseract is absent
    # (this is exactly the case on the cloud demo instance).
    ocr = {"available": False, "detail": "not installed"}
    try:
        import pytesseract  # noqa: PLC0415
        ocr = {"available": True, "detail": str(pytesseract.get_tesseract_version())}
    except Exception as exc:  # noqa: BLE001
        ocr["detail"] = type(exc).__name__

    return {
        "app": {"version": __version__, "python": sys.version.split()[0],
                "platform": platform.platform()},
        "engine": {
            "mode": eng.get("mode"),
            "resolved": eng.get("resolved"),
            "label": eng.get("label"),
            "model": get_model(),
            "reachable": (eng.get("local") or {}).get("reachable", False),
            "model_ready": (eng.get("local") or {}).get("model_ready", False),
            "host": (eng.get("local") or {}).get("host"),
        },
        "curriculum": {
            "embed_ready": rag.get("embed_ready"),
            "embed_model": rag.get("embed_model"),
            "indexed": rag.get("indexed", {}),
            "by_subject": rag.get("indexed_by_subject", {}),
            "subjects": rag.get("subjects", []),
        },
        "database": db_info,
        "ocr": ocr,
    }


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


def _owned_plan(plan_id: int, teacher_id: Optional[int]) -> dict:
    """Fetch a plan, enforcing profile ownership when a teacher is named.

    On a shared classroom device several teachers keep separate histories. The
    client already filters Recent plans by profile, but that is presentation
    only — without this check any plan id read directly returns a colleague's
    work. 404 (not 403) is deliberate: there is no login here, so a plan the
    caller does not own is simply not found from their point of view.
    """
    p = dbmod.get_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="plan not found")
    if teacher_id is not None and p.get("teacher_id") not in (None, teacher_id):
        raise HTTPException(status_code=404, detail="plan not found")
    return p


@app.get("/api/plans/{plan_id}")
def api_get_plan(plan_id: int, teacher_id: Optional[int] = None) -> dict:
    """Full saved record (with parsed payload) for reopening a past plan.

    Pass ?teacher_id=N to scope the read to that profile.
    """
    dbmod.init_db()
    return _owned_plan(plan_id, teacher_id)


@app.delete("/api/plans/{plan_id}")
def api_delete_plan(plan_id: int, teacher_id: Optional[int] = None) -> dict:
    """Delete one saved plan, scoped to a profile when teacher_id is given."""
    dbmod.init_db()
    _owned_plan(plan_id, teacher_id)
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
    tid = req.teacher_id or 1
    _owned_plan(plan_id, tid)
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
    # The cloud review instance serves a bundle carrying a "demonstration build"
    # banner; the packaged app never sets DEMO_FRONTEND, so it keeps index.html.
    # Falls back rather than 404ing if the demo bundle hasn't been built.
    page = FRONTEND_DIR / "index.html"
    if os.getenv("DEMO_FRONTEND", "").strip().lower() in {"1", "true", "yes"}:
        demo = FRONTEND_DIR / "index-demo.html"
        if demo.is_file():
            page = demo
    return FileResponse(
        page,
        # A teacher's browser must never serve a cached copy of the interface
        # after an update — it looks like the update silently failed. The file
        # is on local disk, so re-reading it costs nothing.
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

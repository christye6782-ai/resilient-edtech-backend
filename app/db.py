"""Simple SQLite-backed metadata store for uploads and results.

Uses Python's built-in sqlite3 to avoid extra dependencies for offline deploys.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "resilient.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY,
            orig_filename TEXT,
            stored_path TEXT,
            uploaded_at TEXT,
            size INTEGER,
            extracted_text TEXT,
            ocr_confidence REAL,
            processed INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER,
            summary TEXT,
            score REAL,
            payload TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audits (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER,
            payload TEXT,
            created_at TEXT
        )
        """
    )
    c.commit()
    c.close()
    # ensure jobs table exists as well
    init_jobs_table()


def insert_upload(orig_filename: str, stored_path: str, size: int) -> int:
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        "INSERT INTO uploads (orig_filename, stored_path, uploaded_at, size) VALUES (?,?,?,?)",
        (orig_filename, stored_path, datetime.utcnow().isoformat(), size),
    )
    uid = cur.lastrowid
    c.commit()
    c.close()
    return uid


def update_upload_extraction(upload_id: int, extracted_text: str, ocr_confidence: Optional[float]) -> None:
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        "UPDATE uploads SET extracted_text = ?, ocr_confidence = ?, processed = 1 WHERE id = ?",
        (extracted_text, ocr_confidence, upload_id),
    )
    c.commit()
    c.close()


def insert_analysis(upload_id: int, summary: str, score: Optional[float], payload: Dict[str, Any]) -> int:
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        "INSERT INTO analyses (upload_id, summary, score, payload, created_at) VALUES (?,?,?,?,?)",
        (upload_id, summary, score, json.dumps(payload), datetime.utcnow().isoformat()),
    )
    aid = cur.lastrowid
    c.commit()
    c.close()
    return aid


def insert_audit(upload_id: int, payload: Dict[str, Any]) -> int:
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        "INSERT INTO audits (upload_id, payload, created_at) VALUES (?,?,?)",
        (upload_id, json.dumps(payload), datetime.utcnow().isoformat()),
    )
    aid = cur.lastrowid
    c.commit()
    c.close()
    return aid


def init_jobs_table() -> None:
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY,
            type TEXT,
            upload_id INTEGER,
            status TEXT,
            result TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    c.commit()
    c.close()


def insert_job(job_type: str, upload_id: Optional[int]) -> int:
    c = get_conn()
    cur = c.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO jobs (type, upload_id, status, created_at, updated_at) VALUES (?,?,?,?,?)",
        (job_type, upload_id, "queued", now, now),
    )
    jid = cur.lastrowid
    c.commit()
    c.close()
    return jid


def update_job_status(job_id: int, status: str, result: Optional[Dict[str, Any]] = None) -> None:
    c = get_conn()
    cur = c.cursor()
    now = datetime.utcnow().isoformat()
    res_text = json.dumps(result) if result is not None else None
    cur.execute(
        "UPDATE jobs SET status = ?, result = ?, updated_at = ? WHERE id = ?",
        (status, res_text, now, job_id),
    )
    c.commit()
    c.close()


def get_job(job_id: int) -> Optional[Dict[str, Any]]:
    c = get_conn()
    cur = c.cursor()
    cur.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    if d.get("result"):
        try:
            d["result"] = json.loads(d["result"])
        except Exception:
            pass
    return d


def list_uploads(limit: int = 100) -> list:
    c = get_conn()
    cur = c.cursor()
    cur.execute("SELECT id, orig_filename, stored_path, uploaded_at, size, processed, ocr_confidence FROM uploads ORDER BY uploaded_at DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    c.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "orig_filename": r[1],
            "stored_path": r[2],
            "uploaded_at": r[3],
            "size": r[4],
            "processed": r[5],
            "ocr_confidence": r[6],
        })
    return out

# --------------------------------------------------------------------------- #
# plans — persistent "Recent plans" history for the teacher's device.
#
# One row per generated lesson (a full Analyst + Pedagogy Architect run). The
# whole client record is stored as JSON in `payload` so the shape can evolve
# without a migration; the few fields we list/sort by are promoted to columns.
#
# `teacher_id` defaults to 1 — a single implicit local profile. The app is
# offline and single-device, so there is no login; if a device is ever shared
# by several teachers, a lightweight profile picker can pass a real teacher_id.
# --------------------------------------------------------------------------- #

DEFAULT_TEACHER_ID = 1


def init_plans_table() -> None:
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY,
            teacher_id INTEGER DEFAULT 1,
            lang TEXT,
            title TEXT,
            subject TEXT,
            form TEXT,
            topic TEXT,
            score REAL,
            data_source TEXT,
            constraints TEXT,
            tools TEXT,
            payload TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_plans_teacher ON plans(teacher_id, created_at)")
    c.commit()
    c.close()


def insert_plan(rec: Dict[str, Any], teacher_id: int = DEFAULT_TEACHER_ID) -> Dict[str, Any]:
    """Persist one lesson-plan run. `rec` is the full client record; promoted
    fields are read from it for listing/sorting. Returns {id, created_at}."""
    init_plans_table()
    created_at = datetime.utcnow().isoformat()
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        "INSERT INTO plans (teacher_id, lang, title, subject, form, topic, score, data_source, constraints, tools, payload, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            teacher_id,
            rec.get("lang"),
            rec.get("title"),
            rec.get("subject"),
            rec.get("form"),
            rec.get("topic"),
            rec.get("score"),
            rec.get("dataSource") or rec.get("data_source"),
            json.dumps(rec.get("constraintLabels") or []),
            json.dumps(rec.get("tools") or []),
            json.dumps(rec),
            created_at,
        ),
    )
    pid = cur.lastrowid
    c.commit()
    c.close()
    return {"id": pid, "created_at": created_at}


def list_plans(teacher_id: int = DEFAULT_TEACHER_ID, limit: int = 50) -> list:
    """Light list for the Recent-plans panel (no heavy payload)."""
    init_plans_table()
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        "SELECT id, teacher_id, lang, title, subject, form, topic, score, data_source, constraints, tools, created_at "
        "FROM plans WHERE teacher_id = ? ORDER BY created_at DESC LIMIT ?",
        (teacher_id, limit),
    )
    rows = cur.fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("constraints", "tools"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except Exception:
                d[k] = []
        out.append(d)
    return out


def get_plan(plan_id: int) -> Optional[Dict[str, Any]]:
    """Full record including the parsed `payload` for round-trip restore."""
    init_plans_table()
    c = get_conn()
    cur = c.cursor()
    cur.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
    row = cur.fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    if d.get("payload"):
        try:
            d["payload"] = json.loads(d["payload"])
        except Exception:
            pass
    return d


def delete_plan(plan_id: int) -> bool:
    init_plans_table()
    c = get_conn()
    cur = c.cursor()
    cur.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    deleted = cur.rowcount > 0
    c.commit()
    c.close()
    return deleted


# --------------------------------------------------------------------------- #
# plan_feedback — Level 4 reflective memory.
#
# After a teacher actually teaches a plan, they can mark how it went: a simple
# rating, which suggested tools worked / flopped, and a free note. One row per
# plan (upsert). This feedback feeds the Pedagogy Architect ONLY (never the
# Analyst) via reflection_digest(): tools the teacher rated "worked" are
# promoted in future designs, flops are downranked.

def init_feedback_table() -> None:
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_feedback (
            plan_id INTEGER PRIMARY KEY,
            teacher_id INTEGER DEFAULT 1,
            rating INTEGER,
            tools_worked TEXT,
            tools_flopped TEXT,
            notes TEXT,
            taught_on TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feedback_teacher ON plan_feedback(teacher_id, updated_at)")
    c.commit()
    c.close()


def upsert_feedback(plan_id: int, teacher_id: int, rating: Optional[int],
                    tools_worked: List[str], tools_flopped: List[str],
                    notes: str = "", taught_on: str = "") -> Dict[str, Any]:
    """Insert or update the single feedback row for a plan."""
    init_feedback_table()
    now = datetime.utcnow().isoformat()
    c = get_conn()
    cur = c.cursor()
    cur.execute("SELECT created_at FROM plan_feedback WHERE plan_id = ?", (plan_id,))
    existing = cur.fetchone()
    created_at = (dict(existing).get("created_at") if existing else now) or now
    cur.execute(
        "INSERT INTO plan_feedback (plan_id, teacher_id, rating, tools_worked, tools_flopped, notes, taught_on, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(plan_id) DO UPDATE SET teacher_id=excluded.teacher_id, rating=excluded.rating, "
        "tools_worked=excluded.tools_worked, tools_flopped=excluded.tools_flopped, notes=excluded.notes, "
        "taught_on=excluded.taught_on, updated_at=excluded.updated_at",
        (plan_id, teacher_id, rating, json.dumps(tools_worked or []),
         json.dumps(tools_flopped or []), notes or "", taught_on or "", created_at, now),
    )
    c.commit()
    c.close()
    return {"plan_id": plan_id, "updated_at": now}


def get_feedback(plan_id: int) -> Optional[Dict[str, Any]]:
    init_feedback_table()
    c = get_conn()
    cur = c.cursor()
    cur.execute("SELECT * FROM plan_feedback WHERE plan_id = ?", (plan_id,))
    row = cur.fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    for k in ("tools_worked", "tools_flopped"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    return d


def list_feedback(teacher_id: int = DEFAULT_TEACHER_ID, limit: int = 100) -> list:
    """All feedback rows for a teacher, newest first (for the reflection digest)."""
    init_feedback_table()
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        "SELECT * FROM plan_feedback WHERE teacher_id = ? ORDER BY updated_at DESC LIMIT ?",
        (teacher_id, limit),
    )
    rows = cur.fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("tools_worked", "tools_flopped"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except Exception:
                d[k] = []
        out.append(d)
    return out


def reflection_digest(teacher_id: int = DEFAULT_TEACHER_ID, limit: int = 40) -> Dict[str, Any]:
    """Aggregate this teacher's feedback into tallies the Architect can act on:
    which tools they've marked as working vs. flopping, and how many lessons
    they've rated. Returns empty-ish structure when there's no feedback yet."""
    rows = list_feedback(teacher_id, limit=limit)
    worked: Dict[str, int] = {}
    flopped: Dict[str, int] = {}
    ratings: List[int] = []
    notes: List[str] = []
    for r in rows:
        for t in r.get("tools_worked") or []:
            worked[t] = worked.get(t, 0) + 1
        for t in r.get("tools_flopped") or []:
            flopped[t] = flopped.get(t, 0) + 1
        if r.get("rating") is not None:
            ratings.append(int(r["rating"]))
        if (r.get("notes") or "").strip():
            notes.append(r["notes"].strip())
    order = lambda d: [k for k, _ in sorted(d.items(), key=lambda kv: kv[1], reverse=True)]
    return {
        "count": len(rows),
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "tools_worked": order(worked),
        "tools_flopped": order(flopped),
        "recent_notes": notes[:3],
    }


def reflection_context(teacher_id: int = DEFAULT_TEACHER_ID) -> str:
    """Labelled prompt block for the Architect. Empty string until there's
    feedback to learn from."""
    d = reflection_digest(teacher_id)
    if not d["count"]:
        return ""
    lines = [
        "TEACHER REFLECTION (learned from how THIS teacher's past lessons actually went — "
        "prefer tools/strategies that worked for them, avoid the ones that flopped, unless "
        "THIS lesson or the constraints clearly call for otherwise):"
    ]
    if d["tools_worked"]:
        lines.append("- Worked well for this teacher: " + ", ".join(d["tools_worked"][:6]))
    if d["tools_flopped"]:
        lines.append("- Flopped for this teacher (avoid or adapt): " + ", ".join(d["tools_flopped"][:6]))
    if d["avg_rating"] is not None:
        lines.append(f"- Average self-rated success so far: {d['avg_rating']}/5 across {d['count']} lessons.")
    for n in d["recent_notes"]:
        lines.append(f"- Note from a past lesson: {n[:200]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# teacher_profile — Level 5 consolidated memory.
#
# L4 keeps a growing pile of per-lesson feedback rows. Feeding all of them to
# the Architect gets noisier the more a teacher uses the app. Consolidation
# compresses that raw history into ONE small, stable profile row per teacher:
# their go-to tools (reliably rated "worked"), tools to avoid (reliably
# flopped), the constraints that keep recurring across their lessons, and a
# short free-text summary. The Architect reads THIS clean summary instead of
# the raw digest once it exists. Re-run consolidate() to refresh it (cheap,
# pure-Python tallying — no model needed). Grounding, not bias: the current
# lesson + stated constraints still win.
# --------------------------------------------------------------------------- #

# how many times a tool must be tagged (net) before it's "reliable"
_CONSOLIDATE_MIN = 2

def init_profile_table() -> None:
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_profile (
            teacher_id INTEGER PRIMARY KEY,
            go_to_tools TEXT,
            avoid_tools TEXT,
            common_constraints TEXT,
            summary TEXT,
            lessons_seen INTEGER DEFAULT 0,
            avg_rating REAL,
            updated_at TEXT
        )
        """
    )
    c.commit()
    c.close()


def consolidate(teacher_id: int = DEFAULT_TEACHER_ID) -> Dict[str, Any]:
    """Compress this teacher's feedback + saved plans into one profile row.
    Idempotent: safe to call repeatedly; each call recomputes from scratch."""
    init_profile_table()
    rows = list_feedback(teacher_id, limit=500)

    worked: Dict[str, int] = {}
    flopped: Dict[str, int] = {}
    ratings: List[int] = []
    for r in rows:
        for t in r.get("tools_worked") or []:
            worked[t] = worked.get(t, 0) + 1
        for t in r.get("tools_flopped") or []:
            flopped[t] = flopped.get(t, 0) + 1
        if r.get("rating") is not None:
            ratings.append(int(r["rating"]))

    # net score per tool: worked minus flopped; classify by a stability threshold
    tools = set(worked) | set(flopped)
    go_to, avoid = [], []
    for t in tools:
        net = worked.get(t, 0) - flopped.get(t, 0)
        if net >= _CONSOLIDATE_MIN:
            go_to.append((t, net))
        elif net <= -_CONSOLIDATE_MIN:
            avoid.append((t, -net))
    go_to = [t for t, _ in sorted(go_to, key=lambda kv: kv[1], reverse=True)]
    avoid = [t for t, _ in sorted(avoid, key=lambda kv: kv[1], reverse=True)]

    # recurring constraints across this teacher's saved plans
    con_counts: Dict[str, int] = {}
    n_plans = 0
    for p in list_plans(teacher_id, limit=500):
        cons = p.get("constraints") or []
        if isinstance(cons, dict):
            cons = [k for k, v in cons.items() if v]
        if cons:
            n_plans += 1
        for k in cons:
            con_counts[k] = con_counts.get(k, 0) + 1
    # "recurring" = shows up in at least a third of plans (min 2)
    thresh = max(2, (n_plans + 2) // 3)
    common_con = [k for k, v in sorted(con_counts.items(), key=lambda kv: kv[1], reverse=True) if v >= thresh]

    avg = round(sum(ratings) / len(ratings), 2) if ratings else None
    bits = []
    if go_to:
        bits.append("relies on " + ", ".join(go_to[:3]))
    if avoid:
        bits.append("avoids " + ", ".join(avoid[:3]))
    if common_con:
        bits.append("usually teaches with: " + ", ".join(c.replace("_", " ") for c in common_con[:4]))
    if avg is not None:
        bits.append(f"avg self-rated success {avg}/5")
    summary = "; ".join(bits)

    now = datetime.utcnow().isoformat()
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        "INSERT INTO teacher_profile (teacher_id, go_to_tools, avoid_tools, common_constraints, summary, lessons_seen, avg_rating, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(teacher_id) DO UPDATE SET go_to_tools=excluded.go_to_tools, avoid_tools=excluded.avoid_tools, "
        "common_constraints=excluded.common_constraints, summary=excluded.summary, lessons_seen=excluded.lessons_seen, "
        "avg_rating=excluded.avg_rating, updated_at=excluded.updated_at",
        (teacher_id, json.dumps(go_to), json.dumps(avoid), json.dumps(common_con),
         summary, len(rows), avg, now),
    )
    c.commit()
    c.close()
    return get_profile(teacher_id)


def get_profile(teacher_id: int = DEFAULT_TEACHER_ID) -> Optional[Dict[str, Any]]:
    init_profile_table()
    c = get_conn()
    cur = c.cursor()
    cur.execute("SELECT * FROM teacher_profile WHERE teacher_id = ?", (teacher_id,))
    row = cur.fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    for k in ("go_to_tools", "avoid_tools", "common_constraints"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    return d


def profile_context(teacher_id: int = DEFAULT_TEACHER_ID) -> str:
    """Labelled prompt block from the CONSOLIDATED profile (Level 5). Preferred
    over reflection_context when a profile exists; empty string otherwise."""
    p = get_profile(teacher_id)
    if not p or not (p.get("go_to_tools") or p.get("avoid_tools") or p.get("common_constraints")):
        return ""
    lines = [
        "TEACHER PROFILE (a stable summary consolidated from this teacher's past lessons — "
        "lean on it to fit their proven habits, but the CURRENT lesson and stated constraints "
        "still take priority):"
    ]
    if p.get("go_to_tools"):
        lines.append("- Reliable go-to tools: " + ", ".join(p["go_to_tools"][:6]))
    if p.get("avoid_tools"):
        lines.append("- Consistently avoid: " + ", ".join(p["avoid_tools"][:6]))
    if p.get("common_constraints"):
        lines.append("- Recurring classroom constraints: " + ", ".join(k.replace("_", " ") for k in p["common_constraints"][:6]))
    if p.get("avg_rating") is not None:
        lines.append(f"- Typical self-rated success: {p['avg_rating']}/5 over {p['lessons_seen']} rated lessons.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Level 6 — proactive memory.
#
# L4 records feedback; L5 consolidates it into a stable profile. L6 turns that
# profile into a concrete *starting suggestion* the UI can offer BEFORE the
# teacher does anything: pre-tick the constraints they usually teach with, and
# name the tools they reliably reach for. It's a nudge, never an auto-apply —
# the teacher taps to accept and can always override. Empty until there's a
# consolidated profile worth suggesting from.
# --------------------------------------------------------------------------- #

# the app's constraint keys (mirror of the client toggles) — only suggest these
_CONSTRAINT_KEYS = {
    "no_internet", "limited_connectivity", "unstable_power",
    "mixed_ability", "large_class", "restricted_hardware",
}

def suggestion(teacher_id: int = DEFAULT_TEACHER_ID) -> Dict[str, Any]:
    """A ready-to-apply 'usual setup' derived from the consolidated profile.
    Returns {available, constraints, tools, lessons_seen}. `available` is False
    until the profile has enough signal to be worth offering."""
    p = get_profile(teacher_id)
    if not p:
        return {"available": False, "constraints": [], "tools": [], "lessons_seen": 0}
    constraints = [k for k in (p.get("common_constraints") or []) if k in _CONSTRAINT_KEYS]
    tools = list(p.get("go_to_tools") or [])[:4]
    # only worth a proactive nudge once the teacher has a couple of rated lessons
    available = bool((constraints or tools) and (p.get("lessons_seen") or 0) >= 2)
    return {
        "available": available,
        "constraints": constraints,
        "tools": tools,
        "lessons_seen": p.get("lessons_seen") or 0,
    }


# --------------------------------------------------------------------------- #
# teachers — lightweight local profiles for a SHARED device (no password).
# The app stays offline and single-device; a profile is just a name so several
# teachers can share one tablet and each keep their own history + memory.
# Row id=1 is the implicit default profile, auto-created on first use.
# --------------------------------------------------------------------------- #

def init_teachers_table() -> None:
    c = get_conn()
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT
        )
        """
    )
    # Ensure the default profile always exists.
    cur.execute("SELECT COUNT(*) FROM teachers WHERE id = 1")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO teachers (id, name, created_at) VALUES (1, ?, ?)",
            ("Teacher", datetime.utcnow().isoformat()),
        )
    c.commit()
    c.close()


def list_teachers() -> list:
    init_teachers_table()
    c = get_conn()
    cur = c.cursor()
    cur.execute("SELECT id, name, created_at FROM teachers ORDER BY id")
    rows = cur.fetchall()
    c.close()
    return [dict(r) for r in rows]


def insert_teacher(name: str) -> Dict[str, Any]:
    init_teachers_table()
    name = (name or "").strip() or "Teacher"
    created_at = datetime.utcnow().isoformat()
    c = get_conn()
    cur = c.cursor()
    cur.execute("INSERT INTO teachers (name, created_at) VALUES (?, ?)", (name, created_at))
    tid = cur.lastrowid
    c.commit()
    c.close()
    return {"id": tid, "name": name, "created_at": created_at}


def delete_teacher(teacher_id: int) -> bool:
    """Remove a profile and its plans. The default profile (id=1) is protected."""
    if int(teacher_id) == 1:
        return False
    init_teachers_table()
    c = get_conn()
    cur = c.cursor()
    cur.execute("DELETE FROM plans WHERE teacher_id = ?", (teacher_id,))
    cur.execute("DELETE FROM teachers WHERE id = ?", (teacher_id,))
    deleted = cur.rowcount > 0
    c.commit()
    c.close()
    return deleted

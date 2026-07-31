"""LangGraph orchestration for the Resilient EdTech pipeline.

Drop this file in at app/graph.py. It wraps the EXISTING agents
(analyst.analyse, pedagogy_architect.design) as graph nodes and adds:

  * an explicit check -> rebuild -> grade flow,
  * a conditional retry edge (weak plan loops back to rebuild, capped),
  * SQLite checkpointing so a run resumes after a crash / power cut.

Nothing about the model or the offline guarantee changes. LangGraph is a
local library; it only calls the functions you give it. The rule-based
fallback still lives INSIDE each agent, so "never fails" still holds.

Enable from main.py behind the USE_LANGGRAPH flag (see README-graph.md).
"""
from __future__ import annotations

import os
import time
from typing import List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from .agents import analyst, pedagogy_architect
from .schemas import (
    AnalystRequest,
    AnalystResult,
    DesignRequest,
    DesignResult,
)

# How good the (re-graded) plan must score before we stop, and how many
# rebuild attempts we allow before accepting whatever we have.
QUALITY_THRESHOLD = int(os.getenv("PLAN_QUALITY_THRESHOLD", "70"))
MAX_ATTEMPTS = int(os.getenv("PLAN_MAX_ATTEMPTS", "2"))


class PlanState(TypedDict, total=False):
    # ---- inputs ----
    lesson_text: str
    subject: Optional[str]
    form: Optional[str]
    topic: Optional[str]
    constraints: List[str]
    lang: str
    teacher_id: Optional[int]
    # ---- produced along the way ----
    analysis: AnalystResult
    result: DesignResult      # the full DesignResult (plan + tiers)
    score: int                # latest alignment score used for grading
    attempts: int
    quality_ok: bool


# --------------------------------------------------------------------------- #
# Nodes — thin wrappers around the existing agents (agents are unchanged).
# --------------------------------------------------------------------------- #

def check_node(s: PlanState) -> dict:
    """Curriculum Checker — score the incoming lesson against DSKP."""
    req = AnalystRequest(
        lesson_text=s["lesson_text"],
        subject=s.get("subject"),
        form=s.get("form"),
        topic=s.get("topic"),
        lang=s.get("lang", "en"),
    )
    analysis = analyst.analyse(req)
    return {"analysis": analysis, "score": analysis.overall_alignment_score}


def rebuild_node(s: PlanState) -> dict:
    """Lesson Rebuilder — redesign around constraints, feeding the findings."""
    req = DesignRequest(
        lesson_text=s["lesson_text"],
        constraints=s.get("constraints", []),
        subject=s.get("subject"),
        form=s.get("form"),
        topic=s.get("topic"),
        analyst_summary=s["analysis"].summary if s.get("analysis") else None,
        teacher_id=s.get("teacher_id"),
        lang=s.get("lang", "en"),
    )
    result = pedagogy_architect.design(req)
    return {"result": result, "attempts": s.get("attempts", 0) + 1}


def _plan_to_text(result: DesignResult) -> str:
    """Flatten the revised plan into text so the Checker can re-grade it."""
    p = result.revised_plan
    parts: List[str] = []
    for attr in ("title", "topic", "assessment", "alignment_note"):
        v = getattr(p, attr, None)
        if v:
            parts.append(str(v))
    for attr in ("objectives", "success_criteria", "materials", "recommended_tools"):
        v = getattr(p, attr, None) or []
        parts.extend(str(x) for x in v)
    for ph in getattr(p, "phases", None) or []:
        # phases may be dicts or models
        act = ph.get("activity") if isinstance(ph, dict) else getattr(ph, "activity", "")
        if act:
            parts.append(str(act))
    return "\n".join(parts)


def grade_node(s: PlanState) -> dict:
    """Re-score the REBUILT plan; pass if good enough or attempts exhausted."""
    attempts = s.get("attempts", 0)
    try:
        req = AnalystRequest(
            lesson_text=_plan_to_text(s["result"]),
            subject=s.get("subject"), form=s.get("form"), topic=s.get("topic"),
            lang=s.get("lang", "en"),
        )
        score = analyst.analyse(req).overall_alignment_score
    except Exception:  # noqa: BLE001 — grading must never break the pipeline
        score = s.get("score", QUALITY_THRESHOLD)
    ok = score >= QUALITY_THRESHOLD or attempts >= MAX_ATTEMPTS
    return {"score": score, "quality_ok": ok}


def route_after_grade(s: PlanState) -> str:
    return END if s.get("quality_ok") else "rebuild"


# --------------------------------------------------------------------------- #
# Graph assembly.
# --------------------------------------------------------------------------- #

def build_graph(checkpointer=None):
    g = StateGraph(PlanState)
    g.add_node("check", check_node)
    g.add_node("rebuild", rebuild_node)
    g.add_node("grade", grade_node)
    g.set_entry_point("check")
    g.add_edge("check", "rebuild")
    g.add_edge("rebuild", "grade")
    g.add_conditional_edges("grade", route_after_grade, {"rebuild": "rebuild", END: END})
    return g.compile(checkpointer=checkpointer)


# Build once at import. Checkpointing is best-effort: if the sqlite saver
# isn't available we still run (just without resume-after-crash).
_checkpointer = None
try:
    from langgraph.checkpoint.sqlite import SqliteSaver

    _DB = os.getenv("GRAPH_DB", "graph_state.db")
    _checkpointer = SqliteSaver.from_conn_string(_DB)
except Exception:  # noqa: BLE001
    _checkpointer = None

GRAPH = build_graph(_checkpointer)


def run_design(req: DesignRequest, teacher_id: Optional[int] = None) -> DesignResult:
    """Entry point for main.py — same in/out contract as pedagogy_architect.design.

    Runs check -> rebuild -> (grade -> maybe retry) and returns the DesignResult.
    """
    state: PlanState = {
        "lesson_text": req.lesson_text,
        "constraints": list(req.constraints or []),
        "subject": req.subject,
        "form": req.form,
        "topic": req.topic,
        "lang": getattr(req, "lang", "en") or "en",
        "teacher_id": teacher_id if teacher_id is not None else getattr(req, "teacher_id", None),
        "attempts": 0,
    }
    cfg = {"configurable": {"thread_id": f"plan-{state['teacher_id']}-{int(time.time()*1000)}"}}
    out = GRAPH.invoke(state, cfg)
    return out["result"]

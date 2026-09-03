"""The Critic — a senior-teacher agent that argues with the Architect.

Why this exists
---------------
The base pipeline is one-shot: the Curriculum Checker scores the lesson, the
Pedagogy Architect rebuilds it once, and the teacher sees a first draft. Nobody
stress-tests the Architect's work.

This module adds a second voice. The Critic reads the rebuilt plan the way a
strict senior teacher would — checking it against the constraints the teacher
actually declared, not against theory — and raises concrete objections
("assumes 30 min of device time but only one tablet was declared"). The
Architect then revises to answer them. Two rounds by default.

Design rules
------------
* **Never blocks.** No model, a bad JSON reply, or any exception → the original
  plan passes through untouched. The teacher always gets a plan.
* **Objections must be specific and actionable.** A vague "could be better" is
  filtered out; each objection names the problem and hints at the fix.
* **Only material objections trigger a revision.** If the Critic finds nothing
  serious, we stop early and save the model call (matters a lot on a 3B).
* **The transcript is kept** so the debate can be shown in the UI or a viva —
  it's the clearest evidence of genuine agent-to-agent reasoning in the system.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from ..llm import structured_call
from ..schemas import DesignRequest, DesignResult, RevisedLessonPlan
from .auditor import _CONSTRAINT_KEYS, _tools_digest
from .pedagogy_architect import _PLAN_PROPS

# How many critique→revise rounds to run at most. Each round is ~2 model calls,
# so on a 3B model this is the main cost knob.
MAX_ROUNDS = int(os.getenv("CRITIC_ROUNDS", "2"))

# Objections at or above this severity justify a revision.
_MATERIAL = {"high", "medium"}


def _constraint_digest(constraints: list, tools: dict) -> str:
    """Spell out each declared constraint plus the playbook's workaround, so the
    Critic judges against what the teacher really has (not generic advice)."""
    strategies = tools.get("constraint_strategies", {})
    if not constraints:
        return "  - none declared"
    lines = []
    for c in constraints:
        key = _CONSTRAINT_KEYS.get(str(c).strip().lower())
        hint = ""
        if key and key in strategies:
            opts = strategies[key]
            if opts:
                hint = f"  (usual workaround: {opts[0]})"
        lines.append(f"  - {c}{hint}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Round 1 — the Critic raises objections.
# --------------------------------------------------------------------------- #

_CRITIQUE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string"},  # "approve" | "revise"
        "objections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "issue": {"type": "string"},
                    "severity": {"type": "string"},   # high | medium | low
                    "fix_hint": {"type": "string"},
                },
                "required": ["issue", "severity", "fix_hint"],
            },
        },
    },
    "required": ["verdict", "objections"],
}

_CRITIC_SYSTEM = (
    "You are 'The Critic' — a strict, experienced senior teacher reviewing a colleague's "
    "lesson plan before it is taught in a RURAL, LOW-RESOURCE Malaysian classroom. "
    "Your job is to find what will actually FAIL in the room, not to praise. "
    "Judge the plan ONLY against the constraints and curriculum given to you.\n\n"
    "Look hard for these failure modes:\n"
    "1. CONSTRAINT VIOLATIONS — an activity that quietly needs internet, more devices, "
    "more power, or more time than the teacher declared having.\n"
    "2. TIMING that does not add up — phase durations exceeding the lesson length, or a "
    "task far too ambitious for its slot.\n"
    "3. WEAK DIFFERENTIATION — tiers that are the same task reworded rather than genuinely "
    "easier/harder work.\n"
    "4. MISSING ASSESSMENT — no way for the teacher to know if students actually learned it.\n"
    "5. CURRICULUM DRIFT — activities that no longer serve the stated learning standards.\n"
    "6. UNAVAILABLE RESOURCES — materials a rural school plausibly will not have.\n\n"
    "Rules: every objection must be SPECIFIC and point at something in this plan — never "
    "generic advice. Rate severity 'high' (the lesson breaks), 'medium' (noticeably weaker), "
    "or 'low' (polish). Give a concrete fix_hint the author can act on. "
    "If the plan genuinely holds up, return verdict 'approve' with an empty objections list — "
    "do not invent problems."
)


def _plan_digest(plan: RevisedLessonPlan) -> str:
    """Render the plan compactly so a small model can actually reason over it."""
    lines = [
        f"TITLE: {plan.title}",
        f"DURATION: {plan.duration}",
        "OBJECTIVES:",
    ]
    lines += [f"  - {o}" for o in (plan.objectives or [])]
    lines.append("SUCCESS CRITERIA:")
    lines += [f"  - {s}" for s in (plan.success_criteria or [])]
    lines.append(f"TOOLS: {', '.join(plan.recommended_tools or []) or 'none'}")
    lines.append("PHASES:")
    for ph in plan.phases or []:
        d = ph if isinstance(ph, dict) else ph.__dict__
        lines.append(
            f"  - [{d.get('phase', '?')} · {d.get('duration', '?')}] "
            f"{d.get('activity', '')} | tech: {d.get('technology', '')}"
        )
    lines.append(f"ASSESSMENT: {plan.assessment}")
    lines.append(f"MATERIALS: {', '.join(plan.materials or []) or 'none'}")
    lines.append(f"ALIGNMENT NOTE: {plan.alignment_note}")
    return "\n".join(lines)


def _diff_digest(result: DesignResult) -> str:
    d = result.differentiation
    if not d or not d.tiers:
        return "DIFFERENTIATION: none provided"
    out = ["DIFFERENTIATION TIERS:"]
    for t in d.tiers:
        items = "; ".join(t.items or [])
        out.append(f"  - {t.tier} ({t.tp}): {items}")
    return "\n".join(out)


def critique(result: DesignResult, req: DesignRequest, tools: dict) -> dict:
    """Ask the Critic for objections. Returns {} when unavailable."""
    user = (
        f"CLASSROOM CONSTRAINTS THE TEACHER DECLARED:\n{_constraint_digest(req.constraints, tools)}\n\n"
        f"LESSON PLAN UNDER REVIEW:\n{_plan_digest(result.revised_plan)}\n\n"
        f"{_diff_digest(result)}\n\n"
        "Review this plan. Where will it fail in that classroom?"
    )
    try:
        data = structured_call(
            _CRITIC_SYSTEM, user, _CRITIQUE_SCHEMA,
            max_tokens=1200, lang=getattr(req, "lang", "en"),
        )
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    # Keep only objections that actually say something.
    objs = []
    for o in data.get("objections") or []:
        issue = (o.get("issue") or "").strip()
        if len(issue) < 12:          # too vague to act on
            continue
        objs.append({
            "issue": issue,
            "severity": (o.get("severity") or "low").strip().lower(),
            "fix_hint": (o.get("fix_hint") or "").strip(),
        })
    return {"verdict": (data.get("verdict") or "").strip().lower(), "objections": objs}


# --------------------------------------------------------------------------- #
# Round 2 — the Architect answers the objections.
# --------------------------------------------------------------------------- #

_REVISE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": dict(_PLAN_PROPS),
    "required": [
        "title", "objectives", "success_criteria", "recommended_tools",
        "constraint_solutions", "phases", "assessment", "materials", "alignment_note",
    ],
}

_REVISE_SYSTEM = (
    "You are 'The Pedagogy Architect'. A senior colleague has reviewed your lesson plan and "
    "raised objections. Revise the plan so every objection is genuinely ANSWERED — do not "
    "merely reword it.\n\n"
    "Hold these fixed: the curriculum intent, the lesson's subject/topic/duration, and the "
    "teacher's declared constraints. Change activities, tools, timings, assessment or "
    "materials as needed to fix the problems. Keep everything offline-capable. "
    "Return the COMPLETE revised plan, not a diff."
)


def _revise(result: DesignResult, req: DesignRequest, tools: dict, objections: list) -> Optional[dict]:
    obj_text = "\n".join(
        f"  {i + 1}. [{o['severity'].upper()}] {o['issue']}\n     Suggested fix: {o['fix_hint']}"
        for i, o in enumerate(objections)
    )
    user = (
        f"CLASSROOM CONSTRAINTS:\n{_constraint_digest(req.constraints, tools)}\n\n"
        f"OFFLINE-CAPABLE TOOLS AVAILABLE:\n{_tools_digest(tools)}\n\n"
        f"YOUR CURRENT PLAN:\n{_plan_digest(result.revised_plan)}\n\n"
        f"OBJECTIONS RAISED BY THE REVIEWER:\n{obj_text}\n\n"
        "Return the full revised plan that answers every objection above."
    )
    try:
        return structured_call(
            _REVISE_SYSTEM, user, _REVISE_SCHEMA,
            max_tokens=3000, lang=getattr(req, "lang", "en"),
        )
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# The debate loop.
# --------------------------------------------------------------------------- #

def debate(result: DesignResult, req: DesignRequest, tools: dict,
           rounds: int = MAX_ROUNDS) -> tuple[DesignResult, list]:
    """Run critique→revise up to ``rounds`` times.

    Returns ``(possibly_improved_result, transcript)``. The transcript is a list
    of ``{round, objections, revised}`` entries for display/audit. On any
    failure the ORIGINAL result is returned unchanged — this never blocks.
    """
    transcript: list[dict[str, Any]] = []
    current = result

    for n in range(1, max(1, rounds) + 1):
        c = critique(current, req, tools)
        objs = c.get("objections") or []
        material = [o for o in objs if o["severity"] in _MATERIAL]

        # Nothing worth changing — stop early and save the model call.
        if not material:
            transcript.append({"round": n, "objections": objs, "revised": False,
                               "verdict": c.get("verdict") or "approve"})
            break

        revised = _revise(current, req, tools, material)
        if not revised:
            transcript.append({"round": n, "objections": objs, "revised": False,
                               "verdict": "revise-failed"})
            break

        try:
            # Preserve fields the revision schema doesn't carry.
            merged = current.revised_plan.model_dump()
            merged.update({k: v for k, v in revised.items() if v})
            new_plan = RevisedLessonPlan(**merged)
        except Exception:  # noqa: BLE001
            transcript.append({"round": n, "objections": objs, "revised": False,
                               "verdict": "merge-failed"})
            break

        current = current.model_copy(update={"revised_plan": new_plan})
        transcript.append({"round": n, "objections": objs, "revised": True,
                           "verdict": "revise"})

    return current, transcript

"""Merged Agent — The Pedagogy Architect (Auditor + Differentiation Strategist).

This consolidates two former roles into ONE model call:

  * The Auditor — redesigns the lesson around the school's constraints while
    keeping meaningful, offline-capable technology and curriculum alignment.
  * The Differentiation Strategist — splits the hands-on / formative step into
    three KSSR readiness tiers (Remedial TP1–2, Core TP3–4, Enrichment TP5–6).

Why merge: differentiation operates on the very plan the Auditor produces, so
doing both in one structured call removes a whole model round-trip — a real win
when running offline on a local 3B model.

Resilience: the call degrades in *parts*. If the model returns a solid plan but
the tiers are missing or thin, we keep the model's plan and synthesise the
tiers from the differentiation_scaffolds playbook (and vice-versa). Total
failure falls back to the fully rule-based design. ``DesignResult`` reports the
source of each part (``plan_source`` / ``differentiation_source``).

The UI can still present four named helpers in the rail — presentation roles are
decoupled from execution agents. This module just serves the Auditor +
Differentiation sections from a single endpoint (/api/design).
"""
from __future__ import annotations

from typing import Optional

from ..config import load_tech_tools, load_diff_scaffolds
from ..llm import structured_call, powered_by_label
from ..schemas import (
    DesignRequest,
    DesignResult,
    Differentiation,
    DifferentiationTier,
    RevisedLessonPlan,
)
from .auditor import _CONSTRAINT_KEYS, _tools_digest

# --------------------------------------------------------------------------- #
# Combined JSON schema: the full revised plan + a differentiation block.
# --------------------------------------------------------------------------- #

_PLAN_PROPS = {
    "title": {"type": "string"},
    "subject": {"type": "string"},
    "form": {"type": "string"},
    "topic": {"type": "string"},
    "duration": {"type": "string"},
    "objectives": {"type": "array", "items": {"type": "string"}},
    "success_criteria": {"type": "array", "items": {"type": "string"}},
    "recommended_tools": {"type": "array", "items": {"type": "string"}},
    "constraint_solutions": {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "constraint": {"type": "string"},
                "strategy": {"type": "string"},
            },
            "required": ["constraint", "strategy"],
        },
    },
    "phases": {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "phase": {"type": "string"},
                "duration": {"type": "string"},
                "activity": {"type": "string"},
                "technology": {"type": "string"},
            },
            "required": ["phase", "duration", "activity", "technology"],
        },
    },
    "assessment": {"type": "string"},
    "materials": {"type": "array", "items": {"type": "string"}},
    "alignment_note": {"type": "string"},
}

_DIFF_PROPS = {
    "intro": {"type": "string"},
    "note": {"type": "string"},
    "tiers": {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tier": {"type": "string"},
                "malay": {"type": "string"},
                "tp": {"type": "string"},
                "items": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["tier", "tp", "items"],
        },
    },
}

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **_PLAN_PROPS,
        "differentiation": {
            "type": "object",
            "additionalProperties": False,
            "properties": _DIFF_PROPS,
            "required": ["intro", "tiers"],
        },
    },
    "required": [
        "title", "objectives", "success_criteria", "recommended_tools",
        "constraint_solutions", "phases", "assessment", "materials",
        "alignment_note", "differentiation",
    ],
}

_SYSTEM = (
    "You are 'The Pedagogy Architect', combining two skills for rural-school teachers. "
    "FIRST, as a resourceful instructional-technology coach, redesign the lesson so it "
    "STILL integrates technology meaningfully but works entirely within the school's stated "
    "constraints (e.g. no internet, one device, one screen, no electricity). Favour free, "
    "low-bandwidth, offline-capable tools (Plickers, PhET offline, Kolibri, Quizizz Paper "
    "Mode, projected simulations, USB-served media); never assume resources the teacher said "
    "they lack. Keep alignment to DSKP, scheme of work and textbook, with phased activities "
    "(Set Induction, Development, Closure) and a concrete strategy per constraint. "
    "SECOND, as an inclusive-education specialist, take the hands-on and formative steps you "
    "just designed and split them into THREE readiness tiers mapped to KSSR performance "
    "levels: Remedial (TP1-2, e.g. visual vocabulary matching boards for tactile learners), "
    "Core (TP3-4, the baseline activity), and Enrichment (TP5-6, e.g. students act as peer-"
    "mentors or formulate alternative descriptors). Every tier must work under the SAME "
    "constraints — no extra devices or internet. Use the provided tool and scaffold "
    "references. Reply with ONLY a JSON object matching the schema."
)


def _scaffold_digest(scaffolds: dict) -> str:
    lv = scaffolds["performance_levels"]
    lines = []
    for key in ("remedial", "core", "enrichment"):
        meta = lv[key]
        moves = "; ".join(scaffolds["scaffolds"][key])
        lines.append(f"- {meta['label']} ({meta['malay']}, {meta['tp']}): {moves}")
    return "\n".join(lines)


def design(req: DesignRequest) -> DesignResult:
    """One call → revised plan + differentiation tiers (with partial fallback)."""
    tools = load_tech_tools()
    scaffolds = load_diff_scaffolds()
    user = (
        f"TECHNOLOGY TOOLS AVAILABLE:\n{_tools_digest(tools)}\n\n"
        f"DIFFERENTIATION SCAFFOLDS (KSSR performance levels):\n{_scaffold_digest(scaffolds)}\n\n"
        f"LESSON METADATA: subject={req.subject or 'unknown'}, "
        f"form={req.form or 'unknown'}, topic={req.topic or 'unknown'}\n"
        f"ANALYST SUMMARY: {(req.analyst_summary or 'n/a')[:400]}\n\n"
        f"CONSTRAINTS FACED: {', '.join(req.constraints) or 'none specified'}\n\n"
        f"ORIGINAL LESSON PLAN:\n{req.lesson_text[:2500]}\n\n"
        "Produce a revised, printable, constraint-proof lesson plan AND split its hands-on / "
        "formative step into Remedial, Core and Enrichment tiers."
    )

    data = structured_call(_SYSTEM, user, _SCHEMA, max_tokens=3800)

    plan: Optional[RevisedLessonPlan] = None
    diff: Optional[Differentiation] = None
    label = powered_by_label()

    if data is not None:
        # Try to salvage the plan independently of the tiers.
        try:
            plan_data = {k: v for k, v in data.items() if k != "differentiation"}
            cand = RevisedLessonPlan(**plan_data)
            if cand.title.strip() and cand.phases and cand.objectives:
                plan = cand
        except Exception:  # noqa: BLE001
            plan = None
        # Try the differentiation block independently.
        try:
            dblock = data.get("differentiation") or {}
            cand_d = Differentiation(**dblock)
            if cand_d.tiers and len(cand_d.tiers) >= 2:
                diff = cand_d
        except Exception:  # noqa: BLE001
            diff = None

    plan_source = "model" if plan is not None else "rule-based"
    diff_source = "model" if diff is not None else "rule-based"

    if plan is None:
        plan = _fallback_plan(req, tools)
    if diff is None:
        diff = _fallback_diff(scaffolds)

    powered_by = label if (plan_source == "model" or diff_source == "model") else "rule-based"
    return DesignResult(
        revised_plan=plan,
        differentiation=diff,
        powered_by=powered_by,
        plan_source=plan_source,
        differentiation_source=diff_source,
    )


# --------------------------------------------------------------------------- #
# Rule-based fallbacks (no model).
# --------------------------------------------------------------------------- #

def _fallback_plan(req: DesignRequest, tools: dict) -> RevisedLessonPlan:
    strategies = tools["constraint_strategies"]
    solutions = []
    chosen_tools: list[str] = []
    keys_hit: set[str] = set()
    for c in req.constraints:
        key = _CONSTRAINT_KEYS.get(c.strip().lower())
        if key and key in strategies:
            keys_hit.add(key)
            solutions.append({"constraint": c, "strategy": strategies[key][0]})
        else:
            solutions.append({"constraint": c, "strategy": "Use offline-first, low-bandwidth activities and projected whole-class demos."})

    constraint_blob = " ".join(req.constraints).lower()
    for tool in tools["tools"]:
        if any(bf.lower() in constraint_blob or _CONSTRAINT_KEYS.get(bf.lower(), "") in keys_hit
               for bf in tool.get("best_for", [])):
            chosen_tools.append(tool["name"])
    if not chosen_tools:
        chosen_tools = ["Plickers", "PhET Simulations (offline)"]

    topic = req.topic or "the lesson topic"
    return RevisedLessonPlan(
        title=f"Tech-integrated lesson: {topic}",
        subject=req.subject or "",
        form=req.form or "",
        topic=req.topic or "",
        duration="60 min",
        objectives=[
            f"Students understand the key concepts of {topic}.",
            "Students engage with a technology-supported activity within school constraints.",
        ],
        success_criteria=[
            "Students can explain the main idea in their own words.",
            "Students complete the formative check correctly.",
        ],
        recommended_tools=chosen_tools[:4],
        constraint_solutions=solutions,
        phases=[
            {"phase": "Set Induction", "duration": "10 min",
             "activity": f"Hook the class with a projected image/question about {topic}.",
             "technology": "Single device + projector/TV showing pre-downloaded media (works offline)."},
            {"phase": "Development", "duration": "35 min",
             "activity": "Whole-class interactive demo, then group tasks rotating through the shared device.",
             "technology": f"{chosen_tools[0]} for an interactive, low-bandwidth activity."},
            {"phase": "Closure", "duration": "15 min",
             "activity": "Formative check using printed response cards scanned by the teacher device.",
             "technology": "Plickers / Quizizz Paper Mode — one camera scans the whole class, no student internet."},
        ],
        assessment="Plickers/paper-card exit poll: every student answers, teacher scans once, instant results.",
        materials=["Teacher device (phone/laptop)", "Projector or TV", "Printed response cards", "Pre-downloaded media on USB"],
        alignment_note="Activities preserve the original DSKP content & learning standards; only the delivery method is adapted to the constraints.",
    )


def _fallback_diff(scaffolds: dict) -> Differentiation:
    lv = scaffolds["performance_levels"]
    sc = scaffolds["scaffolds"]
    tiers = [
        DifferentiationTier(
            tier=lv[key]["label"], malay=lv[key]["malay"], tp=lv[key]["tp"], items=list(sc[key])
        )
        for key in ("remedial", "core", "enrichment")
    ]
    return Differentiation(
        intro=scaffolds.get("intro_template", ""),
        note=scaffolds.get("note", ""),
        tiers=tiers,
    )

"""Agent 2 — The Auditor.

Takes the lesson plan plus the technology constraints the school faces, and
produces a revised, printable lesson plan that keeps meaningful technology use
while working around every constraint — still aligned to DSKP / scheme / textbook.
"""
from __future__ import annotations

from ..config import load_tech_tools
from ..llm import structured_call, powered_by_label
from ..schemas import AuditorRequest, AuditorResult, RevisedLessonPlan

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
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
    },
    "required": [
        "title", "objectives", "success_criteria", "recommended_tools",
        "constraint_solutions", "phases", "assessment", "materials", "alignment_note",
    ],
}

_SYSTEM = (
    "You are 'The Auditor', a resourceful instructional technology coach for rural schools. "
    "Given a lesson plan and the real-world technology constraints a school faces (e.g. no "
    "internet, one device, one screen), you redesign the lesson so it STILL integrates "
    "technology meaningfully but works entirely within those constraints. Favour free, "
    "low-bandwidth, offline-capable tools (Plickers, PhET offline, Kolibri, Quizizz Paper "
    "Mode, projected simulations, USB-served media). Every suggested tool must be feasible "
    "under the stated constraints — never assume resources the teacher said they lack. Keep "
    "the lesson aligned to the DSKP, scheme of work and textbook. Produce a complete, "
    "printable plan with phased activities (Set Induction, Development, Closure), and for "
    "each constraint give a concrete strategy. Use the provided tool knowledge base. "
    "Reply with ONLY a JSON object."
)


def _tools_digest(tools: dict) -> str:
    """Compact tool list (name · internet need · devices · best-for) for the model."""
    lines = []
    for t in tools.get("tools", []):
        lines.append(
            f"- {t['name']} ({t['category']}): {t['what'][:140]} "
            f"| internet: {t.get('needs_internet', 'n/a')[:60]} "
            f"| best for: {', '.join(t.get('best_for', []))}"
        )
    return "\n".join(lines)


def audit(req: AuditorRequest) -> AuditorResult:
    tools = load_tech_tools()
    user = (
        f"TECHNOLOGY TOOLS AVAILABLE:\n{_tools_digest(tools)}\n\n"
        f"LESSON METADATA: subject={req.subject or 'unknown'}, "
        f"form={req.form or 'unknown'}, topic={req.topic or 'unknown'}\n"
        f"ANALYST SUMMARY: {(req.analyst_summary or 'n/a')[:400]}\n\n"
        f"CONSTRAINTS FACED: {', '.join(req.constraints) or 'none specified'}\n\n"
        f"ORIGINAL LESSON PLAN:\n{req.lesson_text[:2500]}\n\n"
        "Produce a revised, printable lesson plan that overcomes every constraint while "
        "keeping meaningful technology integration and curriculum alignment."
    )

    data = structured_call(_SYSTEM, user, _SCHEMA, max_tokens=3000)
    if data is not None:
        try:
            plan = RevisedLessonPlan(**data)
            # Quality guard: only trust the model if it produced a real plan.
            if plan.title.strip() and plan.phases and plan.objectives:
                return AuditorResult(revised_plan=plan, powered_by=powered_by_label())
        except Exception:  # noqa: BLE001 — model produced an off-shape object
            pass

    return _fallback(req)


# --------------------------------------------------------------------------- #
# Rule-based fallback (no model).
# --------------------------------------------------------------------------- #

_CONSTRAINT_KEYS = {
    "no internet": "no_internet",
    "no_internet": "no_internet",
    "limited connectivity": "limited_connectivity",
    "limited_connectivity": "limited_connectivity",
    "1 device": "one_device_only",
    "one device": "one_device_only",
    "one_device_only": "one_device_only",
    "1 screen": "one_screen",
    "one screen": "one_screen",
    "one_screen": "one_screen",
    "limited devices": "limited_devices",
    "limited_devices": "limited_devices",
    "no electricity": "no_electricity",
    "no power": "no_electricity",
    "no_electricity": "no_electricity",
    "unstable electricity": "unstable_power",
    "unstable power": "unstable_power",
    "unstable_power": "unstable_power",
    "mixed-ability class": "mixed_ability",
    "mixed ability class": "mixed_ability",
    "mixed ability": "mixed_ability",
    "mixed_ability": "mixed_ability",
    "large class size": "large_class",
    "large class": "large_class",
    "large_class": "large_class",
    "low-spec device": "restricted_hardware",
    "low spec device": "restricted_hardware",
    "limited hardware": "restricted_hardware",
    "restricted_hardware": "restricted_hardware",
}


def _fallback(req: AuditorRequest) -> AuditorResult:
    tools = load_tech_tools()
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

    # Pick tools whose 'best_for' overlaps the constraints faced.
    constraint_blob = " ".join(req.constraints).lower()
    for tool in tools["tools"]:
        if any(bf.lower() in constraint_blob or _CONSTRAINT_KEYS.get(bf.lower(), "") in keys_hit
               for bf in tool.get("best_for", [])):
            chosen_tools.append(tool["name"])
    if not chosen_tools:
        chosen_tools = ["Plickers", "PhET Simulations (offline)"]

    topic = req.topic or "the lesson topic"
    plan = RevisedLessonPlan(
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
            {
                "phase": "Set Induction",
                "duration": "10 min",
                "activity": f"Hook the class with a projected image/question about {topic}.",
                "technology": "Single device + projector/TV showing pre-downloaded media (works offline).",
            },
            {
                "phase": "Development",
                "duration": "35 min",
                "activity": "Whole-class interactive demo, then group tasks rotating through the shared device.",
                "technology": f"{chosen_tools[0]} for an interactive, low-bandwidth activity.",
            },
            {
                "phase": "Closure",
                "duration": "15 min",
                "activity": "Formative check using printed response cards scanned by the teacher device.",
                "technology": "Plickers / Quizizz Paper Mode — one camera scans the whole class, no student internet.",
            },
        ],
        assessment="Plickers/paper-card exit poll: every student answers, teacher scans once, instant results.",
        materials=["Teacher device (phone/laptop)", "Projector or TV", "Printed response cards", "Pre-downloaded media on USB"],
        alignment_note="Activities preserve the original DSKP content & learning standards; only the delivery method is adapted to the constraints.",
    )

    return AuditorResult(revised_plan=plan, powered_by="rule-based")

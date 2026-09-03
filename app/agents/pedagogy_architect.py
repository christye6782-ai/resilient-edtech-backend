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
    CurriculumSource,
    DesignRequest,
    DesignResult,
    Differentiation,
    DifferentiationTier,
    RevisedLessonPlan,
)
from .auditor import _CONSTRAINT_KEYS, _tools_digest

try:  # RAG is optional — the Architect works fine without it
    from .. import rag
except Exception:  # noqa: BLE001
    rag = None

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
    "kbat_level": {"type": "string"},
    "kbat": {"type": "array", "items": {"type": "string"}},
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
        "alignment_note", "kbat_level", "kbat", "differentiation",
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
    # Level 3: ground the redesign in the REAL DSKP passages for this lesson.
    _rag_block = ""
    _rag_sources: list = []
    if rag is not None:
        try:
            _rag_block = rag.curriculum_context(req.subject, req.form, req.topic, req.lesson_text)
            _rag_sources = rag.curriculum_sources(req.subject, req.form, req.topic, req.lesson_text)
        except Exception:  # noqa: BLE001
            _rag_block = ""
            _rag_sources = []
    # Level 3 (P2) lesson recall: retrieve THIS teacher's most similar past lessons
    # and fold them into the design context. Gated in rag.lesson_context() behind a
    # minimum saved-lesson count; returns "" (→ falls back to the Level-2 digest below)
    # until the teacher has enough history. Architect only — never the Analyst.
    _recall_block = ""
    if rag is not None and req.teacher_id is not None:
        try:
            _recall_query = " ".join(
                x for x in [req.subject, req.form, req.topic, (req.lesson_text or "")[:400]] if x
            ).strip()
            _recall_block = rag.lesson_context(_recall_query, req.teacher_id)
        except Exception:  # noqa: BLE001
            _recall_block = ""
    # Level 4/5: reflective memory — prefer the CONSOLIDATED profile (L5) when
    # one exists; fall back to the raw reflection digest (L4) otherwise. Both
    # fold in what this teacher marked as working / flopping so the redesign
    # promotes their successes and avoids their flops. Architect only.
    _reflection_block = ""
    if req.teacher_id is not None:
        try:
            from .. import db as _dbmod
            _reflection_block = _dbmod.profile_context(req.teacher_id) or _dbmod.reflection_context(req.teacher_id)
        except Exception:  # noqa: BLE001
            _reflection_block = ""
    user = (
        (_rag_block + "\n\n" if _rag_block else "")
        + f"TECHNOLOGY TOOLS AVAILABLE:\n{_tools_digest(tools)}\n\n"
        f"DIFFERENTIATION SCAFFOLDS (KSSR performance levels):\n{_scaffold_digest(scaffolds)}\n\n"
        f"LESSON METADATA (AUTHORITATIVE — copy these EXACTLY into subject/form/topic; "
        f"never substitute a subject or form you saw in the reference data above): "
        f"subject={req.subject or 'unknown'}, "
        f"form={req.form or 'unknown'}, topic={req.topic or 'unknown'}\n"
        f"ANALYST SUMMARY: {(req.analyst_summary or 'n/a')[:400]}\n\n"
        + (
            f"TEACHER CONTEXT (memory from this teacher's recent lessons — treat these as "
            f"PRIORS you may OVERRIDE whenever THIS lesson clearly differs; never let them "
            f"override the curriculum or the stated constraints):\n{req.teacher_context[:600]}\n\n"
            if req.teacher_context else ""
        )
        + (_recall_block + "\n\n" if _recall_block else "")
        + (_reflection_block + "\n\n" if _reflection_block else "")
        + f"CONSTRAINTS FACED: {', '.join(req.constraints) or 'none specified'}\n\n"
        f"ORIGINAL LESSON PLAN:\n{req.lesson_text[:2500]}\n\n"
        "Produce a revised, printable, constraint-proof lesson plan AND split its hands-on / "
        "formative step into Remedial (TP1-2), Core (TP3-4) and Enrichment (TP5-6) tiers using the "
        "differentiation scaffolds above. Write the assessment as a PBD judgement against the "
        "general KSSR Tahap Penguasaan bands for this subject and year. "
        "Also fill the KBAT (HOTS) element, which every Malaysian RPH requires: set 'kbat_level' "
        "to the Bloom's band this lesson targets, written bilingually (e.g. "
        "'Analysing & Evaluating / Menganalisis & Menilai'), and give 2-3 'kbat' questions the "
        "teacher can actually ask aloud. They must be open-ended and specific to THIS lesson's "
        "topic — never generic recall questions."
    )

    data = structured_call(_SYSTEM, user, _SCHEMA, max_tokens=3800, lang=getattr(req, "lang", "en"))

    plan: Optional[RevisedLessonPlan] = None
    diff: Optional[Differentiation] = None
    label = powered_by_label()

    if data is not None:
        # Try to salvage the plan independently of the tiers.
        try:
            plan_data = {k: v for k, v in data.items() if k != "differentiation"}
            # The TEACHER's metadata is authoritative. The model sometimes echoes a
            # subject/form it saw in the reference data (e.g. "Form 1" from a Sains
            # Tingkatan 1 band) instead of the lesson's own. Never let it override
            # what the teacher actually entered.
            if (req.subject or "").strip():
                plan_data["subject"] = req.subject.strip()
            if (req.form or "").strip():
                plan_data["form"] = req.form.strip()
            if (req.topic or "").strip():
                plan_data["topic"] = req.topic.strip()
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
        curriculum_sources=[CurriculumSource(**s) for s in _rag_sources],
    )


# --------------------------------------------------------------------------- #
# Rule-based fallbacks (no model).
# --------------------------------------------------------------------------- #

def _fallback_plan(req: DesignRequest, tools: dict) -> RevisedLessonPlan:
    strategies = tools["constraint_strategies"]
    ms = str(getattr(req, "lang", "en")).lower().startswith("ms")
    generic_strategy = (
        "Guna aktiviti utama-luar-talian, lebar jalur rendah dan demo seluruh kelas yang diprojekkan."
        if ms else
        "Use offline-first, low-bandwidth activities and projected whole-class demos."
    )
    solutions = []
    chosen_tools: list[str] = []
    keys_hit: set[str] = set()
    for c in req.constraints:
        key = _CONSTRAINT_KEYS.get(c.strip().lower())
        if key and key in strategies:
            keys_hit.add(key)
            solutions.append({"constraint": c, "strategy": strategies[key][0]})
        else:
            solutions.append({"constraint": c, "strategy": generic_strategy})

    constraint_blob = " ".join(req.constraints).lower()
    for tool in tools["tools"]:
        if any(bf.lower() in constraint_blob or _CONSTRAINT_KEYS.get(bf.lower(), "") in keys_hit
               for bf in tool.get("best_for", [])):
            chosen_tools.append(tool["name"])
    if not chosen_tools:
        chosen_tools = ["Plickers", "PhET Simulations (offline)"]

    if ms:
        topic = req.topic or "topik pelajaran"
        return RevisedLessonPlan(
            title=f"Pelajaran bersepadu teknologi: {topic}",
            subject=req.subject or "", form=req.form or "", topic=req.topic or "",
            duration="60 min",
            objectives=[
                f"Murid memahami konsep utama {topic}.",
                "Murid melibatkan diri dalam aktiviti disokong teknologi dalam kekangan sekolah.",
            ],
            success_criteria=[
                "Murid boleh menerangkan idea utama dengan perkataan sendiri.",
                "Murid melengkapkan semakan formatif dengan betul.",
            ],
            recommended_tools=chosen_tools[:4],
            constraint_solutions=solutions,
            phases=[
                {"phase": "Set Induksi", "duration": "10 min",
                 "activity": f"Tarik perhatian kelas dengan imej/soalan yang diprojekkan tentang {topic}.",
                 "technology": "Satu peranti + projektor/TV memaparkan media pra-muat turun (berfungsi luar talian)."},
                {"phase": "Perkembangan", "duration": "35 min",
                 "activity": "Demo interaktif seluruh kelas, kemudian tugasan kumpulan bergilir menggunakan peranti dikongsi.",
                 "technology": f"{chosen_tools[0]} untuk aktiviti interaktif berlebar-jalur-rendah."},
                {"phase": "Penutup", "duration": "15 min",
                 "activity": "Semakan formatif menggunakan kad respons bercetak yang diimbas oleh peranti guru.",
                 "technology": "Plickers / Mod Kertas Quizizz — satu kamera mengimbas seluruh kelas, tiada internet murid."},
            ],
            assessment="Undian keluar Plickers/kad kertas: setiap murid menjawab, guru mengimbas sekali, keputusan serta-merta.",
            materials=["Peranti guru (telefon/komputer riba)", "Projektor atau TV", "Kad respons bercetak", "Media pra-muat turun dalam USB"],
            alignment_note="Aktiviti mengekalkan Standard Kandungan & Standard Pembelajaran DSKP asal; hanya kaedah penyampaian disesuaikan dengan kekangan.",
            kbat_level="Menganalisis & Menilai / Analysing & Evaluating",
            kbat=[
                f"Mengapa {topic} penting dalam kehidupan seharian kamu? Berikan satu contoh sendiri.",
                f"Jika kamu perlu mengajar {topic} kepada rakan yang tidak hadir, bagaimana kamu menerangkannya?",
                f"Apakah satu cara lain untuk menyelesaikan tugasan {topic} ini, dan mana satu lebih baik? Mengapa?",
            ],
        )

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
        kbat_level="Analysing & Evaluating / Menganalisis & Menilai",
        kbat=[
            f"Why does {topic} matter in your own daily life? Give one example of your own.",
            f"If you had to teach {topic} to a friend who missed today's class, how would you explain it?",
            f"What is another way to approach this {topic} task, and which way is better? Why?",
        ],
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

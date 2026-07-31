"""Agent 1 — The Analyst.

Checks an uploaded lesson plan against the DSKP, the scheme of work, and the
textbook topics, and reports alignment, gaps and recommendations.
"""
from __future__ import annotations

from ..config import load_dskp
from ..llm import structured_call, powered_by_label
from ..schemas import AnalystRequest, AnalystResult

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "overall_alignment_score": {"type": "integer"},
        "alignments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "dimension": {"type": "string"},
                    "status": {"type": "string", "enum": ["aligned", "partial", "not_aligned"]},
                    "notes": {"type": "string"},
                },
                "required": ["dimension", "status", "notes"],
            },
        },
        "content_standards_detected": {"type": "array", "items": {"type": "string"}},
        "learning_standards_detected": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "summary", "overall_alignment_score", "alignments",
        "content_standards_detected", "learning_standards_detected",
        "gaps", "recommendations",
    ],
}

_SYSTEM = (
    "You are 'The Analyst', an expert on the Malaysian KSSM/KSSR curriculum (DSKP — "
    "Dokumen Standard Kurikulum dan Pentaksiran). You evaluate a teacher's lesson plan "
    "against three dimensions: (1) DSKP content & learning standards, (2) the scheme of "
    "work sequencing, and (3) alignment to the textbook chapter/topic. Be specific, "
    "constructive and encouraging — these are rural teachers doing their best with limited "
    "resources. Ground your judgement in the provided DSKP reference where relevant, but use "
    "your broader curriculum knowledge too. Always return the three dimensions DSKP, "
    "Scheme of Work and Textbook in 'alignments'. Reply with ONLY a JSON object."
)


def _dskp_digest(dskp: dict) -> str:
    """Compact, token-light view of the DSKP reference for the model's context."""
    lines = []
    for subj in dskp.get("subjects", []):
        for topic in subj.get("topics", []):
            cs = "; ".join(topic.get("content_standards", []))
            ls = "; ".join(topic.get("learning_standards", []))
            lines.append(
                f"- {subj['subject']} {subj.get('form', '')} | {topic['topic']} "
                f"({topic.get('textbook_chapter', '')}): standards [{cs}] learning [{ls}]"
            )
    return "\n".join(lines)


def analyse(req: AnalystRequest) -> AnalystResult:
    dskp = load_dskp()
    user = (
        f"DSKP REFERENCE (sample topics & standards):\n{_dskp_digest(dskp)}\n\n"
        f"LESSON METADATA: subject={req.subject or 'unknown'}, "
        f"form={req.form or 'unknown'}, topic={req.topic or 'unknown'}\n\n"
        f"TEACHER'S LESSON PLAN:\n{req.lesson_text[:3000]}\n\n"
        "Analyse alignment to DSKP, scheme of work and textbook. Identify the content/"
        "learning standards the lesson appears to address, list concrete gaps, and give "
        "actionable recommendations."
    )

    data = structured_call(_SYSTEM, user, _SCHEMA, lang=getattr(req, "lang", "en"))
    if data is not None:
        try:
            result = AnalystResult(**data)
            # Quality guard: the model sometimes returns valid-but-empty JSON.
            # Only trust it if it actually said something useful.
            if result.summary.strip() and (result.alignments or result.overall_alignment_score > 0):
                result.powered_by = powered_by_label()  # on-device
                return result
        except Exception:  # noqa: BLE001 — model produced an off-shape object
            pass

    return _fallback(req)


# --------------------------------------------------------------------------- #
# Rule-based fallback (no model) — keyword matching against the DSKP sample.
# --------------------------------------------------------------------------- #

def _fallback(req: AnalystRequest) -> AnalystResult:
    text = req.lesson_text.lower()
    dskp = load_dskp()

    matched_topic = None
    content_std: list[str] = []
    learning_std: list[str] = []
    for subj in dskp["subjects"]:
        if req.subject and req.subject.lower() not in subj["subject"].lower():
            continue
        for topic in subj["topics"]:
            tokens = [w for w in topic["topic"].lower().split() if len(w) > 3]
            if (req.topic and req.topic.lower() in topic["topic"].lower()) or any(t in text for t in tokens):
                matched_topic = topic["topic"]
                content_std = topic.get("content_standards", [])
                learning_std = topic.get("learning_standards", [])
                break
        if matched_topic:
            break

    has_objectives = any(k in text for k in ("objective", "objektif", "learning outcome"))
    has_assessment = any(k in text for k in ("assess", "pentaksiran", "evaluat", "quiz", "test"))
    has_activity = any(k in text for k in ("activity", "aktiviti", "task", "exercise", "group"))

    score = 30
    score += 25 if matched_topic else 0
    score += 15 if has_objectives else 0
    score += 15 if has_assessment else 0
    score += 15 if has_activity else 0
    score = min(score, 95)

    def status(ok: bool) -> str:
        return "aligned" if ok else "partial"

    ms = str(getattr(req, "lang", "en")).lower().startswith("ms")

    if ms:
        alignments = [
            {"dimension": "DSKP",
             "status": status(bool(matched_topic) and has_objectives),
             "notes": (f"Pelajaran ini nampaknya menangani topik '{matched_topic}'."
                       if matched_topic
                       else "Tidak dapat memetakan pelajaran ini kepada topik DSKP dengan yakin daripada rujukan sampel. "
                       "Tandakan subjek/tahun/topik untuk padanan yang lebih baik.")},
            {"dimension": "Rancangan Pengajaran Tahunan",
             "status": status(bool(matched_topic)),
             "notes": "Topik dikenali dalam rancangan pengajaran tahunan sampel."
             if matched_topic
             else "Topik tidak ditemui dalam rancangan sampel — sahkan urutan secara manual."},
            {"dimension": "Buku Teks",
             "status": status(bool(content_std)),
             "notes": "Kandungan dipetakan kepada bab buku teks yang diketahui."
             if content_std
             else "Tiada bab buku teks dipadankan secara automatik."},
        ]
        gaps = []
        if not has_objectives:
            gaps.append("Tiada objektif pembelajaran / kriteria kejayaan yang jelas dikesan.")
        if not has_assessment:
            gaps.append("Tiada pentaksiran atau semakan formatif dikesan.")
        if not has_activity:
            gaps.append("Sedikit sahaja aktiviti murid yang jelas dikesan.")
        if not matched_topic:
            gaps.append("Pelajaran tidak dapat dipetakan kepada Standard Kandungan DSKP tertentu.")
        recs = [
            "Nyatakan Standard Pembelajaran DSKP secara jelas (cth. format X.Y.Z) di bahagian atas rancangan.",
            "Tambah satu kriteria kejayaan yang boleh diukur bagi setiap objektif.",
        ]
        if not has_assessment:
            recs.append("Sertakan pentaksiran formatif ringkas (tiket keluar, kuiz, atau soal jawab).")
        summary = (
            "Analisis berasaskan peraturan (tiada model tersedia). "
            + (f"Pelajaran ini nampaknya berkaitan dengan '{matched_topic}'. " if matched_topic else "")
            + "Mulakan model atas peranti (ollama pull llama3.2:3b) untuk semakan yang lebih mendalam dan sedar-kurikulum — masih sepenuhnya luar talian."
        )
    else:
        alignments = [
            {"dimension": "DSKP",
             "status": status(bool(matched_topic) and has_objectives),
             "notes": (f"Lesson appears to address the topic '{matched_topic}'."
                       if matched_topic
                       else "Could not confidently map this lesson to a DSKP topic from the sample reference. "
                       "Tag the subject/form/topic to improve matching.")},
            {"dimension": "Scheme of Work",
             "status": status(bool(matched_topic)),
             "notes": "Topic recognised in the sample scheme of work."
             if matched_topic
             else "Topic not found in the sample scheme of work — verify sequencing manually."},
            {"dimension": "Textbook",
             "status": status(bool(content_std)),
             "notes": "Content maps to a known textbook chapter."
             if content_std
             else "No textbook chapter matched automatically."},
        ]
        gaps = []
        if not has_objectives:
            gaps.append("No clear learning objectives / success criteria detected.")
        if not has_assessment:
            gaps.append("No assessment or formative check detected.")
        if not has_activity:
            gaps.append("Few explicit student activities detected.")
        if not matched_topic:
            gaps.append("Lesson could not be mapped to a specific DSKP content standard.")
        recs = [
            "State explicit DSKP learning standards (e.g. format X.Y.Z) at the top of the plan.",
            "Add a measurable success criterion for each objective.",
        ]
        if not has_assessment:
            recs.append("Include a short formative assessment (exit ticket, quiz, or Q&A).")
        summary = (
            "Rule-based analysis (no model available). "
            + (f"This lesson looks related to '{matched_topic}'. " if matched_topic else "")
            + "Start the on-device model (ollama pull llama3.2:3b) for a deeper, curriculum-aware review — still fully offline."
        )

    return AnalystResult(
        summary=summary,
        overall_alignment_score=score,
        alignments=alignments,
        content_standards_detected=content_std,
        learning_standards_detected=learning_std,
        gaps=gaps,
        recommendations=recs,
        powered_by="rule-based",
    )

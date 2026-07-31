"""Agent 3 — FAQ.

Explains any terminology or tool that appears in the suggested lesson (e.g.
"What is Plickers?") and tells the teacher exactly how to execute it, with
low-resource notes and offline alternatives.
"""
from __future__ import annotations

from ..config import load_tech_tools
from ..llm import structured_call, powered_by_label
from ..schemas import FaqRequest, FaqResult

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "term": {"type": "string"},
        "explanation": {"type": "string"},
        "how_to_execute": {"type": "array", "items": {"type": "string"}},
        "low_resource_notes": {"type": "string"},
        "alternatives": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["term", "explanation", "how_to_execute", "low_resource_notes", "alternatives"],
}

_SYSTEM = (
    "You are the 'FAQ' agent, a friendly help desk for teachers in rural schools. A teacher "
    "asks about a term, tool or technique mentioned in their lesson (e.g. 'What is Plickers?'). "
    "Explain it in plain, jargon-free language, then give clear step-by-step instructions for "
    "using it in a low-resource classroom. Always state what internet/devices are needed and "
    "offer a no-tech or offline fallback. Use the provided tool knowledge base when the term "
    "matches; otherwise use your own knowledge. Keep it practical and encouraging. "
    "Reply with ONLY a JSON object."
)


def _relevant_tool_note(tools: dict, question: str) -> str:
    """If the question names a known tool, inject just that entry (keeps the
    prompt tiny for the model instead of dumping the whole knowledge base)."""
    q = question.lower()
    for t in tools.get("tools", []):
        if t["name"].lower() in q:
            steps = " ".join(t.get("how_to_use", []))
            return (
                f"REFERENCE — {t['name']} ({t['category']}): {t['what']} "
                f"Internet: {t.get('needs_internet', 'n/a')}. "
                f"Devices: {t.get('devices_required', 'n/a')}. "
                f"How: {steps} Offline alternative: {t.get('offline_alternative', 'n/a')}"
            )
    return "REFERENCE: (no matching tool in the knowledge base — use your own knowledge.)"


def answer(req: FaqRequest) -> FaqResult:
    tools = load_tech_tools()
    user = (
        f"{_relevant_tool_note(tools, req.question)}\n\n"
        f"LESSON CONTEXT (for grounding): {(req.context or 'n/a')[:600]}\n\n"
        f"TEACHER'S QUESTION: {req.question}\n\n"
        "Answer with an explanation, step-by-step execution guidance, low-resource notes "
        "and offline alternatives."
    )

    data = structured_call(_SYSTEM, user, _SCHEMA, max_tokens=1500)
    if data is not None:
        try:
            result = FaqResult(**data)
            # Quality guard: need a real explanation, not an empty shell.
            if len(result.explanation.strip()) > 20:
                result.powered_by = powered_by_label()  # cloud / on-device
                return result
        except Exception:  # noqa: BLE001 — model produced an off-shape object
            pass

    return _fallback(req)


def _fallback(req: FaqRequest) -> FaqResult:
    tools = load_tech_tools()
    q = req.question.lower()

    for tool in tools["tools"]:
        if tool["name"].lower() in q:
            return FaqResult(
                term=tool["name"],
                explanation=f"{tool['what']} ({tool['category']}).",
                how_to_execute=tool.get("how_to_use", []),
                low_resource_notes=(
                    f"Internet: {tool.get('needs_internet', 'n/a')} | "
                    f"Devices: {tool.get('devices_required', 'n/a')}"
                ),
                alternatives=[tool.get("offline_alternative", "Use a paper-based equivalent.")],
                powered_by="rule-based",
            )

    return FaqResult(
        term=req.question.strip()[:60] or "Term",
        explanation=(
            "No offline definition found for this term. Connect online or start Ollama "
            "(ollama pull llama3.2:3b) to get a full, context-aware explanation from the FAQ agent."
        ),
        how_to_execute=["Search the tool's official site while you have internet, then note the steps for offline use."],
        low_resource_notes="When unsure, prefer tools that need only one teacher device and no student internet.",
        alternatives=["A printed worksheet or hands-on manipulative usually achieves the same learning goal."],
        powered_by="rule-based",
    )

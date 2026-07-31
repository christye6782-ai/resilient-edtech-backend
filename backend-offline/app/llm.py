"""On-device LLM layer for the agents — Localized Offline Agentic AI.

Every agent calls :func:`structured_call` and gets a validated JSON object (or
``None``) back. There is NO cloud tier and NO network call — the only model is
Llama 3.2 3B running locally via Ollama, with a rule-based fallback.

    ENGINE_MODE = auto   →  on-device Llama (if reachable) → None (rule-based)
    ENGINE_MODE = local  →  on-device Llama → None (rule-based)
    ENGINE_MODE = basic  →  None  (skip the model entirely)

Returning ``None`` is the signal every agent already understands: "use your
rule-based fallback". So the app degrades gracefully — a school with no Ollama
(or the lowest-spec hardware) still gets a complete, if simpler, answer, fully
offline.

The mode is read from settings by default but can be flipped at runtime via
:func:`set_mode` (wired to POST /api/engine), so a teacher can force basic mode
from the UI without restarting the server.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
from typing import Any, Optional

from .config import settings

logger = logging.getLogger("resilient-edtech.llm")

_client = None  # singleton Ollama client

# Runtime override of settings.engine_mode (None = use the configured default).
_runtime_mode: Optional[str] = None

# Records which tier produced the most recent successful result, per-request.
_last_engine: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "last_engine", default=None
)

_VALID_MODES = {"auto", "local", "basic"}


# --------------------------------------------------------------------------- #
# Mode + label helpers
# --------------------------------------------------------------------------- #

def get_mode() -> str:
    """The active engine-selection mode (runtime override or configured default)."""
    return _runtime_mode or settings.engine_mode


def set_mode(mode: str) -> str:
    """Override the engine mode at runtime. Returns the mode now in effect."""
    global _runtime_mode
    mode = (mode or "").strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(_VALID_MODES)}")
    _runtime_mode = mode
    return get_mode()


def powered_by_label() -> str:
    """Human label for the tier that produced the current request's result.

    Agents set ``result.powered_by = powered_by_label()`` after a successful
    model call so the UI can show whether the answer came from the on-device
    model or the rule-based fallback.
    """
    eng = _last_engine.get()
    if eng == "local":
        return "Llama 3.2 3B (on-device)"
    return "rule-based"


# --------------------------------------------------------------------------- #
# Shared JSON helpers
# --------------------------------------------------------------------------- #

def _clean_schema(schema: Any) -> Any:
    """Drop keys llama.cpp's grammar converter doesn't need."""
    if isinstance(schema, dict):
        return {k: _clean_schema(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [_clean_schema(v) for v in schema]
    return schema


def _parse_json(text: str) -> Optional[dict]:
    """Best-effort JSON parse — models sometimes wrap JSON in prose or fences."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


# --------------------------------------------------------------------------- #
# On-device tier (Ollama)
# --------------------------------------------------------------------------- #

def _get_client():
    global _client
    if _client is None:
        from ollama import Client  # lazy import
        _client = Client(host=settings.ollama_host, timeout=settings.request_timeout)
    return _client


def _local_chat(system: str, user: str, schema: dict[str, Any], max_tokens: int) -> Optional[str]:
    client = _get_client()
    response = client.chat(
        model=settings.ollama_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        format=_clean_schema(schema),
        options={
            "temperature": settings.temperature,
            "num_ctx": settings.num_ctx,
            "num_predict": max_tokens,
        },
    )
    return (response.get("message") or {}).get("content", "")


def local_status() -> dict:
    """Quick reachability probe for the on-device Ollama model."""
    status = {
        "enabled": settings.llm_enabled,
        "host": settings.ollama_host,
        "model": settings.ollama_model,
        "reachable": False,
        "model_ready": False,
    }
    if not settings.llm_enabled:
        return status
    try:
        client = _get_client()
        tags = client.list()
        status["reachable"] = True
        models = [(m.get("model", "") or m.get("name", "") or "") for m in tags.get("models", [])]
        base = settings.ollama_model.split(":")[0].lower()
        status["model_ready"] = any(m.split(":")[0].lower() == base for m in models)
    except Exception as exc:  # noqa: BLE001
        logger.info("Ollama not reachable: %s", exc)
    return status


# Back-compat alias.
def llm_status() -> dict:
    return local_status()


def llm_available() -> bool:
    return settings.llm_enabled


# --------------------------------------------------------------------------- #
# Engine resolution + status
# --------------------------------------------------------------------------- #

def resolve_engine() -> str:
    """The tier that WOULD serve a request right now: local|basic.

    Pure inspection (no model call) for display in /api/health. ``basic`` means
    the on-device model is unavailable and answers will be rule-based.
    """
    mode = get_mode()
    if mode == "basic":
        return "basic"
    ls = local_status()
    if ls["enabled"] and ls["reachable"] and ls["model_ready"]:
        return "local"
    return "basic"


def engine_status() -> dict:
    """Full snapshot for /api/health and GET /api/engine."""
    return {
        "mode": get_mode(),
        "resolved": resolve_engine(),
        "offline": True,          # always — there is no network path
        "local": local_status(),
    }


# --------------------------------------------------------------------------- #
# The one call every agent makes
# --------------------------------------------------------------------------- #

def structured_call(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    max_tokens: int = 2048,
    lang: str = "en",
) -> Optional[dict]:
    """Return a dict validated against ``schema`` from the on-device model.

    Returns ``None`` on failure (or in ``basic`` mode) so the caller uses its
    rule-based fallback. Records the winning tier for :func:`powered_by_label`.

    ``lang`` ("en"|"ms") appends a strong output-language directive so the model
    answers entirely in the teacher's language instead of drifting to English.
    """
    _last_engine.set(None)
    mode = get_mode()
    if mode == "basic" or not settings.llm_enabled:
        return None

    if str(lang).lower().startswith("ms"):
        system = system + (
            "\n\nARAHAN BAHASA (PALING PENTING): Tulis SEMUA nilai teks dalam output JSON "
            "sepenuhnya dalam Bahasa Melayu — termasuk ringkasan, nota, objektif, aktiviti, "
            "cadangan, strategi dan penjelasan. JANGAN campur atau guna Bahasa Inggeris dalam "
            "nilai teks. Kekalkan istilah rasmi KPM dalam Bahasa Melayu (contoh: Standard "
            "Kandungan, Standard Pembelajaran, Objektif Pembelajaran). Nama kunci JSON (keys) "
            "kekal dalam Bahasa Inggeris seperti dalam skema."
        )
    else:
        system = system + "\n\nLANGUAGE: Write ALL output text values in English."

    try:
        content = _local_chat(system, user, schema, max_tokens)
        data = _parse_json(content or "")
        if data is not None:
            _last_engine.set("local")
            return data
        logger.warning("On-device model returned unparseable JSON; using rule-based fallback.")
    except Exception as exc:  # noqa: BLE001 — degrade to rule-based
        logger.warning("Ollama/on-device call failed (%s); using rule-based fallback.", exc)

    return None

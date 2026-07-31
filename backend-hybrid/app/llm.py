"""Hybrid LLM layer for the three agents.

Every agent calls :func:`structured_call` exactly as before and gets a validated
JSON object (or ``None``) back. What changed is what happens *inside*: the call
is now tiered.

    ENGINE_MODE = auto   →  try CLOUD (if online & configured) → LOCAL Ollama → None
    ENGINE_MODE = cloud  →  CLOUD only → None
    ENGINE_MODE = local  →  LOCAL Ollama only → None
    ENGINE_MODE = basic  →  None  (skip models entirely)

Returning ``None`` is the signal every agent already understands: "use your
rule-based fallback". So the app degrades gracefully end-to-end — a school with
no internet *and* no Ollama still gets a complete (if simpler) answer.

The mode is read from settings by default but can be flipped at runtime via
:func:`set_mode` (wired to POST /api/engine), so a teacher can force on-device or
basic mode from the UI without restarting the server.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import socket
from typing import Any, Optional
from urllib.parse import urlparse

from .config import settings

logger = logging.getLogger("resilient-edtech.llm")

_client = None  # singleton Ollama client

# Runtime override of settings.engine_mode (None = use the configured default).
_runtime_mode: Optional[str] = None

# Records which tier produced the most recent successful result, per-request.
_last_engine: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "last_engine", default=None
)

_VALID_MODES = {"auto", "cloud", "local", "basic"}


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
    model call so the UI can show whether the answer came from the cloud, the
    on-device model, or the rule-based fallback.
    """
    eng = _last_engine.get()
    if eng == "cloud":
        return f"Cloud AI ({settings.cloud_model})"
    if eng == "local":
        return f"Llama 3.2 3B (on-device)"
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
# Connectivity
# --------------------------------------------------------------------------- #

def _host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "api.openai.com"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def internet_reachable(url: Optional[str] = None, timeout: Optional[float] = None) -> bool:
    """Quick TCP probe to decide online/offline for ``auto`` mode.

    Defaults to probing the configured cloud endpoint's host:port. Cheap and
    dependency-free; never raises.
    """
    host, port = _host_port(url or settings.cloud_base_url)
    timeout = timeout if timeout is not None else settings.connectivity_timeout
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Cloud tier (OpenAI-compatible Chat Completions)
# --------------------------------------------------------------------------- #

def cloud_configured() -> bool:
    return bool(settings.cloud_enabled and settings.cloud_api_key)


def _cloud_chat(system: str, user: str, schema: dict[str, Any], max_tokens: int) -> Optional[str]:
    """POST to an OpenAI-compatible endpoint; return raw message content or None.

    Uses httpx when available (handles proxies/TLS nicely) and falls back to the
    stdlib so no new dependency is required.
    """
    url = f"{settings.cloud_base_url}/chat/completions"
    sys_prompt = (
        system
        + "\n\nReturn ONLY a JSON object that conforms to this JSON schema:\n"
        + json.dumps(_clean_schema(schema))
    )
    payload = {
        "model": settings.cloud_model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ],
        "temperature": settings.temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.cloud_api_key}",
        "Content-Type": "application/json",
    }

    body: Optional[str] = None
    try:
        import httpx  # lazy

        resp = httpx.post(url, json=payload, headers=headers, timeout=settings.cloud_timeout)
        resp.raise_for_status()
        body = resp.text
    except ImportError:
        import urllib.request  # stdlib fallback

        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=settings.cloud_timeout) as r:  # noqa: S310
            body = r.read().decode("utf-8")

    if not body:
        return None
    try:
        data = json.loads(body)
        return (data["choices"][0]["message"]["content"]) or None
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        logger.warning("Unexpected cloud response shape.")
        return None


def cloud_status() -> dict:
    """Reachability probe for the cloud tier (for /api/health)."""
    status = {
        "configured": cloud_configured(),
        "base_url": settings.cloud_base_url,
        "model": settings.cloud_model,
        "online": False,
    }
    if status["configured"]:
        status["online"] = internet_reachable()
    return status


# --------------------------------------------------------------------------- #
# Local tier (Ollama)
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
    """Quick reachability probe for the local Ollama model."""
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


# Back-compat alias: older code imported `llm_status`.
def llm_status() -> dict:
    return local_status()


def llm_available() -> bool:
    return settings.llm_enabled


# --------------------------------------------------------------------------- #
# Engine resolution + status
# --------------------------------------------------------------------------- #

def _tier_order(mode: str) -> list[str]:
    return {
        "auto": ["cloud", "local"],
        "cloud": ["cloud"],
        "local": ["local"],
        "basic": [],
    }.get(mode, ["cloud", "local"])


def resolve_engine() -> str:
    """The tier that WOULD serve a request right now: cloud|local|basic.

    Pure inspection (no model call) for display in /api/health. ``basic`` means
    no model tier is available and answers will be rule-based.
    """
    mode = get_mode()
    if mode == "basic":
        return "basic"
    for tier in _tier_order(mode):
        if tier == "cloud" and cloud_configured():
            if mode == "cloud" or internet_reachable():
                return "cloud"
        if tier == "local":
            ls = local_status()
            if ls["enabled"] and ls["reachable"] and ls["model_ready"]:
                return "local"
    return "basic"


def engine_status() -> dict:
    """Full snapshot for /api/health and GET /api/engine."""
    return {
        "mode": get_mode(),
        "resolved": resolve_engine(),
        "cloud": cloud_status(),
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
) -> Optional[dict]:
    """Return a dict validated against ``schema`` from the best available tier.

    Tries each tier allowed by the current mode in order; returns ``None`` on
    total failure so the caller uses its rule-based fallback. Records the
    winning tier in a context var (see :func:`powered_by_label`).
    """
    _last_engine.set(None)
    mode = get_mode()
    if mode == "basic":
        return None

    online = None  # lazily probed once, only in auto mode
    for tier in _tier_order(mode):
        if tier == "cloud":
            if not cloud_configured():
                continue
            if mode == "auto":
                if online is None:
                    online = internet_reachable()
                if not online:
                    continue
            try:
                content = _cloud_chat(system, user, schema, max_tokens)
                data = _parse_json(content or "")
                if data is not None:
                    _last_engine.set("cloud")
                    return data
                logger.warning("Cloud returned unparseable JSON; trying next tier.")
            except Exception as exc:  # noqa: BLE001 — degrade to next tier
                logger.warning("Cloud call failed (%s); trying next tier.", exc)

        elif tier == "local":
            if not settings.llm_enabled:
                continue
            try:
                content = _local_chat(system, user, schema, max_tokens)
                data = _parse_json(content or "")
                if data is not None:
                    _last_engine.set("local")
                    return data
                logger.warning("Local model returned unparseable JSON; using fallback.")
            except Exception as exc:  # noqa: BLE001 — degrade to rule-based
                logger.warning("Ollama/local call failed (%s); using rule-based fallback.", exc)

    return None

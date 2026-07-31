"""Application configuration, loaded from environment / .env.

HYBRID build: the three agents can now run on one of three tiers —
  * cloud  — an OpenAI-compatible Chat Completions endpoint (when online)
  * local  — Llama 3.2 3B served by Ollama (fully offline)
  * basic  — the built-in rule-based fallback (no model at all)

The active tier is chosen by ``ENGINE_MODE`` (auto|cloud|local|basic). In
``auto`` the app prefers cloud when it's configured *and* the machine is online,
otherwise it transparently falls back to the local model, and finally to the
rule-based logic — so it always produces an answer, online or off.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR.parent / "frontend"

_VALID_MODES = {"auto", "cloud", "local", "basic"}


def _as_bool(value: str, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


class Settings:
    """Runtime settings resolved from environment variables.

    The local tier is powered by Llama 3.2 3B via Ollama (nothing leaves the
    machine). The optional cloud tier uses any OpenAI-compatible endpoint
    (OpenAI, OpenRouter, Together, a self-hosted gateway, …) and is only ever
    used when the school is online and an API key is present.
    """

    # ------------------------------------------------------------------ #
    # Engine selection
    # ------------------------------------------------------------------ #
    # auto | cloud | local | basic. This is the *default* preference; it can be
    # overridden at runtime via POST /api/engine (see app/llm.py).
    engine_mode: str = (os.getenv("ENGINE_MODE", "auto").strip().lower() or "auto")
    if engine_mode not in _VALID_MODES:
        engine_mode = "auto"

    # ------------------------------------------------------------------ #
    # Local tier — Ollama (offline)
    # ------------------------------------------------------------------ #
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip()
    # Master toggle for the LOCAL model — set LLM_ENABLED=false to skip Ollama.
    llm_enabled: bool = _as_bool(os.getenv("LLM_ENABLED", "true"))

    # ------------------------------------------------------------------ #
    # Cloud tier — OpenAI-compatible Chat Completions (online)
    # ------------------------------------------------------------------ #
    cloud_api_key: str = os.getenv("CLOUD_API_KEY", "").strip()
    cloud_base_url: str = os.getenv("CLOUD_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    cloud_model: str = os.getenv("CLOUD_MODEL", "gpt-4o-mini").strip()
    # Cloud is "configured" when a key is present; CLOUD_ENABLED can force it off.
    cloud_enabled: bool = _as_bool(os.getenv("CLOUD_ENABLED", "true")) and bool(cloud_api_key)
    cloud_timeout: float = float(os.getenv("CLOUD_TIMEOUT", "60"))
    # How long the online/offline probe may take (seconds).
    connectivity_timeout: float = float(os.getenv("CONNECTIVITY_TIMEOUT", "1.5"))

    # ------------------------------------------------------------------ #
    # Generation tuning (shared by both model tiers).
    # ------------------------------------------------------------------ #
    num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
    temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
    request_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "180"))

    # Optional: absolute path to the Tesseract OCR executable (CV pipeline).
    tesseract_cmd: str = os.getenv("TESSERACT_CMD", "").strip()


settings = Settings()


@lru_cache(maxsize=1)
def load_dskp() -> dict:
    """Load the DSKP reference knowledge base."""
    return json.loads((DATA_DIR / "dskp.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_tech_tools() -> dict:
    """Load the education-technology / strategies knowledge base."""
    return json.loads((DATA_DIR / "tech_tools.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_diff_scaffolds() -> dict:
    """Load the differentiation scaffolds playbook (Agent D).

    Maps KSSR performance levels (Tahap Penguasaan) to tier templates and
    scaffold moves. Honors the spec's 'Playbooks/differentiation_scaffolds'
    notion; stored as JSON alongside the other knowledge bases for consistency.
    """
    return json.loads((DATA_DIR / "differentiation_scaffolds.json").read_text(encoding="utf-8"))

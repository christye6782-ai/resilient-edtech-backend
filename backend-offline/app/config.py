"""Application configuration — Localized Offline Agentic AI build.

Every agent runs on ONE device with no internet. There are exactly two engine
tiers, both fully offline:

  * local  — Llama 3.2 3B served by Ollama (the on-device model)
  * basic  — the built-in rule-based fallback (no model at all)

``ENGINE_MODE`` chooses the policy:
  auto  → local Ollama if reachable, else rule-based   (default)
  local → local Ollama, else rule-based
  basic → rule-based only

There is no cloud tier and no network call anywhere in the stack.
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

_VALID_MODES = {"auto", "local", "basic"}


def _as_bool(value: str, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


class Settings:
    """Runtime settings resolved from environment variables.

    The model tier is powered by Llama 3.2 3B via Ollama — nothing leaves the
    machine, ever. When the model is unavailable the agents fall back to a
    rule-based engine, so the app always produces a complete answer offline.
    """

    # auto | local | basic. The *default* preference; can be overridden at
    # runtime via POST /api/engine (see app/llm.py).
    engine_mode: str = (os.getenv("ENGINE_MODE", "auto").strip().lower() or "auto")
    if engine_mode not in _VALID_MODES:
        engine_mode = "auto"

    # ------------------------------------------------------------------ #
    # On-device model — Ollama (fully offline)
    # ------------------------------------------------------------------ #
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip()
    # Master toggle for the on-device model — set LLM_ENABLED=false to force
    # the rule-based engine (e.g. on the lowest-spec hardware).
    llm_enabled: bool = _as_bool(os.getenv("LLM_ENABLED", "true"))

    # ------------------------------------------------------------------ #
    # Generation tuning.
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
    """Load the differentiation scaffolds playbook (Agent D)."""
    return json.loads((DATA_DIR / "differentiation_scaffolds.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_tp_pbd() -> dict:
    """Load the Standard Prestasi / Tahap Penguasaan (TP1-6) reference for PBD."""
    return json.loads((DATA_DIR / "tp_pbd.json").read_text(encoding="utf-8"))

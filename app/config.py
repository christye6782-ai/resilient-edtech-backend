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
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
# Read-only content shipped with the app: curriculum corpus, tool knowledge
# bases, differentiation scaffolds. Never written to at runtime.
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR.parent / "frontend"


# --------------------------------------------------------------------------- #
# Writable state location.
#
# Bundled content and teacher data must not share a folder once the app is
# installed rather than run from a source checkout. If the app lands in
# Program Files and a standard-user teacher launches it, the install folder is
# read-only for them — and because the database directory used to be created at
# import time, the app raised PermissionError and refused to start at all.
#
# Resolution order:
#   1. RET_DATA_DIR         — explicit override (school-managed deployments)
#   2. source checkout      — keep data beside the code, as during development
#   3. existing legacy data — don't orphan an install that already has a DB
#   4. per-user app data    — %LOCALAPPDATA%\ResilientEdTech (the normal case)
# --------------------------------------------------------------------------- #

def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:  # noqa: BLE001 — any failure means "treat as read-only"
        return False


def _resolve_user_data_dir() -> Path:
    override = os.getenv("RET_DATA_DIR")
    if override:
        p = Path(override).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    frozen = getattr(sys, "frozen", False)

    # The pre-move location: db.py resolved parent.parent / "data", i.e. a
    # "data" folder beside app/, NOT inside it. An existing install therefore
    # has its database in the PROJECT ROOT. Missing this would silently start
    # the app on an empty database and make a teacher's history look lost.
    legacy = BASE_DIR.parent / "data"
    if (legacy / "resilient.db").exists() and _is_writable(legacy):
        return legacy

    if not frozen and _is_writable(DATA_DIR):
        return DATA_DIR

    # An even older layout kept it inside app/data — honour that too.
    if (DATA_DIR / "resilient.db").exists() and _is_writable(DATA_DIR):
        return DATA_DIR

    base = os.getenv("LOCALAPPDATA") or os.getenv("XDG_DATA_HOME")
    root = Path(base) if base else (Path.home() / ".local" / "share")
    p = root / "ResilientEdTech"
    p.mkdir(parents=True, exist_ok=True)
    return p


USER_DATA_DIR = _resolve_user_data_dir()
UPLOADS_DIR = USER_DATA_DIR / "uploads"

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
    """DEPRECATED — the Standard Prestasi / TP1-6 reference is no longer used.

    It held a single Sains Tingkatan 1 entry, which the model copied into
    unrelated lessons (a Year 5 English plan came back labelled "Form 1").
    Differentiation tiers now come from differentiation_scaffolds.json alone.
    Kept as a stub so any stale import doesn't crash.
    """
    return {"subjects": []}

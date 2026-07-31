"""Secure local storage helpers for uploads."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .config import DATA_DIR


_UPLOADS = Path(DATA_DIR) / "uploads"


def uploads_dir() -> Path:
    _UPLOADS.mkdir(parents=True, exist_ok=True)
    return _UPLOADS


def safe_filename(name: str) -> str:
    # Basic sanitization: keep alphanum, dot, dash, underscore
    name = name.replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9._-]", "", name)
    return name[:200]


def cleanup_old_uploads(days: int = 30) -> int:
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(days=days)
    removed = 0
    for p in uploads_dir().iterdir():
        try:
            mtime = datetime.utcfromtimestamp(p.stat().st_mtime)
            if mtime < cutoff:
                p.unlink()
                removed += 1
        except Exception:
            continue
    return removed

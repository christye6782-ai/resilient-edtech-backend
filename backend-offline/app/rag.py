"""On-device Retrieval-Augmented Generation — Level 3 memory.

Fully offline. Embeddings come from an embedding model (default
``nomic-embed-text``) served by the SAME Ollama instance as the chat model;
vectors live in the existing SQLite database; retrieval is a pure-Python cosine
scan. No numpy, no FAISS, no vector-DB service — nothing new to install beyond
one ``ollama pull``.

Two collections
---------------
* ``curriculum`` — the KSSR DSKP corpus shipped in ``app/data/curriculum/``.
* ``lessons``    — this device's saved lesson plans, tagged by ``teacher_id``.

Routing (see the RAG Scope board)
---------------------------------
* Curriculum retrieval grounds the **Analyst** (grade against the real
  standard) AND the **Pedagogy Architect** (design to it). Grounding, not bias.
* Lesson retrieval personalises the **Architect only**, gated behind a minimum
  number of saved lessons. The Analyst never sees lesson history, so grading
  stays unbiased (the Level 2 principle, preserved).

Everything degrades gracefully: if the embedding model is not present, every
retrieval returns an empty string / empty list and the agents run exactly as
they did before (rule-based or plain-prompt).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Optional

from .config import settings, DATA_DIR
from . import db as dbmod

logger = logging.getLogger("resilient-edtech.rag")

# The embedding model — pulled once via `ollama pull nomic-embed-text`.
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text").strip()

# Where the chunked curriculum corpus lives (built from the DSKP PDFs).
CORPUS_DIR = DATA_DIR / "curriculum"

# Minimum saved lessons before lesson-history retrieval activates (your call).
MIN_LESSONS_FOR_RAG = int(os.getenv("RAG_MIN_LESSONS", "3"))

_client = None  # singleton Ollama client (separate handle from llm.py is fine)
_vec_cache: dict = {}  # collection -> parsed rows, loaded once per server run
_query_cache: dict = {}  # query text -> embedding, avoids re-embedding same query


# --------------------------------------------------------------------------- #
# Ollama embedding tier
# --------------------------------------------------------------------------- #

def _get_client():
    global _client
    if _client is None:
        from ollama import Client  # lazy import — same dependency the LLM uses
        _client = Client(host=settings.ollama_host, timeout=settings.request_timeout)
    return _client


def _embed(text: str) -> Optional[list[float]]:
    """Embed one string. Returns None on any failure (caller degrades)."""
    text = (text or "").strip()
    if not text:
        return None
    if text in _query_cache:
        return _query_cache[text]
    try:
        resp = _get_client().embeddings(model=EMBED_MODEL, prompt=text[:4000])
        emb = None
        if hasattr(resp, "get"):
            emb = resp.get("embedding")
        if emb is None:
            emb = getattr(resp, "embedding", None)
        result = list(emb) if emb else None
        if result is not None:
            if len(_query_cache) > 256:
                _query_cache.clear()
            _query_cache[text] = result
        return result
    except Exception as exc:  # noqa: BLE001 — degrade silently
        logger.info("Embedding failed (%s); RAG will no-op.", exc)
        return None


def embed_ready() -> bool:
    """True if the embedding model is pulled and reachable."""
    if not settings.llm_enabled:
        return False
    try:
        tags = _get_client().list()
        base = EMBED_MODEL.split(":")[0].lower()
        models = [(m.get("model", "") or m.get("name", "") or "") for m in tags.get("models", [])]
        return any(m.split(":")[0].lower() == base for m in models)
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Vector store (SQLite)
# --------------------------------------------------------------------------- #

def _ensure_table() -> None:
    c = dbmod.get_conn()
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_vectors (
            id TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            teacher_id INTEGER,
            year INTEGER,
            section TEXT,
            codes TEXT,
            text TEXT,
            hash TEXT,
            dim INTEGER,
            embedding TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rag_coll ON rag_vectors(collection, teacher_id)")
    c.commit()
    c.close()


def _hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def _upsert(row: dict) -> None:
    c = dbmod.get_conn()
    cur = c.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO rag_vectors "
        "(id, collection, teacher_id, year, section, codes, text, hash, dim, embedding) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            row["id"], row["collection"], row.get("teacher_id"), row.get("year"),
            row.get("section"), json.dumps(row.get("codes") or []), row.get("text"),
            row.get("hash"), row.get("dim"), json.dumps(row.get("embedding")),
        ),
    )
    c.commit()
    c.close()
    _vec_cache.pop(row["collection"], None)  # invalidate cache for this collection
    c = dbmod.get_conn()
    cur = c.cursor()
    cur.execute("SELECT id, hash FROM rag_vectors WHERE collection = ?", (collection,))
    out = {r[0]: r[1] for r in cur.fetchall()}
    c.close()
    return out


def _rows(collection: str, teacher_id: Optional[int] = None, year: Optional[int] = None) -> list[dict]:
    # Load + JSON-parse the collection once, then keep it in memory. Curriculum
    # vectors never change between reindexes, so this turns a per-request
    # 510-row deserialize into a one-time cost. Cache is cleared on reindex.
    base = _vec_cache.get(collection)
    if base is None:
        base = _load_rows(collection)
        _vec_cache[collection] = base
    # apply lightweight filters in memory
    out = base
    if teacher_id is not None:
        out = [r for r in out if r.get("teacher_id") == teacher_id]
    if year is not None:
        out = [r for r in out if r.get("year") == year or r.get("year") is None]
    return out


def _load_rows(collection: str) -> list[dict]:
    c = dbmod.get_conn()
    cur = c.cursor()
    cur.execute(
        "SELECT id, teacher_id, year, section, codes, text, embedding FROM rag_vectors WHERE collection = ?",
        (collection,),
    )
    rows = cur.fetchall()
    c.close()
    out = []
    for r in rows:
        try:
            emb = json.loads(r[6]) if r[6] else None
        except Exception:  # noqa: BLE001
            emb = None
        if not emb:
            continue
        out.append({
            "id": r[0], "teacher_id": r[1], "year": r[2], "section": r[3],
            "codes": json.loads(r[4] or "[]"), "text": r[5], "embedding": emb,
        })
    return out


# --------------------------------------------------------------------------- #
# Indexing
# --------------------------------------------------------------------------- #

def index_curriculum(force: bool = False) -> dict:
    """Embed and store the curriculum corpus. Skips chunks whose text is
    unchanged (content-hash) unless ``force``. Safe to call repeatedly."""
    _ensure_table()
    if not embed_ready():
        return {"ok": False, "reason": "embedding model not available", "indexed": 0, "skipped": 0}

    existing = {} if force else _existing_hashes("curriculum")
    indexed = skipped = 0
    files = sorted(CORPUS_DIR.glob("**/*.json"))
    for fp in files:
        if fp.name == "manifest.json":
            continue
        try:
            records = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for rec in records:
            rid = rec["id"]
            h = _hash(rec.get("text", ""))
            if existing.get(rid) == h:
                skipped += 1
                continue
            emb = _embed(rec.get("text", ""))
            if not emb:
                continue
            _upsert({
                "id": rid, "collection": "curriculum", "teacher_id": None,
                "year": rec.get("year"), "section": rec.get("section"),
                "codes": rec.get("codes"), "text": rec.get("text"),
                "hash": h, "dim": len(emb), "embedding": emb,
            })
            indexed += 1
    return {"ok": True, "indexed": indexed, "skipped": skipped}


def index_lesson(plan_id: int, teacher_id: int, text: str, meta: Optional[dict] = None) -> bool:
    """Embed and store one saved lesson plan for later personalisation (P2)."""
    _ensure_table()
    if not embed_ready():
        return False
    emb = _embed(text)
    if not emb:
        return False
    meta = meta or {}
    _upsert({
        "id": f"lesson-{plan_id}", "collection": "lessons", "teacher_id": teacher_id,
        "year": meta.get("year"), "section": meta.get("subject"),
        "codes": [], "text": text, "hash": _hash(text), "dim": len(emb), "embedding": emb,
    })
    return True


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #

def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def retrieve(query: str, collection: str, k: int = 4,
             teacher_id: Optional[int] = None, year: Optional[int] = None) -> list[dict]:
    """Top-k most similar chunks in ``collection`` (pure-Python cosine)."""
    if not embed_ready():
        return []
    qv = _embed(query)
    if not qv:
        return []
    scored = []
    for row in _rows(collection, teacher_id=teacher_id, year=year):
        score = _cosine(qv, row["embedding"])
        scored.append((score, row))
    scored.sort(key=lambda t: t[0], reverse=True)
    out = []
    for score, row in scored[:k]:
        out.append({
            "id": row["id"], "score": round(score, 4), "year": row["year"],
            "section": row["section"], "codes": row["codes"], "text": row["text"],
        })
    return out


def _year_from(*vals) -> Optional[int]:
    """Best-effort 'Year N' / 'Tahun N' parse from subject/form/topic strings."""
    import re
    for v in vals:
        if not v:
            continue
        m = re.search(r"\b(?:year|tahun|thn|form|tingkatan)?\s*([1-6])\b", str(v), re.I)
        if m:
            return int(m.group(1))
    return None


# --------------------------------------------------------------------------- #
# Prompt-injection helpers (labelled context blocks for the agents)
# --------------------------------------------------------------------------- #

def curriculum_context(subject: Optional[str], form: Optional[str],
                       topic: Optional[str], lesson_text: str = "", k: int = 4) -> str:
    """Grounding block for the Analyst + Architect: the real DSKP passages most
    relevant to this lesson. Empty string when RAG is unavailable."""
    query = " ".join(x for x in [subject, form, topic, (lesson_text or "")[:600]] if x).strip()
    if not query:
        return ""
    year = _year_from(form, subject, topic)
    hits = retrieve(query, "curriculum", k=k, year=year)
    if not hits:
        return ""
    lines = [
        "RETRIEVED DSKP CURRICULUM (real KSSR standards, most relevant to this "
        "lesson — ground your judgement in these and cite the codes where they apply):"
    ]
    for h in hits:
        tag = f"Y{h['year']} · {h['section']}" + (f" · {', '.join(h['codes'])}" if h["codes"] else "")
        snippet = (h["text"] or "").strip().replace("\n", " ")
        lines.append(f"[{tag}] {snippet[:500]}")
    return "\n".join(lines)


def curriculum_sources(subject: Optional[str], form: Optional[str],
                       topic: Optional[str], lesson_text: str = "", k: int = 4) -> list[dict]:
    """P3: the same DSKP passages ``curriculum_context`` feeds the agents, but
    returned as structured records the UI can render ('grounded in these
    standards'). Empty list when RAG is unavailable."""
    query = " ".join(x for x in [subject, form, topic, (lesson_text or "")[:600]] if x).strip()
    if not query:
        return []
    year = _year_from(form, subject, topic)
    hits = retrieve(query, "curriculum", k=k, year=year)
    out = []
    for h in hits:
        snippet = (h["text"] or "").strip().replace("\n", " ")
        out.append({
            "year": h["year"],
            "section": h["section"] or "",
            "codes": h["codes"] or [],
            "snippet": snippet[:280],
            "score": h["score"],
        })
    return out


def lesson_context(query: str, teacher_id: int, k: int = 3,
                   min_lessons: int = MIN_LESSONS_FOR_RAG) -> str:
    """Personalisation block for the Architect ONLY. Gated behind a minimum
    number of indexed lessons; returns '' until the teacher has enough history
    (the caller then falls back to the Level 2 digest)."""
    rows = _rows("lessons", teacher_id=teacher_id)
    if len(rows) < min_lessons:
        return ""
    hits = retrieve(query, "lessons", k=k, teacher_id=teacher_id)
    if not hits:
        return ""
    lines = ["RETRIEVED PAST LESSONS (this teacher's own similar lessons — reuse what worked, adapt to this topic):"]
    for h in hits:
        snippet = (h["text"] or "").strip().replace("\n", " ")
        lines.append(f"- {snippet[:400]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Status + CLI
# --------------------------------------------------------------------------- #

def status() -> dict:
    _ensure_table()
    c = dbmod.get_conn()
    cur = c.cursor()
    cur.execute("SELECT collection, COUNT(*) FROM rag_vectors GROUP BY collection")
    counts = {r[0]: r[1] for r in cur.fetchall()}
    c.close()
    manifest = {}
    mf = CORPUS_DIR / "english_primary" / "manifest.json"
    if mf.exists():
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {
        "embed_model": EMBED_MODEL,
        "embed_ready": embed_ready(),
        "min_lessons_for_rag": MIN_LESSONS_FOR_RAG,
        "indexed": counts,
        "corpus": manifest,
    }


if __name__ == "__main__":
    # One-shot ingest:  python -m app.rag reindex
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "reindex":
        print("Indexing curriculum (embedding via Ollama)…")
        print(index_curriculum(force="--force" in sys.argv))
    else:
        print(json.dumps(status(), indent=2))

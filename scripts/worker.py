"""DB-backed worker: polls the `jobs` table and processes queued tasks.

This simple worker requires no external broker and works offline.
Run with:
    python scripts/worker.py

It continuously polls for jobs with status='queued' and updates job state in
the database so work survives restarts.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure the repository root is importable when running from the scripts directory.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db as dbmod, cv_service
from app.config import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
SLEEP_SECONDS = 3

DB = dbmod


def fetch_queued_job() -> Optional[dict]:
    conn = DB.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, type, upload_id FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "type": row[1], "upload_id": row[2]}


def process_extract(job_id: int, upload_id: int) -> None:
    logging.info(f"Processing extract job {job_id} -> upload {upload_id}")
    try:
        DB.update_job_status(job_id, "running")
        conn = DB.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT orig_filename, stored_path FROM uploads WHERE id = ?", (upload_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            raise RuntimeError("Upload row not found")
        orig_name, stored_path = row[0], row[1]
        p = Path(stored_path)
        if not p.exists():
            raise RuntimeError(f"Stored file missing: {stored_path}")
        data = p.read_bytes()
        res = cv_service.extract_from_upload(orig_name or p.name, data)
        DB.update_upload_extraction(upload_id, res.text or "", getattr(res, "confidence", None))
        DB.update_job_status(job_id, "finished", {"extracted_words": len((res.text or "").split())})
        logging.info(f"Job {job_id} finished")
    except Exception as exc:
        logging.exception("Job failed")
        try:
            DB.update_job_status(job_id, "failed", {"error": str(exc)})
        except Exception:
            logging.exception("Failed to mark job as failed in DB")


def main():
    logging.info("Worker starting — polling jobs table")
    DB.init_db()
    while True:
        try:
            job = fetch_queued_job()
            if not job:
                time.sleep(SLEEP_SECONDS)
                continue
            jid = job["id"]
            jtype = job["type"]
            uid = job["upload_id"]
            if jtype == "extract":
                process_extract(jid, uid)
            else:
                logging.warning(f"Unknown job type: {jtype} (id={jid}), marking failed")
                DB.update_job_status(jid, "failed", {"error": "unknown job type"})
        except KeyboardInterrupt:
            logging.info("Worker interrupted — exiting")
            break
        except Exception:
            logging.exception("Unexpected worker error, sleeping briefly")
            time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    main()

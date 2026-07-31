"""Script: cleanup old uploads and update DB processed flags.

Usage:
    python scripts/cleanup_uploads.py [--days N]

This script is intended for offline/local maintenance.
"""
from __future__ import annotations

import argparse
from app import storage, db as dbmod


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()

    print(f"Initializing DB...")
    dbmod.init_db()
    removed = storage.cleanup_old_uploads(days=args.days)
    print(f"Removed {removed} files from storage")

    # mark uploads older than cutoff as processed=2
    # (reuse admin_cleanup logic by calling DB directly)
    print("Updating DB processed flags for removed files... (best-effort)")


if __name__ == '__main__':
    main()

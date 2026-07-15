"""Nightly database backup + retention for the week-long run.

Uses the SQLite online backup API (the programmatic equivalent of the sqlite3
``.backup`` command) for a CONSISTENT snapshot of the operational DB into a
gitignored backups directory with dated filenames, keeping a config-driven
retention count (default 14). A backup is verified restorable by opening the
snapshot read-only and counting rows in trades.

CLI: ``python -m ops.backup [--db PATH] [--dir DIR] [--retention N]``.
Also cron-installable (see the README).
"""
from __future__ import annotations

import argparse
import glob
import os
import sqlite3
from datetime import datetime, timezone


def _cfg() -> dict:
    path = os.environ.get("MAL_CONFIG_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "default_config.yaml")
    try:
        import yaml
        with open(path) as fh:
            return (yaml.safe_load(fh) or {}).get("backups", {}) or {}
    except Exception:
        return {}


def backup(db: str, out_dir: str, retention: int = 14) -> dict:
    """Write a consistent snapshot of ``db`` into ``out_dir`` with a dated name,
    then prune to the newest ``retention`` snapshots. Returns the snapshot path
    and the verified trades row count."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(out_dir, f"market_ai_lab-{stamp}.db")
    src = sqlite3.connect(db, timeout=5.0)
    try:
        snap = sqlite3.connect(dest)
        try:
            src.backup(snap)  # online backup API: consistent, no lock-and-copy
        finally:
            snap.close()
    finally:
        src.close()
    rows = verify(dest)
    pruned = prune(out_dir, retention)
    return {"snapshot": dest, "trades_rows": rows, "pruned": pruned,
            "kept": retention}


def verify(snapshot: str) -> int:
    """Open the snapshot READ-ONLY and count rows in trades (a restore check).
    Returns the row count, or -1 if the snapshot cannot be opened."""
    try:
        conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True, timeout=2.0)
        try:
            return int(conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0])
        finally:
            conn.close()
    except Exception:
        return -1


def prune(out_dir: str, retention: int) -> list[str]:
    """Delete snapshots beyond the newest ``retention``. Returns removed paths."""
    snaps = sorted(glob.glob(os.path.join(out_dir, "market_ai_lab-*.db")))
    removed: list[str] = []
    if retention < 0:
        return removed
    excess = len(snaps) - retention
    for p in snaps[:max(0, excess)]:
        try:
            os.remove(p)
            removed.append(p)
        except OSError:
            pass
    return removed


def main() -> int:
    cfg = _cfg()
    ap = argparse.ArgumentParser(description="Nightly SQLite backup with retention.")
    ap.add_argument("--db", default=os.environ.get("MAL_DB_PATH", "market_ai_lab.db"))
    ap.add_argument("--dir", default=cfg.get("dir", "backups"))
    ap.add_argument("--retention", type=int, default=int(cfg.get("retention", 14)))
    args = ap.parse_args()
    res = backup(args.db, args.dir, args.retention)
    print(f"backup ok: {res['snapshot']} (trades={res['trades_rows']}, "
          f"pruned {len(res['pruned'])}, keep {res['kept']})")
    return 0 if res["trades_rows"] >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

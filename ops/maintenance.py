"""Periodic maintenance for the week-long unattended run.

Two jobs the watchdog process (or a cron script) runs daily:
  - prune_events: cap the events table so it cannot grow unbounded over a week.
    It NEVER deletes trades, positions, bars, or audit-relevant events, only the
    high-volume informational chatter beyond a retention window.
  - maybe_train_challenger: attempt a real-data DNN challenger on the schedule.
    It refuses cleanly below the sample minimum (as train_real already does), and
    promotion stays GATED + MANUAL, so a challenger only waits for the operator's
    promote action from the GUI. Never auto-promotes.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

# Event kinds that are AUDIT-relevant or low-volume and must never be pruned.
_PROTECTED_KINDS = frozenset({
    "kill_switch", "control_change", "layer_toggle", "layer_source",
    "trade_entry", "trade_exit", "risk_block", "risk_precheck",
    "sleeve_rebalance", "sleeve_cap", "summary", "startup", "engine_supervisor",
    "research_pass", "feed_mode", "clock_mode", "warm_state",
})


def _db_path(db: str | None = None) -> str:
    return db or os.environ.get("MAL_DB_PATH", "market_ai_lab.db")


def events_per_day(db: str | None = None) -> float:
    """Estimate the events written per day (total events over the observed span).
    Used to project the week-long table size. Read-only."""
    db = _db_path(db)
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
    except Exception:
        return 0.0
    try:
        row = conn.execute(
            "SELECT COUNT(*), MIN(ts), MAX(ts) FROM events").fetchone()
    except Exception:
        return 0.0
    finally:
        conn.close()
    n = int(row[0] or 0)
    if n == 0 or not row[1] or not row[2]:
        return float(n)
    try:
        lo = datetime.fromisoformat(str(row[1]).replace("Z", "+00:00"))
        hi = datetime.fromisoformat(str(row[2]).replace("Z", "+00:00"))
    except Exception:
        return float(n)
    span_days = max((hi - lo).total_seconds() / 86400.0, 1.0 / 24)
    return round(n / span_days, 1)


def prune_events(db: str | None = None, keep_days: int = 30) -> dict:
    """Delete informational events older than keep_days, protecting audit kinds.
    Never touches trades/positions/bars (separate tables). Returns the delete
    count. A defensive no-op when keep_days <= 0."""
    db = _db_path(db)
    if keep_days <= 0:
        return {"deleted": 0, "kept_kinds": sorted(_PROTECTED_KINDS)}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    placeholders = ",".join("?" for _ in _PROTECTED_KINDS)
    conn = sqlite3.connect(db, timeout=5.0)
    try:
        cur = conn.execute(
            f"DELETE FROM events WHERE ts < ? AND kind NOT IN ({placeholders})",
            (cutoff, *sorted(_PROTECTED_KINDS)))
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()
    return {"deleted": int(deleted), "cutoff": cutoff}


def append_weeklog(db: str | None = None, path: str | None = None) -> dict:
    """Append the daily week-review digest to WEEKLOG.md. Reporting only: it reads
    the database read-only and writes the digest file, never a trade or a limit. A
    failure here never breaks the rest of maintenance (returns an error dict)."""
    db = _db_path(db)
    try:
        from ops import weeklog
    except Exception as e:  # zoneinfo/deps missing in a minimal env
        return {"status": "unavailable", "reason": type(e).__name__}
    try:
        return weeklog.append_daily_digest(db, path or weeklog.WEEKLOG_PATH)
    except Exception as e:
        return {"status": "error", "reason": type(e).__name__}


def maybe_run_discovery(db: str | None = None,
                        cfg_path: str | None = None) -> dict:
    """Run any due discovery funnel pass (crypto hourly, equities in US hours).

    A no-op returning {"status": "disabled"} while discovery.discovery_enabled is
    false, which is the default, so adding this to maintenance changes nothing
    until an operator opts in. Failure-isolated like the rest of maintenance:
    discovery is an advisory layer and must never break the loop.

    The cadence check lives inside discovery.run.due rather than here, so calling
    this more often than the interval is a cheap no-op.
    """
    db = _db_path(db)
    try:
        from discovery import run as discovery_run
    except Exception as e:  # noqa: BLE001 — optional deps missing in a minimal env
        return {"status": "unavailable", "reason": type(e).__name__}
    try:
        return discovery_run.run_due(db_path=db, cfg_path=cfg_path)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "reason": type(e).__name__}


def maybe_train_challenger(db: str | None = None,
                           symbols: list[str] | None = None) -> dict:
    """Attempt a real-data DNN challenger. Refuses cleanly below the sample
    minimum. Promotion stays GATED + MANUAL (never auto-promotes here). Returns
    the trainer status dict."""
    db = _db_path(db)
    try:
        from ml_factor.train_real import train_real_challenger
    except Exception as e:  # numpy/deps missing in a minimal env
        return {"status": "unavailable", "reason": type(e).__name__}
    syms = symbols or ["BTC/USD", "ETH/USD", "SPY", "QQQ"]
    try:
        res = train_real_challenger(db, syms)
    except Exception as e:
        return {"status": "error", "reason": type(e).__name__}
    # A trained challenger is registered as a challenger, NOT promoted. The GUI
    # surfaces it for the operator's manual promote.
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Daily maintenance: prune + challenger.")
    ap.add_argument("--db", default=None)
    ap.add_argument("--keep-days", type=int, default=30)
    ap.add_argument("--no-train", action="store_true")
    ap.add_argument("--no-weeklog", action="store_true")
    ap.add_argument("--no-discovery", action="store_true")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    print("prune:", prune_events(args.db, args.keep_days))
    print("events/day:", events_per_day(args.db))
    # Weeklog runs daily alongside the backup job: it appends the day's digest to
    # WEEKLOG.md, read-only over the DB. It is failure-isolated from the rest.
    if not args.no_weeklog:
        print("weeklog:", append_weeklog(args.db))
    # Discovery runs on its own cadence (crypto hourly, equities in US hours) and
    # no-ops when not due or while the flag is off (the default).
    if not args.no_discovery:
        print("discovery:", maybe_run_discovery(args.db, args.config))
    if not args.no_train:
        print("challenger:", maybe_train_challenger(args.db))

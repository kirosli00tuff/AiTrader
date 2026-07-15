"""Crash watchdog for the week-long unattended paper run.

Checks the stack every few minutes: engine process alive, bridge health, backend
health, and crypto bars still advancing within a staleness threshold. On a failure
it attempts ONE clean restart through the supervisor (the backend /engine/start
path) and sends an ntfy.sh notification either way, restart-succeeded or
stack-down. It NEVER touches the kill-request control file, and a kill-switch trip
is notified but NEVER auto-resumed (manual resume stays required). Notifications
carry component status only, never a key value or position detail.

Run as a separate process: ``python -m ops.watchdog`` (the start script launches
it and the teardown stops it).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.request

from api_server import stack


def _cfg(cfg_path: str | None = None) -> dict:
    path = cfg_path or os.environ.get("MAL_CONFIG_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "default_config.yaml")
    try:
        import yaml
        with open(path) as fh:
            return (yaml.safe_load(fh) or {}).get("watchdog", {}) or {}
    except Exception:
        return {}


def _db_path() -> str:
    return os.environ.get("MAL_DB_PATH", "market_ai_lab.db")


def bars_fresh(threshold_seconds: int, db: str | None = None) -> bool:
    """True when at least one crypto bar is newer than the staleness threshold.
    Reads the bars table read-only. A missing DB or no bars reads as NOT fresh."""
    db = db or _db_path()
    try:
        uri = f"file:{db}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            row = conn.execute(
                "SELECT MAX(timestamp) FROM bars WHERE symbol LIKE '%/%'"
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return False
    if not row or not row[0]:
        return False
    # ISO-8601 UTC. Compare to now with a tolerant parse.
    from datetime import datetime, timezone
    try:
        ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
    except Exception:
        return False
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age <= threshold_seconds


def kill_tripped() -> bool:
    """Whether the safety kill switch is tripped (read via the backend /kill).
    The watchdog NEVER writes the kill-request file; it only reads state."""
    try:
        with urllib.request.urlopen(stack.api_health_url().replace("/health", "/kill"),
                                    timeout=3) as r:
            data = json.loads(r.read().decode())
        return bool(data.get("kill_switch_tripped") or data.get("tripped"))
    except Exception:
        return False


def check_health(cfg: dict | None = None) -> dict:
    """One health snapshot: engine, bridge, backend, feed freshness, kill state."""
    cfg = cfg if cfg is not None else _cfg()
    stale = int(cfg.get("bar_staleness_seconds", 900))
    running = stack.stack_running()
    bridge_ok = stack.http_ok(stack.bridge_health_url(), tries=1, delay=0)
    backend_ok = stack.http_ok(stack.api_health_url(), tries=1, delay=0)
    fresh = bars_fresh(stale)
    tripped = kill_tripped()
    healthy = bool(running.get("running") and bridge_ok and backend_ok and fresh)
    return {"engine": bool(running.get("running")), "bridge": bridge_ok,
            "backend": backend_ok, "feed_fresh": fresh, "kill_tripped": tripped,
            "healthy": healthy}


def notify(message: str, cfg: dict | None = None, title: str = "AiTrader watchdog") -> bool:
    """Send an ntfy.sh notification (a plain HTTP POST, the curl equivalent).
    No topic configured => a no-op. NEVER includes a key value or position detail,
    only component status. Returns True when a notification was sent."""
    cfg = cfg if cfg is not None else _cfg()
    topic = str(cfg.get("ntfy_topic", "") or "")
    if not topic:
        return False
    server = str(cfg.get("ntfy_server", "https://ntfy.sh")).rstrip("/")
    url = f"{server}/{topic}"
    try:
        req = urllib.request.Request(
            url, data=message.encode("utf-8"), method="POST",
            headers={"Title": title, "Priority": "high"})
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


def attempt_restart() -> dict:
    """One clean restart: self-heal a crashed run, then ask the supervisor to
    start the stack (the backend /engine/start path). Never touches the
    kill-request file. Returns the outcome."""
    healed = stack.self_heal()
    started = False
    detail = ""
    try:
        req = urllib.request.Request(
            stack.api_health_url().replace("/health", "/engine/start"),
            data=b"{}", method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode())
        started = str(body.get("state", "")) in ("starting", "warming", "running")
        detail = str(body.get("state", ""))
    except Exception as e:
        detail = f"supervisor unreachable: {type(e).__name__}"
    return {"healed": healed, "restarted": started, "detail": detail}


def run_once(cfg: dict | None = None) -> dict:
    """One watchdog cycle. On a healthy stack: no action. On a kill trip: notify,
    NEVER restart (manual resume required). On an unhealthy stack: attempt one
    restart and notify the outcome. Returns the cycle result."""
    cfg = cfg if cfg is not None else _cfg()
    h = check_health(cfg)
    if h["kill_tripped"]:
        notify("Kill switch TRIPPED. Trading halted. Manual resume required. "
               "Watchdog will NOT auto-resume.", cfg)
        return {"action": "kill_notified", "health": h}
    if h["healthy"]:
        return {"action": "none", "health": h}
    # Unhealthy and not a kill trip: one clean restart attempt, then notify.
    r = attempt_restart()
    if r["restarted"]:
        notify(f"Stack unhealthy ({_status_line(h)}). Restarted via supervisor "
               f"(state {r['detail']}).", cfg)
        return {"action": "restarted", "health": h, "restart": r}
    notify(f"Stack DOWN ({_status_line(h)}). Restart FAILED ({r['detail']}). "
           "Manual attention needed.", cfg)
    return {"action": "restart_failed", "health": h, "restart": r}


def _status_line(h: dict) -> str:
    return (f"engine={'up' if h['engine'] else 'DOWN'} "
            f"bridge={'up' if h['bridge'] else 'DOWN'} "
            f"backend={'up' if h['backend'] else 'DOWN'} "
            f"feed={'fresh' if h['feed_fresh'] else 'STALE'}")


def main() -> None:
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    interval = int(cfg.get("check_interval_seconds", 180))
    notify("Watchdog started. Monitoring engine, bridge, backend, and feed.", cfg)
    while True:
        try:
            run_once(cfg)
        except Exception:
            pass  # a watchdog must never crash the run it guards
        time.sleep(max(30, interval))


if __name__ == "__main__":
    main()

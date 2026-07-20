"""Crash watchdog for the week-long unattended paper run.

Checks the stack every few minutes: engine process alive, bridge health, backend
health, and every tradeable symbol's bars still advancing within a staleness
threshold. On a failure it attempts ONE clean restart through the supervisor:
a running-but-sick stack (degraded bridge, feed substitution) is stopped first
through the supervisor's graceful /engine/stop, then started, and a down stack
is self-healed then started. It sends an ntfy.sh notification either way,
restart-succeeded or stack-down. On a degraded bridge or a feed substitution it
captures the bridge's fd and socket counts BEFORE the restart, because the
restart destroys the evidence (2026-07-17: caught, restarted, never
root-caused). It NEVER touches the kill-request control file, and a kill-switch
trip is notified but NEVER auto-resumed (manual resume stays required).
Notifications carry component status and symbol names only, never a key value
or position detail.

Run as a separate process: ``python -m ops.watchdog`` (the start script launches
it and the teardown stops it).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone

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


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Provenances that count as REAL market data on the alpaca_paper path.
_REAL_SOURCES = ("real_feed", "backfill")


def _db_path() -> str:
    """Repo-anchored, never cwd-relative (the adaptive/run.py bug class)."""
    d = os.environ.get("MAL_DB_PATH", "market_ai_lab.db")
    return d if os.path.isabs(d) else os.path.join(_REPO_ROOT, d)


def _real_feed_mode() -> bool:
    """True when the loop runs the real path (feed_mode alpaca_paper), read the
    same way the engine reads it: controls.json wins, config seeds. Unreadable
    means not-real, so an offline run is never held to the real-path bar."""
    try:
        from llm_consensus import control_file
        from llm_consensus.config_access import config_block
        feed = control_file.control_state().get("feed_mode")
        if not feed:
            feed = (config_block("simulation") or {}).get("feed_mode", "")
        return str(feed) == "alpaca_paper"
    except Exception:
        return False


def _discovery_enabled() -> bool:
    """Whether discovery is on, resolved the way the engine resolves it
    (controls.json over config). Unprovable reads as off."""
    try:
        from discovery import settings as discovery_settings
        return bool(discovery_settings.discovery_enabled(None))
    except Exception:
        return False


def _equity_market_open() -> bool:
    """US regular trading hours, from the ONE cadence authority
    (discovery.run.us_market_open) rather than a second copy."""
    try:
        from discovery.run import us_market_open
        return us_market_open(datetime.now(timezone.utc))
    except Exception:
        return True  # cannot tell: check anyway, the detecting direction


def tradeable_symbols(db: str | None = None) -> list[str]:
    """Every symbol the engine is actually trading: the profile-resolved static
    whitelist plus the active watchlist members when discovery is enabled.

    Watchlist members are read directly (status active, the only status the
    engine merges), read-only, and a missing table degrades to no members: the
    watchdog must never create schema or block on an advisory table.
    """
    symbols = list(stack.whitelist())
    if not _discovery_enabled():
        return symbols
    try:
        from discovery.watchlist import STATUS_ACTIVE
        conn = sqlite3.connect(f"file:{db or _db_path()}?mode=ro", uri=True,
                               timeout=2.0)
        try:
            rows = conn.execute(
                "SELECT symbol FROM watchlist WHERE status=? ORDER BY symbol",
                (STATUS_ACTIVE,)).fetchall()
        finally:
            conn.close()
        for r in rows:
            if r and r[0] and r[0] not in symbols:
                symbols.append(str(r[0]))
    except Exception:
        pass  # advisory read: unreadable watchlist means no members
    return symbols


def feed_ok(threshold_seconds: int, db: str | None = None) -> dict:
    """Per-symbol freshness AND provenance across every tradeable symbol.

    The old probe read MAX(timestamp) over all crypto bars, so any one current
    crypto symbol kept it green: SOL/USD sat 24 hours stale behind a fresh
    BTC/USD while the watchdog reported the feed healthy. Now every symbol the
    engine is actually trading (static whitelist plus active watchlist) is
    checked BY NAME, and one stale symbol is a detected condition that names
    the symbol.

    Equities are checked only while the US session is open: an equity closes
    no bars overnight, and that is a closed market, not a stale feed. Crypto
    is checked around the clock. Staleness alone is still NOT evidence of
    health (the 2026-07-17 outage wrote synthetic bars that always advance):
    on the real path the newest bar of every checked symbol must also be REAL
    (real_feed or backfill). A DB from before the provenance migration has no
    source column and falls back to freshness only, stated in the result.
    """
    db = db or _db_path()
    real_path = _real_feed_mode()
    now = datetime.now(timezone.utc)
    equities_open = _equity_market_open()
    out: dict = {"fresh": False, "real": False, "ok": False,
                 "source": "unknown", "provenance_checked": False,
                 "real_path": real_path, "symbols": {}, "stale_symbols": [],
                 "non_real_symbols": [], "checked_count": 0}
    symbols = tradeable_symbols(db)
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
    except Exception:
        return out
    provenance_checked = True
    try:
        for sym in symbols:
            if "/" not in sym and not equities_open:
                out["symbols"][sym] = {"checked": False,
                                       "reason": "market_closed"}
                continue
            row = None
            try:
                row = conn.execute(
                    "SELECT timestamp, COALESCE(source,'unknown') FROM bars"
                    " WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                    (sym,)).fetchone()
            except sqlite3.OperationalError:
                # Pre-migration DB: no source column. Freshness only.
                provenance_checked = False
                try:
                    row = conn.execute(
                        "SELECT timestamp, 'unknown' FROM bars WHERE symbol=?"
                        " ORDER BY timestamp DESC LIMIT 1", (sym,)).fetchone()
                except Exception:
                    row = None
            except Exception:
                row = None
            if not row or not row[0]:
                # Never polled and never backfilled. The exact SOL/USD state.
                out["symbols"][sym] = {"checked": True, "fresh": False,
                                       "source": "unknown",
                                       "reason": "no_bars"}
                out["stale_symbols"].append(sym)
                continue
            age = None
            try:
                ts = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                age = (now - ts).total_seconds()
            except Exception:
                age = None
            fresh = age is not None and age <= threshold_seconds
            source = str(row[1] or "unknown")
            out["symbols"][sym] = {
                "checked": True, "fresh": fresh, "source": source,
                "age_seconds": None if age is None else int(age)}
            if not fresh:
                out["stale_symbols"].append(sym)
            if provenance_checked and source not in _REAL_SOURCES:
                out["non_real_symbols"].append(sym)
    finally:
        conn.close()
    out["checked_count"] = sum(
        1 for d in out["symbols"].values() if d.get("checked"))
    out["provenance_checked"] = provenance_checked
    # Every checked symbol must be fresh. Zero checkable symbols (an all-equity
    # universe overnight) is a closed market, not a stale feed.
    out["fresh"] = not out["stale_symbols"]
    out["real"] = not out["non_real_symbols"]
    # Aggregate source for the status line: the worst news wins.
    if out["non_real_symbols"]:
        out["source"] = out["symbols"][out["non_real_symbols"][0]].get(
            "source", "unknown")
    else:
        for d in out["symbols"].values():
            if d.get("checked"):
                out["source"] = d.get("source", "unknown")
                break
    if real_path and provenance_checked:
        out["ok"] = out["fresh"] and out["real"]
    else:
        out["ok"] = out["fresh"]
    return out


def bars_fresh(threshold_seconds: int, db: str | None = None) -> bool:
    """Back-compat wrapper: freshness only. Health decisions use feed_ok."""
    return bool(feed_ok(threshold_seconds, db)["fresh"])


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


def bridge_state() -> dict:
    """Reachability AND capability of the bridge, from its /health payload.

    The 2026-07-17 bridge answered liveness probes while internally sick, so
    reachable alone is not up. status: "ok" | "degraded" | "down". A reachable
    bridge whose payload carries no status field reads "ok" (an old bridge)."""
    try:
        with urllib.request.urlopen(stack.bridge_health_url(), timeout=3) as r:
            data = json.loads(r.read().decode())
        return {"reachable": True,
                "status": str(data.get("status", "ok")) or "ok",
                "degraded": list(data.get("degraded", []) or []),
                "fd_count": data.get("fd_count")}
    except Exception:
        return {"reachable": False, "status": "down", "degraded": [],
                "fd_count": None}


def bridge_fd_snapshot() -> dict:
    """The bridge's open fd and open-socket counts, read EXTERNALLY via /proc.

    External on purpose: the suspected failure is fd exhaustion, in which the
    bridge cannot open a file to report on itself, while /proc/<pid>/fd stays
    readable from outside. The pid comes from the engine lock. Best effort,
    never raises."""
    try:
        pid = (stack.lock_status() or {}).get("bridge_pid")
    except Exception:
        pid = None
    if not pid:
        return {"available": False, "reason": "no bridge pid in engine.lock"}
    from ops import evidence
    fds = evidence.fd_count(int(pid))
    socks = evidence.socket_count(int(pid))
    return {"available": isinstance(fds, int), "bridge_pid": int(pid),
            "fd_count": fds, "socket_count": socks}


def check_health(cfg: dict | None = None) -> dict:
    """One health snapshot: engine, bridge capability, backend, per-symbol feed
    freshness AND provenance, kill state. A degraded bridge, one stale
    tradeable symbol, or a synthetic feed on the real path is a FAILURE, not a
    warning."""
    cfg = cfg if cfg is not None else _cfg()
    stale = int(cfg.get("bar_staleness_seconds", 900))
    running = stack.stack_running()
    bstate = bridge_state()
    bridge_ok = bool(bstate["reachable"] and bstate["status"] == "ok")
    backend_ok = stack.http_ok(stack.api_health_url(), tries=1, delay=0)
    feed = feed_ok(stale)
    tripped = kill_tripped()
    # Fresh but non-real on the real path is the substitution state: the walk
    # fallback advancing in live clothing.
    substitution = bool(feed.get("real_path") and feed.get("provenance_checked")
                        and feed.get("non_real_symbols"))
    healthy = bool(running.get("running") and bridge_ok and backend_ok
                   and feed["ok"])
    return {"engine": bool(running.get("running")), "bridge": bridge_ok,
            "bridge_status": bstate["status"],
            "bridge_degraded": bstate["degraded"],
            "backend": backend_ok, "feed_fresh": feed["fresh"],
            "feed_source": feed["source"], "feed_ok": feed["ok"],
            "feed_stale_symbols": list(feed.get("stale_symbols", [])),
            "feed_non_real_symbols": list(feed.get("non_real_symbols", [])),
            "feed_substitution": substitution,
            "kill_tripped": tripped, "healthy": healthy}


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


def _supervisor_post(path: str, timeout: float = 30) -> dict:
    """POST to a supervisor endpoint on the backend. Raises on transport
    failure so the caller decides what an unreachable supervisor means."""
    req = urllib.request.Request(
        stack.api_health_url().replace("/health", path),
        data=b"{}", method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def attempt_restart() -> dict:
    """One clean restart, for BOTH failure shapes: a down stack and a
    running-but-sick one (degraded bridge, feed substitution).

    Why remediation never fired before 2026-07-19: this function only knew how
    to START. With the sick bridge still answering HTTP 200, stack_running()
    read the stack as up, self_heal() refused ("a healthy stack is already
    running"), the supervisor refused /engine/start ("already running"), and
    the refusal's state echo ("running") satisfied the old success test, so 60
    degraded cycles each read as a successful restart while nothing was ever
    stopped. Now: a running stack is STOPPED first through the supervisor's
    graceful stop (the same path the GUI Stop uses, never the kill-request
    file), and success requires the supervisor to ACCEPT the start (ok true),
    never a state echo alone.

    The stop only happens when the supervisor answered it, deliberately: if
    the backend is down we cannot start either, and stopping a live engine
    with no way to restart it would turn a degraded stack into a dead one.
    """
    stopped: dict | None = None
    if stack.stack_running()["running"]:
        try:
            stopped = _supervisor_post("/engine/stop")
        except Exception as e:
            return {"healed": {}, "stopped": None, "restarted": False,
                    "detail": (f"stop unreachable ({type(e).__name__}); "
                               "leaving the running stack up")}
        if not stopped.get("ok"):
            return {"healed": {}, "stopped": stopped, "restarted": False,
                    "detail": "supervisor refused the stop"}
    healed = stack.self_heal()
    started = False
    detail = ""
    try:
        body = _supervisor_post("/engine/start")
        started = (bool(body.get("ok"))
                   and str(body.get("state", "")) in ("starting", "warming",
                                                      "running"))
        detail = str(body.get("state", "")) or str(body.get("error", ""))
        if not started and body.get("error"):
            detail = str(body.get("error", ""))
    except Exception as e:
        detail = f"supervisor unreachable: {type(e).__name__}"
    return {"healed": healed, "stopped": stopped, "restarted": started,
            "detail": detail}


def capture_before_restart(h: dict) -> tuple[dict | None, str]:
    """Root-cause evidence for a degraded bridge or a feed substitution,
    gathered BEFORE any restart, because the restart destroys it (2026-07-17:
    caught, restarted, never root-caused). Returns (snapshot, notification
    note). No triggering condition returns (None, "")."""
    degraded = h.get("bridge_status") == "degraded"
    substitution = bool(h.get("feed_substitution"))
    if not degraded and not substitution:
        return None, ""
    snap = bridge_fd_snapshot()
    from ops import evidence
    condition = "bridge_degraded" if degraded else "feed_substitution"
    evidence.capture(condition, {"health": h, "bridge": snap})
    note = (f" Bridge fds {snap.get('fd_count', '?')}, sockets "
            f"{snap.get('socket_count', '?')} (pid "
            f"{snap.get('bridge_pid', '?')}), captured before restart.")
    return snap, note


def run_once(cfg: dict | None = None) -> dict:
    """One watchdog cycle. On a healthy stack: no action. On a kill trip: notify,
    NEVER restart (manual resume required). On an unhealthy stack: capture
    evidence if the failure is a degraded bridge or a feed substitution, then
    attempt one restart and notify the outcome. Returns the cycle result."""
    cfg = cfg if cfg is not None else _cfg()
    h = check_health(cfg)
    if h["kill_tripped"]:
        notify("Kill switch TRIPPED. Trading halted. Manual resume required. "
               "Watchdog will NOT auto-resume.", cfg)
        return {"action": "kill_notified", "health": h}
    if h["healthy"]:
        return {"action": "none", "health": h}
    # Unhealthy and not a kill trip: evidence first, one clean restart attempt,
    # then notify.
    snap, note = capture_before_restart(h)
    r = attempt_restart()
    if r["restarted"]:
        notify(f"Stack unhealthy ({_status_line(h)}). Restarted via supervisor "
               f"(state {r['detail']}).{note}", cfg)
        return {"action": "restarted", "health": h, "restart": r,
                "bridge_snapshot": snap}
    notify(f"Stack DOWN ({_status_line(h)}). Restart FAILED ({r['detail']}). "
           f"Manual attention needed.{note}", cfg)
    return {"action": "restart_failed", "health": h, "restart": r,
            "bridge_snapshot": snap}


def _symbols_note(symbols: list, cap: int = 4) -> str:
    shown = ", ".join(symbols[:cap])
    return shown + ("..." if len(symbols) > cap else "")


def _status_line(h: dict) -> str:
    bridge = ("up" if h["bridge"]
              else ("DEGRADED" if h.get("bridge_status") == "degraded"
                    else "DOWN"))
    if not h.get("feed_ok", h["feed_fresh"]):
        stale = h.get("feed_stale_symbols") or []
        non_real = h.get("feed_non_real_symbols") or []
        if not h["feed_fresh"] and stale:
            feed = f"STALE ({_symbols_note(stale)})"
        elif not h["feed_fresh"]:
            feed = "STALE"
        elif non_real:
            feed = (f"NON-REAL ({h.get('feed_source', 'unknown')}: "
                    f"{_symbols_note(non_real)})")
        else:
            feed = f"NON-REAL ({h.get('feed_source', 'unknown')})"
    else:
        feed = "fresh"
    return (f"engine={'up' if h['engine'] else 'DOWN'} "
            f"bridge={bridge} "
            f"backend={'up' if h['backend'] else 'DOWN'} "
            f"feed={feed}")


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

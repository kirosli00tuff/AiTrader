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

Three guards keep remediation honest (2026-07-20, the loop that killed every
fresh start on leftover synthetic rows): substitution is judged only on bars
inside a recency window, feed conditions inside the startup grace are logged
but not remediated, and a condition recurring right after a restart escalates
to notify-and-hold instead of stopping the stack again.

THE TRADEABLE INVARIANT AND SCOPED STOP AUTHORITY (2026-07-20, after two
unserviceable symbols stopped a stack where six were trading correctly): a
symbol with no real bar history fails ``symbol_is_tradeable``
(market_data/tradeable.py) and can only ever raise ``symbol_unavailable``,
contained and per-symbol, never staleness and never substitution. The feed is
broken only when a substitution is live on a tradeable symbol or when nothing
is being served (``any_tradeable_serving``): while any tradeable symbol
receives real bars on time, staleness elsewhere is named but never stops the
stack.

Run as a separate process: ``python -m ops.watchdog`` (the start script launches
it and the teardown stops it).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone

from api_server import stack

log = logging.getLogger("ops.watchdog")


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

# THE tradeable invariant (2026-07-20): the one predicate and the one real
# source set, defined in market_data/tradeable.py. The watchdog consumes it,
# it does not re-derive it.
from market_data.tradeable import (REAL_SOURCES,  # noqa: E402
                                   symbol_is_tradeable)


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


def feed_ok(threshold_seconds: int, db: str | None = None,
            recency_window_seconds: int | None = None) -> dict:
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

    Provenance is judged ONLY on bars inside the recency window (default: the
    staleness threshold). A non-real bar older than the window is historical
    evidence from a prior run, recorded in ``out_of_window_non_real`` and the
    per-symbol detail, never a substitution: on 2026-07-20 leftover synthetic
    rows from the 2026-07-19 outage read as a live substitution and every
    fresh start was stopped before it could fetch a single live bar. No bar
    inside the window is a freshness question, not a substitution question.

    THE TRADEABLE INVARIANT (2026-07-20): a symbol with no real bar history
    (the ``symbol_is_tradeable`` predicate, market_data/tradeable.py) is
    UNAVAILABLE, never stale and never substituted. It lands in
    ``unavailable_symbols`` with per-symbol reason ``symbol_unavailable``,
    reported and logged, and never contributes to any stack-level alarm. This
    covers both the zero-bar shape and the fabricated-synthetic-bars shape:
    on 2026-07-20 MANA/USD and RUNE/USD carried nothing but in-window
    synthetic bars, read as a live substitution, and two unserviceable
    symbols stopped a stack where six were trading correctly.

    STOP AUTHORITY IS SCOPED (Task 4, 2026-07-20): the feed is broken only
    when a substitution is live on a tradeable symbol, or when tradeable
    symbols are stale and NONE is being served (``any_tradeable_serving``).
    Staleness on some symbols while others receive real bars on time is a
    contained, named condition, not grounds to stop the stack.
    """
    db = db or _db_path()
    real_path = _real_feed_mode()
    now = datetime.now(timezone.utc)
    equities_open = _equity_market_open()
    recency = (int(recency_window_seconds)
               if recency_window_seconds is not None
               else int(threshold_seconds))
    out: dict = {"fresh": False, "real": False, "ok": False,
                 "source": "unknown", "provenance_checked": False,
                 "real_path": real_path, "symbols": {}, "stale_symbols": [],
                 "non_real_symbols": [], "unavailable_symbols": [],
                 "serving_symbols": [], "out_of_window_non_real": [],
                 "recency_window_seconds": recency, "checked_count": 0}
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
            # THE predicate, consulted for every symbol before any freshness
            # or provenance judgment. On a pre-migration DB it degrades to
            # any-bar history inside the predicate itself.
            if not symbol_is_tradeable(conn, sym):
                out["symbols"][sym] = {
                    "checked": True, "tradeable": False, "fresh": None,
                    "source": str(row[1]) if row and row[1] else "none",
                    "reason": "symbol_unavailable"}
                out["unavailable_symbols"].append(sym)
                continue
            if not row or not row[0]:
                # Tradeable per predicate but no newest row resolves: an
                # unreadable read. Report without judging.
                out["symbols"][sym] = {"checked": True, "tradeable": True,
                                       "fresh": None, "source": "none",
                                       "reason": "unreadable"}
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
                "checked": True, "tradeable": True, "fresh": fresh,
                "source": source,
                "age_seconds": None if age is None else int(age)}
            if not fresh:
                out["stale_symbols"].append(sym)
            if fresh and source in REAL_SOURCES:
                out["serving_symbols"].append(sym)
            if provenance_checked and source not in REAL_SOURCES:
                # Substitution needs proof the bar reflects the CURRENT run.
                # An unparseable timestamp cannot prove recency and freshness
                # already catches it, so it reads out-of-window here.
                if age is not None and age <= recency:
                    out["non_real_symbols"].append(sym)
                else:
                    out["symbols"][sym]["provenance"] = "out_of_window"
                    out["out_of_window_non_real"].append(sym)
    finally:
        conn.close()
    out["checked_count"] = sum(
        1 for d in out["symbols"].values() if d.get("checked"))
    out["provenance_checked"] = provenance_checked
    # Freshness reports over TRADEABLE symbols only. Zero checkable symbols
    # (an all-equity universe overnight) is a closed market, not a stale feed,
    # and an unavailable symbol is not a stale one: it was never fresh.
    out["fresh"] = not out["stale_symbols"]
    out["real"] = not out["non_real_symbols"]
    # Aggregate source for the status line: the worst news wins.
    if out["non_real_symbols"]:
        out["source"] = out["symbols"][out["non_real_symbols"][0]].get(
            "source", "unknown")
    else:
        for d in out["symbols"].values():
            if d.get("checked") and d.get("tradeable"):
                out["source"] = d.get("source", "unknown")
                break
    if real_path and provenance_checked:
        # Substitution is ALWAYS broken (the emergency, kept at full
        # strength). Staleness is broken only when nothing is being served:
        # if any tradeable symbol receives real bars on time the feed is not
        # broken, however many unserviceable symbols exist.
        broken = bool(out["non_real_symbols"]) or (
            bool(out["stale_symbols"]) and not any_tradeable_serving(out))
        out["ok"] = not broken
    else:
        out["ok"] = out["fresh"]
    return out


def any_tradeable_serving(feed: dict) -> bool:
    """THE stop-authority predicate (Task 4, 2026-07-20).

    True when any tradeable symbol is currently receiving real bars on time
    (fresh AND real provenance). While this holds, the feed is not broken and
    stack-wide remediation is not warranted by staleness or by any number of
    unserviceable symbols. A live substitution on a tradeable symbol OUTRANKS
    this predicate deliberately: a symbol with real history receiving non-real
    bars is the emergency, and its remediation is not weakened here.
    """
    return bool(feed.get("serving_symbols"))


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
    recency = int(cfg.get("substitution_recency_window_seconds", 900))
    running = stack.stack_running()
    bstate = bridge_state()
    bridge_ok = bool(bstate["reachable"] and bstate["status"] == "ok")
    backend_ok = stack.http_ok(stack.api_health_url(), tries=1, delay=0)
    feed = feed_ok(stale, recency_window_seconds=recency)
    tripped = kill_tripped()
    # Fresh but non-real on the real path is the substitution state: the walk
    # fallback advancing in live clothing. Judged only on bars inside the
    # recency window; an older non-real bar is historical evidence.
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
            # symbol_unavailable (never served, contained) and
            # feed_substitution (served, now non-real, emergency) are DISTINCT
            # conditions and never share an alarm: unavailable symbols cannot
            # reach non_real_symbols by construction (feed_ok consults the
            # tradeable predicate first).
            "feed_symbol_unavailable": list(
                feed.get("unavailable_symbols", [])),
            "feed_serving": any_tradeable_serving(feed),
            "feed_serving_symbols": list(feed.get("serving_symbols", [])),
            "feed_out_of_window_non_real": list(
                feed.get("out_of_window_non_real", [])),
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


def _engine_age_seconds() -> float | None:
    """Seconds since the ENGINE process started, from /proc via the engine pid
    in the lock, falling back to the lock's ts. None when it cannot be
    established (no lock, dead pid), which reads as PAST the grace period: an
    unprovable grace must never suppress detection forever."""
    try:
        lk = stack.lock_status()
        pid = lk.get("engine_pid")
        if not pid or not lk.get("alive"):
            return None
        from ops import evidence
        epoch = evidence.process_start_epoch(int(pid))
        if epoch is not None:
            return max(0.0, time.time() - epoch)
        ts = lk.get("ts")
        if ts:
            started = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            return max(0.0, (datetime.now(timezone.utc)
                             - started).total_seconds())
    except Exception:
        return None
    return None


# --- remediation loop guard --------------------------------------------------
# The watchdog must never stop a stack it has just started. On 2026-07-20
# every fresh start was stopped seconds later on the same (historical)
# substitution reading, a remediation loop with no exit. The guard persists
# the last restart across cycles AND across watchdog restarts: the same
# condition recurring within the hold window escalates to notify-and-hold,
# and max_restarts_per_hour caps restarts across ALL conditions (catches an
# A/B/A/B alternation the same-condition check cannot see). A holding
# watchdog leaves the stack exactly as it is, because repeatedly stopping a
# stack that cannot stay up guarantees no data and no diagnosis.

def _state_path() -> str:
    return os.path.join(stack.run_dir(), "watchdog_state.json")


def _load_state() -> dict:
    try:
        with open(_state_path()) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(d: dict) -> None:
    try:
        os.makedirs(stack.run_dir(), exist_ok=True)
        with open(_state_path(), "w") as fh:
            json.dump(d, fh, indent=2)
    except Exception:
        pass  # the guard is advisory state, never a crash


def _clear_state() -> None:
    try:
        os.remove(_state_path())
    except OSError:
        pass


def _condition_key(h: dict) -> str:
    """One stable name for WHAT is failing, so recurrence is comparable
    across cycles. Sick-but-running shapes first, then down shapes, then
    plain staleness."""
    if h.get("bridge_status") == "degraded":
        return "bridge_degraded"
    if h.get("feed_substitution"):
        return "feed_substitution"
    if not h.get("engine"):
        return "engine_down"
    if not h.get("bridge"):
        return "bridge_down"
    if not h.get("backend"):
        return "backend_down"
    if not h.get("feed_fresh", True):
        return "feed_stale"
    return "unhealthy"


# Last-logged unavailable set, so run_once logs the condition once per change
# rather than once per poll. A one-element list so run_once can rebind it.
_unavailable_logged: list = [set()]


def run_once(cfg: dict | None = None) -> dict:
    """One watchdog cycle. On a healthy stack: no action (and any remediation
    hold is released). On a kill trip: notify, NEVER restart (manual resume
    required). On an unhealthy stack: feed-only conditions inside the startup
    grace are logged, not remediated; a condition recurring right after a
    restart escalates to notify-and-hold; otherwise capture evidence (degraded
    bridge or feed substitution), attempt one restart, and notify the
    outcome. Returns the cycle result."""
    cfg = cfg if cfg is not None else _cfg()
    h = check_health(cfg)
    unavailable = set(h.get("feed_symbol_unavailable") or [])
    if unavailable != _unavailable_logged[0]:
        # Logged on CHANGE, not every cycle: contained, per-symbol, warrants
        # pruning, never remediation.
        if unavailable:
            log.warning(
                "watchdog: symbol_unavailable (never received a real bar, "
                "not tradeable, contained): %s", ", ".join(sorted(unavailable)))
        else:
            log.info("watchdog: all previously unavailable symbols resolved")
        _unavailable_logged[0] = unavailable
    if h.get("feed_out_of_window_non_real"):
        log.info("watchdog: non-real bars OUTSIDE the recency window for %s: "
                 "historical evidence from a prior run, not a substitution",
                 ", ".join(h["feed_out_of_window_non_real"]))
    if h["kill_tripped"]:
        notify("Kill switch TRIPPED. Trading halted. Manual resume required. "
               "Watchdog will NOT auto-resume.", cfg)
        return {"action": "kill_notified", "health": h}
    if h["healthy"]:
        prior = _load_state()
        if prior:
            _clear_state()
            if prior.get("holding"):
                notify("Recovered: stack healthy again. Remediation hold "
                       "released.", cfg)
        return {"action": "none", "health": h}
    # Startup grace: a stack that has not lived one bar interval cannot have
    # fetched live data, so feed conditions (stale, substitution) are observed
    # and logged, never remediated. Engine, bridge, and backend failures are
    # NOT grace-suppressed: a degraded bridge is sick at any age.
    grace = int(cfg.get("startup_grace_seconds", 900))
    feed_only = bool(h["engine"] and h["bridge"] and h["backend"])
    age = _engine_age_seconds()
    if feed_only and age is not None and age < grace:
        log.warning(
            "watchdog: %s observed %ds after engine start, inside the %ds "
            "startup grace: logged, NOT remediated (%s)",
            _condition_key(h), int(age), grace, _status_line(h))
        return {"action": "grace_observed", "health": h,
                "engine_age_seconds": int(age), "grace_seconds": grace}
    # Loop guard: the same condition recurring within the hold window of the
    # last restart, or the hourly restart cap, escalates to notify-and-hold.
    cond = _condition_key(h)
    now = time.time()
    st = _load_state()
    hold_window = int(cfg.get("remediation_hold_window_seconds", 1800))
    max_per_hour = int(cfg.get("max_restarts_per_hour", 3))
    history = [t for t in st.get("restart_history", [])
               if isinstance(t, (int, float)) and now - t <= 3600.0]
    holding = bool(st.get("holding") and st.get("condition") == cond)
    same_recent = bool(
        st.get("condition") == cond and st.get("last_restart_ts")
        and now - float(st["last_restart_ts"]) <= hold_window)
    rate_capped = len(history) >= max_per_hour
    if holding or same_recent or rate_capped:
        attempts = int(st.get("attempts", 1))
        reason = ("remediation_loop" if (holding or same_recent)
                  else "restart_rate_cap")
        last_note = float(st.get("last_hold_notify_ts", 0.0) or 0.0)
        due = (not st.get("holding")) or (now - last_note >= hold_window)
        if due:
            notify(f"REMEDIATION HOLD ({reason}): {cond} recurred after "
                   f"{attempts} restart attempt(s). Leaving the stack AS IS, "
                   f"no further automatic restarts until it recovers or an "
                   f"operator intervenes. ({_status_line(h)})", cfg)
        _save_state({"condition": cond, "holding": True, "attempts": attempts,
                     "last_restart_ts": st.get("last_restart_ts"),
                     "restart_history": history,
                     "last_hold_notify_ts": now if due else last_note})
        return {"action": "hold", "reason": reason, "health": h,
                "attempts": attempts}
    # Evidence first, one clean restart attempt, then notify. The attempt is
    # recorded whether or not it succeeds, so a failing restart cannot loop
    # either.
    snap, note = capture_before_restart(h)
    r = attempt_restart()
    history.append(now)
    _save_state({"condition": cond, "holding": False,
                 "attempts": (int(st.get("attempts", 0)) + 1
                              if st.get("condition") == cond else 1),
                 "last_restart_ts": now, "restart_history": history,
                 "last_hold_notify_ts": 0.0})
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
        if non_real:
            feed = (f"NON-REAL ({h.get('feed_source', 'unknown')}: "
                    f"{_symbols_note(non_real)})")
        elif not h["feed_fresh"] and stale:
            feed = f"STALE ({_symbols_note(stale)})"
        elif not h["feed_fresh"]:
            feed = "STALE"
        else:
            feed = f"NON-REAL ({h.get('feed_source', 'unknown')})"
    elif h.get("feed_stale_symbols"):
        # Contained staleness: some symbols lag while others are served real
        # bars on time. Named, never grounds to stop the stack.
        feed = f"serving (stale contained: {_symbols_note(h['feed_stale_symbols'])})"
    else:
        feed = "fresh"
    unavailable = h.get("feed_symbol_unavailable") or []
    suffix = (f" symbol_unavailable({_symbols_note(unavailable)})"
              if unavailable else "")
    return (f"engine={'up' if h['engine'] else 'DOWN'} "
            f"bridge={bridge} "
            f"backend={'up' if h['backend'] else 'DOWN'} "
            f"feed={feed}{suffix}")


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

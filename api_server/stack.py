"""Shared start-stack callable, used by BOTH the GUI supervisor and the bash
start script (scripts/start_paper_trading.sh), so the two reuse one source of
truth instead of duplicating the sequence.

It owns the whitelist, the warm-state report, the component commands (backfill,
bridge, engine), the health checks, and the single-instance lock. The lock file
lives in the control dir next to the kill-request file.

Safety contract: nothing here touches the RiskGate, the live path, or an
operational table. It never writes or reads the kill-request control file, so
the kill switch stays independent of start/stop. Process control (spawn, sleep,
http_ok, run_backfill, warm_report, pid_alive) is factored into module-level
functions so tests can mock them with no real network or subprocess.
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import time
import urllib.request

from api_server import store

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Whitelist warm defaults, mirroring signal_engine/strategy.cpp min_bars_to_warm.
_EMA_SLOW, _ATR, _BB, _RSI, _VLB = 100, 14, 20, 14, 20


# --- paths / config ----------------------------------------------------------

def repo_root() -> str:
    return _REPO_ROOT


def _control_dir() -> str:
    env = os.environ.get("MAL_CONTROL_DIR")
    if env:
        return env
    sys_cfg = store.load_config().get("system", {}) or {}
    return sys_cfg.get("control_dir") or os.path.join(_REPO_ROOT, ".control")


def run_dir() -> str:
    """Runtime dir under the repo for logs and the pid/lock files."""
    return os.environ.get("MAL_RUN_DIR", os.path.join(_REPO_ROOT, ".run"))


def db_path() -> str:
    return os.environ.get("MAL_DB_PATH",
                          os.path.join(_REPO_ROOT, "market_ai_lab.db"))


def python_bin() -> str:
    return os.environ.get("MAL_PYTHON",
                          os.path.join(_REPO_ROOT, ".venv", "bin", "python"))


def engine_bin() -> str:
    return os.path.join(_REPO_ROOT, "build", "mal_engine")


def bridge_port() -> int:
    return int(os.environ.get("BRIDGE_PORT", "8765"))


def api_port() -> int:
    return int(os.environ.get("MAL_API_PORT", "8000"))


def vite_port() -> int:
    return int(os.environ.get("MAL_VITE_PORT", "5173"))


def interval_seconds() -> int:
    return int(os.environ.get("MAL_INTERVAL_SECONDS", "30"))


def whitelist() -> list[str]:
    strat = store.load_config().get("strategy", {}) or {}
    raw = str(strat.get("whitelist", "BTC/USD,ETH/USD,SPY,QQQ"))
    return [s.strip() for s in raw.split(",") if s.strip()]


def _strat_int(cfg: dict, key: str, default: int) -> int:
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def warm_need() -> int:
    """Longest indicator lookback, mirroring strategy::min_bars_to_warm."""
    cfg = store.load_config().get("strategy", {}) or {}
    ema = _strat_int(cfg, "ema_slow", _EMA_SLOW)
    atr = _strat_int(cfg, "atr_period", _ATR)
    bb = _strat_int(cfg, "bb_period", _BB)
    rsi = _strat_int(cfg, "rsi_period", _RSI)
    vlb = _strat_int(cfg, "vol_lookback", _VLB)
    return max(ema + 2, 2 * atr + 1, atr + 1, bb, rsi + 2, vlb, vlb + 1)


def bar_timeframe() -> str:
    cfg = store.load_config().get("strategy", {}) or {}
    return str(cfg.get("bar_timeframe", "5min"))


# --- command builders --------------------------------------------------------

def backfill_cmd(db: str | None = None) -> list[str]:
    return [python_bin(), "-m", "market_data.alpaca_source",
            "--db", db or db_path()]


def bridge_cmd() -> list[str]:
    return [python_bin(), "-m", "python_bridge.server"]


def whale_env() -> dict:
    """The whale live flags the bridge needs, read from config. The whale library
    treats SEC_EDGAR_ENABLED / WHALE_LIVE_ENABLED as env opt-ins (default OFF), so
    a deliberate start must export them or the bridge reports whale_real=false and
    the engine's strict on-real check refuses. The script and the GUI supervisor
    BOTH build the bridge env here so they cannot drift."""
    try:
        cfg = store.load_config().get("whale", {}) or {}
    except Exception:
        cfg = {}

    def _b(v) -> str:
        return "true" if v else "false"

    return {"SEC_EDGAR_ENABLED": _b(cfg.get("sec_edgar_enabled")),
            "WHALE_LIVE_ENABLED": _b(cfg.get("whale_live_enabled"))}


def bridge_env() -> dict:
    """Full environment the bridge is spawned with: the port plus the whale
    live flags. Reused by the supervisor so a GUI start matches the script."""
    return {"BRIDGE_PORT": str(bridge_port()), **whale_env()}


def bridge_missing_real_layers() -> list[str]:
    """After the bridge is healthy, report which ON-REAL layers (per controls.json)
    the bridge does NOT yet serve as real, so the supervisor can fail with a clear
    reason BEFORE the engine starts and exits cryptically. Best-effort: returns []
    when /status cannot be read, so the engine stays the authority."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{bridge_port()}/status", timeout=5) as r:
            st = json.loads(r.read().decode())
    except Exception:
        return []
    try:
        from api_server import controls
        ctl = controls.read_controls()
        layers = ctl.get("layers", {}) or {}
        srcs = ctl.get("layer_sources", {}) or {}
    except Exception:
        layers, srcs = {}, {}

    def _on_real(layer: str) -> bool:
        return bool(layers.get(layer, True)) and srcs.get(layer, "real") == "real"

    missing = []
    if _on_real("council") and not st.get("council_real"):
        missing.append("LLM council: " + str(st.get("council_detail", "not real")))
    if _on_real("dnn_advisory") and not st.get("dnn_real"):
        missing.append("dnn_advisory: " + str(st.get("dnn_detail", "not real")))
    if _on_real("whale") and not st.get("whale_real"):
        missing.append("whale: " + str(st.get("whale_detail", "not real")))
    return missing


def engine_cmd(db: str | None = None) -> list[str]:
    return [engine_bin(), "--continuous",
            "--interval-seconds", str(interval_seconds()),
            "--feed-mode", "alpaca_paper", "--clock-mode", "real",
            "--bridge", f"127.0.0.1:{bridge_port()}",
            "--db", db or db_path()]


def bridge_health_url() -> str:
    return f"http://127.0.0.1:{bridge_port()}/health"


def api_health_url() -> str:
    return f"http://127.0.0.1:{api_port()}/health"


# --- warm report (no network) -----------------------------------------------

def warm_report(db: str | None = None) -> dict:
    """Per-symbol warm state from the bars table. Read-only, no network.

    Mirrors the script's PYWARM block: a symbol is warm when it holds at least
    `warm_need` bars at the configured timeframe. A cold symbol is only a
    warning, the engine's warm-state gate holds it back and never trades on
    partial data.
    """
    db = db or db_path()
    need = warm_need()
    tf = bar_timeframe()
    symbols = []
    all_warm = True
    try:
        con = sqlite3.connect(db)
        try:
            for sym in whitelist():
                try:
                    n = con.execute(
                        "SELECT COUNT(*) FROM bars WHERE symbol=? AND timeframe=?",
                        (sym, tf)).fetchone()[0]
                except Exception:
                    n = 0
                warm = n >= need
                all_warm = all_warm and warm
                symbols.append({"symbol": sym, "bars": int(n), "warm": warm})
        finally:
            con.close()
    except Exception:
        all_warm = False
    return {"need": need, "timeframe": tf, "symbols": symbols,
            "all_warm": all_warm and bool(symbols)}


# --- process control (mockable in tests) ------------------------------------

def sleep(seconds: float) -> None:
    time.sleep(seconds)


def spawn(cmd: list[str], env: dict | None = None,
          log_path: str | None = None) -> subprocess.Popen:
    """Launch a detached child, redirecting output to log_path when given."""
    out = None
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        out = open(log_path, "ab", buffering=0)
    full_env = {**os.environ, **(env or {})}
    return subprocess.Popen(cmd, stdout=out or subprocess.DEVNULL,
                            stderr=subprocess.STDOUT if out else subprocess.DEVNULL,
                            env=full_env, cwd=_REPO_ROOT,
                            start_new_session=True)


def run_backfill(db: str | None = None) -> None:
    """Backfill real Alpaca bars into the bars table. Best-effort, like the
    script's `|| true`: a missing key is a warning, the warm gate holds cold
    symbols back."""
    try:
        subprocess.run(backfill_cmd(db), cwd=_REPO_ROOT, timeout=600,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def http_ok(url: str, tries: int = 40, delay: float = 0.5) -> bool:
    """Poll a URL until it returns HTTP 200 or tries run out."""
    for _ in range(max(1, tries)):
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        sleep(delay)
    return False


def pid_alive(pid: int) -> bool:
    """True if the pid names a live process. A pid we cannot signal (permission)
    still counts as alive."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def terminate(proc, timeout: float = 8.0) -> None:
    """Graceful terminate then force kill. Accepts a Popen or None."""
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
        proc.terminate()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                return
            sleep(0.2)
        proc.kill()
    except Exception:
        pass


def terminate_pid(pid: int, timeout: float = 8.0) -> bool:
    """Graceful terminate then force kill of a bare pid (a foreign process we do
    not hold a handle to). Returns True if it is not alive afterward."""
    if not pid_alive(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not pid_alive(pid):
                return True
            sleep(0.2)
        os.kill(pid, signal.SIGKILL)
        sleep(0.2)
    except Exception:
        pass
    return not pid_alive(pid)


# --- single-instance lock (control dir, never the kill-request file) --------

def lock_path() -> str:
    return os.path.join(_control_dir(), "engine.lock")


def read_lock() -> dict | None:
    try:
        with open(lock_path()) as fh:
            return json.load(fh)
    except Exception:
        return None


def write_lock(engine_pid: int, bridge_pid: int | None = None,
               source: str = "supervisor") -> dict:
    os.makedirs(_control_dir(), exist_ok=True)
    rec = {"engine_pid": int(engine_pid),
           "bridge_pid": int(bridge_pid) if bridge_pid else None,
           "source": source,
           "ts": store._now() if hasattr(store, "_now") else None}
    with open(lock_path(), "w") as fh:
        json.dump(rec, fh, indent=2)
    return rec


def clear_lock() -> None:
    try:
        os.remove(lock_path())
    except FileNotFoundError:
        pass
    except Exception:
        pass


def lock_status() -> dict:
    """Report the lock: present, its pids, whether the engine pid is alive, and
    whether it is stale (present but the engine pid is dead)."""
    rec = read_lock()
    if not rec:
        return {"present": False, "alive": False, "stale": False,
                "engine_pid": None, "bridge_pid": None, "source": None}
    epid = rec.get("engine_pid")
    alive = pid_alive(epid) if epid else False
    return {"present": True, "alive": alive, "stale": not alive,
            "engine_pid": epid, "bridge_pid": rec.get("bridge_pid"),
            "source": rec.get("source"), "ts": rec.get("ts")}


def seed_feed_clock() -> None:
    """Seed controls.json feed=alpaca_paper clock=real so the GUI and engine
    agree from the first tick. Best-effort, mirrors the script's seed step."""
    try:
        from api_server import controls
        controls.set_feed_clock("alpaca_paper", "real")
    except Exception:
        pass


# --- pre-flight port cleanup (self-clean a prior run holding a port) --------
# Only the exact ports this stack owns, never a blanket kill. port_holders is the
# mockable seam. free_port always protects our own pid, so the supervisor can
# never kill the backend process it runs in.

def stack_ports() -> dict:
    return {"bridge": bridge_port(), "api": api_port(), "vite": vite_port()}


def port_holders(port: int) -> list[int]:
    """PIDs listening on a local TCP port. Best-effort via lsof then ss. Returns
    [] when it cannot tell, it never guesses a pid."""
    pids: set[int] = set()
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5)
        for line in out.stdout.split():
            if line.strip().isdigit():
                pids.add(int(line.strip()))
        if pids:
            return sorted(pids)
    except Exception:
        pass
    try:
        import re
        out = subprocess.run(["ss", "-tlnp", f"sport = :{port}"],
                             capture_output=True, text=True, timeout=5)
        for m in re.finditer(r"pid=(\d+)", out.stdout):
            pids.add(int(m.group(1)))
    except Exception:
        pass
    return sorted(pids)


def free_port(port: int, label: str, exclude_pids=()) -> dict:
    """Terminate any process holding `port`, gracefully then force. Only this
    port, never a blanket kill. Always protects our own pid and exclude_pids."""
    protect = set(exclude_pids) | {os.getpid()}
    holders = [p for p in port_holders(port) if p not in protect]
    if not holders:
        return {"port": port, "label": label, "action": "free", "pids": []}
    cleared = [pid for pid in holders if terminate_pid(pid)]
    return {"port": port, "label": label, "action": "cleared", "pids": cleared}


def preflight_ports(names=None, exclude_pids=()) -> list[dict]:
    """Free the named stack ports (default all) of stale holders. The supervisor
    passes names=["bridge"] so it never touches the port it is served on."""
    ports = stack_ports()
    if names is None:
        names = list(ports.keys())
    return [free_port(ports[n], n, exclude_pids) for n in names if n in ports]


# --- pid tracking + clean teardown (self-heal a crashed prior run) ----------

def pids_path() -> str:
    return os.path.join(run_dir(), "pids")


def read_pids() -> dict:
    try:
        with open(pids_path()) as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_pids(d: dict) -> None:
    os.makedirs(run_dir(), exist_ok=True)
    with open(pids_path(), "w") as fh:
        json.dump(d, fh, indent=2)


def record_pid(name: str, pid) -> None:
    d = read_pids()
    try:
        d[name] = int(pid)
    except (TypeError, ValueError):
        return
    d["ts"] = store._now()
    _write_pids(d)


def remove_pid(name: str) -> None:
    d = read_pids()
    if name in d:
        d.pop(name, None)
        _write_pids(d)


def clear_pids() -> None:
    try:
        os.remove(pids_path())
    except FileNotFoundError:
        pass
    except Exception:
        pass


def tracked_pids() -> dict:
    return {k: v for k, v in read_pids().items()
            if k != "ts" and isinstance(v, int)}


def stop_tracked_pids() -> list[dict]:
    """Stop every recorded pid gracefully then force, then clear the file. Used
    by teardown and by self-heal of a crashed prior run."""
    out = []
    for name, pid in tracked_pids().items():
        if pid_alive(pid):
            out.append({"name": name, "pid": pid, "stopped": terminate_pid(pid)})
        else:
            out.append({"name": name, "pid": pid, "stopped": True,
                        "already_dead": True})
    clear_pids()
    return out


def stack_running() -> dict:
    """A healthy stack: the engine pid (from the lock, else the pid file) is alive
    AND a health check passes on the bridge or the backend. The single-instance
    guard refuses a duplicate start when this is true, instead of fighting for
    ports. It reads the kill-request file NOWHERE."""
    lk = lock_status()
    epid = lk["engine_pid"] if lk["alive"] else tracked_pids().get("engine")
    engine_alive = bool(epid) and pid_alive(epid)
    healthy = bool(engine_alive) and (
        http_ok(bridge_health_url(), tries=1, delay=0)
        or http_ok(api_health_url(), tries=1, delay=0))
    return {"running": bool(engine_alive and healthy), "engine_pid": epid,
            "engine_alive": bool(engine_alive), "healthy": bool(healthy)}


def self_heal() -> dict:
    """Clean a crashed prior run: stop any still-alive tracked pids, clear the
    pid file, and clear a stale engine lock. Refuses to run when a healthy stack
    is up (that is a duplicate, not a crash). Never touches the kill-request
    file."""
    if stack_running()["running"]:
        return {"skipped": "a healthy stack is already running"}
    lk = lock_status()
    stopped = stop_tracked_pids()
    cleared_lock = bool(lk["present"] and lk["stale"])
    if cleared_lock:
        clear_lock()
    return {"stopped": stopped, "cleared_stale_lock": cleared_lock}


# --- CLI for the bash script (shared logic, not duplicated) -----------------

def _cli(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "warm-report":
        rep = warm_report()
        print(f"warm needs >= {rep['need']} {rep['timeframe']} bars per symbol")
        for s in rep["symbols"]:
            print(f"  {s['symbol']}: {s['bars']} bars -> "
                  f"{'WARM' if s['warm'] else 'COLD'}")
        return 0 if rep["all_warm"] else 3
    if cmd == "lock-status":
        print(json.dumps(lock_status()))
        return 0
    if cmd == "clear-lock":
        clear_lock()
        print("lock cleared")
        return 0
    if cmd == "bridge-env-export":
        # Shell-eval-able export lines for the whale flags the bridge needs, so
        # the start script reuses the SAME whale_env logic as the supervisor.
        for k, v in whale_env().items():
            print(f"export {k}={v}")
        return 0
    if cmd == "preflight":
        names = argv[1:] or None
        for r in preflight_ports(names):
            if r["action"] == "free":
                print(f"port {r['port']} ({r['label']}): free already")
            else:
                print(f"port {r['port']} ({r['label']}): cleared stale pid(s) {r['pids']}")
        return 0
    if cmd == "self-heal":
        res = self_heal()
        if res.get("skipped"):
            print(f"self-heal skipped: {res['skipped']}")
            return 0
        for s in res["stopped"]:
            extra = " (already dead)" if s.get("already_dead") else ""
            print(f"stopped {s['name']} pid {s['pid']}{extra}")
        if res["cleared_stale_lock"]:
            print("cleared stale engine lock")
        if not res["stopped"] and not res["cleared_stale_lock"]:
            print("nothing to clean")
        return 0
    if cmd == "stack-running":
        st = stack_running()
        print(json.dumps(st))
        return 0 if st["running"] else 1
    if cmd == "record-pid":
        if len(argv) >= 3:
            record_pid(argv[1], argv[2])
            print(f"recorded {argv[1]}={argv[2]}")
            return 0
        print("usage: record-pid <name> <pid>")
        return 2
    if cmd == "clear-pids":
        clear_pids()
        print("pids cleared")
        return 0
    if cmd == "stop-tracked":
        for s in stop_tracked_pids():
            print(f"stopped {s['name']} pid {s['pid']}")
        return 0
    print(f"unknown stack command: {cmd}", flush=True)
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))

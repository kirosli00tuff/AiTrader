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
    print(f"unknown stack command: {cmd}", flush=True)
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))

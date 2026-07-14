"""Engine + bridge lifecycle owner for the GUI Start/Stop controls.

The supervisor owns start and stop of the warmed paper-trading stack from the
GUI. It runs the SAME sequence as scripts/start_paper_trading.sh through the
shared api_server.stack callable (backfill, warm-verify, bridge, engine), health
checked between steps, and reports the lifecycle: not_running, starting, warming
(with per-symbol warm progress), running, stopping.

SAFETY, do not blur these:
  - The KILL SWITCH is not here. The C++ engine reads the kill-request control
    file itself at the top of every loop iteration, so a kill halts the engine
    even with this supervisor, the backend, and the whole GUI down. This module
    never writes or reads the kill-request file.
  - GUI STOP is a graceful shutdown of the processes the supervisor started. It
    is a different mechanism from the safety halt and never routes through the
    kill switch.
  - Nothing here touches the RiskGate, the live-trading gate, or an operational
    table.

Process control lives in api_server.stack (spawn, sleep, http_ok, run_backfill,
warm_report, pid_alive, the lock), so tests mock it with no real network or
subprocess.
"""
from __future__ import annotations

import os
import threading

from api_server import stack
from api_server import store

# Lifecycle states, exactly the set the prompt names.
NOT_RUNNING = "not_running"
STARTING = "starting"
WARMING = "warming"
RUNNING = "running"
STOPPING = "stopping"

# Seconds to let the engine settle before the strict-mode liveness check. The
# engine refuses to start (exits) when an on-real layer is unreachable, so if it
# is still alive after this window it passed strict mode. Mirrors the script's
# `sleep 3; kill -0`. Tests set stack.sleep to a no-op.
ENGINE_SETTLE_SECONDS = 3.0


def _log_tail(path: str, nbytes: int = 1400) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - nbytes))
            data = fh.read().decode("utf-8", "replace").strip()
        return data[-nbytes:]
    except Exception:
        return ""


class Supervisor:
    def __init__(self, source: str = "gui") -> None:
        self._lock = threading.RLock()
        self._state = NOT_RUNNING
        self._engine = None
        self._bridge = None
        self._error: str | None = None
        self._warm: list[dict] = []
        self._thread: threading.Thread | None = None
        self._started_ts: str | None = None
        self._history: list[dict] = []
        self._source = source

    # --- state ---------------------------------------------------------------

    def _set_state(self, s: str) -> None:
        self._state = s
        self._history.append({"state": s, "ts": store._now()})
        self._history = self._history[-24:]

    def _note(self, msg: str) -> None:
        self._history.append({"note": msg, "ts": store._now()})
        self._history = self._history[-24:]

    def _build_state(self) -> dict:
        st = self._state
        lk = stack.lock_status()
        # A foreign engine (started by the script or another process) shows as
        # running even though this supervisor does not own the handle.
        if st == NOT_RUNNING and lk["alive"]:
            report, owned = RUNNING, False
        else:
            report, owned = st, self._engine is not None
        return {
            "state": report,
            "owned": owned,
            "error": self._error,
            "warm": self._warm,
            "all_warm": all(s.get("warm") for s in self._warm) if self._warm else False,
            "engine_pid": (self._engine.pid if self._engine else lk.get("engine_pid")),
            "bridge_pid": (self._bridge.pid if self._bridge else lk.get("bridge_pid")),
            "bridge_port": stack.bridge_port(),
            "api_port": stack.api_port(),
            "interval_seconds": stack.interval_seconds(),
            "feed_mode": "alpaca_paper",
            "clock_mode": "real",
            "started_ts": self._started_ts,
            "lock": lk,
            "history": self._history[-12:],
            "whitelist": stack.whitelist(),
        }

    def state(self) -> dict:
        with self._lock:
            # Reconcile a crashed engine we thought was running.
            if (self._state == RUNNING and self._engine is not None
                    and self._engine.poll() is not None):
                self._error = self._error or "engine exited unexpectedly"
                stack.clear_lock()
                self._engine = None
                self._set_state(NOT_RUNNING)
            return self._build_state()

    # --- start ---------------------------------------------------------------

    def start(self, background: bool = True) -> dict:
        with self._lock:
            if self._state in (STARTING, WARMING, RUNNING, STOPPING):
                return {**self._build_state(), "ok": False,
                        "error": f"start refused: already {self._state}"}
            lk = stack.lock_status()
            if lk["alive"]:
                return {**self._build_state(), "ok": False,
                        "error": (f"start refused: an engine is already running "
                                  f"(pid {lk['engine_pid']}, source {lk['source']}). "
                                  "Stop it before starting a new one.")}
            if lk["present"] and lk["stale"]:
                stack.clear_lock()
                self._note(f"cleared stale lock (dead pid {lk['engine_pid']})")
            self._error = None
            self._warm = []
            self._started_ts = None
            self._set_state(STARTING)
        if background:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                             name="supervisor-start")
            self._thread.start()
        else:
            self._run()
        return {"ok": True, **self.state()}

    def _run(self) -> None:
        db = stack.db_path()
        logdir = stack.run_dir()
        try:
            # 1. Backfill real bars (best-effort, warm gate holds cold symbols).
            stack.run_backfill(db)
            # 2. Warm report + seed feed/clock. Cold is a warning, not a failure.
            self._warm = stack.warm_report(db)["symbols"]
            with self._lock:
                self._set_state(WARMING)
            stack.seed_feed_clock()
            self._warm = stack.warm_report(db)["symbols"]
            # 3. Pre-flight: free ONLY the bridge port of a stale holder from a
            # crashed prior run. Never the api port (this backend runs on it) or
            # the vite port. free_port protects our own pid regardless.
            stack.preflight_ports(names=["bridge"], exclude_pids={os.getpid()})
            # Bridge (real council + dnn + whale). Health check between steps.
            self._bridge = stack.spawn(
                stack.bridge_cmd(),
                env={"BRIDGE_PORT": str(stack.bridge_port())},
                log_path=os.path.join(logdir, "bridge.log"))
            stack.record_pid("bridge", self._bridge.pid)
            if not stack.http_ok(stack.bridge_health_url(), tries=40, delay=0.5):
                raise RuntimeError(
                    f"bridge did not become healthy on port {stack.bridge_port()}")
            # 4. Engine, strict mode. It exits if an on-real layer is unreachable.
            self._engine = stack.spawn(
                stack.engine_cmd(db),
                log_path=os.path.join(logdir, "engine.log"))
            stack.record_pid("engine", self._engine.pid)
            stack.sleep(ENGINE_SETTLE_SECONDS)
            if self._engine.poll() is not None:
                tail = _log_tail(os.path.join(logdir, "engine.log"))
                raise RuntimeError(
                    "engine exited on start. Strict mode may have refused an "
                    "on-real layer whose service is unreachable. " + tail)
            # 5. Record the single-instance lock, then running.
            stack.write_lock(self._engine.pid,
                             self._bridge.pid if self._bridge else None,
                             source=self._source)
            with self._lock:
                self._started_ts = store._now()
                self._set_state(RUNNING)
        except Exception as e:
            self._error = str(e)
            stack.terminate(self._engine)
            self._engine = None
            stack.terminate(self._bridge)
            self._bridge = None
            stack.remove_pid("engine")
            stack.remove_pid("bridge")
            stack.clear_lock()
            with self._lock:
                self._set_state(NOT_RUNNING)

    # --- stop (graceful shutdown, NOT the kill switch) -----------------------

    def stop(self) -> dict:
        with self._lock:
            lk = stack.lock_status()
            if self._state == NOT_RUNNING and not lk["alive"]:
                stack.clear_lock()  # drop a stale lock if any
                return {"ok": True, "note": "nothing running to stop",
                        **self._build_state()}
            eng, br = self._engine, self._bridge
            self._set_state(STOPPING)
        # Terminate outside the lock. Prefer owned handles, fall back to the lock
        # pids for a foreign engine the script started.
        if eng is not None:
            stack.terminate(eng)
        elif lk["alive"] and lk.get("engine_pid"):
            stack.terminate_pid(lk["engine_pid"])
        if br is not None:
            stack.terminate(br)
        elif lk.get("bridge_pid"):
            stack.terminate_pid(lk["bridge_pid"])
        stack.remove_pid("engine")
        stack.remove_pid("bridge")
        stack.clear_lock()
        with self._lock:
            self._engine = None
            self._bridge = None
            self._set_state(NOT_RUNNING)
        return {"ok": True, **self.state()}

    # --- test helpers --------------------------------------------------------

    def join(self, timeout: float = 5.0) -> None:
        t = self._thread
        if t is not None:
            t.join(timeout)

    def _reset_for_test(self) -> None:
        with self._lock:
            self._state = NOT_RUNNING
            self._engine = None
            self._bridge = None
            self._error = None
            self._warm = []
            self._thread = None
            self._started_ts = None
            self._history = []
        stack.clear_lock()


# Module singleton the endpoints and the script-mirror use.
SUPERVISOR = Supervisor()

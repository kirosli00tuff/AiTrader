#!/usr/bin/env bash
# Market AI Lab — clean shutdown of the local 24/7 stack.
#
# Sends SIGTERM to the background engine and python_bridge started by
# ops/start.sh (PIDs recorded under .run/). The engine finishes its current
# tick and flushes to SQLite before exiting. Safe to run repeatedly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$REPO_ROOT/.run"

stop_one() {
  local name="$1" pidfile="$2"
  if [ -f "$pidfile" ]; then
    local pid
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "[stop] stopping $name (pid $pid) ..."
      kill -TERM "$pid" 2>/dev/null || true
      # Give the engine a few seconds to finish its tick + flush.
      for _ in 1 2 3 4 5; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
      done
      kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
    else
      echo "[stop] $name not running."
    fi
    rm -f "$pidfile"
  else
    echo "[stop] no $name pidfile."
  fi
}

stop_one "engine" "$RUN_DIR/engine.pid"
stop_one "python_bridge" "$RUN_DIR/bridge.pid"
echo "[stop] done. (The Dash UI, if running in the foreground, is stopped with Ctrl-C.)"

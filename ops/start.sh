#!/usr/bin/env bash
# Market AI Lab — one-click LOCAL 24/7 launcher (macOS / Linux).
#
# Builds the C++ engine if needed, sets up the Python venv, then starts:
#   1. python_bridge (advisory scoring + Alpaca data/paper RPC) in the background
#   2. the C++ engine in CONTINUOUS (24/7) paper mode in the background
#   3. the Plotly Dash control board (foreground) at http://localhost:8050
# and opens your browser to the dashboard.
#
# Fully offline-safe: with no API keys it auto-falls-back to the deterministic
# mock feed and sim-at-live-price paper fills. Live trading stays DISABLED.
#
# Usage:
#   ops/start.sh                       # mock feed, config interval
#   DATA_SOURCE=alpaca ops/start.sh    # real-time Alpaca data (needs a paper/data key)
#   INTERVAL=10 ops/start.sh           # override loop interval (seconds)
#   NO_BROWSER=1 ops/start.sh          # do not auto-open a browser
#
# Stop everything with: ops/stop.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="${VENV:-$REPO_ROOT/.venv}"
PY="${PYTHON:-python3}"
DB_PATH="${MAL_DB_PATH:-$REPO_ROOT/market_ai_lab.db}"
SCHEMA="$REPO_ROOT/storage/schema.sql"
CONFIG="${MAL_CONFIG_PATH:-$REPO_ROOT/config/default_config.yaml}"
DATA_SOURCE="${DATA_SOURCE:-mock}"
INTERVAL="${INTERVAL:-0}"   # 0 -> use engine.loop_interval_seconds from config
BRIDGE_HOST="127.0.0.1"
BRIDGE_PORT="${BRIDGE_PORT:-8765}"
DASH_HOST="${MAL_DASH_HOST:-127.0.0.1}"
DASH_PORT="${MAL_DASH_PORT:-8050}"
RUN_DIR="$REPO_ROOT/.run"
mkdir -p "$RUN_DIR"

echo "== Market AI Lab — local 24/7 launcher =="
echo "repo: $REPO_ROOT"
echo "data source: $DATA_SOURCE   db: $DB_PATH"

# --- 1. Build the engine if missing ---------------------------------------
if [ ! -x "$REPO_ROOT/build/mal_engine" ]; then
  echo "[start] building C++ engine ..."
  cmake -S "$REPO_ROOT" -B "$REPO_ROOT/build"
  cmake --build "$REPO_ROOT/build" -j
fi

# --- 2. Python venv + deps -------------------------------------------------
if [ ! -d "$VENV" ]; then
  echo "[start] creating venv at $VENV ..."
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$REPO_ROOT/python_bridge/requirements.txt"
pip install --quiet -r "$REPO_ROOT/ui/requirements.txt"

# Ensure the DB + schema exist (one tiny seeding tick if brand new).
if [ ! -f "$DB_PATH" ]; then
  echo "[start] seeding fresh database ..."
  "$REPO_ROOT/build/mal_engine" --config "$CONFIG" --db "$DB_PATH" \
    --schema "$SCHEMA" --iterations 1 >/dev/null
fi

cleanup_pidfile() { [ -f "$1" ] && kill "$(cat "$1")" 2>/dev/null || true; rm -f "$1"; }

# --- 3. Start the python bridge -------------------------------------------
cleanup_pidfile "$RUN_DIR/bridge.pid"
echo "[start] starting python_bridge on $BRIDGE_HOST:$BRIDGE_PORT ..."
BRIDGE_PORT="$BRIDGE_PORT" nohup python "$REPO_ROOT/python_bridge/server.py" \
  >"$RUN_DIR/bridge.log" 2>&1 &
echo $! >"$RUN_DIR/bridge.pid"

# --- 4. Start the engine in CONTINUOUS mode -------------------------------
cleanup_pidfile "$RUN_DIR/engine.pid"
ENGINE_ARGS=(--config "$CONFIG" --db "$DB_PATH" --schema "$SCHEMA"
             --continuous --data-source "$DATA_SOURCE"
             --bridge "$BRIDGE_HOST:$BRIDGE_PORT")
if [ "$INTERVAL" != "0" ]; then
  ENGINE_ARGS+=(--interval-seconds "$INTERVAL")
fi
echo "[start] starting engine (continuous, source=$DATA_SOURCE) ..."
nohup "$REPO_ROOT/build/mal_engine" "${ENGINE_ARGS[@]}" \
  >"$RUN_DIR/engine.log" 2>&1 &
echo $! >"$RUN_DIR/engine.pid"

# --- 5. Open the dashboard -------------------------------------------------
URL="http://$DASH_HOST:$DASH_PORT"
if [ "${NO_BROWSER:-0}" != "1" ]; then
  ( sleep 2
    if command -v open >/dev/null 2>&1; then open "$URL"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
    fi ) >/dev/null 2>&1 &
fi

echo "[start] launching Dash control board at $URL (Ctrl-C to stop the UI)"
echo "[start] engine + bridge keep running in the background; stop them with ops/stop.sh"
export MAL_DB_PATH="$DB_PATH" MAL_CONFIG_PATH="$CONFIG"
export MAL_DASH_HOST="$DASH_HOST" MAL_DASH_PORT="$DASH_PORT"
cd "$REPO_ROOT/ui"
exec python app.py

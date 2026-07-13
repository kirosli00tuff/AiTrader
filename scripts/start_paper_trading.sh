#!/usr/bin/env bash
# One-command full start: real-time Alpaca PAPER trading with all four decision
# levels active. Live trading stays OFF (Alpaca is paper + market-data only).
#
# Order, with a health check between steps:
#   1. Python bridge (real council + dnn + whale via SEC EDGAR).
#   2. C++ engine, feed_mode alpaca_paper, clock real, on the full whitelist
#      (BTC/USD, ETH/USD, SPY, QQQ). Crypto trades 24/7; equities respect market
#      hours via the existing skip. Strict mode: a layer set on-real that is not
#      reachable refuses to start (no silent mock on the real path).
#   3. GUI backend (read-only) + frontend (Vite).
#
# Fails loudly if any component does not come up, and on exit cleanly stops
# everything it started. The per-level source toggle (Controls/Ops) can drop any
# single layer to mock at runtime without stopping the run.
#
# Env:
#   MAL_HEADLESS=1     skip the Vite frontend and run the engine in the
#                      foreground (used by the bounded verification run).
#   MAL_RUN_SECONDS=N  in headless mode, stop after N seconds (default: run
#                      until interrupted).
#   MAL_DB_PATH        shared SQLite DB (default market_ai_lab.db).
#   BRIDGE_PORT / MAL_API_PORT / interval overrides honored.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${MAL_PYTHON:-$ROOT/.venv/bin/python}"
ENGINE="$ROOT/build/mal_engine"
BRIDGE_PORT="${BRIDGE_PORT:-8765}"
API_PORT="${MAL_API_PORT:-8000}"
DB="${MAL_DB_PATH:-$ROOT/market_ai_lab.db}"
INTERVAL="${MAL_INTERVAL_SECONDS:-30}"
export MAL_API_PORT="$API_PORT" MAL_DB_PATH="$DB"

BRIDGE_PID=""; ENGINE_PID=""; API_PID=""; VITE_PID=""

die() { echo "FATAL: $*" >&2; exit 1; }

cleanup() {
  echo ""
  echo "Stopping components..."
  for pid in "$VITE_PID" "$API_PID" "$ENGINE_PID" "$BRIDGE_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "All stopped."
}
trap cleanup EXIT INT TERM

[ -x "$PY" ] || die "python venv not found at $PY"
[ -x "$ENGINE" ] || die "engine binary not found at $ENGINE (build it: cmake -S . -B build && cmake --build build)"

wait_http() {  # url, label, tries
  local url="$1" label="$2" tries="${3:-40}" code
  for _ in $(seq 1 "$tries"); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo 000)"
    [ "$code" = "200" ] && return 0
    sleep 0.5
  done
  return 1
}

# --- Full-activation environment: export the whale live flags declared in
# config so the bridge fetches real SEC EDGAR data. The whale library treats
# these as env opt-ins (default OFF), so this deliberate start command is what
# turns them on. use_real_council is read from config by the bridge directly.
eval "$("$PY" - <<'PYCFG'
import yaml
c = yaml.safe_load(open("config/default_config.yaml")) or {}
w = c.get("whale", {}) or {}
def b(v): return "true" if v else "false"
print(f'export SEC_EDGAR_ENABLED={b(w.get("sec_edgar_enabled"))}')
print(f'export WHALE_LIVE_ENABLED={b(w.get("whale_live_enabled"))}')
PYCFG
)"
echo "Full four-level real-time paper trading"
echo "======================================="
echo "  SEC_EDGAR_ENABLED=$SEC_EDGAR_ENABLED  WHALE_LIVE_ENABLED=$WHALE_LIVE_ENABLED"
echo "  DB=$DB"
echo ""

# --- 1. Python bridge (real council + dnn + whale) --------------------------
echo "[1/4] starting Python bridge on 127.0.0.1:${BRIDGE_PORT} ..."
BRIDGE_PORT="$BRIDGE_PORT" "$PY" -m python_bridge.server &
BRIDGE_PID=$!
wait_http "http://127.0.0.1:${BRIDGE_PORT}/health" "bridge" 40 \
  || die "bridge did not become healthy on port ${BRIDGE_PORT}"
echo "      bridge healthy. Real-service availability:"
curl -s "http://127.0.0.1:${BRIDGE_PORT}/status" \
  | "$PY" -c 'import sys,json;d=json.load(sys.stdin);print("       council_real=%s dnn_real=%s whale_real=%s sec_edgar=%s"%(d.get("council_real"),d.get("dnn_real"),d.get("whale_real"),d.get("sec_edgar")))' \
  2>/dev/null || echo "       (status parse skipped)"

# --- 2. C++ engine, real paper path -----------------------------------------
echo "[2/4] starting engine (feed_mode alpaca_paper, clock real, full whitelist) ..."
"$ENGINE" --continuous --interval-seconds "$INTERVAL" \
  --feed-mode alpaca_paper --clock-mode real \
  --bridge "127.0.0.1:${BRIDGE_PORT}" --db "$DB" &
ENGINE_PID=$!
sleep 3
kill -0 "$ENGINE_PID" 2>/dev/null \
  || die "engine exited immediately (strict mode may have refused an on-real layer; see the log above)"
echo "      engine running (pid $ENGINE_PID). Crypto 24/7; equities respect market hours."

# --- 3. GUI backend ----------------------------------------------------------
echo "[3/4] starting GUI backend on 127.0.0.1:${API_PORT} ..."
"$PY" -m api_server.run &
API_PID=$!
wait_http "http://127.0.0.1:${API_PORT}/health" "api" 40 \
  || die "GUI backend did not become healthy on port ${API_PORT}"
echo "      GUI backend healthy."

# --- 4. Frontend (unless headless) ------------------------------------------
if [ "${MAL_HEADLESS:-0}" = "1" ]; then
  echo "[4/4] headless: frontend skipped. Engine loop is running."
  echo ""
  echo "Open the GUI later with: scripts/run_gui.sh  (http://127.0.0.1:5173)"
  if [ -n "${MAL_RUN_SECONDS:-}" ]; then
    echo "Running for ${MAL_RUN_SECONDS}s then stopping..."
    sleep "${MAL_RUN_SECONDS}" || true
  else
    echo "Press Ctrl-C to stop. Following the engine..."
    wait "$ENGINE_PID"
  fi
else
  if [ ! -d web/node_modules ]; then
    echo "      installing web deps (first run)..."
    ( cd web && npm install --no-audit --no-fund )
  fi
  echo "[4/4] starting frontend (Vite) ..."
  echo ""
  echo "  >>> Open the GUI at:  http://127.0.0.1:5173"
  echo "      (Ops and Controls carry the per-level off / on-mock / on-real toggles)"
  echo ""
  ( cd web && npm run dev ) &
  VITE_PID=$!
  wait "$VITE_PID"
fi

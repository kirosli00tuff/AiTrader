#!/usr/bin/env bash
# Start the read-only API backend and the Vite dev server together.
#
# The React GUI reads the SAME SQLite database as the Dash UI (which stays
# available as a fallback, unchanged). For live data the engine and the Python
# bridge should be running. The backend is read-only on the operational tables.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${MAL_PYTHON:-$ROOT/.venv/bin/python}"
API_PORT="${MAL_API_PORT:-8000}"
export MAL_API_PORT="$API_PORT"

echo "Starting AiTrader GUI"
echo "  API backend  : http://127.0.0.1:${API_PORT}   (read-only + start/stop supervisor)"
echo "  React (Vite) : http://127.0.0.1:5173   (the rebuilt UI, open this)"
echo "  Dash fallback: python ui/app.py       (unchanged, still available)"
echo
echo "  The backend hosts the start/stop supervisor, so it must be running first"
echo "  (this script starts it). Once the GUI is up, use the Start Paper Trading"
echo "  button on the Ops page to bring up the bridge and engine. The Start button"
echo "  does NOT launch this backend, it drives the supervisor that lives in it."
echo

if [ ! -x "$PY" ]; then
  echo "Python venv not found at $PY. Create it and install api_server/requirements.txt:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r api_server/requirements.txt" >&2
  exit 1
fi

if [ ! -d web/node_modules ]; then
  echo "Installing web dependencies (first run)..."
  ( cd web && npm install --no-audit --no-fund )
fi

"$PY" -m api_server.run &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

# Wait for the backend to answer, then tell the operator the stack can be started.
for _ in $(seq 1 40); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${API_PORT}/health" 2>/dev/null || echo 000)"
  [ "$code" = "200" ] && break
  sleep 0.5
done
echo ""
echo "GUI backend is ready. Open http://127.0.0.1:5173 and click Start Paper"
echo "Trading on the Ops page to bring up the bridge and engine."
echo ""

( cd web && npm run dev )

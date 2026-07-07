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
echo "  API backend  : http://127.0.0.1:${API_PORT}   (read-only)"
echo "  React (Vite) : http://127.0.0.1:5173"
echo "  Dash fallback: python ui/app.py  (unchanged, still available)"
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

( cd web && npm run dev )

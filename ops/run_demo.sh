#!/usr/bin/env bash
# Market AI Lab — one-command offline demo.
#
# Builds the C++ engine (if needed), creates/uses a Python venv, installs the
# UI + bridge requirements, runs the paper loop to seed SQLite, then launches
# the Plotly Dash control board. Fully offline; NO API keys required; live
# trading stays DISABLED.
#
# Usage:
#   ops/run_demo.sh                # full demo + dashboard
#   ops/run_demo.sh --no-dash      # seed only
#   ITER=40 ops/run_demo.sh        # custom iteration count
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="${VENV:-$REPO_ROOT/.venv}"
ITER="${ITER:-25}"
PY="${PYTHON:-python3}"

echo "== Market AI Lab demo =="
echo "repo: $REPO_ROOT"

# --- 1. C++ engine build ---------------------------------------------------
if [ ! -x "$REPO_ROOT/build/mal_engine" ]; then
  echo "[run_demo] configuring + building C++ engine ..."
  cmake -S "$REPO_ROOT" -B "$REPO_ROOT/build"
  cmake --build "$REPO_ROOT/build" -j
else
  echo "[run_demo] engine already built (delete build/ to rebuild)."
fi

# --- 2. Python venv + deps -------------------------------------------------
if [ ! -d "$VENV" ]; then
  echo "[run_demo] creating venv at $VENV ..."
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "[run_demo] installing Python requirements ..."
pip install --quiet --upgrade pip
pip install --quiet -r "$REPO_ROOT/python_bridge/requirements.txt"
pip install --quiet -r "$REPO_ROOT/ui/requirements.txt"

# --- 3. Seed + launch ------------------------------------------------------
echo "[run_demo] running demo orchestrator (iterations=$ITER) ..."
exec python "$REPO_ROOT/ops/demo.py" --iterations "$ITER" "$@"

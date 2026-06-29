#!/usr/bin/env bash
# =============================================================================
# Market AI Lab - launch the native desktop app on Linux / Ubuntu.
#
# Activates the project venv (created by ops/build_linux.sh) and runs the
# pywebview desktop window. The C++ engine + bridge are started and supervised
# by ui/desktop.py in 24/7 paper mode (live trading stays DISABLED by default).
#
# This is the command the .desktop launcher (dock icon / autostart) invokes.
#
# Usage:  ops/run_desktop.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="${VENV:-$REPO_ROOT/.venv}"
if [ ! -d "$VENV" ]; then
  echo "[run] venv not found at $VENV"
  echo "[run] Build it first:  bash ops/build_linux.sh"
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

# Force the GTK backend (most reliable on Ubuntu/GNOME). pywebview falls back
# automatically if GTK is unavailable.
export PYWEBVIEW_GUI="${PYWEBVIEW_GUI:-gtk}"
# Use a repo-local DB to avoid the /tmp SQLite "disk I/O error" gotcha.
export MAL_DB_PATH="${MAL_DB_PATH:-$REPO_ROOT/market_ai_lab.db}"

exec python "$REPO_ROOT/ui/desktop.py"

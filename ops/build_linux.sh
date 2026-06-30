#!/usr/bin/env bash
# =============================================================================
# Market AI Lab - build the desktop app on Linux / Ubuntu (one command).
#
#   1. Checks the OS prerequisites (build tools + the GTK WebKit webview that
#      pywebview needs for a native window) and tells you the apt line if any
#      are missing.
#   2. Builds the C++ engine with CMake (Release).
#   3. Creates a Python venv and installs the UI + desktop + bridge deps.
#   4. Generates a PNG icon for the desktop launcher.
#
# After this, start the app with:   ops/run_desktop.sh
# Pin it to your dock / autostart with:   ops/install_desktop.sh
#
# Usage (from anywhere):  bash ops/build_linux.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
VENV="${VENV:-$REPO_ROOT/.venv}"
PY="${PYTHON:-python3}"

echo "== Market AI Lab - Linux desktop builder =="
echo "repo: $REPO_ROOT"
echo

# --- 1. Prerequisite checks ------------------------------------------------- #
APT_PKGS=()
need_cmd() { command -v "$1" >/dev/null 2>&1; }

need_cmd cmake        || APT_PKGS+=(cmake)
need_cmd g++          || APT_PKGS+=(build-essential)
need_cmd "$PY"        || APT_PKGS+=(python3)
"$PY" -c "import venv" 2>/dev/null || APT_PKGS+=(python3-venv)

# The C++ engine links system SQLite3 (CMakeLists.txt). Detect its dev header
# robustly: check the standard path, any arch-specific subdir, and pkg-config.
have_sqlite=0
[ -f /usr/include/sqlite3.h ] && have_sqlite=1
for h in /usr/include/*/sqlite3.h; do [ -f "$h" ] && have_sqlite=1; done
if [ "$have_sqlite" -eq 0 ] && command -v pkg-config >/dev/null 2>&1; then
  pkg-config --exists sqlite3 2>/dev/null && have_sqlite=1
fi
if [ "$have_sqlite" -eq 0 ] && command -v dpkg >/dev/null 2>&1; then
  dpkg -s libsqlite3-dev >/dev/null 2>&1 && have_sqlite=1
fi
if [ "$have_sqlite" -eq 0 ]; then APT_PKGS+=(libsqlite3-dev); fi

# pywebview on Linux needs a GTK WebKit (or Qt) backend at the OS level.
# python3-gi + the WebKit2 GIR provide the GTK backend.
GTK_OK=1
"$PY" - <<'PYCHECK' 2>/dev/null || GTK_OK=0
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2  # noqa
PYCHECK
if [ "$GTK_OK" -ne 1 ]; then
  APT_PKGS+=(python3-gi gir1.2-webkit2-4.1 gir1.2-gtk-3.0 libcairo2-dev libgirepository1.0-dev pkg-config)
fi

if [ "${#APT_PKGS[@]}" -gt 0 ]; then
  echo "[build] Missing system packages. Install them, then re-run this script:"
  echo
  echo "    sudo apt update && sudo apt install -y ${APT_PKGS[*]}"
  echo
  echo "[build] (If you only want to run headless / browser mode, you can skip"
  echo "[build]  the GTK webview packages and use ops/start.sh instead.)"
  exit 1
fi
echo "[build] prerequisites OK (cmake, g++, python3-venv, GTK WebKit)."

# --- 2. Build the C++ engine ------------------------------------------------ #
echo "[build] configuring + building C++ engine (Release) ..."
cmake -S "$REPO_ROOT" -B "$REPO_ROOT/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$REPO_ROOT/build" -j "$(nproc)"
if [ -x "$REPO_ROOT/build/mal_engine" ]; then
  echo "[build] engine built: $REPO_ROOT/build/mal_engine"
else
  echo "[build] WARNING: build/mal_engine not found; dashboard will still open"
  echo "[build]   but no new trades will be generated until the engine builds."
fi

# --- 3. Python venv + deps -------------------------------------------------- #
if [ ! -d "$VENV" ]; then
  echo "[build] creating venv at $VENV (with --system-site-packages so the"
  echo "[build]   GTK/WebKit bindings python3-gi are visible to pywebview) ..."
  "$PY" -m venv --system-site-packages "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip
echo "[build] installing dependencies ..."
python -m pip install -r "$REPO_ROOT/python_bridge/requirements.txt"
python -m pip install -r "$REPO_ROOT/ui/requirements.txt"
python -m pip install -r "$REPO_ROOT/ui/requirements-desktop.txt"
# pywebview's GTK backend needs PyGObject bound into the venv:
python -m pip install pycairo PyGObject 2>/dev/null || \
  echo "[build] note: using system python3-gi for the GTK webview backend."

# --- 4. Generate the PNG launcher icon ------------------------------------- #
echo "[build] generating launcher icon ..."
python "$REPO_ROOT/ops/_make_icon.py" --png || echo "[build] icon generation skipped"

echo
echo "[build] SUCCESS."
echo "[build] Start the app:        ops/run_desktop.sh"
echo "[build] Pin to dock + autostart:  ops/install_desktop.sh"

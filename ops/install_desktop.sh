#!/usr/bin/env bash
# =============================================================================
# Market AI Lab - install the Ubuntu/Linux desktop launcher.
#
# Installs a .desktop entry so the app shows up in your Activities / app grid,
# can be PINNED to the dock / taskbar (right-click the running icon -> "Pin to
# Dash" / "Add to Favorites"), and (optionally) AUTOSTARTS 24/7 at login.
#
# It substitutes the real repo path into the launcher, copies it to the
# standard user locations, and refreshes the desktop database.
#
# Usage:
#   bash ops/install_desktop.sh            # install launcher (pinnable)
#   bash ops/install_desktop.sh --autostart  # also start 24/7 at login
#   bash ops/install_desktop.sh --uninstall  # remove launcher + autostart
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP_NAME="market-ai-lab.desktop"
TEMPLATE="$REPO_ROOT/ops/market-ai-lab.desktop.in"

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$APPS_DIR/$DESKTOP_NAME" "$AUTOSTART_DIR/$DESKTOP_NAME"
  command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
  echo "[install] removed launcher + autostart."
  exit 0
fi

# Make sure scripts + icon exist.
chmod +x "$REPO_ROOT/ops/run_desktop.sh" "$REPO_ROOT/ops/build_linux.sh" 2>/dev/null || true
if [ ! -f "$REPO_ROOT/ops/MarketAILab.png" ]; then
  echo "[install] generating PNG icon ..."
  if [ -d "$REPO_ROOT/.venv" ]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.venv/bin/activate"
  fi
  python "$REPO_ROOT/ops/_make_icon.py" --png || \
    echo "[install] WARNING: could not generate icon (install pillow); launcher will use a generic icon."
fi

# Render the template with the real absolute repo path.
mkdir -p "$APPS_DIR"
sed "s|__REPO__|$REPO_ROOT|g" "$TEMPLATE" > "$APPS_DIR/$DESKTOP_NAME"
chmod +x "$APPS_DIR/$DESKTOP_NAME"
command -v update-desktop-database >/dev/null 2>&1 && \
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
# GNOME: mark as trusted so it launches without the "Allow Launching" prompt.
command -v gio >/dev/null 2>&1 && \
  gio set "$APPS_DIR/$DESKTOP_NAME" metadata::trusted true 2>/dev/null || true

echo "[install] launcher installed: $APPS_DIR/$DESKTOP_NAME"
echo "[install] Find 'Market AI Lab' in your app grid. Launch it once, then"
echo "[install]   right-click its dock icon -> 'Pin to Dash' / 'Add to Favorites'"
echo "[install]   to keep it on your bottom taskbar."

if [ "${1:-}" = "--autostart" ]; then
  mkdir -p "$AUTOSTART_DIR"
  cp "$APPS_DIR/$DESKTOP_NAME" "$AUTOSTART_DIR/$DESKTOP_NAME"
  # X-GNOME-Autostart-enabled tells GNOME to actually run it at login.
  grep -q "X-GNOME-Autostart-enabled" "$AUTOSTART_DIR/$DESKTOP_NAME" || \
    echo "X-GNOME-Autostart-enabled=true" >> "$AUTOSTART_DIR/$DESKTOP_NAME"
  echo "[install] autostart enabled: the app will launch 24/7 at every login."
  echo "[install]   (disable with: rm $AUTOSTART_DIR/$DESKTOP_NAME)"
fi

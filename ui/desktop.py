"""Optional native desktop window for the Market AI Lab dashboard.

Wraps the Plotly Dash control board in a real OS window using pywebview, so the
app looks like a desktop application instead of a browser tab. This is OPTIONAL
and not part of the default install — see ui/requirements-desktop.txt.

It starts the Dash server in a background thread and points a pywebview window
at it. The C++ engine + python_bridge are still launched separately (e.g. via
ops/start.sh); this only replaces the browser with a native window.

Usage:
  pip install -r ui/requirements-desktop.txt
  python ui/desktop.py
"""
from __future__ import annotations

import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _run_server(host: str, port: int) -> None:
    # Import here so the Dash app + its layout are constructed in this process.
    import app as dash_app  # noqa: WPS433 — intentional local import

    # Dash exposes the Flask server as `app.server`; serve it with the built-in
    # development server (fine for a single local user).
    dash_app.app.run(host=host, port=port, debug=False, use_reloader=False)


def main() -> None:
    try:
        import webview  # type: ignore
    except ImportError:
        sys.stderr.write(
            "pywebview is not installed. Install the desktop extra:\n"
            "  pip install -r ui/requirements-desktop.txt\n")
        sys.exit(1)

    host = os.environ.get("MAL_DASH_HOST", "127.0.0.1")
    port = int(os.environ.get("MAL_DASH_PORT", "8050"))

    # Default the DB/config paths to the repo root if not already set.
    repo_root = os.path.dirname(_HERE)
    os.environ.setdefault("MAL_DB_PATH",
                          os.path.join(repo_root, "market_ai_lab.db"))
    os.environ.setdefault("MAL_CONFIG_PATH",
                          os.path.join(repo_root, "config", "default_config.yaml"))

    t = threading.Thread(target=_run_server, args=(host, port), daemon=True)
    t.start()
    time.sleep(1.5)  # give the server a moment to bind

    webview.create_window("Market AI Lab", f"http://{host}:{port}",
                          width=1400, height=900)
    webview.start()


if __name__ == "__main__":
    main()

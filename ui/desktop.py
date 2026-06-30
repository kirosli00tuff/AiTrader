"""Market AI Lab — true Windows desktop application.

Opens a REAL native OS window (via pywebview) showing the Plotly Dash control
board, while supervising the C++ trading engine + python_bridge so the system
keeps running 24/7 in the background.

Behaviour
---------
* On launch it starts (and then monitors / restarts) three things:
    1. ``python_bridge/server.py``  — advisory scoring + Alpaca data/paper RPC
    2. the compiled C++ engine in **CONTINUOUS** (24/7) paper mode
    3. the Dash server, served in a background thread inside this process
  then opens a native pywebview window pointed at the local Dash server.
* A **system-tray icon** (pystray) gives: "Open dashboard", "Engine:
  start/stop", and "Quit".
* Closing the window does NOT stop trading — it **hides to the tray** and the
  engine keeps running. The app only fully exits via tray → "Quit".

Safety posture is unchanged: this is purely a presentation / process-supervision
layer. It launches the engine with exactly the same continuous-mode flags as
``ops/start.sh`` / ``ops/start.bat`` (live trading stays DISABLED by default;
Layer-1 static safety remains the final authority inside the engine).

Run from source (any OS, for development)::

    pip install -r ui/requirements.txt -r ui/requirements-desktop.txt
    python ui/desktop.py

Packaged Windows .exe: see ``ops/build_exe.bat`` and ``ui/MarketAILab.spec``.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from typing import List, Optional

# --------------------------------------------------------------------------- #
# Path / environment resolution (works both from source and from a PyInstaller
# one-file bundle, where assets live under sys._MEIPASS and the working set is
# next to the .exe).
# --------------------------------------------------------------------------- #
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bundle_dir() -> str:
    """Directory holding bundled read-only assets (Dash code, icon, engine)."""
    if _frozen():
        # PyInstaller unpacks data files here.
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(_HERE)  # repo root when running from source


def _runtime_dir() -> str:
    """Writable directory for the DB / logs / venv-independent runtime state.

    When frozen we sit next to the .exe (user-writable); from source we use the
    repo root.
    """
    if _frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(_HERE)


BUNDLE = _bundle_dir()
RUNTIME = _runtime_dir()

HOST = os.environ.get("MAL_DASH_HOST", "127.0.0.1")
PORT = int(os.environ.get("MAL_DASH_PORT", "8050"))
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8765"))
DATA_SOURCE = os.environ.get("DATA_SOURCE", "mock")
INTERVAL = os.environ.get("INTERVAL", "0")  # 0 -> use engine config interval

DB_PATH = os.environ.setdefault("MAL_DB_PATH",
                                os.path.join(RUNTIME, "market_ai_lab.db"))
CONFIG_PATH = os.environ.setdefault(
    "MAL_CONFIG_PATH", os.path.join(BUNDLE, "config", "default_config.yaml"))
SCHEMA_PATH = os.path.join(BUNDLE, "storage", "schema.sql")
os.environ.setdefault("MAL_DASH_HOST", HOST)
os.environ.setdefault("MAL_DASH_PORT", str(PORT))


def _engine_binary() -> Optional[str]:
    """Locate the compiled C++ engine next to the bundle / repo build dir."""
    candidates: List[str] = []
    exe = "mal_engine.exe" if os.name == "nt" else "mal_engine"
    # When frozen, build_exe.bat bundles the engine next to / under the exe.
    candidates.append(os.path.join(BUNDLE, exe))
    candidates.append(os.path.join(BUNDLE, "build", exe))
    candidates.append(os.path.join(BUNDLE, "build", "Release", exe))
    candidates.append(os.path.join(RUNTIME, exe))
    candidates.append(os.path.join(RUNTIME, "build", exe))
    candidates.append(os.path.join(RUNTIME, "build", "Release", exe))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


# --------------------------------------------------------------------------- #
# Process supervisor — owns the engine + bridge child processes, monitors them
# and restarts on unexpected exit, and shuts them down cleanly on Quit.
# --------------------------------------------------------------------------- #
class Supervisor:
    def __init__(self) -> None:
        self._engine: Optional[subprocess.Popen] = None
        self._bridge: Optional[subprocess.Popen] = None
        self._engine_enabled = True  # toggled by the tray "Engine: start/stop"
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._monitor: Optional[threading.Thread] = None

    # --- bridge ---------------------------------------------------------- #
    def _start_bridge(self) -> None:
        server = os.path.join(BUNDLE, "python_bridge", "server.py")
        if not os.path.isfile(server):
            sys.stderr.write(f"[desktop] bridge not found at {server}\n")
            return
        env = dict(os.environ, BRIDGE_PORT=str(BRIDGE_PORT))
        try:
            self._bridge = subprocess.Popen(
                [sys.executable, server], env=env,
                cwd=BUNDLE, stdout=_logfile("bridge"), stderr=subprocess.STDOUT)
            sys.stdout.write(f"[desktop] bridge started (pid {self._bridge.pid})\n")
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[desktop] failed to start bridge: {exc}\n")

    # --- engine ---------------------------------------------------------- #
    def _engine_args(self, binary: str) -> List[str]:
        args = [binary,
                "--config", CONFIG_PATH,
                "--db", DB_PATH,
                "--schema", SCHEMA_PATH,
                "--continuous",
                "--data-source", DATA_SOURCE,
                "--bridge", f"{BRIDGE_HOST}:{BRIDGE_PORT}"]
        if INTERVAL not in ("0", "", None):
            args += ["--interval-seconds", str(INTERVAL)]
        return args

    def _start_engine(self) -> None:
        binary = _engine_binary()
        if not binary:
            sys.stderr.write(
                "[desktop] C++ engine binary not found. Build it first with "
                "ops/build_exe.bat (Windows/MSVC) — the dashboard will still "
                "open but no new trades will be generated.\n")
            return
        try:
            self._engine = subprocess.Popen(
                self._engine_args(binary), cwd=BUNDLE,
                stdout=_logfile("engine"), stderr=subprocess.STDOUT)
            sys.stdout.write(f"[desktop] engine started (pid {self._engine.pid})\n")
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[desktop] failed to start engine: {exc}\n")

    # --- lifecycle ------------------------------------------------------- #
    def start(self) -> None:
        with self._lock:
            self._start_bridge()
            if self._engine_enabled:
                self._start_engine()
        self._monitor = threading.Thread(target=self._supervise, daemon=True)
        self._monitor.start()

    def _supervise(self) -> None:
        """Restart child processes that die unexpectedly (24/7 resilience)."""
        while not self._stop.is_set():
            time.sleep(3.0)
            if self._stop.is_set():
                break
            with self._lock:
                # Re-check _stop inside the lock so a quit already underway
                # never triggers a spurious restart during teardown.
                if self._stop.is_set():
                    break
                if self._bridge is not None and self._bridge.poll() is not None:
                    sys.stderr.write("[desktop] bridge exited — restarting\n")
                    self._start_bridge()
                if (self._engine_enabled and self._engine is not None
                        and self._engine.poll() is not None):
                    sys.stderr.write("[desktop] engine exited — restarting\n")
                    self._start_engine()

    def set_engine_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._engine_enabled = enabled
            if enabled and (self._engine is None or self._engine.poll() is not None):
                self._start_engine()
            elif not enabled and self._engine is not None and self._engine.poll() is None:
                _terminate(self._engine, "engine")
                self._engine = None

    def engine_running(self) -> bool:
        with self._lock:
            return (self._engine_enabled and self._engine is not None
                    and self._engine.poll() is None)

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            if self._engine is not None:
                _terminate(self._engine, "engine")
                self._engine = None
            if self._bridge is not None:
                _terminate(self._bridge, "bridge")
                self._bridge = None


def _logfile(name: str):
    run_dir = os.path.join(RUNTIME, ".run")
    try:
        os.makedirs(run_dir, exist_ok=True)
        return open(os.path.join(run_dir, f"{name}.log"), "ab")
    except Exception:  # noqa: BLE001
        return subprocess.DEVNULL


def _terminate(proc: subprocess.Popen, name: str) -> None:
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.stdout.write(f"[desktop] {name} stopped\n")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[desktop] error stopping {name}: {exc}\n")


# --------------------------------------------------------------------------- #
# Dash server (served in a background thread inside this process).
# --------------------------------------------------------------------------- #
def _run_dash(host: str, port: int) -> None:
    # Import inside the thread so the Dash layout is built in this process and
    # picks up the MAL_* environment we configured above.
    ui_dir = os.path.join(BUNDLE, "ui")
    if ui_dir not in sys.path:
        sys.path.insert(0, ui_dir)
    import app as dash_app  # noqa: WPS433 — intentional local import
    dash_app.app.run(host=host, port=port, debug=False, use_reloader=False)


def _wait_for_server(host: str, port: int, timeout: float = 20.0) -> bool:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.3)
    return False


# --------------------------------------------------------------------------- #
# System tray (pystray). Import-guarded so a headless import never crashes.
# --------------------------------------------------------------------------- #
def _load_icon_image():
    """Return a PIL.Image for the tray/window icon (bundled .ico or generated)."""
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return None
    ico = os.path.join(BUNDLE, "ops", "MarketAILab.ico")
    if os.path.isfile(ico):
        try:
            return Image.open(ico)
        except Exception:  # noqa: BLE001
            pass
    # Fallback: draw a tiny placeholder so the tray still shows something.
    try:
        from PIL import ImageDraw  # type: ignore
        img = Image.new("RGBA", (64, 64), (13, 17, 23, 255))
        d = ImageDraw.Draw(img)
        d.rectangle([8, 8, 56, 56], outline=(46, 160, 67, 255), width=4)
        d.line([14, 44, 26, 28, 38, 36, 50, 18], fill=(46, 160, 67, 255), width=3)
        return img
    except Exception:  # noqa: BLE001
        return None


class TrayController:
    """Owns the pystray icon and wires its menu to the window + supervisor."""

    def __init__(self, supervisor: "Supervisor", window) -> None:
        self._sup = supervisor
        self._window = window
        self._icon = None

    def _open_dashboard(self, icon, item) -> None:  # noqa: ARG002
        try:
            self._window.show()
        except Exception:  # noqa: BLE001
            pass

    def _toggle_engine(self, icon, item) -> None:  # noqa: ARG002
        self._sup.set_engine_enabled(not self._sup.engine_running())

    def _engine_label(self, item) -> str:  # noqa: ARG002
        return ("Engine: running (click to stop)" if self._sup.engine_running()
                else "Engine: stopped (click to start)")

    def _quit(self, icon, item) -> None:  # noqa: ARG002
        sys.stdout.write("[desktop] quit requested from tray\n")
        self._sup.shutdown()
        try:
            if self._icon is not None:
                self._icon.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._window.destroy()
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)

    # Set True once a tray icon is successfully showing, so the window-close
    # handler knows whether hiding-to-tray would strand the app with no UI.
    available = False

    def run(self) -> None:
        # The tray is optional. On some desktops (e.g. GNOME without the
        # AppIndicator extension) pystray's backend raises at import/icon time.
        # Never let that crash the app — just log and skip the tray; the window
        # and Quit-from-window still work.
        try:
            import pystray  # type: ignore
            from pystray import MenuItem as Item  # type: ignore

            image = _load_icon_image()
            menu = pystray.Menu(
                Item("Open dashboard", self._open_dashboard, default=True),
                Item(self._engine_label, self._toggle_engine),
                pystray.Menu.SEPARATOR,
                Item("Quit", self._quit),
            )
            self._icon = pystray.Icon("MarketAILab", image, "Market AI Lab", menu)
            self.available = True
            # run() blocks; we call it on its own thread from main().
            self._icon.run()
        except Exception as exc:  # noqa: BLE001
            self.available = False
            sys.stderr.write(
                f"[desktop] system tray unavailable ({exc}). The app will run\n"
                "[desktop]   without a tray icon; closing the window will quit.\n"
                "[desktop]   On GNOME, install the AppIndicator extension to\n"
                "[desktop]   enable close-to-tray:\n"
                "[desktop]   sudo apt install gnome-shell-extension-appindicator\n")


# --------------------------------------------------------------------------- #
# Main entry point.
# --------------------------------------------------------------------------- #
def main() -> None:
    try:
        import webview  # type: ignore
    except ImportError:
        sys.stderr.write(
            "pywebview is not installed. Install the desktop extras:\n"
            "  pip install -r ui/requirements.txt -r ui/requirements-desktop.txt\n")
        sys.exit(1)

    supervisor = Supervisor()
    supervisor.start()

    # Start the Dash server in this process (background thread) and wait for it.
    threading.Thread(target=_run_dash, args=(HOST, PORT), daemon=True).start()
    if not _wait_for_server(HOST, PORT):
        sys.stderr.write("[desktop] Dash server did not start in time\n")

    window = webview.create_window(
        "Market AI Lab", f"http://{HOST}:{PORT}",
        width=1400, height=900, min_size=(1000, 640))

    # Close-to-tray: intercept the window-close event, hide instead of exit.
    tray = TrayController(supervisor, window)

    def _on_closing():
        # If a tray icon is showing, hide-to-tray (engine keeps running) and
        # cancel the close. If there is NO tray (e.g. GNOME without the
        # AppIndicator extension), hiding would leave the user no way to get
        # the window back — so quit cleanly instead.
        if tray.available:
            try:
                window.hide()
            except Exception:  # noqa: BLE001
                pass
            return False
        sys.stdout.write("[desktop] no tray available — closing the window quits.\n")
        supervisor.shutdown()
        return True

    try:
        window.events.closing += _on_closing
    except Exception:  # noqa: BLE001
        # Older pywebview API — best-effort; Quit from tray still works.
        pass

    # Run the tray on a background thread (pystray.run blocks). Give it a brief
    # moment to initialize so tray.available is set before the window opens.
    try:
        threading.Thread(target=tray.run, daemon=True).start()
        time.sleep(0.8)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[desktop] system tray unavailable: {exc}\n")

    # webview.start() blocks on the GUI main loop until the window is destroyed
    # (which only the tray "Quit" does). gui=None lets pywebview auto-select the
    # native backend (EdgeChromium/WebView2 on Windows).
    webview.start()


if __name__ == "__main__":
    main()

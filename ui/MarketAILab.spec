# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Market AI Lab Windows desktop app.

Produces a single ``MarketAILab.exe`` that bundles:
  * the desktop launcher (ui/desktop.py)  -> the app entry point
  * the Dash control board (ui/)           -> UI + callbacks
  * all Python advisory services           -> bridge, consensus, ml, whale, data
  * config + storage schema                -> needed by engine + dashboard
  * the tray/window icon (ops/MarketAILab.ico)
  * the compiled C++ engine (build\\Release\\mal_engine.exe), IF it exists at
    build time — otherwise the exe still builds and the engine can sit next to
    MarketAILab.exe at runtime (desktop.py searches several locations).

Build it via ops/build_exe.bat (recommended) or directly:
    pyinstaller ui/MarketAILab.spec --noconfirm

Run from the *repo root* so the relative data paths below resolve.
"""
import os

# When PyInstaller execs a spec, the repo root is the current working dir
# (ops/build_exe.bat does `cd` to repo root before invoking pyinstaller).
ROOT = os.path.abspath(os.getcwd())


def _exists(*parts):
    return os.path.isfile(os.path.join(ROOT, *parts))


# --- Bundled data files: (source_on_disk, dest_dir_inside_bundle) ----------- #
datas = [
    (os.path.join(ROOT, "ui"), "ui"),
    (os.path.join(ROOT, "config"), "config"),
    (os.path.join(ROOT, "storage"), "storage"),
    (os.path.join(ROOT, "python_bridge"), "python_bridge"),
    (os.path.join(ROOT, "account_manager"), "account_manager"),
    (os.path.join(ROOT, "llm_consensus"), "llm_consensus"),
    (os.path.join(ROOT, "ml_factor"), "ml_factor"),
    (os.path.join(ROOT, "whale_signal"), "whale_signal"),
    (os.path.join(ROOT, "market_data"), "market_data"),
    (os.path.join(ROOT, "news_ingestion"), "news_ingestion"),
    (os.path.join(ROOT, "signal_engine"), "signal_engine"),
    (os.path.join(ROOT, "risk"), "risk"),
    (os.path.join(ROOT, "learning"), "learning"),
]

# Tray / window / exe icon.
_ico = os.path.join(ROOT, "ops", "MarketAILab.ico")
if os.path.isfile(_ico):
    datas.append((_ico, "ops"))

# Bundle the compiled C++ engine next to the app if it has been built.
for _cand in (("build", "Release", "mal_engine.exe"),
              ("build", "mal_engine.exe")):
    if _exists(*_cand):
        datas.append((os.path.join(ROOT, *_cand), "."))
        break

# Dash / Plotly ship data + many lazily-imported submodules; collect them.
hiddenimports = [
    "dash", "plotly", "pandas", "yaml", "numpy", "cryptography", "requests",
]
try:
    from PyInstaller.utils.hooks import collect_submodules, collect_data_files
    hiddenimports += collect_submodules("dash")
    hiddenimports += collect_submodules("plotly")
    datas += collect_data_files("dash")
    datas += collect_data_files("plotly")
except Exception:  # noqa: BLE001
    pass


block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "ui", "desktop.py")],
    pathex=[ROOT, os.path.join(ROOT, "ui")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "tkinter", "matplotlib"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MarketAILab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app — no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=(_ico if os.path.isfile(_ico) else None),
)

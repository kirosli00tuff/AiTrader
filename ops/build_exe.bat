@echo off
REM ===========================================================================
REM Market AI Lab - build the Windows desktop app (dist\MarketAILab.exe).
REM
REM ONE command that:
REM   1. Configures + builds the C++ engine with MSVC (Release) via CMake.
REM   2. Creates a Python venv and installs the UI + desktop + bridge deps.
REM   3. Runs PyInstaller to produce a single dist\MarketAILab.exe that bundles
REM      the Dash dashboard, the Python advisory services, and the engine.
REM
REM PREREQUISITES (install once):
REM   * Visual Studio Build Tools 2022 -> "Desktop development with C++"
REM       (provides MSVC, the Windows SDK, and CMake/Ninja). Run THIS script
REM       from a "Developer Command Prompt for VS 2022" so cl.exe is on PATH.
REM   * Python 3.12 64-bit (3.13 also works) with "Add to PATH" checked.
REM   * Git for Windows. WebView2 runtime is built into Windows 10/11.
REM
REM DISK SPACE: keep ~5-10 GB free on whichever drive holds this repo. The
REM   venv + PyInstaller scratch are large. To keep temp OFF a full C: drive,
REM   set TEMP/TMP to the repo's drive before running, e.g.:
REM       mkdir E:\maltmp  &  set TEMP=E:\maltmp  &  set TMP=E:\maltmp
REM
REM USAGE (from the repo root, e.g. E:\AiTrader):
REM   ops\build_exe.bat
REM ===========================================================================
setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
pushd "%REPO_ROOT%"
set "REPO_ROOT=%CD%"

if "%PYTHON%"=="" set "PYTHON=python"
if "%VENV%"=="" set "VENV=%REPO_ROOT%\.venv"

echo == Market AI Lab - desktop .exe builder ==
echo repo: %REPO_ROOT%
echo temp: %TEMP%
echo.

REM --- 0. Sanity: is the C++ compiler available? ----------------------------
where cl >nul 2>&1
if errorlevel 1 (
  echo [build] WARNING: MSVC 'cl.exe' not found on PATH.
  echo [build]   Open "Developer Command Prompt for VS 2022" and re-run, OR
  echo [build]   install VS Build Tools 2022 with "Desktop development with C++".
  echo [build]   Continuing anyway in case CMake finds a generator...
  echo.
)

REM --- 1. Build the C++ engine (MSVC / Release) -----------------------------
echo [build] configuring + building C++ engine (Release) ...
cmake -S "%REPO_ROOT%" -B "%REPO_ROOT%\build" || goto :error
cmake --build "%REPO_ROOT%\build" --config Release || goto :error

set "ENGINE=%REPO_ROOT%\build\Release\mal_engine.exe"
if not exist "%ENGINE%" set "ENGINE=%REPO_ROOT%\build\mal_engine.exe"
if exist "%ENGINE%" (
  echo [build] engine built: %ENGINE%
) else (
  echo [build] WARNING: engine binary not found after build. The .exe will
  echo [build]   still be created; place mal_engine.exe next to MarketAILab.exe
  echo [build]   later, or re-run once the engine builds cleanly.
)

REM --- 2. Python venv + dependencies ----------------------------------------
if not exist "%VENV%" (
  echo [build] creating venv at %VENV% ...
  "%PYTHON%" -m venv "%VENV%" || goto :error
)
call "%VENV%\Scripts\activate.bat" || goto :error
python -m pip install --upgrade pip || goto :error
echo [build] installing dependencies ...
python -m pip install -r "%REPO_ROOT%\python_bridge\requirements.txt" || goto :error
python -m pip install -r "%REPO_ROOT%\ui\requirements.txt" || goto :error
python -m pip install -r "%REPO_ROOT%\ui\requirements-desktop.txt" || goto :error

REM --- 3. (Re)generate the icon if pillow is present ------------------------
if not exist "%REPO_ROOT%\ops\MarketAILab.ico" (
  echo [build] generating app icon ...
  python "%REPO_ROOT%\ops\_make_icon.py" || echo [build] icon generation skipped
)

REM --- 4. Package with PyInstaller ------------------------------------------
echo [build] packaging dist\MarketAILab.exe with PyInstaller ...
pyinstaller "%REPO_ROOT%\ui\MarketAILab.spec" --noconfirm --clean || goto :error

echo.
if exist "%REPO_ROOT%\dist\MarketAILab.exe" (
  echo [build] SUCCESS -> %REPO_ROOT%\dist\MarketAILab.exe
  echo [build] Double-click it, or run it, to open the 24/7 desktop app.
) else (
  echo [build] PyInstaller finished but dist\MarketAILab.exe was not found.
  echo [build] Check the output above for errors.
)
popd
endlocal
goto :eof

:error
echo.
echo [build] ERROR during build. See the messages above.
echo [build] Common causes: MSVC not on PATH (use the VS Developer Prompt),
echo [build]   disk full (set TEMP/TMP to a drive with space), or a missing
echo [build]   Python 64-bit install.
popd
endlocal
exit /b 1

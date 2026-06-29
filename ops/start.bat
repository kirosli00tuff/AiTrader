@echo off
REM ===========================================================================
REM Market AI Lab - one-click LOCAL 24/7 launcher (Windows).
REM
REM Builds the C++ engine if needed, sets up the Python venv, then starts:
REM   1. python_bridge (advisory + Alpaca data/paper RPC) in a background window
REM   2. the C++ engine in CONTINUOUS (24/7) paper mode in a background window
REM   3. the Plotly Dash control board (this window) at http://localhost:8050
REM and opens your browser to the dashboard.
REM
REM Offline-safe: with no API keys it auto-falls-back to the mock feed and
REM sim-at-live-price paper fills. Live trading stays DISABLED.
REM
REM Usage:
REM   ops\start.bat                 (mock feed, config interval)
REM   set DATA_SOURCE=alpaca ^& ops\start.bat   (real-time Alpaca data)
REM   set INTERVAL=10 ^& ops\start.bat          (override loop interval)
REM ===========================================================================
setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
pushd "%REPO_ROOT%"
set "REPO_ROOT=%CD%"

if "%VENV%"=="" set "VENV=%REPO_ROOT%\.venv"
if "%PYTHON%"=="" set "PYTHON=python"
if "%MAL_DB_PATH%"=="" set "MAL_DB_PATH=%REPO_ROOT%\market_ai_lab.db"
set "SCHEMA=%REPO_ROOT%\storage\schema.sql"
if "%MAL_CONFIG_PATH%"=="" set "MAL_CONFIG_PATH=%REPO_ROOT%\config\default_config.yaml"
if "%DATA_SOURCE%"=="" set "DATA_SOURCE=mock"
if "%INTERVAL%"=="" set "INTERVAL=0"
if "%BRIDGE_PORT%"=="" set "BRIDGE_PORT=8765"
if "%MAL_DASH_HOST%"=="" set "MAL_DASH_HOST=127.0.0.1"
if "%MAL_DASH_PORT%"=="" set "MAL_DASH_PORT=8050"

echo == Market AI Lab - local 24/7 launcher ==
echo repo: %REPO_ROOT%
echo data source: %DATA_SOURCE%   db: %MAL_DB_PATH%

REM --- 1. Build the engine if missing ---------------------------------------
if not exist "%REPO_ROOT%\build\mal_engine.exe" (
  echo [start] building C++ engine ...
  cmake -S "%REPO_ROOT%" -B "%REPO_ROOT%\build" || goto :error
  cmake --build "%REPO_ROOT%\build" --config Release || goto :error
)

REM --- 2. Python venv + deps -------------------------------------------------
if not exist "%VENV%" (
  echo [start] creating venv at %VENV% ...
  "%PYTHON%" -m venv "%VENV%" || goto :error
)
call "%VENV%\Scripts\activate.bat"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r "%REPO_ROOT%\python_bridge\requirements.txt"
python -m pip install --quiet -r "%REPO_ROOT%\ui\requirements.txt"

REM Resolve the engine binary path (CMake may place it under Release\).
set "ENGINE=%REPO_ROOT%\build\mal_engine.exe"
if not exist "%ENGINE%" set "ENGINE=%REPO_ROOT%\build\Release\mal_engine.exe"

if not exist "%MAL_DB_PATH%" (
  echo [start] seeding fresh database ...
  "%ENGINE%" --config "%MAL_CONFIG_PATH%" --db "%MAL_DB_PATH%" --schema "%SCHEMA%" --iterations 1 >nul
)

REM --- 3. Start the python bridge -------------------------------------------
echo [start] starting python_bridge on 127.0.0.1:%BRIDGE_PORT% ...
start "mal_bridge" cmd /c "set BRIDGE_PORT=%BRIDGE_PORT%& python "%REPO_ROOT%\python_bridge\server.py""

REM --- 4. Start the engine in CONTINUOUS mode -------------------------------
echo [start] starting engine (continuous, source=%DATA_SOURCE%) ...
set "ENGINE_ARGS=--config "%MAL_CONFIG_PATH%" --db "%MAL_DB_PATH%" --schema "%SCHEMA%" --continuous --data-source %DATA_SOURCE% --bridge 127.0.0.1:%BRIDGE_PORT%"
if not "%INTERVAL%"=="0" set "ENGINE_ARGS=%ENGINE_ARGS% --interval-seconds %INTERVAL%"
start "mal_engine" cmd /c ""%ENGINE%" %ENGINE_ARGS%"

REM --- 5. Open the dashboard -------------------------------------------------
set "URL=http://%MAL_DASH_HOST%:%MAL_DASH_PORT%"
if not "%NO_BROWSER%"=="1" start "" "%URL%"

echo [start] launching Dash control board at %URL% (close this window or Ctrl-C to stop the UI)
echo [start] engine + bridge run in separate windows; close them to stop trading.
cd "%REPO_ROOT%\ui"
python app.py
goto :eof

:error
echo [start] ERROR during setup. See messages above.
popd
exit /b 1

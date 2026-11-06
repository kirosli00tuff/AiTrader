#!/usr/bin/env bash
# C.3 full-suite wrapper. Usage: run_suite.sh <logfile> [pytest targets...]
# Refuses to start with MemAvailable under 2 GB or from 22:55 to 23:45 local on
# weekdays. Stops the run if MemAvailable falls under 2 GB or 23:00 arrives.
# Exit 75 means refused or stopped: rerun later, nothing is wrong with the code.
set -u
cd /home/kiros-li/Documents/GitHub/AiTrader || exit 1
LOG="$1"; shift
[ "$#" -gt 0 ] || set -- tests/test_news_eval_*.py
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-$HOME/.cache/news_eval_pyc}"
MIN_KB=$((2048 * 1024))
avail() { awk '/^MemAvailable:/{print $2}' /proc/meminfo; }
weekday() { [ "$(date +%u)" -le 5 ]; }
hhmm() { date +%H%M; }
now=$(hhmm)
if weekday && [ "$now" -ge 2255 ] && [ "$now" -lt 2345 ]; then
  echo "REFUSED: collector window, time $now"; exit 75
fi
a=$(avail)
if [ "$a" -lt "$MIN_KB" ]; then
  echo "REFUSED: MemAvailable $((a / 1024)) MB under 2048 MB"; exit 75
fi
start=$(date +%s); low=$a
nice -n 10 .venv-eval/bin/python -m pytest -q "$@" > "$LOG" 2>&1 &
PID=$!
stop() { kill -TERM "$PID" 2>/dev/null; sleep 3; kill -KILL "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; }
while kill -0 "$PID" 2>/dev/null; do
  a=$(avail); [ "$a" -lt "$low" ] && low=$a
  if [ "$a" -lt "$MIN_KB" ]; then
    stop; echo "STOPPED: MemAvailable $((a / 1024)) MB under 2048 MB"; exit 75
  fi
  now=$(hhmm)
  if weekday && [ "$now" -ge 2300 ] && [ "$now" -lt 2345 ]; then
    stop; echo "STOPPED: collector window, time $now"; exit 75
  fi
  sleep 5
done
wait "$PID"; rc=$?
tail -n 4 "$LOG"
echo "exit=$rc seconds=$(( $(date +%s) - start )) lowest_MemAvailable_MB=$((low / 1024))"
exit "$rc"

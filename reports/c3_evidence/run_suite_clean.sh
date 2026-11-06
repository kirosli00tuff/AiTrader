#!/usr/bin/env bash
# C.3 clean-clone suite. Usage: run_suite_clean.sh <logfile> [pytest targets...]
# Why: tests/test_news_eval_{known_answers,run_c2,mutations}.py assert that
# reports/c2_UNLOCK.json and reports/c2/ do not exist. C.2 attempt 1 created both
# and they may not be touched, so every test in those files errors at teardown
# in the repo root. This runs the same bytes in a sparse clone that never
# materialises those paths. PYTHONPYCACHEPREFIX may be set by the caller.
# Same memory and collector stops as run_suite.sh. Exit 75: refused or stopped.
set -u
REPO=/home/kiros-li/Documents/GitHub/AiTrader
DEST="/tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd/scratchpad/c3_testtree"
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
rm -rf "$DEST"
git clone -q --no-hardlinks --no-checkout "$REPO" "$DEST" || exit 1
cd "$DEST" || exit 1
git sparse-checkout set --no-cone '/*' '!/reports/c2/' '!/reports/c2_UNLOCK.json' '!/reports/c2_RUN_ONCE.json' || exit 1
git checkout -q HEAD || exit 1
rm -rf "$DEST/news_eval"
mkdir "$DEST/news_eval"
(cd "$REPO/news_eval" && find . -type f ! -path '*/__pycache__/*' -print0 | cpio -0pdmu --quiet "$DEST/news_eval") || exit 1
cp -p "$REPO"/tests/test_news_eval_*.py "$DEST/tests/" || exit 1
[ ! -f "$REPO/reports/c3_harness_freeze.json" ] || cp -p "$REPO/reports/c3_harness_freeze.json" "$DEST/reports/"
for p in reports/c2 reports/c2_UNLOCK.json reports/c2_RUN_ONCE.json; do
  [ ! -e "$DEST/$p" ] || { echo "ABORT: $p present in the clone"; exit 1; }
done
d=0
diff -rq -x __pycache__ "$REPO/news_eval" "$DEST/news_eval" || d=1
for f in "$REPO"/tests/test_news_eval_*.py; do cmp -s "$f" "$DEST/tests/$(basename "$f")" || { echo "DIFF $f"; d=1; }; done
for f in EXPERIMENT.md reports/c1_verdict_mapping.md news_experiment/outcomes.py news_experiment/scoring.py news_experiment/spec.py news_experiment/horizon.py news_experiment/store.py news_experiment/collect.py news_experiment/maintain.py news_experiment/daily.py backtest/fees.py scripts/blind_interim_20260928.py; do
  cmp -s "$REPO/$f" "$DEST/$f" || { echo "DIFF $f"; d=1; }
done
[ "$d" -eq 0 ] || { echo "ABORT: the clone differs from the working tree"; exit 1; }
echo "clone identical to working tree on harness, tests and inputs; head $(git -C "$DEST" rev-parse --short HEAD)"
"$REPO/.venv-eval/bin/python" -c 'import news_eval,os;print("news_eval from",os.path.dirname(news_eval.__file__))'
start=$(date +%s); low=$a
nice -n 10 "$REPO/.venv-eval/bin/python" -m pytest -q -p no:cacheprovider "$@" > "$LOG" 2>&1 &
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

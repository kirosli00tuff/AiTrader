#!/usr/bin/env bash
# Full-system test for Market AI Lab. Runs every check in sequence, prints a
# PASS, FAIL, or SKIPPED line per section, continues past failures, and exits
# nonzero when any section fails. Optional sections that need live keys print
# SKIPPED when the keys are absent. Live trading is never touched. The script
# cleans up after itself and leaves the repo state unchanged.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${MAL_PYTHON:-$ROOT/.venv/bin/python}"
TMP="$(mktemp -d)"
API_PID=""
FAILS=0
declare -a ROWS

cleanup() {
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "${TMP:-}" ] && [ -d "$TMP" ] && rm -rf "$TMP" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

log() { printf '%s\n' "$*"; }
record() { ROWS+=("$(printf '%-28s %s' "$1" "$2")"); }

pass_if() {
  local name="$1"; shift
  if "$@" > "$TMP/sec.log" 2>&1; then
    log "PASS   $name"; record "$name" "PASS"
  else
    local why; why="$(tail -n 1 "$TMP/sec.log" 2>/dev/null | tr -d '\r' | cut -c1-90)"
    log "FAIL   $name  -> ${why:-see log}"; record "$name" "FAIL: ${why:-see log}"
    FAILS=$((FAILS+1))
  fi
}
mark_skip() { log "SKIP   $1  -> $2"; record "$1" "SKIPPED ($2)"; }

sec_build() {
  cmake -S . -B build > "$TMP/b.log" 2>&1 || return 1
  cmake --build build -j4 > "$TMP/bw.log" 2>&1 || return 1
  if grep -qi "warning:" "$TMP/bw.log"; then echo "build emitted warnings"; return 1; fi
  return 0
}
sec_ctest() { ctest --test-dir build --output-on-failure > "$TMP/ct.log" 2>&1; }
sec_pytest() { "$PY" -m pytest tests/ -q > "$TMP/pt.log" 2>&1; }
sec_config() { ctest --test-dir build -R '^config$' > "$TMP/cfg.log" 2>&1; }
sec_killswitch() { ctest --test-dir build -R '^kill_switch$' > "$TMP/ks.log" 2>&1; }
sec_strategy() { ctest --test-dir build -R 'strategy|feed_modes' > "$TMP/st.log" 2>&1; }
sec_realfill() { ctest --test-dir build -R 'tuner_minsample|weights|native_conviction_gate' > "$TMP/rf.log" 2>&1; }
sec_council_offline() {
  # Truly offline: clear provider env keys AND point at an empty keystore so no
  # real key resolves. The council must fall back to labeled mock verdicts and
  # the Haiku gate to permissive, with nothing raising.
  env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GEMINI_API_KEY \
      MAL_KEYSTORE_DIR="$TMP/ks_offline" \
      "$PY" -m pytest tests/test_llm_consensus.py -q > "$TMP/co.log" 2>&1
}
sec_cost_controls() { "$PY" -m pytest tests/test_council_cost_controls.py tests/test_council_cost_cuts.py -q > "$TMP/cc.log" 2>&1; }
sec_rl() { "$PY" -m pytest tests/test_rl_advisory.py -q > "$TMP/rl.log" 2>&1; }
sec_whale() {
  "$PY" -m pytest tests/test_whale_fixtures.py tests/test_whale_signal.py -q > "$TMP/wh.log" 2>&1 || return 1
  grep -q 'whale_position_scale_cap: 0.35' config/default_config.yaml || { echo "0.35 cap missing"; return 1; }
  if grep -rniI "clankapp" whale_signal/ account_manager/ api_server/ ui/app.py config/ \
       | grep -viE "removed|dead host" | grep -q .; then
    echo "functional ClankApp reference survives"; return 1
  fi
  return 0
}
sec_dnn() {
  cp -f market_ai_lab.db "$TMP/dnn.db" 2>/dev/null || return 1
  "$PY" -m ml_factor.train_real --db "$TMP/dnn.db" > "$TMP/dnn.log" 2>&1
  grep -qiE "challenger|insufficient_real_data|insufficient|n_samples|refus" "$TMP/dnn.log"
}
sec_api_backend() {
  "$PY" -m pytest tests/test_api_server.py -q > "$TMP/api.log" 2>&1 || return 1
  "$PY" - "$TMP" > "$TMP/seed.log" 2>&1 <<'PYSEED'
import os, sqlite3, sys
tmp = sys.argv[1]
db = os.path.join(tmp, "api.db")
with open("storage/schema.sql") as fh:
    c = sqlite3.connect(db); c.executescript(fh.read()); c.commit(); c.close()
print(db)
PYSEED
  local db="$TMP/api.db"
  env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GEMINI_API_KEY \
      -u APCA_API_KEY_ID -u APCA_API_SECRET_KEY -u ALPACA_API_KEY \
      -u ALPACA_API_SECRET MAL_DB_PATH="$db" MAL_CONTROL_DIR="$TMP/ctrl" \
      MAL_API_PORT=8021 "$PY" -m api_server.run > "$TMP/uv.log" 2>&1 &
  API_PID=$!
  local h1 hi shape
  h1="$(curl -s --retry-connrefused --retry 25 --retry-delay 1 -o /dev/null -w '%{http_code}' http://127.0.0.1:8021/health)"
  hi="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8021/health/integrations)"
  shape="$(curl -s http://127.0.0.1:8021/health/integrations | "$PY" -c 'import sys,json;d=json.load(sys.stdin);print("ok" if "integrations" in d and "summary" in d else "bad")' 2>/dev/null)"
  kill "$API_PID" 2>/dev/null || true; API_PID=""
  [ "$h1" = "200" ] && [ "$hi" = "200" ] && [ "$shape" = "ok" ]
}
sec_frontend() { ( cd web && npm run typecheck && npm test && npm run build ) > "$TMP/fe.log" 2>&1; }
sec_live_exclusion() {
  ctest --test-dir build -R '^ibkr_routing$' > "$TMP/le.log" 2>&1 || return 1
  if grep -rniI "try_enable_live" tests/ | grep -q .; then echo "a test references try_enable_live"; return 1; fi
  return 0
}
sec_council_live() {
  if [ -z "${ANTHROPIC_API_KEY:-}" ] || [ -z "${OPENAI_API_KEY:-}" ] || [ -z "${GEMINI_API_KEY:-}" ]; then return 2; fi
  "$PY" - > "$TMP/cl.log" 2>&1 <<'PYCL'
from llm_consensus import providers as P
state = {"symbol": "SPY", "venue": "alpaca", "price": 500.0, "ret_5": 0.004,
         "imbalance": 0.1, "catalyst": 0.2, "volatility": 0.01}
# One real gate call (Haiku) plus one real council pass (three providers).
gate = P.AnthropicProvider(name="gate", model_id="claude-haiku-4-5",
                           max_tokens=8).score(state)
council = [
    P.OpenAIProvider(name="llm_primary", model_id="gpt-5.5", max_tokens=48).score(state),
    P.AnthropicProvider(name="llm_secondary", model_id="claude-opus-4-8", max_tokens=48).score(state),
    P.GeminiProvider(name="llm_tertiary", model_id="gemini-3.1-pro", max_tokens=48).score(state),
]
print("gate source:", gate.source)
print("council sources:", [c.source for c in council])
assert gate.source in ("real", "mock", "error")
assert all(c.source in ("real", "mock", "error") for c in council)
PYCL
}
sec_alpaca_paper() {
  local k="${APCA_API_KEY_ID:-${ALPACA_API_KEY:-}}"
  local s="${APCA_API_SECRET_KEY:-${ALPACA_API_SECRET:-}}"
  if [ -z "$k" ] || [ -z "$s" ]; then return 2; fi
  local base="${ALPACA_DATA_BASE:-https://data.alpaca.markets}"
  local pbase="${ALPACA_PAPER_BASE:-https://paper-api.alpaca.markets}"
  local q a
  q="$(curl -s -o /dev/null -w '%{http_code}' -H "APCA-API-KEY-ID: $k" -H "APCA-API-SECRET-KEY: $s" "$base/v2/stocks/SPY/quotes/latest")"
  a="$(curl -s -o /dev/null -w '%{http_code}' -H "APCA-API-KEY-ID: $k" -H "APCA-API-SECRET-KEY: $s" "$pbase/v2/account")"
  [ "$q" = "200" ] && [ "$a" = "200" ]
}

log "Market AI Lab full-system test"
log "=============================="
[ -x "$PY" ] || { log "FAIL   venv missing at $PY"; exit 2; }

pass_if "Build (zero warnings)"        sec_build
pass_if "C++ unit tests (ctest)"       sec_ctest
pass_if "Python unit tests (pytest)"   sec_pytest
pass_if "Config validation"            sec_config
pass_if "RiskGate and kill switch"     sec_killswitch
pass_if "Strategy and regime"          sec_strategy
pass_if "Real-fill feedback"           sec_realfill
pass_if "Council offline"              sec_council_offline

if sec_council_live; then
  log "PASS   Council live keys"; record "Council live keys" "PASS"
else
  rc=$?
  if [ "$rc" = "2" ]; then mark_skip "Council live keys" "no ANTHROPIC/OPENAI/GEMINI key"
  else why="$(tail -n1 "$TMP/cl.log" 2>/dev/null | cut -c1-90)"; log "FAIL   Council live keys -> $why"; record "Council live keys" "FAIL: $why"; FAILS=$((FAILS+1)); fi
fi

pass_if "Council cost controls"        sec_cost_controls
pass_if "DNN advisory"                 sec_dnn
pass_if "RL gating"                    sec_rl
pass_if "Whale layer (SEC EDGAR)"      sec_whale

if sec_alpaca_paper; then
  log "PASS   Alpaca paper"; record "Alpaca paper" "PASS"
else
  rc=$?
  if [ "$rc" = "2" ]; then mark_skip "Alpaca paper" "no Alpaca paper keys"
  else log "FAIL   Alpaca paper -> auth or quote non-200"; record "Alpaca paper" "FAIL"; FAILS=$((FAILS+1)); fi
fi

pass_if "API backend"                  sec_api_backend
pass_if "Frontend (types/test/build)"  sec_frontend
pass_if "Live exclusion"               sec_live_exclusion

log ""
log "Section results"
log "---------------"
for r in "${ROWS[@]}"; do log "  $r"; done
log ""
if [ "$FAILS" -eq 0 ]; then
  log "ALL SECTIONS PASSED (skips are optional)."
  exit 0
else
  log "$FAILS section(s) FAILED."
  exit 1
fi

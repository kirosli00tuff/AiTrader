#!/bin/bash
DB="$HOME/Documents/GitHub/AiTrader/market_ai_lab.db"
cd "$HOME/Documents/GitHub/AiTrader" || exit 1

echo "========== 1. PROCESSES =========="
ps aux | grep -E "mal_engine|ops.watchdog" | grep -v grep
sudo ss -tulpn | grep -E "8765|8000|5173"

echo
echo "========== 2. BRIDGE FD + HEALTH (want ~13, flat) =========="
BP=$(sudo ss -tulpn | grep 8765 | grep -oP 'pid=\K[0-9]+' | head -1)
echo "fds: $(ls /proc/$BP/fd 2>/dev/null | wc -l)"
curl -s http://127.0.0.1:8765/health

echo
echo "========== 3. ENGINE HEARTBEAT (rewritten every loop, stale >15s = dead) =========="
cat .run/engine_heartbeat.json 2>/dev/null || echo "no heartbeat file"
echo "now: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo
echo "========== 4. LOOP STATE + PROFILE (want source=alpaca) =========="
sqlite3 -header -column "$DB" "SELECT ts, kind, substr(message,1,70) FROM events WHERE kind IN ('startup','continuous_start','continuous_stop') ORDER BY id DESC LIMIT 4;"
echo "--- resolved profile lever ---"
grep -o '"strategy_profile":[^,}]*' .control/controls.json 2>/dev/null || echo "key not found"

echo
echo "========== 5. BAR PROVENANCE + VOLUME SOURCE (30m) =========="
sqlite3 -header -column "$DB" "SELECT symbol, source, COUNT(*) AS n, MAX(timestamp) FROM bars WHERE timeframe='5min' AND timestamp > datetime('now','-30 minutes') GROUP BY symbol, source ORDER BY symbol;"

echo
echo "========== 6. REAL VENUE VOLUME ARRIVING (the 07-23 fix) =========="
echo "want: nonzero volume on recent real_feed bars, volume_source NOT fabricated"
sqlite3 -header -column "$DB" "SELECT symbol, volume, volume_source, timestamp FROM bars WHERE timeframe='5min' AND source='real_feed' AND timestamp > datetime('now','-1 hour') ORDER BY timestamp DESC LIMIT 12;" 2>/dev/null || echo "volume_source column missing, check schema"

echo
echo "========== 7. CRITICAL EVENTS (want empty) =========="
sqlite3 -header -column "$DB" "SELECT ts, kind, substr(message,1,70) FROM events WHERE severity='critical' OR kind IN ('feed_substitution','bridge_degraded','provenance_block','symbol_unavailable','position_unmanageable') ORDER BY id DESC LIMIT 8;"

echo
echo "========== 8. ENTRY DECISIONS (24h) — every candidate, rejections included =========="
sqlite3 -header -column "$DB" "SELECT COUNT(*) AS total FROM entry_decision WHERE ts > datetime('now','-24 hours');" 2>/dev/null || echo "entry_decision table missing"
sqlite3 -header -column "$DB" "SELECT ts, symbol, outcome, first_reject, tier, round(confidence,3) AS conf FROM entry_decision WHERE ts > datetime('now','-24 hours') ORDER BY rowid DESC LIMIT 15;" 2>/dev/null

echo
echo "========== 9. WHERE CANDIDATES DIE (first refusing condition) =========="
sqlite3 -header -column "$DB" "SELECT outcome, first_reject, COUNT(*) AS n FROM entry_decision WHERE ts > datetime('now','-24 hours') GROUP BY outcome, first_reject ORDER BY n DESC;" 2>/dev/null

echo
echo "========== 10. FACTOR PARTICIPATION (benched vs live) =========="
curl -s http://127.0.0.1:8000/factors/participation 2>/dev/null || echo "backend down or endpoint missing"

echo
echo "========== 11. POSITION HEALTH (past stop / target / time-stop) =========="
curl -s http://127.0.0.1:8000/positions/exits 2>/dev/null || echo "backend down or endpoint missing"
echo "--- positions table with exit state ---"
sqlite3 -header -column "$DB" "SELECT symbol, side, qty, avg_price, stop_price, target_price, bars_held FROM positions WHERE qty != 0;" 2>/dev/null

echo
echo "========== 12. TRADES (24h) =========="
sqlite3 -header -column "$DB" "SELECT ts, kind, symbol, substr(message,1,60) FROM events WHERE kind IN ('trade_entry','trade_exit') AND ts > datetime('now','-24 hours') ORDER BY id DESC LIMIT 20;"

echo
echo "========== 13. COUNCIL EVALS (24h) =========="
sqlite3 -header -column "$DB" "SELECT id, ts, symbol, bias, confidence, verdict, directional_count, abstentions FROM council_eval WHERE ts > datetime('now','-24 hours') ORDER BY id DESC LIMIT 10;"

echo
echo "========== 14. DISCOVERY + BUDGET SPLIT (24h) =========="
sqlite3 -header -column "$DB" "SELECT ts, kind, substr(message,1,65) FROM events WHERE kind LIKE '%discover%' AND ts > datetime('now','-24 hours') ORDER BY id DESC LIMIT 12;"

echo
echo "========== 15. STOP ATTRIBUTION (who stopped what) =========="
sqlite3 -header -column "$DB" "SELECT ts, kind, substr(message,1,70) FROM events WHERE kind IN ('engine_stop_requested','engine_start_requested','process_stop','watchdog_restart','engine_uptime') ORDER BY id DESC LIMIT 10;"

echo
echo "========== 16. EVENT COUNTS (24h) =========="
sqlite3 -header -column "$DB" "SELECT kind, COUNT(*) FROM events WHERE ts > datetime('now','-24 hours') GROUP BY kind ORDER BY COUNT(*) DESC LIMIT 18;"

echo
echo "========== 17. RL GATE =========="
sqlite3 -column "$DB" "SELECT COUNT(*) || ' / 500 strategy fills' FROM trades WHERE origin='strategy';"

echo
echo "========== 18. COUNCIL REFUSALS (free, before any provider call) =========="
sqlite3 -header -column "$DB" "SELECT ts, symbol, reason FROM council_refusal ORDER BY rowid DESC LIMIT 10;" 2>/dev/null || echo "council_refusal table not found"

echo
echo "========== 19. PER-PROVIDER VERDICTS (abstention vs error) =========="
sqlite3 -header -column "$DB" "SELECT eval_id, slot, direction, round(confidence,3) AS conf, abstained, substr(rationale,1,70) AS why FROM council_eval_provider ORDER BY id DESC LIMIT 9;" 2>/dev/null || echo "council_eval_provider table not found"

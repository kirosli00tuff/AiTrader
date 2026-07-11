#!/usr/bin/env bash
# Real end-to-end verification of the live integrations. Resolves keys through
# the unified keystore-first resolver (account_manager.credentials) and runs ONE
# real minimal round trip per integration. Prints a labeled result table and
# appends it to RETURN.md. Never places a resting order, never touches live,
# never prints a key value. One minimal call per provider, spend near zero.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
PY="${MAL_PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || { echo "venv missing at $PY" >&2; exit 2; }

TABLE="$("$PY" - <<'PYV'
from api_server import health
CHECKS = [
    ("OpenAI GPT-5.5", "openai", health._check_openai),
    ("Anthropic Opus 4.8", "anthropic_opus", lambda: health._anthropic("claude-opus-4-8")),
    ("Anthropic Haiku 4.5 (gate path)", "anthropic_haiku_gate", lambda: health._anthropic("claude-haiku-4-5")),
    ("Gemini 3.1 Pro", "gemini", health._check_gemini),
    ("Alpaca paper market data", "alpaca_data", health._check_alpaca_data),
    ("Alpaca paper order-auth (validation-only)", "alpaca_order_auth", health._check_alpaca_trading),
]
print("| Integration | Result | Detail | Latency |")
print("| --- | --- | --- | --- |")
for label, name, fn in CHECKS:
    r = health._run(name, label, fn)
    lat = "-" if r["latency_ms"] is None else f"{r['latency_ms']} ms"
    reason = (r["reason"] or "-").replace("|", "/")[:70]
    print(f"| {label} | {r['state']} | {reason} | {lat} |")
PYV
)"
echo "Live integration verification"
echo "============================="
echo "$TABLE"

if ! grep -q "^## Live Integration Verification Log" RETURN.md 2>/dev/null; then
  printf '\n## Live Integration Verification Log\n' >> RETURN.md
fi
{
  printf '\n### Run %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s\n' "$TABLE"
} >> RETURN.md
echo ""
echo "Appended to RETURN.md"

#!/usr/bin/env python3
"""Measure one full REAL council round trip end to end, per provider and total.

Task 1 of the timeout fix. Calls the council path DIRECTLY with a representative
market snapshot (it never forces a trade) and prints the wall-clock time for the
Haiku base-check gate and each of the three providers, plus the total, at the
configured council_max_tokens. This gives the real number the engine's
bridge-call timeout must exceed.

Usage:
  .venv/bin/python -m scripts.measure_council_latency
  .venv/bin/python scripts/measure_council_latency.py

Needs the provider keys to resolve (keystore or env) to measure the REAL
latency. Without keys each provider returns a labelled mock instantly, and the
script says so, so a run with no keys is honest about what it measured.
"""
from __future__ import annotations

import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from llm_consensus.config_access import (  # noqa: E402
    council_max_tokens, gate_timeout_seconds, provider_timeout_seconds,
)
from llm_consensus.consensus import build_gate, real_providers  # noqa: E402

# A representative native-entry snapshot (a plausible momentum setup on crypto,
# which trades 24/7 so the measurement does not depend on market hours).
_STATE = {
    "symbol": "BTC/USD", "venue": "alpaca", "price": 62000.0,
    "ret_5": 0.012, "imbalance": 0.35, "catalyst": 0.4, "volatility": 0.02,
}


def _timed(label: str, fn):
    t0 = time.perf_counter()
    try:
        result = fn()
        source = getattr(result, "source", None)
    except Exception as e:  # never abort the measurement
        result, source = None, f"raised: {type(e).__name__}"
    dt = time.perf_counter() - t0
    return label, dt, source, result


def main() -> int:
    print("Council latency measurement (Task 1)")
    print("=" * 44)
    print(f"  council_max_tokens={council_max_tokens()}  "
          f"provider_timeout={provider_timeout_seconds()}s  "
          f"gate_timeout={gate_timeout_seconds()}s")
    print("")

    total_t0 = time.perf_counter()
    rows = []

    gate = build_gate()
    rows.append(_timed("gate (haiku base-check)",
                       lambda: gate.should_review(_STATE)))

    for p in real_providers():
        rows.append(_timed(f"{p.name} ({p.model_id})",
                           lambda p=p: p.score(_STATE)))

    total = time.perf_counter() - total_t0

    real_any = False
    for label, dt, source, _ in rows:
        src = source or "?"
        if src == "real":
            real_any = True
        print(f"  {label:<34} {dt*1000:8.1f} ms   [{src}]")
    print("  " + "-" * 42)
    print(f"  {'TOTAL (gate + 3 providers)':<34} {total*1000:8.1f} ms")
    print("")
    if real_any:
        print("  Measured REAL provider latency. Set the engine's council call")
        print("  timeout comfortably above the TOTAL above (config council."
              "engine_council_call_timeout_ms).")
    else:
        print("  NOTE: no provider returned source=real (keys did not resolve),")
        print("  so this measured the instant mock path, not real latency. Run")
        print("  where the provider keys resolve to get the real number.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

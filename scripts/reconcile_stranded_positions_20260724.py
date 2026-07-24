"""One-time reconciliation of the three unmanageable stranded positions.

BTC-USD (legacy dash symbol the feed never polls), PRES-2028-YES and
FED-CUT-Q3 (venue polymarket, removed 2026-07-06) cannot be quoted, managed,
or closed by any code path, and each raises a critical position_unmanageable
event at every startup. Per the SOL/USD precedent: closed through the
JOURNALLED EVENT PATH, never a raw delete.

Per position: a closing trade row with origin 'reconciliation' (excluded from
every real-fill gate, which count 'strategy' only), pnl 0.0 with outcome
'flat' BECAUSE NO MARKET EXISTS TO MARK AGAINST (booking any other number
would invent a price; the honesty note rides in the event), the position row
zeroed through the same upsert semantics a native exit uses (row kept,
qty=0), and a position_reconciled event recording who, why, and the evidence.
All five stranded positions are PAPER artifacts; no real capital is involved.
Idempotent: a position already flat is skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TARGETS = {
    ("alpaca", "BTC-USD"):
        "legacy dash symbol form: not in the resolved universe, the feed "
        "never polls it, no bar can ever close (no trade_entry event exists "
        "to recover exits from)",
    ("polymarket", "PRES-2028-YES"):
        "venue polymarket removed 2026-07-06: no quote, no adapter, no exit "
        "path exists",
    ("polymarket", "FED-CUT-Q3"):
        "venue polymarket removed 2026-07-06: no quote, no adapter, no exit "
        "path exists",
}


def reconcile(db_path: str) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(db_path, timeout=10.0)
    out = {"closed": [], "skipped": []}
    try:
        for (venue, symbol), why in TARGETS.items():
            row = conn.execute(
                "SELECT market, category, side, qty, avg_price, notional, "
                "opened_ts, COALESCE(sleeve,'quant_core') FROM positions "
                "WHERE venue=? AND symbol=?", (venue, symbol)).fetchone()
            if not row or not row[3]:
                out["skipped"].append(symbol)
                continue
            market, category, side, qty, avg_price, notional, opened_ts, \
                sleeve = row
            close_side = "sell" if side == "buy" else "buy"
            conn.execute(
                "INSERT INTO trades(ts, venue, symbol, market, category, "
                "side, qty, price, notional, fee, mode, pnl, outcome, "
                "combined_conf, combined_edge, sleeve, origin, bar_source) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, venue, symbol, market, category, close_side, qty,
                 avg_price, notional, 0.0, "paper", 0.0, "flat", 0.0, 0.0,
                 sleeve, "reconciliation", "unknown"))
            conn.execute(
                "UPDATE positions SET qty=0, notional=0, side=?, "
                "avg_price=avg_price WHERE venue=? AND symbol=?",
                (close_side, venue, symbol))
            conn.execute(
                "INSERT INTO events(ts, kind, venue, symbol, severity, "
                "message, payload_json) VALUES(?,?,?,?,?,?,?)",
                (ts, "position_reconciled", venue, symbol, "info",
                 f"Stranded position {symbol} reconciled out through the "
                 f"journalled event path (operator pre-flight, 2026-07-24): "
                 f"{why}. Closed at entry price with pnl 0.0: no market "
                 f"exists to mark against, and booking any other number "
                 f"would invent a price. Paper artifact, no real capital.",
                 json.dumps({"reason": why, "qty": qty,
                             "avg_price": avg_price, "notional": notional,
                             "opened_ts": opened_ts,
                             "origin": "reconciliation",
                             "operator": "pre-flight session 2026-07-24"})))
            out["closed"].append(symbol)
        conn.commit()
        return out
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=os.path.join(_REPO, "market_ai_lab.db"))
    args = ap.parse_args()
    print(json.dumps(reconcile(args.db), indent=2))

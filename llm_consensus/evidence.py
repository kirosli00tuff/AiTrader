"""The council's evidence: only fields with a real source, every one labelled.

THE OMISSION RULE (2026-07-20). A field with no real measurement behind it is
omitted entirely, never rendered as a zero or a stand-in. The Stage-B gate
measured the failure this prevents: padded zeros read as flat evidence and
rejected 12 of 12 finalists (discovery/gate.py). The renderer therefore works
from an ALLOWLIST. A key not in the allowlist never renders, so a future field
cannot reach a model without declaring its units and its source here first.

Fields the engine sends that this module deliberately never renders, because
no real measurement stands behind them (reported in RETURN.md 2026-07-20):
  * imbalance    uniform random in [-1,1] every tick, even on the real feed
  * catalyst     a per-symbol hash constant from MockCatalystProvider
  * ret_5        sum of the last five poll-tick returns, window unstated
  * volatility   stddev of those tick returns, window unstated
Bar-derived returns with stated windows replace the last two. Volume is
rendered only from backfill-provenance bars, because live bars aggregate the
feed's fabricated tick volume.

Enrichment reads the shared SQLite database READ-ONLY (uri mode=ro) and never
raises: any failure yields empty evidence and the prompt renders without those
sections. It runs only when the caller passes an explicit db path in
state["db"], so unit tests stay hermetic.
"""
from __future__ import annotations

import json
import os
import sqlite3

from market_data.tradeable import real_bar_rows

# Bar windows, in 5-minute bars.
_BARS_1H = 12
_BARS_4H = 48
_BARS_24H = 288
_CLOSES_SHOWN = 12


def _num(x, nd: int = 4) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    return f"{v:.{nd}f}".rstrip("0").rstrip(".") or "0"


def _pct(x) -> str:
    try:
        return f"{float(x):+.2f}"
    except (TypeError, ValueError):
        return str(x)


# The allowlist: state key -> (rendered label, units and scale text). Every
# entry MUST carry a non-empty units text, pinned by test. A state key not
# listed here (and not part of a gathered evidence section) never renders.
ALLOWED_FIELDS: dict[str, tuple[str, str]] = {
    "price": ("price", "USD, last trade"),
    "daily_return_pct": ("daily_return", "percent, today vs prior close"),
    "intraday_range_pct": ("intraday_range", "percent of price, day low to day high"),
    "news_sentiment": ("news_sentiment", "[0,1], 0.5 is neutral, Finnhub company news score"),
}


def _resolve_db(db: str) -> str:
    if os.path.isabs(db):
        return db
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo, db)


def gather_evidence(symbol: str, db_path: str) -> dict:
    """Real recorded evidence for one symbol from the shared database.

    Returns a dict of sections (bars, regime, position), each present only when
    the database actually holds it. Read-only, never raises.
    """
    out: dict = {}
    try:
        conn = sqlite3.connect(f"file:{_resolve_db(db_path)}?mode=ro", uri=True)
    except Exception:
        return out
    try:
        out.update(_bar_evidence(conn, symbol))
        out.update(_regime_evidence(conn, symbol))
        out.update(_position_evidence(conn, symbol))
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def _bar_evidence(conn: sqlite3.Connection, symbol: str) -> dict:
    """Closes and returns from real-provenance 5-minute bars, rendered oldest
    first. Volume only when every window bar is backfill provenance, because
    live bars aggregate fabricated tick volume. The provenance query lives in
    market_data.tradeable (real_bar_rows), the invariant's one home."""
    rows = real_bar_rows(conn, symbol, timeframe="5min", limit=_BARS_24H)
    if not rows:
        return {}
    closes = [r[1] for r in rows]  # newest first
    out: dict = {
        "closes_5min": [round(float(c), 6) for c in reversed(closes[:_CLOSES_SHOWN])],
        "closes_5min_last_ts": str(rows[0][0]),
    }
    now_close = float(closes[0])
    for label, n in (("return_1h_pct", _BARS_1H), ("return_4h_pct", _BARS_4H),
                     ("return_24h_pct", _BARS_24H)):
        if len(closes) >= n:
            then = float(closes[n - 1])
            if then > 0:
                out[label] = round((now_close / then - 1.0) * 100.0, 4)
    if all(r[3] == "backfill" for r in rows):
        out["volume_24h_base"] = round(sum(float(r[2] or 0.0) for r in rows), 4)
    return out


def _regime_evidence(conn: sqlite3.Connection, symbol: str) -> dict:
    """The engine's own persisted regime read: label, ADX, realized vol,
    active strategy factor, and when it was written."""
    try:
        row = conn.execute(
            "SELECT regime, adx, rvol, active_factor, updated_ts "
            "FROM regime_state WHERE symbol=?", (symbol,)).fetchone()
    except sqlite3.OperationalError:
        return {}
    if not row:
        return {}
    return {"regime": {
        "label": str(row[0]), "adx": round(float(row[1] or 0.0), 2),
        "realized_vol": round(float(row[2] or 0.0), 6),
        "active_factor": str(row[3] or ""), "as_of": str(row[4] or ""),
    }}


def _position_evidence(conn: sqlite3.Connection, symbol: str) -> dict:
    """Open position for this exact symbol, or the true statement that none
    exists. Both are real measurements of the positions table."""
    try:
        row = conn.execute(
            "SELECT side, qty, avg_price, opened_ts, unrealized_pnl "
            "FROM positions WHERE symbol=? AND ABS(qty) > 1e-12 "
            "ORDER BY opened_ts DESC LIMIT 1", (symbol,)).fetchone()
    except sqlite3.OperationalError:
        return {}
    if not row:
        return {"position": None}
    return {"position": {
        "side": str(row[0]), "qty": float(row[1]),
        "avg_price": float(row[2]), "opened_ts": str(row[3]),
        "unrealized_pnl": float(row[4] or 0.0),
    }}


def _quote_lines(state: dict) -> list[str]:
    lines: list[str] = []
    for key, (label, units) in ALLOWED_FIELDS.items():
        if key not in state or state.get(key) is None:
            continue
        val = state[key]
        if key == "price":
            try:
                if float(val) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            lines.append(f"- {label}: {_num(val, 6)} ({units})")
        elif key == "daily_return_pct":
            lines.append(f"- {label}: {_pct(val)} ({units})")
        elif key == "intraday_range_pct":
            hi, lo = state.get("day_high"), state.get("day_low")
            span = (f", day low {_num(lo, 6)} to day high {_num(hi, 6)}"
                    if hi is not None and lo is not None else "")
            lines.append(f"- {label}: {_num(val, 2)} ({units}{span})")
        else:
            lines.append(f"- {label}: {_num(val, 4)} ({units})")
    return lines


def _bar_lines(ev: dict) -> list[str]:
    lines: list[str] = []
    closes = ev.get("closes_5min")
    if closes:
        lines.append(
            f"- closes_5min: {json.dumps(closes)} (USD, last "
            f"{len(closes)} five-minute closes, oldest first, real venue "
            f"bars, newest at {ev.get('closes_5min_last_ts', '?')})")
    for key, desc in (("return_1h_pct", "percent over the last 12 five-minute bars"),
                      ("return_4h_pct", "percent over the last 48 five-minute bars"),
                      ("return_24h_pct", "percent over the last 288 five-minute bars")):
        if key in ev:
            lines.append(f"- {key.replace('_pct', '')}: {_pct(ev[key])} ({desc})")
    if "volume_24h_base" in ev:
        lines.append(f"- volume_24h: {_num(ev['volume_24h_base'], 2)} "
                     "(base units summed over 24h of venue-reported bars)")
    return lines


def _engine_lines(ev: dict) -> list[str]:
    lines: list[str] = []
    reg = ev.get("regime")
    if reg:
        lines.append(
            f"- regime: {reg['label']} (engine regime detector, ADX "
            f"{reg['adx']} trend-strength index, realized_vol "
            f"{reg['realized_vol']} stddev of 5-minute returns, active "
            f"strategy factor {reg['active_factor'] or 'unset'}, as of "
            f"{reg['as_of']})")
    if "position" in ev:
        pos = ev["position"]
        if pos is None:
            lines.append("- open_position: none (no open position in this "
                         "system for this symbol)")
        else:
            lines.append(
                f"- open_position: {pos['side']} qty {_num(pos['qty'], 8)} at "
                f"avg {_num(pos['avg_price'], 6)} USD since {pos['opened_ts']}, "
                f"unrealized_pnl {_num(pos['unrealized_pnl'], 2)} USD")
    return lines


def _fundamental_lines(state: dict) -> list[str]:
    """Long-term evidence: quality, fundamentals, and the live catalyst, only
    the components that were actually reported."""
    lines: list[str] = []
    fin = state.get("fundamentals")
    if isinstance(fin, dict) and fin:
        parts = []
        for key, desc in (("quality", "[0,1] composite quality score"),
                          ("roe_ttm", "percent return on equity, trailing 12m"),
                          ("net_margin_ttm", "percent net margin, trailing 12m"),
                          ("revenue_growth_yoy", "percent revenue growth, year over year"),
                          ("pe_ttm", "price to earnings, trailing 12m"),
                          ("week52_high", "USD 52-week high"),
                          ("week52_low", "USD 52-week low")):
            if fin.get(key) is not None:
                parts.append(f"{key} {_num(fin[key], 4)} ({desc})")
        if parts:
            lines.append("- fundamentals: " + ", ".join(parts))
    cat = state.get("catalyst_detail")
    if cat:
        lines.append(f"- catalyst: {cat}")
    return lines


def render_user_prompt(state: dict) -> str:
    """Render the evidence block a provider receives. Allowlist only.

    A key absent from the allowlist and the evidence sections never renders,
    whatever the state carries. Absent fields are omitted, never zeroed.
    """
    from .prompts import prompt_mode
    sym = str(state.get("symbol", "?"))
    cat = str(state.get("category", "") or "")
    venue = str(state.get("venue", "") or "")
    header = f"Instrument: {sym}"
    if cat:
        header += f" ({cat})"
    if venue:
        header += f" on venue {venue}"
    question = ("multi-week holding thesis"
                if prompt_mode(state) == "long_term"
                else "immediate setup, the next few hours on 5-minute bars")

    ev = state.get("_evidence") or {}
    lines = _quote_lines(state) + _bar_lines(ev) + _engine_lines(ev)
    if prompt_mode(state) == "long_term":
        lines += _fundamental_lines(state)
    if not lines:
        lines = ["- (no measured fields are available for this instrument)"]

    return (f"{header}\n"
            f"Question: {question}\n\n"
            "Evidence (absent fields were not measured):\n"
            + "\n".join(lines) + "\n"
            "Answer as instructed with the required JSON object.")

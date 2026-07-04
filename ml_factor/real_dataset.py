"""Real-data supervised dataset for the DNN advisory factor (Task 5).

Reads persisted **bars** (and, for provenance, closed **trades**) from the shared
SQLite DB and builds a chronologically-ordered supervised dataset:

    features per closed bar  ->  forward return label (horizon bars ahead)

Feature set (fixed order, REAL_FEATURE_NAMES): recent returns (1- and 5-bar),
ATR(14) normalised by price, RSI(14) in [0,1], 20-bar volume z-score, and a
regime scalar (trend strength). These are computed with pure-stdlib math so the
dataset half runs with **no numpy dependency** — the numpy trainer
(`ml_factor/train_real.py`) consumes what this produces.

Advisory only: a model trained on this is a *challenger*; promotion to the served
champion stays gated (see registry). True RL is deferred until we have >= 500
real closed fills; this supervised forward-return target is the honest Stage-B.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

REAL_FEATURE_NAMES = [
    "ret_1",        # 1-bar close-to-close return
    "ret_5",        # 5-bar return
    "atr_norm",     # ATR(14) / close  (volatility, price-relative)
    "rsi",          # RSI(14) in [0,1]
    "vol_z",        # 20-bar volume z-score (clipped)
    "regime",       # trend-strength scalar in [-1,1] (sign = direction)
]
N_REAL_FEATURES = len(REAL_FEATURE_NAMES)

# Minimum warmup so every indicator is well-defined before the first sample.
_WARMUP = 20
_ATR_PERIOD = 14
_RSI_PERIOD = 14
_VOL_LOOKBACK = 20


@dataclass(frozen=True)
class RealDataset:
    X: list[list[float]]          # feature rows, chronological
    y: list[float]                # forward returns (same order)
    timestamps: list[str]         # bar open ts per row (for walk-forward split)
    symbols: list[str]            # symbol per row
    n_closed_trades: int          # provenance: real closed paper trades in DB
    horizon: int                  # forward-return horizon in bars

    @property
    def n_samples(self) -> int:
        return len(self.X)


# --- pure-stdlib indicators ------------------------------------------------- #

def _rsi(closes: list[float], period: int = _RSI_PERIOD) -> float:
    """Wilder RSI over the last `period` deltas, scaled to [0,1]."""
    if len(closes) <= period:
        return 0.5
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - period, len(closes)):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0.0:
        return 1.0 if gains > 0 else 0.5
    rs = (gains / period) / (losses / period)
    return (100.0 - 100.0 / (1.0 + rs)) / 100.0


def _atr(highs: list[float], lows: list[float], closes: list[float],
         period: int = _ATR_PERIOD) -> float:
    """Average true range over the last `period` bars (simple mean of TR)."""
    n = len(closes)
    if n <= period:
        return 0.0
    trs = []
    for i in range(n - period, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs) / len(trs)


def _vol_zscore(volumes: list[float], lookback: int = _VOL_LOOKBACK) -> float:
    """Latest volume as a z-score over the prior `lookback` bars, clipped."""
    if len(volumes) <= lookback:
        return 0.0
    window = volumes[-lookback - 1:-1]
    mean = sum(window) / len(window)
    var = sum((v - mean) ** 2 for v in window) / len(window)
    sd = math.sqrt(var)
    if sd == 0.0:
        return 0.0
    z = (volumes[-1] - mean) / sd
    return max(-4.0, min(4.0, z))


def _regime_scalar(closes: list[float], lookback: int = _VOL_LOOKBACK) -> float:
    """Trend-strength scalar in [-1,1]: normalised slope of recent closes."""
    if len(closes) <= lookback:
        return 0.0
    window = closes[-lookback:]
    first, last = window[0], window[-1]
    if first == 0.0:
        return 0.0
    change = (last - first) / first
    return max(-1.0, min(1.0, change * 10.0))  # scale so a 10% move saturates


# --- DB access -------------------------------------------------------------- #

def load_bars(conn: sqlite3.Connection, symbol: str,
              timeframe: str) -> list[dict]:
    """Return bars for (symbol, timeframe) ordered oldest-first."""
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume FROM bars"
        " WHERE symbol=? AND timeframe=? ORDER BY timestamp ASC",
        (symbol, timeframe),
    ).fetchall()
    return [
        {"ts": r[0], "open": r[1], "high": r[2], "low": r[3],
         "close": r[4], "volume": r[5]}
        for r in rows
    ]


def count_closed_trades(conn: sqlite3.Connection) -> int:
    """Closed paper/live trades with a realized outcome (provenance signal)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE outcome IN ('win','loss','flat')"
        " AND pnl IS NOT NULL"
    ).fetchone()
    return int(row[0]) if row else 0


# --- dataset assembly ------------------------------------------------------- #

def _features_at(bars: list[dict], i: int) -> list[float]:
    """Feature vector using bars[:i+1] (no lookahead)."""
    closes = [b["close"] for b in bars[: i + 1]]
    highs = [b["high"] for b in bars[: i + 1]]
    lows = [b["low"] for b in bars[: i + 1]]
    vols = [b["volume"] for b in bars[: i + 1]]
    close = closes[-1] or 1.0
    ret_1 = (closes[-1] / closes[-2] - 1.0) if len(closes) >= 2 and closes[-2] else 0.0
    ret_5 = (closes[-1] / closes[-6] - 1.0) if len(closes) >= 6 and closes[-6] else 0.0
    atr_norm = _atr(highs, lows, closes) / close
    rsi = _rsi(closes)
    vol_z = _vol_zscore(vols)
    regime = _regime_scalar(closes)
    return [ret_1, ret_5, atr_norm, rsi, vol_z, regime]


def build_real_dataset(db_path: str, symbols: list[str],
                       timeframe: str = "5min",
                       horizon: int = 5) -> RealDataset:
    """Build a walk-forward-ready dataset from persisted bars.

    Label is the forward return `close[i+horizon]/close[i] - 1` (no lookahead in
    features). Rows are concatenated per symbol but each row keeps its timestamp
    so the trainer can split chronologically across the whole set.
    """
    conn = sqlite3.connect(db_path)
    try:
        X: list[list[float]] = []
        y: list[float] = []
        ts: list[str] = []
        syms: list[str] = []
        for symbol in symbols:
            bars = load_bars(conn, symbol, timeframe)
            if len(bars) < _WARMUP + horizon + 1:
                continue
            for i in range(_WARMUP, len(bars) - horizon):
                c_now = bars[i]["close"]
                c_fwd = bars[i + horizon]["close"]
                if not c_now:
                    continue
                X.append(_features_at(bars, i))
                y.append(c_fwd / c_now - 1.0)
                ts.append(bars[i]["ts"])
                syms.append(symbol)
        n_trades = count_closed_trades(conn)
    finally:
        conn.close()

    # Keep global chronological order for an honest walk-forward split.
    order = sorted(range(len(X)), key=lambda k: ts[k])
    X = [X[k] for k in order]
    y = [y[k] for k in order]
    ts = [ts[k] for k in order]
    syms = [syms[k] for k in order]
    return RealDataset(X=X, y=y, timestamps=ts, symbols=syms,
                       n_closed_trades=n_trades, horizon=horizon)


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Inspect the real-data DNN dataset.")
    ap.add_argument("--db", default="market_ai_lab.db")
    ap.add_argument("--symbols", default="BTC/USD,ETH/USD,SPY,QQQ")
    ap.add_argument("--timeframe", default="5min")
    ap.add_argument("--horizon", type=int, default=5)
    args = ap.parse_args()
    ds = build_real_dataset(args.db, [s.strip() for s in args.symbols.split(",")],
                            args.timeframe, args.horizon)
    print(json.dumps({
        "n_samples": ds.n_samples,
        "n_closed_trades": ds.n_closed_trades,
        "feature_names": REAL_FEATURE_NAMES,
        "horizon": ds.horizon,
        "first_row": ds.X[0] if ds.X else None,
    }, indent=2))

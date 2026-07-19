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

# THE canonical feature set (2026-07-18). One definition, defined here, used by
# training AND serving through the same builder (_features_at). Version bumps
# when the set changes, and the serving path refuses an artifact whose recorded
# signature does not match (ml_factor/factor.py).
#
# Every feature computes from real bars. Nothing is a constant default:
#   * vol_z was REMOVED from the set: the engine's tick path synthesizes bar
#     volume even on the live feed, so a volume feature would train on real
#     backfill volumes and serve on invented ones, the exact train/serve
#     mismatch this set exists to prevent. _vol_zscore stays exported below
#     for rl_advisory, which builds its own dataset.
#   * time_of_day is COMPUTED from the bar timestamp, replacing the old
#     serving-path constant 0.5.
#   * recent_winrate, streak, drawdown, imbalance, spread_rel from the old
#     serving builder are GONE: none was computable from real data at serve
#     time, and the constant recent_winrate=0.5 alone moved the synthetic
#     champion's read from +0.03 to -0.33.
FEATURE_SET_VERSION = "bars-v2"
REAL_FEATURE_NAMES = [
    "ret_1",        # 1-bar close-to-close return
    "ret_5",        # 5-bar return
    "atr_norm",     # ATR(14) / close  (volatility, price-relative)
    "rsi",          # RSI(14) in [0,1]
    "regime",       # trend-strength scalar in [-1,1] (sign = direction)
    "time_of_day",  # bar UTC time as a fraction of the day [0,1)
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
    """Return bars for (symbol, timeframe) ordered oldest-first.

    Proven-synthetic bars are EXCLUDED: training or serving on walk prices is
    the contamination the provenance column exists to prevent. `unknown` still
    loads (historical rows predate the column and were real). A pre-migration
    DB without the column falls back to the unfiltered read.
    """
    try:
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM bars"
            " WHERE symbol=? AND timeframe=?"
            " AND COALESCE(source,'unknown') <> 'synthetic'"
            " ORDER BY timestamp ASC",
            (symbol, timeframe),
        ).fetchall()
    except sqlite3.OperationalError:
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


def _has_origin_column(conn: sqlite3.Connection) -> bool:
    """Whether this DB records trade provenance.

    A DB written by an engine older than the `origin` migration has no column to
    filter on. Falling back to the unfiltered count there is the honest option:
    the information to tell a strategy fill from a rebalance trim was never
    recorded, so it cannot be recovered retroactively.
    """
    try:
        cols = conn.execute("PRAGMA table_info(trades)").fetchall()
    except sqlite3.Error:
        return False
    return any(c[1] == "origin" for c in cols)


def _has_bar_source_column(conn: sqlite3.Connection) -> bool:
    """Whether this DB records the provenance of the bar each trade executed
    against. Absent on a DB older than the 2026-07-18 migration: those fills
    count unfiltered, the honest fallback, because the information was never
    recorded."""
    try:
        cols = conn.execute("PRAGMA table_info(trades)").fetchall()
    except sqlite3.Error:
        return False
    return any(c[1] == "bar_source" for c in cols)


def count_closed_trades(conn: sqlite3.Connection) -> int:
    """Closed STRATEGY fills with a realized outcome. The real-fill gate.

    This is a GATE, not a dataset: both build_real_dataset and the RL trainer
    build their features from `bars`, and read this only to decide whether enough
    real trading has happened to train on. So the question it has to answer is
    "has the POLICY been exercised enough", not "have any fills occurred".

    Which is why it counts `origin = 'strategy'` only. An adaptive defensive exit
    (a live news event trimmed a position) and a sleeve rebalance trim (drift
    mechanics closed one) are both real fills that moved real money, but neither
    is a decision the policy made, so neither is evidence about the policy. Left
    unfiltered they inflate two gates that exist precisely to withhold training
    until the evidence is real: the DNN real-data trainer, and the RL
    `rl_min_real_fills` activation (500 fills, a CLAUDE.md hard rule).

    Filtering makes both gates STRICTER, never looser: they open later, on fewer
    but more meaningful fills. That is the safe direction for a gate whose whole
    job is to say "not yet".
    """
    if not _has_origin_column(conn):
        return _count_all_closed(conn)
    # A fill against a proven-synthetic bar exercised nothing: the prices were
    # the walk generator, not a market (2026-07-17: BTC bought at 74,335 against
    # a real 63,000). Excluding it is the same direction as the origin filter,
    # STRICTER only. 'unknown' still counts: historical fills predate the
    # provenance column and were real, so excluding them would rewrite history.
    extra = (" AND COALESCE(bar_source, 'unknown') <> 'synthetic'"
             if _has_bar_source_column(conn) else "")
    row = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE outcome IN ('win','loss','flat')"
        " AND pnl IS NOT NULL AND COALESCE(origin, 'strategy') = 'strategy'"
        + extra
    ).fetchone()
    return int(row[0]) if row else 0


def _count_all_closed(conn: sqlite3.Connection) -> int:
    """Every closed fill regardless of what decided it. The pre-`origin`
    behavior, kept for DBs that predate the column."""
    row = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE outcome IN ('win','loss','flat')"
        " AND pnl IS NOT NULL"
    ).fetchone()
    return int(row[0]) if row else 0


# --- dataset assembly ------------------------------------------------------- #

def _time_of_day(ts: str | None) -> float:
    """Bar UTC time as a fraction of the day [0,1). COMPUTED from the bar
    timestamp, never a constant: the old serving default of 0.5 was one of the
    invented inputs that made every inference an out-of-distribution point."""
    s = str(ts or "")
    try:
        hh, mm = int(s[11:13]), int(s[14:16])
        if 0 <= hh < 24 and 0 <= mm < 60:
            return (hh * 60 + mm) / 1440.0
    except (ValueError, IndexError):
        pass
    return 0.0


def _features_at(bars: list[dict], i: int) -> list[float]:
    """THE canonical feature builder (REAL_FEATURE_NAMES order), using
    bars[:i+1] with no lookahead. Training builds every row through this
    function and serving scores the newest window through this function, so
    the features a model trains on are exactly the features it is served."""
    closes = [b["close"] for b in bars[: i + 1]]
    highs = [b["high"] for b in bars[: i + 1]]
    lows = [b["low"] for b in bars[: i + 1]]
    close = closes[-1] or 1.0
    ret_1 = (closes[-1] / closes[-2] - 1.0) if len(closes) >= 2 and closes[-2] else 0.0
    ret_5 = (closes[-1] / closes[-6] - 1.0) if len(closes) >= 6 and closes[-6] else 0.0
    atr_norm = _atr(highs, lows, closes) / close
    rsi = _rsi(closes)
    regime = _regime_scalar(closes)
    tod = _time_of_day(bars[i].get("ts"))
    return [ret_1, ret_5, atr_norm, rsi, regime, tod]


def serve_window(db_path: str, symbol: str, timeframe: str = "5min",
                 lookback: int = 64) -> tuple[list[dict] | None, str]:
    """The newest real-bar window for serve-time feature building.

    Returns (bars, "ok") or (None, reason). Refuses a window shorter than the
    warm-up so every indicator in the canonical set computes from data rather
    than emitting its cold value. A symbol with no real bars is UNAVAILABLE,
    never scored on invented inputs.
    """
    n = max(int(lookback), _WARMUP + 1)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                               timeout=2.0)
        try:
            # Newest-first LIMIT, then reverse: a serve call needs the last
            # `lookback` bars, not the symbol's whole history (BTC/USD holds
            # ~10k rows, and this runs per score call). Same synthetic
            # exclusion and tolerant fallback as load_bars.
            try:
                rows = conn.execute(
                    "SELECT timestamp, open, high, low, close, volume FROM"
                    " bars WHERE symbol=? AND timeframe=?"
                    " AND COALESCE(source,'unknown') <> 'synthetic'"
                    " ORDER BY timestamp DESC LIMIT ?",
                    (symbol, timeframe, n)).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT timestamp, open, high, low, close, volume FROM"
                    " bars WHERE symbol=? AND timeframe=?"
                    " ORDER BY timestamp DESC LIMIT ?",
                    (symbol, timeframe, n)).fetchall()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 — an unreadable DB is unavailable
        return None, f"bars unavailable ({type(e).__name__})"
    bars = [{"ts": r[0], "open": r[1], "high": r[2], "low": r[3],
             "close": r[4], "volume": r[5]} for r in reversed(rows)]
    if len(bars) < _WARMUP + 1:
        return None, (f"insufficient real bars for {symbol}: "
                      f"{len(bars)} < {_WARMUP + 1}")
    return bars, "ok"


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

"""Real-data feature builder for the RL advisory env (Task 4).

Reads persisted **bars** from the shared SQLite DB and builds a chronological
per-bar feature series the RL env consumes as a rolling observation window. The
pure indicator math is reused from ``ml_factor.real_dataset`` (DRY) so the RL and
supervised advisory factors see consistent features.

Per-bar feature vector (fixed order, PER_BAR_FEATURES):
    ret_1, atr_norm, rsi, vol_z, regime_trend, regime_range, regime_neutral
The env appends a 3-way position one-hot (flat/long/short) to the flattened
window to form the full observation.

RL trains on REAL data only. ``count_real_fills`` exposes the closed-fill count
the trainer's gate reads; there is NO synthetic feature path here.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

# Reuse the exact stdlib indicators the supervised real dataset uses.
from ml_factor.real_dataset import (_atr, _regime_scalar, _rsi, _vol_zscore,
                                     count_closed_trades, load_bars)

PER_BAR_FEATURES = [
    "ret_1",           # 1-bar close-to-close return
    "atr_norm",        # ATR(14) / close
    "rsi",             # RSI(14) in [0,1]
    "vol_z",           # 20-bar volume z-score (clipped)
    "regime_trend",    # regime one-hot
    "regime_range",
    "regime_neutral",
]
N_PER_BAR_FEATURES = len(PER_BAR_FEATURES)

_WARMUP = 20
# Regime one-hot thresholds on the trend-strength scalar (|s| in [0,1]).
_TREND_MIN = 0.2
_NEUTRAL_MAX = 0.05


@dataclass(frozen=True)
class RlDataset:
    features: list[list[float]]           # per-bar feature rows, chronological
    prices: list[float]                    # close per row (env PnL uses these)
    episode_boundaries: list[int] = field(default_factory=list)  # symbol-switch idx
    n_real_fills: int = 0                  # closed real fills (trainer gate reads)
    symbols: list[str] = field(default_factory=list)

    @property
    def n_steps(self) -> int:
        return len(self.features)


def _regime_one_hot(closes: list[float]) -> tuple[float, float, float]:
    s = abs(_regime_scalar(closes))
    if s >= _TREND_MIN:
        return (1.0, 0.0, 0.0)   # trending
    if s < _NEUTRAL_MAX:
        return (0.0, 0.0, 1.0)   # neutral
    return (0.0, 1.0, 0.0)       # range-bound


def _features_at(bars: list[dict], i: int) -> list[float]:
    """Feature vector using bars[:i+1] (no lookahead)."""
    closes = [b["close"] for b in bars[: i + 1]]
    highs = [b["high"] for b in bars[: i + 1]]
    lows = [b["low"] for b in bars[: i + 1]]
    vols = [b["volume"] for b in bars[: i + 1]]
    close = closes[-1] or 1.0
    ret_1 = (closes[-1] / closes[-2] - 1.0) if len(closes) >= 2 and closes[-2] else 0.0
    atr_norm = _atr(highs, lows, closes) / close
    trend, rng, neutral = _regime_one_hot(closes)
    return [ret_1, atr_norm, _rsi(closes), _vol_zscore(vols), trend, rng, neutral]


def build_bar_features(bars: list[dict]) -> tuple[list[list[float]], list[float]]:
    """Per-bar feature rows + aligned close prices for a single symbol series."""
    feats: list[list[float]] = []
    prices: list[float] = []
    for i in range(_WARMUP, len(bars)):
        feats.append(_features_at(bars, i))
        prices.append(bars[i]["close"])
    return feats, prices


def count_real_fills(db_path: str) -> int:
    """Closed real fills in the DB (the RL trainer's training gate reads this)."""
    conn = sqlite3.connect(db_path)
    try:
        return count_closed_trades(conn)
    finally:
        conn.close()


def build_rl_dataset(db_path: str, symbols: list[str],
                     timeframe: str = "5min") -> RlDataset:
    """Assemble a chronological RL feature series across symbols from real bars.

    Each symbol contributes a contiguous block; boundary indices are recorded so
    the env can zero the cross-symbol return (no spurious jump between symbols).
    """
    conn = sqlite3.connect(db_path)
    try:
        feats: list[list[float]] = []
        prices: list[float] = []
        boundaries: list[int] = []
        used: list[str] = []
        for symbol in symbols:
            bars = load_bars(conn, symbol, timeframe)
            if len(bars) <= _WARMUP + 1:
                continue
            f, p = build_bar_features(bars)
            if not f:
                continue
            boundaries.append(len(feats))   # first index of this symbol's block
            feats.extend(f)
            prices.extend(p)
            used.append(symbol)
        n_fills = count_closed_trades(conn)
    finally:
        conn.close()
    return RlDataset(features=feats, prices=prices, episode_boundaries=boundaries,
                     n_real_fills=n_fills, symbols=used)

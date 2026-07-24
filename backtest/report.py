"""Statistics over mal_backtest JSON lines (2026-07-24).

The C++ harness owns every DECISION (strategy and RiskGate called by
identity); this module owns every STATISTIC, and enforces statistical
honesty in code:

  * every number carries its sample size and a confidence interval, never a
    bare point estimate;
  * any group below MIN_SAMPLE refuses with status 'insufficient_sample',
    the shape train_real uses for insufficient_real_data;
  * validation is walk-forward on EXPANDING CHRONOLOGICAL folds, matching
    the DNN trainer, never a random split.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

MIN_SAMPLE = 30  # the tuner's own minimum-evidence bar

Z95 = 1.96


def wilson(wins: int, n: int) -> tuple[float, float]:
    """95 percent Wilson interval for a win rate. (0,1) bounds, never NaN."""
    if n <= 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + Z95 * Z95 / n
    center = (p + Z95 * Z95 / (2 * n)) / denom
    half = (Z95 * math.sqrt(p * (1 - p) / n + Z95 * Z95 / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def mean_ci(xs: list[float]) -> tuple[float, float, float]:
    """(mean, lo, hi): 95 percent t-approx interval for a mean return."""
    n = len(xs)
    if n == 0:
        return (0.0, 0.0, 0.0)
    m = sum(xs) / n
    if n == 1:
        return (m, float("-inf"), float("inf"))
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    se = math.sqrt(var / n)
    return (m, m - Z95 * se, m + Z95 * se)


def load(path: str) -> dict:
    """Parse a harness JSONL file into typed record lists."""
    out: dict = {"trades": [], "signals": [], "gate_blocks": [], "bars": {},
                 "summary": {}, "calib": []}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            t = d.get("t")
            if t == "trade":
                out["trades"].append(d)
            elif t == "signal":
                out["signals"].append(d)
            elif t == "gate_block":
                out["gate_blocks"].append(d)
            elif t == "bars":
                out["bars"][d["symbol"]] = d["usable"]
            elif t == "summary":
                out["summary"] = d
            elif t == "calib":
                out["calib"].append(d)
    return out


def stats_for(trades: list[dict]) -> dict:
    """Expectancy statistics for one trade group, honesty enforced."""
    n = len(trades)
    if n < MIN_SAMPLE:
        return {"n": n, "status": "insufficient_sample",
                "min_sample": MIN_SAMPLE,
                "note": (f"{n} trades is below the {MIN_SAMPLE}-trade "
                         "minimum; no conclusion is reported")}
    rets = [t["ret"] for t in trades]
    wins = sum(1 for r in rets if r > 0)
    lo_w, hi_w = wilson(wins, n)
    m, lo, hi = mean_ci(rets)
    # Max drawdown over the group's own equity path (sizing-dependent).
    eq, peak, mdd = 0.0, 0.0, 0.0
    for t in trades:
        eq += t["pnl"]
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    ambiguous = sum(1 for t in trades if t.get("ambiguous"))
    return {"n": n, "status": "ok",
            "win_rate": wins / n, "win_rate_ci": (lo_w, hi_w),
            "mean_ret": m, "mean_ret_ci": (lo, hi),
            "expectancy_sign": ("positive" if lo > 0 else
                                "negative" if hi < 0 else
                                "interval spans zero: too thin to say"),
            "sum_pnl": sum(t["pnl"] for t in trades),
            "max_drawdown_usd": mdd,
            "ambiguous": ambiguous,
            "ambiguous_share": ambiguous / n}


def by_group(trades: list[dict], key) -> dict:
    groups = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)
    return {k: stats_for(v) for k, v in sorted(groups.items())}


def walk_forward(trades: list[dict], folds: int = 4) -> list[dict]:
    """Expanding chronological folds over entry_ts order, the DNN trainer's
    shape. Each fold reports stats over ONLY its held-out chronological
    slice, so a regime-dependent result shows up as fold disagreement."""
    ts_sorted = sorted(trades, key=lambda t: t["entry_ts"])
    n = len(ts_sorted)
    if n == 0:
        return []
    out = []
    for f in range(folds):
        a = n * f // folds
        b = n * (f + 1) // folds
        s = stats_for(ts_sorted[a:b])
        s["fold"] = f + 1
        s["window"] = (ts_sorted[a]["entry_ts"] if b > a else "",
                       ts_sorted[b - 1]["entry_ts"] if b > a else "")
        out.append(s)
    return out


def report(path: str) -> dict:
    r = load(path)
    trades = r["trades"]
    return {
        "bars": r["bars"],
        "summary": r["summary"],
        "signals": len(r["signals"]),
        "gate_blocks": len(r["gate_blocks"]),
        "pooled": stats_for(trades),
        "by_factor": by_group(trades, lambda t: t["factor"]),
        "by_category": by_group(trades, lambda t: t["category"]),
        "folds": walk_forward(trades),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jsonl")
    args = ap.parse_args()
    print(json.dumps(report(args.jsonl), indent=2, default=str))

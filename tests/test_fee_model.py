"""The fee model (2026-07-26): published live schedules, never paper fills.

Pins: per-class per-order-type rates, the tier table and its threshold, the
harness consulting the model per asset class, the engine recording both the
model cost and the venue cost on every fill, and the hurdle appearing at
startup and in runstate. Mutating the crypto taker rate or the equity rates
back toward a flat 2 bp fails these tests.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess

import pytest

from backtest import fees

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(REPO, "build", "mal_engine")
BACKTEST = os.path.join(REPO, "build", "mal_backtest")


# ---- rates per venue, asset class, and order type ------------------------

def test_crypto_taker_round_trip_is_50bp() -> None:
    assert fees.per_side_bp("crypto", "taker") == 25.0
    assert fees.round_trip_bp("crypto", "taker") == 50.0


def test_crypto_maker_differs_from_taker() -> None:
    assert fees.per_side_bp("crypto", "maker") == 15.0
    assert fees.round_trip_bp("crypto", "maker") == 30.0
    assert fees.round_trip_bp("crypto", "maker") < fees.round_trip_bp(
        "crypto", "taker")


def test_equity_round_trip_is_1_3bp() -> None:
    assert fees.per_side_bp("equity", "taker") == pytest.approx(0.65)
    assert fees.round_trip_bp("equity", "taker") == pytest.approx(1.3)


def test_costs_inverted_by_asset_class() -> None:
    # The defect this model fixes: crypto costs MORE than equity live,
    # roughly 38x, where the old flat 2 bp treated them as identical.
    assert fees.round_trip_bp("crypto") > 20 * fees.round_trip_bp("equity")


# ---- the tier boundary is respected and a change is visible --------------

def test_base_tier_applies_under_threshold() -> None:
    f = fees.load()
    assert f["alpaca_crypto_tier_volume_threshold_usd"] == 100_000
    assert fees.crypto_tier(50_000) == (0, 0.15, 0.25)
    assert fees.crypto_tier(99_999) == (0, 0.15, 0.25)


def test_tier_change_is_visible_not_silent() -> None:
    assert fees.crypto_tier(200_000) == (100_000, 0.12, 0.22)
    assert fees.crypto_tier(2_000_000) == (1_000_000, 0.08, 0.18)
    # This account's sizing keeps 30-day volume far under the threshold.
    assert fees.crypto_tier(0)[2] == fees.load()["alpaca_crypto_taker_pct"]


# ---- the hurdle appears where decisions are made -------------------------

def test_summary_carries_hurdle_and_source() -> None:
    s = fees.summary()
    assert s["crypto_round_trip_bp"] == 50.0
    assert s["equity_round_trip_bp"] == pytest.approx(1.3)
    assert s["order_type_assumed"] == "market_taker"
    assert "published live schedules" in s["source"]


@pytest.mark.skipif(not os.path.exists(ENGINE), reason="mal_engine not built")
def test_engine_startup_prints_hurdle(tmp_path) -> None:
    out = subprocess.run(
        [ENGINE, "--db", str(tmp_path / "t.db"), "--iterations", "1"],
        capture_output=True, text=True, cwd=REPO, timeout=120).stdout
    assert "round trip crypto 50 bp / equity 1.3 bp" in out
    assert "taker" in out


# ---- the engine records BOTH figures on every fill -----------------------

@pytest.mark.skipif(not os.path.exists(ENGINE), reason="mal_engine not built")
def test_paper_fill_records_model_and_venue_cost(tmp_path) -> None:
    db = str(tmp_path / "fills.db")
    subprocess.run(
        [ENGINE, "--db", db, "--iterations", "3000",
         "--feed-mode", "synthetic_regimes", "--clock-mode", "simulated"],
        capture_output=True, text=True, cwd=REPO, timeout=300)
    rows = sqlite3.connect(db).execute(
        "SELECT category, notional, fee, fee_model_cost, fee_order_type "
        "FROM trades WHERE notional > 0").fetchall()
    assert rows, "synthetic run produced no fills"
    for cat, notional, venue_fee, model_cost, order_type in rows:
        assert order_type == "market_taker"
        if cat == "crypto":
            # Crypto is a published percentage with no liquidity axis, so the
            # equality still holds exactly.
            side_bp = fees.per_side_bp("crypto", "taker")
            assert model_cost == pytest.approx(notional * side_bp / 1e4,
                                               rel=1e-6)
            continue
        # EQUITY CHANGED 2026-07-27 and this assertion changed with it, stated
        # rather than quietly relaxed. It used to pin model_cost to the flat
        # 0.65 bp per side. That figure is no longer a constant: equity cost
        # now depends on the symbol's own price and median dollar volume, and
        # this test cannot know the ADV the engine measured from its own bar
        # history. What the original assertion existed to prove, that the
        # engine records the MODEL cost and not the venue cost, is kept: the
        # regulatory component is unconditional, so every equity fill must
        # carry at least it, and no fill may be free. The exact arithmetic is
        # pinned on the pure function in tests/test_fee_liquidity.py.
        reg_bp = fees.load()["alpaca_equity_regulatory_bp_per_side"]
        assert model_cost >= notional * reg_bp / 1e4 * 0.999
        assert model_cost > 0.0
    crypto = [r for r in rows if r[0] == "crypto"]
    if crypto:
        # The divergence is the point: paper reports ~1 bp, live pays 25.
        cat, notional, venue_fee, model_cost, _ = crypto[0]
        assert model_cost > 10 * venue_fee


# ---- the harness consults the model per asset class ----------------------

@pytest.mark.skipif(not os.path.exists(BACKTEST),
                    reason="mal_backtest not built")
def test_harness_meta_and_trades_carry_class_fees(tmp_path) -> None:
    from tests.test_research_sweep import _mk_db, _seed
    import datetime
    db = str(tmp_path / "bars.db")
    conn = _mk_db(db)
    base = int(datetime.datetime(
        2026, 3, 2, tzinfo=datetime.timezone.utc).timestamp())
    _seed(conn, "BTC/USD", 400, base)
    _seed(conn, "SPY", 400, base)
    conn.commit()
    conn.close()
    out = subprocess.run(
        [BACKTEST, "--db", db, "--profile", "swing",
         "--symbols", "BTC/USD,SPY"],
        capture_output=True, text=True, check=True, cwd=REPO).stdout
    meta = json.loads(out.splitlines()[0])
    assert meta["fee_crypto_rt_bp"] == "50"
    assert meta["fee_equity_rt_bp"] == "1.3"
    assert meta["fee_order_type"] == "market_taker"
    for line in out.splitlines():
        if '"t":"trade"' not in line:
            continue
        d = json.loads(line)
        if d["category"] == "crypto":
            assert d["fee_rt_bp"] == pytest.approx(50.0)
            continue
        # EQUITY CHANGED 2026-07-27, stated rather than quietly relaxed. This
        # pinned every equity trade at exactly 1.3 bp, which is what the defect
        # WAS: one figure for a mega cap and a micro cap alike. The harness now
        # prices each symbol from its own fill price and median dollar volume,
        # so the per-trade figure is no longer a constant and pinning it to one
        # would re-assert the bug. The meta line above still carries 1.3 as the
        # reference flat figure, and the arithmetic is pinned exactly on the
        # pure function in tests/test_fee_liquidity.py.
        reg_rt = 2 * fees.load()["alpaca_equity_regulatory_bp_per_side"]
        assert reg_rt <= d["fee_rt_bp"] < 1000.0


# ---- runstate surfaces the hurdle ----------------------------------------

def test_runstate_carries_fees(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAL_DB_PATH", str(tmp_path / "rs.db"))
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path))
    from api_server import store
    rs = store.runstate()
    assert rs["fees"]["crypto_round_trip_bp"] == 50.0
    assert rs["fees"]["equity_round_trip_bp"] == pytest.approx(1.3)

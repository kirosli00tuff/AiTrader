"""Tests for the RL advisory module (Task 4/8).

No network, no torch/stable-baselines3 required: these exercise the gym env
(gymnasium only), the scoring service (pure Python), the real-fill training gate
(refuses BEFORE importing any backend), and the ensemble-participation contract.
"""
import sqlite3

import pytest

from rl_advisory import rl_ensemble_factor_names, score_rl
from rl_advisory.env import ACTION_FLAT, ACTION_LONG, ACTION_SHORT, TradingEnv
from rl_advisory.evaluate import (challenger_beats_champion, evaluate_policy,
                                  walk_forward_windows)
from rl_advisory.train import train_rl_challenger

_N_FEATS = 7  # PER_BAR_FEATURES width


def _flat_series(n: int, price: float = 100.0):
    """n bars of zero-feature rows at a CONSTANT price (zero market return)."""
    return [[0.0] * _N_FEATS for _ in range(n)], [price] * n


def _rising_series(n: int):
    return [[0.0] * _N_FEATS for _ in range(n)], [100.0 + i for i in range(n)]


def _cfg(tmp_path, rl_enabled: bool) -> str:
    # Distinct filename per toggle: the config loader lru_caches on the path, and
    # a real config path has stable content across a run, so two toggle states
    # must live at two paths (not one rewritten file) to be read independently.
    p = tmp_path / f"rl_{'on' if rl_enabled else 'off'}.yaml"
    p.write_text(f"rl:\n  rl_enabled: {'true' if rl_enabled else 'false'}\n"
                 f"  rl_min_real_fills: 500\n")
    return str(p)


# --- Env API contract ------------------------------------------------------- #

def test_env_reset_and_step_shapes():
    features, prices = _rising_series(40)
    env = TradingEnv(features, prices, window=8)
    obs, info = env.reset()
    assert obs.shape == env.observation_space.shape == (8 * _N_FEATS + 3,)
    assert isinstance(info, dict)
    obs2, reward, terminated, truncated, info2 = env.step(ACTION_LONG)
    assert obs2.shape == env.observation_space.shape
    assert isinstance(reward, float)
    assert isinstance(terminated, bool) and isinstance(truncated, bool)
    assert env.action_space.n == 3


def test_env_rejects_too_short_series():
    features, prices = _rising_series(4)
    with pytest.raises(ValueError):
        TradingEnv(features, prices, window=8)   # need >= window+1 steps


# --- Reward charges the (mandatory) transaction cost ------------------------ #

def test_env_reward_charges_transaction_cost():
    features, prices = _flat_series(20)      # constant price => zero PnL, zero DD
    env = TradingEnv(features, prices, window=4, txn_cost_rate=0.001,
                     drawdown_penalty=0.0)
    env.reset()
    _o, r_open, *_ = env.step(ACTION_LONG)   # flat -> long : |Δpos| = 1
    assert r_open == pytest.approx(-0.001)   # exactly the transaction cost
    _o, r_hold, *_ = env.step(ACTION_LONG)   # no position change, flat price
    assert r_hold == pytest.approx(0.0)      # no cost, no PnL
    _o, r_close, *_ = env.step(ACTION_FLAT)  # long -> flat : |Δpos| = 1
    assert r_close == pytest.approx(-0.001)  # charged again


def test_env_long_only_clamps_short_to_flat():
    features, prices = _rising_series(20)
    env = TradingEnv(features, prices, window=4, txn_cost_rate=0.0,
                     drawdown_penalty=0.0, long_only=True)
    env.reset()
    _o, _r, _t, _tr, info = env.step(ACTION_SHORT)
    assert info["position"] == 0             # short clamped to flat (equities)


# --- Training gate: refuses below the real-fill gate ------------------------ #

def _db_with_fills(tmp_path, n_fills: int) -> str:
    db = str(tmp_path / "fills.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE trades(outcome TEXT, pnl REAL)")
    conn.executemany("INSERT INTO trades(outcome, pnl) VALUES(?, ?)",
                     [("win", 1.0)] * n_fills)
    conn.commit()
    conn.close()
    return db


def test_trainer_refuses_below_fill_gate(tmp_path):
    db = _db_with_fills(tmp_path, 12)        # 12 << default gate 500
    res = train_rl_challenger(db, ["BTC/USD"])
    assert res["status"] == "insufficient_real_fills"
    assert res["n_real_fills"] == 12
    assert res["min_required"] == 500
    # No synthetic-data path exists; the message must say so.
    assert "No synthetic" in res["note"]


def test_trainer_refuses_below_configured_gate(tmp_path):
    db = _db_with_fills(tmp_path, 3)
    cfg = tmp_path / "g.yaml"
    cfg.write_text("rl:\n  rl_enabled: true\n  rl_min_real_fills: 50\n")
    res = train_rl_challenger(db, ["BTC/USD"], cfg_path=str(cfg))
    assert res["status"] == "insufficient_real_fills"
    assert res["min_required"] == 50


# --- /score/rl : disabled + labelled mock fallback -------------------------- #

def test_score_rl_disabled_is_neutral_and_out(tmp_path):
    cfg = _cfg(tmp_path, rl_enabled=False)
    v = score_rl({"symbol": "BTC-USD", "ret_5": 0.03}, cfg_path=cfg)
    assert v["source"] == "disabled"
    assert v["bias"] == 0.0 and v["confidence"] == 0.0 and v["edge"] == 0.0


def test_score_rl_mock_fallback_when_enabled_no_artifact(tmp_path):
    cfg = _cfg(tmp_path, rl_enabled=True)     # enabled, but no trained artifact
    v = score_rl({"symbol": "BTC-USD", "ret_5": 0.03}, cfg_path=cfg)
    assert v["source"] == "mock"
    assert "MOCK" in v["rationale"]
    # advisory sizing hint is hard-capped at 0.5
    assert 0.0 <= v["rl_position_scale_hint"] <= 0.5
    for k in ("bias", "confidence", "edge"):
        assert k in v


# --- rl_enabled false keeps the factor out of the ensemble ------------------ #

def test_rl_enabled_false_keeps_factor_out_of_ensemble(tmp_path):
    base = ["llm_primary", "rule_based", "dnn_advisory", "whale_signal"]
    off = rl_ensemble_factor_names(base, cfg_path=_cfg(tmp_path, rl_enabled=False))
    assert "rl_advisory" not in off
    assert off == base
    on = rl_ensemble_factor_names(base, cfg_path=_cfg(tmp_path, rl_enabled=True))
    assert "rl_advisory" in on


# --- Walk-forward eval + champion/challenger gate --------------------------- #

def test_walk_forward_windows_are_chronological_and_expanding():
    windows = walk_forward_windows(120, n_folds=5)
    assert windows, "expected non-empty fold list"
    for (tr, te) in windows:
        assert 0 < tr < te
    assert all(windows[i][0] <= windows[i + 1][0] for i in range(len(windows) - 1))


def test_evaluate_policy_averages_5_to_20_episodes():
    features, prices = _rising_series(60)
    env = TradingEnv(features, prices, window=4, txn_cost_rate=0.0,
                     drawdown_penalty=0.0)
    metrics = evaluate_policy(env, lambda obs: ACTION_LONG, n_episodes=1)
    assert 5 <= metrics["n_episodes"] <= 20    # clamped into the RL protocol range
    assert "validation_sharpe" in metrics and "max_drawdown" in metrics


def test_challenger_beats_champion_on_sharpe_and_no_worse_drawdown():
    champ = {"provenance": "real-data", "n_samples": 300,
             "validation_sharpe": 0.5, "max_drawdown": 0.10}
    better = {"provenance": "real-data", "n_samples": 300,
              "validation_sharpe": 0.8, "max_drawdown": 0.08}
    ok, reason = challenger_beats_champion(champ, better)
    assert ok is True                          # competes + wins; promotion still manual


def test_challenger_rejected_when_drawdown_worse():
    champ = {"provenance": "real-data", "n_samples": 300,
             "validation_sharpe": 0.5, "max_drawdown": 0.05}
    worse = {"provenance": "real-data", "n_samples": 300,
             "validation_sharpe": 0.9, "max_drawdown": 0.20}
    ok, reason = challenger_beats_champion(champ, worse)
    assert ok is False and "drawdown" in reason

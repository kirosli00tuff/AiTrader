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


def _cfg(tmp_path, rl_enabled: bool, min_fills: int = 500) -> str:
    # Distinct filename per toggle: the config loader lru_caches on the path, and
    # a real config path has stable content across a run, so two toggle states
    # must live at two paths (not one rewritten file) to be read independently.
    #
    # min_fills is explicit because the real-fill gate is now enforced at the
    # READ (rl_advisory.service.rl_gate_unmet), not only at the GUI write. A test
    # that wants to reach the scoring paths BEHIND the gate has to say so, by
    # setting the gate to 0. That is the point: the CLAUDE.md hard rule ("RL
    # activates only past the rl_min_real_fills gate") is no longer something a
    # caller can walk past by setting one flag.
    p = tmp_path / f"rl_{'on' if rl_enabled else 'off'}_{min_fills}.yaml"
    p.write_text(f"rl:\n  rl_enabled: {'true' if rl_enabled else 'false'}\n"
                 f"  rl_min_real_fills: {min_fills}\n")
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
    # Enabled, gate met (min_fills=0), but no trained artifact. The gate has to
    # be met explicitly: the mock path sits BEHIND the real-fill gate, and that
    # ordering is the hard rule.
    cfg = _cfg(tmp_path, rl_enabled=True, min_fills=0)
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
    # Enabled AND past the gate (min_fills=0) is what puts it in the ensemble.
    # The gate has to be stated: the factor list and score_rl must agree, and
    # neither joins the ensemble on the flag alone.
    on = rl_ensemble_factor_names(
        base, cfg_path=_cfg(tmp_path, rl_enabled=True, min_fills=0))
    assert "rl_advisory" in on


def test_an_under_gated_rl_is_kept_out_of_the_ensemble_too(tmp_path, monkeypatch):
    """The factor list must not NAME an RL that score_rl refuses.

    Before this, the list keyed off rl_enabled alone: an under-gated RL was
    reported as participating while score_rl returned source='gated' with bias 0,
    so the module's two public surfaces disagreed about the hard rule.
    """
    from rl_advisory import service
    monkeypatch.setattr(service, "rl_gate_unmet", lambda cfg_path=None: (240, 500))
    base = ["llm_primary", "rule_based"]
    names = service.rl_ensemble_factor_names(
        base, cfg_path=_cfg(tmp_path, rl_enabled=True))
    assert "rl_advisory" not in names
    assert names == base


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


# --- The real-fill gate is enforced at the READ, not just at the GUI write ----
#
# CLAUDE.md, a hard rule: "RL ships toggled off, trains only on real fills, and
# activates only past the rl_min_real_fills gate". That gate used to live ONLY in
# api_server.set_rl, which refuses to WRITE an enable below it. So the rule held
# only for operators who went through the GUI. A hand-edited config, or now a
# hand-edited controls.json (which the runtime-precedence fix makes
# authoritative), could set rl_enabled true under-gated and score_rl would serve
# a policy that was never entitled to run. Now the flag is a REQUEST and the gate
# decides.

def test_the_fill_gate_blocks_an_under_gated_rl_at_the_read(tmp_path, monkeypatch):
    """rl_enabled=true does NOT activate RL below the fill gate."""
    from rl_advisory import service
    monkeypatch.setattr(service, "rl_gate_unmet", lambda cfg_path=None: (240, 500))
    cfg = _cfg(tmp_path, rl_enabled=True)
    v = score_rl({"symbol": "BTC-USD", "ret_5": 0.03}, cfg_path=cfg)

    assert v["source"] == "gated"
    # Out of the ensemble entirely: it contributes nothing rather than a guess.
    assert v["bias"] == 0.0 and v["confidence"] == 0.0
    assert v["rl_position_scale_hint"] == 0.0
    assert "240" in v["rationale"] and "500" in v["rationale"]


def test_the_fill_gate_fails_closed_when_the_count_cannot_be_read(tmp_path,
                                                                  monkeypatch):
    """An unreadable fill count gates RL. Unprovable means not yet."""
    from rl_advisory import service
    monkeypatch.setenv("MAL_DB_PATH", str(tmp_path / "does_not_exist.db"))
    unmet = service.rl_gate_unmet(_cfg(tmp_path, rl_enabled=True))
    assert unmet is not None
    fills, gate = unmet
    assert fills == 0 and gate == 500


def test_a_zero_gate_means_no_gate_even_when_the_count_is_unreadable(tmp_path,
                                                                    monkeypatch):
    """min_fills=0 disables the gate. The fail-closed path must not override it."""
    from rl_advisory import service
    monkeypatch.setenv("MAL_DB_PATH", str(tmp_path / "does_not_exist.db"))
    assert service.rl_gate_unmet(_cfg(tmp_path, rl_enabled=True,
                                      min_fills=0)) is None


def test_rl_enabled_honors_controls_json_over_config(tmp_path, monkeypatch):
    """The precedence rule reaches RL too: controls.json wins over config.

    Safe only because the fill gate is enforced at the read. The toggle is a
    request; the gate is the authority.
    """
    import json
    from rl_advisory.config import rl_enabled
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path))
    (tmp_path / "controls.json").write_text(json.dumps({"rl_enabled": True}))
    # cfg_path=None is the runtime path, which reads the control file.
    assert rl_enabled() is True
    # A PINNED config ignores the control file, so tests stay hermetic.
    assert rl_enabled(_cfg(tmp_path, rl_enabled=False)) is False


def test_rl_enabled_degrades_instead_of_raising_when_llm_consensus_is_absent(
        monkeypatch):
    """rl_advisory must degrade, never raise.

    service.score_rl promises "none of which ever raise (offline runs must not
    break)". rl_enabled reaches ACROSS packages for the control file, and an
    unguarded ImportError there propagated through score_rl and would 500 the
    bridge's /score/rl instead of returning a labelled neutral.
    """
    import sys
    from rl_advisory.config import rl_enabled
    from rl_advisory.service import score_rl
    monkeypatch.setitem(sys.modules, "llm_consensus", None)

    # No control file reachable means no override, so config decides, and config
    # ships RL off. The fallback cannot enable anything.
    assert rl_enabled() is False
    v = score_rl({"symbol": "BTC-USD", "ret_5": 0.03})
    assert v["source"] == "disabled"
    assert v["bias"] == 0.0 and v["confidence"] == 0.0


def test_the_fill_count_is_cached_off_the_hot_path(tmp_path, monkeypatch):
    """The gate runs on EVERY score once RL is on. It must not re-query per call.

    Without a cache, enabling RL puts a sqlite connect plus a COUNT(*) over a
    growing trades table on the engine's per-symbol, per-bar advisory path.
    """
    from rl_advisory import service
    service.reset_gate_cache()
    calls = []
    monkeypatch.setattr(service, "_db_path", lambda: str(tmp_path / "x.db"))
    real = service._cached_real_fills

    import ml_factor.real_dataset as rd
    def counting(conn):
        calls.append(1)
        return 7
    monkeypatch.setattr(rd, "count_closed_trades", counting)
    # Give it a real database so the count path is actually reached.
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "x.db"))
    conn.execute("CREATE TABLE trades (outcome TEXT, origin TEXT)")
    conn.commit(); conn.close()

    for _ in range(50):
        assert service._cached_real_fills() == 7
    assert len(calls) == 1, f"expected 1 query for 50 reads, got {len(calls)}"


def test_the_fill_cache_is_keyed_by_database(tmp_path, monkeypatch):
    """A different database must never be served the previous one's count."""
    from rl_advisory import service
    service.reset_gate_cache()
    monkeypatch.setattr(service, "_db_path", lambda: str(tmp_path / "a.db"))
    assert service._cached_real_fills() == 0        # absent db -> 0, gated
    monkeypatch.setattr(service, "_db_path", lambda: str(tmp_path / "b.db"))
    assert service._cached_real_fills() == 0        # re-read, not served from a.db
    # The cache key changed, so the second call did not reuse the first entry.
    assert service._fills_cache[1] == str(tmp_path / "b.db")


def test_the_db_path_is_repo_root_anchored_not_cwd_relative(tmp_path, monkeypatch):
    """The launchers (stack.db_path, store._DEFAULT_DB, ui/db) all anchor the
    default to the repo root, so the gate must resolve the same file from any cwd.

    A bare relative default meant a bridge started outside the repo root read a
    database that was not there, counted 0, and silently gated RL forever.
    """
    import os
    from rl_advisory import service
    monkeypatch.delenv("MAL_DB_PATH", raising=False)
    here = service._db_path()
    assert os.path.isabs(here)
    monkeypatch.chdir(tmp_path)
    assert service._db_path() == here, "the db path must not follow the cwd"


def test_mal_db_path_and_config_db_path_still_win(tmp_path, monkeypatch):
    from rl_advisory import service
    monkeypatch.setenv("MAL_DB_PATH", "/tmp/explicit.db")
    assert service._db_path() == "/tmp/explicit.db"
    monkeypatch.delenv("MAL_DB_PATH")
    from llm_consensus import config_access
    monkeypatch.setattr(config_access, "config_block",
                        lambda name, path=None: {"db_path": "/tmp/from_config.db"}
                        if name == "system" else {})
    assert service._db_path() == "/tmp/from_config.db"

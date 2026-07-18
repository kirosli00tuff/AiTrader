"""DNN advisory factor: canonical features, serving, artifact round trip.

Rewritten 2026-07-18 for the unified pipeline: build_features(state) is gone,
both training and serving build through features_at over real bars, and
serving refuses what it cannot compute honestly.
"""
from __future__ import annotations

import sqlite3

from ml_factor.factor import load_champion, score_state
from ml_factor.features import (FEATURE_NAMES, FEATURE_SET_VERSION,
                                N_FEATURES, features_at)
from ml_factor.model import DnnModel


def _bars(n=40, start_price=100.0):
    bars = []
    price = start_price
    for i in range(n):
        price *= 1.0 + (0.002 if i % 3 else -0.001)
        bars.append({"ts": f"2026-07-18T{(i // 12):02d}:{(i % 12) * 5:02d}:00Z",
                     "open": price * 0.999, "high": price * 1.004,
                     "low": price * 0.996, "close": price, "volume": 10.0})
    return bars


def _bars_db(tmp_path, symbol="BTC/USD", n=40):
    db = tmp_path / "bars.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE bars (venue TEXT, symbol TEXT, timeframe TEXT,"
        " timestamp TEXT, open REAL, high REAL, low REAL, close REAL,"
        " volume REAL, source TEXT DEFAULT 'unknown')")
    for b in _bars(n):
        conn.execute(
            "INSERT INTO bars VALUES('alpaca',?, '5min',?,?,?,?,?,?,"
            "'backfill')",
            (symbol, b["ts"], b["open"], b["high"], b["low"], b["close"],
             b["volume"]))
    conn.commit()
    conn.close()
    return str(db)


def _served(tmp_path, monkeypatch, state=None, n=40):
    from ml_factor import factor
    monkeypatch.setenv("MAL_DB_PATH", _bars_db(tmp_path, n=n))
    monkeypatch.setattr(factor, "_bench_cache", None)
    return score_state(state or {"symbol": "BTC/USD", "price": 100.0})


def test_features_have_fixed_width_and_version():
    feats = features_at(_bars(), 39)
    assert len(feats) == N_FEATURES == len(FEATURE_NAMES)
    assert FEATURE_SET_VERSION == "bars-v2"


def test_score_state_emits_named_fields(tmp_path, monkeypatch):
    out = _served(tmp_path, monkeypatch)
    for key in ("dnn_action_bias", "dnn_confidence", "dnn_expected_edge",
                "dnn_regime_label", "dnn_risk_flag",
                "dnn_position_scale_hint", "available", "benched"):
        assert key in out
    assert out["available"] is True
    # The synthetic champion is benched: aliases zero, raw visible.
    if out["benched"]:
        assert out["bias"] == 0.0
        assert out["confidence"] == 0.0
        assert out["edge"] == 0.0
        assert out["benched_reason"]
    else:
        assert out["bias"] == out["dnn_action_bias"]
        assert out["confidence"] == out["dnn_confidence"]
        assert out["edge"] == out["dnn_expected_edge"]


def test_scale_hint_is_capped(tmp_path, monkeypatch):
    out = _served(tmp_path, monkeypatch)
    assert out["dnn_position_scale_hint"] <= 0.5


def test_output_ranges(tmp_path, monkeypatch):
    out = _served(tmp_path, monkeypatch)
    assert -1.0 <= out["dnn_action_bias"] <= 1.0
    assert 0.0 <= out["dnn_confidence"] <= 1.0
    assert out["dnn_expected_edge"] >= 0.0
    assert out["dnn_risk_flag"] in (0, 1)


def test_champion_is_loadable_and_signed():
    model = load_champion()
    assert model.model_id
    # The self-healed bootstrap carries the canonical signature + normalizer.
    ok, why = model.signature_matches(list(FEATURE_NAMES))
    assert ok, why


def test_model_save_load_roundtrip_with_normalizer(tmp_path):
    model = DnnModel.train_synthetic(n=400, epochs=30, model_id="dnn-rt")
    path = str(tmp_path / "m.npz")
    model.save(path)
    reloaded = DnnModel.load(path)
    assert reloaded.model_id == "dnn-rt"
    assert list(reloaded.feature_names) == list(FEATURE_NAMES)
    assert reloaded.norm_mean is not None and reloaded.norm_std is not None
    feats = features_at(_bars(), 39)
    a = model.forward(feats)
    b = reloaded.forward(feats)
    assert a["dnn_action_bias"] == b["dnn_action_bias"]
    assert a["dnn_confidence"] == b["dnn_confidence"]

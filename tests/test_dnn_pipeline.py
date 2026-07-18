"""The unified DNN pipeline: one feature builder, signed artifacts, refusals.

Each test pins one of the fixes from the 2026-07-18 pipeline session. No
network, tmp DBs only, loopback untouched.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess

import pytest

from ml_factor import factor, real_dataset
from ml_factor.features import FEATURE_NAMES, N_FEATURES, features_at
from ml_factor.model import DnnModel

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENGINE = os.path.join(_REPO, "build", "mal_engine")


def _bars(n=40, price=100.0):
    out = []
    for i in range(n):
        price *= 1.0 + (0.003 if i % 4 else -0.002)
        out.append({"ts": f"2026-07-18T{(i // 12):02d}:{(i % 12) * 5:02d}:00Z",
                    "open": price * 0.999, "high": price * 1.005,
                    "low": price * 0.995, "close": price, "volume": 5.0})
    return out


# --- Task 1 + 2: one canonical pipeline, train == serve ----------------------

def test_training_and_serving_build_identical_features():
    # Training builds rows through real_dataset._features_at. Serving builds
    # through features.features_at. They must be THE SAME function producing
    # THE SAME vector, and the exported names must agree.
    bars = _bars()
    train_vec = real_dataset._features_at(bars, 30)
    serve_vec = features_at(bars, 30)
    assert train_vec == serve_vec
    assert real_dataset._features_at is features_at
    assert list(real_dataset.REAL_FEATURE_NAMES) == list(FEATURE_NAMES)
    assert len(train_vec) == N_FEATURES


def test_no_serving_feature_is_a_silent_constant_default():
    # The old serving builder defaulted recent_winrate=0.5, time_of_day=0.5,
    # streak=0, drawdown=0, imbalance=0, spread_rel. None of those constants
    # survives in the canonical set, and time_of_day is COMPUTED from the bar
    # timestamp, so it varies with the data.
    for gone in ("recent_winrate", "streak", "drawdown", "imbalance",
                 "spread_rel", "vol_z"):
        assert gone not in FEATURE_NAMES
    bars = _bars()
    tod_a = features_at(bars, 20)[FEATURE_NAMES.index("time_of_day")]
    tod_b = features_at(bars, 35)[FEATURE_NAMES.index("time_of_day")]
    assert tod_a != tod_b  # computed, not constant


def test_normalizer_is_persisted_and_applied(tmp_path):
    model = DnnModel.train_synthetic(n=400, epochs=30, model_id="dnn-nrm")
    path = str(tmp_path / "m.npz")
    model.save(path)
    reloaded = DnnModel.load(path)
    ok, why = reloaded.signature_matches(list(FEATURE_NAMES))
    assert ok, why
    # Strip the normalizer: the artifact must no longer satisfy the signature
    # rule. A model is never servable without the normalization it was
    # trained with.
    reloaded.norm_mean = None
    ok, why = reloaded.signature_matches(list(FEATURE_NAMES))
    assert not ok and "normalizer" in why


def test_signature_mismatch_refuses_to_serve(tmp_path, monkeypatch):
    # An artifact recording a DIFFERENT feature signature fails closed with a
    # clear message: zero aliases, available False, reason names the mismatch.
    model = DnnModel.train_synthetic(n=400, epochs=30, model_id="dnn-old")
    model.feature_names = ["ret_1", "ret_5"]  # wrong signature
    monkeypatch.setattr(factor, "_cached", model)
    out = factor.score_state({"symbol": "BTC/USD", "price": 100.0})
    assert out["available"] is False
    assert "refused to serve" in out["unavailable_reason"]
    assert out["bias"] == 0.0 and out["confidence"] == 0.0


def test_unsigned_legacy_artifact_refuses_to_serve(tmp_path, monkeypatch):
    model = DnnModel.train_synthetic(n=400, epochs=30, model_id="dnn-legacy")
    model.feature_names = None
    model.norm_mean = None
    model.norm_std = None
    monkeypatch.setattr(factor, "_cached", model)
    out = factor.score_state({"symbol": "BTC/USD", "price": 100.0})
    assert out["available"] is False
    assert "no feature signature" in out["unavailable_reason"]


def test_symbol_without_real_bars_is_unavailable_not_defaulted(
        tmp_path, monkeypatch):
    # No bars for the symbol: the old path would have scored constants. Now
    # the inference is UNAVAILABLE and contributes nothing, consistent with
    # the bench behavior.
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    monkeypatch.setenv("MAL_DB_PATH", str(db))
    monkeypatch.setattr(factor, "_bench_cache", None)
    monkeypatch.setattr(factor, "_cached", None)
    out = factor.score_state({"symbol": "NEW/USD", "price": 5.0})
    assert out["available"] is False
    assert out["bias"] == 0.0
    assert "bars" in out["unavailable_reason"]


def test_synthetic_bars_are_excluded_from_the_pipeline(tmp_path):
    db = tmp_path / "mix.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE bars (venue TEXT, symbol TEXT, timeframe TEXT,"
        " timestamp TEXT, open REAL, high REAL, low REAL, close REAL,"
        " volume REAL, source TEXT DEFAULT 'unknown')")
    for i, b in enumerate(_bars(30)):
        src = "synthetic" if i >= 25 else "backfill"
        conn.execute("INSERT INTO bars VALUES('alpaca','X/USD','5min',?,?,?,?,?,?,?)",
                     (b["ts"], b["open"], b["high"], b["low"], b["close"],
                      b["volume"], src))
    conn.commit()
    loaded = real_dataset.load_bars(conn, "X/USD", "5min")
    conn.close()
    assert len(loaded) == 25  # walk bars never reach training or serving


# --- Task 3: promotion refuses a challenger without a loadable artifact ------

def test_artifact_loadable_refuses_missing_and_accepts_signed(tmp_path):
    ok, why = factor.artifact_loadable(str(tmp_path / "missing.npz"))
    assert not ok and "no artifact" in why
    model = DnnModel.train_synthetic(n=400, epochs=30, model_id="dnn-ch")
    path = str(tmp_path / "ch.npz")
    model.save(path)
    ok, why = factor.artifact_loadable(path)
    assert ok, why


def test_promotion_refuses_metadata_only_challenger(monkeypatch, tmp_path):
    # The full request_promote path with a challenger that has NO artifact:
    # refused before the registry is touched, so a metadata-only promotion is
    # impossible. bench_state's artifact-match rule is the second, independent
    # guard behind this one.
    from api_server import controls
    monkeypatch.setattr(controls, "registry_summary", lambda: {
        "can_promote": True, "promote_reason": "ok",
        "challenger": {"model_id": "dnn-real-1", "metrics": {}},
        "champion": {"model_id": "dnn-0.1.0"},
        "can_rollback": False,
    })
    promoted = {"called": False}
    monkeypatch.setattr(controls, "_registry_conn",
                        lambda: promoted.update(called=True))
    out = controls.request_promote()
    assert out["ok"] is False
    assert "no servable artifact" in out["error"]
    assert promoted["called"] is False  # refused BEFORE the registry promote


def test_train_real_supervised_produces_signed_servable_artifact(tmp_path):
    bars = _bars(80)
    X = [features_at(bars, i) for i in range(20, 70)]
    y = [bars[i + 5]["close"] / bars[i]["close"] - 1.0 for i in range(20, 70)]
    model = DnnModel.train_real_supervised(X, y, model_id="dnn-real-t",
                                           epochs=30)
    path = str(tmp_path / "real.npz")
    model.save(path)
    ok, why = factor.artifact_loadable(path)
    assert ok, why


# --- Task 5: --help touches nothing ------------------------------------------

@pytest.mark.skipif(not os.path.exists(_ENGINE),
                    reason="mal_engine not built (build/ absent)")
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_engine_help_exits_without_touching_the_database(tmp_path, flag):
    r = subprocess.run([_ENGINE, flag], cwd=tmp_path, capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0
    assert "Usage:" in r.stdout
    assert not os.path.exists(tmp_path / "market_ai_lab.db")


# --- Task 6: the RL write gate equals the read gate ---------------------------

def test_real_fills_uses_the_canonical_counter(tmp_path, monkeypatch):
    from api_server import controls, store
    from ml_factor.real_dataset import count_closed_trades
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, ts TEXT, venue TEXT,"
        " symbol TEXT, side TEXT, mode TEXT, pnl REAL, outcome TEXT,"
        " origin TEXT DEFAULT 'strategy', bar_source TEXT DEFAULT 'unknown')")
    rows = [("win", "strategy", "real_feed"), ("loss", "strategy", "unknown"),
            ("win", "rebalance", "real_feed"),        # origin-excluded
            ("win", "strategy", "synthetic"),         # provenance-excluded
            ("open", "strategy", "real_feed")]        # not closed
    for outcome, origin, src in rows:
        conn.execute(
            "INSERT INTO trades(ts,venue,symbol,side,mode,pnl,outcome,origin,"
            "bar_source) VALUES('2026-07-18T00:00:00Z','alpaca','B','buy',"
            "'paper',1.0,?,?,?)", (outcome, origin, src))
    conn.commit()
    canonical = count_closed_trades(conn)
    conn.close()
    monkeypatch.setenv("MAL_DB_PATH", str(db))
    assert controls.real_fills() == canonical == 2
    assert store._db_path() == str(db)


# --- Task 7: no cwd-relative database resolution ------------------------------

def test_db_paths_are_absolute_wherever_the_process_starts(tmp_path,
                                                           monkeypatch):
    monkeypatch.delenv("MAL_DB_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    import adaptive.run as arun
    import discovery.run as drun
    import ops.watchdog as wd
    for path in (arun._db_path(), wd._db_path(), drun._DEFAULT_DB,
                 factor._default_db_path()):
        assert os.path.isabs(path), path
        assert path.startswith(_REPO), path

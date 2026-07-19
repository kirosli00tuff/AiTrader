"""Stray invocations cannot touch production, and watchlist members are polled.

Two subprocess proofs against the built engine, both offline (mock feed, no
bridge, no network):

1. A mal_engine run WITHOUT --db writes a scratch mal_demo.db and never the
   production database. The five 2026-07-17 discovery_blocked warns came from
   exactly such strays polluting the diagnostic log.
2. A watchlist member is POLLED: an active watchlist row is onboarded at
   engine construction (whitelist merge, feed extension, discovery_onboard
   event) and the feed then closes bars for it, which is what keeps a
   discovered symbol current instead of a dead entry. SOL/USD died because it
   was never a member during any polling run, not because this path is
   unwired; this pins the path so that stays true.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENGINE = os.path.join(_REPO, "build", "mal_engine")
_SCHEMA = os.path.join(_REPO, "storage", "schema.sql")
_CONFIG = os.path.join(_REPO, "config", "default_config.yaml")

needs_engine = pytest.mark.skipif(
    not os.path.exists(_ENGINE),
    reason="mal_engine not built (build/ absent)")


@needs_engine
def test_no_db_flag_writes_scratch_demo_db_never_production(tmp_path):
    ctrl = tmp_path / "ctrl"
    ctrl.mkdir()
    env = {**os.environ, "MAL_CONTROL_DIR": str(ctrl)}
    r = subprocess.run(
        [_ENGINE, "--config", _CONFIG, "--schema", _SCHEMA,
         "--iterations", "2", "--feed-mode", "flat_random_walk"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "mal_demo.db").exists()
    assert not (tmp_path / "market_ai_lab.db").exists()
    assert "SCRATCH demo db" in r.stdout


@needs_engine
def test_explicit_db_flag_is_honored_unchanged(tmp_path):
    db = tmp_path / "explicit.db"
    ctrl = tmp_path / "ctrl"
    ctrl.mkdir()
    env = {**os.environ, "MAL_CONTROL_DIR": str(ctrl)}
    r = subprocess.run(
        [_ENGINE, "--config", _CONFIG, "--db", str(db), "--schema", _SCHEMA,
         "--iterations", "2", "--feed-mode", "flat_random_walk"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert db.exists()
    assert not (tmp_path / "mal_demo.db").exists()
    assert "SCRATCH demo db" not in r.stdout


@needs_engine
def test_watchlist_member_is_polled_and_stays_current(tmp_path):
    # Arrange: a scratch DB holding one ACTIVE watchlist member the engine has
    # never heard of, and a control dir turning discovery ON.
    db = tmp_path / "wl.db"
    conn = sqlite3.connect(db)
    from discovery import watchlist as wl
    wl.ensure_schema(conn)
    conn.execute(
        "INSERT INTO watchlist(symbol,asset_class,added_ts,updated_ts,source,"
        "reason,sleeve_target,score,status) VALUES('FAKE/USD','crypto',"
        "'2026-07-18T00:00:00Z','2026-07-18T00:00:00Z','discovery',"
        "'polling test','quant_core',0.6,'active')")
    conn.commit()
    conn.close()
    ctrl = tmp_path / "ctrl"
    ctrl.mkdir()
    (ctrl / "controls.json").write_text(
        json.dumps({"discovery": {"discovery_enabled": True}}))
    env = {**os.environ, "MAL_CONTROL_DIR": str(ctrl)}

    # Act: a short offline run, one bar closing per tick so the feed's polls
    # become persisted bars fast.
    r = subprocess.run(
        [_ENGINE, "--config", _CONFIG, "--db", str(db), "--schema", _SCHEMA,
         "--iterations", "30", "--native-bar-seconds", "0",
         "--feed-mode", "flat_random_walk"],
        cwd=_REPO, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr

    conn = sqlite3.connect(db)
    # Onboarded: whitelist merge + feed extension, said so in the event log.
    onboard = conn.execute(
        "SELECT COUNT(*) FROM events WHERE kind='discovery_onboard'"
        " AND symbol='FAKE/USD'").fetchone()[0]
    assert onboard >= 1, r.stdout
    # Polled and current: the feed closed real bar rows for it this run.
    bars = conn.execute(
        "SELECT COUNT(*) FROM bars WHERE symbol='FAKE/USD'").fetchone()[0]
    assert bars > 0, ("onboarded but never polled: the dead-entry state "
                      f"this test exists to prevent\n{r.stdout}")
    conn.close()

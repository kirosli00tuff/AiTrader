"""Tests for the week-long-run ops: watchdog, backups, and maintenance.

All process/HTTP/notification calls are mocked, so no test starts a real process,
opens a socket, or sends a real notification. The watchdog must detect a dead
engine and a stale feed, attempt ONE restart, notify on both outcomes, never
auto-resume a kill trip, and never touch the kill-request file.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from ops import watchdog, backup, maintenance


@pytest.fixture(autouse=True)
def _isolated_remediation_state(tmp_path, monkeypatch):
    """Own loop-guard state file per test: a restart recorded by one test must
    not read as a remediation loop in the next."""
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))


# --- Watchdog ---------------------------------------------------------------

def _health(engine=True, bridge=True, backend=True, fresh=True, kill=False):
    return {"engine": engine, "bridge": bridge, "backend": backend,
            "feed_fresh": fresh, "kill_tripped": kill,
            "healthy": engine and bridge and backend and fresh}


def test_watchdog_restarts_dead_engine_and_notifies(monkeypatch):
    sent, restarted = [], []
    monkeypatch.setattr(watchdog, "check_health", lambda cfg=None: _health(engine=False, fresh=False))
    monkeypatch.setattr(watchdog, "notify", lambda msg, cfg=None, title="": sent.append(msg) or True)
    monkeypatch.setattr(watchdog, "attempt_restart",
                        lambda: restarted.append(True) or {"restarted": True, "detail": "running", "healed": {}})
    res = watchdog.run_once({})
    assert res["action"] == "restarted"
    assert restarted == [True]           # exactly ONE restart attempt
    assert sent and "Restarted" in sent[0]


def test_watchdog_notifies_when_restart_fails(monkeypatch):
    sent = []
    monkeypatch.setattr(watchdog, "check_health", lambda cfg=None: _health(backend=False))
    monkeypatch.setattr(watchdog, "notify", lambda msg, cfg=None, title="": sent.append(msg) or True)
    monkeypatch.setattr(watchdog, "attempt_restart",
                        lambda: {"restarted": False, "detail": "supervisor unreachable", "healed": {}})
    res = watchdog.run_once({})
    assert res["action"] == "restart_failed"
    assert sent and "DOWN" in sent[0]


def test_watchdog_notifies_kill_but_never_auto_resumes(monkeypatch):
    sent, restarts = [], []
    monkeypatch.setattr(watchdog, "check_health", lambda cfg=None: _health(kill=True))
    monkeypatch.setattr(watchdog, "notify", lambda msg, cfg=None, title="": sent.append(msg) or True)
    monkeypatch.setattr(watchdog, "attempt_restart", lambda: restarts.append(True) or {})
    res = watchdog.run_once({})
    assert res["action"] == "kill_notified"
    assert restarts == []                # NEVER auto-resumes a kill trip
    assert sent and "Manual resume required" in sent[0]


def test_watchdog_healthy_no_action(monkeypatch):
    monkeypatch.setattr(watchdog, "check_health", lambda cfg=None: _health())
    monkeypatch.setattr(watchdog, "notify", lambda *a, **k: True)
    assert watchdog.run_once({})["action"] == "none"


def test_watchdog_never_touches_kill_request_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "control"))
    monkeypatch.setattr(watchdog, "check_health", lambda cfg=None: _health(engine=False, fresh=False))
    monkeypatch.setattr(watchdog, "notify", lambda *a, **k: True)
    monkeypatch.setattr(watchdog, "attempt_restart", lambda: {"restarted": True, "detail": "running", "healed": {}})
    watchdog.run_once({})
    assert not os.path.exists(str(tmp_path / "control" / "kill_request.json"))


def test_watchdog_notify_no_topic_is_noop():
    assert watchdog.notify("x", {"ntfy_topic": ""}) is False


# --- Backups ----------------------------------------------------------------

def _seed_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE trades(id INTEGER PRIMARY KEY, ts TEXT)")
    conn.executemany("INSERT INTO trades(ts) VALUES(?)",
                     [("2026-07-15T00:00:00Z",) for _ in range(5)])
    conn.commit()
    conn.close()


def test_backup_produces_restorable_snapshot(tmp_path):
    db = tmp_path / "op.db"
    _seed_db(str(db))
    out = tmp_path / "backups"
    res = backup.backup(str(db), str(out), retention=14)
    assert os.path.exists(res["snapshot"])
    assert res["trades_rows"] == 5                # restore-verified row count
    assert backup.verify(res["snapshot"]) == 5


def test_backup_retention_prunes_oldest(tmp_path):
    db = tmp_path / "op.db"
    _seed_db(str(db))
    out = tmp_path / "backups"
    os.makedirs(out, exist_ok=True)
    for i in range(4):
        dest = out / f"market_ai_lab-2026071{i}T000000Z.db"
        src = sqlite3.connect(str(db)); snap = sqlite3.connect(str(dest))
        src.backup(snap); snap.close(); src.close()
    removed = backup.prune(str(out), retention=2)
    kept = sorted(p for p in os.listdir(out))
    assert len(kept) == 2 and len(removed) == 2   # oldest two removed


# --- Maintenance ------------------------------------------------------------

def _seed_events(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, ts TEXT, kind TEXT)")
    conn.execute("CREATE TABLE trades(id INTEGER PRIMARY KEY, ts TEXT)")
    conn.execute("CREATE TABLE bars(id INTEGER PRIMARY KEY, ts TEXT)")
    old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.executemany("INSERT INTO events(ts,kind) VALUES(?,?)", [
        (old, "regime"),        # old, prunable
        (old, "no_execution"),  # old, prunable
        (old, "trade_entry"),   # old, PROTECTED
        (old, "kill_switch"),   # old, PROTECTED
        (new, "regime"),        # recent, kept
    ])
    conn.execute("INSERT INTO trades(ts) VALUES(?)", (old,))
    conn.execute("INSERT INTO bars(ts) VALUES(?)", (old,))
    conn.commit()
    conn.close()


def test_prune_events_protects_audit_and_tables(tmp_path):
    db = tmp_path / "op.db"
    _seed_events(str(db))
    res = maintenance.prune_events(str(db), keep_days=30)
    assert res["deleted"] == 2                     # only the 2 old informational rows
    conn = sqlite3.connect(str(db))
    kinds = [r[0] for r in conn.execute("SELECT kind FROM events").fetchall()]
    assert "trade_entry" in kinds and "kill_switch" in kinds  # audit kept
    assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1  # trades untouched
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 1    # bars untouched
    conn.close()


def test_prune_events_noop_when_keep_days_zero(tmp_path):
    db = tmp_path / "op.db"
    _seed_events(str(db))
    assert maintenance.prune_events(str(db), keep_days=0)["deleted"] == 0


def test_events_per_day_estimate(tmp_path):
    db = tmp_path / "op.db"
    _seed_events(str(db))
    assert maintenance.events_per_day(str(db)) >= 0.0


def test_challenger_refuses_or_reports(tmp_path):
    # With no real dataset the trainer refuses cleanly (or reports unavailable if
    # numpy is missing). It NEVER raises and NEVER auto-promotes.
    db = tmp_path / "op.db"
    _seed_events(str(db))
    res = maintenance.maybe_train_challenger(str(db))
    assert isinstance(res, dict) and "status" in res

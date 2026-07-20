"""The watchdog must REMEDIATE a degraded bridge, not only detect it.

2026-07-18/19: the watchdog detected bridge_degraded 60 times over 20 hours,
wrote an evidence file each time, and never restarted anything. Three
compounding reasons, each pinned here: attempt_restart only knew how to
START a down stack; self_heal refused while the sick stack still answered
HTTP 200 ("a healthy stack is already running"); and the supervisor's
refusal ("start refused: already running") echoed state "running", which the
old success test read as a completed restart. The fix stops a running-but-
sick stack first through the supervisor's graceful /engine/stop, then
starts, and success requires the supervisor to ACCEPT the start (ok true).

Everything is mocked: no test starts a process, opens a socket, or sends a
notification. The kill switch is never auto-resumed and the kill-request
file is never touched.
"""
from __future__ import annotations

import os

import pytest

from ops import watchdog


@pytest.fixture(autouse=True)
def _isolated_remediation_state(tmp_path, monkeypatch):
    """Each test gets its own loop-guard state file: without this, a restart
    recorded by one test reads as a remediation loop in the next."""
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))


def _health(*, degraded=False, substitution=False, kill=False, healthy=None):
    h = {"engine": True, "bridge": not degraded,
         "bridge_status": "degraded" if degraded else "ok",
         "bridge_degraded": ["fd_headroom"] if degraded else [],
         "backend": True, "feed_fresh": True, "feed_source": "real_feed",
         "feed_ok": not substitution, "feed_stale_symbols": [],
         "feed_non_real_symbols": ["BTC/USD"] if substitution else [],
         "feed_substitution": substitution, "kill_tripped": kill,
         "healthy": (not degraded and not substitution) if healthy is None
                    else healthy}
    return h


def _wire(monkeypatch, *, health, running=True, posts=None, notes=None):
    """Wire run_once's collaborators: recorded supervisor posts, recorded
    notifications, a quiet evidence capture, and a self-heal recorder."""
    posts = posts if posts is not None else []
    notes = notes if notes is not None else []
    healed = []

    def fake_post(path, timeout=30):
        posts.append(path)
        if path == "/engine/stop":
            return {"ok": True, "state": "not_running"}
        return {"ok": True, "state": "starting"}

    monkeypatch.setattr(watchdog, "check_health", lambda cfg=None: health)
    monkeypatch.setattr(watchdog, "_supervisor_post", fake_post)
    monkeypatch.setattr(watchdog.stack, "stack_running",
                        lambda: {"running": running})
    monkeypatch.setattr(watchdog.stack, "self_heal",
                        lambda: healed.append(True) or {"stopped": []})
    monkeypatch.setattr(watchdog, "notify",
                        lambda msg, cfg=None, title="": notes.append(msg)
                        or True)
    monkeypatch.setattr(watchdog, "capture_before_restart",
                        lambda h: (None, ""))
    return posts, notes, healed


# --- The two triggering conditions actually remediate ------------------------

def test_degraded_bridge_triggers_stop_then_start_and_notifies(monkeypatch):
    posts, notes, healed = _wire(monkeypatch, health=_health(degraded=True))
    res = watchdog.run_once({})
    assert res["action"] == "restarted"
    assert posts == ["/engine/stop", "/engine/start"]  # stop FIRST, then start
    assert healed == [True]
    assert notes and "Restarted" in notes[0]


def test_feed_substitution_triggers_stop_then_start_and_notifies(monkeypatch):
    posts, notes, _ = _wire(monkeypatch, health=_health(substitution=True))
    res = watchdog.run_once({})
    assert res["action"] == "restarted"
    assert posts == ["/engine/stop", "/engine/start"]
    assert notes and "Restarted" in notes[0]


def test_exactly_one_restart_per_cycle(monkeypatch):
    posts, _, _ = _wire(monkeypatch, health=_health(degraded=True))
    watchdog.run_once({})
    assert posts.count("/engine/stop") == 1
    assert posts.count("/engine/start") == 1


def test_down_stack_skips_the_stop_and_still_starts(monkeypatch):
    # The crash shape the watchdog always handled: nothing running, nothing
    # to stop, self-heal then start.
    posts, notes, healed = _wire(
        monkeypatch, health=_health(degraded=True), running=False)
    res = watchdog.run_once({})
    assert res["action"] == "restarted"
    assert posts == ["/engine/start"]
    assert healed == [True]


# --- The 2026-07-19 failure shapes can never read as success -----------------

def test_start_refusal_is_not_a_successful_restart(monkeypatch):
    # The exact response that fooled the old predicate for 60 cycles: ok
    # false, error "already running", state echo "running".
    def refusing_post(path, timeout=30):
        if path == "/engine/stop":
            return {"ok": True, "state": "not_running"}
        return {"ok": False, "state": "running",
                "error": "start refused: already running"}

    monkeypatch.setattr(watchdog, "_supervisor_post", refusing_post)
    monkeypatch.setattr(watchdog.stack, "stack_running",
                        lambda: {"running": True})
    monkeypatch.setattr(watchdog.stack, "self_heal", lambda: {})
    r = watchdog.attempt_restart()
    assert r["restarted"] is False
    assert "refused" in r["detail"]


def test_refused_stop_reports_failure_and_never_starts(monkeypatch):
    posts = []

    def refusing_stop(path, timeout=30):
        posts.append(path)
        return {"ok": False, "error": "nope"}

    monkeypatch.setattr(watchdog, "_supervisor_post", refusing_stop)
    monkeypatch.setattr(watchdog.stack, "stack_running",
                        lambda: {"running": True})
    monkeypatch.setattr(watchdog.stack, "self_heal",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("self_heal must not run")))
    r = watchdog.attempt_restart()
    assert r["restarted"] is False
    assert posts == ["/engine/stop"]


def test_unreachable_stop_leaves_the_running_stack_up(monkeypatch):
    # If the backend cannot be reached we cannot start either, so the sick
    # stack must be LEFT RUNNING rather than stopped into a hole.
    def dead_post(path, timeout=30):
        raise OSError("connection refused")

    healed = []
    monkeypatch.setattr(watchdog, "_supervisor_post", dead_post)
    monkeypatch.setattr(watchdog.stack, "stack_running",
                        lambda: {"running": True})
    monkeypatch.setattr(watchdog.stack, "self_heal",
                        lambda: healed.append(True) or {})
    r = watchdog.attempt_restart()
    assert r["restarted"] is False
    assert "leaving the running stack up" in r["detail"]
    assert healed == []  # no teardown of any kind was attempted


# --- The kill switch stays sovereign -----------------------------------------

def test_kill_trip_with_degraded_bridge_is_never_restarted(monkeypatch):
    # A tripped kill switch outranks remediation: notify, no stop, no start,
    # manual resume stays required.
    posts, notes, healed = _wire(
        monkeypatch, health=_health(degraded=True, kill=True))
    res = watchdog.run_once({})
    assert res["action"] == "kill_notified"
    assert posts == []
    assert healed == []
    assert notes and "Manual resume required" in notes[0]


def test_remediation_never_touches_the_kill_request_file(monkeypatch,
                                                         tmp_path):
    control = tmp_path / "control"
    monkeypatch.setenv("MAL_CONTROL_DIR", str(control))
    posts, _, _ = _wire(monkeypatch, health=_health(degraded=True))
    watchdog.run_once({})
    assert posts == ["/engine/stop", "/engine/start"]
    assert not os.path.exists(str(control / "kill_request.json"))

"""Every engine stop path persists its attribution (2026-07-24).

The 2026-07-21 stop was unattributable because no stop path journalled its
caller. These pin the Python-side paths: the /engine/stop route passes the
caller through, the supervisor journals engine_stop_requested BEFORE acting
(unattributed when unnamed), stack.terminate_pid journals process_stop before
the signal, and the watchdog names itself in its POST payload.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO, "storage", "schema.sql")


@pytest.fixture()
def temp_env(tmp_path, monkeypatch):
    db = tmp_path / "attr.db"
    conn = sqlite3.connect(db)
    with open(SCHEMA) as fh:
        conn.executescript(fh.read())
    conn.commit()
    conn.close()
    monkeypatch.setenv("MAL_DB_PATH", str(db))
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "control"))
    return db


def _events(db, kind):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT message, payload_json FROM events WHERE kind=? ORDER BY id",
            (kind,)).fetchall()
    finally:
        conn.close()


def test_supervisor_stop_journals_caller_before_acting(temp_env):
    from api_server import supervisor
    out = supervisor.SUPERVISOR.stop(caller="test_caller", reason="test why")
    assert out["ok"]
    rows = _events(temp_env, "engine_stop_requested")
    assert rows, "the stop request must journal even when nothing is running"
    payload = json.loads(rows[-1][1])
    assert payload["caller"] == "test_caller"
    assert payload["reason"] == "test why"
    assert payload["supervisor_pid"] == os.getpid()


def test_unnamed_caller_is_recorded_as_unattributed(temp_env):
    from api_server import supervisor
    supervisor.SUPERVISOR.stop()
    rows = _events(temp_env, "engine_stop_requested")
    payload = json.loads(rows[-1][1])
    # A stop that cannot name its caller records THAT, not nothing.
    assert payload["caller"] == "unattributed"


def test_engine_stop_route_passes_the_caller_through(temp_env, monkeypatch):
    from fastapi.testclient import TestClient
    from api_server import app as app_module, supervisor
    seen = {}
    monkeypatch.setattr(
        supervisor.SUPERVISOR, "stop",
        lambda caller="", reason="": seen.update(caller=caller,
                                                 reason=reason) or {"ok": True})
    client = TestClient(app_module.app)
    r = client.post("/engine/stop", json={"caller": "gui_operator",
                                          "reason": "stop button"})
    assert r.status_code == 200
    assert seen == {"caller": "gui_operator", "reason": "stop button"}


def test_terminate_pid_journals_process_stop(temp_env):
    import threading
    from api_server import stack
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    # Reap the child as it dies: a terminated but unreaped child is a zombie
    # and pid_alive (kill(pid, 0)) still reads it as alive.
    threading.Thread(target=proc.wait, daemon=True).start()
    try:
        assert stack.terminate_pid(proc.pid, why="test: attribution check")
    finally:
        if proc.poll() is None:
            proc.kill()
    rows = _events(temp_env, "process_stop")
    assert rows, "terminate_pid must journal before signalling"
    payload = json.loads(rows[-1][1])
    assert payload["target_pid"] == proc.pid
    assert payload["sender_pid"] == os.getpid()
    assert "attribution check" in payload["caller"]


def test_watchdog_names_itself_in_the_stop_payload(monkeypatch):
    from ops import watchdog

    captured = {}

    class _Resp:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        captured["data"] = req.data
        return _Resp()

    monkeypatch.setattr(watchdog.urllib.request, "urlopen", fake_urlopen)
    watchdog._supervisor_post("/engine/stop",
                              payload={"caller": "watchdog",
                                       "reason": "condition feed_ok: stale"})
    body = json.loads(captured["data"].decode())
    assert body["caller"] == "watchdog"
    assert "feed_ok" in body["reason"]

"""Evidence capture and fd telemetry for the two unexplained failure modes.

The captures exist so the NEXT occurrence of the layer.whale unaudited
restoration or the engine-ON funnel-OFF flag mismatch documents itself:
control file bytes as read, reading process pid and start time, and (for the
funnel case) the bridge's fd count. These tests pin that each capture fires on
its condition, records the specified fields, stays silent otherwise, and that
the bridge health payload carries fd telemetry that degrades at the threshold.

No network. The diagnostics dir and control dir are isolated per test.
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from ops import evidence


@pytest.fixture()
def diag_dir(tmp_path, monkeypatch):
    d = tmp_path / "diag"
    monkeypatch.setenv("MAL_DIAGNOSTICS_DIR", str(d))
    monkeypatch.setattr(evidence, "_last_capture", {})
    return d


def _records(diag_dir, condition):
    if not diag_dir.exists():
        return []
    return sorted(diag_dir.glob(f"{condition}-*.json"))


# --- The capture primitive ----------------------------------------------------

def test_capture_records_the_specified_fields(diag_dir, tmp_path, monkeypatch):
    ctrl = tmp_path / "ctrl"
    ctrl.mkdir()
    (ctrl / "controls.json").write_bytes(b'{"layers": {"whale": true}}')
    monkeypatch.setenv("MAL_CONTROL_DIR", str(ctrl))

    path = evidence.capture("test_condition", {"why": "unit"},
                            min_interval_seconds=0)
    assert path is not None
    record = json.loads(open(path).read())
    assert record["condition"] == "test_condition"
    assert record["pid"] == os.getpid()
    # Start time from /proc: an ISO timestamp on linux, an error string never.
    assert record["process_start_time"].startswith("20")
    assert isinstance(record["fd_count"], int)
    # The control file BYTES as read, verbatim, with integrity facts.
    cf = record["control_file"]
    assert cf["bytes"] == '{"layers": {"whale": true}}'
    assert len(cf["sha256"]) == 64
    assert cf["size"] == 27
    assert record["detail"] == {"why": "unit"}


def test_capture_is_rate_limited_per_condition(diag_dir, monkeypatch):
    assert evidence.capture("rl_cond", {}) is not None
    assert evidence.capture("rl_cond", {}) is None      # inside the window
    assert evidence.capture("other_cond", {}) is not None  # separate condition
    assert len(_records(diag_dir, "rl_cond")) == 1


def test_capture_survives_a_missing_control_file(diag_dir, tmp_path,
                                                 monkeypatch):
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "absent"))
    path = evidence.capture("no_ctrl", {}, min_interval_seconds=0)
    record = json.loads(open(path).read())
    # The unreadable file is a recorded fact, not a voided record.
    assert "read_error" in record["control_file"] \
        or "stat_error" in record["control_file"]


def test_fd_and_socket_counts_read_as_ints_on_proc():
    assert isinstance(evidence.fd_count(), int)
    assert isinstance(evidence.socket_count(), int)


def test_fd_count_reports_error_string_for_dead_pid():
    # A pid that cannot exist: the error string is the recorded fact.
    out = evidence.fd_count(2 ** 22 + 1)
    assert isinstance(out, str) and out.startswith("unavailable")


# --- Condition 1: layer toggle restored with no audit row --------------------

_EVENTS_DDL = (
    "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,"
    " kind TEXT, venue TEXT, symbol TEXT, severity TEXT, message TEXT,"
    " payload_json TEXT)")


def _controls_env(tmp_path, monkeypatch, audit_new):
    """Isolated control dir + a tmp DB whose last layer.whale audit says
    ``audit_new``. Returns the DB path."""
    ctrl = tmp_path / "ctrl"
    ctrl.mkdir()
    monkeypatch.setenv("MAL_CONTROL_DIR", str(ctrl))
    db = tmp_path / "audit.db"
    conn = sqlite3.connect(db)
    conn.execute(_EVENTS_DDL)
    if audit_new is not None:
        conn.execute(
            "INSERT INTO events(ts,kind,severity,message,payload_json)"
            " VALUES(?,?,?,?,?)",
            ("2026-07-17T08:44:00Z", "control_change", "info",
             f"layer.whale: True -> {audit_new}",
             json.dumps({"param": "layer.whale", "old": True,
                         "new": audit_new, "source": "gui"})))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MAL_DB_PATH", str(db))
    return db


def test_set_layer_captures_an_unaudited_restoration(diag_dir, tmp_path,
                                                     monkeypatch):
    # The 2026-07-17 shape: the last audit wrote False, yet the toggle reads
    # the on-disk value as True. Something restored it with no audit row.
    from api_server import controls
    _controls_env(tmp_path, monkeypatch, audit_new=False)
    out = controls.set_layer("whale", False)
    assert out["ok"] is True             # diagnosis only, the toggle proceeds
    records = _records(diag_dir, "layer_unaudited_change")
    assert len(records) == 1
    record = json.loads(open(records[0]).read())
    assert record["detail"]["param"] == "layer.whale"
    assert record["detail"]["on_disk_value"] is True
    assert record["detail"]["last_audited_new"] is False
    assert record["pid"] == os.getpid()
    assert "control_file" in record


def test_set_layer_stays_silent_when_the_audit_agrees(diag_dir, tmp_path,
                                                      monkeypatch):
    from api_server import controls
    _controls_env(tmp_path, monkeypatch, audit_new=True)
    assert controls.set_layer("whale", False)["ok"] is True
    assert _records(diag_dir, "layer_unaudited_change") == []


def test_set_layer_stays_silent_with_no_audit_history(diag_dir, tmp_path,
                                                      monkeypatch):
    # A fresh DB has no audit rows: nothing to contradict, nothing captured.
    from api_server import controls
    _controls_env(tmp_path, monkeypatch, audit_new=None)
    assert controls.set_layer("whale", False)["ok"] is True
    assert _records(diag_dir, "layer_unaudited_change") == []


# --- Condition 2: engine reads ON, funnel reads OFF --------------------------

def test_bridge_captures_the_flag_mismatch(diag_dir):
    from python_bridge import server
    server._capture_flag_mismatch(
        "/discovery/due",
        {"asset_class": "crypto", "engine_reads_enabled": True},
        {"enabled": False, "due": False,
         "reason": "discovery.discovery_enabled is false"})
    records = _records(diag_dir, "discovery_flag_mismatch")
    assert len(records) == 1
    record = json.loads(open(records[0]).read())
    # The funnel case must carry the bridge's own fd count (the exhaustion
    # hypothesis) plus the standard pid, start time, and control file bytes.
    assert "fd_count" in record
    assert record["detail"]["endpoint"] == "/discovery/due"
    assert record["detail"]["response"]["enabled"] is False


def test_bridge_run_once_disabled_status_also_captures(diag_dir):
    from python_bridge import server
    server._capture_flag_mismatch(
        "/discovery/run_once",
        {"asset_class": "crypto", "engine_reads_enabled": True},
        {"status": "disabled",
         "reason": "discovery.discovery_enabled is false"})
    assert len(_records(diag_dir, "discovery_flag_mismatch")) == 1


def test_no_capture_without_the_engine_hint(diag_dir):
    # A CLI or test calling the endpoint with the flag off is a legitimate
    # read, not a mismatch: only the engine's own ON-claim makes it one.
    from python_bridge import server
    server._capture_flag_mismatch(
        "/discovery/due", {"asset_class": "crypto"},
        {"enabled": False, "due": False})
    assert _records(diag_dir, "discovery_flag_mismatch") == []


def test_no_capture_when_both_sides_read_on(diag_dir):
    from python_bridge import server
    server._capture_flag_mismatch(
        "/discovery/due",
        {"asset_class": "crypto", "engine_reads_enabled": True},
        {"enabled": True, "due": False, "reason": "not due"})
    assert _records(diag_dir, "discovery_flag_mismatch") == []


# --- fd telemetry in the bridge health payload -------------------------------

def _pin_capabilities(monkeypatch, server):
    monkeypatch.setattr(server, "_fresh_file_check", lambda: "ok")
    monkeypatch.setattr(server, "_fresh_socket_check", lambda: "ok")
    monkeypatch.setattr(server, "_quote_capability", lambda: "ok")


def test_health_reports_fd_count_and_threshold(monkeypatch):
    from python_bridge import server
    _pin_capabilities(monkeypatch, server)
    payload = server.health_payload()
    assert isinstance(payload["fd_count"], int)
    assert payload["fd_warn_threshold"] > 0
    assert "fd_headroom" in payload["checks"]
    assert payload["status"] == "ok"


def test_health_degrades_when_fd_count_crosses_the_threshold(monkeypatch):
    from python_bridge import server
    _pin_capabilities(monkeypatch, server)
    monkeypatch.setattr(server, "_fd_warn_threshold", lambda: 1)
    payload = server.health_payload()
    assert payload["status"] == "degraded"
    assert "fd_headroom" in payload["degraded"]
    assert "threshold 1" in payload["checks"]["fd_headroom"]


def test_fd_threshold_auto_derives_from_rlimit(monkeypatch):
    # Auto keys off the healthy baseline, not the limit: min(256, soft // 2).
    # The old 80%-of-limit rule read ok at 410 open fds on 2026-07-19 while
    # the feed had already substituted.
    from python_bridge import server
    import resource
    monkeypatch.setattr(server, "_bridge_cfg", lambda: {})
    soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    assert server._fd_warn_threshold() == max(64, min(256, int(soft) // 2))


def test_fd_threshold_auto_never_exceeds_256(monkeypatch):
    # A raised soft limit (the Task-5 defence in depth) must not drag the
    # alarm up with it: at soft 65536 the auto threshold stays 256.
    from python_bridge import server
    import resource
    monkeypatch.setattr(server, "_bridge_cfg", lambda: {})
    monkeypatch.setattr(resource, "getrlimit", lambda which: (65536, 524288))
    assert server._fd_warn_threshold() == 256


def test_fd_threshold_honors_explicit_config(monkeypatch):
    from python_bridge import server
    monkeypatch.setattr(server, "_bridge_cfg",
                        lambda: {"fd_warn_threshold": 123})
    assert server._fd_warn_threshold() == 123


# --- fd trend: a rising floor is degraded before any absolute threshold ------

def _seed_trend(monkeypatch, server, samples, window=3600, growth=12):
    monkeypatch.setattr(server, "_bridge_cfg",
                        lambda: {"fd_trend_window_seconds": window,
                                 "fd_trend_growth": growth})
    monkeypatch.setattr(server, "_FD_SAMPLES", list(samples))


def test_fd_trend_reads_ok_while_collecting(monkeypatch):
    from python_bridge import server
    _seed_trend(monkeypatch, server, [(0.0, 30)])
    assert server._fd_trend_check(now=3600.0).startswith("ok")


def test_fd_trend_flags_a_rising_floor(monkeypatch):
    # The leak signature: the MINIMUM climbs. 30/hour, the measured 2026-07-19
    # rate, must read degraded within the hour window.
    from python_bridge import server
    samples = [(t, 30 + int(t / 120)) for t in range(0, 3601, 180)]
    _seed_trend(monkeypatch, server, samples)
    result = server._fd_trend_check(now=3600.0)
    assert result.startswith("fail")
    assert "leak signature" in result


def test_fd_trend_ignores_a_load_burst(monkeypatch):
    # Honest load raises the ceiling and falls back; the floor stays put. A
    # burst to 90 fds in the newer half must NOT read as a leak.
    from python_bridge import server
    samples = ([(t, 30) for t in range(0, 1800, 180)]
               + [(1980.0, 90), (2160.0, 30), (2600.0, 88), (3000.0, 30)])
    _seed_trend(monkeypatch, server, samples)
    assert server._fd_trend_check(now=3600.0).startswith("ok")


def test_fd_trend_degrades_health(monkeypatch):
    from python_bridge import server
    _pin_capabilities(monkeypatch, server)
    monkeypatch.setattr(server, "_fd_trend_check",
                        lambda now=None: "fail (fd floor rose 25 in 3600s "
                                         "window, threshold 20: leak signature)")
    payload = server.health_payload()
    assert payload["status"] == "degraded"
    assert "fd_trend" in payload["degraded"]


def test_fd_sample_prunes_outside_the_window(monkeypatch):
    from python_bridge import server
    monkeypatch.setattr(server, "_bridge_cfg",
                        lambda: {"fd_trend_window_seconds": 600})
    monkeypatch.setattr(server, "_FD_SAMPLES", [(0.0, 30), (500.0, 31)])
    monkeypatch.setattr(server, "_fd_count", lambda: 32)
    server._fd_sample(now=700.0)
    assert server._FD_SAMPLES == [(500.0, 31), (700.0, 32)]


# --- soft fd limit raise: defence in depth, never the fix --------------------

def test_soft_limit_raised_toward_target(monkeypatch):
    from python_bridge import server
    import resource
    calls = []
    monkeypatch.setattr(resource, "getrlimit", lambda which: (1024, 524288))
    monkeypatch.setattr(resource, "setrlimit",
                        lambda which, pair: calls.append(pair))
    msg = server._raise_fd_soft_limit()
    assert calls == [(65536, 524288)]
    assert "1024 -> 65536" in msg


def test_soft_limit_bounded_by_hard(monkeypatch):
    from python_bridge import server
    import resource
    calls = []
    monkeypatch.setattr(resource, "getrlimit", lambda which: (1024, 2048))
    monkeypatch.setattr(resource, "setrlimit",
                        lambda which, pair: calls.append(pair))
    server._raise_fd_soft_limit()
    assert calls == [(2048, 2048)]


def test_soft_limit_never_lowered(monkeypatch):
    from python_bridge import server
    import resource
    calls = []
    monkeypatch.setattr(resource, "getrlimit", lambda which: (100000, 524288))
    monkeypatch.setattr(resource, "setrlimit",
                        lambda which, pair: calls.append(pair))
    msg = server._raise_fd_soft_limit()
    assert calls == []
    assert "already" in msg

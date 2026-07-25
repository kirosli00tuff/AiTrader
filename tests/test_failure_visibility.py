"""NO FAILURE MAY LEAVE NO TRACE, AND NO REPORT MAY NAME A CAUSE IT DID NOT MEASURE.

Guards the 2026-07-25 fixes:

  * every supervised process's output reaches a stamped, rotating file
    (`ops.logpipe`, `api_server.stack.spawn(log_name=...)`),
  * a slow funnel reads as a timeout, never as "bridge unreachable",
  * onboarding runs on the BLOCK path, because it reads the database and never
    needed the HTTP response,
  * the pass completion event reaches the journal,
  * a transient provider failure is retried exactly once and a permanent one is
    not retried at all,
  * an errored verdict persists distinctly from a considered abstention,
  * and the composition math is byte-identical under the new accounting.

Everything binds loopback ephemeral ports and writes only to tmp_path.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(REPO, "build", "mal_engine")
SCHEMA = os.path.join(REPO, "storage", "schema.sql")


# --------------------------------------------------------------------------
# Task 0: process output is captured, stamped, and rotated
# --------------------------------------------------------------------------

def test_logpipe_stamps_every_line_and_marks_the_boundaries(tmp_path,
                                                            monkeypatch):
    from ops import logpipe
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path))
    written = logpipe.pump("demo", stream=io.BytesIO(b"first\nsecond\n"))
    assert written == 2
    text = (tmp_path / "demo.log").read_text()
    assert "first" in text and "second" in text
    for line in text.strip().splitlines():
        # Every line, including the open/close markers, carries its own time.
        assert line[:20].endswith("Z"), f"unstamped line: {line!r}"
        assert line[4] == "-" and line[10] == "T"
    assert "log opened" in text and "stream closed" in text


def test_logpipe_rotates_and_keeps_bounded_generations(tmp_path, monkeypatch):
    from ops import logpipe
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path))
    payload = b"".join(b"x" * 200 + b"\n" for _ in range(200))
    logpipe.pump("chatty", stream=io.BytesIO(payload), max_bytes=4096,
                 generations=2)
    assert (tmp_path / "chatty.log").exists()
    assert (tmp_path / "chatty.log.1").exists(), "the log rotated"
    assert not (tmp_path / "chatty.log.3").exists(), "generations are bounded"
    live = (tmp_path / "chatty.log").stat().st_size
    assert live < len(payload), "the live file is smaller than all output"


def test_spawn_with_log_name_captures_a_child_that_writes_to_stderr(
        tmp_path, monkeypatch):
    """The backend died and left nothing. This is the assertion that fails if
    that regresses: a child's stderr must land on disk without the parent."""
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path))
    from api_server import stack
    monkeypatch.setattr(stack, "run_dir", lambda: str(tmp_path))
    proc = stack.spawn(
        [sys.executable, "-c",
         "import sys; sys.stderr.write('boom: the backend died\\n')"],
        env={"MAL_RUN_DIR": str(tmp_path)}, log_name="victim")
    proc.wait(timeout=30)
    log = tmp_path / "victim.log"
    for _ in range(120):  # the logger is its own process, give it a moment
        if log.exists() and "boom" in log.read_text():
            break
        time.sleep(0.05)
    text = log.read_text()
    assert "boom: the backend died" in text, "stderr reached the log"
    assert text.strip().splitlines()[0][:20].endswith("Z"), "and it is stamped"


def test_watchdog_captures_a_down_component_before_stopping_it(
        tmp_path, monkeypatch):
    """A component that dies must leave enough behind to explain itself."""
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path))
    from ops import logpipe, watchdog
    logpipe.pump("backend", stream=io.BytesIO(b"Traceback: it fell over\n"))
    captured: list = []
    monkeypatch.setattr("ops.evidence.capture",
                        lambda cond, detail=None, **kw: (
                            captured.append((cond, detail)) or "x"))
    monkeypatch.setattr(watchdog.stack, "read_pids", lambda: {"backend": 4242})
    snap, note = watchdog.capture_before_restart(
        {"engine": True, "bridge": True, "backend": False})
    assert captured, "a down component is captured"
    cond, detail = captured[0]
    assert cond == "component_failure-backend"
    comp = detail["component"]
    assert comp["component"] == "backend"
    assert comp["pid"] == 4242, "its pid is recorded"
    assert "it fell over" in comp["log_tail"], "its last words are recorded"
    assert "final_health" in comp or "final_health_error" in comp, \
        "a final health answer was attempted either way"
    assert "backend" in note


def test_capture_before_restart_is_quiet_when_everything_is_healthy(monkeypatch):
    from ops import watchdog
    calls: list = []
    monkeypatch.setattr("ops.evidence.capture",
                        lambda *a, **k: calls.append(a) or "x")
    snap, note = watchdog.capture_before_restart(
        {"engine": True, "bridge": True, "backend": True})
    assert (snap, note) == (None, "") and not calls


# --------------------------------------------------------------------------
# Task 3: provider retry, bounded and budget-respecting
# --------------------------------------------------------------------------

def _provider(monkeypatch, timeout=30.0):
    from llm_consensus.providers import OpenAIProvider
    p = OpenAIProvider(name="llm_primary", model_id="gpt-5.5", timeout=timeout)
    monkeypatch.setattr(p, "_api_key", lambda: "test-key")
    monkeypatch.setattr(p, "_request", lambda state, key: ("http://x", {}, {}))
    monkeypatch.setattr(p, "_text_from_response", json.dumps)
    return p


def test_a_transient_failure_is_retried_exactly_once_and_then_succeeds(
        monkeypatch):
    from llm_consensus import http_json
    calls = {"n": 0}

    def flaky(url, headers, payload, timeout=30.0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise http_json.LLMHTTPError("HTTP 503: high demand")
        return {"direction": "long", "confidence": 0.7, "edge": 0.02}

    monkeypatch.setattr(http_json, "post_json", flaky)
    monkeypatch.setattr("llm_consensus.providers.PROVIDER_RETRY_BACKOFF_SECONDS",
                        0.01)
    p = _provider(monkeypatch)
    v = p.score({"symbol": "BTC/USD"})
    assert calls["n"] == 2, "exactly one retry"
    assert v.source == "real", "the retry produced a real read"
    assert v.extra.get("attempts") == 2, "the retry is recorded, not just logged"


def test_a_transient_failure_that_never_clears_is_retried_once_not_forever(
        monkeypatch):
    from llm_consensus import http_json
    from llm_consensus.providers import MAX_PROVIDER_ATTEMPTS
    calls = {"n": 0}

    def always_503(url, headers, payload, timeout=30.0):
        calls["n"] += 1
        raise http_json.LLMHTTPError("HTTP 503: high demand")

    monkeypatch.setattr(http_json, "post_json", always_503)
    monkeypatch.setattr("llm_consensus.providers.PROVIDER_RETRY_BACKOFF_SECONDS",
                        0.01)
    p = _provider(monkeypatch)
    v = p.score({"symbol": "BTC/USD"})
    assert calls["n"] == MAX_PROVIDER_ATTEMPTS == 2, "bounded, never a loop"
    assert v.source == "error" and v.bias == 0.0


def test_a_permanent_failure_is_not_retried_at_all(monkeypatch):
    from llm_consensus import http_json
    calls = {"n": 0}

    def unauthorized(url, headers, payload, timeout=30.0):
        calls["n"] += 1
        raise http_json.LLMHTTPError("HTTP 401: invalid api key")

    monkeypatch.setattr(http_json, "post_json", unauthorized)
    p = _provider(monkeypatch)
    v = p.score({"symbol": "BTC/USD"})
    assert calls["n"] == 1, "an auth failure is a certain second failure"
    assert v.source == "error"


def test_the_retry_never_extends_the_round_past_the_provider_budget(monkeypatch):
    """Two full-length attempts plus a backoff must not outlive the budget."""
    from llm_consensus import http_json
    calls = {"n": 0}

    def slow_then_fail(url, headers, payload, timeout=30.0):
        calls["n"] += 1
        time.sleep(0.25)
        raise http_json.LLMHTTPError("HTTP 503: high demand")

    monkeypatch.setattr(http_json, "post_json", slow_then_fail)
    monkeypatch.setattr("llm_consensus.providers.PROVIDER_RETRY_BACKOFF_SECONDS",
                        0.05)
    monkeypatch.setattr(
        "llm_consensus.providers.MIN_PROVIDER_RETRY_BUDGET_SECONDS", 0.05)
    p = _provider(monkeypatch, timeout=0.4)
    started = time.monotonic()
    v = p.score({"symbol": "BTC/USD"})
    elapsed = time.monotonic() - started
    assert v.source == "error"
    assert elapsed < 1.2, f"the round stayed inside its budget ({elapsed:.2f}s)"
    assert calls["n"] <= 2


def test_the_classifier_separates_transient_from_permanent():
    from llm_consensus.providers import _is_transient
    for transient in ("HTTP 503: high demand", "HTTP 429: rate limited",
                      "HTTP 500: oops", "HTTP 504: gateway timeout",
                      "request failed: Read timed out. (read timeout=30.0)",
                      "request failed: Connection reset by peer"):
        assert _is_transient(Exception(transient)), transient
    for permanent in ("HTTP 401: invalid key", "HTTP 403: forbidden",
                      "HTTP 404: model not found", "HTTP 400: bad request"):
        assert not _is_transient(Exception(permanent)), permanent


# --------------------------------------------------------------------------
# Task 3: an error is not an abstention
# --------------------------------------------------------------------------

def _verdicts():
    from llm_consensus.verdicts import ModelVerdict, flat_verdict
    return [
        ModelVerdict(model="llm_primary", bias=0.6, confidence=0.6, edge=0.02,
                     verdict="strong_buy", source="real", model_id="gpt-5.5"),
        ModelVerdict(model="llm_secondary", bias=0.0, confidence=0.55, edge=0.0,
                     verdict="hold", source="real", model_id="claude-opus-4-8",
                     rationale="considered, and held"),
        flat_verdict("llm_tertiary", "flat: Gemini call error",
                     source="error", model_id="gemini-3.1-pro-preview"),
    ]


def test_an_error_is_counted_separately_from_a_considered_hold():
    from llm_consensus.consensus import consensus
    from llm_consensus.gate import AlwaysProceedGate

    class P:
        def __init__(self, v):
            self.v, self.name, self.weight = v, v.model, 0.2

        def score(self, state):
            return self.v

    provs = [P(v) for v in _verdicts()]
    r = consensus({"symbol": "BTC/USD", "price": 1.0}, providers=provs,
                  gate=AlwaysProceedGate())
    assert r.directional_count == 1
    assert r.abstentions == 1, "only the provider that ANSWERED and held"
    assert r.errors == 1, "the failed call is its own count"
    d = r.to_dict()
    assert d["errors"] == 1 and d["abstentions"] == 1
    assert d["responded_count"] == 2, "two providers actually answered"


def test_composition_math_is_unchanged_by_the_error_split():
    """The deciding numbers derive from directional voters only, and an errored
    verdict was never directional. Splitting the count must move nothing."""
    from llm_consensus.verdicts import bias_to_verdict, is_error
    vs = _verdicts()
    ws = [0.4, 0.35, 0.25]

    def compose(split):
        directional = [(v, w) for v, w in zip(vs, ws) if abs(v.bias) > 1e-9]
        errors = sum(1 for v in vs if is_error(v)) if split else 0
        abst = len(vs) - len(directional) - errors
        dw = sum(w for _, w in directional) or 1.0
        bias = sum(v.bias * w for v, w in directional) / dw
        conf = sum(v.confidence * w for v, w in directional) / dw
        edge = sum(v.edge * w for v, w in directional) / dw
        net = 1 if bias > 0 else (-1 if bias < 0 else 0)
        agree = sum(1 for v, _ in directional
                    if net and (1 if v.bias > 0 else -1) == net)
        return (bias, conf, edge, bias_to_verdict(bias), agree,
                len(directional)), abst

    old_deciding, old_abst = compose(False)
    new_deciding, new_abst = compose(True)
    assert old_deciding == new_deciding, "not one deciding value moves"
    assert new_abst == old_abst - 1, "only the abstention count moves"


def test_an_errored_verdict_persists_distinctly_from_an_abstention(tmp_path):
    from llm_consensus.persist import load_evaluation, record_evaluation
    from llm_consensus.verdicts import ConsensusResult

    db = str(tmp_path / "council.db")
    result = ConsensusResult(
        bias=0.6, confidence=0.6, edge=0.02, verdict="strong_buy",
        agreement_count=1, per_model=_verdicts(), directional_count=1,
        abstentions=1, errors=1)
    eid = record_evaluation(db, {"symbol": "BTC/USD", "price": 1.0}, result)
    assert eid

    conn = sqlite3.connect(db)
    rows = dict(conn.execute(
        "SELECT slot, abstained || '/' || errored FROM council_eval_provider "
        "WHERE eval_id=?", (eid,)).fetchall())
    assert rows["llm_secondary"] == "1/0", "a considered hold abstained"
    assert rows["llm_tertiary"] == "0/1", "a failed call did NOT abstain"
    assert rows["llm_primary"] == "0/0", "a directional read is neither"
    assert conn.execute("SELECT errors FROM council_eval WHERE id=?",
                        (eid,)).fetchone()[0] == 1
    conn.close()

    loaded = load_evaluation(db, eid)
    by_slot = {p["slot"]: p for p in loaded["providers"]}
    assert by_slot["llm_tertiary"]["errored"] is True
    assert by_slot["llm_tertiary"]["abstained"] is False
    assert by_slot["llm_secondary"]["abstained"] is True
    assert by_slot["llm_secondary"]["errored"] is False
    assert loaded["errors"] == 1 and loaded["responded_count"] == 2


def test_a_pre_migration_row_still_reads_its_errors_from_source(tmp_path):
    """History has no `errored` column. It must not start claiming its failed
    calls were considered reads."""
    from llm_consensus.persist import load_evaluation
    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """CREATE TABLE council_eval (id INTEGER PRIMARY KEY, ts TEXT, symbol
           TEXT, mode TEXT, prompt_version TEXT, state_json TEXT, system_prompt
           TEXT, user_prompt TEXT, bias REAL, confidence REAL, edge REAL,
           verdict TEXT, agreement_count INT, directional_count INT,
           abstentions INT, gate_json TEXT);
           CREATE TABLE council_eval_provider (id INTEGER PRIMARY KEY, eval_id
           INT, slot TEXT, model_id TEXT, source TEXT, direction TEXT, bias
           REAL, confidence REAL, edge REAL, abstained INT, rationale TEXT,
           extra_json TEXT);""")
    conn.execute(
        "INSERT INTO council_eval VALUES (1,'t','BTC/USD','short_term','v1',"
        "'{}','s','u',0.6,0.6,0.02,'strong_buy',2,2,1,NULL)")
    conn.execute(
        "INSERT INTO council_eval_provider VALUES (1,1,'llm_tertiary','gemini',"
        "'error','flat',0.0,0.0,0.0,1,'flat: Gemini call error','{}')")
    conn.commit()
    conn.close()
    loaded = load_evaluation(db, 1)
    p = loaded["providers"][0]
    assert p["errored"] is True, "derived from source when the column is absent"
    assert p["abstained"] is False, "and it stops reading as an abstention"


# --------------------------------------------------------------------------
# Tasks 1 and 2: the engine, end to end, against a deliberately slow bridge
# --------------------------------------------------------------------------

class _SlowFunnelBridge:
    """Answers /discovery/due instantly, then stalls /discovery/run_once past
    the engine's deadline, exactly like a real 90-second funnel. It writes the
    watchlist row and the pass row FIRST, which is what a real pass does before
    it answers."""

    def __init__(self, db_path: str, stall_seconds: float):
        self.db_path, self.stall = db_path, stall_seconds
        self.run_once_calls = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                body = json.dumps(obj).encode()
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception:
                    pass

            def do_GET(self):
                self._json({"status": "ok"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                if n:
                    self.rfile.read(n)
                if self.path == "/discovery/due":
                    return self._json({"enabled": True, "due": True,
                                       "reason": "test"})
                if self.path == "/discovery/run_once":
                    outer.run_once_calls += 1
                    outer._record_pass()
                    time.sleep(outer.stall)   # the funnel is still working
                    return self._json({"status": "ok", "universe_count": 10,
                                       "finalists": 5, "survivors": 2,
                                       "evaluated": 2, "council_calls": 1,
                                       "est_cost_usd": 0.05})
                if self.path == "/status":
                    return self._json({"council_real": True, "dnn_real": True,
                                       "whale_real": True})
                return self._json({"bias": 0.0, "confidence": 0.0, "edge": 0.0})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def _record_pass(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (symbol, asset_class, "
                "added_ts, updated_ts, source, reason, sleeve_target, score, "
                "status) VALUES ('LATE/USD','crypto','2026-07-25T00:00:00Z',"
                "'2026-07-25T00:00:00Z','discovery','test add','quant_core',"
                "0.7,'active')")
            conn.execute(
                "INSERT INTO discovery_pass (ts, asset_class, universe_count, "
                "finalists_count, survivors_count, evaluated_count, "
                "council_calls, gate_calls, est_cost_usd, budget_remaining, "
                "status, reason) VALUES ('2026-07-25T00:00:00Z','crypto',10,5,"
                "2,2,1,2,0.05,9,'ok','')")
            conn.commit()
        finally:
            conn.close()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _events(db, kind):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT ts, severity, message, COALESCE(payload_json,'') FROM "
            "events WHERE kind=? ORDER BY id", (kind,)).fetchall()
    finally:
        conn.close()


@pytest.mark.skipif(not os.path.exists(ENGINE), reason="engine not built")
def test_a_slow_funnel_is_a_timeout_and_still_onboards_and_journals(tmp_path):
    """THE 2026-07-25 REGRESSION GUARD, end to end.

    A funnel that outruns the engine's deadline must:
      1. report a TIMEOUT, naming the deadline, never "bridge unreachable",
      2. still onboard the watchlist member the pass added (it is in the
         database and never needed the response),
      3. still journal the pass completion, read back from discovery_pass.

    Mutation: revert the onboard call on the block path and 2 fails; revert
    journal_pass_completion and 3 fails; revert the typed result and 1 fails.
    """
    db = str(tmp_path / "engine.db")
    subprocess.run([ENGINE, "--db", db, "--schema", SCHEMA, "--iterations", "1"],
                   cwd=REPO, capture_output=True, timeout=180)

    bridge = _SlowFunnelBridge(db, stall_seconds=6.0)
    cfg = tmp_path / "cfg.yaml"
    base = open(os.path.join(REPO, "config", "default_config.yaml")).read()
    assert "engine_discovery_call_timeout_ms: 300000" in base
    # Shrink the whole timeout ladder, not just the discovery rung. The config
    # validator now REFUSES a discovery deadline tighter than one council round
    # trip, and a council deadline tighter than one provider call, which is the
    # invariant that stops the 2026-07-25 defect being reintroduced by a config
    # edit. Honouring it here is the point, not an inconvenience.
    base = base.replace("provider_timeout_seconds: 30",
                        "provider_timeout_seconds: 1")
    base = base.replace("engine_council_call_timeout_ms: 60000",
                        "engine_council_call_timeout_ms: 1200")
    base = base.replace("engine_discovery_call_timeout_ms: 300000",
                        "engine_discovery_call_timeout_ms: 1500")
    base = base.replace("discovery_enabled: false", "discovery_enabled: true")
    cfg.write_text(base)
    # CONTINUOUS, bounded by wall clock. The finite --iterations path runs its
    # loop without sleeping, so it exits milliseconds after launching the pass
    # and never lives long enough to collect it. The defect under test only
    # appears when the engine is still running when the deadline expires.
    #
    # MAL_CONTROL_DIR points at tmp_path so the run never reads or writes the
    # operator's real .control directory.
    ctrl = tmp_path / "control"
    ctrl.mkdir()
    (ctrl / "controls.json").write_text(
        json.dumps({"discovery": {"discovery_enabled": True}}))
    proc = subprocess.Popen(
        # The DEFAULT feed mode on purpose. `synthetic_regimes` takes the
        # bar-stepping branch of Engine::run, which never calls run_iteration
        # and therefore never reaches consume_discovery.
        [ENGINE, "--db", db, "--config", str(cfg), "--schema", SCHEMA,
         "--continuous", "--interval-seconds", "1",
         "--bridge", f"127.0.0.1:{bridge.port}"],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={**os.environ, "MAL_CONTROL_DIR": str(ctrl)})
    try:
        time.sleep(14)   # launch at ~0s, deadline at ~1.5s, collect next tick
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        bridge.stop()

    assert bridge.run_once_calls >= 1, "the engine actually launched a pass"

    blocked = _events(db, "discovery_blocked")
    assert blocked, "a pass that outran the deadline is reported"
    msg = " ".join(b[2] for b in blocked)
    payload = " ".join(b[3] for b in blocked)
    assert "unreachable" not in msg, (
        "a slow funnel is NOT unreachable, that was the 44-time lie: " + msg)
    assert "deadline" in msg, "the report names the deadline it missed: " + msg
    assert "timed_out" in payload, "and carries the measured label: " + payload

    onboard = _events(db, "discovery_onboard")
    assert any("LATE/USD" in o[2] for o in onboard), (
        "the member the pass added is onboarded IN SESSION, on the block path")

    passes = _events(db, "discovery_pass")
    assert passes, "the completion reaches the journal even with no response"
    assert "transport" in passes[0][3]

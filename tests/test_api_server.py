"""Tests for the read-only FastAPI backend (api_server).

Data comes from a temporary SQLite database built from the real schema. No real
network or socket: the bridge probe is stubbed. Credential writes go to a
temporary keystore, never the real one and never an operational table.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO_ROOT, "storage", "schema.sql")
MASK = "•" * 8  # eight bullet dots, as the credential store masks secrets

_SEED = """
INSERT INTO venue_state(venue, mode, live_enabled, credentials_connected,
    kill_switch_tripped, updated_ts) VALUES
  ('alpaca','paper',0,1,0,'2026-07-06T00:00:00Z'),
  ('ibkr','recommendation_only',0,0,0,'2026-07-06T00:00:00Z');

INSERT INTO account_balances(ts, venue, equity, cash, realized_pnl,
    unrealized_pnl, drawdown_pct) VALUES
  ('2026-07-06T00:00:00Z','AGGREGATE',100000,90000,0,0,0.0),
  ('2026-07-06T01:00:00Z','AGGREGATE',100120,90000,120,0,-0.1),
  ('2026-07-06T02:00:00Z','AGGREGATE',100085,90000,85,0,-0.2),
  ('2026-07-06T02:00:00Z','alpaca',100085,90000,85,0,-0.2);

INSERT INTO trades(ts, venue, symbol, side, qty, price, notional, mode, pnl,
    outcome, combined_conf, combined_edge) VALUES
  ('2026-07-06T01:00:00Z','alpaca','BTC/USD','buy',0.01,60000,600,'paper',12.5,'win',0.7,0.03),
  ('2026-07-06T01:30:00Z','alpaca','ETH/USD','buy',0.1,3000,300,'paper',-4.0,'loss',0.66,0.02),
  ('2026-07-06T02:00:00Z','alpaca','SPY','buy',1,540,540,'paper',NULL,'open',0.68,0.02);

INSERT INTO positions(venue, symbol, side, qty, avg_price, notional,
    opened_ts, unrealized_pnl) VALUES
  ('alpaca','SPY','buy',1,540,540,'2026-07-06T02:00:00Z',1.25);

INSERT INTO signals(ts, venue, symbol, factor, bias, confidence, edge) VALUES
  ('2026-07-06T02:00:00Z','alpaca','BTC/USD','rule_based',0.4,0.7,0.03),
  ('2026-07-06T02:00:00Z','alpaca','BTC/USD','dnn_advisory',0.2,0.6,0.02);

INSERT INTO regime_state(symbol, regime, adx, rvol, updated_ts) VALUES
  ('BTC/USD','trending',31.2,0.04,'2026-07-06T02:00:00Z');

INSERT INTO model_outputs(ts, model, verdict, confidence, edge, weight) VALUES
  ('2026-07-06T02:00:00Z','gpt-5.5','buy',0.7,0.03,0.27),
  ('2026-07-06T02:00:00Z','claude-opus-4-8','buy',0.68,0.02,0.18);

INSERT INTO whale_activity(ts, source, delayed, entity, symbol, direction,
    value_usd) VALUES
  ('2026-07-06T01:00:00Z','clankapp',0,'wallet-x','BTC/USD','inflow',1200000);

INSERT INTO whale_signal_history(ts, symbol, whale_bias, whale_confidence,
    whale_flow_direction, whale_regime_label, trade_outcome) VALUES
  ('2026-07-06T01:00:00Z','BTC/USD',0.3,0.5,'inflow','accumulation','win');

INSERT INTO approval_state(id, live_enabled, manual_confirmation,
    last_checked_ts, readiness_json) VALUES
  (1,0,0,'2026-07-06T00:00:00Z','{"ready": false}');

INSERT INTO events(ts, kind, venue, symbol, severity, message) VALUES
  ('2026-07-06T02:00:00Z','trade','alpaca','BTC/USD','info','opened BTC/USD');
"""


def _seed(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    with open(SCHEMA) as fh:
        conn.executescript(fh.read())
    conn.executescript(_SEED)
    conn.commit()
    # Convert to a rollback journal so a read-only open needs no -wal/-shm and
    # the file stays byte-stable across reads (checks the no-write invariant).
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.commit()
    conn.close()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = tmp_path / "op.db"
    _seed(str(db))
    monkeypatch.setenv("MAL_DB_PATH", str(db))
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "control"))
    kdir = tmp_path / "keystore"
    kdir.mkdir()
    import account_manager.credentials as creds
    monkeypatch.setattr(creds, "KEYSTORE_DIR", str(kdir))
    monkeypatch.setattr(creds, "_KEY_PATH", str(kdir / "secret.key"))
    monkeypatch.setattr(creds, "_STORE_PATH", str(kdir / "credentials.sqlite"))
    from api_server import store
    monkeypatch.setattr(store, "bridge_health",
                        lambda: {"reachable": False,
                                 "url": "http://127.0.0.1:8765",
                                 "status": None})
    return {"db": str(db), "keystore": str(kdir),
            "control": str(tmp_path / "control")}


@pytest.fixture()
def client(env):
    from api_server.app import app
    return TestClient(app)


# --- Bind address -----------------------------------------------------------

def test_bind_host_is_loopback():
    from api_server.app import HOST
    assert HOST == "127.0.0.1"
    assert ipaddress.ip_address(HOST).is_loopback


# --- Endpoint shapes --------------------------------------------------------

def test_health_shape(client):
    j = client.get("/health").json()
    assert j["status"] == "ok"
    assert j["db_present"] is True
    assert "engine" in j and "bridge" in j
    assert j["bridge"]["reachable"] is False
    assert j["engine"]["kill_switch_tripped"] is False


def test_account_shape(client):
    j = client.get("/account?mode=paper").json()
    assert j["mode"] == "paper"
    for k in ("equity", "cash", "realized_pnl", "unrealized_pnl",
              "drawdown_pct", "venues"):
        assert k in j
    assert j["equity"] > 0


def test_account_live_is_zeroed(client):
    j = client.get("/account?mode=live").json()
    assert j["mode"] == "live"
    assert j["equity"] == 0
    assert j["venues"] == []


def test_positions_shape(client):
    j = client.get("/positions?mode=paper").json()
    assert j["mode"] == "paper"
    assert any(p["symbol"] == "SPY" for p in j["positions"])


def test_orders_shape(client):
    j = client.get("/orders?mode=paper").json()
    assert j["mode"] == "paper"
    assert len(j["orders"]) == 3


def test_trades_closed_only(client):
    j = client.get("/trades?mode=paper").json()
    outcomes = {t["outcome"] for t in j["trades"]}
    assert outcomes <= {"win", "loss"}
    assert len(j["trades"]) == 2


def test_pnl_shape(client):
    j = client.get("/pnl?mode=paper").json()
    for k in ("equity_curve", "daily_pnl", "win_rate", "wins", "losses",
              "n_trades", "total_pnl", "max_drawdown_pct"):
        assert k in j
    assert j["win_rate"] == 50.0
    assert len(j["equity_curve"]) == 3


def test_signals_with_regime(client):
    j = client.get("/signals").json()
    assert "signals" in j and "regimes" in j
    btc = [s for s in j["signals"] if s["symbol"] == "BTC/USD"]
    assert btc and btc[0]["regime"] == "trending"


def test_council_shape(client):
    j = client.get("/council").json()
    assert j["models"]["llm_primary"] == "gpt-5.5"
    assert len(j["latest"]) == 2


def test_whale_shape(client):
    j = client.get("/whale").json()
    assert "activity" in j and "history" in j
    assert j["activity"][0]["source"] == "clankapp"


def test_risk_shape(client):
    j = client.get("/risk").json()
    assert "level1" in j and "kill_switch_enabled" in j
    assert "max_daily_loss_total_pct" in j["level1"]
    assert j["kill_switch_tripped"] is False


def test_venues_shape(client):
    venues = client.get("/venues").json()["venues"]
    names = {v["venue"] for v in venues}
    assert {"alpaca", "ibkr"}.issubset(names)
    ibkr = next(v for v in venues if v["venue"] == "ibkr")
    assert ibkr["live_enabled"] is False


def test_approval_four_mechanisms(client):
    j = client.get("/approval").json()
    assert len(j["mechanisms"]) == 4
    assert j["live_enabled"] is False
    assert j["all_passed"] is False
    keys = {m["key"] for m in j["mechanisms"]}
    assert keys == {"approval_gate", "credentials_connected",
                    "kill_switch", "live_enabled"}


# --- WebSocket --------------------------------------------------------------

def test_stream_snapshot(client):
    with client.websocket_connect("/stream") as ws:
        ws.send_text("paper")
        snap = ws.receive_json()
    for k in ("mode", "ts", "positions", "orders", "pnl", "events"):
        assert k in snap
    assert snap["mode"] == "paper"


# --- Credentials: masked read, encrypted write, never logged ----------------

def test_credentials_get_masks(client):
    creds = client.get("/credentials").json()["credentials"]
    assert any(c["name"] == "alpaca_paper_key" for c in creds)
    for c in creds:
        assert "value" not in c  # only masked status, never a value field


def test_credential_post_masks_and_never_echoes(client, capsys):
    fake_val = "unit-test-fake-value-do-not-log-0001"
    r = client.post("/credentials",
                    json={"name": "alpaca_paper_key", "value": fake_val})
    body = r.json()
    assert body["ok"] is True
    assert fake_val not in r.text
    assert body["status"]["masked"] == MASK
    assert body["status"]["configured"] is True

    got = client.get("/credentials").json()["credentials"]
    entry = next(c for c in got if c["name"] == "alpaca_paper_key")
    assert entry["masked"] == MASK
    assert fake_val not in str(got)

    out = capsys.readouterr()
    assert fake_val not in out.out
    assert fake_val not in out.err


def test_credential_post_unknown_name(client):
    r = client.post("/credentials", json={"name": "nope", "value": "x"})
    assert r.json()["ok"] is False


def test_credential_test_endpoint(client):
    r = client.post("/credentials/test?group=alpaca&mode=paper")
    assert "ok" in r.json()


# --- Kill switch: state read + halt request (control file only) -------------

def test_kill_get_reports_engine_state(client):
    j = client.get("/kill").json()
    assert j["engine_kill_switch_tripped"] is False
    assert j["request"]["requested"] is False


def test_kill_post_records_request_not_op_table(env, client):
    def digest():
        import hashlib
        with open(env["db"], "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    before = digest()
    r = client.post("/kill", json={"requested": True, "reason": "operator halt"})
    body = r.json()
    assert body["ok"] is True
    assert body["request"]["requested"] is True
    # request landed in the control dir, operational DB is byte-identical
    assert os.path.exists(os.path.join(env["control"], "kill_request.json"))
    assert digest() == before
    assert client.get("/kill").json()["request"]["reason"] == "operator halt"


def test_kill_request_file_shape_matches_engine_contract(env, client):
    """The control file must carry exactly the fields the C++ engine parses: a
    boolean `requested`, a `reason` string, and a `ts`. Mocked filesystem only
    (temp control dir); no real engine and no real halt."""
    import json as _json
    client.post("/kill", json={"requested": True, "reason": "halt now"})
    with open(os.path.join(env["control"], "kill_request.json")) as fh:
        rec = _json.load(fh)
    assert set(rec) == {"requested", "reason", "ts"}
    assert rec["requested"] is True
    assert rec["reason"] == "halt now"
    assert isinstance(rec["ts"], str) and rec["ts"]


# --- The backend never writes an operational table --------------------------

def test_no_operational_table_write(env, client):
    def digest() -> str:
        with open(env["db"], "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    before = digest()
    reads = ["/health", "/account?mode=paper", "/account?mode=live",
             "/positions?mode=paper", "/orders?mode=paper",
             "/trades?mode=paper", "/pnl?mode=paper", "/pnl?mode=live",
             "/signals", "/council", "/whale", "/risk", "/venues",
             "/approval", "/kill"]
    for path in reads:
        assert client.get(path).status_code == 200
    # A credential write must land in the keystore, not the operational DB.
    client.post("/credentials",
                json={"name": "alpaca_paper_key", "value": "zzz"})
    after = digest()
    assert before == after
    assert os.path.exists(os.path.join(env["keystore"], "credentials.sqlite"))

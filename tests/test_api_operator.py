"""The operator-experience read endpoints (2026-07-20).

Shape, read-only-ness, loopback bind, no key values, and the never-drop
contract of the WebSocket event delta. Temp DB from the real schema, bridge
stubbed, no network, nothing binds (TestClient is in-process).
"""
from __future__ import annotations

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO_ROOT, "storage", "schema.sql")

_SEED = """
INSERT INTO venue_state(venue, mode, live_enabled, credentials_connected,
    kill_switch_tripped, updated_ts) VALUES
  ('alpaca','paper',0,1,0,'2026-07-20T00:00:00Z');

INSERT INTO events(ts, kind, venue, symbol, severity, message, payload_json) VALUES
  ('2026-07-20T01:00:00Z','risk_block','alpaca','BTC/USD','info',
   'Native entry blocked: confidence below min_confidence_default',
   '{"reason":"confidence below min_confidence_default","tier":"council",
     "confidence":0.31,"min_confidence":0.65,"agreement":1,
     "required_agreement":2,"edge":0.024,"min_edge":0.02,"symbol":"BTC/USD"}'),
  ('2026-07-20T01:05:00Z','trade_entry','alpaca','ETH/USD','info',
   'Native entry momentum','{"factor":"momentum","regime":"trending",
     "stop":2900.5,"target":3400.1,"strength":0.4}'),
  ('2026-07-20T01:06:00Z','symbol_unavailable','alpaca','MANA/USD','warn',
   'SYMBOL UNAVAILABLE: MANA/USD has never received a real bar', '{}'),
  ('2026-07-20T01:07:00Z','continuous_start',NULL,NULL,'info',
   'Continuous paper loop started','{}');

INSERT INTO model_outputs(ts, model, verdict, confidence, edge, weight) VALUES
  ('2026-07-20T01:00:00Z','llm_primary','buy',0.62,0.03,0.27),
  ('2026-07-20T01:00:00Z','llm_secondary','hold',0.0,0.0,0.18),
  ('2026-07-20T01:00:00Z','dnn_advisory','hold',0.0,0.0,0.15);

INSERT INTO bars(venue, symbol, timeframe, timestamp, open, high, low, close,
    volume, source) VALUES
  ('alpaca','BTC/USD','5min','2026-07-20T00:50:00Z',100,105,99,104,10,'real_feed'),
  ('alpaca','BTC/USD','5min','2026-07-20T00:55:00Z',104,106,103,105,12,'real_feed'),
  ('alpaca','MANA/USD','5min','2026-07-20T00:55:00Z',1,1,1,1,1,'synthetic');

INSERT INTO positions(venue, symbol, side, qty, avg_price, notional,
    opened_ts, unrealized_pnl) VALUES
  ('alpaca','ETH/USD','buy',0.5,3000,1500,'2026-07-20T01:05:00Z',12.0);

-- A position with DURABLE exit-state columns (persisted at entry since
-- 2026-07-23): these win over any trade_entry payload.
INSERT INTO positions(venue, symbol, side, qty, avg_price, notional,
    opened_ts, unrealized_pnl, stop_price, target_price, time_stop_bars,
    factor, bars_held) VALUES
  ('alpaca','SOL/USD','buy',1.0,100,100,'2026-07-22T01:00:00Z',0.0,
   95.5,110.25,24,'reversion',3);

-- A stranded position the engine reported unmanageable at construction.
INSERT INTO positions(venue, symbol, side, qty, avg_price, notional,
    opened_ts, unrealized_pnl) VALUES
  ('polymarket','PRES-TEST','sell',10,0.5,5,'2026-06-30T00:00:00Z',0.0);
INSERT INTO events(ts, kind, venue, symbol, severity, message, payload_json) VALUES
  ('2026-07-23T00:00:00Z','position_unmanageable','polymarket','PRES-TEST',
   'critical','OPEN POSITION CANNOT BE MANAGED: PRES-TEST',
   '{"reason":"venue polymarket no longer exists in the system",
     "sleeve":"quant_core","opened_ts":"2026-06-30T00:00:00Z","qty":10.0}');

INSERT INTO watchlist(symbol, asset_class, added_ts, updated_ts, source,
    reason, sleeve_target, score, status) VALUES
  ('MANA/USD','crypto','2026-07-20T00:00:00Z','2026-07-20T00:00:00Z',
   'discovery','test','quant_core',0.5,'active');
"""

NEW_ROUTES = ("/activity", "/council/decisions", "/diagnostics/symbols",
              "/diagnostics/watchdog", "/positions/exits")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "op.db"
    conn = sqlite3.connect(db)
    with open(SCHEMA) as fh:
        conn.executescript(fh.read())
    # The provenance column lands via runtime migration in production
    # (storage.cpp / alpaca_source.ensure_bars_schema); mirror it here.
    try:
        conn.execute("ALTER TABLE bars ADD COLUMN source TEXT DEFAULT 'unknown'")
    except sqlite3.OperationalError:
        pass
    conn.executescript(_SEED)
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.commit()
    conn.close()
    monkeypatch.setenv("MAL_DB_PATH", str(db))
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "control"))
    from api_server import store
    monkeypatch.setattr(store, "bridge_health",
                        lambda: {"reachable": False, "url": "", "status": None})
    from api_server.app import app
    return TestClient(app)


def test_activity_shape_and_incremental_feed(client):
    r = client.get("/activity?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["latest_id"] > 0
    kinds = [e["kind"] for e in body["events"]]
    assert "risk_block" in kinds and "continuous_start" in kinds
    block = next(e for e in body["events"] if e["kind"] == "risk_block")
    # The payload is parsed and carries the real numbers.
    assert block["payload"]["min_confidence"] == 0.65
    # Incremental: since_id returns only newer rows, ascending.
    first_id = body["events"][0]["id"]
    inc = client.get(f"/activity?since_id={first_id}").json()
    assert all(e["id"] > first_id for e in inc["events"])
    ids = [e["id"] for e in inc["events"]]
    assert ids == sorted(ids)


def test_council_decisions_shape_and_no_key_values(client):
    r = client.get("/council/decisions?limit=10")
    assert r.status_code == 200
    body = r.json()
    d = next(x for x in body["decisions"] if x["kind"] == "risk_block")
    assert d["numbers"]["required_agreement"] == 2
    models = [p["model"] for p in d["providers"]]
    assert "llm_primary" in models and "dnn_advisory" in models
    assert isinstance(body["dnn_benched"], bool)
    assert "council_min_confidence" in body["floors"]
    # No credential-shaped value or env-var name in the payload, ever.
    text = r.text
    assert "sk-" not in text and "API_KEY" not in text


def test_diagnostics_symbols_uses_the_tradeable_predicate(client):
    body = client.get("/diagnostics/symbols").json()
    by = {s["symbol"]: s for s in body["symbols"]}
    assert by["BTC/USD"]["tradeable"] is True
    assert by["BTC/USD"]["last_bar_source"] == "real_feed"
    # MANA holds only a synthetic bar: unavailable, and its last real bar is
    # honestly "never".
    assert by["MANA/USD"]["tradeable"] is False
    assert by["MANA/USD"]["last_real_ts"] is None


def test_diagnostics_watchdog_shape(client):
    body = client.get("/diagnostics/watchdog").json()
    assert isinstance(body["state"], dict)
    kinds = [e["kind"] for e in body["events"]]
    assert "symbol_unavailable" in kinds


def test_bars_and_position_exits(client):
    b = client.get("/bars/BTC/USD?limit=10").json()
    assert b["symbol"] == "BTC/USD"
    assert [row["close"] for row in b["bars"]] == [104, 105]
    assert b["last_price"] == 105

    p = client.get("/positions/exits?mode=paper").json()
    row = next(x for x in p["positions"] if x["symbol"] == "ETH/USD")
    # The engine's own logged exit levels, never recomputed. ETH has no
    # durable exit-state columns, so the trade_entry payload still serves.
    assert row["stop"] == 2900.5 and row["target"] == 3400.1
    assert row["entry_factor"] == "momentum"


def test_position_exits_durable_columns_and_unmanageable(client):
    p = client.get("/positions/exits?mode=paper").json()
    # Durable exit-state columns (persisted at entry) are preferred.
    sol = next(x for x in p["positions"] if x["symbol"] == "SOL/USD")
    assert sol["stop"] == 95.5 and sol["target"] == 110.25
    assert sol["entry_factor"] == "reversion"
    # The engine's unmanageable verdict reaches the GUI beside the positions,
    # naming the position and why it cannot be managed.
    um = {u["symbol"]: u for u in p["unmanageable"]}
    assert "PRES-TEST" in um
    assert "no longer exists" in um["PRES-TEST"]["reason"]


def test_new_routes_are_get_only_and_bind_stays_loopback(client):
    from api_server import app as app_module
    assert app_module.HOST == "127.0.0.1"
    for path in NEW_ROUTES:
        r = client.post(path, json={})
        assert r.status_code == 405, f"{path} accepted a write"
    assert client.post("/bars/BTC/USD", json={}).status_code == 405


def test_stream_delta_never_drops_events(client):
    with client.websocket_connect("/stream") as ws:
        ws.send_text("paper")
        first = ws.receive_json()
        assert "events_delta" in first and "latest_event_id" in first
        seen = {e["id"] for e in first["events_delta"]}
        # A new event lands between ticks; the NEXT frame must deliver it.
        db = os.environ["MAL_DB_PATH"]
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO events(ts, kind, venue, symbol, severity, message,"
            " payload_json) VALUES ('2026-07-20T02:00:00Z','risk_block',"
            "'alpaca','SPY','info','Native entry blocked: test',"
            "'{\"reason\":\"test\"}')")
        conn.commit()
        conn.close()
        second = ws.receive_json()
        delta_kinds = [(e["id"], e["kind"]) for e in second["events_delta"]]
        fresh = [k for i, k in delta_kinds if i not in seen]
        assert "risk_block" in fresh, (
            "an event written between ticks was dropped from the stream")

"""Tests for the read-only FastAPI backend (api_server).

Data comes from a temporary SQLite database built from the real schema. No real
network or socket: the bridge probe is stubbed. Credential writes go to a
temporary keystore, never the real one and never an operational table.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
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
  ('2026-07-06T01:00:00Z','sec_13f',1,'Institution-x','SPY','long',1200000);

INSERT INTO whale_signal_history(ts, symbol, whale_bias, whale_confidence,
    whale_flow_direction, whale_regime_label, trade_outcome) VALUES
  ('2026-07-06T01:00:00Z','BTC/USD',0.3,0.5,'inflow','accumulation','win');

INSERT INTO approval_state(id, live_enabled, manual_confirmation,
    last_checked_ts, readiness_json) VALUES
  (1,0,0,'2026-07-06T00:00:00Z','{"ready": false}');

INSERT INTO events(ts, kind, venue, symbol, severity, message) VALUES
  ('2026-07-06T02:00:00Z','trade','alpaca','BTC/USD','info','opened BTC/USD');

-- Discovery: one crypto pass and one equity pass, with drops at every stage and
-- Stage-C candidates. Written Python-side by the discovery package in reality.
INSERT INTO discovery_pass(id, ts, asset_class, universe_count, finalists_count,
    survivors_count, evaluated_count, council_calls, gate_calls, est_cost_usd,
    budget_remaining, status, reason) VALUES
  (1,'2026-07-06T02:00:00Z','crypto',50,12,5,2,2,12,0.08,10,'ok',''),
  (2,'2026-07-06T01:00:00Z','crypto',50,10,4,1,1,10,0.04,11,'ok','stale pass'),
  (3,'2026-07-06T02:05:00Z','equity',119,12,3,1,1,12,0.04,9,'ok','');

INSERT INTO discovery_drop(pass_id, ts, symbol, stage, reason, score) VALUES
  (1,'2026-07-06T02:00:00Z','DOGE/USD','A','below_min_score',0.04),
  (1,'2026-07-06T02:00:00Z','XLM/USD','A','not_top_ranked',0.21),
  (1,'2026-07-06T02:00:00Z','ADA/USD','B','gate: too quiet',0.33),
  (1,'2026-07-06T02:00:00Z','DOT/USD','C','pass_council_ceiling',0.41),
  (3,'2026-07-06T02:05:00Z','KO','A','below_min_score',0.02);

INSERT INTO discovery_candidate(pass_id, ts, symbol, verdict, direction,
    conviction, edge, agreement, size_pct, horizon, sleeve_target, rationale,
    whale_surfaced, whale_reason)
    VALUES
  (1,'2026-07-06T02:00:00Z','SOL/USD','buy','long',0.82,0.05,3,0.41,'days',
   'quant_core','Council buy on SOL/USD: bias 0.60, agreement 3',0,''),
  (1,'2026-07-06T02:00:00Z','AVAX/USD','avoid','flat',0.30,0.0,1,0.0,'days',
   'quant_core','Council hold on AVAX/USD: bias 0.02',0,''),
  (3,'2026-07-06T02:05:00Z','NVDA','buy','long',0.88,0.06,3,0.44,'months',
   'research_satellite','Long-term long on NVDA. Quality 0.71, catalyst earnings',
   1,'whale accumulation (delayed)');

INSERT INTO watchlist(symbol, asset_class, added_ts, updated_ts, source, reason,
    sleeve_target, score, status, removed_ts, removed_reason) VALUES
  ('SOL/USD','crypto','2026-07-06T02:00:00Z','2026-07-06T02:00:00Z','discovery',
   'discovery buy conviction 0.82','quant_core',0.82,'active',NULL,NULL),
  ('NVDA','equity','2026-07-05T02:00:00Z','2026-07-06T02:05:00Z','discovery',
   'discovery buy conviction 0.88','research_satellite',0.88,'active',NULL,NULL),
  ('XRP/USD','crypto','2026-07-01T02:00:00Z','2026-07-01T02:00:00Z','prune',
   'signal stale, no pass in 48h','quant_core',0.4,'removed',
   '2026-07-06T02:00:00Z','signal stale, no pass in 48h');

INSERT INTO watchlist_event(ts, action, symbol, source, reason, applied) VALUES
  ('2026-07-06T02:00:00Z','add','SOL/USD','discovery','discovery buy 0.82',1),
  ('2026-07-06T02:00:00Z','remove','XRP/USD','prune','signal stale',1),
  ('2026-07-06T02:01:00Z','add','PEPE/USD','adaptive_react','breaking headline',0);

-- A long-term satellite position with its persisted thesis.
INSERT INTO positions(venue, symbol, market, category, side, qty, avg_price,
    notional, opened_ts, unrealized_pnl, sleeve) VALUES
  ('alpaca','NVDA','us_equity','equity','buy',10,180.0,1800.0,
   '2026-07-06T02:05:00Z',150.0,'research_satellite');

INSERT INTO research_thesis(ts, symbol, direction, conviction, horizon,
    rationale, status, target, invalidation_price, invalidation, entry_price)
    VALUES
  ('2026-07-06T02:05:00Z','NVDA','long',0.88,'months',
   'Long-term long on NVDA. Quality 0.71, catalyst earnings 2026-07-28.','open',
   240.0,150.0,'close below 150.00 (thesis broken)',180.0);
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
    monkeypatch.setenv("MAL_WEIGHT_OVERRIDE_PATH", str(tmp_path / "weights.json"))
    # Clear real API keys/flags so the integration health checks stay offline
    # (not_configured) in tests: no real network or socket call is made.
    for _v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
               "APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "ALPACA_API_KEY",
               "ALPACA_API_SECRET", "ALPACA_PAPER_API_KEY",
               "ALPACA_PAPER_API_SECRET", "WHALE_ALERT_API_KEY",
               "UNUSUAL_WHALES_API_KEY", "SEC_EDGAR_ENABLED",
               "FINNHUB_API_KEY"):
        monkeypatch.delenv(_v, raising=False)
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
            "control": str(tmp_path / "control"),
            "weights": str(tmp_path / "weights.json")}


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
    assert j["activity"][0]["source"] == "sec_13f"


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


# --- Category filters (Paper/Live Stocks + Crypto subpages) -----------------

def test_positions_category_filter(client):
    stocks = client.get("/positions?mode=paper&category=stocks").json()
    assert stocks["category"] == "stocks"
    assert {p["symbol"] for p in stocks["positions"]} <= {"SPY", "QQQ"}
    assert any(p["symbol"] == "SPY" for p in stocks["positions"])
    crypto = client.get("/positions?mode=paper&category=crypto").json()
    assert all(p["symbol"] in {"BTC/USD", "ETH/USD"}
               for p in crypto["positions"])


def test_orders_category_filter(client):
    crypto = client.get("/orders?mode=paper&category=crypto").json()["orders"]
    assert {o["symbol"] for o in crypto} == {"BTC/USD", "ETH/USD"}
    stocks = client.get("/orders?mode=paper&category=stocks").json()["orders"]
    assert {o["symbol"] for o in stocks} == {"SPY"}


def test_trades_category_filter(client):
    crypto = client.get("/trades?mode=paper&category=crypto").json()["trades"]
    assert {t["symbol"] for t in crypto} <= {"BTC/USD", "ETH/USD"}
    assert len(crypto) == 2
    stocks = client.get("/trades?mode=paper&category=stocks").json()["trades"]
    assert all(t["symbol"] in {"SPY", "QQQ"} for t in stocks)  # SPY is open


def test_signals_category_filter(client):
    crypto = client.get("/signals?category=crypto").json()
    assert all(s["symbol"] in {"BTC/USD", "ETH/USD"} for s in crypto["signals"])
    assert any(s["symbol"] == "BTC/USD" for s in crypto["signals"])
    stocks = client.get("/signals?category=stocks").json()
    assert all(s["symbol"] in {"SPY", "QQQ"} for s in stocks["signals"])


# --- Controls: validated write surface --------------------------------------

def _events(db_path, kind):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM events WHERE kind=? ORDER BY id", (kind,)).fetchall()]
    conn.close()
    return rows


def test_controls_get_shape(client):
    j = client.get("/controls").json()
    for k in ("layers", "models", "gate_enabled", "budget", "rl", "weights",
              "default_weights", "level1", "registry", "whitelist"):
        assert k in j
    assert set(j["layers"]) == {"adaptive", "council", "dnn_advisory", "whale"}
    assert j["rl"]["min_real_fills"] == 500
    assert "max_daily_loss_total_pct" in j["level1"]


def test_controls_weights_clamped_normalized_and_audited(env, client):
    r = client.post("/controls/weights", json={"weights": {
        "rule_based": 5.0, "llm_primary": -1.0, "llm_secondary": 0.5,
        "llm_tertiary": 0.5, "dnn_advisory": 0.5, "whale_signal": 0.5}}).json()
    assert r["ok"] is True
    w = r["weights"]
    assert all(0.0 <= v <= 1.0 for v in w.values())
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert w["llm_primary"] == 0.0                       # negative -> 0
    conn = sqlite3.connect(f"file:{env['db']}?mode=ro", uri=True)
    n = conn.execute("SELECT COUNT(*) FROM weight_changes").fetchone()[0]
    conn.close()
    assert n >= 1                                        # audited to weight_changes
    assert _events(env["db"], "control_change")          # and to the event log


def test_controls_layer_toggle_and_safety_rejected(env, client):
    ok = client.post("/controls/layer",
                     json={"layer": "adaptive", "enabled": False}).json()
    assert ok["ok"] is True
    assert client.get("/controls").json()["layers"]["adaptive"] is False
    bad = client.post("/controls/layer",
                      json={"layer": "safety", "enabled": False}).json()
    assert bad["ok"] is False


def test_controls_source_toggle_and_safety_rejected(env, client):
    # Source axis (mock/real), distinct from the enable toggle.
    ok = client.post("/controls/source",
                     json={"layer": "council", "source": "mock"}).json()
    assert ok["ok"] is True and ok["source"] == "mock"
    j = client.get("/controls").json()
    assert j["layer_sources"]["council"] == "mock"       # written + read back
    assert set(j["source_layers"]) == {"council", "dnn_advisory", "whale"}
    # Safety has no source axis (always real).
    assert client.post("/controls/source",
                       json={"layer": "safety", "source": "mock"}).json()["ok"] is False
    # Adaptive has no mock-vs-real service, so no source axis.
    assert client.post("/controls/source",
                       json={"layer": "adaptive", "source": "mock"}).json()["ok"] is False
    # An invalid source value is refused.
    assert client.post("/controls/source",
                       json={"layer": "whale", "source": "banana"}).json()["ok"] is False
    # The change is audited to the event log.
    assert _events(env["db"], "control_change")
    # /runstate mirrors the same source view for the banner.
    assert client.get("/runstate").json()["layer_sources"]["council"] == "mock"


def test_controls_feed_clock_toggle_and_open_position_safety(env, client):
    j = client.get("/controls").json()
    assert j["feed_mode"] in j["feed_modes"]
    assert j["clock_mode"] in j["clock_modes"]
    assert "open_positions" in j
    # An invalid feed mode is refused.
    assert client.post("/controls/feed_clock",
                       json={"feed_mode": "bogus",
                             "clock_mode": "real"}).json()["ok"] is False
    # Put the loop on alpaca_paper (a same-or-into switch is always safe).
    ok = client.post("/controls/feed_clock",
                     json={"feed_mode": "alpaca_paper",
                           "clock_mode": "real"}).json()
    assert ok["ok"] is True and ok["feed_mode"] == "alpaca_paper"
    # The seed has an open SPY paper position, so a switch AWAY from alpaca_paper
    # is refused (it would orphan the position).
    refused = client.post("/controls/feed_clock",
                          json={"feed_mode": "synthetic_regimes",
                                "clock_mode": "real"}).json()
    assert refused["ok"] is False and refused["open_positions"] >= 1
    # It did not change: the loop stays on alpaca_paper.
    assert client.get("/controls").json()["feed_mode"] == "alpaca_paper"
    # A clock-only change (feed unchanged) is always safe.
    okc = client.post("/controls/feed_clock",
                      json={"feed_mode": "alpaca_paper",
                            "clock_mode": "simulated"}).json()
    assert okc["ok"] is True and okc["clock_mode"] == "simulated"
    # /runstate mirrors the runtime feed/clock for the banner + status strip.
    rs = client.get("/runstate").json()
    assert rs["feed_mode"] == "alpaca_paper" and rs["clock_mode"] == "simulated"
    # The change was audited to the append-only event log (kind control_change).
    conn = sqlite3.connect(env["db"])
    n = conn.execute("SELECT COUNT(*) FROM events WHERE kind='control_change' "
                     "AND message LIKE 'feed_clock%'").fetchone()[0]
    conn.close()
    assert n >= 1


def test_controls_model_and_gate_toggle(env, client):
    assert client.post("/controls/model",
                       json={"model": "gpt-5.5", "enabled": False}).json()["ok"]
    assert client.get("/controls").json()["models"]["gpt-5.5"] is False
    assert client.post("/controls/model",
                       json={"model": "gate", "enabled": False}).json()["ok"]
    assert client.get("/controls").json()["gate_enabled"] is False
    assert client.post("/controls/model",
                       json={"model": "bogus", "enabled": False}).json()["ok"] is False


def test_controls_rl_refused_below_gate(env, client):
    r = client.post("/controls/rl", json={"enabled": True}).json()
    assert r["ok"] is False
    assert r["real_fills"] < r["min_real_fills"]
    assert client.get("/controls").json()["rl"]["enabled"] is False
    assert client.post("/controls/rl", json={"enabled": False}).json()["ok"] is True


def test_controls_regime_persists_and_clears(env, client):
    assert client.post("/controls/regime",
                       json={"symbol": "SPY", "regime": "trending"}).json()["ok"]
    assert client.get("/controls").json()["regime_pins"]["SPY"] == "trending"
    assert client.post("/controls/regime",
                       json={"symbol": "SPY", "regime": None}).json()["ok"]
    assert "SPY" not in client.get("/controls").json()["regime_pins"]
    assert client.post("/controls/regime",
                       json={"symbol": "NOPE", "regime": "trending"}).json()["ok"] is False


def test_controls_budget_clamped(env, client):
    r = client.post("/controls/budget",
                    json={"council_daily_budget": 99999,
                          "per_symbol_cooldown_minutes": -5}).json()
    assert r["ok"] is True and r["clamped"] is True
    assert r["budget"]["council_daily_budget"] == 500
    assert r["budget"]["per_symbol_cooldown_minutes"] == 0


def test_controls_promote_and_rollback_gated(client):
    assert client.post("/controls/promote").json()["ok"] is False
    assert client.post("/controls/rollback").json()["ok"] is False


def _seed_registry(db, champ_metrics, chall_metrics):
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO model_registry(ts,model_id,role,metrics_json,notes) "
                 "VALUES(?,?,?,?,?)", ("2026-07-06T00:00:00Z", "dnn-champ",
                 "champion", json.dumps(champ_metrics), "seed"))
    conn.execute("INSERT INTO model_registry(ts,model_id,role,metrics_json,notes) "
                 "VALUES(?,?,?,?,?)", ("2026-07-06T01:00:00Z", "dnn-chall",
                 "challenger", json.dumps(chall_metrics), "seed"))
    conn.commit()
    conn.close()


def test_controls_promote_and_rollback_execute(env, client):
    # A qualifying challenger (real-data, >=200 samples, higher sharpe, no worse
    # drawdown) so meets_promotion_criteria passes and the promote executes.
    _seed_registry(env["db"],
                   {"validation_sharpe": 0.5, "max_drawdown": 0.2,
                    "provenance": "synthetic"},
                   {"validation_sharpe": 0.9, "max_drawdown": 0.15,
                    "provenance": "real-data", "n_samples": 300})
    r = client.post("/controls/promote").json()
    assert r["ok"] is True and r["champion"] == "dnn-chall" \
        and r["retired"] == "dnn-champ"
    assert client.get("/controls").json()["registry"]["champion"]["model_id"] \
        == "dnn-chall"
    # Rollback restores the previous champion through the registry path.
    rb = client.post("/controls/rollback").json()
    assert rb["ok"] is True and rb["champion"] == "dnn-champ"
    assert client.get("/controls").json()["registry"]["champion"]["model_id"] \
        == "dnn-champ"
    # Both were audited to the append-only event log.
    conn = sqlite3.connect(env["db"])
    n = conn.execute("SELECT COUNT(*) FROM events WHERE kind='control_change' "
                     "AND (message LIKE 'promote:%' OR message LIKE 'rollback:%')"
                     ).fetchone()[0]
    conn.close()
    assert n >= 2


def test_controls_flat_engine_keys(env, client):
    # The engine reads flat keys from controls.json; the GUI setters must emit
    # them: a disabled provider slot, the runtime budget, and a regime pin.
    client.post("/controls/model", json={"model": "gpt-5.5", "enabled": False})
    client.post("/controls/budget", json={"council_daily_budget": 12,
                                          "per_symbol_cooldown_minutes": 45})
    client.post("/controls/regime", json={"symbol": "BTC/USD",
                                          "regime": "trending"})
    with open(os.path.join(env["control"], "controls.json")) as fh:
        j = json.load(fh)
    assert j["llm_primary_enabled"] is False      # gpt-5.5 is the primary slot
    assert j["rt_council_daily_budget"] == 12
    assert j["rt_per_symbol_cooldown_minutes"] == 45
    assert j["regime_pin:BTC/USD"] == "trending"


def test_controls_never_writes_level1(env, client):
    cfg = os.path.join(REPO_ROOT, "config", "default_config.yaml")

    def digest() -> str:
        with open(cfg, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    before = digest()
    # A Level-1 risk key can never enter the weight channel.
    r = client.post("/controls/weights",
                    json={"weights": {"max_daily_loss_total_pct": 0.9}}).json()
    assert r["ok"] is False
    client.post("/controls/layer", json={"layer": "whale", "enabled": False})
    client.post("/controls/budget",
                json={"council_daily_budget": 10, "per_symbol_cooldown_minutes": 30})
    client.post("/controls/regime", json={"symbol": "QQQ", "regime": "neutral"})
    assert digest() == before                     # config (Level-1 source) untouched
    lvl = client.get("/controls").json()["level1"]
    assert lvl.get("max_daily_loss_total_pct") == 0.03


# --- Live API health check (Task 5): read-only, offline-safe in tests --------

def test_health_integrations_offline_all_not_configured(env, client):
    j = client.get("/health/integrations").json()
    assert "integrations" in j and "summary" in j
    names = {r["name"] for r in j["integrations"]}
    assert {"openai", "anthropic_opus", "anthropic_haiku_gate", "gemini",
            "alpaca_data", "alpaca_trading_auth", "sec_edgar", "ibkr_gateway",
            "whale_alert", "unusual_whales"} <= names
    for r in j["integrations"]:
        assert r["state"] in {"working", "failing", "not_configured"}
    # Keys cleared, SEC/IBKR disabled -> every check not_configured, so NO real
    # network or socket call happens in the test.
    assert all(r["state"] == "not_configured" for r in j["integrations"])
    assert j["summary"]["configured_count"] == 0


def test_health_integrations_writes_no_op_or_risk_value(env, client):
    before = hashlib.sha256(open(env["db"], "rb").read()).hexdigest()
    client.get("/health/integrations")
    after = hashlib.sha256(open(env["db"], "rb").read()).hexdigest()
    assert before == after


# --- Discovery views (read-only) ---------------------------------------------

_DISCOVERY_ROUTES = ("/discovery/state", "/discovery/latest",
                     "/discovery/candidates", "/watchlist",
                     "/longterm/positions")


def test_discovery_latest_reports_the_funnel_narrowing(env, client):
    r = client.get("/discovery/latest")
    assert r.status_code == 200
    passes = {p["asset_class"]: p for p in r.json()["passes"]}
    # One pass per asset class, the most recent only (id 2 is the stale crypto).
    assert set(passes) == {"crypto", "equity"}
    c = passes["crypto"]
    assert c["ts"] == "2026-07-06T02:00:00Z"
    # The narrowing, which is the whole point of the view.
    assert (c["universe_count"], c["finalists_count"], c["survivors_count"],
            c["evaluated_count"]) == (50, 12, 5, 2)
    assert c["council_calls"] == 2 and c["gate_calls"] == 12
    assert c["est_cost_usd"] == 0.08 and c["budget_remaining"] == 10


def test_discovery_latest_carries_every_drop_with_stage_and_reason(env, client):
    passes = {p["asset_class"]: p
              for p in client.get("/discovery/latest").json()["passes"]}
    drops = {d["symbol"]: d for d in passes["crypto"]["drops"]}
    assert drops["DOGE/USD"]["stage"] == "A"
    assert drops["DOGE/USD"]["reason"] == "below_min_score"
    assert drops["XLM/USD"]["reason"] == "not_top_ranked"
    assert drops["ADA/USD"]["stage"] == "B"
    assert "too quiet" in drops["ADA/USD"]["reason"]
    assert drops["DOT/USD"]["stage"] == "C"
    assert drops["DOT/USD"]["reason"] == "pass_council_ceiling"
    # A drop from another pass never leaks in.
    assert "KO" not in drops


def test_discovery_latest_filters_by_asset_class(env, client):
    r = client.get("/discovery/latest?asset_class=equity")
    passes = r.json()["passes"]
    assert len(passes) == 1 and passes[0]["asset_class"] == "equity"
    assert passes[0]["universe_count"] == 119
    # An unknown class degrades to both, matching store.valid_category rather
    # than erroring.
    both = client.get("/discovery/latest?asset_class=nonsense").json()["passes"]
    assert len(both) == 2


def test_discovery_candidates_returns_verdicts_and_sizing(env, client):
    r = client.get("/discovery/candidates")
    assert r.status_code == 200
    cands = {c["symbol"]: c for c in r.json()["candidates"]}
    assert cands["NVDA"]["verdict"] == "buy"
    assert cands["NVDA"]["conviction"] == 0.88
    assert cands["NVDA"]["sleeve_target"] == "research_satellite"
    assert cands["NVDA"]["horizon"] == "months"
    assert cands["SOL/USD"]["sleeve_target"] == "quant_core"
    assert cands["AVAX/USD"]["verdict"] == "avoid"
    # Highest conviction first, so the operator reads the strongest first.
    assert [c["symbol"] for c in r.json()["candidates"]][0] == "NVDA"
    # Only the LATEST pass per class: the stale crypto pass contributes nothing.
    assert all(c["asset_class"] in ("crypto", "equity")
               for c in r.json()["candidates"])


def test_watchlist_reports_why_each_instrument_is_on_it(env, client):
    r = client.get("/watchlist")
    assert r.status_code == 200
    wl = {w["symbol"]: w for w in r.json()["watchlist"]}
    # Only active entries: the pruned XRP/USD is not on the list.
    assert set(wl) == {"SOL/USD", "NVDA"}
    assert wl["NVDA"]["reason"] == "discovery buy conviction 0.88"
    assert wl["NVDA"]["sleeve_target"] == "research_satellite"
    assert wl["NVDA"]["added_ts"] == "2026-07-05T02:00:00Z"
    assert wl["NVDA"]["updated_ts"] == "2026-07-06T02:05:00Z"
    assert wl["SOL/USD"]["sleeve_target"] == "quant_core"
    # Strongest first.
    assert [w["symbol"] for w in r.json()["watchlist"]] == ["NVDA", "SOL/USD"]


def test_watchlist_events_show_adds_prunes_and_refusals(env, client):
    events = client.get("/watchlist").json()["events"]
    by_symbol = {e["symbol"]: e for e in events}
    assert by_symbol["SOL/USD"]["action"] == "add"
    assert by_symbol["XRP/USD"]["action"] == "remove"
    assert by_symbol["XRP/USD"]["reason"] == "signal stale"
    # A REFUSED event from the not-yet-enabled react source stays visible, so a
    # silently dropped event can never hide.
    assert by_symbol["PEPE/USD"]["source"] == "adaptive_react"
    assert by_symbol["PEPE/USD"]["applied"] == 0


def test_longterm_positions_carry_the_full_thesis(env, client):
    r = client.get("/longterm/positions")
    assert r.status_code == 200
    positions = r.json()["positions"]
    # Only the research_satellite sleeve: the quant_core SPY position is absent.
    assert [p["symbol"] for p in positions] == ["NVDA"]
    p = positions[0]
    assert p["direction"] == "long" and p["conviction"] == 0.88
    assert p["horizon"] == "months"
    assert p["target"] == 240.0
    assert p["invalidation_price"] == 150.0
    assert "thesis broken" in p["invalidation"]
    assert p["opened_ts"] == "2026-07-06T02:05:00Z"   # entry date
    assert p["unrealized_pnl"] == 150.0               # current PnL
    assert p["thesis_status"] == "open"


def test_longterm_status_against_thesis(env, client):
    p = client.get("/longterm/positions").json()["positions"][0]
    # Entry 180, +150 PnL on 10 qty -> mark 195. Below target 240, above
    # invalidation 150, so the position is still on thesis.
    assert p["status_vs_thesis"] == "on thesis"


def test_longterm_status_reports_target_and_invalidation(env, client):
    from api_server import store
    base = {"direction": "long", "qty": 10.0, "avg_price": 180.0,
            "target": 240.0, "invalidation_price": 150.0}
    # Mark 245 (>= target 240).
    assert store._thesis_status({**base, "unrealized_pnl": 650.0}) == \
        "target reached"
    # Mark 145 (<= invalidation 150).
    assert store._thesis_status({**base, "unrealized_pnl": -350.0}) == \
        "invalidated"
    # A thesis-less position says so rather than guessing.
    assert store._thesis_status({"qty": 1}) == "no thesis"


def test_longterm_distinguishes_strategy_from_sleeve(env, client):
    j = client.get("/longterm/positions").json()
    # Three distinct booleans, because they answer different questions.
    assert j["strategy_enabled"] is False        # long_term_sleeve_enabled
    assert j["sleeve_config_enabled"] is False   # research_satellite_enabled
    # `enabled` is the conjunction: a long-term position needs both.
    assert j["enabled"] is False


def test_discovery_state_summarizes_for_the_top_strip(env, client):
    j = client.get("/discovery/state").json()
    assert j["enabled"] is False                 # ships disabled
    assert j["long_term_sleeve_enabled"] is False
    assert j["watchlist_size"] == 2              # active only, pruned excluded
    assert j["last_pass"]["crypto"] == "2026-07-06T02:00:00Z"
    assert j["last_pass"]["equity"] == "2026-07-06T02:05:00Z"
    # Universe sizes come from the real config, so the strip cannot drift.
    assert j["universe"]["equity_universe"] >= 100
    assert j["universe"]["crypto_active_max"] <= 50
    assert j["ceilings"]["max_survivors"] <= j["ceilings"]["max_finalists"]
    # The react layer is not built, and the payload says so.
    assert j["react_layer_built"] is False


def test_discovery_state_budget_is_separate_from_the_trading_budget(env, client):
    j = client.get("/discovery/state").json()
    # 2 + 1 + 1 council calls across the seeded passes... but only today's count.
    # The seed dates are 2026-07-06, not today, so today's spend is 0.
    assert j["budget"]["used_today"] == 0
    assert j["budget"]["remaining"] == j["budget"]["daily"]
    assert j["budget"]["est_spend_today"] == 0.0
    # This is the DISCOVERY budget, counted from discovery_pass, not the
    # trading council's model_outputs.
    from api_server import controls
    assert controls.discovery_used_today() == 0


def test_discovery_views_are_empty_but_valid_when_the_tables_are_absent(
        tmp_path, monkeypatch):
    """A DB predating discovery must render an empty view, never a 500."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE positions(venue TEXT, symbol TEXT, market TEXT, "
        "category TEXT, side TEXT, qty REAL, avg_price REAL, notional REAL, "
        "opened_ts TEXT, unrealized_pnl REAL, sleeve TEXT);")
    conn.commit()
    conn.close()
    monkeypatch.setenv("MAL_DB_PATH", str(db))
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "control"))
    from api_server.app import app
    c = TestClient(app)
    for route in _DISCOVERY_ROUTES:
        r = c.get(route)
        assert r.status_code == 200, route
    assert c.get("/discovery/latest").json()["passes"] == []
    assert c.get("/watchlist").json()["watchlist"] == []
    assert c.get("/discovery/state").json()["watchlist_size"] == 0


def test_discovery_candidates_carry_the_whale_surfaced_tag(env, client):
    """Whale surfacing and whale evaluation are two jobs, and the tag says which
    candidates whale FOUND. The Level-4 evaluation is unaffected by this."""
    cands = {c["symbol"]: c
             for c in client.get("/discovery/candidates").json()["candidates"]}
    assert cands["NVDA"]["whale_surfaced"] == 1
    assert cands["NVDA"]["whale_reason"] == "whale accumulation (delayed)"
    # A technically-found candidate is NOT tagged.
    assert cands["SOL/USD"]["whale_surfaced"] == 0


def test_discovery_latest_reports_the_whale_surfaced_count(env, client):
    passes = {p["asset_class"]: p
              for p in client.get("/discovery/latest").json()["passes"]}
    # Seeded 0 for crypto; the column exists and reads back rather than 500ing.
    assert passes["crypto"]["whale_surfaced_count"] == 0


def test_discovery_views_write_nothing(env, client):
    """The structural claim: these are reads. The DB must be byte-identical."""
    before = hashlib.sha256(open(env["db"], "rb").read()).hexdigest()
    for route in _DISCOVERY_ROUTES:
        assert client.get(route).status_code == 200
    after = hashlib.sha256(open(env["db"], "rb").read()).hexdigest()
    assert before == after


def test_discovery_views_expose_no_write_route(env, client):
    """No POST/PUT/PATCH/DELETE exists on any discovery path."""
    paths = {r.path: r for r in client.app.routes if hasattr(r, "methods")}
    for path, route in paths.items():
        if any(path.startswith(p) for p in
               ("/discovery", "/watchlist", "/longterm")):
            assert route.methods <= {"GET", "HEAD"}, (path, route.methods)


def test_discovery_views_never_expose_a_key_value(env, client, monkeypatch):
    """No discovery response may carry a credential, even with keys resolvable."""
    canary = "CANARY-GUI-KEY-MUST-NOT-APPEAR-2b3c4d"
    for var in ("FINNHUB_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"):
        monkeypatch.setenv(var, canary)
    for route in _DISCOVERY_ROUTES:
        body = client.get(route).text
        assert canary not in body, route
        assert "token=" not in body, route
        assert "api_key" not in body.lower(), route


def test_discovery_views_never_enable_live(env, client):
    """A discovery view cannot change the live posture."""
    before = client.get("/approval").json()
    for route in _DISCOVERY_ROUTES:
        client.get(route)
    after = client.get("/approval").json()
    assert before == after
    assert after.get("live_enabled") in (0, False)


def test_health_trade_auth_and_ibkr_never_order():
    import inspect
    from api_server import health
    # Trade-auth is a GET /v2/account only. It must never POST or hit an orders
    # endpoint (no resting order, no money moved).
    trade = inspect.getsource(health._check_alpaca_trading)
    assert "_post(" not in trade
    assert "orders" not in trade.lower()
    assert "/v2/account" in trade
    # IBKR check is socket reachability only. No HTTP POST, no orders endpoint.
    ibkr = inspect.getsource(health._check_ibkr)
    assert "_post(" not in ibkr
    assert "/v2/orders" not in ibkr
    assert "create_connection" in ibkr


# --- Operational upgrades: skip feed, run state, day summary, provider cost --

def test_skips_reads_event_log(env, client):
    conn = sqlite3.connect(env["db"])
    conn.execute("INSERT INTO events(ts,kind,venue,symbol,severity,message,"
                 "payload_json) VALUES(?,?,?,?,?,?,?)",
                 ("2026-07-06T03:00:00Z", "council_skip", "alpaca", "SPY",
                  "info", "Council skipped: skip_budget", '{"reason":"skip_budget"}'))
    conn.commit(); conn.close()
    j = client.get("/skips").json()
    assert any(x["reason"] == "skip_budget" for x in j["skips"])


def test_runstate_and_day_summary_shape(client):
    r = client.get("/runstate").json()
    assert r["council_mode"] in {"real", "mock"}
    assert "feed_mode" in r and "bridge" in r
    d = client.get("/day_summary").json()
    for k in ("trades_today", "win_rate_today", "council_calls_today",
              "council_daily_budget", "estimated_spend_today"):
        assert k in d


def test_providers_cost_shape_and_absent_key_unavailable(env, client):
    j = client.get("/providers/cost").json()
    assert "providers" in j and "totals" in j and j["currency"] == "USD"
    names = {p["provider"] for p in j["providers"]}
    assert {"OpenAI", "Anthropic", "Google"} <= names
    for p in j["providers"]:
        for k in ("provider", "model", "balance", "spend", "estimated_day",
                  "estimated_month", "status", "source"):
            assert k in p
        assert p["status"] in {"live", "estimated", "unavailable"}
        # env fixture clears provider keys -> unavailable
        assert p["status"] == "unavailable"
    # no key-shaped value leaks in the response
    body = client.get("/providers/cost").text
    assert "sk-" not in body and "APCA-API" not in body


def test_providers_cost_estimated_from_recorded_calls(env, client):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(env["db"])
    conn.execute("INSERT INTO model_outputs(ts,model,verdict,confidence,edge,"
                 "weight) VALUES(?,?,?,?,?,?)",
                 (now, "llm_primary", "buy", 0.7, 0.03, 0.27))
    conn.commit(); conn.close()
    j = client.get("/providers/cost").json()
    openai = next(p for p in j["providers"] if p["provider"] == "OpenAI")
    assert openai["calls_today"] >= 1
    assert openai["estimated_day"] > 0.0   # computed from calls * config prices


def test_trade_detail_shape(client):
    j = client.get("/trade/1").json()
    assert "trade" in j
    if j["trade"]:
        for k in ("signals", "council", "regime", "events"):
            assert k in j


def test_ops_endpoints_write_no_op_or_risk_value(env, client):
    before = hashlib.sha256(open(env["db"], "rb").read()).hexdigest()
    for path in ("/skips", "/runstate", "/day_summary", "/providers/cost", "/trade/1"):
        assert client.get(path).status_code == 200
    after = hashlib.sha256(open(env["db"], "rb").read()).hexdigest()
    assert before == after


# --- Unified keystore-first credential resolution (live-key paths) ----------

def test_health_resolver_keystore_counts_configured(env, client, monkeypatch):
    # A key in the keystore ONLY (no env) must count as configured. Stub the
    # HTTP so no real network call happens.
    import account_manager.credentials as creds
    for name in ("openai_key", "anthropic_key", "gemini_key",
                 "alpaca_paper_key", "alpaca_paper_secret"):
        creds.set_credential(name, "unit-test-fake-value")
    from api_server import health
    monkeypatch.setattr(health, "_post", lambda *a, **k: 200)
    monkeypatch.setattr(health, "_get", lambda *a, **k: 200)
    j = client.get("/health/integrations").json()
    states = {i["name"]: i["state"] for i in j["integrations"]}
    for n in ("openai", "anthropic_opus", "anthropic_haiku_gate", "gemini",
              "alpaca_data", "alpaca_trading_auth"):
        assert states[n] == "working", (n, states[n])
    assert "unit-test-fake-value" not in client.get("/health/integrations").text


def test_health_resolver_absent_key_not_configured(env, client):
    j = client.get("/health/integrations").json()
    states = {i["name"]: i["state"] for i in j["integrations"]}
    for n in ("openai", "anthropic_opus", "anthropic_haiku_gate", "gemini",
              "alpaca_data", "alpaca_trading_auth"):
        assert states[n] == "not_configured"   # no key anywhere -> no call


def test_resolver_is_single_source_for_provider_keys():
    import inspect
    from api_server import health
    import llm_consensus.providers as P
    import llm_consensus.gate as G
    import whale_signal.adapters as W
    import market_data.alpaca_source as A
    assert "resolve_env" in inspect.getsource(health._key)
    assert "get_credential" in inspect.getsource(health._alpaca_creds)
    assert "resolve_env" in inspect.getsource(P._resolve_key)
    assert "_resolve_key" in inspect.getsource(G)
    # SEC contact + Alpaca data keys go through the resolver, not raw env
    assert "_resolve(" in inspect.getsource(W._user_agent)
    assert "os.environ" not in inspect.getsource(A._data_keys)


def test_verify_script_places_no_order_and_never_touches_live():
    path = os.path.join(REPO_ROOT, "scripts", "verify_live_integrations.sh")
    src = open(path).read()
    assert "/v2/orders" not in src                    # never a resting order
    assert "_check_alpaca_trading" in src             # auth-only account check
    assert "health" in src                            # resolver-backed checks
    # no live-trading branch, no order placement helper
    assert "submit_paper_order" not in src and "execute" not in src


# --- Layer toggles: Ops writes the same controls.json the engine reads -------

def test_runstate_reflects_layer_toggle(env, client):
    r0 = client.get("/runstate").json()
    assert "layers" in r0
    # An Ops/Controls toggle writes controls.json, which /runstate (and the
    # engine) read back. Same validated endpoint, no new write path.
    assert client.post("/controls/layer",
                       json={"layer": "council", "enabled": False}).json()["ok"] is True
    r1 = client.get("/runstate").json()
    assert r1["layers"].get("council") is False
    # Safety is never toggleable.
    bad = client.post("/controls/layer",
                      json={"layer": "safety", "enabled": False}).json()
    assert bad["ok"] is False
    # The toggle change audits to the event log (control_change).
    conn = sqlite3.connect(f"file:{env['db']}?mode=ro", uri=True)
    n = conn.execute("SELECT COUNT(*) FROM events WHERE kind='control_change'").fetchone()[0]
    conn.close()
    assert n >= 1


# --- Engine supervisor: GUI Start/Stop with fully mocked process control -----
# No real subprocess, no network. api_server.stack is the process-control seam;
# every function it exposes is patched here so the lifecycle is deterministic.

class FakeProc:
    """Stand-in for a subprocess.Popen: poll() is None while alive."""
    def __init__(self, pid=12345, alive=True, exit_code=1):
        self.pid = pid
        self._alive = alive
        self._code = exit_code

    def poll(self):
        return None if self._alive else self._code

    def terminate(self):
        self._alive = False

    def kill(self):
        self._alive = False

    def wait(self, timeout=None):
        self._alive = False
        return 0


def _mk_spawn(engine_alive=True):
    """A spawn() that returns a live bridge and an engine whose liveness is
    configurable. When the engine is not alive it writes a strict-mode failure
    line to the engine log, the way a real strict-mode refusal would."""
    def _spawn(cmd, env=None, log_path=None):
        is_engine = any("mal_engine" in str(c) for c in cmd)
        if is_engine and not engine_alive:
            if log_path:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "w") as fh:
                    fh.write("FATAL: council set on-real but the bridge reports "
                             "council_real=false. Missing OPENAI_API_KEY.\n")
            return FakeProc(pid=222, alive=False, exit_code=1)
        return FakeProc(pid=(222 if is_engine else 111), alive=True)
    return _spawn


_WARM_ALL = {
    "need": 102, "timeframe": "5min", "all_warm": True,
    "symbols": [{"symbol": s, "bars": 9000, "warm": True}
                for s in ("BTC/USD", "ETH/USD", "SPY", "QQQ")],
}


@pytest.fixture()
def sup(env, monkeypatch, tmp_path):
    """The supervisor singleton, reset, with api_server.stack fully mocked so no
    real process or network is touched."""
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))
    from api_server import stack, supervisor
    supervisor.SUPERVISOR._reset_for_test()
    monkeypatch.setattr(supervisor, "ENGINE_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(stack, "sleep", lambda s: None)
    monkeypatch.setattr(stack, "run_backfill", lambda db=None: None)
    monkeypatch.setattr(stack, "seed_feed_clock", lambda: None)
    monkeypatch.setattr(stack, "http_ok", lambda *a, **k: True)
    monkeypatch.setattr(stack, "warm_report", lambda db=None: dict(_WARM_ALL))
    monkeypatch.setattr(stack, "pid_alive", lambda pid: True)
    monkeypatch.setattr(stack, "spawn", _mk_spawn(engine_alive=True))
    # Pre-flight is mocked so tests never probe or kill a real port. pid-file
    # helpers stay real (they write under the temp MAL_RUN_DIR).
    monkeypatch.setattr(stack, "preflight_ports", lambda names=None, exclude_pids=(): [])
    # The bridge readiness probe hits no real network in tests: default all-ready.
    monkeypatch.setattr(stack, "bridge_missing_real_layers", lambda: [])
    stack.clear_pids()
    yield supervisor.SUPERVISOR
    supervisor.SUPERVISOR._reset_for_test()
    stack.clear_pids()


def test_engine_state_shape_and_no_key(sup, client):
    j = client.get("/engine/state").json()
    assert j["state"] == "not_running"
    for k in ("warm", "lock", "history", "bridge_port", "feed_mode"):
        assert k in j
    # No credential-shaped value is ever surfaced by the lifecycle state.
    blob = json.dumps(j).lower()
    for bad in ("api_key", "secret", "apca", "sk-", "bearer"):
        assert bad not in blob


def test_engine_start_warms_to_running_then_stops(sup, client):
    assert client.get("/engine/state").json()["state"] == "not_running"
    r = client.post("/engine/start").json()
    assert r["ok"] is True
    sup.join(4)
    st = client.get("/engine/state").json()
    assert st["state"] == "running"
    # It transitioned through warming (Task 1 lifecycle).
    assert "warming" in [h.get("state") for h in st["history"]]
    # Stop is a graceful shutdown back to not_running.
    s = client.post("/engine/stop").json()
    assert s["ok"] is True
    assert client.get("/engine/state").json()["state"] == "not_running"


def test_engine_second_start_refused_while_running(sup, client):
    client.post("/engine/start")
    sup.join(4)
    assert client.get("/engine/state").json()["state"] == "running"
    r = client.post("/engine/start").json()
    assert r["ok"] is False and "already" in r["error"]


def test_engine_start_refused_by_live_foreign_lock(sup, client):
    # A lock left by the start SCRIPT (or another process) with a live pid blocks
    # a GUI start, rather than fighting for the same engine.
    from api_server import stack
    stack.write_lock(4242, 4243, source="script")   # pid_alive is True here
    r = client.post("/engine/start").json()
    assert r["ok"] is False and "already running" in r["error"]
    # The GUI still reflects the foreign engine as running.
    assert client.get("/engine/state").json()["state"] == "running"


def test_engine_stale_lock_cleared_then_start(sup, client, monkeypatch):
    from api_server import stack
    # Dead pids: the lock is stale, not a running instance.
    monkeypatch.setattr(stack, "pid_alive", lambda pid: pid in (222, 111))
    stack.write_lock(999999, 999998, source="script")
    assert stack.lock_status()["stale"] is True
    r = client.post("/engine/start").json()
    assert r["ok"] is True
    sup.join(4)
    assert client.get("/engine/state").json()["state"] == "running"


def test_engine_strict_mode_start_fails_loudly(sup, monkeypatch):
    from api_server import stack, supervisor
    # The engine exits on start (strict mode refused an unreachable on-real
    # layer). The supervisor surfaces what is missing, not a silent mock.
    monkeypatch.setattr(stack, "spawn", _mk_spawn(engine_alive=False))
    supervisor.SUPERVISOR.start(background=False)
    st = supervisor.SUPERVISOR.state()
    assert st["state"] == "not_running"
    assert st["error"] and "on-real" in st["error"]


def test_kill_path_independent_of_supervisor(sup, client, env):
    """Task 2: the kill switch halts the engine even with the supervisor down.
    It writes the control file the C++ engine reads on its own, no supervisor."""
    client.post("/engine/start")
    sup.join(4)
    assert client.get("/engine/state").json()["state"] == "running"
    # Simulate the supervisor + backend process being gone.
    sup._engine = None
    sup._bridge = None
    sup._state = "not_running"
    # The kill request still records the durable halt the engine consumes.
    r = client.post("/kill", json={"requested": True, "reason": "halt"})
    assert r.json()["ok"] is True
    assert os.path.exists(os.path.join(env["control"], "kill_request.json"))
    # Structural: the kill write path never routes through the supervisor.
    import inspect
    from api_server import store, app as appmod
    assert "supervisor" not in inspect.getsource(store.write_kill_request).lower()
    assert "supervisor" not in inspect.getsource(appmod.post_kill).lower()


def test_supervisor_never_touches_kill_request_file():
    """The supervisor and its stack must never read or write the kill-request
    file, so start/stop can never interfere with the safety halt."""
    import inspect
    from api_server import supervisor, stack
    src = (inspect.getsource(supervisor) + inspect.getsource(stack)).lower()
    assert "kill_request" not in src


def test_warm_report_reads_bars_table(env):
    """warm_report reports per-symbol warm state from the bars table, no network.
    The seed DB has no 5-min bars for the whitelist, so every symbol is cold."""
    from api_server import stack
    rep = stack.warm_report(env["db"])
    assert set(rep) >= {"need", "timeframe", "symbols", "all_warm"}
    assert rep["need"] >= 102
    assert rep["all_warm"] is False
    assert {"BTC/USD", "SPY"} <= {s["symbol"] for s in rep["symbols"]}


def test_engine_endpoints_bind_loopback():
    """The lifecycle endpoints ride the same loopback-bound app, no new bind."""
    from api_server.app import HOST
    assert HOST == "127.0.0.1"


# --- Pre-flight port cleanup, PID tracking, single-instance self-heal --------
# All process/port control is mocked. No real lsof, no real kill, no network.

def test_preflight_clears_stale_holder_and_leaves_others(monkeypatch, tmp_path):
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))
    from api_server import stack
    killed = []
    monkeypatch.setattr(stack, "terminate_pid",
                        lambda pid, timeout=8.0: (killed.append(pid) or True))
    bp = stack.bridge_port()
    # Only the bridge port is held by a stale pid; other stack ports are free.
    monkeypatch.setattr(stack, "port_holders",
                        lambda port: [55555] if port == bp else [])
    rep = stack.preflight_ports()
    br = next(r for r in rep if r["label"] == "bridge")
    assert br["action"] == "cleared" and 55555 in br["pids"]
    assert all(r["action"] == "free" for r in rep if r["label"] != "bridge")
    assert killed == [55555]   # only the stale bridge holder, no blanket kill


def test_preflight_never_targets_own_pid(monkeypatch):
    import os as _os
    from api_server import stack
    killed = []
    monkeypatch.setattr(stack, "terminate_pid",
                        lambda pid, timeout=8.0: (killed.append(pid) or True))
    # Even if our own process appears to hold a stack port, it is protected.
    monkeypatch.setattr(stack, "port_holders", lambda port: [_os.getpid()])
    stack.preflight_ports()
    assert killed == []


def test_pid_file_record_read_and_stop(monkeypatch, tmp_path):
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))
    from api_server import stack
    stack.clear_pids()
    stack.record_pid("bridge", 111)
    stack.record_pid("engine", 222)
    assert stack.tracked_pids() == {"bridge": 111, "engine": 222}
    stopped = []
    monkeypatch.setattr(stack, "pid_alive", lambda pid: True)
    monkeypatch.setattr(stack, "terminate_pid",
                        lambda pid, timeout=8.0: (stopped.append(pid) or True))
    res = stack.stop_tracked_pids()
    assert {r["pid"] for r in res} == {111, 222}
    assert set(stopped) == {111, 222}
    assert stack.read_pids() == {}   # file cleared after teardown


def test_self_heal_clears_stale_run(monkeypatch, tmp_path):
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "control"))
    from api_server import stack
    # A crashed prior run: dead recorded pids + a stale engine lock.
    monkeypatch.setattr(stack, "pid_alive", lambda pid: False)
    monkeypatch.setattr(stack, "http_ok", lambda *a, **k: False)
    stack.record_pid("engine", 999999)
    stack.write_lock(999999, source="script")
    assert stack.lock_status()["stale"] is True
    res = stack.self_heal()
    assert res.get("skipped") is None
    assert stack.read_pids() == {}
    assert stack.lock_status()["present"] is False


def test_self_heal_refuses_when_healthy_stack_up(monkeypatch, tmp_path):
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "control"))
    from api_server import stack
    # A live, healthy engine: self-heal must NOT kill it (it is a duplicate, not
    # a crash), and stop_tracked must not be reached.
    monkeypatch.setattr(stack, "pid_alive", lambda pid: True)
    monkeypatch.setattr(stack, "http_ok", lambda *a, **k: True)
    stack.write_lock(4242, 4243, source="script")
    res = stack.self_heal()
    assert res.get("skipped")


def test_stack_running_guard(monkeypatch, tmp_path):
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "control"))
    from api_server import stack
    monkeypatch.setattr(stack, "pid_alive", lambda pid: True)
    stack.write_lock(4242, 4243, source="script")
    # Healthy: engine alive AND a health check passes -> refuse a duplicate.
    monkeypatch.setattr(stack, "http_ok", lambda *a, **k: True)
    assert stack.stack_running()["running"] is True
    # Engine alive but unhealthy (no health) -> not a running instance to block.
    monkeypatch.setattr(stack, "http_ok", lambda *a, **k: False)
    assert stack.stack_running()["running"] is False


def test_supervisor_preflights_bridge_only_and_tracks_pids(sup, client, monkeypatch):
    from api_server import stack
    calls = []
    monkeypatch.setattr(stack, "preflight_ports",
                        lambda names=None, exclude_pids=(): (calls.append(names) or []))
    client.post("/engine/start")
    sup.join(4)
    assert client.get("/engine/state").json()["state"] == "running"
    # Pre-flight cleaned ONLY the bridge port, never the api port it runs on.
    assert calls and all(n == ["bridge"] for n in calls)
    # It tracked the bridge + engine pids in the shared pid file.
    assert {"bridge", "engine"} <= set(stack.tracked_pids())
    # Stop removes the tracked pids.
    client.post("/engine/stop")
    assert "engine" not in stack.tracked_pids()


def test_preflight_and_pid_helpers_never_touch_kill_request():
    """Pre-flight, pid tracking, and self-heal must never read or write the
    kill-request file, so cleanup can never disturb the safety halt."""
    import inspect
    from api_server import stack
    for fn in (stack.preflight_ports, stack.free_port, stack.self_heal,
               stack.stop_tracked_pids, stack.record_pid):
        assert "kill_request" not in inspect.getsource(fn).lower()


# --- Supervisor survives past warming: env parity + readiness gating ---------
# The GUI start died right after warming because the supervisor spawned the
# bridge WITHOUT the whale env flags the script exports, so the bridge reported
# whale_real=false, the engine's strict on-real check refused, the engine exited,
# and the supervisor tore everything down. These lock the fix.

def test_bridge_env_carries_whale_flags(env):
    """The bridge env the supervisor spawns with includes the whale flags the
    script exports, so a GUI start matches the script (whale_real can be true)."""
    from api_server import stack
    be = stack.bridge_env()
    assert "SEC_EDGAR_ENABLED" in be and "WHALE_LIVE_ENABLED" in be
    assert be["SEC_EDGAR_ENABLED"] in ("true", "false")
    assert be.get("BRIDGE_PORT")


def test_supervisor_spawns_bridge_with_whale_env(sup, client, monkeypatch):
    from api_server import stack
    seen = {}

    def _rec_spawn(cmd, env=None, log_path=None):
        if any("python_bridge" in str(c) for c in cmd):
            seen["bridge_env"] = env or {}
        return FakeProc(pid=(222 if any("mal_engine" in str(c) for c in cmd) else 111),
                        alive=True)

    monkeypatch.setattr(stack, "spawn", _rec_spawn)
    client.post("/engine/start")
    sup.join(4)
    assert client.get("/engine/state").json()["state"] == "running"
    # The bridge was spawned WITH the whale flags (the shutdown-after-warming fix).
    assert "SEC_EDGAR_ENABLED" in seen.get("bridge_env", {})


def test_supervisor_readiness_gate_blocks_engine_when_bridge_unhealthy(sup, monkeypatch):
    from api_server import stack, supervisor
    calls = {"spawn": 0}
    real_spawn = _mk_spawn(engine_alive=True)

    def _count_spawn(cmd, env=None, log_path=None):
        calls["spawn"] += 1
        return real_spawn(cmd, env, log_path)

    monkeypatch.setattr(stack, "spawn", _count_spawn)
    monkeypatch.setattr(stack, "http_ok", lambda *a, **k: False)  # bridge never healthy
    supervisor.SUPERVISOR.start(background=False)
    st = supervisor.SUPERVISOR.state()
    assert st["state"] == "not_running"
    assert st["error"] and "health check" in st["error"]
    # The engine was NEVER spawned: only the bridge spawn happened before the gate.
    assert calls["spawn"] == 1


def test_supervisor_teardown_reports_reason_to_state_and_event_log(sup, env, monkeypatch):
    from api_server import stack, supervisor
    # The bridge is healthy but a required on-real layer is not ready.
    monkeypatch.setattr(stack, "bridge_missing_real_layers",
                        lambda: ["whale: SEC_EDGAR_ENABLED off, whale would be offline mock"])
    supervisor.SUPERVISOR.start(background=False)
    st = supervisor.SUPERVISOR.state()
    assert st["state"] == "not_running"
    assert st["error"] and "on-real layer" in st["error"] and "whale" in st["error"]
    # The reason is also recorded to the append-only event log for the GUI feed.
    conn = sqlite3.connect(env["db"])
    n = conn.execute("SELECT COUNT(*) FROM events WHERE kind='engine_supervisor' "
                     "AND message LIKE 'GUI start failed%'").fetchone()[0]
    conn.close()
    assert n >= 1


def test_supervisor_teardown_never_touches_kill_request(sup, env, monkeypatch):
    """A supervisor teardown must never write the kill-request file: the safety
    halt stays independent of a failed start."""
    from api_server import stack, supervisor
    monkeypatch.setattr(stack, "bridge_missing_real_layers", lambda: ["council: not real"])
    supervisor.SUPERVISOR.start(background=False)
    assert supervisor.SUPERVISOR.state()["state"] == "not_running"
    assert not os.path.exists(os.path.join(env["control"], "kill_request.json"))


# --- Core-satellite sleeve GUI endpoints (Q) -------------------------------

def test_sleeves_endpoint_reports_split_and_cap(env, client):
    r = client.get("/sleeves")
    assert r.status_code == 200
    d = r.json()
    # Default 70/30 split, 5% band, hard cap 35% of equity. The 30 percent is a
    # CEILING, not a floor: the cap is what the satellite can never exceed.
    assert d["targets"]["quant_core"] == 0.70
    assert d["targets"]["research_satellite"] == 0.30
    assert d["drift_band"] == 0.05
    assert abs(d["hard_cap_pct"] - 0.35) < 1e-9
    assert "allocation" in d and "rebalance_due" in d
    # research_satellite ships OFF by default.
    assert d["research_satellite_config_enabled"] is False
    assert d["enabled"]["research_satellite"] is False


def test_research_theses_endpoint(env, client):
    r = client.get("/research/theses")
    assert r.status_code == 200
    assert isinstance(r.json()["theses"], list)


def test_sleeve_history_endpoint(env, client):
    r = client.get("/sleeves/history")
    assert r.status_code == 200
    assert isinstance(r.json()["history"], list)


def test_sleeve_toggle_writes_control_file(env, client):
    r = client.post("/controls/sleeve",
                    json={"sleeve": "research_satellite", "enabled": True})
    assert r.status_code == 200 and r.json()["ok"] is True
    # The toggle persists to the control file and reads back through /sleeves.
    assert client.get("/sleeves").json()["enabled"]["research_satellite"] is True
    # An unknown sleeve is refused server-side.
    bad = client.post("/controls/sleeve", json={"sleeve": "moon", "enabled": True})
    assert bad.json()["ok"] is False


def test_manual_rebalance_request(env, client):
    r = client.post("/controls/rebalance")
    assert r.status_code == 200 and r.json()["rebalance_requested"] is True
    # It writes the control file, never a kill-request file.
    assert not os.path.exists(os.path.join(env["control"], "kill_request.json"))


def test_sleeve_endpoints_never_return_a_key(env, client):
    blob = (client.get("/sleeves").text + client.get("/research/theses").text +
            client.get("/sleeves/history").text)
    assert "sk-" not in blob and "API_KEY" not in blob

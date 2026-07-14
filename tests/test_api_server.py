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
               "UNUSUAL_WHALES_API_KEY", "SEC_EDGAR_ENABLED"):
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
    yield supervisor.SUPERVISOR
    supervisor.SUPERVISOR._reset_for_test()


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

"""FastAPI application exposing the read-only trading data + credential writes.

All GET endpoints are read-only on the operational tables. The only write path
is POST /credentials, which stores an encrypted credential through the existing
account_manager keystore and NEVER echoes or logs the value. The app binds
loopback only (see HOST). CORS is limited to the local Vite dev origins.

Nothing here can weaken the RiskGate or enable live trading. The Live view
reads approval state and reports it. It cannot change it.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api_server import store
from api_server import controls
from api_server import health
from api_server import providers_cost
from api_server import supervisor

HOST = "127.0.0.1"        # loopback only, asserted by the test suite
PORT = int(os.environ.get("MAL_API_PORT", "8000"))
STREAM_INTERVAL_SECONDS = 2.0

# Local dev origins only. The Vite dev server serves the React app here.
_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5173", "http://localhost:5173",
    "http://127.0.0.1:4173", "http://localhost:4173",
]

app = FastAPI(title="AiTrader API", version="1.0.0",
              description="Read-only trading data for the React GUI.")
app.add_middleware(
    CORSMiddleware, allow_origins=_ALLOWED_ORIGINS, allow_methods=["*"],
    allow_headers=["*"], allow_credentials=False)


def _mode(mode: str) -> str:
    return store.valid_mode(mode)


# --- Read endpoints ---------------------------------------------------------

@app.get("/health")
def get_health():
    return store.health()


@app.get("/health/integrations")
def get_health_integrations():
    """Per-integration live round-trip health. Read-only except the Alpaca
    trade-auth check, which authenticates only and never places an order. No
    key value is returned. See api_server/health.py for the safety contract."""
    return health.integrations()


@app.get("/account")
def get_account(mode: str = Query(store.PAPER)):
    return store.account(_mode(mode))


@app.get("/positions")
def get_positions(mode: str = Query(store.PAPER),
                  category: str | None = Query(None)):
    return {"mode": _mode(mode), "category": store.valid_category(category),
            "positions": store.positions(_mode(mode), category)}


@app.get("/orders")
def get_orders(mode: str = Query(store.PAPER), limit: int = Query(50, le=500),
               category: str | None = Query(None)):
    return {"mode": _mode(mode), "category": store.valid_category(category),
            "orders": store.orders(_mode(mode), limit, category)}


@app.get("/trades")
def get_trades(mode: str = Query(store.PAPER), limit: int = Query(200, le=1000),
               category: str | None = Query(None)):
    return {"mode": _mode(mode), "category": store.valid_category(category),
            "trades": store.closed_trades(_mode(mode), limit, category)}


@app.get("/pnl")
def get_pnl(mode: str = Query(store.PAPER)):
    return store.pnl(_mode(mode))


@app.get("/sleeves")
def get_sleeves():
    # Core-satellite allocation panel: live per-sleeve capital + the target split,
    # drift band, hard cap, and a rebalance-due flag. Read-only. No key value.
    return controls.sleeve_state()


@app.get("/sleeves/history")
def get_sleeve_history(sleeve: str | None = Query(None),
                       limit: int = Query(200, le=1000)):
    return {"history": store.sleeve_history(sleeve, limit)}


@app.get("/research/theses")
def get_research_theses(limit: int = Query(100, le=500)):
    # Research feed + satellite positions: each deep-research pass with its thesis.
    return {"theses": store.research_theses(limit)}


# --- Discovery views (READ-ONLY) ---------------------------------------------
# Every route below is a pure read over the mode=ro connection. None writes an
# operational or Level-1 value, none enables live, and none returns a key value.
# Discovery ships DISABLED, so they return empty with enabled=false until an
# operator opts in, which the GUI renders as a clear disabled state rather than
# an empty page that looks broken. An unknown asset_class degrades to "both",
# matching store.valid_category rather than introducing a new error path.

@app.get("/discovery/state")
def get_discovery_state():
    # Summary for the top strip and the sleeve panel: discovery on or off, last
    # pass per asset class, watchlist size, universe sizes, and today's spend
    # against the SEPARATE discovery budget.
    return controls.discovery_state()


@app.get("/discovery/latest")
def get_discovery_latest(asset_class: str | None = Query(None)):
    # The most recent funnel pass per asset class: per-stage counts plus every
    # instrument dropped at each stage with its reason.
    ac = asset_class if asset_class in ("crypto", "equity") else None
    return {"passes": store.discovery_latest(ac),
            "enabled": controls.discovery_enabled()}


@app.get("/discovery/candidates")
def get_discovery_candidates(limit: int = Query(50, le=200)):
    # Current Stage-C survivors with their four-level verdicts and ADVISORY
    # sizing. The engine's hard sleeve cap and the RiskGate rule any real order.
    return {"candidates": store.discovery_candidates(limit),
            "enabled": controls.discovery_enabled()}


@app.get("/watchlist")
def get_watchlist(limit: int = Query(100, le=500),
                  events: int = Query(30, le=200)):
    # The living candidate list both sleeves draw from: why each instrument is
    # on it, its sleeve target, plus recent adds and prunes.
    return {"watchlist": store.watchlist(limit),
            "events": store.watchlist_events(events),
            "enabled": controls.discovery_enabled()}


@app.get("/longterm/positions")
def get_longterm_positions():
    # Open research_satellite positions with their persisted theses: entry date,
    # conviction, target, horizon, invalidation condition, current PnL, and where
    # each position sits against its thesis.
    #
    # Three distinct booleans, kept distinct because they answer different
    # questions and collapsing them would mislead:
    #   strategy_enabled  discovery.long_term_sleeve_enabled (the STRATEGY)
    #   sleeve_config     sleeves.research_satellite_enabled (the SLEEVE, config)
    #   sleeve_toggle     the operator's controls.json toggle for the sleeve
    # A long-term position needs the strategy AND the sleeve. `enabled` is that
    # conjunction, so the GUI has one honest answer to "is this running".
    sleeves = controls.sleeve_state()
    strategy = controls.longterm_state()
    sleeve_config = bool(sleeves.get("research_satellite_config_enabled", False))
    sleeve_toggle = bool(
        sleeves.get("enabled", {}).get("research_satellite", False))
    return {"positions": store.longterm_positions(),
            "enabled": strategy and sleeve_config,
            "strategy_enabled": strategy,
            "sleeve_config_enabled": sleeve_config,
            "sleeve_toggle_enabled": sleeve_toggle}


class SleeveWrite(BaseModel):
    sleeve: str
    enabled: bool


@app.post("/controls/sleeve")
def post_sleeve(body: SleeveWrite):
    # Independent sleeve enable toggle. Validated server-side; control-file write.
    return controls.set_sleeve(body.sleeve, body.enabled)


@app.post("/controls/rebalance")
def post_rebalance():
    # Manual rebalance-now request. The engine rebalances through the normal
    # RiskGate-approved exit path (no forced bypass, no new write path).
    return controls.request_rebalance()


@app.get("/signals")
def get_signals(limit: int = Query(100, le=500),
                category: str | None = Query(None)):
    return store.signals(limit, category)


@app.get("/council")
def get_council():
    return store.council()


@app.get("/whale")
def get_whale():
    return store.whale()


@app.get("/risk")
def get_risk():
    return store.risk_state()


@app.get("/venues")
def get_venues():
    return {"venues": store.venues_status()}


@app.get("/approval")
def get_approval():
    return store.approval()


# --- Credential endpoints (masked read, encrypted write) --------------------

class CredentialWrite(BaseModel):
    name: str
    value: str


@app.get("/credentials")
def get_credentials():
    """Report which venue/data-source keys are set. Values are masked."""
    from account_manager import credentials as creds
    return {"credentials": creds.list_status()}


@app.post("/credentials")
def post_credential(body: CredentialWrite):
    """Save one credential through the encrypted keystore.

    The raw value is written straight to the encrypted store and is never
    logged or echoed. The response confirms the save using only masked status.
    """
    from account_manager import credentials as creds
    try:
        creds.set_credential(body.name, body.value)
    except KeyError:
        return {"ok": False, "error": f"unknown credential: {body.name}"}
    status = next((s for s in creds.list_status()
                   if s["name"] == body.name), None)
    return {"ok": True, "name": body.name, "status": status}


@app.post("/credentials/test")
def post_credential_test(group: str = Query(...),
                         mode: str | None = Query(None)):
    """Offline-safe connection check. Reports whether required keys resolve."""
    from account_manager import credentials as creds
    return creds.validate_connection(group, mode)


# --- WebSocket live stream --------------------------------------------------

@app.websocket("/stream")
async def stream(ws: WebSocket):
    """Push a positions/orders/pnl/events snapshot on a fixed tick.

    Read-only. The client sends its mode once (paper|live); the server replies
    with a fresh snapshot every STREAM_INTERVAL_SECONDS until disconnect.
    """
    await ws.accept()
    mode = store.PAPER
    try:
        try:
            first = await asyncio.wait_for(ws.receive_text(), timeout=0.5)
            mode = store.valid_mode(first.strip())
        except (asyncio.TimeoutError, Exception):
            mode = store.PAPER
        while True:
            await ws.send_json(store.stream_snapshot(mode))
            await asyncio.sleep(STREAM_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return
    except Exception:
        return


# --- Kill switch: read engine state, record an operator halt request --------

class KillRequest(BaseModel):
    requested: bool = True
    reason: str | None = None


@app.get("/kill")
def get_kill():
    """Current engine kill-switch state plus any recorded operator request."""
    return store.kill_state()


@app.post("/kill")
def post_kill(body: KillRequest):
    """Record a durable operator halt request in the control file.

    Safety-positive and read-only on operational tables: this only writes the
    control file and reports state. It cannot un-halt or weaken the RiskGate.
    """
    rec = store.write_kill_request(body.requested, body.reason)
    return {"ok": True, "request": rec, "engine": store.kill_state()}


# --- Controls: validated operator control surface ---------------------------
# Every control validates + clamps server-side, records the change to the events
# log with old/new values, and reuses the Dash weight-override channel for
# weights. STRUCTURAL RULE (asserted in tests): no control writes a Level-1 risk
# value, an operational STATE table, or the RiskGate, and none enables live.

@app.get("/controls")
def get_controls():
    return controls.control_state()


class WeightsWrite(BaseModel):
    weights: dict[str, float]


@app.post("/controls/weights")
def post_weights(body: WeightsWrite):
    return controls.set_weights(body.weights)


class LayerWrite(BaseModel):
    layer: str
    enabled: bool


@app.post("/controls/layer")
def post_layer(body: LayerWrite):
    return controls.set_layer(body.layer, body.enabled)


class SourceWrite(BaseModel):
    layer: str
    source: str


@app.post("/controls/source")
def post_source(body: SourceWrite):
    # Source axis (mock/real), distinct from the enable toggle. Validated
    # server-side; refuses the safety layer. Same control-file write path.
    return controls.set_source(body.layer, body.source)


class FeedClockWrite(BaseModel):
    feed_mode: str
    clock_mode: str


@app.post("/controls/feed_clock")
def post_feed_clock(body: FeedClockWrite):
    # Runtime feed-mode + clock-mode toggle (Task 3). Validated server-side;
    # refuses an unsafe switch away from alpaca_paper with an open position so it
    # never orphans one. Same control-file write path, audited to the event log.
    return controls.set_feed_clock(body.feed_mode, body.clock_mode)


class ModelWrite(BaseModel):
    model: str
    enabled: bool


@app.post("/controls/model")
def post_model(body: ModelWrite):
    return controls.set_model(body.model, body.enabled)


class ToggleWrite(BaseModel):
    enabled: bool


@app.post("/controls/rl")
def post_rl(body: ToggleWrite):
    return controls.set_rl(body.enabled)


@app.post("/controls/auto_promote")
def post_auto_promote(body: ToggleWrite):
    return controls.set_auto_promote(body.enabled)


@app.post("/controls/promote")
def post_promote():
    return controls.request_promote()


@app.post("/controls/rollback")
def post_rollback():
    return controls.request_rollback()


class RegimeWrite(BaseModel):
    symbol: str
    regime: str | None = None


@app.post("/controls/regime")
def post_regime(body: RegimeWrite):
    return controls.set_regime(body.symbol, body.regime)


class BudgetWrite(BaseModel):
    council_daily_budget: int
    per_symbol_cooldown_minutes: int


@app.post("/controls/budget")
def post_budget(body: BudgetWrite):
    return controls.set_budget(body.council_daily_budget,
                               body.per_symbol_cooldown_minutes)


# --- Operational reads (skip feed, run state, day summary, trade detail) -----
# All read-only. None writes an operational or Level-1 value. Bind stays 127.0.0.1.

@app.get("/skips")
def get_skips(limit: int = Query(50, le=200)):
    return {"skips": store.skip_feed(limit)}


@app.get("/runstate")
def get_runstate():
    return store.runstate()


@app.get("/day_summary")
def get_day_summary():
    d = store.day_summary()
    d["estimated_spend_today"] = providers_cost.estimated_day_total()
    return d


@app.get("/providers/cost")
def get_providers_cost():
    """Per-provider balance where available, provider spend where available, and
    local estimated day and month spend always. Never returns a key value."""
    return providers_cost.provider_cost()


@app.get("/trade/{trade_id}")
def get_trade_detail(trade_id: int):
    return store.trade_detail(trade_id)


# --- Engine lifecycle: GUI Start/Stop through the supervisor ----------------
# The supervisor owns the bridge + engine processes and runs the same sequence
# as scripts/start_paper_trading.sh through the shared api_server.stack callable.
# These endpoints never enable live and never route the kill switch: the engine
# reads the kill-request control file itself, independent of the supervisor.

@app.get("/engine/state")
def get_engine_state():
    """Live lifecycle: not_running, starting, warming (with per-symbol warm
    progress), running, stopping. Read-only, never returns a key value."""
    return supervisor.SUPERVISOR.state()


@app.post("/engine/start")
def post_engine_start():
    """Start the warmed paper stack (backfill, warm, bridge, engine), health
    checked between steps. Refuses a second start when one is already running,
    clears a stale lock from a crashed run. Strict mode: an unreachable on-real
    layer fails the start with what is missing."""
    return supervisor.SUPERVISOR.start()


@app.post("/engine/stop")
def post_engine_stop():
    """Graceful shutdown of the bridge + engine the supervisor started. This is
    NOT the kill switch. The safety halt is the kill-request control file the
    engine reads on its own, independent of this endpoint."""
    return supervisor.SUPERVISOR.stop()

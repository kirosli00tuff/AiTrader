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


@app.get("/account")
def get_account(mode: str = Query(store.PAPER)):
    return store.account(_mode(mode))


@app.get("/positions")
def get_positions(mode: str = Query(store.PAPER)):
    return {"mode": _mode(mode), "positions": store.positions(_mode(mode))}


@app.get("/orders")
def get_orders(mode: str = Query(store.PAPER), limit: int = Query(50, le=500)):
    return {"mode": _mode(mode),
            "orders": store.orders(_mode(mode), limit)}


@app.get("/trades")
def get_trades(mode: str = Query(store.PAPER), limit: int = Query(200, le=1000)):
    return {"mode": _mode(mode),
            "trades": store.closed_trades(_mode(mode), limit)}


@app.get("/pnl")
def get_pnl(mode: str = Query(store.PAPER)):
    return store.pnl(_mode(mode))


@app.get("/signals")
def get_signals(limit: int = Query(100, le=500)):
    return store.signals(limit)


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

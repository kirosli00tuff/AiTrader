"""IBKR live-venue adapter (Python side of the bridge).

IBKR is the only real-money path in this project. It connects to a locally run
IB Gateway over a local socket. No IBKR credentials pass through this app. The
operator installs, runs, and authenticates IB Gateway separately. This module
maps an engine order to an IBKR contract plus order, submits it, and reports the
fill back to the C++ core in the flat dict shape the C++ adapter reads.

IBKR live stays disabled behind the approval gate. Nothing here runs unless the
operator enables live in-app and the C++ RiskGate and mode router allow the
order. This module never simulates a fill. A missing IB Gateway or a dropped
socket returns a safe unavailable marker so the C++ side logs it and books
nothing.

ib_insync is the client. It is imported lazily so the bridge and the whole app
run offline with no IBKR dependency installed. Tests inject a fake ib_insync
module, so no real network or socket is ever opened under test.
"""
from __future__ import annotations

import os
import socket

# IB Gateway defaults. 4001 is the IB Gateway live socket. The paper socket is
# 4002, but IBKR handles live only in this project, so live is the default.
IBKR_DEFAULT_HOST = "127.0.0.1"
IBKR_DEFAULT_PORT = 4001

# Distinct client id for engine-placed orders. Keeps this session separate from
# a human trader logged into the same Gateway.
_DEFAULT_CLIENT_ID = 17
_DEFAULT_TIMEOUT = 5.0

# Order statuses that mean the order is not working. Any of these is reported as
# an error so the C++ side logs it and never books a trade.
_DEAD_STATUSES = frozenset(
    {"", "cancelled", "apicancelled", "inactive", "rejected", "pendingcancel"}
)


def _import_ib():
    """Import ib_insync lazily. Raises ImportError if it is not installed."""
    import ib_insync  # noqa: PLC0415  (deliberate lazy import)

    return ib_insync


def _env_host() -> str:
    return os.environ.get("IBKR_HOST") or IBKR_DEFAULT_HOST


def _env_port() -> int:
    raw = os.environ.get("IBKR_PORT")
    if not raw:
        return IBKR_DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        return IBKR_DEFAULT_PORT


def _is_crypto(symbol: str) -> bool:
    s = symbol.strip().upper()
    return "/" in s or s.endswith("-USD") or s.endswith("-USDT")


def _crypto_base(symbol: str) -> str:
    """Return the base asset of a crypto pair. BTC/USD -> BTC, ETH-USD -> ETH."""
    s = symbol.strip().upper()
    for sep in ("/", "-"):
        if sep in s:
            return s.split(sep)[0]
    return s


def build_contract(symbol: str):
    """Map an engine symbol to an IBKR contract.

    Crypto pairs route to the PAXOS venue. Everything else is a US equity on the
    SMART router, priced in USD.
    """
    ibm = _import_ib()
    if _is_crypto(symbol):
        return ibm.Crypto(_crypto_base(symbol), "PAXOS", "USD")
    return ibm.Stock(symbol.strip().upper(), "SMART", "USD")


def build_order(side: str, qty: float, price: float = 0.0):
    """Map an engine order to an IBKR order.

    A positive price produces a limit order at that price. A zero or missing
    price produces a market order. Side maps to BUY or SELL.
    """
    ibm = _import_ib()
    action = "BUY" if str(side).lower() == "buy" else "SELL"
    if price and float(price) > 0:
        return ibm.LimitOrder(action, float(qty), float(price))
    return ibm.MarketOrder(action, float(qty))


def map_order(symbol: str, side: str, qty: float, price: float = 0.0):
    """Return an (IBKR contract, IBKR order) pair for an engine order."""
    return build_contract(symbol), build_order(side, qty, price)


def gateway_reachable(host: str | None = None, port: int | None = None,
                      timeout: float = 2.0) -> bool:
    """Return True if a TCP socket to IB Gateway opens within timeout.

    A raw socket test with no ib_insync dependency. Used by the startup health
    check. Never raises, so a missing Gateway just reports unreachable.
    """
    host = host or _env_host()
    port = int(port or _env_port())
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _connect(ibm, host: str, port: int, client_id: int, timeout: float):
    """Open an IB Gateway session. Caller handles the exception on failure."""
    ib = ibm.IB()
    ib.connect(host, int(port), clientId=int(client_id), timeout=float(timeout))
    return ib


def _safe_disconnect(ib) -> None:
    try:
        ib.disconnect()
    except Exception:  # noqa: BLE001  (best-effort cleanup, never raise)
        pass


def _find_open_trade(ib, order_id: str):
    for trade in ib.openTrades():
        if str(getattr(trade.order, "orderId", "")) == str(order_id):
            return trade
    return None


def place_order(symbol: str, side: str, qty: float, price: float = 0.0,
                host: str | None = None, port: int | None = None,
                client_id: int = _DEFAULT_CLIENT_ID,
                timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """Submit a live order to IB Gateway and report the fill.

    Returns the flat dict the C++ IbkrLiveAdapter reads:
      {"status": "ok", order_id, filled_price, filled_qty, broker_status} on a
      working or filled order, or {"status": "unavailable"|"error", "error": ...}
      on a dropped socket, a rejected order, or bad input. Never simulates.
    """
    if float(qty) <= 0:
        return {"status": "error", "error": "non-positive qty"}
    try:
        ibm = _import_ib()
    except ImportError as exc:
        return {"status": "error", "error": f"ib_insync not installed: {exc}"}

    host = host or _env_host()
    port = int(port or _env_port())
    try:
        ib = _connect(ibm, host, port, client_id, timeout)
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable",
                "error": f"IB Gateway unreachable at {host}:{port}: {exc}"}

    try:
        contract, order = map_order(symbol, side, qty, price)
        try:
            ib.qualifyContracts(contract)
        except Exception:  # noqa: BLE001  (qualify is best-effort)
            pass
        trade = ib.placeOrder(contract, order)
        # Pump the event loop briefly so IB can report status and fills.
        try:
            ib.sleep(min(1.0, float(timeout)))
        except Exception:  # noqa: BLE001
            pass
        st = getattr(trade, "orderStatus", None)
        status_txt = str(getattr(st, "status", "") or "")
        filled = float(getattr(st, "filled", 0.0) or 0.0)
        avg = float(getattr(st, "avgFillPrice", 0.0) or 0.0)
        order_id = str(getattr(getattr(trade, "order", None), "orderId", "") or "")
        if status_txt.lower() in _DEAD_STATUSES:
            return {"status": "error",
                    "error": f"order not working (status={status_txt or 'unknown'})"}
        return {
            "status": "ok",
            "order_id": order_id,
            "filled_price": avg if avg > 0 else float(price or 0.0),
            "filled_qty": filled,
            "broker_status": status_txt,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"IBKR place failed: {exc}"}
    finally:
        _safe_disconnect(ib)


def cancel_order(order_id: str, host: str | None = None, port: int | None = None,
                 client_id: int = _DEFAULT_CLIENT_ID,
                 timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """Cancel a working IBKR order by id. Returns a flat status dict."""
    try:
        ibm = _import_ib()
    except ImportError as exc:
        return {"status": "error", "error": f"ib_insync not installed: {exc}"}

    host = host or _env_host()
    port = int(port or _env_port())
    try:
        ib = _connect(ibm, host, port, client_id, timeout)
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable",
                "error": f"IB Gateway unreachable at {host}:{port}: {exc}"}

    try:
        trade = _find_open_trade(ib, order_id)
        if trade is None:
            return {"status": "error", "error": f"no open order {order_id}"}
        ib.cancelOrder(trade.order)
        try:
            ib.sleep(min(1.0, float(timeout)))
        except Exception:  # noqa: BLE001
            pass
        st = getattr(trade, "orderStatus", None)
        return {"status": "ok", "order_id": str(order_id),
                "broker_status": str(getattr(st, "status", "") or "")}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"IBKR cancel failed: {exc}"}
    finally:
        _safe_disconnect(ib)


def order_status(order_id: str, host: str | None = None, port: int | None = None,
                 client_id: int = _DEFAULT_CLIENT_ID,
                 timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """Report the current status of an IBKR order by id."""
    try:
        ibm = _import_ib()
    except ImportError as exc:
        return {"status": "error", "error": f"ib_insync not installed: {exc}"}

    host = host or _env_host()
    port = int(port or _env_port())
    try:
        ib = _connect(ibm, host, port, client_id, timeout)
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable",
                "error": f"IB Gateway unreachable at {host}:{port}: {exc}"}

    try:
        for trade in ib.trades():
            if str(getattr(trade.order, "orderId", "")) == str(order_id):
                st = getattr(trade, "orderStatus", None)
                return {
                    "status": "ok",
                    "order_id": str(order_id),
                    "broker_status": str(getattr(st, "status", "") or ""),
                    "filled": float(getattr(st, "filled", 0.0) or 0.0),
                    "avg_fill_price": float(getattr(st, "avgFillPrice", 0.0) or 0.0),
                }
        return {"status": "error", "error": f"order {order_id} not found"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"IBKR status failed: {exc}"}
    finally:
        _safe_disconnect(ib)

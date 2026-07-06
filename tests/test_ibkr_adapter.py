"""Tests for the IBKR live adapter (Python side of the bridge).

All IBKR interaction is mocked by injecting a fake ib_insync module into
sys.modules. No real network or socket is ever opened. These tests verify:
  - an engine order maps to the correct IBKR contract and order shape,
  - place / cancel / status call the client correctly,
  - a dropped or refused IB Gateway session fails the order safely and reports
    it (never simulates a fill),
  - the offline reachability probe returns False with no Gateway.
"""
import socket
import sys

import pytest

from execution import ibkr_adapter


# --- Fake ib_insync -------------------------------------------------------


class _Stock:
    def __init__(self, symbol, exchange, currency):
        self.secType = "STK"
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency


class _Crypto:
    def __init__(self, symbol, exchange, currency):
        self.secType = "CRYPTO"
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency


class _LimitOrder:
    def __init__(self, action, totalQuantity, lmtPrice):
        self.orderType = "LMT"
        self.action = action
        self.totalQuantity = totalQuantity
        self.lmtPrice = lmtPrice
        self.orderId = 0


class _MarketOrder:
    def __init__(self, action, totalQuantity):
        self.orderType = "MKT"
        self.action = action
        self.totalQuantity = totalQuantity
        self.orderId = 0


class _OrderStatus:
    def __init__(self, status, filled, avg):
        self.status = status
        self.filled = filled
        self.avgFillPrice = avg


class _Trade:
    def __init__(self, contract, order, status="Filled"):
        self.contract = contract
        self.order = order
        price = getattr(order, "lmtPrice", 0.0) or 100.0
        self.orderStatus = _OrderStatus(status, order.totalQuantity, price)


class _FakeIB:
    """Fake ib_insync.IB. Instances and a shared order book are class-level so a
    test can inspect calls made inside the adapter and share state across the
    separate connections place/cancel/status each open."""

    instances = []
    book = []
    fail_connect = False
    next_status = "Filled"

    def __init__(self):
        self.calls = []
        _FakeIB.instances.append(self)

    def connect(self, host, port, clientId, timeout):
        self.calls.append(("connect", host, port, clientId, timeout))
        if _FakeIB.fail_connect:
            raise ConnectionRefusedError("IB Gateway not running")

    def qualifyContracts(self, contract):
        self.calls.append(("qualify", contract))
        return [contract]

    def placeOrder(self, contract, order):
        order.orderId = len(_FakeIB.book) + 1
        self.calls.append(("placeOrder", contract, order))
        trade = _Trade(contract, order, status=_FakeIB.next_status)
        _FakeIB.book.append(trade)
        return trade

    def cancelOrder(self, order):
        self.calls.append(("cancelOrder", order))
        for t in _FakeIB.book:
            if t.order is order:
                t.orderStatus.status = "Cancelled"

    def openTrades(self):
        return list(_FakeIB.book)

    def trades(self):
        return list(_FakeIB.book)

    def sleep(self, _seconds):
        self.calls.append(("sleep",))

    def disconnect(self):
        self.calls.append(("disconnect",))


class _FakeIbInsync:
    Stock = _Stock
    Crypto = _Crypto
    LimitOrder = _LimitOrder
    MarketOrder = _MarketOrder
    IB = _FakeIB


@pytest.fixture
def fake_ib(monkeypatch):
    _FakeIB.instances = []
    _FakeIB.book = []
    _FakeIB.fail_connect = False
    _FakeIB.next_status = "Filled"
    monkeypatch.setitem(sys.modules, "ib_insync", _FakeIbInsync)
    return _FakeIB


# --- Mapping --------------------------------------------------------------


def test_equity_maps_to_smart_stock_limit_order(fake_ib):
    contract, order = ibkr_adapter.map_order("SPY", "buy", 10, 545.0)
    assert (contract.secType, contract.symbol, contract.exchange,
            contract.currency) == ("STK", "SPY", "SMART", "USD")
    assert (order.orderType, order.action, order.totalQuantity,
            order.lmtPrice) == ("LMT", "BUY", 10.0, 545.0)


def test_crypto_pair_maps_to_paxos_crypto(fake_ib):
    contract, _ = ibkr_adapter.map_order("BTC/USD", "sell", 0.5, 0.0)
    assert (contract.secType, contract.symbol, contract.exchange) == (
        "CRYPTO", "BTC", "PAXOS")


def test_zero_price_maps_to_market_order(fake_ib):
    _, order = ibkr_adapter.map_order("QQQ", "sell", 3, 0.0)
    assert order.orderType == "MKT"
    assert order.action == "SELL"


# --- Place / cancel / status ---------------------------------------------


def test_place_order_calls_client_and_reports_fill(fake_ib):
    res = ibkr_adapter.place_order("SPY", "buy", 10, 545.0,
                                   host="127.0.0.1", port=4001)
    assert res["status"] == "ok"
    assert res["filled_qty"] == 10.0
    assert res["filled_price"] == 545.0
    assert res["broker_status"] == "Filled"
    ib = fake_ib.instances[-1]
    kinds = [c[0] for c in ib.calls]
    assert "connect" in kinds
    assert "placeOrder" in kinds
    assert "disconnect" in kinds  # session always closed


def test_cancel_order_calls_client(fake_ib):
    placed = ibkr_adapter.place_order("SPY", "buy", 5, 100.0)
    oid = placed["order_id"]
    res = ibkr_adapter.cancel_order(oid)
    assert res["status"] == "ok"
    assert res["order_id"] == str(oid)
    ib = fake_ib.instances[-1]
    assert any(c[0] == "cancelOrder" for c in ib.calls)


def test_order_status_reports_book_state(fake_ib):
    placed = ibkr_adapter.place_order("QQQ", "buy", 2, 470.0)
    res = ibkr_adapter.order_status(placed["order_id"])
    assert res["status"] == "ok"
    assert res["broker_status"] == "Filled"
    assert res["filled"] == 2.0


def test_rejected_order_reported_as_error_not_filled(fake_ib):
    _FakeIB.next_status = "Rejected"
    res = ibkr_adapter.place_order("SPY", "buy", 10, 545.0)
    assert res["status"] == "error"
    assert "rejected" in res["error"].lower()


# --- Safety ---------------------------------------------------------------


def test_connection_loss_fails_order_safely(fake_ib):
    _FakeIB.fail_connect = True
    res = ibkr_adapter.place_order("SPY", "buy", 10, 545.0,
                                   host="127.0.0.1", port=4001)
    assert res["status"] == "unavailable"
    assert "unreachable" in res["error"].lower()
    # A failed connect must not leave a placed order in the book.
    assert _FakeIB.book == []


def test_non_positive_qty_refused_before_connect(fake_ib):
    res = ibkr_adapter.place_order("SPY", "buy", 0, 545.0)
    assert res["status"] == "error"
    assert res["error"] == "non-positive qty"
    assert fake_ib.instances == []  # never even connected


def test_gateway_reachable_false_when_no_gateway():
    # A closed local port is unreachable. Real socket, no ib_insync, fast timeout.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    # Port is now closed again; probe must report unreachable, never raise.
    assert ibkr_adapter.gateway_reachable("127.0.0.1", free_port, timeout=0.3) is False

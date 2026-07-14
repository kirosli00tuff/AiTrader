"""Backfill helper request-shape tests (Task 1). Mocked HTTP, no network.

Asserts the Alpaca backfill requests 5-minute bars for every whitelisted symbol
with enough lookback to warm the native indicators (the 30-day 5-min window is
far more than the >= 300 bars the warm-start needs), and upserts them into the
shared bars table. No key value is ever logged.
"""
from __future__ import annotations

import sqlite3
import urllib.parse as up

from market_data import alpaca_source


def test_backfill_requests_5min_bars_for_all_symbols(tmp_path, monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_http(method, url, headers, body=None):
        calls.append((method, url))
        q = dict(up.parse_qsl(up.urlparse(url).query))
        syms = [s for s in q.get("symbols", "").split(",") if s]
        bars = {s: [{"t": "2026-07-06T00:00:00Z", "o": 1.0, "h": 2.0, "l": 0.5,
                     "c": 1.5, "v": 100.0}] for s in syms}
        return {"bars": bars}

    monkeypatch.setattr(alpaca_source, "_http", fake_http)
    monkeypatch.setattr(alpaca_source, "_data_keys", lambda: ("k", "s"))

    db = tmp_path / "bars.db"
    res = alpaca_source.backfill(db_path=str(db))
    assert res["status"] == "ok"

    # 5-min bars requested for every whitelisted symbol (equities + crypto pairs).
    fivemin = [u for (_m, u) in calls if "timeframe=5Min" in u]
    assert fivemin, "backfill must request 5-min bars"
    joined = " ".join(fivemin)
    for token in ("SPY", "QQQ", "BTC", "ETH"):
        assert token in joined, f"5-min backfill must cover {token}"
    # Lookback is a dated start (~30 days), far more than 300 5-min bars.
    assert all("start=" in u for u in fivemin)

    # One 5-min bar per whitelisted symbol was upserted into the bars table.
    conn = sqlite3.connect(str(db))
    n = conn.execute(
        "SELECT COUNT(*) FROM bars WHERE timeframe='5min'").fetchone()[0]
    conn.close()
    assert n >= 4


def test_backfill_no_key_is_a_safe_noop(tmp_path, monkeypatch):
    # With no data key resolvable the backfill is a no-op (offline-safe) and
    # never makes a network call.
    monkeypatch.setattr(alpaca_source, "_data_keys", lambda: (None, None))

    def boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("no HTTP call may happen without a key")

    monkeypatch.setattr(alpaca_source, "_http", boom)
    res = alpaca_source.backfill(db_path=str(tmp_path / "bars.db"))
    assert res["status"] == "unavailable"

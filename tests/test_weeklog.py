"""Tests for the week-review digest (ops/weeklog.py).

Seed a temp SQLite database with known rows and assert the digest computes the
right counts and PnL, the near-miss table includes only blocks inside the band,
the summary marks the success criteria correctly against thresholds, the job
appends without clobbering prior sections, and no key or credential ever reaches
the file. Read-only over the DB, no network.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ops import weeklog

DAY_START = datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc)
DAY_END = datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc)


def _init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    with open("storage/schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def _trade(conn, ts, symbol, outcome, pnl, fee=0.05, category="equity",
           sleeve="quant_core", side="buy", qty=1.0, price=100.0):
    conn.execute(
        "INSERT INTO trades (ts,venue,symbol,market,category,side,qty,price,"
        "notional,fee,mode,pnl,outcome,sleeve) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, "alpaca", symbol, "us_equity", category, side, qty, price,
         qty * price, fee, "paper", pnl, outcome, sleeve))


def _event(conn, ts, kind, symbol=None, severity="info", message="m", payload=None):
    conn.execute(
        "INSERT INTO events (ts,kind,venue,symbol,severity,message,payload_json) "
        "VALUES (?,?,?,?,?,?,?)",
        (ts, kind, "alpaca", symbol, severity, message,
         json.dumps(payload) if payload is not None else None))


def _seed(path: str) -> None:
    conn = _init_db(path)
    # Trades: 1 open entry, 3 closed (2 win, 1 loss). Known PnL and fees.
    _trade(conn, "2026-07-10T14:00:00Z", "SPY", "open", None, fee=0.01)
    _trade(conn, "2026-07-10T15:00:00Z", "SPY", "win", 12.0, fee=0.02)
    _trade(conn, "2026-07-10T16:00:00Z", "QQQ", "loss", -4.0, fee=0.03)
    _trade(conn, "2026-07-10T17:00:00Z", "BTC/USD", "win", 30.0, fee=0.05,
           category="crypto")
    # Entry-reason lookup source for the best trade.
    _event(conn, "2026-07-10T13:59:00Z", "trade_entry", "BTC/USD",
           payload={"factor": "momentum", "regime": "trending"})
    # risk_block events: one IN band (near-miss), one OUT of band, one empty.
    _event(conn, "2026-07-10T14:30:00Z", "risk_block", "SPY", severity="warn",
           message="Native entry blocked: confidence below min",
           payload={"reason": "confidence below min", "confidence": 0.61,
                    "min_confidence": 0.65, "agreement": 2, "tier": "fast",
                    "council_ran": "no", "symbol": "SPY"})       # gap 0.04 -> in band
    _event(conn, "2026-07-10T14:40:00Z", "risk_block", "QQQ", severity="warn",
           message="blocked", payload={"reason": "confidence below min",
                                       "confidence": 0.40, "min_confidence": 0.65,
                                       "tier": "council", "council_ran": "yes",
                                       "symbol": "QQQ"})           # gap 0.25 -> out
    _event(conn, "2026-07-10T14:50:00Z", "risk_block", "SPY", severity="warn",
           message="blocked", payload=None)                       # empty -> anomaly
    conn.commit()
    conn.close()


def test_digest_counts_and_pnl(tmp_path):
    db = str(tmp_path / "seed.db")
    _seed(db)
    d = weeklog.build_digest(db, DAY_START, DAY_END)
    t = d["trades"]
    assert t["n_total"] == 4
    assert t["n_entries"] == 1
    assert t["n_closed"] == 3
    assert t["n_wins"] == 2 and t["n_losses"] == 1
    assert t["win_rate"] == round(200 / 3, 1)          # 2 of 3
    # net = 12 - 4 + 30 = 38; gross = net + closed fees (0.02+0.03+0.05 = 0.10)
    assert t["net_pnl"] == 38.0
    assert t["gross_pnl"] == 38.1
    assert t["by_symbol"]["SPY"] == 2
    assert t["best"]["symbol"] == "BTC/USD" and t["best"]["pnl"] == 30.0
    assert t["best"]["entry_reason"] == "momentum (trending)"
    assert t["worst"]["symbol"] == "QQQ" and t["worst"]["pnl"] == -4.0


def test_near_miss_band_only(tmp_path):
    db = str(tmp_path / "seed.db")
    _seed(db)
    d = weeklog.build_digest(db, DAY_START, DAY_END)
    nm = d["blocks"]["near_misses"]
    # Only the 0.04-gap SPY block is in the 0.10 band; the 0.25-gap QQQ is not.
    assert len(nm) == 1
    assert nm[0]["symbol"] == "SPY"
    assert nm[0]["confidence"] == 0.61 and nm[0]["min_confidence"] == 0.65
    assert nm[0]["tier"] == "fast" and nm[0]["council_ran"] == "no"
    # The empty-payload block is flagged as an anomaly, not a near-miss.
    assert d["blocks"]["empty_payloads"] == 1
    assert any("empty payload" in a for a in d["anomalies"])


def test_sessions_tag_crypto(tmp_path):
    db = str(tmp_path / "seed.db")
    _seed(db)
    d = weeklog.build_digest(db, DAY_START, DAY_END)
    # The BTC/USD fill at 17:00Z falls in the NY window (13:30-20:00Z).
    assert d["sessions"]["counts"].get("NY") == 1
    assert d["sessions"]["pnl"].get("NY") == 30.0


def test_summary_marks_criteria_against_thresholds(tmp_path):
    db = str(tmp_path / "seed.db")
    _seed(db)
    # Few closed trades -> the >=40 fills criterion is NOT met.
    week = weeklog.build_digest(db, DAY_START, DAY_END)
    crit = {c["name"]: c["status"] for c in weeklog.evaluate_success_criteria(week)}
    fills = "Closed fills >= 40 quant_core over the week"
    drawdown = "Drawdown within Level-1 (no daily-loss kill breach)"
    cost = "Combined API spend at/under $100/month ceiling"
    assert crit[fills] == "not met"          # only 3 closed
    assert crit[drawdown] == "met"           # no kill-switch events seeded
    assert crit[cost] == "met"               # no council calls -> $0 est

    # Construct a week with >=40 closed to flip the fills criterion to met.
    big = {**week, "trades": {**week["trades"], "n_closed": 45,
                              "by_sleeve": {"quant_core": 45}}}
    crit_big = {c["name"]: c["status"]
                for c in weeklog.evaluate_success_criteria(big)}
    assert crit_big[fills] == "met"


def test_append_does_not_clobber_prior_sections(tmp_path):
    db = str(tmp_path / "seed.db")
    _seed(db)
    path = str(tmp_path / "WEEKLOG.md")
    weeklog.append_daily_digest(db, path, end=DAY_END)
    weeklog.append_week_summary(db, path, end=DAY_END)
    text = open(path, encoding="utf-8").read()
    # Header appears once, both sections are present.
    assert text.count("# Week-Review Log") == 1
    assert "daily digest" in text
    assert "Week summary" in text
    # A second daily append keeps the first section intact.
    weeklog.append_daily_digest(db, path, end=DAY_END)
    text2 = open(path, encoding="utf-8").read()
    assert text2.count("# Week-Review Log") == 1
    assert text2.count("### Trades") >= 2      # two daily sections now


def test_no_raw_payload_leaks_to_file(tmp_path):
    db = str(tmp_path / "seed.db")
    _seed(db)
    # Seed an event whose payload carries a distinctive canary value (a stand-in
    # for any sensitive field a payload might hold). The digest renders only
    # specific whitelisted fields, never a raw payload, so the canary must never
    # reach the file. This proves no key or credential value can leak through.
    canary = "CANARY-RAW-PAYLOAD-MUST-NOT-APPEAR-9x8y7z"
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO events (ts,kind,venue,symbol,severity,message,payload_json) "
        "VALUES (?,?,?,?,?,?,?)",
        ("2026-07-10T18:00:00Z", "control_change", "alpaca", "SPY", "info",
         "rotate", json.dumps({"sensitive_field": canary})))
    conn.commit()
    conn.close()
    path = str(tmp_path / "WEEKLOG.md")
    weeklog.append_daily_digest(db, path, end=DAY_END)
    weeklog.append_week_summary(db, path, end=DAY_END)
    text = open(path, encoding="utf-8").read()
    assert canary not in text
    assert "sensitive_field" not in text

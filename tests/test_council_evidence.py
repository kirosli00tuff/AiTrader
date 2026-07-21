"""The 2026-07-20 council evidence contract.

Pins: the omission rule (no field renders without a real source, absent is
omitted not zeroed, unknown keys never render), units on every rendered field,
the anchored confidence scale and disclosed threshold, flat framed as
abstention, the mode split (short-term and long-term render differently),
reasoning before verdict in the schema, and per-provider persistence with
replay. No network, nothing binds.
"""
from __future__ import annotations

import json
import sqlite3

from llm_consensus import consensus
from llm_consensus.evidence import (ALLOWED_FIELDS, gather_evidence,
                                    render_user_prompt)
from llm_consensus.gate import GATE_SYSTEM_PROMPT, AlwaysProceedGate
from llm_consensus.persist import load_evaluation, replay_prompt
from llm_consensus.prompts import (long_term_system, prompt_mode,
                                   short_term_system, system_prompt_for)
from llm_consensus.providers import OpenAIProvider, build_user_prompt
from llm_consensus.verdicts import ModelVerdict, verdict_from_payload
from discovery.evaluate import market_state_from

CFG = "config/default_config.yaml"

# The engine's /score/llm payload shape, fabricated fields included.
ENGINE_STATE = {
    "symbol": "BTC/USD", "venue": "alpaca", "factor": "llm_primary",
    "price": 64000.5, "ret_5": 0.0012, "volatility": 0.0018,
    "imbalance": -0.4173, "catalyst": 0.286,
}


def _seed_db(path, *, source="real_feed", bars=300, with_position=False):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE bars (id INTEGER PRIMARY KEY, venue TEXT, "
                 "symbol TEXT, timeframe TEXT, timestamp TEXT, open REAL, "
                 "high REAL, low REAL, close REAL, volume REAL, source TEXT)")
    conn.execute("CREATE TABLE regime_state (symbol TEXT PRIMARY KEY, "
                 "regime TEXT, adx REAL, rvol REAL, updated_ts TEXT, "
                 "active_factor TEXT)")
    conn.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, venue TEXT, "
                 "symbol TEXT, market TEXT, category TEXT, side TEXT, "
                 "qty REAL, avg_price REAL, notional REAL, opened_ts TEXT, "
                 "unrealized_pnl REAL, sleeve TEXT)")
    for i in range(bars):
        ts = f"2026-07-20T{i // 12:02d}:{(i % 12) * 5:02d}:00Z"
        px = 100.0 + i * 0.01
        conn.execute("INSERT INTO bars (venue, symbol, timeframe, timestamp, "
                     "open, high, low, close, volume, source) "
                     "VALUES ('alpaca','BTC/USD','5min',?,?,?,?,?,?,?)",
                     (ts, px, px + 0.1, px - 0.1, px, 10.0, source))
    conn.execute("INSERT INTO regime_state VALUES ('BTC/USD','trending',"
                 "31.2,0.0021,'2026-07-20T19:00:00Z','momentum')")
    if with_position:
        conn.execute("INSERT INTO positions (venue, symbol, market, category, "
                     "side, qty, avg_price, notional, opened_ts, "
                     "unrealized_pnl, sleeve) VALUES ('alpaca','BTC/USD',"
                     "'BTC-USD','crypto','buy',0.5,63000.0,31500.0,"
                     "'2026-07-19T10:00:00Z',12.5,'quant_core')")
    conn.commit()
    conn.close()


# --- TASK 1: the omission rule ------------------------------------------------

def test_fabricated_engine_fields_never_render():
    prompt = build_user_prompt(ENGINE_STATE)
    assert "imbalance" not in prompt
    assert "catalyst" not in prompt
    assert "ret_5" not in prompt and "return_5" not in prompt
    assert "volatility" not in prompt


def test_absent_field_omitted_never_zeroed():
    crypto = market_state_from({"price": 0.37, "change_pct": 7.05,
                                "high": 0.38, "low": 0.35})
    prompt = render_user_prompt({"symbol": "LDO/USD", **crypto})
    assert "news_sentiment" not in prompt
    equity = market_state_from({"price": 515.0, "change_pct": 4.0,
                                "high": 522.0, "low": 506.0,
                                "sentiment_score": 0.62})
    prompt2 = render_user_prompt({"symbol": "AMD", **equity})
    assert "news_sentiment: 0.62" in prompt2
    assert "0.5 is neutral" in prompt2


def test_unknown_field_never_renders_guard():
    prompt = render_user_prompt({"symbol": "X", "price": 10.0,
                                 "future_metric": 123.456,
                                 "order_book_imbalance": 0.0})
    assert "future_metric" not in prompt
    assert "123.456" not in prompt
    assert "order_book_imbalance" not in prompt


def test_every_allowlist_entry_declares_units():
    for key, (label, units) in ALLOWED_FIELDS.items():
        assert label and units and len(units) >= 3, key


def test_no_measured_fields_says_so_instead_of_zeros():
    prompt = render_user_prompt({"symbol": "X"})
    assert "no measured fields" in prompt
    assert "0.0" not in prompt


# --- TASK 2: evidence with units ----------------------------------------------

def test_bar_regime_position_evidence_rendered_with_units(tmp_path):
    db = str(tmp_path / "e.db")
    _seed_db(db, with_position=True)
    ev = gather_evidence("BTC/USD", db)
    prompt = render_user_prompt({"symbol": "BTC/USD", "price": 103.0,
                                 "_evidence": ev})
    assert "closes_5min" in prompt and "five-minute closes" in prompt
    assert "return_24h" in prompt and "percent over the last 288" in prompt
    assert "regime: trending" in prompt and "ADX" in prompt
    assert "momentum" in prompt
    assert "open_position: buy" in prompt and "USD" in prompt


def test_volume_only_from_backfill_provenance(tmp_path):
    live = str(tmp_path / "live.db")
    _seed_db(live, source="real_feed")
    assert "volume_24h_base" not in gather_evidence("BTC/USD", live)
    back = str(tmp_path / "back.db")
    _seed_db(back, source="backfill")
    ev = gather_evidence("BTC/USD", back)
    assert "volume_24h_base" in ev
    assert "volume_24h" in render_user_prompt(
        {"symbol": "BTC/USD", "_evidence": ev})


def test_no_position_is_a_real_statement(tmp_path):
    db = str(tmp_path / "p.db")
    _seed_db(db, with_position=False)
    prompt = render_user_prompt({"symbol": "BTC/USD",
                                 "_evidence": gather_evidence("BTC/USD", db)})
    assert "open_position: none" in prompt


def test_missing_db_yields_empty_evidence_never_raises(tmp_path):
    assert gather_evidence("BTC/USD", str(tmp_path / "absent.db")) == {}


# --- TASK 3: anchors, threshold, abstention -----------------------------------

def test_confidence_anchors_present_ends_and_middle():
    s = short_term_system(0.60)
    assert "0.50 means a coin flip" in s
    assert "0.60 means a modest real edge" in s
    assert "0.70 means a strong edge" in s
    assert "1.00 means certainty" in s
    assert "Below 0.50 means you believe the opposite direction" in s


def test_threshold_disclosed_from_config():
    s = system_prompt_for({"mode": "short_term"}, CFG)
    assert "reaches 0.60" in s
    lt = system_prompt_for({"mode": "long_term"}, CFG)
    assert "reaches 0.70" in lt


def test_flat_framed_as_legitimate_abstention():
    s = short_term_system(0.60)
    assert "deliberate abstention" in s
    assert "not a low-confidence long or short" in s


def test_gate_prompt_carries_absence_rule_and_reason_first():
    assert "Absence is not evidence" in GATE_SYSTEM_PROMPT
    assert GATE_SYSTEM_PROMPT.index('"reason"') < GATE_SYSTEM_PROMPT.index(
        '"proceed"')


# --- TASK 4: names match contents ----------------------------------------------

def test_field_names_match_contents():
    out = market_state_from({"price": 100.0, "change_pct": 4.0,
                             "high": 110.0, "low": 95.0})
    assert out["daily_return_pct"] == 4.0
    assert out["intraday_range_pct"] == 15.0
    prompt = render_user_prompt({"symbol": "X", **out})
    assert "daily_return: +4.00 (percent" in prompt
    assert "intraday_range: 15 (percent of price" in prompt


# --- TASK 5: the mode split -----------------------------------------------------

def test_modes_render_different_system_and_user():
    state = {"symbol": "AMD", "price": 515.0, "daily_return_pct": 4.0}
    short_sys = system_prompt_for({**state, "mode": "short_term"}, CFG)
    long_sys = system_prompt_for({**state, "mode": "long_term"}, CFG)
    assert short_sys != long_sys
    assert "MULTI-WEEK HOLDING THESIS" in long_sys
    assert "IMMEDIATE setup" in short_sys
    for key in ('"target_view"', '"horizon_weeks"', '"invalidation"'):
        assert key in long_sys and key not in short_sys
    short_user = render_user_prompt({**state, "mode": "short_term"})
    long_user = render_user_prompt({**state, "mode": "long_term"})
    assert short_user != long_user
    assert "multi-week holding thesis" in long_user


def test_legacy_deep_research_maps_to_long_term():
    assert prompt_mode({"mode": "deep_research"}) == "long_term"
    assert prompt_mode({}) == "short_term"


def test_long_mode_renders_fundamentals_and_catalyst():
    prompt = render_user_prompt({
        "symbol": "AMD", "mode": "long_term", "price": 515.0,
        "fundamentals": {"quality": 0.62, "roe_ttm": 18.4, "pe_ttm": 41.0},
        "catalyst_detail": "earnings: earnings 2026-07-28, inside 21d"})
    assert "quality 0.62" in prompt and "roe_ttm 18.4" in prompt
    assert "catalyst: earnings" in prompt
    short = render_user_prompt({
        "symbol": "AMD", "mode": "short_term", "price": 515.0,
        "fundamentals": {"quality": 0.62}})
    assert "quality" not in short


def test_provider_request_uses_mode_system_prompt():
    p = OpenAIProvider(name="llm_primary", model_id="gpt-5.5", cfg_path=CFG)
    _, _, payload = p._request({**ENGINE_STATE, "mode": "long_term"}, "REDACTED")
    assert "MULTI-WEEK" in payload["messages"][0]["content"]
    _, _, payload2 = p._request(ENGINE_STATE, "REDACTED")
    assert "IMMEDIATE setup" in payload2["messages"][0]["content"]


# --- TASK 6: reasoning before verdict -------------------------------------------

def test_schema_orders_reasoning_before_verdict():
    for s in (short_term_system(0.6), long_term_system(0.7)):
        schema = s[s.index("Respond with a SINGLE JSON object"):]
        assert schema.index('"reasoning"') < schema.index(
            '"direction"') < schema.index('"confidence"')


def test_parser_reads_reasoning_and_extras():
    v = verdict_from_payload("llm_primary", {
        "reasoning": "trend up on rising volume", "direction": "long",
        "confidence": 0.72, "edge": 0.02, "target_view": "+15 percent",
        "horizon_weeks": 6, "invalidation": "close below 90"})
    assert v.rationale == "trend up on rising volume"
    assert v.extra["horizon_weeks"] == 6
    old = verdict_from_payload("llm_primary", {
        "direction": "short", "confidence": 0.6, "rationale": "old shape"})
    assert old.rationale == "old shape" and old.extra == {}


# --- TASK 7: persistence and replay ----------------------------------------------

class _StubProvider:
    def __init__(self, name, bias, conf, rationale):
        self.name, self.weight = name, 0.2
        self._v = ModelVerdict(model=name, bias=bias, confidence=conf,
                               edge=0.01, verdict="buy" if bias > 0 else "hold",
                               rationale=rationale, source="real",
                               model_id=f"{name}-model")

    def score(self, state):
        return self._v


def test_per_provider_state_persists_and_replays(tmp_path):
    db = str(tmp_path / "persist.db")
    _seed_db(db)
    providers = [_StubProvider("llm_primary", 0.7, 0.7, "clear up trend"),
                 _StubProvider("llm_secondary", 0.0, 0.6, "no edge"),
                 _StubProvider("llm_tertiary", -0.55, 0.55, "fading")]
    state = {"symbol": "BTC/USD", "venue": "alpaca", "price": 103.0,
             "daily_return_pct": 2.0, "mode": "short_term", "db": db}
    result = consensus(state, providers=providers, gate=AlwaysProceedGate(),
                       cfg_path=CFG)
    conn = sqlite3.connect(db)
    eval_id = conn.execute("SELECT MAX(id) FROM council_eval").fetchone()[0]
    rows = conn.execute("SELECT slot, direction, abstained, rationale FROM "
                        "council_eval_provider WHERE eval_id=?",
                        (eval_id,)).fetchall()
    conn.close()
    assert eval_id is not None and len(rows) == 3
    by_slot = {r[0]: r for r in rows}
    assert by_slot["llm_primary"][1] == "long"
    assert by_slot["llm_secondary"][2] == 1  # hold persisted as abstained
    assert by_slot["llm_secondary"][3] == "no edge"
    assert by_slot["llm_tertiary"][1] == "short"

    stored = load_evaluation(db, eval_id)
    assert stored["providers"][1]["abstained"] is True
    assert stored["directional_count"] == result.directional_count == 2
    sys_now, user_now = replay_prompt(stored, cfg_path=CFG)
    assert sys_now == stored["system_prompt"]
    assert user_now == stored["user_prompt"]
    assert json.loads(json.dumps(stored["state"]))  # state round-trips


def test_no_db_key_means_no_persistence_and_no_enrichment(tmp_path):
    providers = [_StubProvider("llm_primary", 0.5, 0.5, "x")]
    state = {"symbol": "BTC/USD", "price": 103.0}
    result = consensus(state, providers=providers, gate=AlwaysProceedGate(),
                       cfg_path=CFG)
    assert result.per_model and "_evidence" not in state

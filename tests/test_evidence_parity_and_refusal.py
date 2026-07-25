"""One evidence builder, a bounded bar series, and a refusal that saves spend.

The 2026-07-25 evidence is the spec. Ten consecutive discovery Stage-C
evaluations returned all-abstain (directional_count 0, abstentions 3, verdict
hold) on ten different symbols, every provider naming the same cause in
writing: no 5-minute closes, no volume, no regime, no multi-hour returns. The
discovery state_json measured 364 to 380 characters with
``"_evidence": {"position": null}`` as its entire evidence block. On LDO/USD,
eval 49, the prompt carried twelve 5-minute closes frozen at 0.3863 beside a
last price of 0.3749, a 3.0 percent gap, with rvol 0 against ADX 97.1.

These tests pin four properties:
  * both council paths assemble evidence through ONE builder, and the
    discovery adapter no longer computes rendered fields of its own
  * a field with no measurement is omitted, never zeroed
  * a stale or price-inconsistent series is refused, and so is the regime read
    computed from it
  * the below-minimum refusal fires, records its reason, spends nothing, and
    NEVER suppresses a call whose evidence is adequate

Two are mutation-tested: reverting the parity or the staleness bound must turn
the suite red. No network, no bind, no production database.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from discovery.evaluate import build_verdict, market_state_from
from llm_consensus import consensus
from llm_consensus.evidence import (MAX_BAR_AGE_SECONDS,
                                    MAX_PRICE_DIVERGENCE_PCT,
                                    MIN_SERIES_CLOSES, bar_series_integrity,
                                    build_state, evidence_refusal,
                                    gather_evidence, quote_evidence,
                                    render_user_prompt)
from llm_consensus.gate import AlwaysProceedGate, PriorScreenGate
from llm_consensus.persist import recent_refusals
from llm_consensus.verdicts import ModelVerdict

CFG = "config/default_config.yaml"

# The anchor is the REAL clock, taken once at import. consensus() resolves its
# own "now" internally and takes no injection, so a fixture pinned to a fixed
# date would read every seeded series as years stale the moment it went
# through the real call path. The pure-function tests below still pass their
# own fixed timestamps, which is where a frozen clock belongs.
NOW = datetime.now(timezone.utc)


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed(path, *, symbol="BTC/USD", bars=300, newest_age_seconds=60,
          close=100.0, drift=0.0, source="real_feed",
          volume_source="venue_bar", regime=True, now=NOW):
    """A database carrying one symbol's series, its regime, and no position."""
    newest = now - timedelta(seconds=newest_age_seconds)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE bars (id INTEGER PRIMARY KEY, venue TEXT, "
                 "symbol TEXT, timeframe TEXT, timestamp TEXT, open REAL, "
                 "high REAL, low REAL, close REAL, volume REAL, source TEXT, "
                 "volume_source TEXT)")
    conn.execute("CREATE TABLE regime_state (symbol TEXT PRIMARY KEY, "
                 "regime TEXT, adx REAL, rvol REAL, updated_ts TEXT, "
                 "active_factor TEXT)")
    conn.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, venue TEXT, "
                 "symbol TEXT, side TEXT, qty REAL, avg_price REAL, "
                 "opened_ts TEXT, unrealized_pnl REAL)")
    for i in range(bars):
        stamp = _stamp(newest - timedelta(seconds=(bars - 1 - i) * 300))
        px = round(close + i * drift, 6)
        conn.execute("INSERT INTO bars (venue, symbol, timeframe, timestamp, "
                     "open, high, low, close, volume, source, volume_source) "
                     "VALUES ('alpaca',?,'5min',?,?,?,?,?,?,?,?)",
                     (symbol, stamp, px, px, px, px, 7.5, source,
                      volume_source))
    if regime:
        conn.execute("INSERT INTO regime_state VALUES (?,'trending',97.1,0.0,"
                     "?,'momentum')", (symbol, _stamp(newest)))
    conn.commit()
    conn.close()
    return path


# --- TASK 1: one builder, both paths ------------------------------------------

def test_both_council_paths_assemble_evidence_through_one_builder(tmp_path):
    """The same observation and the same database render byte-identically.

    The trading path's observation comes from the engine's MarketState and the
    discovery path's from the Stage-A Finnhub snapshot. Once each is named in
    the canonical vocabulary, ONE builder turns it into evidence, so a
    discovery candidate is judged on the same fields as a held position.
    """
    db = _seed(str(tmp_path / "one.db"))

    # The discovery path: a Finnhub snapshot through the adapter.
    discovery_observation = market_state_from(
        {"price": 100.0, "change_pct": 2.5, "high": 101.0, "low": 98.0})
    # The trading path: the engine's payload, fabricated fields included.
    trading_observation = {"price": 100.0, "daily_change_pct": 2.5,
                           "day_high": 101.0, "day_low": 98.0,
                           "factor": "council", "imbalance": -0.16,
                           "catalyst": 0.459, "ret_5": 0.00041}

    prompts = set()
    for observation in (discovery_observation, trading_observation):
        built = build_state({"symbol": "BTC/USD", "venue": "alpaca",
                             **observation}, db_path=db, now=NOW)
        prompts.add(render_user_prompt(built))
    assert len(prompts) == 1, "two paths, two prompts: the builder is not one"

    rendered = prompts.pop()
    # And the discovery candidate really does get the full field set now.
    for field in ("price", "daily_return", "intraday_range", "closes_5min",
                  "return_1h", "return_4h", "return_24h", "volume_24h",
                  "regime", "open_position"):
        assert field in rendered, field


def test_mutation_a_second_assembler_in_discovery_breaks_parity():
    """MUTATION: revert market_state_from to computing rendered fields.

    Before 2026-07-25 the adapter emitted daily_return_pct and
    intraday_range_pct itself. Reverting means the adapter produces rendered
    keys, which this refuses: an adapter that renders is a second assembler,
    and two assemblers under one template is the whole defect.
    """
    observation = market_state_from(
        {"price": 100.0, "change_pct": 4.0, "high": 110.0, "low": 95.0})
    rendered_keys = {"daily_return_pct", "intraday_range_pct"}
    assert not (rendered_keys & set(observation)), (
        "the discovery adapter is computing rendered fields again; that is a "
        "second assembler beside evidence.build_state")
    assert observation["daily_change_pct"] == 4.0
    assert observation["day_high"] == 110.0 and observation["day_low"] == 95.0

    # The mutation's observable consequence: the builder is what renders them.
    built = build_state({"symbol": "X", **observation})
    assert built["daily_return_pct"] == 4.0
    assert built["intraday_range_pct"] == 15.0


def test_an_unmeasured_field_is_omitted_never_zeroed():
    """Absence renders as absence, on every field, in both directions."""
    nothing = quote_evidence({"symbol": "X"})
    assert nothing == {}, nothing

    # A non-positive price is not a measurement of zero, it is no measurement.
    assert quote_evidence({"price": 0.0}) == {}
    assert quote_evidence({"price": -1.0}) == {}
    # A degenerate day range (high not above low) is not a zero-width range.
    assert "intraday_range_pct" not in quote_evidence(
        {"price": 100.0, "day_high": 99.0, "day_low": 99.0})
    # A genuine zero daily change IS a measurement and stays.
    assert quote_evidence({"price": 100.0, "daily_change_pct": 0.0})[
        "daily_return_pct"] == 0.0

    prompt = render_user_prompt({"symbol": "X", "price": 100.0})
    for absent in ("daily_return", "intraday_range", "news_sentiment",
                   "closes_5min", "regime", "volume_24h"):
        assert absent not in prompt, absent


def test_volume_renders_only_from_venue_reported_provenance(tmp_path):
    """Volume has its own provenance axis, and NULL is not venue-reported."""
    good = _seed(str(tmp_path / "v_ok.db"), volume_source="venue_bar")
    assert "volume_24h_base" in gather_evidence("BTC/USD", good, price=100.0,
                                                now=NOW)
    for label in (None, "fabricated_zeroed", "synthetic", "unknown"):
        db = _seed(str(tmp_path / f"v_{label}.db"), volume_source=label)
        assert "volume_24h_base" not in gather_evidence(
            "BTC/USD", db, price=100.0, now=NOW), label


# --- TASK 2: the bar series must agree with the price beside it ---------------

def test_a_fresh_consistent_series_is_accepted():
    closes = [100.0 + i * 0.01 for i in range(12)]
    verdict = bar_series_integrity(closes=closes, newest_ts=_stamp(
        NOW - timedelta(seconds=60)), price=100.11, now=NOW)
    assert verdict.ok and verdict.reason == ""
    assert 59 <= verdict.age_seconds <= 61


def test_the_ldo_series_is_refused_on_both_bounds():
    """LDO/USD eval 49, reproduced from the recorded numbers.

    Twelve closes frozen at 0.3863, newest bar 2026-07-24T01:05:05Z, price
    0.3749 at an eval timestamp of 2026-07-25T00:00:42Z. It fails freshness by
    23 hours and price consistency by 3.0 percent, and either alone refuses it.
    """
    eval_ts = datetime(2026, 7, 25, 0, 0, 42, tzinfo=timezone.utc)
    frozen = [0.3863] * 12

    stale = bar_series_integrity(closes=frozen,
                                 newest_ts="2026-07-24T01:05:05Z",
                                 price=0.3749, now=eval_ts)
    assert not stale.ok and stale.reason == "stale"
    assert stale.age_seconds == pytest.approx(82537, abs=2)  # 22h55m

    # Same series, same price, made fresh: the price bound alone still refuses.
    inconsistent = bar_series_integrity(
        closes=frozen, newest_ts=_stamp(eval_ts - timedelta(seconds=60)),
        price=0.3749, now=eval_ts)
    assert not inconsistent.ok
    assert inconsistent.reason == "price_inconsistent"
    assert inconsistent.divergence_pct == pytest.approx(2.95, abs=0.05)


def test_a_short_series_is_a_fragment_not_a_tape():
    short = bar_series_integrity(
        closes=[100.0] * (MIN_SERIES_CLOSES - 1),
        newest_ts=_stamp(NOW - timedelta(seconds=60)), price=100.0, now=NOW)
    assert not short.ok and short.reason == "too_short"


def test_an_unreadable_timestamp_is_stale_not_fresh():
    """An age that cannot be established fails the bound rather than passing
    it: the safe direction for a claim about currency."""
    verdict = bar_series_integrity(closes=[100.0] * 12, newest_ts="not a date",
                                   price=100.0, now=NOW)
    assert not verdict.ok and verdict.reason == "stale"


def test_a_refused_series_takes_its_derived_numbers_with_it(tmp_path):
    """The window returns, the volume, and the regime all come off the same
    tape, so a refused series must not leave them rendering as current."""
    db = _seed(str(tmp_path / "stale.db"), newest_age_seconds=24 * 3600)
    evidence = gather_evidence("BTC/USD", db, price=100.0, now=NOW)
    assert "closes_5min" not in evidence
    for derived in ("return_1h_pct", "return_4h_pct", "return_24h_pct",
                    "volume_24h_base", "regime"):
        assert derived not in evidence, derived
    assert evidence["bars_refused"]["reason"] == "stale"
    # The position is a separate measurement and is unaffected.
    assert evidence["position"] is None

    prompt = render_user_prompt({"symbol": "BTC/USD", "price": 100.0,
                                 "_evidence": evidence})
    assert "closes_5min" not in prompt and "regime" not in prompt
    assert "bars_refused" not in prompt  # the reason is recorded, not rendered


def test_mutation_removing_the_staleness_bound_lets_the_frozen_tape_through(
        tmp_path, monkeypatch):
    """MUTATION: widen the bound past any age and the stale series renders.

    This is what the code did before 2026-07-25, and it is what put a 23-hour
    old frozen tape into a prompt beside a live price. The bound is what
    refuses it, proven by removing the bound and watching it come back.
    """
    db = _seed(str(tmp_path / "mut.db"), newest_age_seconds=24 * 3600)
    assert "closes_5min" not in gather_evidence("BTC/USD", db, price=100.0,
                                                now=NOW)

    monkeypatch.setattr("llm_consensus.evidence.MAX_BAR_AGE_SECONDS", 10 ** 9)
    reverted = gather_evidence("BTC/USD", db, price=100.0, now=NOW)
    assert "closes_5min" in reverted, (
        "MAX_BAR_AGE_SECONDS is not what refuses the stale series")


def test_mutation_removing_the_price_bound_lets_a_contradicting_tape_through(
        tmp_path, monkeypatch):
    """MUTATION: the same, for the price-consistency bound."""
    db = _seed(str(tmp_path / "mutp.db"), close=0.3863)
    assert "closes_5min" not in gather_evidence("BTC/USD", db, price=0.3749,
                                                now=NOW)

    monkeypatch.setattr("llm_consensus.evidence.MAX_PRICE_DIVERGENCE_PCT", 1e9)
    reverted = gather_evidence("BTC/USD", db, price=0.3749, now=NOW)
    assert "closes_5min" in reverted, (
        "MAX_PRICE_DIVERGENCE_PCT is not what refuses the contradicting series")


# --- TASK 3: refuse to ask a question the evidence cannot answer --------------

class _CountingProvider:
    """A provider that records every call. weight and score match the real
    shape, so the ensemble math is exercised unchanged."""

    def __init__(self, name="llm_primary", bias=0.7):
        self.name = name
        self.weight = 1.0
        self.calls = 0
        self._bias = bias

    def score(self, state):
        self.calls += 1
        return ModelVerdict(model=self.name, bias=self._bias, confidence=0.7,
                            edge=0.01, verdict="buy", rationale="ok",
                            source="real", model_id="stub")


def test_the_minimum_is_explicit_and_the_bounds_are_named():
    """The minimum is a defined, readable contract, not a scattered guess."""
    assert MIN_SERIES_CLOSES == 8
    assert MAX_BAR_AGE_SECONDS == 1800
    assert MAX_PRICE_DIVERGENCE_PCT == 1.0


@pytest.mark.parametrize("kwargs,expected", [
    ({"bars": 0}, "no_series"),
    ({"bars": MIN_SERIES_CLOSES - 1}, "bar_series_too_short"),
    ({"newest_age_seconds": 24 * 3600}, "bar_series_stale"),
    ({"close": 0.3863}, "bar_series_price_inconsistent"),
])
def test_the_refusal_fires_with_its_reason(tmp_path, kwargs, expected):
    price = 0.3749 if "close" in kwargs else 100.0
    db = _seed(str(tmp_path / f"{expected}.db"), **kwargs)
    state = build_state({"symbol": "BTC/USD", "price": price},
                        db_path=db, now=NOW)
    refusal = evidence_refusal(state)
    assert refusal is not None and refusal.reason == expected
    assert refusal.detail, "a refusal must say what was wrong"


def test_a_refused_round_contacts_nobody_and_records_the_reason(tmp_path):
    db = _seed(str(tmp_path / "refuse.db"), newest_age_seconds=24 * 3600)
    providers = [_CountingProvider("llm_primary"),
                 _CountingProvider("llm_secondary"),
                 _CountingProvider("llm_tertiary")]
    result = consensus({"symbol": "BTC/USD", "price": 100.0, "db": db},
                       providers=providers, gate=AlwaysProceedGate(),
                       cfg_path=CFG)

    assert [p.calls for p in providers] == [0, 0, 0], "spend was not saved"
    assert result.per_model == []
    assert result.refusal["reason"] == "bar_series_stale"
    assert "minutes old" in result.refusal["detail"]

    recorded = recent_refusals(db)
    assert len(recorded) == 1
    assert recorded[0]["symbol"] == "BTC/USD"
    assert recorded[0]["reason"] == "bar_series_stale"
    # The state is kept so a refusal can be re-examined against a changed
    # bound without re-running anything.
    conn = sqlite3.connect(db)
    stored = conn.execute("SELECT state_json FROM council_refusal").fetchone()
    conn.close()
    assert json.loads(stored[0])["symbol"] == "BTC/USD"


def test_a_refusal_costs_no_budget_and_reads_as_avoid(tmp_path):
    """Downstream, a refusal is structurally a short-circuit: zero provider
    calls means the discovery budget charges nothing, and the verdict is
    avoid. Its rationale says nobody was asked, not that three voters held."""
    db = _seed(str(tmp_path / "budget.db"), bars=0)
    council = consensus({"symbol": "BTC/USD", "price": 100.0, "db": db},
                        providers=[_CountingProvider()],
                        gate=AlwaysProceedGate(), cfg_path=CFG)
    verdict = build_verdict(symbol="BTC/USD", council=council, dnn={},
                            whale={}, conviction_floor=0.60)
    assert verdict["provider_calls"] == 0
    assert verdict["verdict"] == "avoid"
    assert verdict["refusal"]["reason"] == "no_series"
    assert "No council call" in verdict["rationale"]
    assert "directional voter" not in verdict["rationale"]

    from discovery.funnel import _budget_cost
    assert _budget_cost(verdict) == 0


def test_adequate_evidence_is_never_suppressed(tmp_path):
    """THE guard against the refusal becoming a wall.

    A fresh, consistent, long-enough series with a price reaches the gate and
    every provider exactly as before. Proven with the numbers from the real
    trading-path evaluation of SPY on 2026-07-22 (eval 29): price 748.99,
    newest close 748.83, newest bar 16 seconds before the round.
    """
    # The recorded numbers are SPY's, but SPY is an equity and the
    # market-hours cost cut would short-circuit it before the evidence
    # builder outside US hours, measuring the wrong thing. Crypto trades 24/7.
    db = _seed(str(tmp_path / "spy.db"), symbol="BTC/USD", close=746.11,
               drift=0.0092, newest_age_seconds=16)
    providers = [_CountingProvider("llm_primary"),
                 _CountingProvider("llm_secondary"),
                 _CountingProvider("llm_tertiary")]
    state = {"symbol": "BTC/USD", "price": 748.99, "db": db}

    assert evidence_refusal(build_state(state, db_path=db, now=NOW)) is None
    result = consensus(state, providers=providers,
                       gate=AlwaysProceedGate(), cfg_path=CFG)
    assert [p.calls for p in providers] == [1, 1, 1]
    assert result.refusal is None
    assert len(result.per_model) == 3


def test_no_database_means_no_refusal():
    """A caller that requested no enrichment gets the behaviour it asked for.

    Every path that can spend passes a db, so this is the hermetic offline
    path whose providers are deterministic mocks. Refusing here would suppress
    calls on the strength of a database nobody offered.
    """
    provider = _CountingProvider()
    result = consensus({"symbol": "BTC/USD", "ret_5": 0.03},
                       providers=[provider], gate=AlwaysProceedGate(),
                       cfg_path=CFG)
    assert provider.calls == 1 and result.refusal is None


# --- TASK 4: the screen that ran is the screen that is recorded ---------------

def test_a_stage_b_screen_is_reported_not_relabelled_disabled():
    from llm_consensus.gate import GateDecision

    real = GateDecision(True, "Strong daily momentum, worth a look",
                        "claude-haiku-4-5", "real")
    reported = PriorScreenGate(real).should_review({})
    assert reported.proceed is True
    assert reported.source == "stage_b_real"
    assert reported.model == "claude-haiku-4-5"
    assert "Strong daily momentum" in reported.reason
    assert "disabled" not in reported.reason.lower()

    # A survivor the gate failed open on says so, rather than claiming a screen.
    unscreened = PriorScreenGate(None).should_review({})
    assert unscreened.proceed is True
    assert unscreened.source == "stage_b_failed_open"
    assert "not screened" in unscreened.reason


def test_a_disabled_gate_is_a_visible_condition(monkeypatch):
    """Off states the CONSEQUENCE, in the startup block and in the GUI feed."""
    import importlib

    consensus_mod = importlib.import_module("llm_consensus.consensus")

    monkeypatch.setattr(consensus_mod, "gate_enabled", lambda cfg=None: False)
    line = consensus_mod.council_status_line()
    assert "DISABLED" in line
    assert "unscreened" in line

    monkeypatch.setattr(consensus_mod, "gate_enabled", lambda cfg=None: True)
    assert "DISABLED" not in consensus_mod.council_status_line()


def test_the_runstate_gate_field_follows_the_control_file_not_the_config(
        monkeypatch):
    """The banner must show what the council OBEYS, which is the resolved
    value. Reading config only let the two halves disagree silently, in the
    direction that spends money."""
    from api_server import store

    monkeypatch.setattr("llm_consensus.config_access.gate_enabled",
                        lambda cfg_path=None: False)
    state = store.runstate()
    assert state["gate_enabled"] is False
    assert "DISABLED" in state["gate_status"]
    assert "unscreened" in state["gate_status"]

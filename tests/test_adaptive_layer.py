"""The adaptive layer end to end: feed, free filter, budget, gating, referrals.

No network and no model anywhere in this file. The Finnhub client and the
interpreter are both fakes, so every assertion is about OUR logic rather than a
vendor's uptime.

The flags are driven through a real controls.json in a temp control dir, which is
exactly how the operator turns this on from the GUI. So these tests exercise the
actual config-plus-controls precedence rather than a mock of it.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from adaptive import materiality, run, settings, store
from adaptive.interpret import Interpretation, MockInterpreter
from adaptive.news_feed import NewsFeed, poll_targets
from discovery import watchlist

NOW = datetime(2026, 7, 16, 9, 30, tzinfo=timezone.utc)
TS = "2026-07-16T09:30:00Z"

KEYWORDS = ["bankruptcy", "fraud", "halt", "sec probe"]


# --- fixtures ---------------------------------------------------------------

@pytest.fixture
def control_dir(tmp_path, monkeypatch):
    """A real control dir. Returns a setter that writes the adaptive block."""
    d = tmp_path / "control"
    d.mkdir()
    monkeypatch.setenv("MAL_CONTROL_DIR", str(d))

    def _set(**flags):
        (d / "controls.json").write_text(
            json.dumps({"adaptive_realtime": flags}))
    return _set


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(str(tmp_path / "m.db"))
    store.ensure_schema(c)
    watchlist.ensure_schema(c)
    c.execute("CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, "
              "venue TEXT, symbol TEXT, qty REAL)")
    return c


def _hold(conn, symbol: str = "SPY") -> None:
    """Give the account an open position, which makes the symbol a poll target.

    The feed only asks about held names and watchlist names, so a test with no
    target polls nothing and sees nothing. That is correct behavior, and it makes
    the target a required part of the arrangement rather than an afterthought.
    """
    conn.execute("INSERT INTO positions(venue,symbol,qty) VALUES('alpaca',?,5)",
                 (symbol,))


class ExplodingClient:
    """Raises on ANY attribute access.

    This is how "zero adaptive API calls" gets proven rather than asserted: if
    the disabled path touched the client in any way at all, the test errors.
    """

    def __getattr__(self, name):
        raise AssertionError(
            f"the adaptive layer touched the client ({name}) while disabled")


class FakeClient:
    """A Finnhub stand-in. Records what was asked for.

    NOTE the sentiment default. Finnhub's companyNewsScore is 0..1 where 0.5 is
    NEUTRAL, not 0.0: a score of 0.0 means maximally bearish. Defaulting this to
    0.0 would make every fake article read as a -1.0 sentiment shock and escalate
    on the sentiment trigger, which quietly turns the "the filter drops the vast
    majority" test into a test of nothing.
    """

    NEUTRAL = 0.5

    def __init__(self, articles=None, sentiment=NEUTRAL):
        self._articles = articles or []
        self._sentiment = sentiment
        self.company_news_calls: list[str] = []
        self.general_news_calls = 0

    def company_news(self, symbol, frm, to):
        self.company_news_calls.append(symbol)
        return [a for a in self._articles if a.get("related") == symbol]

    def general_news(self, category="general"):
        self.general_news_calls += 1
        return [a for a in self._articles if not a.get("related")]

    def news_sentiment(self, symbol):
        return {"companyNewsScore": self._sentiment}


class ScriptedInterpreter:
    """A stand-in model. Says exactly what the test tells it to."""

    model_id = "fake"

    def __init__(self, action="none", severity=0.9, relevance=0.9):
        self._action, self._severity, self._relevance = (
            action, severity, relevance)
        self.calls = 0

    def interpret(self, event):
        self.calls += 1
        return Interpretation(
            relevance=self._relevance, direction="bearish",
            severity=self._severity, action=self._action,
            rationale="scripted", model=self.model_id, source="real",
            symbol=event.get("symbol", ""))


def _article(aid: int, related: str = "SPY", headline: str = "Routine update",
             minutes_ago: int = 1) -> dict:
    when = NOW - timedelta(minutes=minutes_ago)
    return {"id": aid, "datetime": int(when.timestamp()), "headline": headline,
            "summary": "", "source": "Reuters", "url": "https://example.test/x",
            "related": related, "category": "company news"}


# --- Task 8: flags off means OFF -------------------------------------------

def test_disabled_does_nothing_at_all_and_calls_nothing(conn, control_dir):
    """The whole safety claim of shipping this: with the flag off, it is inert.

    Not "returns early" but touches nothing: no client access, no row written,
    no poll recorded.
    """
    control_dir(adaptive_news_feed_enabled=False)
    stats = run.run_once(conn, client=ExplodingClient(),
                         interpreter=ExplodingClient(), now=NOW)
    assert stats["status"] == "disabled"
    assert stats["events_seen"] == 0
    assert stats["llm_calls"] == 0
    assert store.last_poll(conn) is None, "a disabled layer records no poll"
    assert store.recent_events(conn) == []
    assert store.recent_actions(conn) == []


def test_disabled_by_default_with_no_control_file_at_all(conn, tmp_path,
                                                         monkeypatch):
    """A fresh checkout, an empty control dir, a deleted controls.json: all mean
    the same thing. Config ships false, so the fallback is always OFF."""
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "nonexistent"))
    assert settings.news_feed_enabled() is False
    assert settings.watchlist_shaping_enabled() is False
    assert settings.react_defensive_enabled() is False
    assert settings.any_enabled() is False
    stats = run.run_once(conn, client=ExplodingClient(), now=NOW)
    assert stats["status"] == "disabled"


def test_run_due_is_also_inert_while_disabled(conn, control_dir):
    control_dir(adaptive_news_feed_enabled=False)
    stats = run.run_due(conn, client=ExplodingClient(), now=NOW)
    assert stats["status"] == "disabled"
    assert store.last_poll(conn) is None


def test_the_feed_flag_is_the_master(conn, control_dir):
    """Shaping and defensive are downstream of a poll. With the feed off they
    cannot do anything, whatever they are set to. One flag to be sure of."""
    control_dir(adaptive_news_feed_enabled=False,
                adaptive_watchlist_shaping_enabled=True,
                adaptive_react_defensive_enabled=True)
    stats = run.run_once(conn, client=ExplodingClient(), now=NOW)
    assert stats["status"] == "disabled"
    assert store.recent_actions(conn) == []


def test_a_malformed_control_file_reads_as_off(conn, tmp_path, monkeypatch):
    """A broken control file must never be able to turn a spender ON."""
    d = tmp_path / "ctl"
    d.mkdir()
    (d / "controls.json").write_text("{not json at all")
    monkeypatch.setenv("MAL_CONTROL_DIR", str(d))
    assert settings.news_feed_enabled() is False
    assert run.run_once(conn, client=ExplodingClient(),
                        now=NOW)["status"] == "disabled"


# --- Task 2: the free filter -----------------------------------------------

def test_routine_news_is_dropped_for_free():
    v = materiality.assess({"symbol": "SPY", "headline": "Stock rises slightly",
                            "sentiment": 0.1},
                           keywords=KEYWORDS, min_sentiment=0.55)
    assert v.dropped
    assert v.reason == "no_trigger"


def test_a_keyword_escalates():
    v = materiality.assess({"symbol": "SPY", "headline": "SEC probe opened",
                            "sentiment": 0.0},
                           keywords=KEYWORDS, min_sentiment=0.55)
    assert v.material
    assert v.reason == "keyword:sec probe"


def test_a_high_impact_event_type_escalates_even_in_flat_language():
    """A halt announced in a dull sentence is still a halt."""
    v = materiality.assess({"symbol": "SPY", "headline": "Company files update",
                            "sentiment": 0.0, "event_type": "halt"},
                           keywords=[], min_sentiment=0.99)
    assert v.material
    assert v.reason == "event_type:halt"


def test_loud_sentiment_escalates_in_either_direction():
    for s in (0.8, -0.8):
        v = materiality.assess({"symbol": "SPY", "headline": "Something",
                                "sentiment": s},
                               keywords=[], min_sentiment=0.55)
        assert v.material, f"sentiment {s} should escalate"


def test_a_held_name_gets_a_lower_bar():
    """Safe by construction: an event about a held name can only ever cause a
    DEFENSIVE action, so reading more of them can only make us more careful."""
    event = {"symbol": "SPY", "headline": "Something", "sentiment": 0.45}
    assert materiality.assess({**event, "held": False}, keywords=[],
                              min_sentiment=0.55).dropped
    assert materiality.assess({**event, "held": True}, keywords=[],
                              min_sentiment=0.55).material


def test_the_filter_drops_the_vast_majority(conn, control_dir):
    """The cost argument, as a measurement rather than a claim."""
    control_dir(adaptive_news_feed_enabled=True)
    _hold(conn)
    articles = [_article(i, headline="Shares trade sideways in quiet session")
                for i in range(1, 51)]
    articles.append(_article(99, headline="Trading halted amid fraud probe"))
    interp = ScriptedInterpreter(action="none")
    stats = run.run_once(conn, client=FakeClient(articles),
                         interpreter=interp, now=NOW)
    assert stats["events_seen"] == 51
    assert stats["events_material"] == 1
    assert interp.calls == 1, "50 of 51 events cost nothing at all"


# --- Task 1: the feed -------------------------------------------------------

def test_held_names_are_polled_before_watchlist_names(conn):
    """When the per-poll cap binds, the thing dropped must be a candidate we
    might buy, never a position we own and might need to exit."""
    conn.execute("INSERT INTO positions(venue,symbol,qty) VALUES('alpaca','ZZZ',5)")
    watchlist.add_from_discovery(conn, "AAA", reason="x", ts=TS)
    targets = poll_targets(conn, max_symbols=1)
    assert targets == [{"symbol": "ZZZ", "held": True}]


def test_a_flat_position_is_not_held(conn):
    conn.execute("INSERT INTO positions(venue,symbol,qty) VALUES('alpaca','ZZZ',0)")
    assert poll_targets(conn, max_symbols=10) == []


def test_the_poll_cap_bounds_the_call_rate(conn, control_dir):
    control_dir(adaptive_news_feed_enabled=True, max_symbols_per_poll=2)
    for s in ("AAA", "BBB", "CCC", "DDD"):
        watchlist.add_from_discovery(conn, s, reason="x", ts=TS)
    client = FakeClient([])
    run.run_once(conn, client=client, interpreter=MockInterpreter(), now=NOW)
    assert len(client.company_news_calls) == 2


def test_the_same_headline_is_never_read_twice(conn, control_dir):
    """The lookback is wider than the interval on purpose, so overlapping polls
    are NORMAL. Without dedupe the same headline would be re-charged every
    minute."""
    control_dir(adaptive_news_feed_enabled=True)
    _hold(conn)
    articles = [_article(1, headline="Trading halted amid fraud probe")]
    interp = ScriptedInterpreter(action="none")
    first = run.run_once(conn, client=FakeClient(articles), interpreter=interp,
                         now=NOW)
    second = run.run_once(conn, client=FakeClient(articles), interpreter=interp,
                          now=NOW + timedelta(minutes=1))
    assert first["events_new"] == 1
    assert second["events_new"] == 0, "the repeat is deduped"
    assert interp.calls == 1, "and is never paid for twice"


def test_finnhub_sentiment_is_recentred_from_its_own_scale():
    """Finnhub's companyNewsScore is 0..1 with 0.5 NEUTRAL. The filter wants a
    signed magnitude where 0 means "nothing to see". Getting this mapping wrong
    in either direction silently breaks the sentiment trigger: read 0.5 as
    "bearish" and everything escalates, read 0.0 as "neutral" and nothing does.
    """
    feed = lambda score: NewsFeed(  # noqa: E731
        FakeClient([], sentiment=score), general=False)._sentiment_for("SPY")
    assert feed(0.5) == 0.0, "0.5 is neutral, not bearish"
    assert feed(1.0) == 1.0, "1.0 is maximally bullish"
    assert feed(0.0) == -1.0, "0.0 is maximally bearish"
    assert feed(0.75) == 0.5


def test_unknown_sentiment_reads_as_silence_not_neutral():
    """A missing score means "we do not know", which must trigger nothing. That
    happens to coincide with neutral numerically, but they are different claims
    and only one of them is safe to assume."""

    class NoSentiment(FakeClient):
        def news_sentiment(self, symbol):
            return None

    assert NewsFeed(NoSentiment([]), general=False)._sentiment_for("SPY") == 0.0


def test_stale_articles_outside_the_lookback_are_ignored(conn):
    feed = NewsFeed(FakeClient([_article(1, minutes_ago=120)]),
                    lookback_minutes=15, general=False)
    assert feed.poll([{"symbol": "SPY", "held": False}], now=NOW) == []


def test_a_feed_error_never_raises_into_the_runner(conn, control_dir):
    """This layer is advisory. It must not be able to take anything down."""
    control_dir(adaptive_news_feed_enabled=True)
    _hold(conn)

    class Broken(FakeClient):
        def company_news(self, symbol, frm, to):
            raise RuntimeError("finnhub is down")

    stats = run.run_once(conn, client=Broken(), interpreter=MockInterpreter(),
                         now=NOW)
    assert stats["events_seen"] == 0
    assert store.last_poll(conn) is not None, "the failed poll is still recorded"


# --- Task 3: the budget -----------------------------------------------------

def test_the_daily_budget_is_a_hard_ceiling(conn, control_dir):
    control_dir(adaptive_news_feed_enabled=True, adaptive_daily_llm_budget=2,
                max_interpretations_per_poll=10)
    _hold(conn)
    articles = [_article(i, headline="Trading halted amid fraud probe")
                for i in range(1, 6)]
    interp = ScriptedInterpreter(action="none")
    stats = run.run_once(conn, client=FakeClient(articles), interpreter=interp,
                         now=NOW)
    assert interp.calls == 2, "spends the budget and stops"
    assert stats["status"] == "budget_exhausted"
    assert stats["budget_remaining"] == 0
    assert stats["events_material"] == 5, "the rest are stored, just not read"


def test_the_per_poll_cap_stops_one_storm_spending_the_day(conn, control_dir):
    control_dir(adaptive_news_feed_enabled=True, adaptive_daily_llm_budget=100,
                max_interpretations_per_poll=2)
    _hold(conn)
    articles = [_article(i, headline="Trading halted amid fraud probe")
                for i in range(1, 9)]
    interp = ScriptedInterpreter(action="none")
    stats = run.run_once(conn, client=FakeClient(articles), interpreter=interp,
                         now=NOW)
    assert interp.calls == 2
    assert stats["reason"] == "per_poll_cap_reached"


def test_the_budget_carries_across_polls_within_a_day(conn, control_dir):
    control_dir(adaptive_news_feed_enabled=True, adaptive_daily_llm_budget=2,
                max_interpretations_per_poll=1)
    _hold(conn)
    interp = ScriptedInterpreter(action="none")
    for i in range(1, 5):
        run.run_once(conn, client=FakeClient(
            [_article(i, headline="Trading halted amid fraud probe")]),
            interpreter=interp, now=NOW + timedelta(minutes=i))
    assert interp.calls == 2, "the day's ceiling holds across polls"
    assert store.llm_calls_today(conn, TS) == 2


def test_a_low_relevance_read_causes_nothing(conn, control_dir):
    """Relevance is a MODEL output, so it gates after the call, not before."""
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_react_defensive_enabled=True,
                interpretation_min_relevance=0.5)
    _hold(conn)
    interp = ScriptedInterpreter(action="exit", severity=1.0, relevance=0.1)
    run.run_once(conn, client=FakeClient(
        [_article(1, headline="Trading halted amid fraud probe")]),
        interpreter=interp, now=NOW)
    assert store.recent_actions(conn) == []
    assert store.recent_interpretations(conn)[0]["outcome"] == "dropped"


# --- Task 4 + 5: gating and the asymmetry, end to end ----------------------

def test_the_react_source_is_refused_while_the_shaping_flag_is_off(conn,
                                                                   control_dir):
    """The gate lives in watchlist.apply_event and reads the flag directly, so no
    caller can pass an override that unlocks it."""
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_watchlist_shaping_enabled=False)
    r = watchlist.refer_from_adaptive(conn, "TSLA", reason="hype", ts=TS)
    assert r == {"applied": False, "reason": "source_not_enabled"}
    assert watchlist.active_symbols(conn) == []
    assert watchlist.referred_symbols(conn) == []
    # Refused, but still JOURNALLED: a refusal must be visible, not silent.
    events = watchlist.recent_events(conn)
    assert len(events) == 1 and events[0]["applied"] is False


def test_a_referral_is_not_tradeable(conn, control_dir):
    """THE END-TO-END ASYMMETRY.

    The best an aggressive read can do is put a name in front of the funnel. The
    engine reads active symbols only, so a referral changes nothing it trades.
    """
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_watchlist_shaping_enabled=True)
    r = watchlist.refer_from_adaptive(conn, "TSLA", reason="bullish news",
                                      ts=TS)
    assert r == {"applied": True, "reason": "referred"}
    assert watchlist.referred_symbols(conn) == ["TSLA"]
    # The engine's view (active only) does not contain it. This is the line
    # between "noticed" and "traded".
    assert watchlist.active_symbols(conn) == []
    assert [w["symbol"] for w in watchlist.active(conn)] == []


def test_only_the_funnel_can_promote_a_referral(conn, control_dir):
    """A referral becomes tradeable ONLY once a discovery pass confirms it,
    which means it cleared Stage A, Stage B, and the four levels."""
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_watchlist_shaping_enabled=True)
    watchlist.refer_from_adaptive(conn, "TSLA", reason="bullish news", ts=TS)
    assert watchlist.active_symbols(conn) == []

    watchlist.add_from_discovery(conn, "TSLA", reason="survived stage C",
                                 score=0.8, ts=TS)
    assert watchlist.active_symbols(conn) == ["TSLA"]
    assert watchlist.referred_symbols(conn) == []


def test_a_referral_cannot_demote_a_symbol_the_funnel_promoted(conn,
                                                               control_dir):
    """A referral of an already-active symbol must not knock it out of the
    traded universe: the adaptive layer must never overwrite the funnel."""
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_watchlist_shaping_enabled=True)
    watchlist.add_from_discovery(conn, "TSLA", reason="survived", score=0.8,
                                 ts=TS)
    watchlist.refer_from_adaptive(conn, "TSLA", reason="more news", ts=TS)
    assert watchlist.active_symbols(conn) == ["TSLA"], "still active"


def test_an_aggressive_read_end_to_end_only_refers(conn, control_dir):
    """Everything on. The model says BUY. The result is a referral, no position,
    and nothing on the engine's queue."""
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_watchlist_shaping_enabled=True,
                adaptive_react_defensive_enabled=True,
                action_min_severity=0.1)
    _hold(conn)
    interp = ScriptedInterpreter(action="open", severity=1.0, relevance=1.0)
    stats = run.run_once(conn, client=FakeClient(
        [_article(1, headline="Company announces takeover, shares to soar")]),
        interpreter=interp, now=NOW)
    assert stats["referrals"] == 1
    assert stats["actions_queued"] == 0
    assert store.recent_actions(conn) == [], "nothing reaches the engine"
    assert watchlist.active_symbols(conn) == [], "and nothing becomes tradeable"
    assert watchlist.referred_symbols(conn) == ["SPY"]


def test_a_defensive_read_end_to_end_queues_for_the_engine(conn, control_dir):
    """The other half: the layer is allowed to be careful."""
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_react_defensive_enabled=True,
                action_min_severity=0.1)
    _hold(conn)
    interp = ScriptedInterpreter(action="exit", severity=0.95, relevance=1.0)
    stats = run.run_once(conn, client=FakeClient(
        [_article(1, headline="Trading halted amid fraud probe")]),
        interpreter=interp, now=NOW)
    assert stats["actions_queued"] == 1
    actions = store.recent_actions(conn)
    assert len(actions) == 1
    assert actions[0]["action"] == "exit"
    assert actions[0]["symbol"] == "SPY"


def test_a_prune_removes_a_watchlist_name_without_touching_positions(
        conn, control_dir):
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_watchlist_shaping_enabled=True)
    watchlist.add_from_discovery(conn, "SPY", reason="survived", ts=TS)
    r = watchlist.remove_from_adaptive(conn, "SPY", reason="thesis broke",
                                       ts=TS)
    assert r["applied"] is True
    assert watchlist.active_symbols(conn) == []
    assert store.recent_actions(conn) == [], "a prune is not an engine action"


# --- Interpretation fails closed -------------------------------------------

def test_the_mock_interpreter_is_inert_not_plausible():
    """A mock that invented severities would let a flags-on run look like it was
    working while every read was fiction."""
    i = MockInterpreter().interpret({"symbol": "SPY", "headline": "x"})
    assert i.action == "none"
    assert i.severity == 0.0
    assert not i.is_actionable


def test_an_unusable_read_causes_nothing(conn, control_dir):
    """Fail CLOSED. This deliberately inverts the council gate, which fails open:
    the price of failing open there is money, here it is a position."""
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_react_defensive_enabled=True)
    _hold(conn)

    class BrokenInterpreter:
        model_id = "broken"

        def interpret(self, event):
            return Interpretation(action="none", severity=0.0, relevance=0.0,
                                  model="broken", source="error",
                                  rationale="output unparseable")

    run.run_once(conn, client=FakeClient(
        [_article(1, headline="Trading halted amid fraud probe")]),
        interpreter=BrokenInterpreter(), now=NOW)
    assert store.recent_actions(conn) == []


# --- Settings parity --------------------------------------------------------

def test_the_shipped_config_ships_every_flag_false(tmp_path, monkeypatch):
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "none"))
    assert settings.news_feed_enabled("config/default_config.yaml") is False
    assert settings.watchlist_shaping_enabled(
        "config/default_config.yaml") is False
    assert settings.react_defensive_enabled(
        "config/default_config.yaml") is False


def test_python_defaults_mirror_the_cpp_struct():
    """tests/test_adaptive_react.cpp asserts the same numbers on the C++ side.
    Two sources of truth only stay in step if something checks both."""
    d = settings._DEFAULTS
    assert d["poll_interval_seconds"] == 60
    # 25, not 30: a poll costs 2N+1 Finnhub calls on a cold sentiment cache
    # and the free tier is 60/min, so 30 symbols meant 61 calls and a stall.
    assert d["max_symbols_per_poll"] == 25
    assert d["adaptive_daily_llm_budget"] == 20
    assert d["max_interpretations_per_poll"] == 3
    assert d["action_min_severity"] == 0.60
    assert d["action_max_age_seconds"] == 300
    assert d["defensive_trim_fraction"] == 0.50
    assert d["interpretation_model"] == "claude-haiku-4-5"


def test_the_control_file_overrides_config_but_never_upward_by_default(
        control_dir):
    """The operator's toggle wins. A key the control file does not carry falls
    back to config, and config ships off."""
    control_dir(adaptive_news_feed_enabled=True)
    assert settings.news_feed_enabled() is True
    assert settings.watchlist_shaping_enabled() is False, "untouched: config off"
    assert settings.poll_interval_seconds() == 60, "untouched: config default"


# --- Regressions from the 2026-07-16 self-review ----------------------------
# Each of these fails against the code as originally shipped.

def test_a_general_market_event_never_crashes_the_poller(conn, control_dir):
    """A macro headline names no instrument, so there is nothing to exit.

    Originally route() handed symbol="" to DefensiveAction, whose constructor
    raises, and the unguarded loop let that ValueError escape run_once and kill
    the poller. general_news_enabled is on by default, so a headline like 'SEC
    probe into fraud at major bank' read as `exit` was a live crash.
    """
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_react_defensive_enabled=True, action_min_severity=0.1)
    general = {"id": 1, "datetime": int((NOW - timedelta(minutes=1)).timestamp()),
               "headline": "SEC probe into fraud at major bank", "summary": "",
               "source": "Reuters", "url": "https://example.test/x",
               "related": "", "category": "general"}
    interp = ScriptedInterpreter(action="exit", severity=1.0, relevance=1.0)
    stats = run.run_once(conn, client=FakeClient([general]), interpreter=interp,
                         now=NOW)          # must not raise
    assert stats["status"] == "ok"
    assert store.recent_actions(conn) == [], "you cannot exit 'the market'"
    assert store.recent_interpretations(conn)[0]["outcome_reason"] == (
        "no_symbol_for_defensive")


def test_a_routing_failure_costs_one_event_not_the_process(conn, control_dir):
    """The 'never raises' promise must not depend on every future branch of
    route() remembering it."""
    control_dir(adaptive_news_feed_enabled=True,
                adaptive_react_defensive_enabled=True, action_min_severity=0.1)
    _hold(conn)

    class Exploding(ScriptedInterpreter):
        def interpret(self, event):
            i = super().interpret(event)
            object.__setattr__(i, "severity", float("nan"))  # poison the route
            return i

    stats = run.run_once(conn, client=FakeClient(
        [_article(1, headline="Trading halted amid fraud probe")]),
        interpreter=Exploding(action="exit"), now=NOW)
    assert stats["status"] == "ok", "one bad event must not kill the poll"


def test_the_held_discount_lowers_the_bar_at_every_threshold():
    """It used to INVERT below 0.15: subtracting the discount drove the
    threshold to 0.0, a `threshold > 0.0` guard then skipped the trigger, and a
    held name ended up unreachable while an unheld one still fired."""
    ev = {"symbol": "SPY", "headline": "x", "sentiment": 0.9}
    for mins in (0.9, 0.55, 0.16, 0.15, 0.10, 0.01):
        held = materiality.assess({**ev, "held": True}, keywords=[],
                                  min_sentiment=mins).material
        unheld = materiality.assess({**ev, "held": False}, keywords=[],
                                    min_sentiment=mins).material
        assert held or not unheld, (
            f"at min_sentiment={mins} a HELD name has a higher bar than an "
            f"unheld one (held={held}, unheld={unheld})")


def test_an_unknown_sentiment_never_escalates_a_held_name():
    """0.0 means 'we do not know' (news_feed._sentiment_for), not 'neutral'. A
    discounted threshold that reached 0.0 would escalate, and pay for, every
    event on a held name including the ones carrying no sentiment at all."""
    v = materiality.assess({"symbol": "SPY", "headline": "x", "sentiment": 0.0,
                            "held": True}, keywords=[], min_sentiment=0.15)
    assert v.dropped


def test_a_zero_threshold_disables_the_sentiment_trigger_entirely():
    for held in (True, False):
        v = materiality.assess({"symbol": "SPY", "headline": "x",
                                "sentiment": 0.99, "held": held},
                               keywords=[], min_sentiment=0.0)
        assert v.dropped, "min_sentiment 0 means the trigger is OFF"


def test_the_per_poll_cap_defers_an_event_it_does_not_discard_it(conn,
                                                                 control_dir):
    """The cap used to drop events PERMANENTLY: the leftovers were stored, the
    next poll re-fetched the same articles, record_event deduped them, and they
    were skipped as 'already seen' forever. A halt arriving as the 4th material
    event of a busy minute was simply never read."""
    control_dir(adaptive_news_feed_enabled=True, adaptive_daily_llm_budget=100,
                max_interpretations_per_poll=2)
    _hold(conn)
    articles = [_article(i, headline="Trading halted amid fraud probe")
                for i in range(1, 6)]
    interp = ScriptedInterpreter(action="none")

    first = run.run_once(conn, client=FakeClient(articles), interpreter=interp,
                         now=NOW)
    assert first["events_material"] == 5
    assert interp.calls == 2, "the cap binds"

    # The next poll picks up the backlog rather than starting from nothing new.
    run.run_once(conn, client=FakeClient(articles), interpreter=interp,
                 now=NOW + timedelta(minutes=1))
    assert interp.calls == 4, "the deferred events are read, not discarded"
    run.run_once(conn, client=FakeClient(articles), interpreter=interp,
                 now=NOW + timedelta(minutes=2))
    assert interp.calls == 5, "and the last one drains"


def test_the_backlog_never_resurrects_stale_news(conn, control_dir):
    """A material event nobody could afford to read an hour ago is not worth
    acting on now, and the engine would refuse an action built from it anyway."""
    control_dir(adaptive_news_feed_enabled=True, max_interpretations_per_poll=0)
    _hold(conn)
    run.run_once(conn, client=FakeClient(
        [_article(1, headline="Trading halted amid fraud probe")]),
        interpreter=ScriptedInterpreter(), now=NOW)

    late = ScriptedInterpreter(action="none")
    run.run_once(conn, client=FakeClient([]), interpreter=late,
                 now=NOW + timedelta(minutes=run.PENDING_MAX_AGE_MINUTES + 5))
    assert late.calls == 0, "an hour-old unread event is not resurrected"


def test_an_event_with_no_dedupe_key_is_not_swallowed_as_a_duplicate(conn):
    """An empty key collides with itself under UNIQUE (NULL does not), so the
    first keyless event used to insert and silently swallow every one after."""
    first = store.record_event(conn, {"ts": TS, "symbol": "SPY",
                                      "headline": "one"})
    second = store.record_event(conn, {"ts": TS, "symbol": "SPY",
                                       "headline": "two"})
    assert first is not None
    assert second is not None, "a second keyless event must not read as a dupe"
    assert len(store.recent_events(conn)) == 2

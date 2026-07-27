"""Guards on the hindsight-free universe rule.

The headline test is `test_future_bars_cannot_move_an_earlier_membership`.
Every other property here is worth pinning, but that one is the reason the
module exists: a universe rule whose past decisions move when tomorrow
arrives is a backtest that cannot be believed.
"""
from __future__ import annotations

import datetime as dt

import pytest

from backtest import universe as U


def _sessions(n: int, start: str = "2020-01-01") -> list[str]:
    """n weekday session dates. Weekdays only, no holiday calendar: the rule
    never reads the calendar's contents, only its order."""
    out, day = [], dt.date.fromisoformat(start)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += dt.timedelta(days=1)
    return out


def _params(**kw) -> U.RuleParams:
    base = dict(window_sessions=10, min_window_bars=6, min_median_close=5.0,
                top_n=3, include_funds=False)
    base.update(kw)
    return U.RuleParams(**base)


def _cand(symbol: str, mdv: float, *, bars: int = 10, close: float = 50.0,
          is_fund: bool | None = False, brk: bool = False) -> U.Candidate:
    return U.Candidate(symbol=symbol, window_bars=bars, median_close=close,
                       median_dollar_volume=mdv, is_fund=is_fund,
                       segment_break_in_window=brk)


# --------------------------------------------------------- the headline guard

def _members_at(bars_by_symbol: dict[str, dict[str, tuple[float, float]]],
                sessions: list[str], formation: str,
                params: U.RuleParams) -> list[str]:
    """Reproduce the loader's per-formation-date path with plain dicts.

    Mirrors scripts/breadth_universe_20260726.py::_window_candidates: select
    the window, summarise, rank. Anything the loader does that this does not
    is outside the rule and cannot affect membership.
    """
    start, end = U.window_bounds(sessions, formation, params.window_sessions)
    cands = []
    for sym, series in bars_by_symbol.items():
        window = [(d, v) for d, v in sorted(series.items()) if start <= d <= end]
        if not window:
            continue
        cand = U.summarize_window(sym, [v[0] for _, v in window],
                                  [v[1] for _, v in window],
                                  is_fund=False, segment_break_in_window=False)
        if cand:
            cands.append(cand)
    members, _ = U.rank_members(cands, params)
    return [m.candidate.symbol for m in members]


def test_future_bars_cannot_move_an_earlier_membership():
    # Arrange: three symbols with distinct liquidity over 30 sessions, and a
    # formation date in the middle whose window is entirely in the past.
    sessions = _sessions(30)
    params = _params(top_n=2)
    formation = sessions[20]
    base = {
        "AAA": {d: (50.0, 1_000.0) for d in sessions[:20]},
        "BBB": {d: (50.0, 900.0) for d in sessions[:20]},
        "CCC": {d: (50.0, 10.0) for d in sessions[:20]},
    }
    before = _members_at(base, sessions, formation, params)

    # Act: the future arrives and completely reorders liquidity. CCC becomes
    # the most traded name in the market.
    after_bars = {
        "AAA": dict(base["AAA"]),
        "BBB": dict(base["BBB"]),
        "CCC": dict(base["CCC"]) | {d: (50.0, 9_999_999.0)
                                    for d in sessions[20:]},
    }
    after = _members_at(after_bars, sessions, formation, params)

    # Assert: the decision made at the formation date is untouched.
    assert before == ["AAA", "BBB"]
    assert after == before


def test_window_ends_strictly_before_the_formation_date():
    sessions = _sessions(30)
    start, end = U.window_bounds(sessions, sessions[20], 10)
    assert start == sessions[10]
    assert end == sessions[19]
    assert end < sessions[20]


def test_window_bounds_refuses_a_formation_date_without_a_full_window():
    sessions = _sessions(30)
    with pytest.raises(ValueError):
        U.window_bounds(sessions, sessions[5], 10)


def test_formation_dates_are_first_session_of_each_month_past_warmup():
    sessions = _sessions(200, "2020-01-01")
    dates = U.formation_dates(sessions, _params(window_sessions=60))
    assert dates, "expected at least one formation date"
    for d in dates:
        idx = sessions.index(d)
        assert idx >= 60
        assert sessions[idx - 1][:7] != d[:7]
    assert len({d[:7] for d in dates}) == len(dates)


# ------------------------------------------------------------------- ranking

def test_rank_orders_by_median_dollar_volume_and_truncates_at_top_n():
    members, rejected = U.rank_members(
        [_cand("LOW", 10.0), _cand("HIGH", 1000.0), _cand("MID", 100.0),
         _cand("TINY", 1.0)], _params(top_n=2))
    assert [m.candidate.symbol for m in members] == ["HIGH", "MID"]
    assert [m.rank for m in members] == [1, 2]
    assert sorted(rejected) == [("LOW", "below_rank_2"),
                                ("TINY", "below_rank_2")]


def test_ties_break_on_symbol_so_membership_is_reproducible():
    members, _ = U.rank_members(
        [_cand("ZZZ", 100.0), _cand("AAA", 100.0), _cand("MMM", 100.0)],
        _params(top_n=3))
    assert [m.candidate.symbol for m in members] == ["AAA", "MMM", "ZZZ"]


def test_one_squeeze_day_cannot_buy_membership():
    """The median, not the mean. A name that trades 1 USD a day except for
    one 10 million dollar session must not out-rank a steadily liquid name."""
    steady = U.summarize_window("STEADY", [50.0] * 10, [100.0] * 10,
                                is_fund=False, segment_break_in_window=False)
    spike = U.summarize_window("SPIKE", [50.0] * 10,
                               [1.0] * 9 + [10_000_000.0],
                               is_fund=False, segment_break_in_window=False)
    members, _ = U.rank_members([steady, spike], _params(top_n=1))
    assert [m.candidate.symbol for m in members] == ["STEADY"]


# ---------------------------------------------------------------- rejections

@pytest.mark.parametrize("cand,expected", [
    (_cand("THIN", 100.0, bars=5), "thin_window:5<6"),
    (_cand("PENNY", 100.0, close=1.25), "below_price_floor:1.25"),
    (_cand("REUSED", 100.0, brk=True), "listing_segment_break_in_window"),
    (_cand("FUND", 100.0, is_fund=True), "fund"),
    (_cand("OK", 100.0), None),
])
def test_every_rejection_states_its_reason(cand, expected):
    assert U.rejection_reason(cand, _params()) == expected


def test_funds_are_admitted_when_the_rule_says_so():
    assert U.rejection_reason(_cand("FUND", 1.0, is_fund=True),
                              _params(include_funds=True)) is None


def test_rule_id_distinguishes_the_fund_variants():
    assert _params().rule_id != _params(include_funds=True).rule_id


# ------------------------------------------------------------------ segments

def _index(sessions: list[str]) -> dict[str, int]:
    return {d: i for i, d in enumerate(sessions)}


def test_a_holiday_length_gap_does_not_end_a_segment():
    sessions = _sessions(60)
    dates = sessions[:10] + sessions[15:30]  # a 5-session hole
    segs = U.segment_series(dates, _index(sessions))
    assert len(segs) == 1
    assert segs[0].n_bars == len(dates)


def test_a_long_hole_ends_a_segment_and_the_two_are_never_joined():
    sessions = _sessions(120)
    dates = sessions[:20] + sessions[80:100]  # a 60-session hole
    segs = U.segment_series(dates, _index(sessions))
    assert len(segs) == 2
    assert segs[0].start_date == sessions[0]
    assert segs[0].end_date == sessions[19]
    assert segs[1].start_date == sessions[80]
    assert segs[1].gap_sessions_before == 60


def test_a_segment_break_inside_the_window_is_detected():
    sessions = _sessions(120)
    segs = U.segment_series(sessions[:20] + sessions[80:100], _index(sessions))
    assert U.has_segment_break_in(segs, sessions[70], sessions[90])
    assert not U.has_segment_break_in(segs, sessions[0], sessions[19])


def test_empty_series_produces_no_segments():
    assert U.segment_series([], {}) == []


# ------------------------------------------------------ gaps are never filled

def test_a_missing_session_is_absent_from_the_window_not_padded():
    """The rule counts the bars it was given. Nothing here invents a value for
    a session with no bar, which is what a pandas pad default did to the SOL
    hole on 2026-07-26."""
    cand = U.summarize_window("GAPPY", [10.0, 10.0, 10.0], [5.0, 5.0, 5.0],
                              is_fund=False, segment_break_in_window=False)
    assert cand.window_bars == 3
    assert U.rejection_reason(cand, _params()) == "thin_window:3<6"


def test_summarize_refuses_mismatched_or_empty_series():
    assert U.summarize_window("X", [], [], is_fund=False,
                              segment_break_in_window=False) is None
    assert U.summarize_window("X", [1.0], [1.0, 2.0], is_fund=False,
                              segment_break_in_window=False) is None


# ------------------------------------------------------------ discontinuities

def test_detect_discontinuities_finds_both_directions_and_nothing_else():
    dates = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
    closes = [100.0, 105.0, 10.0, 30.0]  # +5%, -90%, +200%
    hits = U.detect_discontinuities(dates, closes)
    assert [h.date for h in hits] == ["2020-01-06", "2020-01-07"]


def test_a_ten_for_one_split_artifact_is_split_shaped_and_a_squeeze_is_not():
    assert U.is_split_shaped(0.1)
    assert U.is_split_shaped(2.0)
    assert not U.is_split_shaped(0.62)
    assert not U.is_split_shaped(1.75)


def test_a_zero_or_negative_prior_close_is_skipped_not_divided_by():
    assert U.detect_discontinuities(["a", "b"], [0.0, 50.0]) == []


# ----------------------------------------------------------------- classifier

@pytest.mark.parametrize("name,exchange,expected", [
    ("Apple Inc. Common Stock", "NASDAQ", False),
    ("Microsoft Corporation Common Stock", "NASDAQ", False),
    ("SPDR S&P 500 ETF Trust", "ARCA", True),
    ("Invesco QQQ Trust, Series 1", "NASDAQ", True),
    ("iShares Core S&P 500 ETF", "ARCA", True),
    ("ProShares S&P 500 Dynamic Buffer ETF", "BATS", True),
    ("Some Fundamental Company Inc", "NYSE", False),   # "Fundamental" != "Fund"
    ("Bank of America Corporation", "NYSE", False),
])
def test_fund_classifier(name, exchange, expected):
    assert U.classify_fund(name, exchange) is expected


# ------------------------------------------------- fail closed on the unknown

def test_a_symbol_with_no_metadata_is_unclassified_not_an_operating_company():
    """THE DEFECT THIS GUARDS. The classifier used to return a bare bool, so a
    symbol carrying no name read as "not a fund" and was ADMITTED. That is how
    SPLG, an S&P 500 tracker, reached 51 of 124 formation books."""
    assert U.classify_fund("", "") is None
    assert U.classify_fund("", "NASDAQ") is None
    assert U.classify_fund(None, None) is None


def test_an_unclassified_candidate_is_excluded_rather_than_admitted():
    assert U.rejection_reason(_cand("UNK", 1e9, is_fund=None),
                              _params()) == "unclassified"


def test_unclassified_is_excluded_even_when_the_caller_asks_for_funds():
    """Unclassified is not a fund, it is an unknown, so include_funds does not
    reach it. Otherwise the fund-inclusive variant would admit the very
    symbols whose type could not be established."""
    assert U.rejection_reason(_cand("UNK", 1e9, is_fund=None),
                              _params(include_funds=True)) == "unclassified"


def test_an_unclassified_symbol_never_reaches_the_book_at_any_rank():
    """Even the most liquid name in the market is refused when its type
    cannot be established."""
    members, rejected = U.rank_members(
        [_cand("HUGE", 1e12, is_fund=None), _cand("REAL", 1.0)],
        _params(top_n=5))
    assert [m.candidate.symbol for m in members] == ["REAL"]
    assert ("HUGE", "unclassified") in rejected


def test_a_known_pooled_vehicle_is_rejected_at_every_formation_date():
    """SPLG, the vehicle that leaked, plus the other six found by the audit."""
    leaked = [
        ("SPDR Portfolio S&P 500 ETF", "ARCA"),
        ("VanEck Russia ETF", "BATS"),
        ("DBX ETF Trust Xtrackers California Municipal Bonds ETF", "NASDAQ"),
        ("Tradr 2X Long GS Daily ETF", "BATS"),
        ("MicroSectors FANG+ Index 3X Leveraged ETNs due January 8", "ARCA"),
        ("JP Morgan Alerian MLP Index ETN 5/24/24", "ARCA"),
    ]
    for name, exch in leaked:
        assert U.classify_fund(name, exch) is True, name
        cand = _cand("X", 1e9, is_fund=U.classify_fund(name, exch))
        # Rejected at every formation date because the rule is stateless:
        # the same inputs give the same rejection every month.
        for _ in range(3):
            assert U.rejection_reason(cand, _params()) == "fund"


@pytest.mark.parametrize("name,exchange", [
    ("The Charles Schwab Corporation", "NYSE"),        # brand token "schwab"
    ("Invesco LTD", "NYSE"),                           # brand token "invesco"
    ("Franklin Resources, Inc.", "NYSE"),              # brand token "franklin"
    ("Northern Trust Corporation Common Stock", "NASDAQ"),   # one weak token
    ("Vornado Realty Trust", "NYSE"),                        # one weak token
    ("Horizon Therapeutics Public Limited Company Ordinary Shares", "NASDAQ"),
    ("Abcam plc American Depositary Shares", "NASDAQ"),      # an ADR
])
def test_operating_companies_are_not_mistaken_for_pooled_vehicles(name,
                                                                  exchange):
    """The over-match that excluded four large caps from the universe
    entirely. A brand name is not a structure, and one weak marker is not
    evidence."""
    assert U.classify_fund(name, exchange) is False


@pytest.mark.parametrize("name,exchange", [
    ("State Street SPDR S&P 500 ETF Trust", "ARCA"),
    ("Invesco QQQ Trust, Series 1", "NASDAQ"),
    ("ProShares UltraPro QQQ", "NASDAQ"),
    ("Direxion Daily Semiconductor Bull 3X ETF", "ARCA"),
    ("PRINCIPAL REAL ESTATE INCOME FUND", "NYSE"),
])
def test_liquid_pooled_vehicles_are_still_caught(name, exchange):
    """The narrowing must not open a hole for the funds that actually trade
    at top-500 liquidity."""
    assert U.classify_fund(name, exchange) is True


def test_membership_is_reproducible_from_the_rule_alone():
    """Same inputs, same membership, twice, with the candidate order shuffled
    in between. Nothing in the rule reads a clock, a file, or an order."""
    cands = [_cand(f"S{i:03d}", float(1000 - i)) for i in range(50)]
    first, _ = U.rank_members(cands, _params(top_n=10))
    second, _ = U.rank_members(list(reversed(cands)), _params(top_n=10))
    assert [m.candidate.symbol for m in first] == \
           [m.candidate.symbol for m in second]
    assert [m.rank for m in first] == list(range(1, 11))


# --------------------------------------------------------------------- median

def test_median_is_the_middle_not_the_mean():
    assert U.median([1.0, 2.0, 1000.0]) == 2.0
    assert U.median([1.0, 3.0]) == 2.0


def test_median_refuses_an_empty_sequence_rather_than_returning_zero():
    with pytest.raises(ValueError):
        U.median([])

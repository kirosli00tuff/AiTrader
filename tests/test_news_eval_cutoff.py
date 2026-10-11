"""news_eval.cutoff: the 9.1 day rule (D18) and the 9.7 cutoff S* (D16), over counts."""
from __future__ import annotations

import dataclasses
import json

import pytest

from news_eval import constants as K
from news_eval import cutoff

R, P, X = K.OUTCOME_RESOLVED, K.OUTCOME_PENDING, K.OUTCOME_EXCLUDED
SF, J, NN = K.STATE_SOURCE_FAILED, K.STATE_JUDGED, K.STATE_NO_NEWS


# ------------------------------------------------------------ 9.1 day rule

def test_day_rule_share_strictly_above_twenty_percent_excludes():
    counts = {
        "2026-08-03": {SF: 20, J: 80},          # exactly 0.20: kept
        "2026-08-04": {SF: 21, J: 79},          # 0.21: excluded
        "2026-08-05": {J: 50, NN: 50},          # 0: kept
        "2026-08-06": {SF: 3},                  # 1.0: excluded
    }
    excluded, shares = cutoff.excluded_query_dates(counts)
    assert excluded == ("2026-08-04", "2026-08-06")
    assert shares == {"2026-08-03": 0.20, "2026-08-04": 0.21,
                      "2026-08-05": 0.0, "2026-08-06": 1.0}
    assert list(shares) == sorted(shares)


def test_day_rule_denominator_is_every_state():
    # 3 source_failed of 12 rows over five states = 0.25 > 0.20.
    counts = {"2026-08-03": {SF: 3, J: 3, NN: 3, K.STATE_MODEL_FAILED: 2,
                             K.STATE_EXCLUDED_PRE_CALL: 1}}
    excluded, shares = cutoff.excluded_query_dates(counts)
    assert excluded == ("2026-08-03",) and shares["2026-08-03"] == 0.25


def test_day_rule_empty_input_and_bad_counts():
    assert cutoff.excluded_query_dates({}) == ((), {})
    with pytest.raises(ValueError):
        cutoff.excluded_query_dates({"2026-08-03": {J: -1}})
    with pytest.raises(ValueError):
        cutoff.excluded_query_dates({"2026-08-03": {J: 0}})
    with pytest.raises(ValueError):
        cutoff.excluded_query_dates({None: {J: 1}})
    with pytest.raises(ValueError):
        cutoff.excluded_query_dates({"2026-08-03": {J: 1.5}})


# --------------------------------------------------------------- 9.7 S*

def _sessions(n: int) -> list[str]:
    return [f"2026-08-{d:02d}" for d in range(3, 3 + n)]


def test_s_star_latest_session_when_nothing_pending():
    s = _sessions(4)
    out = cutoff.compute_s_star({x: {R: 5} for x in s})
    assert out.s_star == s[-1] and out.case == cutoff.CASE_NO_PENDING
    assert out.sessions == tuple(s)
    assert out.latest_resolved == s[-1]
    assert out.earliest_nonstale_pending is None
    assert out.stale_pending == () and out.stale_pending_rows == 0


def test_s_star_strictly_before_earliest_nonstale_pending():
    s = _sessions(6)
    status = {x: {R: 5} for x in s}
    status[s[3]] = {R: 4, P: 1}           # pending at index 3
    status[s[5]] = {P: 2}                 # pending at index 5
    out = cutoff.compute_s_star(status)
    assert out.latest_resolved == s[4]
    assert out.earliest_nonstale_pending == s[3]
    assert out.s_star == s[2] and out.case == cutoff.CASE_PENDING_CUTOFF


def test_stale_boundary_is_more_than_three_sessions():
    s = _sessions(8)
    status = {x: {R: 5} for x in s}
    status[s[3]] = {R: 1, P: 2}   # 7 - 3 = 4 > 3: stale
    status[s[4]] = {R: 1, P: 1}   # 7 - 4 = 3: not stale, holds S* back
    out = cutoff.compute_s_star(status)
    assert out.stale_pending == ((s[3], 2),)
    assert out.stale_pending_rows == 2
    assert out.earliest_nonstale_pending == s[4]
    assert out.s_star == s[3]


def test_only_stale_pending_does_not_hold_s_star_back():
    s = _sessions(9)
    status = {x: {R: 5} for x in s}
    status[s[0]] = {P: 1}
    status[s[2]] = {R: 3, P: 4}
    out = cutoff.compute_s_star(status)
    assert out.stale_pending == ((s[0], 1), (s[2], 4))
    assert out.stale_pending_rows == 5
    assert out.s_star == s[-1] and out.case == cutoff.CASE_NO_PENDING


def test_empty_and_null_session_pending_counted_not_holding_back():
    s = _sessions(3)
    status = {x: {R: 5} for x in s}
    status[None] = {P: 2, R: 9}
    status[""] = {P: 3}
    out = cutoff.compute_s_star(status)
    assert out.empty_session_pending == 5
    assert out.sessions == tuple(s)
    assert out.s_star == s[-1]


def test_other_outcome_states_place_but_neither_resolve_nor_hold():
    s = _sessions(4)
    status = {s[0]: {R: 2}, s[1]: {R: 2}, s[2]: {X: 3}, s[3]: {X: 1}}
    out = cutoff.compute_s_star(status)
    assert out.sessions == tuple(s)
    assert out.latest_resolved == s[1]
    # No pending row at all: S* is the latest session on the order (D16).
    assert out.s_star == s[3]


def test_staleness_uses_session_index_not_calendar_days():
    # Sessions skip a weekend; the index distance is what counts.
    s = ["2026-08-07", "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"]
    status = {x: {R: 1} for x in s}
    status[s[0]] = {P: 1}   # index distance 4 from the latest: stale
    out = cutoff.compute_s_star(status)
    assert out.stale_pending == ((s[0], 1),)
    assert out.s_star == s[-1]


def test_no_resolved_session_gives_none():
    s = _sessions(3)
    out = cutoff.compute_s_star({x: {P: 1} for x in s})
    assert out.s_star is None and out.case == cutoff.CASE_NO_RESOLVED
    assert out.latest_resolved is None
    assert out.stale_pending == ()          # undefined without a resolved one
    assert out.earliest_nonstale_pending == s[0]


def test_first_session_pending_gives_none():
    s = _sessions(3)
    status = {x: {R: 2} for x in s}
    status[s[0]] = {R: 2, P: 1}
    out = cutoff.compute_s_star(status)
    assert out.s_star is None
    assert out.case == cutoff.CASE_FIRST_SESSION_PENDING


def test_no_sessions_gives_none():
    out = cutoff.compute_s_star({})
    assert out.s_star is None and out.case == cutoff.CASE_NO_SESSIONS
    out = cutoff.compute_s_star({None: {P: 4}})
    assert out.s_star is None and out.empty_session_pending == 4


def test_zero_count_session_is_not_placed():
    out = cutoff.compute_s_star({"2026-08-03": {R: 1}, "2026-08-04": {P: 0}})
    assert out.sessions == ("2026-08-03",) and out.s_star == "2026-08-03"


def test_session_order_is_iso_string_order_whatever_the_dict_order():
    status = {"2026-08-05": {R: 1}, "2026-08-03": {R: 1},
              "2026-08-04": {P: 1}}
    out = cutoff.compute_s_star(status)
    assert out.sessions == ("2026-08-03", "2026-08-04", "2026-08-05")
    assert out.s_star == "2026-08-03"


@pytest.mark.parametrize("bad", ["08/03/2026", "2026-8-3", " 2026-08-03", 5])
def test_non_iso_session_refused(bad):
    with pytest.raises(ValueError):
        cutoff.compute_s_star({bad: {R: 1}})


def test_negative_count_refused():
    with pytest.raises(ValueError):
        cutoff.compute_s_star({"2026-08-03": {R: -1}})


def test_result_is_frozen_and_serialisable():
    out = cutoff.compute_s_star({"2026-08-03": {R: 1}, "2026-08-04": {P: 2}})
    with pytest.raises(dataclasses.FrozenInstanceError):
        out.s_star = "x"  # type: ignore[misc]
    again = json.loads(json.dumps(out.as_dict()))
    assert again["s_star"] == "2026-08-03"
    assert again["sessions"] == ["2026-08-03", "2026-08-04"]


def test_inputs_are_not_mutated():
    status = {"2026-08-03": {R: 1}, None: {P: 1}}
    snapshot = json.dumps({str(k): v for k, v in status.items()},
                          sort_keys=True)
    cutoff.compute_s_star(status)
    assert json.dumps({str(k): v for k, v in status.items()},
                      sort_keys=True) == snapshot

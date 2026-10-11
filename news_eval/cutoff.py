"""The 9.1 day exclusion and the 9.7 S* cutoff, over COUNTS only (STAGE C.1).

Both functions are pure: they take the count dictionaries the GATE loader phase
returns (news_eval.data.GatePhase.state_counts_by_query_date and
judged_session_status) and never touch a database or a row. They are shared by
news_eval.gate, news_eval.family and news_eval.run_c2, so their signatures are
part of the frozen harness:

    excluded_query_dates(state_counts) -> (excluded, shares)
    compute_s_star(session_status) -> SStar

Definitions (EXPERIMENT.md Amendment 9; reports/c1_verdict_mapping.md D16, D18):

- 9.1 and Task 7 "How absence is visible", D18: for each collection query_date
  the share is source_failed rows over all run_kind = 'collection' rows of
  that query_date, and the day is excluded when the share EXCEEDS 0.20
  (constants.SOURCE_FAILED_DAY_EXCLUDE, strictly greater than).
- 9.7 cutoff S*, D16: sessions are ordered as ISO date strings over the
  distinct non-empty scoring_session values among judged collection rows. A
  pending row is stale when index(latest resolved session) minus index(its
  session) exceeds 3 (constants.STALE_PENDING_SESSIONS). S* is the latest
  session strictly before the earliest non-stale pending session, or the latest
  session when no non-stale pending row exists. A pending row with an empty or
  NULL scoring_session is counted and reported and does not hold S* back.

Cases D16 leaves open, fixed here (C.1 HarnessCoder decision, reported):

- No resolved session at all: s_star is None (nothing can be scorable, since
  9.7 needs outcome_state = 'resolved'), and staleness is undefined, so no
  pending row is called stale.
- The earliest non-stale pending session is the first session: s_star is None
  (no session lies strictly before it).
- No session at all: s_star is None.

A None s_star therefore always means "the analysis set is EMPTY". It never
means "no cutoff": callers must not pass None to a loader method that reads
None as "no filter" (news_eval.data.GatePhase.gate_rows does). `SStar.case`
names which case applied.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from news_eval import constants as K

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# SStar.case values.
CASE_NO_SESSIONS = "no_sessions"
CASE_NO_RESOLVED = "no_resolved_session"
CASE_FIRST_SESSION_PENDING = "earliest_nonstale_pending_is_first_session"
CASE_PENDING_CUTOFF = "before_earliest_nonstale_pending"
CASE_NO_PENDING = "latest_session_no_nonstale_pending"


# ------------------------------------------------------------- 9.1 day rule

def _check_count(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"count must be a non-negative int at {where}: "
                         f"{value!r}")
    return value


def excluded_query_dates(
        state_counts: Mapping[str, Mapping[str, int]]
) -> tuple[tuple[str, ...], dict[str, float]]:
    """The 9.1 / Task 7 day rule (D18) over collection-row counts.

    state_counts: {query_date: {state: count}} for run_kind = 'collection'
    rows, as GatePhase.state_counts_by_query_date returns it.

    Returns (excluded, shares): `excluded` is the sorted tuple of query_dates
    whose source_failed share exceeds SOURCE_FAILED_DAY_EXCLUDE; `shares` maps
    EVERY query_date (sorted) to its source_failed share. A query_date with no
    rows, a non-string query_date or a negative count raises ValueError.
    """
    shares: dict[str, float] = {}
    for query_date in sorted(state_counts, key=lambda d: (d is None, str(d))):
        if not isinstance(query_date, str) or not query_date:
            raise ValueError(f"query_date must be a non-empty string: "
                             f"{query_date!r}")
        by_state = state_counts[query_date]
        total = 0
        for state, count in by_state.items():
            total += _check_count(count, f"{query_date}/{state}")
        if total == 0:
            raise ValueError(f"query_date {query_date} has no rows")
        failed = _check_count(by_state.get(K.STATE_SOURCE_FAILED, 0),
                              f"{query_date}/{K.STATE_SOURCE_FAILED}")
        shares[query_date] = failed / total
    excluded = tuple(d for d, share in shares.items()
                     if share > K.SOURCE_FAILED_DAY_EXCLUDE)
    return excluded, shares


# ------------------------------------------------------------- 9.7 cutoff S*

@dataclass(frozen=True)
class SStar:
    """The 9.7 cutoff (D16), with everything needed to report it.

    s_star: the latest scoring_session in the analysis set, or None when the
        analysis set is empty (see the module docstring; never "no cutoff").
    case: which D16 case applied (one of the CASE_* constants).
    sessions: the ordered distinct non-empty scoring_session values.
    latest_resolved: the latest session holding a resolved row, or None.
    earliest_nonstale_pending: the earliest session holding a non-stale
        pending row, or None.
    stale_pending: ((session, pending count), ...) in session order.
    stale_pending_rows: total pending rows in stale sessions.
    empty_session_pending: pending rows with an empty or NULL scoring_session
        (counted, reported, never holding S* back).
    """
    s_star: str | None
    case: str
    sessions: tuple[str, ...]
    latest_resolved: str | None
    earliest_nonstale_pending: str | None
    stale_pending: tuple[tuple[str, int], ...]
    stale_pending_rows: int
    empty_session_pending: int

    def as_dict(self) -> dict:
        """A JSON-serialisable copy (lists for tuples)."""
        return {
            "s_star": self.s_star,
            "case": self.case,
            "sessions": list(self.sessions),
            "latest_resolved": self.latest_resolved,
            "earliest_nonstale_pending": self.earliest_nonstale_pending,
            "stale_pending": [[s, n] for s, n in self.stale_pending],
            "stale_pending_rows": self.stale_pending_rows,
            "empty_session_pending": self.empty_session_pending,
        }


def _split_sessions(
        session_status: Mapping[str | None, Mapping[str, int]]
) -> tuple[dict[str, Mapping[str, int]], int]:
    """Non-empty sessions (validated ISO dates) and the empty-session pending count."""
    placed: dict[str, Mapping[str, int]] = {}
    empty_pending = 0
    for session, by_outcome in session_status.items():
        for outcome, count in by_outcome.items():
            _check_count(count, f"{session!r}/{outcome}")
        if session is None or session == "":
            empty_pending += by_outcome.get(K.OUTCOME_PENDING, 0)
            continue
        if not isinstance(session, str) or not _ISO_DATE_RE.match(session):
            raise ValueError(f"scoring_session must be an ISO date string: "
                             f"{session!r}")
        if sum(by_outcome.values()) > 0:
            placed[session] = by_outcome
    return placed, empty_pending


def compute_s_star(
        session_status: Mapping[str | None, Mapping[str, int]]) -> SStar:
    """The 9.7 cutoff S* (D16) from judged collection-row counts.

    session_status: {scoring_session or None or '': {outcome_state: count}}
    for run_kind = 'collection', state = 'judged' rows, as
    GatePhase.judged_session_status returns it. Outcome states other than
    'resolved' and 'pending' place a session on the order but neither resolve
    it nor hold S* back. Raises ValueError on a non-ISO session or a bad count.
    """
    placed, empty_pending = _split_sessions(session_status)
    sessions = tuple(sorted(placed))
    index = {s: i for i, s in enumerate(sessions)}
    resolved = [s for s in sessions
                if placed[s].get(K.OUTCOME_RESOLVED, 0) > 0]
    pending = [s for s in sessions
               if placed[s].get(K.OUTCOME_PENDING, 0) > 0]
    latest_resolved = resolved[-1] if resolved else None

    stale: list[tuple[str, int]] = []
    nonstale: list[str] = []
    for s in pending:
        if latest_resolved is not None and (
                index[latest_resolved] - index[s] > K.STALE_PENDING_SESSIONS):
            stale.append((s, placed[s][K.OUTCOME_PENDING]))
        else:
            nonstale.append(s)
    earliest_nonstale = nonstale[0] if nonstale else None

    if not sessions:
        s_star, case = None, CASE_NO_SESSIONS
    elif latest_resolved is None:
        s_star, case = None, CASE_NO_RESOLVED
    elif earliest_nonstale is None:
        s_star, case = sessions[-1], CASE_NO_PENDING
    elif index[earliest_nonstale] == 0:
        s_star, case = None, CASE_FIRST_SESSION_PENDING
    else:
        s_star = sessions[index[earliest_nonstale] - 1]
        case = CASE_PENDING_CUTOFF

    return SStar(
        s_star=s_star,
        case=case,
        sessions=sessions,
        latest_resolved=latest_resolved,
        earliest_nonstale_pending=earliest_nonstale,
        stale_pending=tuple(stale),
        stale_pending_rows=sum(n for _, n in stale),
        empty_session_pending=empty_pending,
    )

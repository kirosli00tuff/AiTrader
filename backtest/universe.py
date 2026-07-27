"""Hindsight-free universe construction for the analysis database.

Pure functions only: no network, no database, no clock. Everything here
decides membership from bars dated STRICTLY BEFORE the formation date, so a
decision made at date f can never move when later data arrives. That
property is the point of the module and is pinned by
tests/test_universe_rule.py.

Terms used throughout:

  formation date   the first trading session of a calendar month. Membership
                   decided here governs that month.
  trailing window  the WINDOW_SESSIONS trading sessions ending on the last
                   session strictly before the formation date.
  segment          a maximal run of a symbol's bars with no gap longer than
                   SEGMENT_BREAK_SESSIONS. A ticker reused by a second
                   listing produces two segments, and the two are never one
                   price series.

The one input here that is NOT point-in-time is the fund classification,
which reads a present-day instrument name. It is stated rather than hidden:
an instrument's fund-ness does not change over time and is not derived from
its performance or its survival, so it cannot leak an outcome.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

# Rule constants. Named because a threshold buried in a call site cannot be
# re-derived by a reader six months from now.
WINDOW_SESSIONS = 60          # about one calendar quarter of trading
MIN_WINDOW_BARS = 40          # a symbol silent for a third of the window is
                              # not liquid enough to rank honestly
MIN_MEDIAN_CLOSE = 5.0        # USD. Penny-stock floor, measured IN the window
TOP_N = 500                   # members per formation date
SEGMENT_BREAK_SESSIONS = 20   # a hole this long ends a listing segment
JUMP_THRESHOLD = 0.50         # |close-to-close| above this is a discontinuity

# Name tokens that identify a pooled investment vehicle rather than an
# operating company. Order does not matter; matching is case-insensitive on
# word boundaries so "Fundamental" does not match "Fund".
_FUND_TOKENS = (
    "etf", "etn", "fund", "trust", "index", "portfolio", "shares",
    "ishares", "spdr", "proshares", "invesco", "vanguard", "wisdomtree",
    "direxion", "etracs", "ipath", "vaneck", "franklin", "schwab",
    "closed end", "royalty", "commodity", "bull", "bear",
)
_FUND_RE = re.compile(r"\b(" + "|".join(_FUND_TOKENS) + r")\b", re.IGNORECASE)

# Exchanges that list essentially only exchange-traded products. Used as a
# second, independent signal beside the name so a fund with an unhelpful
# name is still caught.
FUND_EXCHANGES = frozenset({"ARCA", "BATS"})


def classify_fund(name: str, exchange: str) -> bool:
    """True when the instrument is a pooled vehicle, not an operating company.

    Two independent signals: the listing venue and the instrument name. ARCA
    and BATS list exchange-traded products almost exclusively, so venue alone
    settles those. Elsewhere the name decides.
    """
    if (exchange or "").upper() in FUND_EXCHANGES:
        return True
    return bool(_FUND_RE.search(name or ""))


def median(values: Sequence[float]) -> float:
    """Median of a non-empty sequence. Raises on empty rather than guessing."""
    if not values:
        raise ValueError("median of an empty sequence")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


@dataclass(frozen=True)
class RuleParams:
    """Every knob the membership rule has. Frozen so a caller cannot mutate
    the rule between formation dates and produce an unlabelled hybrid."""
    window_sessions: int = WINDOW_SESSIONS
    min_window_bars: int = MIN_WINDOW_BARS
    min_median_close: float = MIN_MEDIAN_CLOSE
    top_n: int = TOP_N
    include_funds: bool = False

    @property
    def rule_id(self) -> str:
        kind = "all" if self.include_funds else "stk"
        return (f"U-LIQ-{self.top_n}-{kind}-w{self.window_sessions}"
                f"-m{self.min_window_bars}-p{self.min_median_close:g}")


@dataclass(frozen=True)
class Candidate:
    """One symbol's trailing-window summary. Built from bars strictly before
    the formation date and from nothing else."""
    symbol: str
    window_bars: int
    median_close: float
    median_dollar_volume: float
    is_fund: bool
    segment_break_in_window: bool


@dataclass(frozen=True)
class Member:
    rank: int
    candidate: Candidate


def summarize_window(symbol: str, closes: Sequence[float],
                     volumes: Sequence[float], *, is_fund: bool,
                     segment_break_in_window: bool) -> Candidate | None:
    """Reduce one symbol's window to a Candidate, or None when it has no bars.

    Dollar volume is close times volume per session, then the median over
    sessions. The median, not the mean, so one squeeze day cannot buy
    membership for a name that is otherwise untradeable.
    """
    if not closes or len(closes) != len(volumes):
        return None
    return Candidate(
        symbol=symbol,
        window_bars=len(closes),
        median_close=median(closes),
        median_dollar_volume=median([c * v for c, v in zip(closes, volumes)]),
        is_fund=is_fund,
        segment_break_in_window=segment_break_in_window,
    )


def rejection_reason(cand: Candidate, params: RuleParams) -> str | None:
    """Why this candidate cannot be a member, or None when it can be ranked.

    Returned rather than raised so every rejection can be recorded. A filter
    that rejects silently cannot be evaluated.
    """
    if cand.window_bars < params.min_window_bars:
        return f"thin_window:{cand.window_bars}<{params.min_window_bars}"
    if cand.median_close < params.min_median_close:
        return f"below_price_floor:{cand.median_close:.2f}"
    if cand.segment_break_in_window:
        return "listing_segment_break_in_window"
    if cand.is_fund and not params.include_funds:
        return "fund"
    return None


def rank_members(candidates: Iterable[Candidate], params: RuleParams
                 ) -> tuple[list[Member], list[tuple[str, str]]]:
    """Rank eligible candidates by median dollar volume, take the top N.

    Returns the members and the (symbol, reason) rejections. Ties break on
    symbol ascending so the same inputs always produce the same membership.
    """
    eligible: list[Candidate] = []
    rejected: list[tuple[str, str]] = []
    for cand in candidates:
        reason = rejection_reason(cand, params)
        if reason:
            rejected.append((cand.symbol, reason))
        else:
            eligible.append(cand)
    eligible.sort(key=lambda c: (-c.median_dollar_volume, c.symbol))
    members = [Member(rank=i + 1, candidate=c)
               for i, c in enumerate(eligible[:params.top_n])]
    for c in eligible[params.top_n:]:
        rejected.append((c.symbol, f"below_rank_{params.top_n}"))
    return members, rejected


def formation_dates(sessions: Sequence[str], params: RuleParams) -> list[str]:
    """First trading session of each month that has a full trailing window.

    `sessions` is the exchange trading calendar as ascending YYYY-MM-DD, not
    the dates one symbol happened to trade: a formation schedule keyed off a
    symbol's own bars would shift whenever that symbol was quiet.
    """
    out: list[str] = []
    seen_months: set[str] = set()
    for i, day in enumerate(sessions):
        month = day[:7]
        if month in seen_months:
            continue
        seen_months.add(month)
        if i >= params.window_sessions:
            out.append(day)
    return out


def window_bounds(sessions: Sequence[str], formation_date: str,
                  window_sessions: int) -> tuple[str, str]:
    """The trailing window as [start, end] inclusive session dates.

    The window ENDS on the session before the formation date. A window that
    included the formation date would decide membership using a bar the month
    it governs could trade on.
    """
    idx = sessions.index(formation_date)
    if idx < window_sessions:
        raise ValueError(f"{formation_date} has no full trailing window")
    return sessions[idx - window_sessions], sessions[idx - 1]


@dataclass(frozen=True)
class Segment:
    """One continuous listing run of a ticker."""
    index: int
    start_date: str
    end_date: str
    n_bars: int
    gap_sessions_before: int


def segment_series(bar_dates: Sequence[str], session_index: dict[str, int],
                   max_gap_sessions: int = SEGMENT_BREAK_SESSIONS
                   ) -> list[Segment]:
    """Split a ticker's bar dates into listing segments.

    The gap is counted in TRADING SESSIONS, not calendar days, so a holiday
    week is never mistaken for a delisting. More than one segment means the
    ticker carried more than one listing and the segments must never be
    joined into a single price series.
    """
    if not bar_dates:
        return []
    segments: list[Segment] = []
    start = bar_dates[0]
    count = 1
    gap_before = 0
    for prev, cur in zip(bar_dates, bar_dates[1:]):
        gap = session_index[cur] - session_index[prev] - 1
        if gap > max_gap_sessions:
            segments.append(Segment(len(segments), start, prev, count,
                                    gap_before))
            start, count, gap_before = cur, 1, gap
        else:
            count += 1
    segments.append(Segment(len(segments), start, bar_dates[-1], count,
                            gap_before))
    return segments


def has_segment_break_in(segments: Sequence[Segment], start: str,
                         end: str) -> bool:
    """Whether any segment begins inside [start, end] after the first one."""
    return any(seg.index > 0 and start <= seg.start_date <= end
               for seg in segments)


@dataclass(frozen=True)
class Discontinuity:
    symbol: str
    date: str
    prev_date: str
    ratio: float
    prev_close: float
    close: float


def detect_discontinuities(dates: Sequence[str], closes: Sequence[float],
                           threshold: float = JUMP_THRESHOLD
                           ) -> list[Discontinuity]:
    """Close-to-close moves beyond the threshold, in both directions.

    Reported, never smoothed. A real stock can legitimately move this far in
    one session, so a hit is a thing to ATTRIBUTE (to a split, to news, to a
    failed adjustment), not a thing to correct.
    """
    out: list[Discontinuity] = []
    for (pd, pc), (d, c) in zip(zip(dates, closes), zip(dates[1:], closes[1:])):
        if pc <= 0:
            continue
        ratio = c / pc
        if ratio > 1.0 + threshold or ratio < 1.0 / (1.0 + threshold):
            out.append(Discontinuity("", d, pd, ratio, pc, c))
    return out


# Ratios a missed split adjustment would leave behind. A discontinuity landing
# on one of these with no recorded corporate action is the shape that means
# the adjustment failed, as opposed to the market simply moving.
SPLIT_SHAPED_RATIOS = (0.5, 1.0 / 3, 0.25, 0.2, 0.1, 2.0, 3.0, 4.0, 5.0, 10.0)


def is_split_shaped(ratio: float, tolerance: float = 0.05) -> bool:
    """Whether a jump ratio looks like an unadjusted split rather than a move."""
    return any(abs(ratio - r) <= tolerance * r for r in SPLIT_SHAPED_RATIOS)

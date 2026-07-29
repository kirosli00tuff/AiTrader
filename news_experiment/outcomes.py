"""Prices and the scored outcome (EXPERIMENT.md Tasks 4, 5 and 8).

SEPARATE FROM COLLECTION ON PURPOSE. A headline collected today has no next
session yet, so its outcome fields cannot exist at collection time. Writing
zeros there would be the fabrication this project has corrected five times, so
a fresh row is written `outcome_state = 'pending'` and this module fills it in
once the scoring session has closed. `pending` and a resolved 0.0 return are
different facts and the column keeps them apart.

WHAT IS COMPUTED, from Task 5:

    raw_i      the symbol's return over its scoring window (adjustment=all)
    bench_i    the UNCONDITIONAL move over the SAME window, equal-weighted
               across every band member that traded it
    excess_i   raw_i - bench_i
    signed_i   +excess when POSITIVE, -excess when NEGATIVE, NEUTRAL unscored
    net_i      signed_i - cost_i

`cost_i` is the per-observation round trip from the liquidity-aware fee model
at the symbol's OWN price and formation ADV, doubled. A single band-average
hurdle would be the large-cap calibration error in a different axis.

A GAP IS ABSENCE, NEVER A FILLED VALUE. A symbol with no bar for its scoring
session is recorded and excluded as `symbol_did_not_trade`, never scored as a
zero return, and never rolled forward: the horizon is fixed at pre-registration
and moving it per observation is how a horizon gets chosen by its result.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field

from backtest import fees as fee_model

from . import spec
from .horizon import Calendar


@dataclass
class PriceBook:
    """Daily opens and closes for the symbols and sessions in play.

    Loaded in one pass rather than one query per row: the window is bounded on
    both sides so the (timeframe, timestamp) index serves it, and a per-row
    query against a 25-million-row table is how a resolve pass takes hours.
    """
    opens: dict[tuple[str, str], float] = field(default_factory=dict)
    closes: dict[tuple[str, str], float] = field(default_factory=dict)
    source: dict[tuple[str, str], str] = field(default_factory=dict)

    @classmethod
    def load(cls, db_path: str, symbols: set[str], start: str,
             end: str) -> "PriceBook":
        book = cls()
        if not symbols:
            return book
        # closing(), never a bare `with` around the connect call: that form
        # is transaction scope and leaks the handle (test_keystore_fd_leak).
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro",
                                     uri=True)) as conn:
            for sym, ts, op, cl, src in conn.execute(
                    "SELECT symbol, timestamp, open, close, source FROM bars "
                    "WHERE timeframe='1day' AND timestamp >= ? "
                    "AND timestamp < ?", (start, end + "T99")):
                if sym not in symbols:
                    continue
                key = (sym, str(ts)[:10])
                if op is not None:
                    book.opens[key] = float(op)
                if cl is not None:
                    book.closes[key] = float(cl)
                # Provenance follows the established rule: an empty or unknown
                # source is `unclassified`, never a silent default.
                book.source[key] = str(src) if src else "unclassified"
        return book

    def has(self, symbol: str, session: str) -> bool:
        return (symbol, session) in self.closes


def band_benchmark(book: PriceBook, members: list[str], anchor_kind: str,
                   anchor_session: str, scoring_session: str) -> float | None:
    """The equal-weighted unconditional move of the band over the same window.

    Equal-weighted because the hypothesis is about names in this band, not
    about a cap-weighted index they barely influence. Members that did not
    trade the window are dropped rather than treated as flat: a non-trading
    name has no return, and counting it as zero would pull the benchmark toward
    zero exactly when liquidity is thin.
    """
    rets: list[float] = []
    for sym in members:
        start = (book.opens.get((sym, scoring_session))
                 if anchor_kind == spec.ANCHOR_NEXT_SESSION_OPEN
                 else book.closes.get((sym, anchor_session)))
        end = book.closes.get((sym, scoring_session))
        if start is None or end is None or start <= 0:
            continue
        rets.append(end / start - 1.0)
    if not rets:
        return None
    return sum(rets) / len(rets)


@dataclass
class Outcome:
    outcome_state: str
    exclusion_reason: str = ""
    anchor_price: float | None = None
    ret_intraday: float | None = None
    ret_1session: float | None = None
    ret_2session: float | None = None
    ret_5session: float | None = None
    ret_10session: float | None = None
    bench_1session: float | None = None
    excess_1session: float | None = None
    bar_source: str = ""
    cost_bp_round_trip: float | None = None
    net_bp: float | None = None


def resolve_one(*, symbol: str, judgment: str | None, anchor_kind: str,
                anchor_session: str, scoring_session: str,
                adv_usd: float | None, notional: float, book: PriceBook,
                cal: Calendar, band_members: list[str]) -> Outcome:
    """Fill one row's outcome, or say why it cannot be filled."""
    if not scoring_session or scoring_session not in cal.sessions:
        return Outcome("pending")

    anchor_price = (book.opens.get((symbol, scoring_session))
                    if anchor_kind == spec.ANCHOR_NEXT_SESSION_OPEN
                    else book.closes.get((symbol, anchor_session)))
    end_price = book.closes.get((symbol, scoring_session))
    if anchor_price is None or end_price is None or anchor_price <= 0:
        # Absence, not a zero. Recorded and excluded, never rolled forward.
        return Outcome("excluded",
                       exclusion_reason=spec.EXCLUSION_SYMBOL_DID_NOT_TRADE)

    if adv_usd is None or adv_usd <= 0:
        # An absent ADV must not fall to the engine's flat 1.3 bp legacy
        # figure here: in this band that would understate the measured cost
        # 14x to 40x, silently inflating net_bp. The engine keeps its
        # deliberate fallback. THIS path refuses (Task 7: absence refuses).
        return Outcome("excluded",
                       exclusion_reason=spec.EXCLUSION_ADV_UNAVAILABLE)

    ret_1 = end_price / anchor_price - 1.0
    # ret_intraday is "anchor to that session's close". For a CLOSE anchor the
    # anchor IS that session's close, so the quantity is a structural zero
    # carrying no information. Left NULL rather than recorded as 0.0 beside
    # genuine intraday returns.
    ret_intraday = (ret_1 if anchor_kind == spec.ANCHOR_NEXT_SESSION_OPEN
                    else None)

    longer: dict[int, float | None] = {}
    for k in spec.RETURN_HORIZONS:
        if k == 1:
            longer[k] = ret_1
            continue
        target = cal.session_ahead(scoring_session, k - 1)
        price = book.closes.get((symbol, target)) if target else None
        longer[k] = (price / anchor_price - 1.0) if price else None

    bench = band_benchmark(book, band_members, anchor_kind, anchor_session,
                           scoring_session)
    excess = (ret_1 - bench) if bench is not None else None

    cost_bp = fee_model.equity_round_trip_bp(anchor_price, adv_usd, notional)
    net_bp = None
    if excess is not None and judgment in (spec.JUDGMENT_POSITIVE,
                                           spec.JUDGMENT_NEGATIVE):
        signed = excess if judgment == spec.JUDGMENT_POSITIVE else -excess
        net_bp = signed * 10_000.0 - cost_bp

    return Outcome(
        outcome_state="resolved",
        anchor_price=anchor_price,
        ret_intraday=ret_intraday,
        ret_1session=longer.get(1),
        ret_2session=longer.get(2),
        ret_5session=longer.get(5),
        ret_10session=longer.get(10),
        bench_1session=bench,
        excess_1session=excess,
        bar_source=book.source.get((symbol, scoring_session), "unclassified"),
        cost_bp_round_trip=cost_bp,
        net_bp=net_bp,
    )

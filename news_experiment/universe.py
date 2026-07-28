"""The ADV-band universe rule (EXPERIMENT.md Task 2), point-in-time.

The shipped `backtest/universe.py` rule is TOP-N BY RANK. This experiment's
rule is an ABSOLUTE ADV BAND with fixed log-spaced strata, which Amendment 1
adopted precisely because rank drifts. The two rules must not be conflated, so
this module is separate and the shipped one is untouched. What IS reused is
every pure helper the two share: `classify_fund` and `median`. Re-deriving
those here would be a second copy of a rule this project has already been
bitten by keeping in two places.

POINT-IN-TIME BY CONSTRUCTION. Only bars dated strictly before the formation
date enter, and the window ends on the session BEFORE it, so a membership
decided at D cannot move when later data arrives.

READ-ONLY. `analysis_bars.db` is opened `mode=ro`. This module writes nothing.
"""
from __future__ import annotations

import hashlib
import random
import sqlite3
from contextlib import closing
from dataclasses import dataclass

from backtest.universe import classify_fund, median

from . import spec


@dataclass(frozen=True)
class BandMember:
    """One symbol admitted by the rule at one formation date."""
    symbol: str
    adv_usd: float
    median_close: float
    window_bars: int
    stratum: str
    liquidity_rank: int      # rank in the eligible pool, recorded not used
    name: str
    exchange: str


def _connect(db_path: str):
    """A read-only connection that CLOSES on exit.

    `contextlib.closing`, never a bare `with` around the connect call. That
    form is transaction scope and never closes the handle, the idiom that
    leaked 1018 of 1024 fds to the keystore in the 2026-07-19 bridge outage.
    `tests/test_keystore_fd_leak.py` bans it in runtime code and caught this
    module before it shipped.
    """
    return closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True))


def load_sessions(db_path: str) -> list[str]:
    """Every exchange session date, ascending. The calendar is authoritative:
    a weekday rule would silently invent holidays (Task 4)."""
    with _connect(db_path) as conn:
        return [r[0] for r in conn.execute(
            "SELECT date FROM trading_calendar ORDER BY date ASC")]


def session_close_time(db_path: str, session: str) -> str | None:
    """The calendar's own close for one session, so a half day is honoured
    rather than a hardcoded 16:00 (Task 4, calendar edge cases)."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT close FROM trading_calendar WHERE date=?", (session,)
        ).fetchone()
    return row[0] if row else None


def quarter_formation_dates(sessions: list[str]) -> list[str]:
    """The first trading session of each calendar quarter that has a full
    trailing window (Task 2 rule step 6)."""
    out: list[str] = []
    seen: set[str] = set()
    for i, day in enumerate(sessions):
        key = f"{day[:4]}Q{(int(day[5:7]) - 1) // 3}"
        if key in seen:
            continue
        seen.add(key)
        if i >= spec.WINDOW_SESSIONS:
            out.append(day)
    return out


def window_for(sessions: list[str], formation_date: str) -> tuple[str, str]:
    """The trailing window as inclusive [start, end] session dates.

    Ends on the session BEFORE the formation date: a window containing D would
    decide membership using a bar the quarter it governs can trade on.
    """
    idx = sessions.index(formation_date)
    if idx < spec.WINDOW_SESSIONS:
        raise ValueError(f"{formation_date} has no full {spec.WINDOW_SESSIONS}"
                         f"-session trailing window")
    return sessions[idx - spec.WINDOW_SESSIONS], sessions[idx - 1]


def _asset_metadata(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    return {r[0]: (r[1] or "", r[2] or "")
            for r in conn.execute("SELECT symbol, name, exchange "
                                  "FROM universe_asset")}


def _segment_breaks(conn: sqlite3.Connection, start: str, end: str) -> set[str]:
    """Symbols whose listing segment restarts inside the window.

    Read from the precomputed `listing_segment` table rather than recomputed,
    because that table is what the survivorship repair built and a second
    derivation would be a second opinion on the same question.
    """
    by_symbol: dict[str, list[str]] = {}
    for sym, seg_start in conn.execute(
            "SELECT symbol, start_date FROM listing_segment "
            "ORDER BY symbol, seg"):
        by_symbol.setdefault(sym, []).append(seg_start)
    return {sym for sym, starts in by_symbol.items()
            if any(start <= s <= end for s in starts[1:])}


def resolve_band(db_path: str, formation_date: str, *,
                 sessions: list[str] | None = None
                 ) -> tuple[list[BandMember], dict[str, int]]:
    """Every symbol the ADV band admits at `formation_date`, plus rejection
    counts by reason.

    The rejection counts are returned rather than dropped because a filter that
    rejects silently cannot be evaluated. Same discipline as
    `backtest.universe.rejection_reason`.
    """
    sessions = sessions or load_sessions(db_path)
    start, end = window_for(sessions, formation_date)

    rejects: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejects[reason] = rejects.get(reason, 0) + 1

    with _connect(db_path) as conn:
        meta = _asset_metadata(conn)
        broken = _segment_breaks(conn, start, end)
        closes: dict[str, list[float]] = {}
        dollar: dict[str, list[float]] = {}
        # Bounded on both sides so the (timeframe, timestamp) index serves the
        # scan. `end` is inclusive, so the exclusive upper bound is the next
        # lexical string after any timestamp on that date.
        for sym, close, vol in conn.execute(
                "SELECT symbol, close, volume FROM bars "
                "WHERE timeframe='1day' AND timestamp >= ? AND timestamp < ? "
                "AND close IS NOT NULL AND volume IS NOT NULL",
                (start, end + "T99")):
            closes.setdefault(sym, []).append(float(close))
            dollar.setdefault(sym, []).append(float(close) * float(vol))

    eligible: list[tuple[float, str, float, int]] = []
    for sym, cl in closes.items():
        if len(cl) < spec.MIN_WINDOW_BARS:
            reject("thin_window")
            continue
        med_close = median(cl)
        if med_close < spec.MIN_MEDIAN_CLOSE:
            reject("below_price_floor")
            continue
        if sym in broken:
            reject("listing_segment_break_in_window")
            continue
        name, exchange = meta.get(sym, ("", ""))
        fund = classify_fund(name, exchange)
        if fund is None:
            # FAIL CLOSED. An instrument whose type cannot be established is an
            # unknown, not an operating company. Admitting it is how an S&P 500
            # tracker reached 51 of 124 formation books.
            reject("unclassified")
            continue
        if fund:
            reject("fund")
            continue
        eligible.append((median(dollar[sym]), sym, med_close, len(cl)))

    # Rank over the whole ELIGIBLE pool, BEFORE the band filter, so
    # `liquidity_rank` means what the superseded rank rule meant and that rule
    # stays scoreable as a pre-registered robustness check (Task 8).
    eligible.sort(key=lambda t: (-t[0], t[1]))

    members: list[BandMember] = []
    for rank, (adv, sym, med_close, bars) in enumerate(eligible, start=1):
        stratum = spec.stratum_for(adv)
        if stratum is None:
            reject("outside_adv_band")
            continue
        name, exchange = meta.get(sym, ("", ""))
        members.append(BandMember(symbol=sym, adv_usd=adv,
                                  median_close=med_close, window_bars=bars,
                                  stratum=stratum, liquidity_rank=rank,
                                  name=name, exchange=exchange))
    return members, rejects


def draw_seed(rule_id: str, formation_date: str) -> int:
    """The deterministic seed: sha256(rule_id + formation_date) (Task 2).

    An integer from the full digest, so the same rule at the same formation
    always draws the same 400 symbols and a reader can reproduce the sample
    without the database.
    """
    digest = hashlib.sha256((rule_id + formation_date).encode("utf-8")).digest()
    return int.from_bytes(digest, "big")


def stratified_sample(members: list[BandMember], *, rule_id: str,
                      formation_date: str,
                      per_stratum: int = spec.SAMPLE_PER_STRATUM
                      ) -> list[BandMember]:
    """100 symbols per stratum, uniform at random within a stratum (Task 2).

    Deterministic three ways: one `Random` seeded from the digest, strata
    visited in the fixed S1..S4 order, and each stratum's candidates sorted by
    symbol before the draw. Without all three the same seed would still produce
    different samples when dict ordering changed.

    A stratum with fewer than `per_stratum` members contributes all of them.
    Stated rather than padded: drawing from a neighbouring stratum to reach 400
    would silently change what a stratum means.
    """
    rng = random.Random(draw_seed(rule_id, formation_date))
    out: list[BandMember] = []
    for name, _lo, _hi in spec.STRATA:
        pool = sorted([m for m in members if m.stratum == name],
                      key=lambda m: m.symbol)
        if len(pool) <= per_stratum:
            out.extend(pool)
            continue
        out.extend(rng.sample(pool, per_stratum))
    return out

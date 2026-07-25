"""THE council's evidence builder. One builder, both council paths.

THE OMISSION RULE (2026-07-20). A field with no real measurement behind it is
omitted entirely, never rendered as a zero or a stand-in. The Stage-B gate
measured the failure this prevents: padded zeros read as flat evidence and
rejected 12 of 12 finalists (discovery/gate.py). The renderer therefore works
from an ALLOWLIST. A key not in the allowlist never renders, so a future field
cannot reach a model without declaring its units and its source here first.

ONE BUILDER, BOTH PATHS (2026-07-25). ``build_state`` is the only assembler of
council evidence. Before this, the DB-derived sections came from here while the
quote-level fields were assembled twice: the trading path sent whatever the C++
engine happened to put on the /score/llm payload, and the discovery path
computed its own in ``discovery.evaluate.market_state_from``. Two assemblers is
how the two paths came to render different field sets under the same prompt
template. Callers now hand this module a market OBSERVATION under canonical
keys and it applies the units, the scales, and the omission rule once.

Fields the engine sends that this module deliberately never renders, because
no real measurement stands behind them (reported in RETURN.md 2026-07-20):
  * imbalance    uniform random in [-1,1] every tick, even on the real feed
  * catalyst     a per-symbol hash constant from MockCatalystProvider
  * ret_5        sum of the last five poll-tick returns, window unstated
  * volatility   stddev of those tick returns, window unstated
Bar-derived returns with stated windows replace the last two. Volume renders
only from venue-reported volume provenance.

A SERIES THE PRICE CONTRADICTS IS NOT EVIDENCE (2026-07-25). LDO/USD, eval 49,
carried twelve identical 5-minute closes at 0.3863 beside a last price of
0.3749, a 3.0 percent gap, with rvol 0 against ADX 97.1. The series was 23
hours old: the symbol had been pruned from the watchlist, so nothing polled it
any more, while the price beside it came live from a different source. Opus
identified the tape as non-updating and Gemini misread it as illiquidity. The
builder now bounds a series two ways before rendering it, and omits it (with
the reason recorded for the operator, never rendered) when either bound fails.

Enrichment reads the shared SQLite database READ-ONLY (uri mode=ro) and never
raises: any failure yields empty evidence and the prompt renders without those
sections. It runs only when the caller passes an explicit db path, so unit
tests stay hermetic.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from market_data.tradeable import VENUE_VOLUME_SOURCES, real_bar_rows

# Bar windows, in 5-minute bars.
_BARS_1H = 12
_BARS_4H = 48
_BARS_24H = 288
_CLOSES_SHOWN = 12

# --- The bounds a bar series must clear to be current evidence ---------------
#
# Both answer the same question: does this series describe the SAME market
# state as the price beside it? Neither is a trading threshold and neither
# touches a risk value. They decide what a prompt may claim, not what the
# system may do.

# Six 5-minute bars. Wide enough that an ordinary poll gap or a quiet crypto
# minute does not disqualify a live series, tight enough that a symbol nothing
# polls any more cannot pass. LDO/USD failed this by 23 hours.
MAX_BAR_AGE_SECONDS = 1800

# The newest close and the quoted price are two reads of one instrument taken
# moments apart, so they agree closely or one of them is not current. LDO/USD
# failed this by 3.0 percent.
MAX_PRICE_DIVERGENCE_PCT = 1.0

# Below this a series is a fragment, not a tape: the returns computed from it
# describe a window whose shape the model cannot see.
MIN_SERIES_CLOSES = 8


def _num(x, nd: int = 4) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    return f"{v:.{nd}f}".rstrip("0").rstrip(".") or "0"


def _pct(x) -> str:
    try:
        return f"{float(x):+.2f}"
    except (TypeError, ValueError):
        return str(x)


def _positive(x) -> float | None:
    """A strictly positive float, or None. None means NOT MEASURED, and every
    caller must omit rather than substitute: that is the omission rule."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _parse_ts(ts) -> datetime | None:
    """An ISO-8601 UTC bar stamp, or None when it cannot be established.

    Both stored shapes parse: the Z-suffixed form the engine and the backfill
    write (2026-07-24T01:05:05Z) and an explicit offset. An unparseable stamp
    is not treated as fresh: the caller reads None as unknown age, which fails
    the freshness bound rather than passing it.
    """
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(timezone.utc)


# The allowlist: state key -> (rendered label, units and scale text). Every
# entry MUST carry a non-empty units text, pinned by test. A state key not
# listed here (and not part of a gathered evidence section) never renders.
# The units text renders ONCE, in the system prompt's legend (the cacheable
# stable prefix), not on every user line (2026-07-20 token optimization).
ALLOWED_FIELDS: dict[str, tuple[str, str]] = {
    "price": ("price", "USD, last trade"),
    "daily_return_pct": ("daily_return", "percent, today vs prior close"),
    "intraday_range_pct": ("intraday_range", "percent of price, day low to day high in USD"),
    "news_sentiment": ("news_sentiment", "[0,1], 0.5 is neutral, Finnhub company news score"),
}

# The canonical market OBSERVATION a caller hands the builder: raw venue
# numbers under one set of names, in the units the venue reports them. The
# trading path fills it from the engine's MarketState, the discovery path from
# the Stage-A snapshot (discovery.evaluate.market_state_from). Turning these
# into rendered evidence is quote_evidence's job and nobody else's.
OBSERVATION_FIELDS = ("price", "day_high", "day_low", "daily_change_pct",
                      "news_sentiment")

# The legend for the gathered-evidence sections. Same contract: every entry
# declares units, rendered once in the system prefix.
EVIDENCE_SECTION_LEGEND: dict[str, str] = {
    "closes_5min": "USD, five-minute closes, oldest first, real venue bars, "
                   "newest timestamp attached",
    "return_1h": "percent over the last 12 five-minute bars",
    "return_4h": "percent over the last 48 five-minute bars",
    "return_24h": "percent over the last 288 five-minute bars",
    "volume_24h": "base units summed over 24h of venue-reported bars",
    "regime": "engine regime detector: label, adx trend-strength index, rvol "
              "stddev of 5-minute returns, the active strategy factor, and "
              "when it was written",
    "open_position": "this system's open position for the instrument, or none",
}

# Long-mode extras, same contract.
LONG_SECTION_LEGEND: dict[str, str] = {
    "fundamentals": "quality [0,1] composite, roe_ttm and net_margin_ttm and "
                    "revenue_growth_yoy in percent, pe_ttm ratio, week52 "
                    "high and low in USD, only reported components shown",
    "catalyst": "the live catalyst the free screen found: kind and detail",
}


def field_legend(long_term: bool = False) -> str:
    """The one-per-mode legend block embedded in the system prompt.

    Units render here ONCE per conversation prefix instead of on every user
    line, so they ride the provider prompt cache instead of being paid per
    call.
    """
    entries = [(label, units) for label, units in ALLOWED_FIELDS.values()]
    entries += list(EVIDENCE_SECTION_LEGEND.items())
    if long_term:
        entries += list(LONG_SECTION_LEGEND.items())
    return "Evidence field legend, units apply to every call:\n" + "\n".join(
        f"  {label}: {units}" for label, units in entries)


def _resolve_db(db: str) -> str:
    if os.path.isabs(db):
        return db
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo, db)


# --- Bar-series integrity ----------------------------------------------------

@dataclass(frozen=True)
class SeriesIntegrity:
    """Whether a bar series may be presented as current evidence.

    ``reason`` is empty when ok, otherwise one of the named failures below. It
    is recorded for the operator and read by the pre-call refusal; it never
    renders into a prompt, because a prompt states what WAS measured and this
    is a statement about what was not.
    """
    ok: bool
    reason: str = ""
    detail: str = ""
    age_seconds: float | None = None
    divergence_pct: float | None = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason, "detail": self.detail,
                "age_seconds": self.age_seconds,
                "divergence_pct": self.divergence_pct}


def bar_series_integrity(*, closes: list, newest_ts, price=None,
                         now: datetime | None = None) -> SeriesIntegrity:
    """Is this series current, long enough, and consistent with the price?

    Pure, so the whole rule is testable without a database. Three failures,
    each named, checked cheapest first:

      too_short           fewer than MIN_SERIES_CLOSES closes
      stale               newest bar older than MAX_BAR_AGE_SECONDS, or a
                          stamp that cannot be parsed at all
      price_inconsistent  newest close more than MAX_PRICE_DIVERGENCE_PCT from
                          the quoted price

    A missing price cannot make the series inconsistent, so that check is
    skipped rather than failed: the price is a separate measurement and its
    absence is handled by the evidence minimum.
    """
    if not closes or len(closes) < MIN_SERIES_CLOSES:
        return SeriesIntegrity(
            False, "too_short",
            f"{len(closes or [])} closes, need {MIN_SERIES_CLOSES}")

    stamp = _parse_ts(newest_ts)
    if stamp is None:
        return SeriesIntegrity(
            False, "stale",
            f"newest bar timestamp unreadable ({newest_ts!r})")
    age = (_now(now) - stamp).total_seconds()
    if age > MAX_BAR_AGE_SECONDS:
        return SeriesIntegrity(
            False, "stale",
            f"newest bar {age / 60.0:.0f} minutes old, bound is "
            f"{MAX_BAR_AGE_SECONDS // 60} minutes", age_seconds=age)

    quoted = _positive(price)
    newest_close = _positive(closes[-1])
    if quoted is None or newest_close is None:
        return SeriesIntegrity(True, age_seconds=age)
    divergence = abs(quoted / newest_close - 1.0) * 100.0
    if divergence > MAX_PRICE_DIVERGENCE_PCT:
        return SeriesIntegrity(
            False, "price_inconsistent",
            f"newest close {newest_close:.6g} against price {quoted:.6g}, "
            f"{divergence:.2f} percent apart, bound is "
            f"{MAX_PRICE_DIVERGENCE_PCT:.2f} percent",
            age_seconds=age, divergence_pct=divergence)
    return SeriesIntegrity(True, age_seconds=age, divergence_pct=divergence)


# --- The quote assembler -----------------------------------------------------

def intraday_range_pct(price, day_high, day_low) -> float | None:
    """Day range as a percent of price, or None when it was not measured.

    THE one place this arithmetic lives. It was written twice before
    2026-07-25, here and in discovery.evaluate, which is how the two council
    paths came to disagree about which fields a candidate is judged on.
    """
    px, high, low = _positive(price), _positive(day_high), _positive(day_low)
    if px is None or high is None or low is None or high <= low:
        return None
    return round((high - low) / px * 100.0, 4)


def quote_evidence(observation: dict) -> dict:
    """Rendered allowlist fields from ONE market observation. THE assembler.

    Reads the canonical OBSERVATION_FIELDS and applies the units and scales
    the legend declares. A field whose input is absent, unparseable, or
    non-positive where positive is required is OMITTED from the result: it is
    never zeroed, defaulted, or carried over. Returns a new dict and mutates
    nothing.
    """
    out: dict = {}
    price = _positive(observation.get("price"))
    if price is not None:
        out["price"] = price

    change = observation.get("daily_change_pct")
    if change is not None:
        try:
            out["daily_return_pct"] = round(float(change), 4)
        except (TypeError, ValueError):
            pass

    span = intraday_range_pct(price, observation.get("day_high"),
                              observation.get("day_low"))
    if span is not None:
        out["intraday_range_pct"] = span
        out["day_high"] = _positive(observation.get("day_high"))
        out["day_low"] = _positive(observation.get("day_low"))

    sentiment = observation.get("news_sentiment")
    if sentiment is not None:
        try:
            out["news_sentiment"] = float(sentiment)
        except (TypeError, ValueError):
            pass
    return out


# --- The recorded evidence sections ------------------------------------------

def gather_evidence(symbol: str, db_path: str, *, price=None,
                    now: datetime | None = None) -> dict:
    """Real recorded evidence for one symbol from the shared database.

    Returns a dict of sections (bars, regime, position), each present only when
    the database actually holds it AND it survives its integrity bound. Read
    only, never raises.

    ``price`` is the live quote the same call will render, so the bar series
    can be checked against it. ``now`` is injectable so the freshness bound is
    testable without waiting.
    """
    out: dict = {}
    try:
        conn = sqlite3.connect(f"file:{_resolve_db(db_path)}?mode=ro", uri=True)
    except Exception:
        return out
    try:
        out.update(_bar_evidence(conn, symbol, price=price, now=now))
        out.update(_regime_evidence(conn, symbol, now=now))
        out.update(_position_evidence(conn, symbol))
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def _bar_evidence(conn: sqlite3.Connection, symbol: str, *, price=None,
                  now: datetime | None = None) -> dict:
    """Closes and returns from real-provenance 5-minute bars, oldest first.

    The provenance query lives in market_data.tradeable (real_bar_rows), the
    invariant's one home. A series that fails its integrity bound is OMITTED
    whole, together with every number derived from it (the three window
    returns and the 24h volume), because those describe the same non-current
    tape. The failure is recorded under ``bars_refused`` for the operator and
    for the pre-call refusal; that key is in no legend, so it never renders.

    Volume renders only when EVERY bar in the window carries venue-reported
    volume provenance. A row whose volume_source is NULL predates the label
    and cannot prove where its number came from, so it is not summed: the
    provenance rule applies to volume exactly as it applies to price.
    """
    rows = real_bar_rows(conn, symbol, timeframe="5min", limit=_BARS_24H)
    if not rows:
        return {"bars_refused": {
            "ok": False, "reason": "no_series",
            "detail": "no real-provenance 5-minute bars for this symbol"}}
    closes = [r[1] for r in rows]  # newest first
    shown = [round(float(c), 6) for c in reversed(closes[:_CLOSES_SHOWN])]
    newest_ts = str(rows[0][0])

    integrity = bar_series_integrity(closes=shown, newest_ts=newest_ts,
                                     price=price, now=now)
    if not integrity.ok:
        return {"bars_refused": integrity.to_dict()}

    out: dict = {"closes_5min": shown, "closes_5min_last_ts": newest_ts,
                 "closes_5min_age_seconds": int(integrity.age_seconds or 0)}
    now_close = float(closes[0])
    for label, n in (("return_1h_pct", _BARS_1H), ("return_4h_pct", _BARS_4H),
                     ("return_24h_pct", _BARS_24H)):
        if len(closes) >= n:
            then = float(closes[n - 1])
            if then > 0:
                out[label] = round((now_close / then - 1.0) * 100.0, 4)
    if all(r[4] in VENUE_VOLUME_SOURCES for r in rows):
        out["volume_24h_base"] = round(sum(float(r[2] or 0.0) for r in rows), 4)
    return out


def _regime_evidence(conn: sqlite3.Connection, symbol: str, *,
                     now: datetime | None = None) -> dict:
    """The engine's own persisted regime read: label, ADX, realized vol,
    active strategy factor, and when it was written.

    Held to the SAME freshness bound as the bar series, because it is computed
    FROM that series: LDO/USD's frozen tape produced ADX 97.1 beside rvol 0,
    an artifact of a non-updating series that reads as a screaming trend. A
    regime older than the bound describes a market that has since moved on, so
    it is omitted rather than presented as the current read.
    """
    try:
        row = conn.execute(
            "SELECT regime, adx, rvol, active_factor, updated_ts "
            "FROM regime_state WHERE symbol=?", (symbol,)).fetchone()
    except sqlite3.OperationalError:
        return {}
    if not row:
        return {}
    stamp = _parse_ts(row[4])
    if stamp is None or (_now(now) - stamp).total_seconds() > MAX_BAR_AGE_SECONDS:
        return {}
    return {"regime": {
        "label": str(row[0]), "adx": round(float(row[1] or 0.0), 2),
        "realized_vol": round(float(row[2] or 0.0), 6),
        "active_factor": str(row[3] or ""), "as_of": str(row[4] or ""),
    }}


def _position_evidence(conn: sqlite3.Connection, symbol: str) -> dict:
    """Open position for this exact symbol, or the true statement that none
    exists. Both are real measurements of the positions table."""
    try:
        row = conn.execute(
            "SELECT side, qty, avg_price, opened_ts, unrealized_pnl "
            "FROM positions WHERE symbol=? AND ABS(qty) > 1e-12 "
            "ORDER BY opened_ts DESC LIMIT 1", (symbol,)).fetchone()
    except sqlite3.OperationalError:
        return {}
    if not row:
        return {"position": None}
    return {"position": {
        "side": str(row[0]), "qty": float(row[1]),
        "avg_price": float(row[2]), "opened_ts": str(row[3]),
        "unrealized_pnl": float(row[4] or 0.0),
    }}


# --- THE builder -------------------------------------------------------------

def build_state(state: dict, *, db_path: str | None = None,
                now: datetime | None = None) -> dict:
    """Assemble the complete council evidence for one state. THE builder.

    Both council paths call this and only this, so a discovery candidate and a
    trading candidate are judged on the same fields, with the same units, the
    same scales, and the same absent-field rule.

    Two halves, in order, because the second needs the first:
      1. quote_evidence over the caller's market observation
      2. gather_evidence over the recorded database, checked against the price
         the first half produced

    Returns a NEW dict; the caller's is never mutated. Idempotent: a state
    that already carries ``_evidence`` keeps it, which is what lets a test
    inject an evidence block directly and what stops a re-entrant call from
    paying for a second database read.
    """
    out = {**state, **quote_evidence(state)}
    if "_evidence" in state:
        return out
    symbol = str(state.get("symbol") or "")
    if db_path and symbol:
        out["_evidence"] = gather_evidence(symbol, str(db_path),
                                           price=out.get("price"), now=now)
    return out


# --- The pre-call refusal ----------------------------------------------------

# THE COUNCIL EVIDENCE MINIMUM (2026-07-25). A spend and correctness control,
# not a threshold: it decides whether a question is worth asking, never what
# an answer means or what the system may do with one.
#
# A council call is made only when the assembled evidence carries ALL of:
#   1. a positive price
#   2. a real-provenance 5-minute close series
#   3. that series at least MIN_SERIES_CLOSES long
#   4. that series fresh within MAX_BAR_AGE_SECONDS
#   5. that series within MAX_PRICE_DIVERGENCE_PCT of the price
#
# The set is not invented. It is what all three providers named as missing
# across ten consecutive all-abstain discovery evaluations on 2026-07-25:
# "the evidence lacks 5-minute closes, volume, regime, and multi-hour returns"
# (gpt-5.5 on SEI/USD), "without momentum fields, news sentiment, volume, or
# regime data, I cannot confirm" (claude-opus-4-8 on ZEC/USD), "without
# short-term price action, volume data, or regime context, it is impossible to
# determine" (gemini-3.1-pro-preview on SEI/USD). The series is the root: the
# window returns and the regime are computed from it, so a symbol that has one
# has them all and a symbol that lacks it has none.
#
# Deliberately NOT in the minimum: volume, regime, news sentiment, position.
# Each is genuinely absent for some serviceable instrument (a quiet crypto
# minute reports no volume, a newly onboarded symbol has no regime row yet,
# crypto has no Finnhub news sentiment), so refusing on those would suppress
# calls the evidence CAN answer. The bar is the floor of what the providers
# said they needed, not a wish list.

_NO_SERIES_DETAIL = "no real-provenance 5-minute bars for this symbol"


@dataclass(frozen=True)
class EvidenceRefusal:
    """Why a council call was not made. Recorded, never rendered."""
    reason: str
    detail: str

    def to_dict(self) -> dict:
        return {"reason": self.reason, "detail": self.detail}


def evidence_refusal(state: dict) -> EvidenceRefusal | None:
    """The pre-call check. None means the evidence can answer the question.

    Pure over an already-built state, so it can never itself spend anything,
    and so the whole rule is testable without a provider or a database.

    WE ONLY REFUSE WHEN WE ACTUALLY LOOKED. A state carrying no ``_evidence``
    asked for no database enrichment, so there is nothing to judge and nothing
    is refused. That is not a hole: every path that can spend real money
    passes a db (the bridge defaults it onto /score/llm and /research/thesis,
    discovery/run.py always passes db_path), so a state without one is the
    hermetic offline path whose providers are deterministic mocks costing
    nothing. Refusing there would suppress calls on the strength of a
    database the caller deliberately did not offer.
    """
    evidence = state.get("_evidence")
    if not isinstance(evidence, dict):
        return None
    if _positive(state.get("price")) is None:
        return EvidenceRefusal(
            "no_price", "no positive price was measured for this instrument")
    if evidence.get("closes_5min"):
        return None
    refused = evidence.get("bars_refused") or {}
    reason = str(refused.get("reason") or "no_series")
    detail = str(refused.get("detail") or _NO_SERIES_DETAIL)
    if reason == "no_series":
        return EvidenceRefusal("no_series", detail)
    return EvidenceRefusal(f"bar_series_{reason}", detail)


def _sig(x, digits: int = 5) -> str:
    """Compact significant-digit formatting: precision beyond what a model
    can use is pure token cost."""
    try:
        return f"{float(x):.{digits}g}"
    except (TypeError, ValueError):
        return str(x)


def _quote_lines(state: dict) -> list[str]:
    lines: list[str] = []
    for key, (label, _units) in ALLOWED_FIELDS.items():
        if key not in state or state.get(key) is None:
            continue
        val = state[key]
        if key == "price":
            try:
                if float(val) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            lines.append(f"{label}: {_sig(val, 6)}")
        elif key == "daily_return_pct":
            lines.append(f"{label}: {_pct(val)}")
        elif key == "intraday_range_pct":
            hi, lo = state.get("day_high"), state.get("day_low")
            span = (f" (low {_sig(lo, 6)}, high {_sig(hi, 6)})"
                    if hi is not None and lo is not None else "")
            lines.append(f"{label}: {_num(val, 2)}{span}")
        else:
            lines.append(f"{label}: {_num(val, 4)}")
    return lines


def _bar_lines(ev: dict) -> list[str]:
    lines: list[str] = []
    closes = ev.get("closes_5min")
    if closes:
        compact = "[" + ", ".join(_sig(c, 5) for c in closes) + "]"
        lines.append(f"closes_5min: {compact} newest "
                     f"{ev.get('closes_5min_last_ts', '?')}")
    for key in ("return_1h_pct", "return_4h_pct", "return_24h_pct"):
        if key in ev:
            lines.append(f"{key.replace('_pct', '')}: {_pct(ev[key])}")
    if "volume_24h_base" in ev:
        lines.append(f"volume_24h: {_num(ev['volume_24h_base'], 2)}")
    return lines


def _engine_lines(ev: dict) -> list[str]:
    lines: list[str] = []
    reg = ev.get("regime")
    if reg:
        lines.append(f"regime: {reg['label']}, adx {_sig(reg['adx'], 3)}, "
                     f"rvol {_sig(reg['realized_vol'], 3)}, active "
                     f"{reg['active_factor'] or 'unset'}, as of {reg['as_of']}")
    if "position" in ev:
        pos = ev["position"]
        if pos is None:
            lines.append("open_position: none")
        else:
            lines.append(
                f"open_position: {pos['side']} qty {_sig(pos['qty'], 6)} at "
                f"avg {_sig(pos['avg_price'], 6)} since {pos['opened_ts']}, "
                f"upnl {_num(pos['unrealized_pnl'], 2)}")
    return lines


def _fundamental_lines(state: dict) -> list[str]:
    """Long-term evidence: quality, fundamentals, and the live catalyst, only
    the components that were actually reported. Units live in the legend."""
    lines: list[str] = []
    fin = state.get("fundamentals")
    if isinstance(fin, dict) and fin:
        parts = [f"{key} {_num(fin[key], 4)}" for key in (
            "quality", "roe_ttm", "net_margin_ttm", "revenue_growth_yoy",
            "pe_ttm", "week52_high", "week52_low") if fin.get(key) is not None]
        if parts:
            lines.append("fundamentals: " + ", ".join(parts))
    cat = state.get("catalyst_detail")
    if cat:
        lines.append(f"catalyst: {cat}")
    return lines


def render_user_prompt(state: dict) -> str:
    """Render the evidence block a provider receives. Allowlist only.

    A key absent from the allowlist and the evidence sections never renders,
    whatever the state carries. Absent fields are omitted, never zeroed.
    """
    from .prompts import prompt_mode
    sym = str(state.get("symbol", "?"))
    cat = str(state.get("category", "") or "")
    venue = str(state.get("venue", "") or "")
    header = f"Instrument: {sym}"
    if cat:
        header += f" ({cat})"
    if venue:
        header += f" on venue {venue}"
    question = ("multi-week holding thesis"
                if prompt_mode(state) == "long_term"
                else "immediate setup, the next few hours on 5-minute bars")

    ev = state.get("_evidence") or {}
    lines = _quote_lines(state) + _bar_lines(ev) + _engine_lines(ev)
    if prompt_mode(state) == "long_term":
        lines += _fundamental_lines(state)
    if not lines:
        lines = ["(no measured fields are available for this instrument)"]

    return (f"{header}\n"
            f"Question: {question}\n\n"
            "Evidence (absent fields were not measured):\n"
            + "\n".join(lines) + "\n"
            "Answer with the required JSON object.")

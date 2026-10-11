"""Seeded synthetic news_observation databases with known answers (STAGE C.1 Task 2).

Each scenario builds a SQLite file with the exact real schema (read at run
time from news_eval/schema.sql, never copied here), fills it with rows shaped
the way news_experiment/collect.py and outcomes.py write them, and stamps it
with news_eval.marker so the loader's SYNTHETIC phase accepts it. A scenario's
expected answer is stated in its docstring entry below and, machine-readably,
in SCENARIOS[name].expected, using the vocabulary of
reports/c1_verdict_mapping.md.

Row shapes mirrored from the collector (read-only reads of collect.py 200-520,
outcomes.py 160-245, spec.py):
- source_failed: error_class 'source_unreachable', no headline, outcome_state
  'pending' forever (the default; such rows never resolve).
- no_news: fetched_ts set, error_class NULL, outcome_state 'pending' forever.
- excluded_pre_call: exclusion_reason = error_class in (no_publication_time,
  clock_inconsistent, duplicate_headline), outcome_state 'excluded', no anchor.
  Only a duplicate carries a story_group_id.
- model_failed: anchor and scoring_session set (the anchor resolves before the
  call), judgment NULL, parse_ok 0, error_class in the model-failure list.
  The resolver selects every pending row with a scoring_session, so these
  rows resolve too: excess present, net_bp NULL (no judgment).
- judged: judgment, strength (1 to 5 directional, 1 on NEUTRAL, NULL with
  strength_parse_ok 0 on a few), error_class ''. Outcome 'pending' until the
  scoring session closes, then 'resolved' (or 'excluded' with
  symbol_did_not_trade). excess_1session = ret_1session - bench_1session as
  fractions; net_bp = signed_bp - cost_bp_round_trip for directional rows and
  NULL for NEUTRAL; a resolved row whose benchmark is absent has NULL bench,
  excess and net_bp but keeps ret_1session and cost.
- run_kind 'collection' everywhere except a block of 'demonstration' rows that
  every harness phase must ignore: they include source_failed rows that would
  push their day over 20 percent, pending judged rows that would hold S* back,
  and resolved directional rows with a large excess.

Per-scenario structure (all scenarios): all five states; NEUTRAL near 30
percent of judged; one collection query_date whose source_failed share is
above 0.20 and every other day at or below about 0.10; query_dates split
half and half between their own session and the next; both formations
(2026-07-01 before 2026-10-01, 2026-10-01 from then on); 8.2 rule (a)
symbols, rule (b) closed-end funds, SECZ (Financial Services on most rows,
'N/A' on the rows of four fixed collection days, not excluded) and GLQ (modal 'N/A' in the 2026-07-01
formation only, so excluded there only, D9); shared story groups; a pinned
handful of resolved judged rows with NULL excess.

Numbers quoted as "calibration (scratch, not the harness)" come from
reports/c1_scratch/synth/calib.py, an independent numpy implementation of
9.4 to 9.10 with 10,000 bootstrap draws and 10,000 within-session label
shuffles, run on the built databases. They are the margins behind each
expected answer, not harness output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from news_eval import marker

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
REAL_DB_NAME = "news_experiment.db"

# --- strings the collector writes (pinned against news_experiment/spec.py by
# tests/test_news_eval_synthetic.py) ------------------------------------------
RULE_ID = "U-NEWS-ADV2M-65M-stk-w60-m40-p5-s400"
SPEC_VERSION = "EXPERIMENT.md@amendment-3-accepted-2026-07-28"
MODEL_ID = "claude-haiku-4-5"
PROMPT_SHA = hashlib.sha256(b"synthetic system block").hexdigest()
STATE_NO_NEWS, STATE_JUDGED = "no_news", "judged"
STATE_MODEL_FAILED, STATE_PRE_CALL = "model_failed", "excluded_pre_call"
STATE_SOURCE_FAILED = "source_failed"
STATES = (STATE_NO_NEWS, STATE_JUDGED, STATE_MODEL_FAILED, STATE_PRE_CALL,
          STATE_SOURCE_FAILED)
SOURCE_FAILED_CLASS = "source_unreachable"
PRE_CALL_CLASSES = ("no_publication_time", "clock_inconsistent",
                    "duplicate_headline")
MODEL_FAILED_CLASSES = ("transport", "timeout", "http_status", "unparseable")
EXHAUSTED = "exhausted"
EXHAUSTED_DAYS = ("2026-10-02", "2026-10-05")   # Amendment 9.14
DID_NOT_TRADE = "symbol_did_not_trade"
ANCHOR_CLOSE, ANCHOR_OPEN = "same_session_close", "next_session_open"
POS, NEG, NEU = "POSITIVE", "NEGATIVE", "NEUTRAL"
RUN_COLLECTION, RUN_DEMO = "collection", "demonstration"
SECTOR_SOURCE = "finnhub_profile2"
NA = "N/A"

# --- calendar ---------------------------------------------------------------
_HOLIDAYS = frozenset({"2026-09-07", "2026-11-26", "2026-12-25"})
_EARLY_CLOSE = frozenset({"2026-11-27", "2026-12-24"})
_DST_END = "2026-11-01"


def _session_list() -> tuple[str, ...]:
    out, d = [], date(2026, 7, 28)
    while d <= date(2026, 12, 31):
        if d.weekday() < 5 and d.isoformat() not in _HOLIDAYS:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return tuple(out)


SESSIONS: tuple[str, ...] = _session_list()   # NYSE, 2026-07-28 onward
FORMATION_JULY, FORMATION_OCT = "2026-07-01", "2026-10-01"


def formation_for(query_date: str) -> str:
    return FORMATION_JULY if query_date < FORMATION_OCT else FORMATION_OCT


def _utc_offset(day: str) -> int:
    return 4 if day < _DST_END else 5


def _ts(day: str, hh: int, mm: int, ss: int = 0, et: bool = True) -> str:
    """ISO-8601 UTC for a wall time on `day`; `et` means America/New_York."""
    base = date.fromisoformat(day)
    hour = hh + (_utc_offset(day) if et else 0)
    stamp = (np.datetime64(base.isoformat()) + np.timedelta64(hour, "h")
             + np.timedelta64(mm, "m") + np.timedelta64(ss, "s"))
    return str(stamp.astype("datetime64[s]")) + "Z"


def _open_ts(day: str) -> str:
    return _ts(day, 9, 30)


def _close_ts(day: str) -> str:
    return _ts(day, 13 if day in _EARLY_CLOSE else 16, 0)


# --- universe ---------------------------------------------------------------
RULE_A = ("ARES.PRB", "BAC.PRL", "BF.A", "NEE.PRV", "STRK", "UHAL.B",
          "WFC.PRL")
RULE_B = ("BCX", "BUI", "GDV", "HQH")
SECZ_LIKE = "SECZ"
FORMATION_ONLY_NA = "GLQ"          # modal 'N/A' in 2026-07-01 only
STRATA = ("S1", "S2", "S3", "S4")
_ADV_BOUNDS = {"S1": (27_553_544.0, 65_300_000.0),
               "S2": (11_626_306.0, 27_553_544.0),
               "S3": (4_905_757.0, 11_626_306.0),
               "S4": (2_070_000.0, 4_905_757.0)}
COST_BP = {"S1": 16.0, "S2": 21.0, "S3": 31.0, "S4": 50.0}
SIGMA_BP = {"S1": 110.0, "S2": 125.0, "S3": 160.0, "S4": 190.0}
_NEWS_RATE = {"S1": 0.50, "S2": 0.44, "S3": 0.38, "S4": 0.32}
_INDUSTRIES = ("Technology", "Banking", "Pharmaceuticals", "Biotechnology",
               "Retail", "Semiconductors", "Media", "Real Estate",
               "Utilities", "Insurance", "Machinery", "Financial Services",
               "Energy", "Aerospace & Defense")
_SPECIAL_STRATUM = {"BAC.PRL": "S1", "WFC.PRL": "S1", "BF.A": "S1",
                    "NEE.PRV": "S1", "BCX": "S1", "GDV": "S1",
                    "ARES.PRB": "S2", "UHAL.B": "S2", "STRK": "S2",
                    "BUI": "S2", "HQH": "S2", "GLQ": "S2", "SECZ": "S3"}
_NORMAL_PER_STRATUM = {"S1": 22, "S2": 22, "S3": 27, "S4": 28}
UNIVERSE_SEED = 20261100


@dataclass(frozen=True)
class Symbol:
    symbol: str
    stratum: str
    kind: str                      # normal | rule_a | rule_b | secz | glq
    sector: str
    adv: float
    median_close: float
    news_rate: float
    cost_bp: float
    etb: int
    formations: tuple[str, ...]


def _normal_name(i: int, stratum: str) -> str:
    tail = "WXYZ"[STRATA.index(stratum)]
    return "K" + chr(65 + (i // 26) % 26) + chr(65 + i % 26) + tail


def _build_universe() -> tuple[Symbol, ...]:
    rng = np.random.default_rng(UNIVERSE_SEED)
    out: list[Symbol] = []

    def make(name: str, stratum: str, kind: str, sector: str,
             formations: tuple[str, ...], rate_mult: float) -> Symbol:
        lo, hi = _ADV_BOUNDS[stratum]
        adv = float(np.exp(rng.uniform(np.log(lo) + 0.02, np.log(hi) - 0.02)))
        close = float(10.5 + np.exp(rng.normal(3.3, 0.7)))
        rate = float(np.clip(_NEWS_RATE[stratum] * rate_mult
                             * np.exp(rng.normal(0, 0.25)), 0.08, 0.9))
        cost = float(COST_BP[stratum] * np.exp(rng.normal(0, 0.08)))
        etb = int(rng.random() < 0.8)
        return Symbol(name, stratum, kind, sector, round(adv, 2),
                      round(close, 4), rate, cost, etb, formations)

    both = (FORMATION_JULY, FORMATION_OCT)
    for s in STRATA:
        n = _NORMAL_PER_STRATUM[s]
        for i in range(n):
            # two names per stratum leave at the October formation and two
            # join it, so the formations' samples differ as real ones do
            forms = (both if i < n - 4 else
                     (FORMATION_JULY,) if i < n - 2 else (FORMATION_OCT,))
            sector = _INDUSTRIES[int(rng.integers(len(_INDUSTRIES)))]
            out.append(make(_normal_name(i, s), s, "normal", sector, forms,
                            1.0))
    for name in RULE_A:
        out.append(make(name, _SPECIAL_STRATUM[name], "rule_a",
                        "Financial Services", both, 1.6))
    for name in RULE_B:
        out.append(make(name, _SPECIAL_STRATUM[name], "rule_b", NA, both,
                        0.9))
    out.append(make(SECZ_LIKE, "S3", "secz", "Financial Services", both, 1.0))
    out.append(make(FORMATION_ONLY_NA, "S2", "glq", NA, both, 1.0))
    return tuple(out)


UNIVERSE: tuple[Symbol, ...] = _build_universe()


def sens_excluded_design(symbol: str, formation: str) -> bool:
    """The 8.2 membership the generator plants (the data must agree, D9)."""
    if "." in symbol or symbol in ("STRK", "STRF", "STRD", "STRC"):
        return True
    if symbol in RULE_B:
        return True
    return symbol == FORMATION_ONLY_NA and formation == FORMATION_JULY


SECZ_NA_DAYS = frozenset({"2026-08-04", "2026-09-15", "2026-09-22",
                          "2026-10-13"})


def _sector_for(sym: Symbol, formation: str, query_date: str,
                rng) -> tuple[str | None, str]:
    """One draw per (symbol, collection day): the collector caches per run."""
    u = rng.random()
    if sym.kind == "normal":
        return (None, "unresolved") if u < 0.02 else (sym.sector,
                                                      SECTOR_SOURCE)
    if sym.kind == "rule_a":
        return (None, "unresolved") if u < 0.03 else (sym.sector,
                                                      SECTOR_SOURCE)
    if sym.kind == "rule_b":
        if u < 0.06:
            return None, "unresolved"
        if u < 0.12:
            return "Financial Services", SECTOR_SOURCE
        return NA, SECTOR_SOURCE
    if sym.kind == "secz":
        return ((NA, SECTOR_SOURCE) if query_date in SECZ_NA_DAYS
                else ("Financial Services", SECTOR_SOURCE))
    na_share = 0.85 if formation == FORMATION_JULY else 0.08
    return (NA, SECTOR_SOURCE) if u < na_share else ("Financial Services",
                                                     SECTOR_SOURCE)


# --- scenario parameters ----------------------------------------------------
@dataclass(frozen=True)
class Params:
    n_days: int = 64
    start: int = 0                     # index into SESSIONS of the first day
    pos_share: float = 0.70            # POSITIVE among directional units
    neutral_share: float = 0.30        # NEUTRAL among judged units
    pair_bp: float = 0.0               # POSITIVE +x, NEGATIVE -x in excess
    sens_pair_bp: float = 0.0          # same, only on 8.2-excluded rows
    premium_bp: float = 0.0            # unconditional, every judged row
    sess_sd_bp: float = 12.0           # common scoring_session component
    alt_signed_bp: float = 0.0         # +-A per session, signed by judgment
    story_frac: float = 0.06           # share of headline slots in groups
    story_sd_bp: float = 40.0          # common shock inside a shared story
    sf_rate: float = 0.015
    sf_day: int = 20                   # day index whose share exceeds 0.20
    sf_day_rate: float = 0.40
    bump_day: int = 35                 # day index near 0.06 to 0.10 (kept)
    bump_rate: float = 0.06
    cutoff: bool = False               # S-CUTOFF edge and stale row
    n_null_dir: int = 7                # resolved directional, NULL excess
    n_null_neu: int = 2                # resolved NEUTRAL, NULL excess
    not_traded_rate: float = 0.012
    sigma_scale: float = 1.0           # multiplies SIGMA_BP
    cost_mult: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)


@dataclass(frozen=True)
class Scenario:
    name: str
    seed: int
    description: str
    params: Params
    expected: Mapping[str, Any] = field(default_factory=dict)




# --- row construction ---------------------------------------------------------
_SHA_EARLY = "3f1c9a7e2b6d4c58a0e1f7b39d2c6a4e8b1f0d57"
_SHA_LATE = "c426318a9d0e47b2f6a3c1e58b7d9f20a4c6e1b3"
_SOURCES = ("Yahoo", "SeekingAlpha", "Benzinga", "MarketWatch", "Reuters",
            "Finnhub")
_VERBS = ("raises guidance", "misses estimates", "announces buyback",
          "prices offering", "wins contract", "cuts dividend",
          "beats revenue forecast", "names new CEO", "faces probe",
          "expands partnership", "receives downgrade", "receives upgrade")
_REASONS = {POS: "Headline implies improved fundamentals.",
            NEG: "Headline implies deteriorating fundamentals.",
            NEU: "Headline is routine or not price relevant."}
_STRENGTH_P = (0.08, 0.24, 0.36, 0.23, 0.09)
_T_DF = 5
_T_SCALE = float(np.sqrt(_T_DF / (_T_DF - 2)))


def _ranks() -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for f in (FORMATION_JULY, FORMATION_OCT):
        members = sorted((s for s in UNIVERSE if f in s.formations),
                         key=lambda s: (-_adv(s, f), s.symbol))
        for i, s in enumerate(members, start=1):
            out[(s.symbol, f)] = i
    return out


def _adv(sym: Symbol, formation: str) -> float:
    if formation == FORMATION_JULY:
        return sym.adv
    lo, hi = _ADV_BOUNDS[sym.stratum]
    return round(min(hi * 0.999, max(lo * 1.001, sym.adv * 1.03)), 2)


_RANKS = _ranks()


def _next_day(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _base_row(sym: Symbol, formation: str, query_date: str, run_kind: str,
              sector: str | None, sector_source: str, seq: int) -> dict:
    nd = _next_day(query_date)
    fetched = _ts(nd, 5, 1 + (seq // 60) % 58, seq % 60, et=False)
    return {
        "rule_id": RULE_ID, "formation_date": formation,
        "symbol": sym.symbol, "adv_usd_at_formation": _adv(sym, formation),
        "liquidity_rank": _RANKS[(sym.symbol, formation)],
        "stratum": sym.stratum,
        "median_close_at_formation": sym.median_close,
        "price_floor_at_formation": 10.0, "sector": sector,
        "sector_source": sector_source, "query_date": query_date,
        "state": None, "exclusion_reason": "", "fetched_ts": fetched,
        "model_id": MODEL_ID, "prompt_sha256": PROMPT_SHA,
        "temperature": 0.0, "credential_shared": 0, "etb": sym.etb,
        "shortable": 1, "etb_source": "alpaca_assets", "delay_rolled": 0,
        "outcome_state": "pending", "spec_version": SPEC_VERSION,
        "collector_git_sha": (_SHA_EARLY if query_date < "2026-09-15"
                              else _SHA_LATE),
        "run_kind": run_kind, "written_ts": _ts(nd, 5, 59, 30, et=False),
    }


def _group_slots(n: int, symbols: list[str], frac: float, rng) -> list[list[int]]:
    """Partition headline slots into events; some events span several tickers."""
    flagged = rng.random(n) < frac
    events: list[list[int]] = []
    current: list[int] = []
    target = 0
    for i in (int(x) for x in rng.permutation(n)):
        if not flagged[i]:
            events.append([i])
            continue
        if not current:
            target = int(rng.choice([2, 3, 4], p=[0.6, 0.3, 0.1]))
        if any(symbols[j] == symbols[i] for j in current):
            events.append([i])
            continue
        current.append(i)
        if len(current) == target:
            events.append(current)
            current = []
    if current:
        events.extend([[j] for j in current] if len(current) == 1
                      else [current])
    return events


def _timing(side_same: bool, q: str, q_next: str,
            rng) -> dict:
    """Publication time and anchor, mirroring horizon.resolve_anchor."""
    if side_same:
        hh, mm = 6 + int(rng.integers(3)), int(rng.integers(60))
        return {"published_ts": _ts(q, hh, mm, int(rng.integers(60))),
                "anchor_kind": ANCHOR_OPEN, "anchor_ts": _open_ts(q),
                "same": True, "delay_rolled": 0}
    u = rng.random()
    close_h = 13 if q in _EARLY_CLOSE else 16
    if u < 0.60:
        mins = int(rng.integers(5, (close_h - 9) * 60 - 55))
        hh, mm = 9 + (30 + mins) // 60, (30 + mins) % 60
        return {"published_ts": _ts(q, hh, mm, int(rng.integers(60))),
                "anchor_kind": ANCHOR_CLOSE, "anchor_ts": _close_ts(q),
                "same": False, "delay_rolled": 0}
    if u < 0.95:
        hh, mm = close_h + 1 + int(rng.integers(4)), int(rng.integers(60))
        return {"published_ts": _ts(q, hh, mm, int(rng.integers(60))),
                "anchor_kind": ANCHOR_OPEN, "anchor_ts": _open_ts(q_next),
                "same": False, "delay_rolled": 0}
    mm = 42 + int(rng.integers(17))
    return {"published_ts": _ts(q, close_h - 1, mm, int(rng.integers(60))),
            "anchor_kind": ANCHOR_OPEN, "anchor_ts": _open_ts(q_next),
            "same": False, "delay_rolled": 1}


def _headline_row(base: dict, ev: dict, sidx: int, p: Params, rng) -> dict:
    row = dict(base)
    row.update(headline=f"{base['symbol']} {ev['headline']}",
               source_name=ev["source"], source_article_id=ev["article"])
    if ev["group"] is not None and len(ev["members"]) > 1:
        row["headline"] = ev["headline_shared"]
    u = rng.random()
    if u < 0.012:
        row.update(state=STATE_PRE_CALL, exclusion_reason=PRE_CALL_CLASSES[0],
                   error_class=PRE_CALL_CLASSES[0], outcome_state="excluded",
                   published_ts=None)
        return row
    row["published_ts"] = ev["published_ts"]
    if u < 0.020:
        late = _ts(_next_day(base["query_date"]), 6, 30 + int(rng.integers(29)),
                   et=False)
        row.update(state=STATE_PRE_CALL, exclusion_reason=PRE_CALL_CLASSES[1],
                   error_class=PRE_CALL_CLASSES[1], outcome_state="excluded",
                   published_ts=late)
        return row
    row["story_group_id"] = ev["group"]
    if u < 0.045:
        row.update(state=STATE_PRE_CALL, exclusion_reason=PRE_CALL_CLASSES[2],
                   error_class=PRE_CALL_CLASSES[2], outcome_state="excluded")
        return row
    row.update(anchor_kind=ev["anchor_kind"], anchor_ts=ev["anchor_ts"],
               scoring_session=SESSIONS[sidx], delay_rolled=ev["delay_rolled"],
               called_ts=row["fetched_ts"], _sidx=sidx,
               _story=ev["shock"], _ev=ev["id"])
    exhausted_day = base["query_date"] in EXHAUSTED_DAYS
    if rng.random() < (0.30 if exhausted_day else 0.025):
        cls = (EXHAUSTED if exhausted_day else
               MODEL_FAILED_CLASSES[int(rng.integers(4))])
        unparse = cls == "unparseable"
        row.update(state=STATE_MODEL_FAILED, error_class=cls,
                   raw_response=("I cannot determine" if unparse else
                                 "HTTP 529 overloaded" if cls == "http_status"
                                 else ""),
                   judgment=None, strength=None, strength_parse_ok=0,
                   neutral_strength_anomaly=0, reason="", parse_ok=0,
                   latency_ms=0 if cls == EXHAUSTED else
                   int(rng.integers(300, 30000)),
                   input_tokens=312 if unparse else 0, cached_input_tokens=0,
                   output_tokens=9 if unparse else 0,
                   cost_usd=0.000357 if unparse else 0.0)
        return row
    tin, tout = 300 + int(rng.integers(40)), 28 + int(rng.integers(14))
    row.update(state=STATE_JUDGED, error_class="", parse_ok=1,
               neutral_strength_anomaly=0, latency_ms=int(rng.integers(350, 1900)),
               input_tokens=tin, cached_input_tokens=0, output_tokens=tout,
               cost_usd=round(tin * 1e-6 + tout * 5e-6, 8))
    return row


def _day_rows(q: str, qi: int, sidx: int, p: Params, rng, seq0: int,
              ev_counter: list[int], seed: int) -> list[dict]:
    formation = formation_for(q)
    sf_rate = (p.sf_day_rate if qi == p.sf_day else
               p.bump_rate if qi == p.bump_day else p.sf_rate)
    per_symbol: list[list[dict]] = []
    slot_bases: list[dict] = []
    slot_owner: list[int] = []
    seq = seq0
    for sym in UNIVERSE:
        if formation not in sym.formations:
            continue
        sector, source = _sector_for(sym, formation, q, rng)
        base = _base_row(sym, formation, q, RUN_COLLECTION, sector, source,
                         seq)
        seq += 1
        bucket: list[dict] = []
        per_symbol.append(bucket)
        if rng.random() < sf_rate:
            bucket.append({**base, "state": STATE_SOURCE_FAILED,
                           "error_class": SOURCE_FAILED_CLASS})
            continue
        if rng.random() >= sym.news_rate:
            bucket.append({**base, "state": STATE_NO_NEWS})
            continue
        for _ in range(1 + int(rng.poisson(0.35))):
            slot_bases.append(base)
            slot_owner.append(len(per_symbol) - 1)
    symbols = [b["symbol"] for b in slot_bases]
    events = _group_slots(len(slot_bases), symbols, p.story_frac, rng)
    q_next = SESSIONS[sidx + 1]
    n_same = n_next = 0
    for members in (events[int(i)] for i in rng.permutation(len(events))):
        side_same = n_same <= n_next
        if side_same:
            n_same += len(members)
        else:
            n_next += len(members)
        ev_counter[0] += 1
        eid = ev_counter[0]
        timing = _timing(side_same, q, q_next, rng)
        verb = _VERBS[int(rng.integers(len(_VERBS)))]
        ev = {"id": eid, "members": members, **timing,
              "headline": verb,
              "headline_shared": f"Analysts weigh sector move as peers {verb}",
              "source": _SOURCES[int(rng.integers(len(_SOURCES)))],
              "article": str(130_000_000 + eid),
              "group": "sg_" + hashlib.sha256(
                  f"{seed}|{q}|{eid}".encode()).hexdigest()[:16],
              "shock": (float(rng.normal(0.0, p.story_sd_bp))
                        if len(members) > 1 else 0.0)}
        ev_sidx = sidx if timing["same"] else sidx + 1
        for j in members:
            row = _headline_row(slot_bases[j], ev, ev_sidx, p, rng)
            per_symbol[slot_owner[j]].append(row)
    out: list[dict] = []
    for bucket in per_symbol:
        out.extend(sorted(bucket, key=lambda r: (r.get("published_ts") or "",
                                                 r.get("_ev", 0))))
    return out


def _assign_judgments(rows: list[dict], p: Params, rng) -> None:
    units: dict[int, list[int]] = {}
    for i, r in enumerate(rows):
        if r["state"] == STATE_JUDGED and r["run_kind"] == RUN_COLLECTION:
            units.setdefault(r["_ev"], []).append(i)
    keys = sorted(units)
    n = len(keys)
    n_neu = int(round(n * p.neutral_share))
    n_pos = int(round((n - n_neu) * p.pos_share))
    labels = np.array([NEU] * n_neu + [POS] * n_pos + [NEG] * (n - n_neu - n_pos))
    labels = labels[rng.permutation(n)]
    for k, lab in zip(keys, labels):
        for i in units[k]:
            _set_judgment(rows[i], str(lab), rng)


def _set_judgment(row: dict, lab: str, rng) -> None:
    strength, ok = 1, 1
    if lab != NEU:
        if rng.random() < 0.008:
            strength, ok = None, 0
        else:
            strength = int(rng.choice(5, p=_STRENGTH_P)) + 1
    shown = "null" if strength is None else str(strength)
    row.update(judgment=lab, strength=strength, strength_parse_ok=ok,
               reason=_REASONS[lab],
               raw_response=(f'{{"judgment": "{lab}", "strength": {shown}, '
                             f'"reason": "{_REASONS[lab]}"}}'))


def _sign(row: dict) -> int:
    return {POS: 1, NEG: -1}.get(row.get("judgment") or "", 0)


def _resolve(row: dict, p: Params, draws: dict, last_bar: int, rng) -> None:
    """Fill the outcome columns the way outcomes.resolve_one does."""
    sym = _SYMBOLS[row["symbol"]]
    c = row["_sidx"]
    if rng.random() < p.not_traded_rate:
        row.update(outcome_state="excluded", exclusion_reason=DID_NOT_TRADE,
                   bar_source="")
        return
    j = _sign(row)
    pair = p.pair_bp + (p.sens_pair_bp if sens_excluded_design(
        row["symbol"], row["formation_date"]) else 0.0)
    noise = (SIGMA_BP[sym.stratum] * p.sigma_scale
             * float(rng.standard_t(_T_DF)) / _T_SCALE)
    x_bp = (p.premium_bp + draws["sess"][c] + row["_story"] + noise
            + j * (pair + draws["alt"][c]))
    excess = x_bp / 10_000.0
    bench = float(draws["bench"][c])
    ret1 = bench + excess
    anchor_price = round(sym.median_close * float(np.exp(rng.normal(0, 0.06))),
                         4)
    longer = {}
    for k in (2, 5, 10):
        step = float(rng.normal(0, SIGMA_BP[sym.stratum] * np.sqrt(k - 1)))
        longer[k] = (ret1 + step / 10_000.0) if c + k - 1 <= last_bar else None
    cost = (sym.cost_bp * p.cost_mult[STRATA.index(sym.stratum)]
            * float(np.exp(rng.normal(0, 0.03))))
    row.update(
        outcome_state="resolved", anchor_price=anchor_price,
        ret_intraday=ret1 if row["anchor_kind"] == ANCHOR_OPEN else None,
        ret_1session=ret1, ret_2session=longer[2], ret_5session=longer[5],
        ret_10session=longer[10], bench_1session=bench,
        excess_1session=excess, bar_source="alpaca_iex",
        cost_bp_round_trip=cost,
        net_bp=(j * excess * 10_000.0 - cost) if j else None)


_OUTCOME_COLS = ("anchor_price", "ret_intraday", "ret_1session",
                 "ret_2session", "ret_5session", "ret_10session",
                 "bench_1session", "excess_1session", "bar_source",
                 "cost_bp_round_trip", "net_bp")
_SYMBOLS = {s.symbol: s for s in UNIVERSE}


def _demo_rows(days: tuple[str, ...], first: int, resolved_upto: int, rng,
               seq0: int) -> list[dict]:
    """run_kind 'demonstration' rows every phase must ignore (traps)."""
    q = days[10]
    formation = formation_for(q)
    members = [s for s in UNIVERSE if formation in s.formations]
    out: list[dict] = []
    for i, sym in enumerate(members[:40]):
        out.append({**_base_row(sym, formation, q, RUN_DEMO, sym.sector,
                                SECTOR_SOURCE, seq0 + i),
                    "state": STATE_SOURCE_FAILED,
                    "error_class": SOURCE_FAILED_CLASS})
    for i, sym in enumerate(members[40:60]):
        row = {**_base_row(sym, formation, q, RUN_DEMO, sym.sector,
                           SECTOR_SOURCE, seq0 + 40 + i),
               "state": STATE_JUDGED, "headline": f"{sym.symbol} demo item",
               "source_name": "Finnhub", "error_class": "", "parse_ok": 1,
               "anchor_kind": ANCHOR_OPEN, "delay_rolled": 0,
               "published_ts": _ts(q, 7, 15)}
        _set_judgment(row, POS, rng)
        if i < 12:     # pending, not stale: would hold S* back two sessions
            sess = SESSIONS[resolved_upto - 2]
            row.update(scoring_session=sess, anchor_ts=_open_ts(sess))
        else:          # resolved with a large excess: would move T
            sess = SESSIONS[first + 10]
            row.update(scoring_session=sess, anchor_ts=_open_ts(sess),
                       outcome_state="resolved", bench_1session=0.001,
                       excess_1session=0.05, ret_1session=0.051,
                       cost_bp_round_trip=COST_BP[sym.stratum],
                       net_bp=500.0 - COST_BP[sym.stratum],
                       anchor_price=sym.median_close, bar_source="alpaca_iex")
        out.append(row)
    return out


def _generate(sc: Scenario) -> tuple[list[dict], dict]:
    p = sc.params
    rng = np.random.default_rng(sc.seed)
    first, last_q = p.start, p.start + p.n_days - 1
    days = SESSIONS[first:last_q + 1]
    resolved_upto = last_q - (1 if p.cutoff else 0)
    n_idx = last_q + 2
    draws = {"bench": rng.normal(0.0, 0.009, n_idx),
             "sess": rng.normal(0.0, p.sess_sd_bp, n_idx),
             "alt": np.array([p.alt_signed_bp * (1 if i % 2 == 0 else -1)
                              for i in range(n_idx)])}
    rows: list[dict] = []
    ev_counter = [0]
    for qi, q in enumerate(days):
        rows.extend(_day_rows(q, qi, first + qi, p, rng, len(rows),
                              ev_counter, sc.seed))
    _assign_judgments(rows, p, rng)
    for r in rows:
        if "_sidx" in r and r["_sidx"] <= resolved_upto:
            _resolve(r, p, draws, resolved_upto, rng)
    meta = {"excluded_query_date": days[p.sf_day], "stale_row": None}
    excluded_q = days[p.sf_day]
    if p.cutoff:
        target = resolved_upto - 5
        cands = [i for i, r in enumerate(rows)
                 if r.get("_sidx") == target and _sign(r)
                 and r["outcome_state"] == "resolved"
                 and r["query_date"] != excluded_q]
        pick = cands[int(rng.integers(len(cands)))]
        rows[pick].update({c: None for c in _OUTCOME_COLS},
                          outcome_state="pending")
        meta["stale_row"] = {"symbol": rows[pick]["symbol"],
                             "query_date": rows[pick]["query_date"],
                             "scoring_session": rows[pick]["scoring_session"]}
    lo, hi = first + 3, resolved_upto - 8
    for want, is_dir in ((p.n_null_dir, True), (p.n_null_neu, False)):
        cands = [i for i, r in enumerate(rows)
                 if r["state"] == STATE_JUDGED and r["outcome_state"] == "resolved"
                 and bool(_sign(r)) == is_dir and lo <= r["_sidx"] <= hi
                 and r["query_date"] != excluded_q]
        for i in sorted(int(x) for x in rng.choice(len(cands), want,
                                                   replace=False)):
            rows[cands[i]].update(bench_1session=None, excess_1session=None,
                                  net_bp=None)
    rows.extend(_demo_rows(days, first, resolved_upto, rng, len(rows)))
    meta.update(first_query_date=days[0], last_query_date=days[-1],
                s_star_design=SESSIONS[resolved_upto])
    return rows, meta


# --- database -----------------------------------------------------------------
def _refuse_real(path: Path) -> None:
    real = Path(__file__).resolve().parent.parent / REAL_DB_NAME
    if path.name == REAL_DB_NAME or os.path.realpath(path) == \
            os.path.realpath(real):
        raise PermissionError(f"refusing to write {path}: real database name")


def _prepare_path(path: Path) -> None:
    _refuse_real(path)
    if not path.exists():
        return
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ok = marker.is_synthetic(conn)
    except sqlite3.DatabaseError:
        ok = False
    finally:
        conn.close()
    if not ok:
        raise FileExistsError(f"{path} exists and is not a synthetic database")
    path.unlink()


def build(name: str, path: str | os.PathLike) -> dict:
    """Build scenario `name` at `path` and return its counts (see summarize)."""
    sc = SCENARIOS[name]
    path = Path(path)
    _prepare_path(path)
    rows, meta = _generate(sc)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        cols = [r[1] for r in conn.execute("PRAGMA table_info(news_observation)")
                if r[1] != "id"]
        conn.executemany(
            f"INSERT INTO news_observation ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            [tuple(r.get(c) for c in cols) for r in rows])
        conn.commit()
        marker.write_marker(conn, sc.name, sc.seed)
        summary = summarize(conn)
    finally:
        conn.close()
    summary["design"] = meta
    return summary


def build_all(directory: str | os.PathLike) -> dict:
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in SCENARIOS:
        t0 = time.perf_counter()
        info = build(name, out_dir / f"{name}.db")
        info["build_seconds"] = round(time.perf_counter() - t0, 3)
        result[name] = info
    return result


# --- fixture summary (the generator's own bookkeeping, not the harness) -------
_SUMMARY_COLS = ("symbol", "formation_date", "sector", "sector_source",
                 "query_date", "state", "judgment", "outcome_state",
                 "exclusion_reason", "excess_1session", "net_bp",
                 "scoring_session", "story_group_id", "run_kind")


def _flagged_82(rows: list[dict]) -> set[tuple[str, str]]:
    """D9 on the data: rule (a) by symbol, rule (b) per (symbol, formation)."""
    by_sf: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if r["run_kind"] == RUN_COLLECTION:
            by_sf.setdefault((r["symbol"], r["formation_date"]), []).append(r)
    out = set()
    for key, rs in by_sf.items():
        sym = key[0]
        if "." in sym or sym in ("STRK", "STRF", "STRD", "STRC"):
            out.add(key)
            continue
        sec = _modal([r["sector"] for r in rs if r["sector"] is not None], NA)
        if sec != NA:
            continue
        src = _modal([r["sector_source"] for r in rs if r["sector"] == NA
                      and r["sector_source"] is not None], SECTOR_SOURCE)
        if src == SECTOR_SOURCE:
            out.add(key)
    return out


def _modal(values: list[str], tie_to: str) -> str | None:
    if not values:
        return None
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    top = max(counts.values())
    tied = sorted(k for k, v in counts.items() if v == top)
    return tie_to if tie_to in tied else tied[0]


def summarize(conn: sqlite3.Connection) -> dict:
    """Counts a test can pin, computed from the built rows (D9, D16, D18)."""
    rows = [dict(zip(_SUMMARY_COLS, r)) for r in conn.execute(
        f"SELECT {', '.join(_SUMMARY_COLS)} FROM news_observation ORDER BY id")]
    coll = [r for r in rows if r["run_kind"] == RUN_COLLECTION]
    tally = lambda key, rs: dict(sorted(  # noqa: E731
        _count(r[key] for r in rs).items()))
    day_tot = _count(r["query_date"] for r in coll)
    day_sf = _count(r["query_date"] for r in coll
                    if r["state"] == STATE_SOURCE_FAILED)
    shares = {d: day_sf.get(d, 0) / n for d, n in sorted(day_tot.items())}
    excluded = sorted(d for d, s in shares.items() if s > 0.20)
    judged = [r for r in coll if r["state"] == STATE_JUDGED]
    order = sorted({r["scoring_session"] for r in judged if r["scoring_session"]})
    idx = {s: i for i, s in enumerate(order)}
    resolved = [idx[r["scoring_session"]] for r in judged
                if r["outcome_state"] == "resolved" and r["scoring_session"]]
    latest = max(resolved)
    pend = [idx[r["scoring_session"]] for r in judged
            if r["outcome_state"] == "pending" and r["scoring_session"]]
    stale = sorted(order[i] for i in pend if latest - i > 3)
    live = [i for i in pend if latest - i <= 3]
    s_star = order[min(live) - 1] if live else order[-1]
    flagged = _flagged_82(rows)

    def scorable(r: dict, need_dir: bool) -> bool:
        return (r["state"] == STATE_JUDGED and r["outcome_state"] == "resolved"
                and r["exclusion_reason"] == ""
                and r["excess_1session"] is not None
                and bool(r["scoring_session"])
                and r["query_date"] not in excluded
                and r["scoring_session"] <= s_star
                and (r["judgment"] in (POS, NEG) if need_dir else True))

    analysis = [r for r in coll if scorable(r, True)]
    sens = [r for r in analysis
            if (r["symbol"], r["formation_date"]) not in flagged]
    gate_rows = [r for r in coll if scorable(r, False)]
    groups = _count(r["story_group_id"] for r in analysis if r["story_group_id"])
    shared = sum(1 for r in analysis if groups.get(r["story_group_id"], 0) >= 2)
    null_ex = [r for r in judged if r["outcome_state"] == "resolved"
               and r["excess_1session"] is None]
    return {
        "total_rows": len(rows),
        "collection_rows": len(coll),
        "demonstration_rows": len(rows) - len(coll),
        "by_state": tally("state", coll),
        "by_outcome_state": tally("outcome_state", coll),
        "by_judgment": tally("judgment", judged),
        "query_dates": len(day_tot),
        "formations": sorted({r["formation_date"] for r in coll}),
        "excluded_query_dates": excluded,
        "excluded_day_share": round(max(shares[d] for d in excluded), 4)
        if excluded else None,
        "max_other_day_share": round(max(s for d, s in shares.items()
                                         if d not in excluded), 4),
        "s_star": s_star,
        "stale_pending_sessions": stale,
        "null_excess_resolved_judged": {
            "directional": sum(1 for r in null_ex if r["judgment"] in (POS, NEG)),
            "neutral": sum(1 for r in null_ex if r["judgment"] == NEU)},
        "analysis_scored": len(analysis),
        "analysis_clusters": len({r["scoring_session"] for r in analysis}),
        "analysis_positive": sum(1 for r in analysis if r["judgment"] == POS),
        "analysis_negative": sum(1 for r in analysis if r["judgment"] == NEG),
        "analysis_null_net": sum(1 for r in analysis if r["net_bp"] is None),
        "sensitivity_scored": len(sens),
        "sensitivity_clusters": len({r["scoring_session"] for r in sens}),
        "gate_rows": len(gate_rows),
        "story_shared_share": round(shared / len(analysis), 4)
        if analysis else 0.0,
        "flagged_82": sorted(f"{s}@{f}" for s, f in flagged),
    }


def _count(values) -> dict:
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


# --- scenarios ------------------------------------------------------------------
# Vocabulary: reports/c1_verdict_mapping.md. "statuses" pins P1 to P4 per
# reading, "e_statuses" pins the E-tests where the verdict row depends on them
# or the margin is wide, "rows" lists the verdict rows of that reading (an
# empty list means no Amendment 5 outcome row: an abstention). "gate" is the
# 9.8 gate with its failing conditions among C, M and REQUIRED.
ROW_CLEARS_NONE = "Clears gross, fails net in every stratum"
ROW_CLEARS_SOME = ("Clears gross, net clears in some strata and fails in "
                   "S3/S4")
ROW_CLEARS_ALL = "Clears gross and net"
ROW_AMENDMENT_6 = "Any gross positive, whatever net says (AMENDMENT 6)"
ROW_FAILS_GROSS = "Fails gross"
ROW_UNINFORMATIVE = ("The permutation null is UNINFORMATIVE under the "
                     "Amendment 6 thresholds")
_EXCLUDED_DAY = "2026-08-25"       # days[20] when the first day is 2026-07-28
_S_STAR = "2026-10-26"             # last resolved session at 64 days


def _freeze(obj: Any) -> Any:
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(v) for v in obj)
    return obj


def _all(status: str) -> dict:
    return {k: status for k in ("P1", "P2", "P3", "P4")}


def _reading(gross: str, statuses: dict, rows: list, informative: bool,
             e_statuses: dict | None = None) -> dict:
    return {"gross": gross, "statuses": statuses, "rows": rows,
            "null_informative": informative,
            "e_statuses": e_statuses or {}}


def _expected(gate: tuple[str, list], primary: dict, sensitivity: dict,
              counts: dict, calibration: dict, *, s_star: str = _S_STAR,
              excluded: str = _EXCLUDED_DAY, story: bool = False,
              story_version: dict | None = None, **extra: Any) -> dict:
    out = {"gate": {"status": gate[0], "failing": gate[1]},
           "readings": {"primary": primary, "sensitivity": sensitivity},
           "readings_disagree": (primary["gross"] != sensitivity["gross"]
                                 or primary["rows"] != sensitivity["rows"]),
           "story_trigger": story, "story_version": story_version,
           "s_star": s_star, "excluded_query_dates": [excluded],
           "null_excess_resolved_judged": {"directional": 7, "neutral": 2},
           "counts": counts, "calibration": calibration}
    out.update(extra)
    return out


def _counts(scored: int, pos: int, neg: int, sens: int, clusters: int = 64,
            sens_clusters: int | None = None) -> dict:
    return {"analysis_scored": scored, "analysis_positive": pos,
            "analysis_negative": neg, "analysis_clusters": clusters,
            "sensitivity_scored": sens,
            "sensitivity_clusters": sens_clusters or clusters}


def _s_null() -> Scenario:
    """S-NULL: no skill, 70/30 POSITIVE/NEGATIVE, 64 clusters.

    Planted: excess carries no pairing, no premium; sigma by stratum 110 to
    190 bp (t5 noise) plus a 12 bp session component.
    Expected: every primary `not_clear` in both readings, none with its
    bootstrap bar met; null informative; gross `powered_negative` in both
    readings; row "Fails gross"; gate PASS. E1 to E4 `net_negative` in the
    primary reading.
    Calibration (scratch, not the harness): primary P1 T 1.32 SE 3.08 z 0.43
    upper bound 9.0 bp; P2 z 0.07, P3 z 0.71, P4 z 0.58; sensitivity P1 z 0.84
    upper 11.1; max |z| over both readings 0.84. Minority share 0.298, 64
    mixed clusters. Gate sigma 141.6, rho 0.013, k_eff 39.9, Required 377
    against M 2,470. E1..E4 z -3.76, -4.93, -4.22, -6.19. Seed 35 chosen
    from 31-38 as the one with the widest |z| margin (fixture choice).
    """
    return Scenario("S-NULL", 35, _s_null.__doc__, Params(), _freeze(_expected(
        ("PASS", []),
        _reading("powered_negative", _all("not_clear"), [ROW_FAILS_GROSS],
                 True, {k: "net_negative" for k in ("E1", "E2", "E3", "E4")}),
        _reading("powered_negative", _all("not_clear"), [ROW_FAILS_GROSS],
                 True),
        _counts(2470, 1733, 737, 2076),
        {"P1_T": 1.319, "P1_SE": 3.079, "P1_z": 0.428, "P1_upper": 9.017,
         "max_abs_z": 0.84, "required": 377.4, "minority": 0.2984})))


_EFFECT_COSTS = (1.0, 1.0, 1.35, 1.4)


def _s_effect() -> Scenario:
    """S-EFFECT: a planted +40 bp pairing (POSITIVE +40, NEGATIVE -40), 64 clusters.

    Planted: sigma scaled by 0.75; cost multiplied by 1.35 in S3 and 1.4 in
    S4 (about 42 and 70 bp) so the E-pattern is clear-cut.
    Expected: P1 to P4 `clear` in both readings, null p at its floor
    (2/10,001); gross `clears_gross`; primary E1 `clear`, E2 `clear`, E3
    `abstain_interval`, E4 `net_negative`; rows "Clears gross, net clears in
    some strata and fails in S3/S4" plus the Amendment 6 row (both readings);
    gate PASS.
    Calibration (scratch, not the harness): P1 T 40.10 SE 1.87 z 21.5 p
    0.0002 (null mean 6.7); P2 z 11.4, P3 z 9.3, P4 z 17.0, all p 0.0002.
    E1 T 25.8 z 9.11; E2 T 16.6 z 4.33; E3 T 1.4 z 0.32; E4 T -34.6 z -3.92.
    Sensitivity P1 z 19.0, E1 z 9.65, E2 z 2.93 (not pinned).
    """
    e = {"E1": "clear", "E2": "clear", "E3": "abstain_interval",
         "E4": "net_negative"}
    rows = [ROW_CLEARS_SOME, ROW_AMENDMENT_6]
    return Scenario("S-EFFECT", 20261202, _s_effect.__doc__,
                    Params(pair_bp=40.0, sigma_scale=0.75,
                           cost_mult=_EFFECT_COSTS),
                    _freeze(_expected(
                        ("PASS", []),
                        _reading("clears_gross", _all("clear"), rows, True, e),
                        _reading("clears_gross", _all("clear"), rows, True,
                                 {"E1": "clear", "E3": "abstain_interval",
                                  "E4": "net_negative"}),
                        _counts(2486, 1727, 759, 2087),
                        {"P1_T": 40.096, "P1_SE": 1.868, "P1_z": 21.46,
                         "P1_p": 0.0002, "E_z": [9.113, 4.333, 0.324,
                                                 -3.915]})))


def _s_premium() -> Scenario:
    """S-PREMIUM: no skill, 88/12 skew, +40 bp news-day premium on every news row.

    Planted: excess = +40 bp + noise on every judged (and model_failed) row,
    whatever the judgment. The Amendment 6 case.
    Expected: null informative (minority 0.1176 >= 0.10, 63 mixed >= 30);
    P1 bootstrap bar met, null p large, P1 `blocked_by_null`; P2
    `significant_reversal` (NEGATIVE rows carry the premium against them);
    P3 and P4 `blocked_by_null`; gross `abstention` (a positive intercepted
    by the null); no Amendment 5 row; never a clear. Same in both readings.
    Gate PASS.
    Calibration (scratch, not the harness): P1 T 30.17 SE 3.35 z 9.00, null
    mean 32.7, p 0.161, not upper tail; P2 z -6.40; P3 z 6.29 p 0.909; P4
    z 7.01 p 0.065. Sensitivity P1 z 8.24 p 0.483.
    """
    st = {"P1": "blocked_by_null", "P2": "significant_reversal",
          "P3": "blocked_by_null", "P4": "blocked_by_null"}
    return Scenario("S-PREMIUM", 20261203, _s_premium.__doc__,
                    Params(pos_share=0.88, premium_bp=40.0),
                    _freeze(_expected(
                        ("PASS", []),
                        _reading("abstention", st, [], True),
                        _reading("abstention", st, [], True),
                        _counts(2560, 2259, 301, 2160),
                        {"P1_T": 30.174, "P1_SE": 3.352, "P1_z": 9.001,
                         "P1_p": 0.16058, "P1_null_mean": 32.738,
                         "minority": 0.1176, "mixed": 63},
                        abstention_reason="positive intercepted by the null")))


def _s_unanimous() -> Scenario:
    """S-UNANIMOUS: minority directional share under 10 percent (94/6) plus a +50 bp pairing.

    Expected: null UNINFORMATIVE in both readings (minority 0.0589 primary,
    0.0570 sensitivity); every primary has its bootstrap bar met and reads
    `abstain_null_uninformative`; gross `abstention`; rows: only the
    UNINFORMATIVE row; no clear. Gate PASS.
    Calibration (scratch, not the harness): P1 T 49.37 SE 3.02 z 16.3; P2
    z 4.90 (57 clusters); P3 z 8.75; P4 z 11.75. Mixed clusters 57.
    """
    return Scenario("S-UNANIMOUS", 20261204, _s_unanimous.__doc__,
                    Params(pos_share=0.94, pair_bp=50.0),
                    _freeze(_expected(
                        ("PASS", []),
                        _reading("abstention",
                                 _all("abstain_null_uninformative"),
                                 [ROW_UNINFORMATIVE], False),
                        _reading("abstention",
                                 _all("abstain_null_uninformative"),
                                 [ROW_UNINFORMATIVE], False),
                        _counts(2480, 2334, 146, 2089),
                        {"P1_T": 49.371, "P1_SE": 3.024, "P1_z": 16.324,
                         "P2_z": 4.897, "minority": 0.0589, "mixed": 57},
                        abstention_reason="null uninformative")))


def _s_reversal() -> Scenario:
    """S-REVERSAL: a planted -40 bp pairing (POSITIVE rows fall, NEGATIVE rows rise).

    Expected: P1 to P4 `significant_reversal` in both readings; gross
    `powered_negative` (a reversal does not block it, 9.3); row "Fails
    gross"; never a clear; E1 to E4 `net_negative`. Gate PASS.
    Calibration (scratch, not the harness): P1 T -42.29 SE 2.91 z -14.6,
    upper bound -35.0; P2 z -6.46; P3 z -7.23; P4 z -8.35.
    """
    return Scenario("S-REVERSAL", 20261205, _s_reversal.__doc__,
                    Params(pair_bp=-40.0), _freeze(_expected(
                        ("PASS", []),
                        _reading("powered_negative",
                                 _all("significant_reversal"),
                                 [ROW_FAILS_GROSS], True,
                                 {k: "net_negative"
                                  for k in ("E1", "E2", "E3", "E4")}),
                        _reading("powered_negative",
                                 _all("significant_reversal"),
                                 [ROW_FAILS_GROSS], True),
                        _counts(2457, 1721, 736, 2077),
                        {"P1_T": -42.288, "P1_SE": 2.906, "P1_z": -14.553,
                         "P1_upper": -35.024})))


def _s_highrho() -> Scenario:
    """S-HIGHRHO: a strong common scoring_session component (sd 120 bp) in excess.

    Expected: gate FAIL with only REQUIRED failing (C = 64 >= 60, M = 2,526
    >= 1,000, Required about 6,800 > M). No skill: P1 to P4 `not_clear`,
    gross `powered_negative`, row "Fails gross" in both readings.
    Calibration (scratch, not the harness): gate sigma 182.0, rho 0.393,
    k_eff 40.5, Required 6,797. P1 T -6.60 SE 6.53 z -1.01 upper 9.7; max
    |z| 1.22. Seed 34 chosen from 31-38 for the widest margins.
    """
    return Scenario("S-HIGHRHO", 34, _s_highrho.__doc__,
                    Params(sess_sd_bp=120.0), _freeze(_expected(
                        ("FAIL", ["REQUIRED"]),
                        _reading("powered_negative", _all("not_clear"),
                                 [ROW_FAILS_GROSS], True),
                        _reading("powered_negative", _all("not_clear"),
                                 [ROW_FAILS_GROSS], True),
                        _counts(2526, 1756, 770, 2118),
                        {"sigma": 182.04, "rho": 0.3932, "k_eff": 40.54,
                         "required": 6796.8, "M": 2526, "C": 64,
                         "P1_upper": 9.74})))


def _s_thin() -> Scenario:
    """S-THIN: 45 clusters (collection 2026-09-09 to 2026-11-10).

    Expected: gate FAIL on C only (45 < 60; M 1,719 >= 1,000 and >=
    Required 384); gross `abstention_floor` in both readings; no row. P1 to
    P3 `not_clear` (45 clusters >= 30); P4 `abstain_floor` (22 clusters).
    The excluded collection day is 2026-10-07; S* is 2026-11-10.
    Calibration (scratch, not the harness): P1 z 0.03, P2 z 0.54, P3 z
    0.59, max |z| 0.60. Seed 31 chosen from 31-38 for the widest margins.
    """
    st = {"P1": "not_clear", "P2": "not_clear", "P3": "not_clear",
          "P4": "abstain_floor"}
    return Scenario("S-THIN", 31, _s_thin.__doc__, Params(n_days=45, start=30),
                    _freeze(_expected(
                        ("FAIL", ["C"]),
                        _reading("abstention_floor", st, [], True),
                        _reading("abstention_floor", st, [], True),
                        _counts(1719, 1201, 518, 1442, clusters=45),
                        {"C": 45, "M": 1719, "required": 384.0,
                         "P4_clusters": 22},
                        s_star="2026-11-10", excluded="2026-10-07")))


def _s_story() -> Scenario:
    """S-STORY: shared story groups, +40 bp pairing, S-EFFECT costs.

    Planted: 32 percent of headline slots merged into multi-ticker stories
    (one judgment and a common 70 bp story shock per story).
    Expected: trigger fires (share of scored observations in a story_group_id
    shared by at least 2 scored observations 0.2833 > 0.10). Day-clustered
    version: P1 to P4 `clear` in both readings, gross `clears_gross`, E1 and
    E2 `clear`, E3 `abstain_interval`, E4 `net_negative`, rows "Clears
    gross, net clears in some strata and fails in S3/S4" plus Amendment 6.
    Story-group version (bootstrap on story_group_id, block null): P1 to P4
    `clear` in both readings, so the two versions agree.
    Calibration (scratch, not the harness): day version P1 z 12.8, P2 6.68,
    P3 7.68, P4 11.2; story version P1 SE 2.55 z 13.5 (2,074 clusters), P2
    z 7.19, P3 z 7.75, P4 z 10.8, all p 0.0002. E z 5.33, 3.30, -1.24,
    -4.69.
    """
    e = {"E1": "clear", "E2": "clear", "E3": "abstain_interval",
         "E4": "net_negative"}
    rows = [ROW_CLEARS_SOME, ROW_AMENDMENT_6]
    return Scenario("S-STORY", 20261208, _s_story.__doc__,
                    Params(pair_bp=40.0, story_frac=0.32, story_sd_bp=70.0,
                           sigma_scale=0.75, cost_mult=_EFFECT_COSTS),
                    _freeze(_expected(
                        ("PASS", []),
                        _reading("clears_gross", _all("clear"), rows, True, e),
                        _reading("clears_gross", _all("clear"), rows, True, e),
                        _counts(2485, 1744, 741, 2067),
                        {"story_share": 0.2833, "P1_z": 12.828,
                         "story_P1_SE": 2.553, "story_P1_z": 13.51,
                         "story_P1_clusters": 2074},
                        story=True,
                        story_version={"primary": _all("clear"),
                                       "sensitivity": _all("clear")},
                        story_versions_disagree=False)))


def _s_sens() -> Scenario:
    """S-SENS: the effect lives only in 8.2-excluded rows (+200 bp pairing there).

    The 8.2 rows: rule (a) ARES.PRB, BAC.PRL, BF.A, NEE.PRV, STRK, UHAL.B,
    WFC.PRL; rule (b) BCX, BUI, GDV, HQH in both formations and GLQ in
    2026-07-01 only; SECZ is not excluded. All sit in S1 and S2.
    Expected: primary P1, P2, P4 `clear`, P3 `not_clear`; primary gross
    `clears_gross`, E1 and E2 `clear`, E3 and E4 `net_negative`, rows "Clears
    gross, net clears in some strata and fails in S3/S4" plus Amendment 6.
    Sensitivity: P1 to P4 `not_clear`, gross `powered_negative`, row "Fails
    gross". The readings disagree; both are reported and the primary
    governs.
    Calibration (scratch, not the harness): primary P1 T 32.71 SE 2.97 z
    11.0 p 0.0002; P2 z 4.40; P3 z 0.82; P4 z 9.13; E z 8.24, 5.62, -6.01,
    -3.59. Sensitivity P1 T 0.65 SE 3.21 z 0.20 upper 8.7; max |z| 1.12.
    """
    return Scenario("S-SENS", 20261209, _s_sens.__doc__,
                    Params(sens_pair_bp=200.0), _freeze(_expected(
                        ("PASS", []),
                        _reading("clears_gross",
                                 {"P1": "clear", "P2": "clear",
                                  "P3": "not_clear", "P4": "clear"},
                                 [ROW_CLEARS_SOME, ROW_AMENDMENT_6], True,
                                 {"E1": "clear", "E2": "clear",
                                  "E3": "net_negative", "E4": "net_negative"}),
                        _reading("powered_negative", _all("not_clear"),
                                 [ROW_FAILS_GROSS], True),
                        _counts(2499, 1758, 741, 2094),
                        {"primary_P1_z": 11.026, "sensitivity_P1_z": 0.204,
                         "sensitivity_P1_upper": 8.679})))


def _s_cluster() -> Scenario:
    """S-CLUSTER: a session component in the SIGNED excess, +-80 bp alternating by session.

    Planted: each scoring_session c carries s_c = +80 bp on even session
    indices and -80 bp on odd ones, added to POSITIVE rows' excess and
    subtracted from NEGATIVE rows' (so signed_bp gets +s_c), plus a +16 bp
    pairing. Each query_date splits half and half between its own session
    and the next, so its two halves carry opposite shocks: the
    query_date-clustered SE misses the session variance.
    Expected: harness P1 SE (clustered on scoring_session) matches 10.48
    within Monte Carlo tolerance (5 percent); P1 `not_clear` (z about 1.2),
    though its z on query_date clusters would be 3.89; P1 to P4
    `not_clear`; gross `abstention` (P1's interval includes both zero and
    30 bp); no row. Gate PASS.
    Calibration (scratch, not the harness): P1 T 12.69; SE on
    scoring_session 10.48 (z 1.21, upper 38.9); SE on query_date 3.267 (z
    3.89, 63 clusters); ratio 3.21. P2 z 0.89, P3 z 1.50, P4 z 0.75.
    """
    return Scenario("S-CLUSTER", 20261210, _s_cluster.__doc__,
                    Params(pair_bp=16.0, alt_signed_bp=80.0),
                    _freeze(_expected(
                        ("PASS", []),
                        _reading("abstention", _all("not_clear"), [], True),
                        _reading("abstention", _all("not_clear"), [], True),
                        _counts(2535, 1770, 765, 2153),
                        {"P1_T": 12.693, "P1_SE_scoring_session": 10.48,
                         "P1_SE_query_date": 3.267, "se_ratio": 3.21,
                         "P1_z_scoring_session": 1.211,
                         "P1_z_query_date": 3.885},
                        abstention_reason="interval includes zero and 30 bp",
                        p1_se_tolerance=0.05)))


def _s_cutoff() -> Scenario:
    """S-CUTOFF: pending judged rows in the last 2 sessions plus one stale pending row.

    Planted: 65 collection days to 2026-10-27; every judged row scoring
    2026-10-27 or 2026-10-28 is pending; one judged directional row scoring
    2026-10-19 (5 sessions before the latest resolved session 2026-10-26) is
    pending. Demonstration rows pending at 2026-10-22 must be ignored.
    Expected: S* = 2026-10-26; the stale row (2026-10-19) reported and not
    holding S* back; analysis set 2,532 scored observations in 64 clusters;
    no skill: P1 to P4 `not_clear`, gross `powered_negative`, "Fails gross".
    Calibration (scratch, not the harness): P1 z -0.35 upper 5.4; max |z|
    0.48. Seed 35 chosen from 31-38 for the widest margins.
    """
    return Scenario("S-CUTOFF", 35, _s_cutoff.__doc__,
                    Params(n_days=65, cutoff=True), _freeze(_expected(
                        ("PASS", []),
                        _reading("powered_negative", _all("not_clear"),
                                 [ROW_FAILS_GROSS], True),
                        _reading("powered_negative", _all("not_clear"),
                                 [ROW_FAILS_GROSS], True),
                        _counts(2532, 1780, 752, 2142),
                        {"P1_z": -0.351, "P1_upper": 5.39},
                        stale_pending_sessions=["2026-10-19"],
                        stale_pending_rows=1,
                        pending_judged_sessions=["2026-10-27",
                                                 "2026-10-28"])))


SCENARIOS: dict[str, Scenario] = {sc.name: sc for sc in (
    _s_null(), _s_effect(), _s_premium(), _s_unanimous(), _s_reversal(),
    _s_highrho(), _s_thin(), _s_story(), _s_sens(), _s_cluster(),
    _s_cutoff())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m news_eval.synthetic")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b_all = sub.add_parser("build-all", help="build every scenario")
    b_all.add_argument("--out", required=True)
    b_one = sub.add_parser("build", help="build one scenario")
    b_one.add_argument("name", choices=sorted(SCENARIOS))
    b_one.add_argument("--out", required=True, help="database file path")
    args = ap.parse_args(argv)
    if args.cmd == "build-all":
        result = build_all(args.out)
    else:
        result = {args.name: build(args.name, args.out)}
    json.dump(result, sys.stdout, indent=1, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

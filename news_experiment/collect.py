"""The collector (EXPERIMENT.md stage 2). A standalone script.

  python -m news_experiment.collect --formation 2026-04-01 \
      --from 2026-07-14 --to 2026-07-16 --symbols 12 --ceiling 2.00 \
      --run-kind demonstration --db /tmp/demo.db

IT DOES NOT START COLLECTION BY ITSELF. `--run-kind collection` is refused
unless `--i-have-read-the-preconditions` is also passed, because the tick
multiple is still unmeasured and its result may amend the cost model or the
band. A demonstration run is the default and its rows are labelled
`run_kind='demonstration'` so they can never be counted toward the
pre-registered sample.

THE ORDER OF OPERATIONS IS THE ABSENT-INPUT RULE. For each symbol-day the
source is queried first and its answer decides the state before any model call
is considered:

    query fails           -> source_failed   (absence UNPROVEN)
    query returns []      -> no_news         (absence PROVEN)
    query returns items   -> per headline: judged | model_failed

`no_news` and `source_failed` never merge, and a `no_news` row emits no order,
no signal and no factor value of any kind. There is nothing here that could:
this package has no execution path.

THE FIFTH STATE, AMENDMENT 4. Stage 2 reported that Task 7's four states did
not cover a headline found but excluded BEFORE any model call, and routed those
rows to `model_failed` rather than inventing a state under a binding
specification. The operator has now approved `excluded_pre_call`. The rule is
one question: WAS A REQUEST SENT TO THE PROVIDER?

    no publication timestamp      -> excluded_pre_call / no_publication_time
    published later than fetched  -> excluded_pre_call / clock_inconsistent
    collapsed duplicate           -> excluded_pre_call / duplicate_headline
    calendar cannot reach forward -> excluded_pre_call / calendar_exhausted
    transport / timeout / status / unparseable / exhausted -> model_failed

The two never merge and are never summed. `model_failed` is an OPERATIONAL
HEALTH metric, so a rising rate means go and look at the provider.
`excluded_pre_call` is a SAMPLE COMPOSITION metric, so a rising rate means the
effective sample is smaller than the raw headline count and the power
arithmetic is optimistic. `error_class` remains the cause axis inside each.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone

from llm_consensus.http_json import LLMHTTPError

from . import credentials as expcred
from . import outcomes, spec, store, universe
from .dedup import Deduplicator
from .horizon import Calendar, resolve_anchor, to_iso_z
from .scoring import Scorer, SpendCeiling, SpendCeilingReached

ANALYSIS_DB = "analysis_bars.db"
ALPACA_ASSETS = "https://paper-api.alpaca.markets/v2/assets/"

# Level 1 sizes a position at 2 percent of 100,000 equity. Used ONLY to price
# the per-observation cost hurdle (Task 5). Nothing here sizes an order.
NOTIONAL_FOR_COST = 2000.0


@dataclass
class Injector:
    """Deterministically fails the first N source and model calls.

    Task 3 requires each recorded state to be DEMONSTRATED BY PRODUCING IT.
    `no_news` and `judged` arrive on their own from live data; `source_failed`
    and `model_failed` do not, and waiting for a real outage is not a
    demonstration. These counters drive the REAL collector down its real
    branches, so what is exercised is the production path rather than a test
    double of it. Rows produced this way are `run_kind='demonstration'`.
    """
    source_failures: int = 0
    model_failures: int = 0
    strip_timestamps: int = 0        # -> excluded_pre_call/no_publication_time
    future_timestamps: int = 0       # -> excluded_pre_call/clock_inconsistent
    _src_used: int = field(default=0, init=False)
    _mdl_used: int = field(default=0, init=False)
    _strip_used: int = field(default=0, init=False)
    _future_used: int = field(default=0, init=False)

    def fail_source(self) -> bool:
        if self._src_used < self.source_failures:
            self._src_used += 1
            return True
        return False

    def fail_model(self) -> bool:
        if self._mdl_used < self.model_failures:
            self._mdl_used += 1
            return True
        return False

    def corrupt_article(self, article: dict) -> dict:
        """Damage a real article's timestamp the way a real source sometimes
        does, so the collector's OWN branches classify it.

        Nothing here writes a state. The article is handed back to the same
        code path a healthy article takes, and the classification is the
        production code's, not the injector's. That is the difference between
        demonstrating a state and asserting one.
        """
        if self._strip_used < self.strip_timestamps:
            self._strip_used += 1
            out = dict(article)
            out["datetime"] = 0          # a source that reports only a date
            return out
        if self._future_used < self.future_timestamps:
            self._future_used += 1
            out = dict(article)
            out["datetime"] = int(
                datetime.now(timezone.utc).timestamp()) + 86_400
            return out
        return article


def _get_json(url: str, headers: dict[str, str], timeout: float = 15.0):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        raise LLMHTTPError(f"HTTP {exc.code}", status=exc.code) from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMHTTPError(f"request failed: {exc}") from exc


def fetch_etb(symbol: str, key: str,
              secret: str) -> tuple[int | None, int | None, str]:
    """Easy-to-borrow and shortable AT DECISION TIME.

    Recorded per observation because Stage 1 established this endpoint answers
    for CURRENT classification only. A forward study must record it when the
    decision is made, since it cannot be reconstructed later.
    """
    if not key or not secret:
        return None, None, "no_credential"
    try:
        data = _get_json(ALPACA_ASSETS + symbol,
                         {"APCA-API-KEY-ID": key,
                          "APCA-API-SECRET-KEY": secret})
    except LLMHTTPError:
        return None, None, "unresolved"
    if not isinstance(data, dict):
        return None, None, "unresolved"
    etb = data.get("easy_to_borrow")
    shortable = data.get("shortable")
    return (int(bool(etb)) if etb is not None else None,
            int(bool(shortable)) if shortable is not None else None,
            "alpaca_assets")


def fetch_sector(client, symbol: str) -> tuple[str | None, str]:
    """Sector, recorded for the Task 5 secondary robustness clustering.

    `universe_asset` carries no sector column, so it comes from Finnhub's
    company profile. An unavailable sector is NULL with `sector_source` saying
    so, never a guess: a fabricated sector would silently create a robustness
    check that clusters on nothing.
    """
    try:
        data = client._get("stock/profile2", {"symbol": symbol})
    except Exception:  # noqa: BLE001
        return None, "unresolved"
    if not isinstance(data, dict) or not data:
        return None, "unresolved"
    value = data.get("finnhubIndustry")
    if isinstance(value, str) and value.strip():
        return value.strip(), "finnhub_profile2"
    return None, "absent_in_source"


@dataclass
class RunConfig:
    formation: str
    day_from: str
    day_to: str
    symbols: int
    ceiling: float
    db_path: str
    run_kind: str
    analysis_db: str = ANALYSIS_DB
    inject_source_failures: int = 0
    inject_model_failures: int = 0
    inject_strip_timestamps: int = 0
    inject_future_timestamps: int = 0
    allow_shared_key: bool = False


def demonstration_slice(sample: list, n: int) -> list:
    """A bounded, reproducible slice that keeps every stratum represented.

    Round-robin across strata rather than the first n of the ordered sample,
    which would be all S1 and would demonstrate one stratum four times. This
    does NOT re-draw: it reorders the symbols the seed already chose, so the
    slice is a subset of the seeded sample and stays reproducible.
    """
    by_stratum: dict[str, list] = {}
    for m in sample:
        by_stratum.setdefault(m.stratum, []).append(m)
    out: list = []
    idx = 0
    while len(out) < n and any(len(v) > idx for v in by_stratum.values()):
        for name, _lo, _hi in spec.STRATA:
            pool = by_stratum.get(name, [])
            if idx < len(pool) and len(out) < n:
                out.append(pool[idx])
        idx += 1
    return out


def _base_row(member, cfg: RunConfig, query_date: str, sha: str,
              shared: int) -> dict:
    return {
        "rule_id": spec.RULE_ID,
        "formation_date": cfg.formation,
        "symbol": member.symbol,
        "adv_usd_at_formation": member.adv_usd,
        "liquidity_rank": member.liquidity_rank,
        "stratum": member.stratum,
        "median_close_at_formation": member.median_close,
        "price_floor_at_formation": spec.MIN_MEDIAN_CLOSE,
        "query_date": query_date,
        "model_id": spec.MODEL_ID,
        "prompt_sha256": spec.prompt_sha256(),
        "temperature": float(spec.TEMPERATURE),
        "credential_shared": shared,
        "spec_version": spec.SPEC_VERSION,
        "collector_git_sha": sha,
        "run_kind": cfg.run_kind,
        "exclusion_reason": spec.EXCLUSION_NONE,
        "outcome_state": "pending",
    }


def run(cfg: RunConfig, *, finnhub_client=None, scorer=None,
        injector: Injector | None = None) -> dict:
    """Execute one collector run and return its report."""
    injector = injector or Injector(cfg.inject_source_failures,
                                    cfg.inject_model_failures,
                                    cfg.inject_strip_timestamps,
                                    cfg.inject_future_timestamps)

    key = expcred.resolve_experiment_key(allow_shared=cfg.allow_shared_key)
    print(f"[credential] {key.describe()}")
    separate = expcred.latch_is_separate()
    print(f"[latch] experiment label '{expcred.EXPERIMENT_PROVIDER_LABEL}' is "
          f"{'SEPARATE from' if separate else 'NOT separate from'} the "
          f"council's '{expcred.COUNCIL_PROVIDER_LABEL}'")
    if not key.ok:
        raise SystemExit(2)
    if not separate:
        raise SystemExit("latch separation failed, refusing to run")

    ceiling = SpendCeiling(limit_usd=cfg.ceiling)
    print(f"[ceiling] hard limit {cfg.ceiling:.2f} USD, enforced before the "
          f"first call")

    if finnhub_client is None:
        from discovery.finnhub_source import FinnhubClient
        finnhub_client = FinnhubClient()
    if scorer is None:
        scorer = Scorer(key=key.key or "", label=key.label, ceiling=ceiling)

    sessions = universe.load_sessions(cfg.analysis_db)
    # closing(), never a bare `with` around the connect call: that form is
    # transaction scope and leaks the handle (test_keystore_fd_leak).
    with closing(sqlite3.connect(f"file:{cfg.analysis_db}?mode=ro",
                                 uri=True)) as aconn:
        cal = Calendar.from_rows(list(aconn.execute(
            "SELECT date, open, close FROM trading_calendar")))

    print(f"[universe] resolving band at formation {cfg.formation}")
    members, rejects = universe.resolve_band(cfg.analysis_db, cfg.formation,
                                             sessions=sessions)
    sample = universe.stratified_sample(members, rule_id=spec.RULE_ID,
                                        formation_date=cfg.formation)
    print(f"[universe] band {len(members)} members, seeded sample "
          f"{len(sample)}, rejections {rejects}")
    if cfg.symbols and cfg.symbols < len(sample):
        sample = demonstration_slice(sample, cfg.symbols)
        print(f"[universe] demonstration slice {len(sample)} symbols, strata "
              f"{sorted({m.stratum for m in sample})}")

    band_symbols = [m.symbol for m in members]
    sha = store.collector_git_sha()
    shared = 1 if key.shared else 0
    conn = store.open_store(cfg.db_path)

    days = [d for d in sessions if cfg.day_from <= d <= cfg.day_to]
    print(f"[window] {len(days)} sessions in {cfg.day_from}..{cfg.day_to}")

    etb_cache: dict[str, tuple] = {}
    sector_cache: dict[str, tuple] = {}
    alp_key = alp_secret = ""
    try:
        from account_manager import credentials as _ac
        alp_key = _ac.get_credential("alpaca_paper_key") or ""
        alp_secret = _ac.get_credential("alpaca_paper_secret") or ""
    except Exception:  # noqa: BLE001
        pass

    written = 0
    ceiling_hit = False
    for day in days:
        dedup = Deduplicator()
        for member in sample:
            sym = member.symbol
            row = _base_row(member, cfg, day, sha, shared)
            if sym not in etb_cache:
                etb_cache[sym] = fetch_etb(sym, alp_key, alp_secret)
            row["etb"], row["shortable"], row["etb_source"] = etb_cache[sym]
            if sym not in sector_cache:
                sector_cache[sym] = fetch_sector(finnhub_client, sym)
            row["sector"], row["sector_source"] = sector_cache[sym]

            if injector.fail_source():
                row["state"] = spec.STATE_SOURCE_FAILED
                row["error_class"] = "source_unreachable"
                store.insert_observation(conn, row)
                written += 1
                continue

            items = finnhub_client.company_news(sym, day, day)
            row["fetched_ts"] = store.now_iso()
            if items is None:
                # ABSENCE UNPROVEN. The source was not reachable, so nothing is
                # known about this symbol-day. Never a quiet news day.
                row["state"] = spec.STATE_SOURCE_FAILED
                row["error_class"] = "source_unreachable"
                store.insert_observation(conn, row)
                written += 1
                continue
            if not items:
                # ABSENCE PROVEN. The source answered and had nothing.
                row["state"] = spec.STATE_NO_NEWS
                store.insert_observation(conn, row)
                written += 1
                continue

            ordered = sorted([a for a in items if isinstance(a, dict)],
                             key=lambda a: a.get("datetime") or 0)
            for article in ordered:
                article = injector.corrupt_article(article)
                hrow = dict(row)
                headline = str(article.get("headline") or "").strip()
                hrow["headline"] = headline
                hrow["source_name"] = str(article.get("source") or "finnhub")
                hrow["source_article_id"] = str(article.get("id") or "")

                epoch = article.get("datetime")
                if not epoch:
                    # Recorded and excluded. NOT assumed to have arrived at
                    # midnight, at the open, or at any other hour. No call was
                    # attempted, so this is sample composition and not provider
                    # health (AMENDMENT 4).
                    hrow["state"] = spec.STATE_EXCLUDED_PRE_CALL
                    hrow["exclusion_reason"] = spec.EXCLUSION_NO_PUBLICATION_TIME
                    hrow["error_class"] = "no_publication_time"
                    hrow["outcome_state"] = "excluded"
                    store.insert_observation(conn, hrow)
                    written += 1
                    continue

                published = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
                hrow["published_ts"] = to_iso_z(published)
                if hrow["published_ts"] > (hrow["fetched_ts"] or ""):
                    # The source reported a publication later than the fetch, so
                    # nothing is known about when this headline arrived. No call
                    # attempted (AMENDMENT 4).
                    hrow["state"] = spec.STATE_EXCLUDED_PRE_CALL
                    hrow["exclusion_reason"] = spec.EXCLUSION_CLOCK_INCONSISTENT
                    hrow["error_class"] = "clock_inconsistent"
                    hrow["outcome_state"] = "excluded"
                    store.insert_observation(conn, hrow)
                    written += 1
                    continue

                is_dup, group = dedup.consider(
                    ticker=sym, headline=headline,
                    article_id=hrow["source_article_id"], published=published)
                hrow["story_group_id"] = group
                if is_dup:
                    # A PRE-CALL EXCLUSION. Stage 2's first run recorded these
                    # as `judged` with a NULL judgment, which reads as "the
                    # model returned a verdict" when no call was made; that was
                    # fixed to `model_failed`, and AMENDMENT 4 moves it again to
                    # the state that actually describes it. A collapsed
                    # duplicate is not a provider failure, it is the source
                    # serving the same story twice, which is a fact about the
                    # SAMPLE. `error_class` keeps the three pre-call causes
                    # distinguishable.
                    hrow["state"] = spec.STATE_EXCLUDED_PRE_CALL
                    hrow["exclusion_reason"] = spec.EXCLUSION_DUPLICATE_HEADLINE
                    hrow["error_class"] = "duplicate_headline"
                    hrow["outcome_state"] = "excluded"
                    store.insert_observation(conn, hrow)
                    written += 1
                    continue

                anchor = resolve_anchor(published, cal)
                hrow["anchor_kind"] = anchor.anchor_kind
                hrow["anchor_ts"] = anchor.anchor_ts
                hrow["scoring_session"] = anchor.scoring_session
                hrow["delay_rolled"] = 1 if anchor.delay_rolled else 0
                if anchor.reason:
                    # THE CALENDAR COULD NOT ANSWER, SO THE COLLECTOR REFUSES
                    # RATHER THAN ASSUMES. No call is attempted, because a
                    # verdict whose scoring window cannot be located is worth
                    # nothing and would still cost money. The row is
                    # excluded_pre_call with its own error_class, never a
                    # guessed date, and never `symbol_did_not_trade`: the
                    # calendar's ignorance is not the symbol's silence.
                    hrow["state"] = spec.STATE_EXCLUDED_PRE_CALL
                    hrow["exclusion_reason"] = anchor.reason
                    hrow["error_class"] = anchor.reason
                    hrow["outcome_state"] = "excluded"
                    store.insert_observation(conn, hrow)
                    written += 1
                    continue

                if injector.fail_model():
                    hrow["state"] = spec.STATE_MODEL_FAILED
                    hrow["error_class"] = "transport"
                    hrow["raw_response"] = "injected transport failure"
                    hrow["called_ts"] = store.now_iso()
                    store.insert_observation(conn, hrow)
                    written += 1
                    continue

                try:
                    result = scorer.score(sym, headline)
                except SpendCeilingReached as exc:
                    print(f"[ceiling] STOPPING: {exc}")
                    ceiling_hit = True
                    break
                hrow["called_ts"] = store.now_iso()
                hrow["state"] = result.state
                hrow["raw_response"] = result.raw_response
                hrow["judgment"] = result.judgment
                hrow["strength"] = result.strength
                hrow["strength_parse_ok"] = int(result.strength_parse_ok)
                hrow["neutral_strength_anomaly"] = int(
                    result.neutral_strength_anomaly)
                hrow["reason"] = result.reason
                hrow["parse_ok"] = int(result.parse_ok)
                hrow["error_class"] = result.error_class
                hrow["latency_ms"] = result.latency_ms
                hrow["input_tokens"] = result.input_tokens
                hrow["cached_input_tokens"] = result.cached_input_tokens
                hrow["output_tokens"] = result.output_tokens
                hrow["cost_usd"] = result.cost_usd
                store.insert_observation(conn, hrow)
                written += 1
            if ceiling_hit:
                break
        conn.commit()
        if ceiling_hit:
            break
    conn.commit()

    resolved = resolve_pending(conn, cfg, cal, band_symbols)
    conn.commit()
    horizons = backfill_horizons(conn, cfg, cal)
    conn.commit()

    report = {
        "rows_written": written,
        "outcomes_resolved": resolved,
        "horizons_backfilled": horizons,
        "band_members": len(members),
        "seeded_sample_size": spec.SAMPLE_TOTAL,
        "symbols_run": len(sample),
        "rejections": rejects,
        "spend_usd": round(ceiling.spent_usd, 6),
        "calls": ceiling.calls,
        "ceiling_usd": cfg.ceiling,
        "ceiling_hit": ceiling_hit,
        "cost_per_call": round(ceiling.spent_usd / ceiling.calls, 8)
                         if ceiling.calls else None,
        "projected_cost_per_call": spec.PROJECTED_COST_PER_CALL,
        "coverage": store.coverage_summary(conn),
        "strength": store.strength_distribution(conn),
        "credential_shared": bool(shared),
        "latch_separate": separate,
    }
    conn.close()
    return report


def band_resolver(cfg: RunConfig, cal: Calendar,
                  seed: dict[str, list[str]] | None = None):
    """A cached formation-date to band-membership lookup.

    THE BENCHMARK BELONGS TO THE ROW'S OWN FORMATION, NOT TO THE RUNNING
    QUARTER. Task 5 defines the benchmark as the equal-weighted mean of every
    eligible ADV-band member that traded the window, and Task 2 fixes band
    membership at the formation date. The resolver previously benchmarked
    every pending row against the CURRENT run's band, which is identical
    inside one quarter and silently wrong across a boundary: on 2026-10-01 a
    row still pending from the July formation would have been priced against
    the October universe. The row's own `formation_date` is recorded on every
    row precisely so this question has an answer.

    Returns None for a formation whose band cannot be resolved, which leaves
    those rows PENDING and reported rather than priced against a substitute.
    """
    cache: dict[str, list[str] | None] = {k: list(v) for k, v in
                                          (seed or {}).items() if v}
    sessions = list(cal.sessions)

    def get(formation: str) -> list[str] | None:
        if formation not in cache:
            try:
                members, _rej = universe.resolve_band(
                    cfg.analysis_db, formation, sessions=sessions)
            except Exception as exc:  # noqa: BLE001
                # ANY failure to resolve a band leaves those rows pending.
                # The alternative, letting it propagate, would abandon the
                # whole resolve pass over one bad formation, and the
                # alternative to THAT, substituting another band, is the
                # defect this function exists to remove.
                print(f"[resolve] band UNRESOLVABLE at formation "
                      f"{formation}: {type(exc).__name__}: {exc}. "
                      f"Its rows stay pending.")
                cache[formation] = None
            else:
                cache[formation] = [m.symbol for m in members]
                print(f"[resolve] formation {formation} band "
                      f"{len(cache[formation] or [])} members")
        return cache[formation]

    return get


def needed_days(rows: list, *, anchor_idx: int, scoring_idx: int) -> set[str]:
    """Every session date the rows depend on, anchors included.

    A row's earliest bar is its anchor session, so the load span must be
    derived from it rather than from an offset off the scoring session.
    """
    days = {(r[anchor_idx] or "")[:10] for r in rows}
    days |= {r[scoring_idx] or "" for r in rows}
    days.discard("")
    return days


RESOLVE_UPDATE_SQL = (
    "UPDATE news_observation SET outcome_state=?, anchor_price=?, "
    "ret_intraday=?, ret_1session=?, ret_2session=?, ret_5session=?, "
    "ret_10session=?, bench_1session=?, excess_1session=?, "
    "bar_source=?, cost_bp_round_trip=?, net_bp=?, "
    "exclusion_reason=CASE WHEN ?='' THEN exclusion_reason ELSE ? END "
    "WHERE id=?")


def resolve_pending(conn, cfg: RunConfig, cal: Calendar,
                    band_symbols: list[str], band_for=None) -> int:
    """Fill outcomes for rows whose scoring session has closed.

    Each row is benchmarked against the band of ITS OWN formation date. The
    running band is passed in only as a cache seed, so the common case (every
    pending row belongs to the current quarter) costs no extra resolution.
    `band_for` is injectable so a test can supply a band without standing up
    a full universe, and so the pre-fix behaviour can be mutated back in.
    """
    rows = conn.execute(
        "SELECT id, symbol, judgment, anchor_kind, anchor_ts, scoring_session, "
        "adv_usd_at_formation, formation_date FROM news_observation "
        "WHERE outcome_state='pending' AND scoring_session IS NOT NULL "
        "AND scoring_session != ''").fetchall()
    if not rows:
        return 0
    if band_for is None:
        seed = ({cfg.formation: list(band_symbols)}
                if cfg.formation and band_symbols else {})
        band_for = band_resolver(cfg, cal, seed)

    sessions = sorted({r[5] for r in rows})
    symbols = {r[1] for r in rows}
    for formation in sorted({r[7] for r in rows}):
        members = band_for(formation)
        if members:
            symbols |= set(members)
    # The span starts at the earliest bar any row actually needs, which is its
    # ANCHOR session, not two sessions before its scoring session. The old
    # form guessed the anchor's position and lost it whenever the arithmetic
    # ran off the front of the calendar, and a lost anchor bar reads as
    # `symbol_did_not_trade`, the same wrong reason this session is repairing.
    start = min(needed_days(rows, anchor_idx=4, scoring_idx=5))
    end = cal.session_ahead(sessions[-1], 12) or cal.sessions[-1]
    book = outcomes.PriceBook.load(cfg.analysis_db, symbols, start, end)

    n = 0
    for rid, sym, judgment, kind, anchor_ts, scoring, adv, formation in rows:
        members = band_for(formation)
        if members is None:
            continue
        out = outcomes.resolve_one(
            symbol=sym, judgment=judgment, anchor_kind=kind or "",
            anchor_session=(anchor_ts or "")[:10],
            scoring_session=scoring or "",
            adv_usd=(float(adv) if adv is not None else None),
            notional=NOTIONAL_FOR_COST, book=book, cal=cal,
            band_members=members)
        if out.outcome_state == "pending":
            continue
        conn.execute(
            RESOLVE_UPDATE_SQL,
            (out.outcome_state, out.anchor_price, out.ret_intraday,
             out.ret_1session, out.ret_2session, out.ret_5session,
             out.ret_10session, out.bench_1session, out.excess_1session,
             out.bar_source, out.cost_bp_round_trip, out.net_bp,
             out.exclusion_reason, out.exclusion_reason, rid))
        n += 1
    return n


# THE IMMUTABILITY GUARD, AND IT IS STRUCTURAL RATHER THAN A CONVENTION.
#
# 1. The statement NAMES ONLY the three unscored companion horizons.
#    `ret_1session`, `excess_1session`, `bench_1session`, `net_bp`,
#    `cost_bp_round_trip`, `anchor_price`, `judgment`, `strength`,
#    `outcome_state` and `bar_source` are absent, so no execution of this
#    statement can write them whatever the caller computed.
# 2. Every assignment is COALESCE(existing, new), so an already-filled value
#    WINS over anything recomputed. A later pull on a different adjustment
#    baseline therefore cannot silently move a number that has been reported.
# 3. The caller's WHERE clause requires `outcome_state='resolved'`, so the
#    pass cannot touch a pending or excluded row.
#
# Guarded by `tests/test_outcome_backfill.py`, which asserts every column
# except the three is byte-identical across a pass, and by a mutation test
# that adds `ret_1session` here and verifies that assertion fails.
HORIZON_UPDATE_SQL = (
    "UPDATE news_observation SET "
    "ret_2session = COALESCE(ret_2session, ?), "
    "ret_5session = COALESCE(ret_5session, ?), "
    "ret_10session = COALESCE(ret_10session, ?) "
    "WHERE id=?")


def backfill_horizons(conn, cfg: RunConfig, cal: Calendar) -> dict:
    """Fill the unscored follow-up horizons whose bars have since arrived.

    A row resolves once, at T+1, when its 2, 5 and 10-session returns do not
    exist yet, so those columns stayed NULL forever and Task 8's recorded
    reason for carrying them was being lost on every row collected. This pass
    fills each one when, and only when, its bar appears. It never re-touches
    the scored horizon: see HORIZON_UPDATE_SQL above.
    """
    cols = ", ".join(f"ret_{k}session" for k in outcomes.COMPANION_HORIZONS)
    nulls = " OR ".join(f"ret_{k}session IS NULL"
                        for k in outcomes.COMPANION_HORIZONS)
    rows = conn.execute(
        f"SELECT id, symbol, anchor_kind, anchor_ts, scoring_session, {cols} "
        f"FROM news_observation WHERE outcome_state='resolved' "
        f"AND scoring_session IS NOT NULL AND scoring_session != '' "
        f"AND ({nulls})").fetchall()
    filled = {k: 0 for k in outcomes.COMPANION_HORIZONS}
    report = {"rows_examined": len(rows), "rows_updated": 0,
              "filled": filled, "rows_still_incomplete": 0}
    if not rows:
        return report

    sessions = sorted({r[4] for r in rows})
    try:
        start = min(needed_days(rows, anchor_idx=3, scoring_idx=4))
        end = cal.session_ahead(sessions[-1], max(
            outcomes.COMPANION_HORIZONS) + 2) or cal.sessions[-1]
    except ValueError:
        # A scoring session outside the loaded calendar. Reported by leaving
        # every such row untouched rather than guessing a span.
        print("[horizons] a scoring session is outside the calendar, "
              "skipping the pass")
        return report
    book = outcomes.PriceBook.load(cfg.analysis_db, {r[1] for r in rows},
                                   start, end)

    for rid, sym, kind, anchor_ts, scoring, *have in rows:
        present = dict(zip(outcomes.COMPANION_HORIZONS, have))
        values = outcomes.companion_horizons(
            symbol=sym, anchor_kind=kind or "",
            anchor_session=(anchor_ts or "")[:10], scoring_session=scoring,
            book=book, cal=cal)
        new = {k: v for k, v in values.items()
               if present[k] is None and v is not None}
        if any(present[k] is None and values[k] is None
               for k in outcomes.COMPANION_HORIZONS):
            report["rows_still_incomplete"] += 1
        if not new:
            continue
        conn.execute(HORIZON_UPDATE_SQL,
                     (*(new.get(k) for k in outcomes.COMPANION_HORIZONS), rid))
        report["rows_updated"] += 1
        for k in new:
            filled[k] += 1
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stage 2 news-drift collector")
    p.add_argument("--formation", required=True)
    p.add_argument("--from", dest="day_from", required=True)
    p.add_argument("--to", dest="day_to", required=True)
    p.add_argument("--symbols", type=int, default=0)
    p.add_argument("--ceiling", type=float, required=True)
    p.add_argument("--db", default=store.DEFAULT_DB)
    p.add_argument("--analysis-db", default=ANALYSIS_DB)
    p.add_argument("--run-kind", choices=("demonstration", "collection"),
                   default="demonstration")
    p.add_argument("--inject-source-failures", type=int, default=0)
    p.add_argument("--inject-model-failures", type=int, default=0)
    p.add_argument("--inject-strip-timestamps", type=int, default=0)
    p.add_argument("--inject-future-timestamps", type=int, default=0)
    p.add_argument("--allow-shared-key", action="store_true")
    p.add_argument("--i-have-read-the-preconditions", action="store_true")
    args = p.parse_args(argv)

    if args.run_kind == "collection" and not args.i_have_read_the_preconditions:
        print("REFUSING: collection has not been cleared to start. The tick "
              "multiple is unmeasured and its result may amend the cost model "
              "or the band (EXPERIMENT.md, Stage 1 verdict). Use --run-kind "
              "demonstration, or pass --i-have-read-the-preconditions once the "
              "operator has cleared it.", file=sys.stderr)
        return 3

    cfg = RunConfig(formation=args.formation, day_from=args.day_from,
                    day_to=args.day_to, symbols=args.symbols,
                    ceiling=args.ceiling, db_path=args.db,
                    run_kind=args.run_kind, analysis_db=args.analysis_db,
                    inject_source_failures=args.inject_source_failures,
                    inject_model_failures=args.inject_model_failures,
                    inject_strip_timestamps=args.inject_strip_timestamps,
                    inject_future_timestamps=args.inject_future_timestamps,
                    allow_shared_key=args.allow_shared_key)
    print(json.dumps(run(cfg), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

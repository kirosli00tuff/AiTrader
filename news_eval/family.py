"""The analysis set, the Amendment 6 diagnostics and every test's numbers (STAGE C.1 Task 4).

compute(db_path) reads the database through the guarded loader (the VERDICT
phase for rows, the GATE phase's count methods for the 9.1 day rule and the
9.7 cutoff, so S* is the one news_eval.gate uses) and returns one
JSON-serialisable dict. news_eval.verdict maps it to statuses and rows.

Spec, in order of authority: EXPERIMENT.md (Task 5, Amendment 5, Amendment 6,
8.2, 9.1 to 9.12), then reports/c1_verdict_mapping.md (D1, D2, D9 to D20,
D25, D26).

Mutation seams (Task 7 monkeypatches these; each is looked up at call time):
    CLUSTER_COLUMN          the 9.1 cluster column, read by cluster_of
    K.<NAME>                every bar, floor, threshold, count and seed is read
                            through the constants module at call time
    signed_values           the 9.4 sign convention
    direction_labels        the +1/-1 labels the permutation null shuffles
    scorable_filter         the 9.7 scorable conditions (pending vs resolved)
    cutoff_s_star           the 9.7 cutoff S*
    day_exclusion           the 9.1 day rule
    build_sensitivity_set   the 8.2 sensitivity set
    estimate_t              the 9.4/9.5 T estimator with its bootstrap
    permutation_strata      the Amendment 6 / 9.9 strata

compute() never reads ret_2session, ret_5session or ret_10session. Those are
read only by companion_horizons (9.12, D26), which compute() never calls.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, fields
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from news_eval import constants as K
from news_eval import cutoff
from news_eval import data
from news_eval import envcheck
from news_eval import stats
from news_eval import verdict

# 9.1: the cluster unit for the bootstrap, the permutation strata and every
# cluster count. Read at call time (mutation seam).
CLUSTER_COLUMN = "scoring_session"

READING_PRIMARY = "primary"
READING_SENSITIVITY = "sensitivity"
STORY_READING = {READING_PRIMARY: "primary_story",
                 READING_SENSITIVITY: "sensitivity_story"}
# N7 ruling: the story trigger's reason when the scored set is empty.
STORY_EMPTY_POOL_REASON = "empty pool: no scored observations, so no share"

# Columns compute() reads from judged collection rows (VERDICT phase).
ANALYSIS_COLUMNS = (
    "id", "symbol", "formation_date", "stratum", "sector", "query_date",
    "state", "run_kind", "exclusion_reason", "story_group_id", "judgment",
    "strength", "strength_parse_ok", "outcome_state", "scoring_session",
    "excess_1session", "net_bp")
# Columns compute() reads from every collection row, any state (8.2 rule b).
SECTOR_COLUMNS = ("id", "symbol", "formation_date", "sector",
                  "sector_source", "run_kind")
# 9.12 / D26 companion horizons: (k, column). Read only by companion_horizons.
COMPANION_HORIZONS = ((2, "ret_2session"), (5, "ret_5session"),
                      (10, "ret_10session"))

# scorable_filter drop reasons, in the order they are tested (the funnel).
DROP_RUN_KIND = "run_kind_not_collection"
DROP_STATE = "state_not_judged"
DROP_PENDING = "outcome_pending"
DROP_OUTCOME_OTHER = "outcome_not_resolved_other"
DROP_EXCLUSION = "exclusion_reason_set"
DROP_SESSION_EMPTY = "scoring_session_empty"
DROP_DAY_RULE = "day_rule"
DROP_BEYOND_S_STAR = "beyond_s_star"
DROP_EXCESS_NULL = "excess_1session_null"
DROP_ORDER = (DROP_RUN_KIND, DROP_STATE, DROP_PENDING, DROP_OUTCOME_OTHER,
              DROP_EXCLUSION, DROP_SESSION_EMPTY, DROP_DAY_RULE,
              DROP_BEYOND_S_STAR, DROP_EXCESS_NULL)

PRIMARY_SUBSETS = {"P1": "pooled", "P2": "NEGATIVE-only",
                   "P3": "thin-end S3 and S4", "P4": "chronological second half"}
STRENGTH_BUCKETS = (1, 2, 3, 4, 5)
DESCRIPTIVE = "descriptive"


# ------------------------------------------------------------- inputs

@dataclass(frozen=True)
class Inputs:
    """Everything compute() reads (9.7, 9.8 counts, 8.2).

    state_counts: GATE state_counts_by_query_date (9.1 day rule, D18).
    session_status: GATE judged_session_status (9.7 S*, D16).
    judged: judged collection rows, ANALYSIS_COLUMNS, ordered by id.
    collection: every collection row, SECTOR_COLUMNS, ordered by id.
    """
    state_counts: Mapping[str, Mapping[str, int]]
    session_status: Mapping[Any, Mapping[str, int]]
    judged: tuple[dict, ...]
    collection: tuple[dict, ...]


def _phase_kwargs(real_db_path, unlock_path, marker_path) -> dict:
    return {"real_db_path": real_db_path, "unlock_path": unlock_path,
            "run_once_path": marker_path}


def _analysis_columns() -> tuple[str, ...]:
    cols = ANALYSIS_COLUMNS
    return cols if CLUSTER_COLUMN in cols else cols + (CLUSTER_COLUMN,)


def load_inputs(db_path, *, real_db_path=None, unlock_path=None,
                marker_path=None) -> Inputs:
    """9.7, 9.15: read the analysis inputs through the guarded loader.

    The VERDICT phase is opened first, so on a non-synthetic database the
    unlock file and the run-once marker are checked before any count or row
    is read; the GATE phase's count methods then give the day-rule and S*
    counts exactly as news_eval.gate reads them."""
    kw = _phase_kwargs(real_db_path, unlock_path, marker_path)
    collection_filter = (("run_kind", "=", K.RUN_KIND_COLLECTION),)
    with data.open_phase("VERDICT", db_path, **kw) as phase:
        judged = phase.select(
            _analysis_columns(),
            collection_filter + (("state", "=", K.STATE_JUDGED),))
        collection = phase.select(SECTOR_COLUMNS, collection_filter)
        with data.open_phase("GATE", db_path, **kw) as gate:
            state_counts = gate.state_counts_by_query_date()
            session_status = gate.judged_session_status()
    return Inputs(state_counts=state_counts, session_status=session_status,
                  judged=tuple(judged.as_dicts()),
                  collection=tuple(collection.as_dicts()))


# ------------------------------------------------------------- seams

def cluster_of(row: Mapping[str, Any]) -> Any:
    """9.1: a row's cluster label, from CLUSTER_COLUMN at call time."""
    return row[CLUSTER_COLUMN]


def bootstrap_clusters(rows: Sequence[Mapping[str, Any]]) -> list:
    """9.1, 9.5: the day-cluster label of each row."""
    return [cluster_of(r) for r in rows]


def permutation_strata(rows: Sequence[Mapping[str, Any]]) -> list:
    """9.9, Amendment 6: the strata the judgment labels are shuffled within
    (each row's scoring_session cluster)."""
    return [cluster_of(r) for r in rows]


def story_clusters(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """9.10, D11: bootstrap clusters for the story-group version: the row's
    non-empty story_group_id, across sessions; an unshared row is its own
    cluster. Prefixes keep the two label kinds from colliding."""
    return [f"g:{r['story_group_id']}" if r["story_group_id"]
            else f"r:{r['id']}" for r in rows]


def story_groups(rows: Sequence[Mapping[str, Any]]) -> list:
    """9.10, D11, D12: story_group_id per row for the block null (None or ''
    is an unshared row, its own block)."""
    return [r["story_group_id"] for r in rows]


def signed_values(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """9.4: signed_bp = +10,000 x excess_1session for POSITIVE and
    -10,000 x excess_1session for NEGATIVE."""
    excess = np.asarray([r["excess_1session"] for r in rows],
                        dtype=np.float64).reshape(-1)
    is_positive = np.asarray([r["judgment"] == K.POSITIVE for r in rows],
                             dtype=bool).reshape(-1)
    return stats.signed_bp(excess, is_positive)


def direction_labels(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """Amendment 6: +1 for POSITIVE, -1 for NEGATIVE (stats label codes)."""
    return np.asarray([stats.POSITIVE_LABEL if r["judgment"] == K.POSITIVE
                       else stats.NEGATIVE_LABEL for r in rows],
                      dtype=np.int64).reshape(-1)


def excess_values(rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """9.4: excess_1session as stored (a fraction), for the permutation null."""
    return np.asarray([r["excess_1session"] for r in rows],
                      dtype=np.float64).reshape(-1)


def day_exclusion(state_counts: Mapping[str, Mapping[str, int]]
                  ) -> tuple[tuple[str, ...], dict[str, float]]:
    """9.1 with Task 7 and D18: the query_dates whose source_failed share
    exceeds K.SOURCE_FAILED_DAY_EXCLUDE (news_eval.cutoff, shared with the
    gate)."""
    return cutoff.excluded_query_dates(state_counts)


def cutoff_s_star(session_status: Mapping[Any, Mapping[str, int]]
                  ) -> cutoff.SStar:
    """9.7 with D16: the cutoff S* (news_eval.cutoff, shared with the gate)."""
    return cutoff.compute_s_star(session_status)


def scorable_filter(excluded_query_dates: Iterable[str],
                    s_star: str | None) -> Callable[[Mapping[str, Any]], str | None]:
    """9.7 with D1 and D25: build the filter for rows meeting every scorable
    condition except the judgment condition, after the 9.1 day exclusion and
    at or before S*.

    The returned function gives None for a row that passes (a gate row G,
    NEUTRAL included) and otherwise the first failing condition, tested in
    DROP_ORDER. A None s_star means the analysis set is empty
    (news_eval.cutoff), so every otherwise-passing row is beyond S*. A NULL
    excess_1session is excluded and counted, never read as 0 (D25)."""
    excluded = frozenset(excluded_query_dates)

    def reason(row: Mapping[str, Any]) -> str | None:
        if row["run_kind"] != K.RUN_KIND_COLLECTION:
            return DROP_RUN_KIND
        if row["state"] != K.STATE_JUDGED:
            return DROP_STATE
        if row["outcome_state"] != K.OUTCOME_RESOLVED:
            return (DROP_PENDING if row["outcome_state"] == K.OUTCOME_PENDING
                    else DROP_OUTCOME_OTHER)
        if row["exclusion_reason"] != K.EXCLUSION_NONE:
            return DROP_EXCLUSION
        session = row["scoring_session"]
        if session is None or session == "":
            return DROP_SESSION_EMPTY
        if row["query_date"] in excluded:
            return DROP_DAY_RULE
        if s_star is None or session > s_star:
            return DROP_BEYOND_S_STAR
        if row["excess_1session"] is None:
            return DROP_EXCESS_NULL
        return None

    return reason


def is_directional(row: Mapping[str, Any]) -> bool:
    """9.7: the judgment condition (POSITIVE or NEGATIVE)."""
    return row["judgment"] in K.DIRECTIONAL


def estimate_t(values, clusters, *, rng: np.random.Generator
               ) -> stats.BootstrapResult:
    """9.4 and 9.5: the observation-weighted T with its cluster bootstrap,
    K.N_BOOT draws, interval at K.BAR_PRIMARY_Z (P1 to P4 on signed_bp,
    E1 to E4 on net_bp)."""
    return stats.cluster_bootstrap_ratio(values, clusters, n_draws=K.N_BOOT,
                                         rng=rng, bar=K.BAR_PRIMARY_Z)


def _modal(values: Iterable[Any], tie_to: str) -> Any:
    """The most frequent value; ties go to tie_to when it is among the tied
    values, else to the smallest (D9, D10). None for no values."""
    counts = Counter(values)
    if not counts:
        return None
    top = max(counts.values())
    tied = sorted(v for v, n in counts.items() if n == top)
    return tie_to if tie_to in tied else tied[0]


def flag_sensitivity_pairs(collection_rows: Iterable[Mapping[str, Any]]
                           ) -> dict[tuple[str, str], tuple[str, ...]]:
    """8.2 with D9: the (symbol, formation_date) pairs the sensitivity
    reading removes, with the rules that flag each ("a", "b").

    Rule (a), by symbol in every formation: a symbol containing
    K.SENS_RULE_A_CHAR or listed in K.SENS_RULE_A_SYMBOLS. Rule (b), per
    (symbol, formation) over every run_kind = 'collection' row of that pair,
    any state: the modal non-null sector (ties toward 'N/A') is 'N/A', and
    the modal non-null sector_source among the pair's 'N/A' rows (ties
    toward 'finnhub_profile2') is 'finnhub_profile2'."""
    by_pair: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for r in collection_rows:
        if r["run_kind"] != K.RUN_KIND_COLLECTION:
            continue
        by_pair.setdefault((r["symbol"], r["formation_date"]), []).append(r)
    flags: dict[tuple[str, str], tuple[str, ...]] = {}
    for pair in sorted(by_pair):
        rows = by_pair[pair]
        rules = []
        if K.SENS_RULE_A_CHAR in pair[0] or pair[0] in K.SENS_RULE_A_SYMBOLS:
            rules.append("a")
        sector = _modal((r["sector"] for r in rows if r["sector"] is not None),
                        K.SENS_RULE_B_SECTOR)
        if sector == K.SENS_RULE_B_SECTOR:
            source = _modal((r["sector_source"] for r in rows
                             if r["sector"] == K.SENS_RULE_B_SECTOR
                             and r["sector_source"] is not None),
                            K.SENS_RULE_B_SOURCE)
            if source == K.SENS_RULE_B_SOURCE:
                rules.append("b")
        if rules:
            flags[pair] = tuple(rules)
    return flags


def build_sensitivity_set(rows: Sequence[Mapping[str, Any]],
                          flags: Mapping[tuple[str, str], Any]
                          ) -> tuple[Mapping[str, Any], ...]:
    """8.2 with D9: the rows of `rows` outside every flagged (symbol,
    formation); a flagged pair loses its rows in that formation only."""
    return tuple(r for r in rows
                 if (r["symbol"], r["formation_date"]) not in flags)


# ------------------------------------------------------------- analysis set

@dataclass(frozen=True)
class AnalysisSet:
    """9.7 analysis set with its funnel (D1, D16, D18, D25)."""
    excluded_query_dates: tuple[str, ...]
    day_shares: Mapping[str, float]
    s_star: cutoff.SStar
    gate_rows: tuple[Mapping[str, Any], ...]   # all 9.7 conditions but judgment
    scored: tuple[Mapping[str, Any], ...]      # gate rows, POSITIVE or NEGATIVE
    funnel: Mapping[str, Any]


def _funnel(inputs: Inputs, reasons: Sequence[str | None], sstar: cutoff.SStar,
            excluded: Sequence[str], gate_rows, scored) -> dict:
    """Counts of judged collection rows by the first failing condition
    (DROP_ORDER), the pending split (stale, not stale, empty session), and
    the non-exclusive day-rule and beyond-S* counts."""
    first = Counter(r for r in reasons if r is not None)
    stale_sessions = {s for s, _ in sstar.stale_pending}
    pending = Counter()
    other_outcomes = Counter()
    for row, why in zip(inputs.judged, reasons):
        if why == DROP_PENDING:
            session = row["scoring_session"]
            pending["empty_session" if not session else
                    "stale" if session in stale_sessions else "not_stale"] += 1
        elif why == DROP_OUTCOME_OTHER:
            other_outcomes[str(row["outcome_state"])] += 1
    excluded_set = frozenset(excluded)
    s_star = sstar.s_star
    judged_on_excluded_days = sum(1 for r in inputs.judged
                                  if r["query_date"] in excluded_set)
    judged_beyond = sum(1 for r in inputs.judged if r["scoring_session"]
                        and (s_star is None or r["scoring_session"] > s_star))
    judgments = Counter(r["judgment"] for r in gate_rows)
    return {
        "judged_collection_rows": len(inputs.judged),
        "dropped_first_reason": {k: first.get(k, 0) for k in DROP_ORDER},
        "pending": {k: pending.get(k, 0)
                    for k in ("stale", "not_stale", "empty_session")},
        "outcome_other_by_state": dict(sorted(other_outcomes.items())),
        "judged_on_excluded_days_any_outcome": judged_on_excluded_days,
        "judged_beyond_s_star_any_outcome": judged_beyond,
        "gate_rows": len(gate_rows),
        "gate_rows_by_judgment": {
            K.POSITIVE: judgments.get(K.POSITIVE, 0),
            K.NEGATIVE: judgments.get(K.NEGATIVE, 0),
            K.NEUTRAL: judgments.get(K.NEUTRAL, 0),
            "other": len(gate_rows) - sum(judgments.get(j, 0) for j in (
                K.POSITIVE, K.NEGATIVE, K.NEUTRAL))},
        "scored": len(scored),
        "scored_net_bp_null": sum(1 for r in scored if r["net_bp"] is None),
        "scored_strength_not_parse_ok": sum(
            1 for r in scored if r["strength_parse_ok"] != 1),
        "scored_parse_ok_strength_null": sum(
            1 for r in scored if r["strength_parse_ok"] == 1
            and r["strength"] is None),
    }


def build_analysis(inputs: Inputs) -> AnalysisSet:
    """9.7 with 9.1, D1, D16, D18, D25: the gate rows G (every scorable
    condition but the judgment), the scored observations (G rows judged
    POSITIVE or NEGATIVE) and the funnel of what was dropped and why."""
    excluded, shares = day_exclusion(inputs.state_counts)
    sstar = cutoff_s_star(inputs.session_status)
    reason = scorable_filter(excluded, sstar.s_star)
    reasons = [reason(r) for r in inputs.judged]
    gate_rows = tuple(r for r, why in zip(inputs.judged, reasons) if why is None)
    scored = tuple(r for r in gate_rows if is_directional(r))
    funnel = _funnel(inputs, reasons, sstar, excluded, gate_rows, scored)
    return AnalysisSet(excluded_query_dates=tuple(excluded),
                       day_shares=dict(shares), s_star=sstar,
                       gate_rows=gate_rows, scored=scored, funnel=funnel)


def half_boundary(scored: Sequence[Mapping[str, Any]]) -> tuple[Any, dict]:
    """9.6 with D17: order the D clusters holding scored observations; the
    second half is the last floor(D/2). Returns the first second-half
    cluster (None when the second half is empty) and the split's counts.
    A row is in the second half when its cluster is at or after the
    boundary, so rows of a cluster holding no scored observation (diagnostics
    only) fall in the half its date places them."""
    clusters = sorted({cluster_of(r) for r in scored})
    d = len(clusters)
    n_second = d // 2
    n_first = d - n_second
    boundary = clusters[n_first] if n_second else None
    return boundary, {
        "D": d, "first_half_clusters": n_first,
        "second_half_clusters": n_second,
        "first_half_first": clusters[0] if d else None,
        "first_half_last": clusters[n_first - 1] if n_first else None,
        "second_half_first": boundary,
        "second_half_last": clusters[-1] if n_second else None,
    }


def in_second_half(row: Mapping[str, Any], boundary: Any) -> bool:
    """9.6: the row's cluster is in the chronological second half."""
    return boundary is not None and cluster_of(row) >= boundary


# ------------------------------------------------------------- serialisation

def _plain(obj: Any) -> Any:
    """A JSON-serialisable copy: str keys, lists for tuples, Python scalars.
    A non-finite float is a defect and raises."""
    if isinstance(obj, Mapping):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        if not math.isfinite(value):
            raise ValueError("non-finite number in the results")
        return value
    if obj is None or isinstance(obj, str):
        return obj
    raise TypeError(f"not serialisable: {type(obj).__name__}")


def _result_dict(result: Any, *, skip: tuple[str, ...] = ("replicates",),
                 **extra: Any) -> dict:
    out = {f.name: getattr(result, f.name) for f in fields(result)
           if f.name not in skip}
    out.update(extra)
    return out


def _mean(values: Sequence[float]) -> float | None:
    return math.fsum(float(v) for v in values) / len(values) if len(values) else None


def _n_clusters(rows: Sequence[Mapping[str, Any]]) -> int:
    return len({cluster_of(r) for r in rows})


def _stratum_key(value: Any) -> str:
    return "null" if value is None else str(value)


def _stratum_keys(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    present = {_stratum_key(r["stratum"]) for r in rows}
    return list(K.STRATA) + sorted(present - set(K.STRATA))


# ------------------------------------------------------------- diagnostics

def judgment_counts(rows: Sequence[Mapping[str, Any]]) -> dict:
    """Amendment 6: POSITIVE, NEGATIVE and NEUTRAL counts and shares (any
    other judgment value counted as "other"), over the given rows."""
    c = Counter(r["judgment"] for r in rows)
    total = len(rows)
    counts = {K.POSITIVE: c.get(K.POSITIVE, 0), K.NEGATIVE: c.get(K.NEGATIVE, 0),
              K.NEUTRAL: c.get(K.NEUTRAL, 0)}
    counts["other"] = total - sum(counts.values())
    shares = {k: (n / total if total else None) for k, n in counts.items()}
    return {"total": total, "counts": counts, "shares": shares}


def strength_rows(scored: Sequence[Mapping[str, Any]]) -> list:
    """Task 5 Amendment 3, 9.10: scored observations with strength_parse_ok = 1
    (and a stored strength)."""
    return [r for r in scored
            if r["strength_parse_ok"] == 1 and r["strength"] is not None]


def strength_histogram(scored: Sequence[Mapping[str, Any]]) -> dict:
    """9.10: the strength histogram over scored strength_parse_ok = 1 rows,
    with the five per-bucket mean signed_bp, labelled descriptive."""
    rows = strength_rows(scored)
    signed = signed_values(rows)
    buckets = {}
    for s in STRENGTH_BUCKETS:
        vals = [float(v) for r, v in zip(rows, signed) if r["strength"] == s]
        buckets[str(s)] = {"n": len(vals), "mean_signed_bp": _mean(vals)}
    other = Counter(str(r["strength"]) for r in rows
                    if r["strength"] not in STRENGTH_BUCKETS)
    return {"label": DESCRIPTIVE, "n_parse_ok": len(rows),
            "n_not_parse_ok": sum(1 for r in scored
                                  if r["strength_parse_ok"] != 1),
            "buckets": buckets, "other_values": dict(sorted(other.items()))}


def _balance_dict(rows: Sequence[Mapping[str, Any]]) -> dict:
    bal = stats.minority_share_and_mixed(direction_labels(rows),
                                         bootstrap_clusters(rows))
    return {"n_positive": bal.n_positive, "n_negative": bal.n_negative,
            "minority_share": bal.minority_share,
            "n_mixed_clusters": bal.n_mixed_strata,
            "n_clusters": bal.n_strata}


def null_determination(scored: Sequence[Mapping[str, Any]]) -> dict:
    """Amendment 6 skew diagnostic with D2: one determination per reading,
    over its scored observations, applied to all four primaries."""
    bal = _balance_dict(scored)
    return {**bal,
            "min_minority_share": K.NULL_MIN_MINORITY_SHARE,
            "min_mixed_clusters": K.NULL_MIN_MIXED_CLUSTERS,
            "informative": verdict.null_informative(
                bal["minority_share"], bal["n_mixed_clusters"])}


def diagnostics(gate_rows: Sequence[Mapping[str, Any]],
                scored: Sequence[Mapping[str, Any]], boundary: Any) -> dict:
    """Amendment 6 and Task 5 with D20, reported before the null: judgment
    counts and shares pooled, per stratum and per half over the gate rows
    (NEUTRAL included); the NEUTRAL rate against K.NEUTRAL_RATE_BAR; the
    strength histogram; per-stratum counts and cluster counts over the
    scored observations; D and M."""
    pooled = judgment_counts(gate_rows)
    neutral_rate = pooled["shares"][K.NEUTRAL]
    per_stratum = {s: judgment_counts([r for r in gate_rows
                                       if _stratum_key(r["stratum"]) == s])
                   for s in _stratum_keys(gate_rows)}
    per_half = {
        "first": judgment_counts([r for r in gate_rows
                                  if not in_second_half(r, boundary)]),
        "second": judgment_counts([r for r in gate_rows
                                   if in_second_half(r, boundary)])}
    clusters = {}
    for s in _stratum_keys(scored):
        rows = [r for r in scored if _stratum_key(r["stratum"]) == s]
        net = [r for r in rows if r["net_bp"] is not None]
        clusters[s] = {"scored": len(rows), "scored_clusters": _n_clusters(rows),
                       "net_bp_non_null": len(net),
                       "net_bp_null": len(rows) - len(net),
                       "net_bp_clusters": _n_clusters(net)}
    return {
        "population": "gate rows: every 9.7 scorable condition except the "
                      "judgment condition (D20)",
        "pooled": pooled, "per_stratum": per_stratum, "per_half": per_half,
        "neutral_rate": neutral_rate,
        "neutral_rate_bar": K.NEUTRAL_RATE_BAR,
        "neutral_rate_exceeds_bar": (neutral_rate is not None
                                     and neutral_rate > K.NEUTRAL_RATE_BAR),
        "strength_histogram": strength_histogram(scored),
        "per_stratum_scored": clusters,
        "D": _n_clusters(scored), "M": len(scored),
    }


# ------------------------------------------------------------- the tests

def _streams(test: str, reading: str) -> tuple[int, np.random.Generator,
                                                np.random.Generator]:
    """9.11 with D13: the (test, reading) stream index, its bootstrap child of
    K.BOOT_SEED and its permutation child of K.PERM_SEED."""
    idx = K.stream_index(test, reading)
    return (idx, stats.child_rng(K.BOOT_SEED, idx),
            stats.child_rng(K.PERM_SEED, idx))


def run_primary(test: str, reading: str, subset: Sequence[Mapping[str, Any]],
                perm_rows: Sequence[Mapping[str, Any]], mode: str, *,
                story: bool = False) -> dict:
    """One primary test (Task 5, Amendment 6, 9.2 to 9.5, 9.9, 9.10).

    T over the subset's signed_bp with the cluster bootstrap (clusters
    scoring_session, or story_group_id in the story version), and the
    permutation null over perm_rows (the subset itself in "subset" mode;
    every scored observation of the reading in "negative_only" mode), K.N_PERM
    permutations within scoring_session, story groups as blocks in the story
    version. n_clusters is the 9.2 floor's count: scoring_session clusters
    holding the subset (in both versions; 9.1 "every cluster count")."""
    idx, boot_rng, perm_rng = _streams(test, reading)
    clusters = story_clusters(subset) if story else bootstrap_clusters(subset)
    boot = estimate_t(signed_values(subset), clusters, rng=boot_rng)
    perm = stats.permutation_test(
        excess_values(perm_rows), direction_labels(perm_rows),
        permutation_strata(perm_rows), mode=mode, n_perm=K.N_PERM,
        rng=perm_rng, story_groups=story_groups(perm_rows) if story else None)
    return {
        "test": test, "reading": reading, "subset": PRIMARY_SUBSETS[test],
        "clustering": "story_group_id" if story else "scoring_session",
        "n_obs": len(subset), "n_clusters": _n_clusters(subset),
        "floor": K.FLOOR_TEST_CLUSTERS,
        "bootstrap": _result_dict(boot, stream_index=idx),
        "permutation": _result_dict(perm, stream_index=idx),
        "permutation_population_balance": _balance_dict(perm_rows),
    }


def primary_tests(scored: Sequence[Mapping[str, Any]], boundary: Any,
                  reading: str, *, story: bool = False) -> dict:
    """P1 to P4 (Task 5, Amendment 6, 9.6): pooled, NEGATIVE-only (null over
    all of the day's scored observations, subset re-formed per draw),
    thin-end S3 and S4, chronological second half."""
    negative = [r for r in scored if r["judgment"] == K.NEGATIVE]
    thin = [r for r in scored if r["stratum"] in K.THIN_END]
    second = [r for r in scored if in_second_half(r, boundary)]
    plan = (("P1", scored, scored, stats.MODE_SUBSET),
            ("P2", negative, scored, stats.MODE_NEGATIVE_ONLY),
            ("P3", thin, thin, stats.MODE_SUBSET),
            ("P4", second, second, stats.MODE_SUBSET))
    return {test: run_primary(test, reading, subset, perm_rows, mode,
                              story=story)
            for test, subset, perm_rows, mode in plan}


def e_tests(scored: Sequence[Mapping[str, Any]], reading: str) -> dict:
    """E1 to E4 (Amendment 5, Task 6, 9.4, 9.10, D25): T over the stratum's
    scored observations with non-null net_bp, bootstrap at K.BAR_PRIMARY_Z.
    NULL net_bp rows are excluded and counted."""
    out = {}
    for test in sorted(K.E_TEST_STRATUM):
        stratum = K.E_TEST_STRATUM[test]
        rows = [r for r in scored if r["stratum"] == stratum]
        net = [r for r in rows if r["net_bp"] is not None]
        idx, boot_rng, _ = _streams(test, reading)
        values = np.asarray([float(r["net_bp"]) for r in net], dtype=np.float64)
        boot = estimate_t(values, bootstrap_clusters(net), rng=boot_rng)
        out[test] = {"test": test, "reading": reading, "stratum": stratum,
                     "n_scored": len(rows), "n_net_bp_null": len(rows) - len(net),
                     "n_obs": len(net), "n_clusters": _n_clusters(net),
                     "floor": K.FLOOR_TEST_CLUSTERS,
                     "econ_bar_bp": K.ECON_BAR_BP,
                     "bootstrap": _result_dict(boot, stream_index=idx)}
    return out


def strength_tests(scored: Sequence[Mapping[str, Any]], reading: str) -> dict:
    """S1 and S2 (Task 5 Amendment 3, 9.10, D15) over scored observations
    with strength_parse_ok = 1, bootstrap at K.BAR_STRENGTH_Z. Every result
    carries the strength label (weaker evidence; never confirmation)."""
    rows = strength_rows(scored)
    strength = np.asarray([float(r["strength"]) for r in rows], dtype=np.float64)
    values = signed_values(rows)
    clusters = bootstrap_clusters(rows)
    common = {"reading": reading, "n_obs": len(rows),
              "n_clusters": _n_clusters(rows), "floor": K.FLOOR_TEST_CLUSTERS,
              "label": verdict.STRENGTH_LABEL}
    idx1, rng1, _ = _streams("S1", reading)
    s1 = stats.spearman_bootstrap(strength, values, clusters, n_draws=K.N_BOOT,
                                  rng=rng1, bar=K.BAR_STRENGTH_Z)
    idx2, rng2, _ = _streams("S2", reading)
    s2 = stats.top_bottom_bootstrap(
        strength, values, clusters, top_strengths=K.S2_TOP,
        bottom_strengths=K.S2_BOTTOM, n_draws=K.N_BOOT, rng=rng2,
        bar=K.BAR_STRENGTH_Z)
    return {
        "S1": {"test": "S1", **common,
               "bootstrap": _result_dict(s1, stream_index=idx1)},
        "S2": {"test": "S2", **common,
               "n_top": int(np.isin(strength, K.S2_TOP).sum()),
               "n_bottom": int(np.isin(strength, K.S2_BOTTOM).sum()),
               "bootstrap": _result_dict(s2, stream_index=idx2)},
    }


def reading_results(reading: str, gate_rows: Sequence[Mapping[str, Any]],
                    scored: Sequence[Mapping[str, Any]], boundary: Any) -> dict:
    """One reading (primary or 8.2 sensitivity): diagnostics first
    (Amendment 6, D20), the D2 null determination, then P1 to P4, E1 to E4,
    S1 and S2 on that reading's 9.11 streams."""
    return {
        "reading": reading,
        "D": _n_clusters(scored), "M": len(scored),
        "diagnostics": diagnostics(gate_rows, scored, boundary),
        "null": null_determination(scored),
        "tests": {**primary_tests(scored, boundary, reading),
                  **e_tests(scored, reading),
                  **strength_tests(scored, reading)},
    }


def story_trigger(scored: Sequence[Mapping[str, Any]]) -> dict:
    """9.10 with D11: the share of the primary reading's scored observations
    whose non-empty story_group_id appears on at least 2 scored observations;
    the trigger fires above K.STORY_TRIGGER_SHARE.

    N7 ruling (reports/c1_rulings.md): an empty scored set has no share. The
    share is None, not 0.0, the trigger does not fire, and "reason" says the
    pool was empty (None otherwise)."""
    groups = Counter(r["story_group_id"] for r in scored if r["story_group_id"])
    shared = sum(1 for r in scored
                 if r["story_group_id"] and groups[r["story_group_id"]] >= 2)
    m = len(scored)
    share = shared / m if m else None
    return {"n_scored": m, "n_shared": shared,
            "n_shared_groups": sum(1 for n in groups.values() if n >= 2),
            "share": share, "threshold": K.STORY_TRIGGER_SHARE,
            "fired": share is not None and share > K.STORY_TRIGGER_SHARE,
            "reason": None if m else STORY_EMPTY_POOL_REASON}


def sector_robustness(scored: Sequence[Mapping[str, Any]]) -> dict:
    """9.10 with D10: P1's T (primary reading) with a CR1 SE over sectors.
    A (symbol, formation)'s sector is the modal non-null sector over its
    analysis-set rows, ties to 'N/A' when tied, else the smallest; 'N/A'
    and null pool as K.SECTOR_UNCLASSIFIED. Descriptive, no bar."""
    by_pair: dict[tuple[str, str], list] = {}
    for r in scored:
        by_pair.setdefault((r["symbol"], r["formation_date"]), []).append(
            r["sector"])
    label_of = {}
    for pair, sectors in by_pair.items():
        sector = _modal((s for s in sectors if s is not None),
                        K.SENS_RULE_B_SECTOR)
        label_of[pair] = (K.SECTOR_UNCLASSIFIED
                          if sector is None or sector == K.SENS_RULE_B_SECTOR
                          else sector)
    labels = [label_of[(r["symbol"], r["formation_date"])] for r in scored]
    res = stats.cr1_mean(signed_values(scored), labels)
    return {"label": DESCRIPTIVE, "test": "P1", "reading": READING_PRIMARY,
            **_result_dict(res, skip=()),
            "observations_per_sector": dict(sorted(Counter(labels).items()))}


def sensitivity_report(flags: Mapping[tuple[str, str], tuple[str, ...]],
                       judged: Sequence[Mapping[str, Any]],
                       scored: Sequence[Mapping[str, Any]]) -> dict:
    """8.2: the excluded (symbol, formation) pairs per rule with their judged
    and scored-row counts, and each rule's scale (the closed-end-fund defect
    scale is rule b's)."""
    judged_by = Counter((r["symbol"], r["formation_date"]) for r in judged)
    scored_by = Counter((r["symbol"], r["formation_date"]) for r in scored)

    def entries(rule: str) -> list[dict]:
        return [{"symbol": p[0], "formation_date": p[1],
                 "judged_rows": judged_by[p], "scored_rows": scored_by[p]}
                for p, rules in sorted(flags.items()) if rule in rules]

    def scale(pairs: list) -> dict:
        j = sum(judged_by[p] for p in pairs)
        s = sum(scored_by[p] for p in pairs)
        return {"pairs": len(pairs),
                "symbols": sorted({p[0] for p in pairs}),
                "judged_rows": j,
                "judged_share": j / len(judged) if judged else None,
                "scored_rows": s,
                "scored_share": s / len(scored) if scored else None}

    return {
        "rule_a": entries("a"), "rule_b": entries("b"),
        "rule_a_scale": scale([p for p, r in flags.items() if "a" in r]),
        "rule_b_scale": scale([p for p, r in flags.items() if "b" in r]),
        "all_scale": scale(sorted(flags)),
    }


def _settings() -> dict:
    return {"cluster_column": CLUSTER_COLUMN, "n_boot": K.N_BOOT,
            "n_perm": K.N_PERM, "boot_seed": K.BOOT_SEED,
            "perm_seed": K.PERM_SEED, "bar_primary_z": K.BAR_PRIMARY_Z,
            "bar_strength_z": K.BAR_STRENGTH_Z, "bar_perm_p": K.BAR_PERM_P,
            "econ_bar_bp": K.ECON_BAR_BP, "effect_bp": K.EFFECT_BP,
            "floor_analysis_clusters": K.FLOOR_ANALYSIS_CLUSTERS,
            "floor_scorable": K.FLOOR_SCORABLE,
            "floor_test_clusters": K.FLOOR_TEST_CLUSTERS}


def compute_from_inputs(inputs: Inputs) -> dict:
    """9.1 to 9.11 on loaded inputs (compute() without the database read)."""
    analysis = build_analysis(inputs)
    flags = flag_sensitivity_pairs(inputs.collection)
    sens_gate = build_sensitivity_set(analysis.gate_rows, flags)
    sens_scored = tuple(r for r in sens_gate if is_directional(r))
    boundary, halves = half_boundary(analysis.scored)
    readings = {
        READING_PRIMARY: reading_results(READING_PRIMARY, analysis.gate_rows,
                                         analysis.scored, boundary),
        READING_SENSITIVITY: reading_results(READING_SENSITIVITY, sens_gate,
                                             sens_scored, boundary),
    }
    trigger = story_trigger(analysis.scored)
    story_readings = {}
    if trigger["fired"]:
        for name, rows in ((READING_PRIMARY, analysis.scored),
                           (READING_SENSITIVITY, sens_scored)):
            story_readings[STORY_READING[name]] = {
                "tests": primary_tests(rows, boundary, STORY_READING[name],
                                       story=True)}
    excluded_set = frozenset(analysis.excluded_query_dates)
    return _plain({
        "settings": _settings(),
        "analysis_set": {
            "day_rule": {
                "excluded_query_dates": list(analysis.excluded_query_dates),
                "source_failed_share": dict(analysis.day_shares),
                "threshold": K.SOURCE_FAILED_DAY_EXCLUDE,
                "collection_rows_on_excluded_days": sum(
                    sum(by_state.values())
                    for qd, by_state in inputs.state_counts.items()
                    if qd in excluded_set)},
            "cutoff": analysis.s_star.as_dict(),
            "funnel": analysis.funnel,
        },
        "sensitivity_exclusion": sensitivity_report(flags, inputs.judged,
                                                    analysis.scored),
        "halves": halves,
        "readings": readings,
        "story": {"trigger": trigger, "fired": trigger["fired"],
                  "readings": story_readings},
        "sector_robustness": sector_robustness(analysis.scored),
    })


def compute(db_path, *, real_db_path=None, unlock_path=None,
            marker_path=None) -> dict:
    """The full Stage C family result (9.1 to 9.11, Amendment 6, 8.2).

    Deterministic: the same database gives byte-identical
    json.dumps(compute(...), sort_keys=True). Holds no timestamp and no path.
    Always runs K.N_BOOT bootstrap draws and K.N_PERM permutations.
    Refuses (envcheck.EnvironmentRefused) before any database access when the
    numpy elision canary fails."""
    envcheck.assert_numpy_sane()
    return compute_from_inputs(load_inputs(
        db_path, real_db_path=real_db_path, unlock_path=unlock_path,
        marker_path=marker_path))


def companion_horizons(db_path, *, real_db_path=None, unlock_path=None,
                       marker_path=None) -> dict:
    """9.12 with D26: for k in 2, 5 and 10, the observation-weighted mean over
    the primary reading's scored observations with non-null ret_ksession of
    +10,000 x ret_ksession for POSITIVE and -10,000 x ret_ksession for
    NEGATIVE. EXPLORATORY: no interval, no bar. The runner calls this only
    when the 9.12 condition holds; compute() never does. Refuses
    (envcheck.EnvironmentRefused) before any database access when the numpy
    elision canary fails."""
    envcheck.assert_numpy_sane()
    inputs = load_inputs(db_path, real_db_path=real_db_path,
                         unlock_path=unlock_path, marker_path=marker_path)
    analysis = build_analysis(inputs)
    columns = ("id",) + tuple(col for _, col in COMPANION_HORIZONS)
    kw = _phase_kwargs(real_db_path, unlock_path, marker_path)
    with data.open_phase("VERDICT", db_path, **kw) as phase:
        rows = phase.select(columns, (
            ("run_kind", "=", K.RUN_KIND_COLLECTION),
            ("state", "=", K.STATE_JUDGED)))
    by_id = {r[0]: r[1:] for r in rows}
    horizons = {}
    for i, (k, col) in enumerate(COMPANION_HORIZONS):
        kept = [(r, by_id[r["id"]][i]) for r in analysis.scored
                if by_id[r["id"]][i] is not None]
        signed = stats.signed_bp(
            np.asarray([v for _, v in kept], dtype=np.float64).reshape(-1),
            np.asarray([r["judgment"] == K.POSITIVE for r, _ in kept],
                       dtype=bool).reshape(-1))
        horizons[col] = {"k": k, "n_obs": len(kept),
                         "n_null": len(analysis.scored) - len(kept),
                         "mean_signed_bp": _mean(signed.tolist())}
    return _plain({"label": "EXPLORATORY", "reading": READING_PRIMARY,
                   "interval": None, "bar": None, "horizons": horizons})

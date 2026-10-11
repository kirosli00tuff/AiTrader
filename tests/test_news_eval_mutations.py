"""Mutation tests for the Stage C harness (STAGE C.1 Task 7).

Each mutant is one plausible implementation error, applied with pytest's
monkeypatch to the symbol named in its `target`. For each mutant the test
first runs its kill checks on the unmutated harness (every check must pass),
then applies the mutant and runs the same checks again: at least one must
fail. The checks are known-answer checks: scenario_failures from
tests/test_news_eval_known_answers.py (the same functions its per-scenario
tests assert empty) and the five toy known answers below, each derived by
hand and asserted by test_toy_known_answer.

Scenario checks run family.compute_from_inputs on the cached scenario inputs
with the registered 10,000 bootstrap draws and K.N_PERM = 1,000 permutations
(set for both runs; every expected status and pin in the scenarios holds at
1,000, and the p pins scale their tolerance with n_perm), then verdict.decide
and gate.evaluate. Inputs and references are fetched before the mutant is
applied, so nothing cached is computed under a mutant.

Mutants (Task 7): a shuffle labels across clusters, b drop the upper-tail
rule, c mean of cluster means, d cluster on query_date, e1 a 1.96 interval
for P and E tests, e2 1.96 for S1 and S2, f1 flip the 9.4 sign convention,
f2 flip the null's label sign, g skip the 20 percent day exclusion, h treat
pending rows as resolved (S* and the scorable filter), h2 the scorable
filter alone, i skip the 8.2 sensitivity reading.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

import numpy as np
import pytest

import test_news_eval_known_answers as KA
from news_eval import constants as K
from news_eval import cutoff, family, gate, stats, verdict

MUTATION_N_PERM = 1_000
POS, NEG = KA.POS, KA.NEG
Check = Callable[[KA.ScenarioCache], Callable[[], list[str]]]


@pytest.fixture(autouse=True)
def _guards(monkeypatch, tmp_path):
    before = KA.install_guards(monkeypatch, tmp_path)
    yield
    assert [p.exists() for p in KA.C2_PATHS] == before == [False] * 3


@pytest.fixture(scope="session")
def cache(tmp_path_factory) -> KA.ScenarioCache:
    return KA.scenario_cache(tmp_path_factory)


# ------------------------------------------------- toy known answers

def toy_sessions(n: int) -> list[str]:
    return [(date(2026, 8, 3) + timedelta(days=i)).isoformat() for i in range(n)]


def toy_row(i: int, session: str, judgment: str, excess_bp: float) -> dict:
    return {"id": i, "scoring_session": session, "query_date": session,
            "judgment": judgment, "excess_1session": excess_bp / 1e4,
            "stratum": "S1", "story_group_id": None}


def confound_rows() -> list[dict]:
    """40 sessions of 10 rows. Every row of a session carries the same excess
    x_c (a day premium: +30..+42 bp on even sessions, -30..-42 bp on odd
    ones) and the label mix follows it (8 or 9 POSITIVE on up days, 1 or 2
    on down days). There is no skill within any day."""
    rows = []
    for c, s in enumerate(toy_sessions(40)):
        up = c % 2 == 0
        x = (30 + 2 * (c % 7)) * (1 if up else -1)
        k_pos = (8 + (c % 3 == 0)) if up else (2 - (c % 3 == 0))
        rows += [toy_row(len(rows) + j, s, POS if j < k_pos else NEG, x)
                 for j in range(10)]
    return rows


def anti_skill_rows() -> list[dict]:
    """40 sessions of 8 POSITIVE and 2 NEGATIVE rows. A day premium p_c
    (20..40 bp) on every row plus 60 bp more on the two NEGATIVE rows: the
    names called NEGATIVE rise most (anti-skill). T > 0 from the premium,
    and within each day the observed labelling is the unique minimum."""
    rows = []
    for c, s in enumerate(toy_sessions(40)):
        p = 20 + 2 * (c % 11)
        rows += [toy_row(len(rows) + j, s, POS if j < 8 else NEG,
                         p if j < 8 else p + 60) for j in range(10)]
    return rows


def unequal_rows() -> list[dict]:
    """30 sessions; session i (1..30) holds i POSITIVE rows of excess i bp.
    Observation-weighted T = sum i^2 / sum i = 9455/465 = 20.33; the mean of
    the cluster means would be 15.5."""
    rows = []
    for i, s in enumerate(toy_sessions(30), start=1):
        rows += [toy_row(len(rows) + j, s, POS, float(i)) for j in range(i)]
    return rows


def _p1(rows: list[dict]) -> tuple[dict, str, bool]:
    res = family.run_primary("P1", "primary", rows, rows, stats.MODE_SUBSET)
    informative = family.null_determination(rows)["informative"]
    return res, verdict.primary_status(res, informative), informative


def _report(prefix: str, checks: list[tuple[str, bool, str]]) -> list[str]:
    return [f"{prefix} {label}: {detail}" for label, ok, detail in checks if not ok]


def confound_failures() -> list[str]:
    """Within-session shuffles leave every T_perm equal to T_obs (constant
    excess inside a session, exact sums), so count_ge = count_le = n_perm,
    p = 1, not the upper tail: a met bootstrap bar is blocked_by_null."""
    rows = confound_rows()
    res, status, informative = _p1(rows)
    b, p = res["bootstrap"], res["permutation"]
    n = p["n_perm"]
    hand_t = math.fsum((1 if r["judgment"] == POS else -1) * r["excess_1session"]
                       * 1e4 for r in rows) / len(rows)
    return _report("confound toy", [
        ("informative", informative, f"{informative}"),
        ("bar met", b["z"] >= KA.PRIMARY_BAR and b["lower"] > 0, f"z {b['z']}"),
        ("T", KA.close(b["statistic"], hand_t, rel=KA.EXACT),
         f"{b['statistic']} != hand {hand_t}"),
        ("counts", (p["count_ge"], p["count_le"]) == (n, n),
         f"ge {p['count_ge']} le {p['count_le']}, want {n} and {n}"),
        ("p", p["p"] == 1.0, f"{p['p']} != 1"),
        ("status", status == verdict.BLOCKED_BY_NULL, f"{status} != blocked_by_null")])


def anti_skill_failures() -> list[str]:
    """T_obs is the global minimum of the within-session null (another
    labelling raises a session's sum by at least 120 bp), so count_ge =
    n_perm, count_le = 0 (a tie needs all 40 sessions at 1/45 each), p =
    2/(n+1) at its floor, and the statistic sits in the LOWER tail:
    blocked_by_null, never clear."""
    rows = anti_skill_rows()
    res, status, informative = _p1(rows)
    b, p = res["bootstrap"], res["permutation"]
    n = p["n_perm"]
    hand_t = math.fsum((8 * pc - 2 * (pc + 60)) / 10
                       for pc in (20 + 2 * (c % 11) for c in range(40))) / 40
    return _report("anti-skill toy", [
        ("informative", informative, f"{informative}"),
        ("bar met", b["z"] >= KA.PRIMARY_BAR and b["lower"] > 0, f"z {b['z']}"),
        ("T", KA.close(b["statistic"], hand_t, rel=KA.EXACT),
         f"{b['statistic']} != hand {hand_t}"),
        ("counts", (p["count_ge"], p["count_le"]) == (n, 0),
         f"ge {p['count_ge']} le {p['count_le']}, want {n} and 0"),
        ("p", KA.close(p["p"], 2.0 / (n + 1), rel=KA.EXACT) and p["p"] <= KA.PERM_P_BAR,
         f"{p['p']} != 2/{n + 1}"),
        ("status", status == verdict.BLOCKED_BY_NULL, f"{status} != blocked_by_null")])


def unequal_failures() -> list[str]:
    rows = unequal_rows()
    res = family.run_primary("P1", "primary", rows, rows, stats.MODE_SUBSET)
    t = res["bootstrap"]["statistic"]
    return _report("unequal-cluster toy", [
        ("T", KA.close(t, 9455 / 465, rel=1e-12), f"{t} != 9455/465 = {9455 / 465}"),
        ("n", (res["n_obs"], res["n_clusters"]) == (465, 30),
         f"{res['n_obs']} rows in {res['n_clusters']} clusters")])


def _toy_test(t: float, se: float) -> dict:
    return {"n_clusters": 64,
            "bootstrap": {"status": "ok", "statistic": t, "se": se, "n_clusters": 64},
            "permutation": {"status": "ok", "p": 0.0002, "count_ge": 0,
                            "count_le": 10_000}}


def primary_bar_failures() -> list[str]:
    """z = +2.2 and -2.2 sit inside 2.50: a primary reads not_clear (even with
    p at its floor in the upper tail) and an E-test abstain_interval."""
    got = (verdict.primary_status(_toy_test(11.0, 5.0), True),
           verdict.primary_status(_toy_test(-11.0, 5.0), True),
           verdict.e_status(_toy_test(11.0, 5.0)))
    want = (verdict.NOT_CLEAR, verdict.NOT_CLEAR, verdict.ABSTAIN_INTERVAL)
    return _report("bar toy", [
        (label, g == w, f"{g} != {w}") for label, g, w in zip(
            ("primary z +2.2", "primary z -2.2", "E-test z +2.2"), got, want)])


def strength_bar_failures() -> list[str]:
    """z = 2.1 sits inside 2.24: S1 and S2 read not_clear (D = 64)."""
    got = verdict.strength_status(_toy_test(0.21, 0.1), 64)
    return _report("strength toy", [("z 2.1", got == verdict.NOT_CLEAR,
                                      f"{got} != not_clear")])


TOYS = {"confound": confound_failures, "anti_skill": anti_skill_failures,
        "unequal_clusters": unequal_failures, "primary_bar": primary_bar_failures,
        "strength_bar": strength_bar_failures}


@pytest.mark.parametrize("toy_name", sorted(TOYS))
def test_toy_known_answer(toy_name):
    assert TOYS[toy_name]() == []


# ------------------------------------------------------------------ checks

def scenario(name: str) -> Check:
    def prepare(c: KA.ScenarioCache) -> Callable[[], list[str]]:
        inputs, ref, db = c.inputs(name), c.reference(name), c.db(name)

        def run() -> list[str]:
            results = family.compute_from_inputs(inputs)
            decision = verdict.decide(results)
            entry = gate.evaluate(db, real_db_path=c.fake_real)
            return [f"{name}: {x}" for x in KA.scenario_failures(
                name, results, decision, ref, entry)]
        return run
    prepare.label = f"scenario {name}"
    return prepare


def toy(key: str) -> Check:
    def prepare(c: KA.ScenarioCache) -> Callable[[], list[str]]:
        return TOYS[key]
    prepare.label = f"toy {key}"
    return prepare


# ----------------------------------------------------------------- mutants

def _across_clusters(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(family, "permutation_strata", lambda rows: [0] * len(rows))


def _no_upper_tail(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(verdict, "upper_tail",
               lambda perm: None if not perm or perm.get("status") != "ok" else True)


def _mean_of_cluster_means(mp: pytest.MonkeyPatch) -> None:
    def estimate_t(values, clusters, *, rng):
        v = np.asarray(values, dtype=np.float64)
        labels, inverse = np.unique(np.asarray(clusters), return_inverse=True)
        means = (np.bincount(inverse, weights=v, minlength=labels.size)
                 / np.bincount(inverse, minlength=labels.size))
        return stats.cluster_bootstrap_ratio(means, labels, n_draws=K.N_BOOT,
                                             rng=rng, bar=K.BAR_PRIMARY_Z)
    mp.setattr(family, "estimate_t", estimate_t)


def _query_date_clusters(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(family, "CLUSTER_COLUMN", "query_date")


def _bar(name: str) -> Callable[[pytest.MonkeyPatch], None]:
    return lambda mp: mp.setattr(K, name, 1.96)


def _flip_signed(mp: pytest.MonkeyPatch) -> None:
    original = family.signed_values
    mp.setattr(family, "signed_values", lambda rows: -original(rows))


def _flip_labels(mp: pytest.MonkeyPatch) -> None:
    original = family.direction_labels
    mp.setattr(family, "direction_labels", lambda rows: -original(rows))


def _no_day_exclusion(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(cutoff, "excluded_query_dates", lambda counts: ((), {}))


def _filter_pending_as_resolved(mp: pytest.MonkeyPatch) -> None:
    original = family.scorable_filter

    def scorable_filter(excluded, s_star):
        inner = original(excluded, s_star)
        return lambda r: inner({**r, "outcome_state": K.OUTCOME_RESOLVED}
                               if r["outcome_state"] == K.OUTCOME_PENDING else r)
    mp.setattr(family, "scorable_filter", scorable_filter)


def _pending_as_resolved(mp: pytest.MonkeyPatch) -> None:
    original = cutoff.compute_s_star

    def compute_s_star(session_status):
        merged = {}
        for session, by in session_status.items():
            out = {k: v for k, v in by.items() if k != K.OUTCOME_PENDING}
            out[K.OUTCOME_RESOLVED] = (by.get(K.OUTCOME_RESOLVED, 0)
                                       + by.get(K.OUTCOME_PENDING, 0))
            merged[session] = out
        return original(merged)
    mp.setattr(cutoff, "compute_s_star", compute_s_star)
    _filter_pending_as_resolved(mp)


def _no_sensitivity(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(family, "build_sensitivity_set", lambda rows, flags: tuple(rows))


@dataclass(frozen=True)
class Mutant:
    key: str
    description: str
    target: str
    apply: Callable[[pytest.MonkeyPatch], None]
    checks: tuple[Check, ...]


MUTANTS = (
    Mutant("a", "shuffle labels across clusters instead of within",
           "news_eval.family.permutation_strata -> one stratum",
           _across_clusters, (toy("confound"), scenario("S-PREMIUM"))),
    Mutant("b", "drop the upper-tail rule",
           "news_eval.verdict.upper_tail -> True",
           _no_upper_tail, (toy("anti_skill"),)),
    Mutant("c", "mean of cluster means instead of the observation-weighted T",
           "news_eval.family.estimate_t -> T over per-cluster means",
           _mean_of_cluster_means, (toy("unequal_clusters"), scenario("S-NULL"))),
    Mutant("d", "cluster on query_date instead of scoring_session",
           "news_eval.family.CLUSTER_COLUMN = 'query_date'",
           _query_date_clusters, (scenario("S-CLUSTER"),)),
    Mutant("e1", "a 1.96 interval instead of 2.50 (P1-P4, E1-E4)",
           "news_eval.constants.BAR_PRIMARY_Z = 1.96",
           _bar("BAR_PRIMARY_Z"), (toy("primary_bar"), scenario("S-NULL"))),
    Mutant("e2", "a 1.96 interval instead of 2.24 (S1, S2)",
           "news_eval.constants.BAR_STRENGTH_Z = 1.96",
           _bar("BAR_STRENGTH_Z"), (toy("strength_bar"), scenario("S-NULL"))),
    Mutant("f1", "flip the 9.4 sign convention (signed_bp)",
           "news_eval.family.signed_values -> negated",
           _flip_signed, (scenario("S-EFFECT"),)),
    Mutant("f2", "flip the sign convention in the null (labels)",
           "news_eval.family.direction_labels -> negated",
           _flip_labels, (scenario("S-EFFECT"),)),
    Mutant("g", "skip the 20 percent source_failed day exclusion",
           "news_eval.cutoff.excluded_query_dates -> nothing excluded "
           "(reached by family.day_exclusion and gate)",
           _no_day_exclusion, (scenario("S-NULL"),)),
    Mutant("h", "treat pending rows as resolved",
           "news_eval.cutoff.compute_s_star (pending counted resolved; reached "
           "by family.cutoff_s_star and gate) + news_eval.family.scorable_filter",
           _pending_as_resolved, (scenario("S-CUTOFF"),)),
    Mutant("h2", "treat pending rows as resolved in the scorable filter only",
           "news_eval.family.scorable_filter (pending passes)",
           _filter_pending_as_resolved, (scenario("S-CUTOFF"),)),
    Mutant("i", "skip the 8.2 sensitivity reading",
           "news_eval.family.build_sensitivity_set -> every row kept",
           _no_sensitivity, (scenario("S-SENS"),)),
)


_BASELINE: dict[str, list[str]] = {}


@pytest.mark.parametrize("mutant", MUTANTS, ids=[m.key for m in MUTANTS])
def test_mutant_is_killed(mutant, cache, monkeypatch):
    monkeypatch.setattr(K, "N_PERM", MUTATION_N_PERM)
    runs = [(check.label, check(cache)) for check in mutant.checks]
    for label, run in runs:
        if label not in _BASELINE:
            _BASELINE[label] = run()
        assert _BASELINE[label] == [], f"{label} fails unmutated"
    mutant.apply(monkeypatch)
    observed = {label: run() for label, run in runs}
    killers = [label for label, failures in observed.items() if failures]
    for label, failures in observed.items():
        print(f"MUTANT {mutant.key} | {label} | {len(failures)} failures | "
              f"{failures[0] if failures else 'SURVIVED'}")
    assert killers, f"mutant {mutant.key} ({mutant.description}) survived"

"""Known answers for the Stage C harness (STAGE C.1 Task 7).

Every Task 2 scenario runs through the real entry points: gate.evaluate,
family.compute at the registered 10,000 draws and permutations, and
verdict.decide. Its outcome is checked against two sources that share no
code with the harness:

- synthetic.SCENARIOS[name].expected: the fixture author's machine-readable
  answer and its calibration numbers (an independent numpy implementation,
  reports/c1_scratch/synth/calib.py).
- `reference()` below: the analysis set, every T, the linearised cluster SE
  and the gate counts recomputed in plain Python from rows read through the
  SYNTHETIC loader phase. It imports nothing from family, cutoff or stats; the
  8.2 flags come from the fixture's own synthetic._flagged_82.

Registered numbers the checks rely on (2.50, 2.24, 10,000) are literals here,
so a mutant that moves news_eval.constants cannot move the expectation with it.
The failure functions return lists of strings; tests/test_news_eval_mutations.py
reuses them as its kill checks.

Five hand-built toy known answers, for what no scenario can pin (the
within-cluster null on a day premium that co-varies with the label mix, the
upper-tail rule, the observation-weighted T on unequal clusters, the 2.50 and
2.24 bars at the verdict layer), live in tests/test_news_eval_mutations.py
beside the mutants they kill.

The repository's news_experiment.db is never opened (sqlite3.connect is
guarded), data.REAL_DB_PATH points into tmp, and reports/c2* is never created.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from news_eval import constants as K
from news_eval import data, family, gate, synthetic, verdict

REPO = Path(__file__).resolve().parent.parent
REPO_REAL_DB = os.path.realpath(REPO / "news_experiment.db")  # never opened
EXPERIMENT_MD = REPO / "EXPERIMENT.md"
C2_PATHS = (REPO / "reports" / "c2_UNLOCK.json",
            REPO / "reports" / "c2_RUN_ONCE.json", REPO / "reports" / "c2")
_UNPATCHED_CONNECT = sqlite3.connect
NAMES = tuple(synthetic.SCENARIOS)

PRIMARY_BAR = 2.50        # EXPERIMENT.md 9.5: P1 to P4 and E1 to E4
STRENGTH_BAR = 2.24       # 9.10: S1 and S2
REGISTERED_DRAWS = 10_000  # 9.5 bootstrap draws, Amendment 6 permutations
PERM_P_BAR = 0.0125       # 9.3
SE_TOL = 0.05             # bootstrap SE against the linearised SE (seen <= 2%)
EXACT = 1e-9              # relative tolerance for exact sums (fsum both sides)
POS, NEG, NEU = "POSITIVE", "NEGATIVE", "NEUTRAL"
E_STRATUM = {"E1": "S1", "E2": "S2", "E3": "S3", "E4": "S4"}
THIN = ("S3", "S4")
READINGS = ("primary", "sensitivity")
PRIMARIES = ("P1", "P2", "P3", "P4")
# Scenario docstrings that put the permutation p at its floor 2/(n_perm + 1).
P_AT_FLOOR = {"S-EFFECT": ("primary", PRIMARIES),
              "S-STORY": ("primary_story", PRIMARIES)}
CALIBRATION_NOT_REPORTED = {"P1_null_mean"}  # the harness reports no null mean


class RealDatabaseOpened(AssertionError):
    pass


def _db_text(database: Any) -> str:
    text = os.fspath(database) if not isinstance(database, int) else ""
    if isinstance(text, bytes):
        text = text.decode()
    if text.startswith("file:"):
        text = text[5:].split("?", 1)[0]
        while text.startswith("//"):
            text = text[1:]
    return "" if text == ":memory:" else text


def same_file(database: Any, path: str | os.PathLike) -> bool:
    text = _db_text(database)
    if not text:
        return False
    if os.path.realpath(text) == os.path.realpath(path):
        return True
    try:
        a, b = os.stat(text), os.stat(path)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def guarded_connect(database, *args, **kwargs):
    if same_file(database, REPO_REAL_DB):
        raise RealDatabaseOpened(f"test opened the real database: {database}")
    return _UNPATCHED_CONNECT(database, *args, **kwargs)


def install_guards(monkeypatch, tmp_path) -> list[bool]:
    """Never the repository's database; the loader's default paths in tmp.
    Returns the reports/c2* existence flags to compare at teardown."""
    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    fake = tmp_path / "fake_repo"
    monkeypatch.setattr(data, "REAL_DB_PATH", str(fake / "news_experiment.db"))
    monkeypatch.setattr(data, "UNLOCK_PATH", str(fake / "unlock.json"))
    monkeypatch.setattr(data, "RUN_ONCE_PATH", str(fake / "once.json"))
    return [p.exists() for p in C2_PATHS]


@pytest.fixture(autouse=True)
def _guards(monkeypatch, tmp_path):
    before = install_guards(monkeypatch, tmp_path)
    yield
    assert [p.exists() for p in C2_PATHS] == before == [False] * 3


# ------------------------------------------------- independent reference

ROW_COLUMNS = ("id", "run_kind", "state", "outcome_state", "exclusion_reason",
               "excess_1session", "net_bp", "scoring_session", "query_date",
               "judgment", "stratum", "symbol", "formation_date", "sector",
               "sector_source", "strength", "strength_parse_ok",
               "story_group_id")


def _mean(values: list[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def ratio_se(values: list[float], clusters: list[Any]) -> float | None:
    """Linearised SE of the 9.4 ratio under 9.5's cluster resampling:
    sqrt(sum_c (S_c - T n_c)^2) / n. The multinomial bootstrap variance of
    sum_c w_c e_c is exactly sum_c e_c^2 when sum_c e_c = 0."""
    if len(set(clusters)) < 2:
        return None
    t = _mean(values)
    by: dict[Any, list[float]] = {}
    for v, c in zip(values, clusters):
        by.setdefault(c, []).append(v)
    e2 = math.fsum((math.fsum(vs) - t * len(vs)) ** 2 for vs in by.values())
    return math.sqrt(e2) / len(values)


def avg_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    rx, ry = avg_ranks(x), avg_ranks(y)
    mx, my = _mean(rx), _mean(ry)
    dx, dy = [a - mx for a in rx], [b - my for b in ry]
    sxy = math.fsum(a * b for a, b in zip(dx, dy))
    return sxy / math.sqrt(math.fsum(a * a for a in dx)
                           * math.fsum(b * b for b in dy))


def signed(r: dict) -> float:
    """9.4 by hand: +10,000 x excess for POSITIVE, -10,000 x for NEGATIVE."""
    return (1e4 if r["judgment"] == POS else -1e4) * r["excess_1session"]


def _s_star(judged: list[dict]) -> tuple[str, list[str], int, list[str]]:
    """9.7 / D16 by hand: (S*, stale sessions, stale rows, live pending)."""
    order = sorted({r["scoring_session"] for r in judged
                    if r["scoring_session"]})
    idx = {s: i for i, s in enumerate(order)}
    latest = max(idx[r["scoring_session"]] for r in judged
                 if r["outcome_state"] == "resolved" and r["scoring_session"])
    pending = [r["scoring_session"] for r in judged
               if r["outcome_state"] == "pending" and r["scoring_session"]]
    stale = [s for s in pending if latest - idx[s] > 3]
    live = sorted({s for s in pending if latest - idx[s] <= 3})
    s_star = order[idx[live[0]] - 1] if live else order[-1]
    return s_star, sorted(set(stale)), len(stale), live


def _test_ref(rows: list[dict], values: list[float]) -> dict:
    clusters = [r["scoring_session"] for r in rows]
    return {"n": len(rows), "clusters": len(set(clusters)),
            "T": _mean(values), "SE": ratio_se(values, clusters)}


def _s2_ref(rows: list[dict]) -> dict:
    """S2 by hand: mean signed_bp over strengths 4 and 5 minus over 1 and 2,
    with the linearised SE of the difference of the two ratios."""
    top = [r for r in rows if r["strength"] in (4, 5)]
    bot = [r for r in rows if r["strength"] in (1, 2)]
    t_top, t_bot = _mean([signed(r) for r in top]), _mean([signed(r) for r in bot])
    e: dict[str, float] = {r["scoring_session"]: 0.0 for r in rows}
    for r in top:
        e[r["scoring_session"]] += (signed(r) - t_top) / len(top)
    for r in bot:
        e[r["scoring_session"]] -= (signed(r) - t_bot) / len(bot)
    return {"T": t_top - t_bot, "SE": math.sqrt(math.fsum(v * v for v in e.values()))}


def _reading_ref(scored: list[dict], second_half: set[str]) -> dict:
    neg = [r for r in scored if r["judgment"] == NEG]
    subsets = {"P1": scored, "P2": neg,
               "P3": [r for r in scored if r["stratum"] in THIN],
               "P4": [r for r in scored if r["scoring_session"] in second_half]}
    tests = {t: _test_ref(rs, [signed(r) for r in rs])
             for t, rs in subsets.items()}
    for t, stratum in E_STRATUM.items():
        rs = [r for r in scored if r["stratum"] == stratum]
        net = [r for r in rs if r["net_bp"] is not None]
        tests[t] = {**_test_ref(net, [r["net_bp"] for r in net]),
                    "n_scored": len(rs), "n_null": len(rs) - len(net)}
    strength = [r for r in scored if r["strength_parse_ok"] == 1
                and r["strength"] is not None]
    tests["S1"] = {"T": spearman([float(r["strength"]) for r in strength],
                                 [signed(r) for r in strength])}
    tests["S2"] = _s2_ref(strength)
    by: dict[str, set[str]] = {}
    for r in scored:
        by.setdefault(r["scoring_session"], set()).add(r["judgment"])
    n_pos = sum(1 for r in scored if r["judgment"] == POS)
    return {"M": len(scored), "D": len(by), "n_pos": n_pos,
            "n_neg": len(scored) - n_pos,
            "minority": min(n_pos, len(scored) - n_pos) / len(scored),
            "mixed": sum(1 for js in by.values() if len(js) == 2),
            "net_null": sum(1 for r in scored if r["net_bp"] is None),
            "tests": tests}


def reference(rows: list[dict]) -> dict:
    """Everything the checks compare, from raw rows, with no harness code."""
    coll = [r for r in rows if r["run_kind"] == "collection"]
    days: dict[str, list[int]] = {}
    for r in coll:
        tally = days.setdefault(r["query_date"], [0, 0])
        tally[0] += 1
        tally[1] += r["state"] == "source_failed"
    excluded = sorted(d for d, (n, sf) in days.items() if sf / n > 0.20)
    judged = [r for r in coll if r["state"] == "judged"]
    s_star, stale, stale_rows, live = _s_star(judged)

    def all_but_excess(r: dict) -> bool:
        return (r["outcome_state"] == "resolved" and r["exclusion_reason"] == ""
                and bool(r["scoring_session"])
                and r["query_date"] not in excluded
                and r["scoring_session"] <= s_star)

    base = [r for r in judged if all_but_excess(r)]
    gate_rows = [r for r in base if r["excess_1session"] is not None]
    scored = [r for r in gate_rows if r["judgment"] in (POS, NEG)]
    flagged = synthetic._flagged_82(rows)
    sens = [r for r in scored if (r["symbol"], r["formation_date"]) not in flagged]
    sessions = sorted({r["scoring_session"] for r in scored})
    second = set(sessions[len(sessions) - len(sessions) // 2:])
    groups: dict[str, int] = {}
    for r in scored:
        if r["story_group_id"]:
            groups[r["story_group_id"]] = groups.get(r["story_group_id"], 0) + 1
    shared = sum(1 for r in scored if r["story_group_id"]
                 and groups[r["story_group_id"]] >= 2)
    null_resolved = [r for r in judged if r["outcome_state"] == "resolved"
                     and r["excess_1session"] is None]
    p1_values = [signed(r) for r in scored]
    return {
        "excluded": excluded, "s_star": s_star, "stale_sessions": stale,
        "stale_rows": stale_rows, "live_pending": live,
        "gate_rows": len(gate_rows),
        "null_excess_scorable": len(base) - len(gate_rows),
        "null_excess_scorable_directional": sum(
            1 for r in base if r["excess_1session"] is None
            and r["judgment"] in (POS, NEG)),
        "null_excess_resolved": {
            "directional": sum(1 for r in null_resolved if r["judgment"] in (POS, NEG)),
            "neutral": sum(1 for r in null_resolved if r["judgment"] == NEU)},
        "readings": {"primary": _reading_ref(scored, second),
                     "sensitivity": _reading_ref(sens, second)},
        "story_share": shared / len(scored),
        "p1_se_query_date": ratio_se(p1_values, [r["query_date"] for r in scored]),
    }


# ------------------------------------------------------- the scenario cache

class ScenarioCache:
    """Each scenario built once per session; registered-count results
    computed once. Nothing here is computed while a mutant is applied: the
    mutation tests fetch inputs and references before they patch."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.fake_real = base / "fake_repo" / "news_experiment.db"  # absent
        self._store: dict[tuple[str, str], Any] = {}

    def _get(self, kind: str, name: str, make):
        key = (kind, name)
        if key not in self._store:
            self._store[key] = make()
        return self._store[key]

    def db(self, name: str) -> Path:
        def make() -> Path:
            path = self.base / f"{name}.db"
            synthetic.build(name, path)
            return path
        return self._get("db", name, make)

    def reference(self, name: str) -> dict:
        def make() -> dict:
            with data.open_phase("SYNTHETIC", self.db(name),
                                 real_db_path=self.fake_real) as ph:
                return reference(ph.select(ROW_COLUMNS).as_dicts())
        return self._get("ref", name, make)

    def inputs(self, name: str) -> family.Inputs:
        return self._get("inputs", name, lambda: family.load_inputs(
            self.db(name), real_db_path=self.fake_real))

    def registered(self, name: str) -> tuple[dict, dict]:
        def make() -> tuple[dict, dict]:
            assert (K.N_BOOT, K.N_PERM) == (REGISTERED_DRAWS, REGISTERED_DRAWS)
            assert family.CLUSTER_COLUMN == "scoring_session"
            results = family.compute(self.db(name), real_db_path=self.fake_real)
            return results, verdict.decide(results)
        return self._get("registered", name, make)

    def gate_entry(self, name: str) -> dict:
        return self._get("gate", name, lambda: gate.evaluate(
            self.db(name), real_db_path=self.fake_real))


_CACHE: ScenarioCache | None = None


def scenario_cache(tmp_path_factory) -> ScenarioCache:
    global _CACHE
    if _CACHE is None:
        _CACHE = ScenarioCache(tmp_path_factory.mktemp("known_answers"))
    return _CACHE


@pytest.fixture(scope="session")
def cache(tmp_path_factory) -> ScenarioCache:
    return scenario_cache(tmp_path_factory)


# ----------------------------------------------------- the failure checks

def close(got: Any, want: Any, *, rel: float = 0.0, abs_: float = 0.0) -> bool:
    if got is None or want is None:
        return got is None and want is None
    return abs(got - want) <= max(abs_, rel * abs(want))


def _expected(name: str) -> dict:
    return synthetic.SCENARIOS[name].expected


def gate_failures(name: str, entry: dict, ref: dict) -> list[str]:
    """9.8 known answer: pass or fail, failing conditions, C, M, N, S*."""
    exp, f = _expected(name), []
    want_pass = exp["gate"]["status"] == "PASS"
    checks = [("pass", entry["pass"], want_pass),
              ("failing", entry["failing"], list(exp["gate"]["failing"])),
              ("s_star", entry["s_star"], exp["s_star"]),
              ("excluded", sorted(entry["excluded_query_dates"]),
               list(exp["excluded_query_dates"])),
              ("N", entry["N"], ref["gate_rows"]),
              ("M", entry["M"], exp["counts"]["analysis_scored"]),
              ("C", entry["C"], exp["counts"]["analysis_clusters"]),
              ("null_excess", entry["null_excess_count"], ref["null_excess_scorable"])]
    f += [f"gate {k}: {g!r} != {w!r}" for k, g, w in checks if g != w]
    for key in ("sigma", "rho", "k_eff", "required"):
        want = exp["calibration"].get(key)
        if want is not None and not close(entry[key], want, rel=2e-3):
            f.append(f"gate {key}: {entry[key]} != calibration {want}")
    return f


def analysis_failures(name: str, results: dict, ref: dict) -> list[str]:
    """9.1 day rule, 9.7 S* and stale rows, the analysis-set counts."""
    exp, a, f = _expected(name), results["analysis_set"], []
    cut, funnel = a["cutoff"], a["funnel"]
    stale = exp.get("stale_pending_sessions", [])
    checks = [("s_star", cut["s_star"], exp["s_star"]),
              ("s_star ref", ref["s_star"], exp["s_star"]),
              ("excluded", a["day_rule"]["excluded_query_dates"],
               list(exp["excluded_query_dates"])),
              ("excluded ref", ref["excluded"], list(exp["excluded_query_dates"])),
              ("stale sessions", [s for s, _ in cut["stale_pending"]], list(stale)),
              ("stale ref", ref["stale_sessions"], list(stale)),
              ("stale rows", cut["stale_pending_rows"], ref["stale_rows"]),
              ("funnel stale", funnel["pending"]["stale"], ref["stale_rows"]),
              ("funnel gate rows", funnel["gate_rows"], ref["gate_rows"]),
              ("funnel scored", funnel["scored"], ref["readings"]["primary"]["M"])]
    if "stale_pending_rows" in exp:
        checks.append(("stale rows exp", cut["stale_pending_rows"],
                       exp["stale_pending_rows"]))
    if "pending_judged_sessions" in exp:
        checks.append(("live pending ref", ref["live_pending"],
                       list(exp["pending_judged_sessions"])))
        checks.append(("earliest live pending", cut["earliest_nonstale_pending"],
                       exp["pending_judged_sessions"][0]))
    c = exp["counts"]
    for rd, m_key, d_key in (("primary", "analysis_scored", "analysis_clusters"),
                             ("sensitivity", "sensitivity_scored",
                              "sensitivity_clusters")):
        got, r = results["readings"][rd], ref["readings"][rd]
        checks += [(f"{rd} M", got["M"], c[m_key]), (f"{rd} D", got["D"], c[d_key]),
                   (f"{rd} M ref", r["M"], c[m_key]), (f"{rd} D ref", r["D"], c[d_key]),
                   (f"{rd} n_positive", got["null"]["n_positive"], r["n_pos"]),
                   (f"{rd} n_negative", got["null"]["n_negative"], r["n_neg"]),
                   (f"{rd} mixed", got["null"]["n_mixed_clusters"], r["mixed"])]
        if not close(got["null"]["minority_share"], r["minority"], rel=EXACT):
            f.append(f"{rd} minority share {got['null']['minority_share']} "
                     f"!= {r['minority']}")
    checks += [("positives", results["readings"]["primary"]["null"]["n_positive"],
                c["analysis_positive"]),
               ("negatives", results["readings"]["primary"]["null"]["n_negative"],
                c["analysis_negative"])]
    f += [f"{k}: {g!r} != {w!r}" for k, g, w in checks if g != w]
    return f


def null_failures(name: str, results: dict, ref: dict) -> list[str]:
    """D25: a NULL excess_1session or net_bp is excluded and counted, never 0."""
    exp, f = _expected(name), []
    funnel = results["analysis_set"]["funnel"]
    checks = [("null resolved ref", ref["null_excess_resolved"],
               dict(exp["null_excess_resolved_judged"])),
              ("funnel excess null", funnel["dropped_first_reason"][
                  family.DROP_EXCESS_NULL], ref["null_excess_scorable"]),
              ("funnel net null", funnel["scored_net_bp_null"],
               ref["readings"]["primary"]["net_null"])]
    for rd in READINGS:
        tests, r = results["readings"][rd]["tests"], ref["readings"][rd]["tests"]
        checks.append((f"{rd} P1 n_obs", tests["P1"]["n_obs"], r["P1"]["n"]))
        for t in E_STRATUM:
            checks += [(f"{rd} {t} n_scored", tests[t]["n_scored"], r[t]["n_scored"]),
                       (f"{rd} {t} n_null", tests[t]["n_net_bp_null"], r[t]["n_null"]),
                       (f"{rd} {t} n_obs", tests[t]["n_obs"], r[t]["n"])]
    if ref["null_excess_scorable"] == 0:
        f.append("scenario plants no scorable NULL excess row: D25 untested")
    return f + [f"{k}: {g!r} != {w!r}" for k, g, w in checks if g != w]


def verdict_failures(name: str, results: dict, decision: dict) -> list[str]:
    """Statuses, gross readings, rows, null determination, story, 8.2."""
    exp, f = _expected(name), []
    for rd in READINGS:
        e, d = exp["readings"][rd], decision["readings"][rd]
        checks = [("gross", d["gross"]["gross_reading"], e["gross"]),
                  ("statuses", {t: d["statuses"][t] for t in PRIMARIES},
                   dict(e["statuses"])),
                  ("rows", [r["outcome"] for r in d["rows"]], list(e["rows"])),
                  ("null informative", d["null_informative"], e["null_informative"])]
        checks += [(f"{t}", d["statuses"][t], s) for t, s in e["e_statuses"].items()]
        f += [f"{rd} {k}: {g!r} != {w!r}" for k, g, w in checks if g != w]
        reason = exp.get("abstention_reason")
        if e["gross"] == "abstention" and reason is not None:
            want = (verdict.REASON_INTERVAL_ZERO_AND_EFFECT
                    if reason == "interval includes zero and 30 bp"
                    else verdict.REASON_NULL_INTERCEPTED)
            if want not in d["gross"]["reasons"]:
                f.append(f"{rd} abstention reasons {d['gross']['reasons']} lack {want}")
    checks = [("readings disagree", decision["sensitivity_disagreement"]["differs"],
               exp["readings_disagree"]),
              ("story fired", results["story"]["fired"], exp["story_trigger"]),
              ("story comparison fired", decision["story"]["fired"],
               exp["story_trigger"])]
    if exp["story_version"] is not None:
        for rd in READINGS:
            checks.append((f"story {rd}", decision["story"]["statuses"].get(
                verdict.STORY_READINGS[rd]), dict(exp["story_version"][rd])))
        checks.append(("story differences", decision["story"]["differences"] != [],
                       exp["story_versions_disagree"]))
    f += [f"{k}: {g!r} != {w!r}" for k, g, w in checks if g != w]
    if exp["readings_disagree"] and "disagrees" not in decision["summary"]:
        f.append("the summary does not state the 8.2 disagreement")
    return f


def _boot(results: dict, reading: str, test: str) -> dict:
    return results["readings"][reading]["tests"][test]["bootstrap"]


def _interval_failures(label: str, b: dict, r: dict, bar: float,
                       se_tol: float) -> list[str]:
    f = []
    if not close(b["statistic"], r["T"], rel=EXACT, abs_=EXACT):
        f.append(f"{label} T {b['statistic']} != reference {r['T']}")
    if r.get("SE") is None:
        return f
    if not close(b["se"], r["SE"], rel=se_tol):
        f.append(f"{label} SE {b['se']:.4f} vs linearised {r['SE']:.4f} (tol {se_tol})")
    for side, sign in (("upper", 1.0), ("lower", -1.0)):
        if not close(b[side], b["statistic"] + sign * bar * b["se"], rel=EXACT, abs_=EXACT):
            f.append(f"{label} {side} {b[side]:.4f} is not T {sign:+.0f} x {bar} x SE")
        if not close(b[side], r["T"] + sign * bar * r["SE"], abs_=bar * se_tol * r["SE"]):
            f.append(f"{label} {side} {b[side]:.4f} vs reference "
                     f"{r['T'] + sign * bar * r['SE']:.4f} at {bar}")
    return f


def numbers_failures(name: str, results: dict, decision: dict, ref: dict,
                     se_tol: float = SE_TOL) -> list[str]:
    """Every T exact, every SE and interval against the reference, the
    gross interval at 2.50, S1 and S2 at 2.24, the p floors."""
    f = []
    for rd in READINGS:
        r = ref["readings"][rd]["tests"]
        for t in PRIMARIES + tuple(E_STRATUM):
            h = results["readings"][rd]["tests"][t]
            if h["n_clusters"] != r[t]["clusters"]:
                f.append(f"{rd} {t} clusters {h['n_clusters']} != {r[t]['clusters']}")
            if r[t]["n"]:
                f += _interval_failures(f"{rd} {t}", h["bootstrap"], r[t],
                                        PRIMARY_BAR, se_tol)
        f += _interval_failures(f"{rd} S2", _boot(results, rd, "S2"), r["S2"],
                                STRENGTH_BAR, se_tol)
        s1 = _boot(results, rd, "S1")
        if not close(s1["statistic"], r["S1"]["T"], rel=EXACT, abs_=EXACT):
            f.append(f"{rd} S1 {s1['statistic']} != Spearman {r['S1']['T']}")
        if not close(s1["upper"] - s1["statistic"], STRENGTH_BAR * s1["se"], rel=EXACT):
            f.append(f"{rd} S1 half-width is not {STRENGTH_BAR} x SE")
        g, p1 = decision["readings"][rd]["gross"], _boot(results, rd, "P1")
        for side, sign in (("p1_upper", 1.0), ("p1_lower", -1.0)):
            want = p1["statistic"] + sign * PRIMARY_BAR * p1["se"]
            if not close(g[side], want, rel=EXACT, abs_=EXACT):
                f.append(f"{rd} gross {side} {g[side]} != {want} at {PRIMARY_BAR}")
    n_perm = results["settings"]["n_perm"]
    for name_, (rd, tests) in P_AT_FLOOR.items():
        if name_ != name:
            continue
        src = (results["readings"][rd] if rd in READINGS
               else results["story"]["readings"][rd])
        for t in tests:
            p = src["tests"][t]["permutation"]["p"]
            if not close(p, 2.0 / (n_perm + 1), rel=EXACT):
                f.append(f"{rd} {t} p {p} is not at the floor 2/{n_perm + 1}")
    return f + calibration_failures(name, results, ref)


def _p_tol(p: float, n_perm: int) -> float:
    return 10.0 * math.sqrt(max(p, 1.0 / n_perm) * (1.0 - p) / n_perm) + 2.0 / (n_perm + 1)


def calibration_failures(name: str, results: dict, ref: dict) -> list[str]:
    """The fixture author's calibration numbers (independent numpy). Gate
    numbers are checked in gate_failures. An unknown key is a failure."""
    exp = _expected(name)
    tol = exp.get("p1_se_tolerance", SE_TOL)
    p1, s1 = _boot(results, "primary", "P1"), _boot(results, "sensitivity", "P1")
    n_perm = results["settings"]["n_perm"]
    null = results["readings"]["primary"]["null"]
    story = results["story"]["readings"].get("primary_story", {}).get("tests", {})
    zs = [abs(_boot(results, rd, t)["z"]) for rd in READINGS for t in PRIMARIES
          if _boot(results, rd, t)["z"] is not None]
    se_ss = ref["readings"]["primary"]["tests"]["P1"]["SE"]
    t_ref = ref["readings"]["primary"]["tests"]["P1"]["T"]
    got = {
        "P1_T": (p1["statistic"], 2e-3, 0.0), "P1_SE": (p1["se"], 0.0, tol),
        "P1_SE_scoring_session": (p1["se"], 0.0, tol),
        "P1_z": (p1["z"], 0.0, tol), "P1_z_scoring_session": (p1["z"], 0.0, tol),
        "primary_P1_z": (p1["z"], 0.0, tol), "sensitivity_P1_z": (s1["z"], 0.0, tol),
        "P1_upper": (p1["upper"], PRIMARY_BAR * tol * p1["se"], 0.0),
        "sensitivity_P1_upper": (s1["upper"], PRIMARY_BAR * tol * s1["se"], 0.0),
        "P2_z": (_boot(results, "primary", "P2")["z"], 0.0, tol),
        "max_abs_z": (max(zs), 0.0, tol),
        "minority": (null["minority_share"], 1e-4, 0.0),
        "mixed": (null["n_mixed_clusters"], 0.0, 0.0),
        "P4_clusters": (results["readings"]["primary"]["tests"]["P4"]["n_clusters"], 0, 0),
        "story_share": (results["story"]["trigger"]["share"], 1e-4, 0.0),
        "P1_SE_query_date": (ref["p1_se_query_date"], 0.0, tol),
        "P1_z_query_date": (t_ref / ref["p1_se_query_date"], 0.0, tol),
        "se_ratio": (se_ss / ref["p1_se_query_date"], 0.0, tol),
    }
    if story:
        sb = story["P1"]["bootstrap"]
        got.update({"story_P1_SE": (sb["se"], 0.0, tol), "story_P1_z": (sb["z"], 0.0, tol),
                    "story_P1_clusters": (sb["n_clusters"], 0, 0)})
    if "P1_p" in exp["calibration"]:
        p = results["readings"]["primary"]["tests"]["P1"]["permutation"]["p"]
        got["P1_p"] = (p, _p_tol(exp["calibration"]["P1_p"], n_perm), 0.0)
    if "E_z" in exp["calibration"]:
        for t, z in zip(E_STRATUM, exp["calibration"]["E_z"]):
            got[f"E_z {t}"] = (_boot(results, "primary", t)["z"], 0.0, tol)
    f = []
    for key, want in exp["calibration"].items():
        if key in CALIBRATION_NOT_REPORTED or key in ("sigma", "rho", "k_eff",
                                                      "required", "M", "C"):
            continue
        wants = list(zip(E_STRATUM, want)) if key == "E_z" else [(None, want)]
        for t, w in wants:
            k = f"E_z {t}" if t else key
            if k not in got:
                f.append(f"calibration key {k} has no check")
                continue
            value, abs_, rel = got[k]
            if not close(value, w, abs_=abs_, rel=rel):
                f.append(f"calibration {k}: {value} vs {w}")
    return f


def scenario_failures(name: str, results: dict, decision: dict, ref: dict,
                      entry: dict, se_tol: float = SE_TOL) -> list[str]:
    """Every check above, in one list (the mutation tests' kill check)."""
    return (gate_failures(name, entry, ref) + analysis_failures(name, results, ref)
            + null_failures(name, results, ref)
            + verdict_failures(name, results, decision)
            + numbers_failures(name, results, decision, ref, se_tol))


# --------------------------------------------------- per-scenario tests

@pytest.mark.parametrize("name", NAMES)
def test_gate_known_answer(cache, name):
    assert gate_failures(name, cache.gate_entry(name), cache.reference(name)) == []


@pytest.mark.parametrize("name", NAMES)
def test_analysis_set_known_answer(cache, name):
    results, _ = cache.registered(name)
    assert analysis_failures(name, results, cache.reference(name)) == []


@pytest.mark.parametrize("name", NAMES)
def test_null_outcomes_excluded_and_counted(cache, name):
    results, _ = cache.registered(name)
    ref = cache.reference(name)
    assert null_failures(name, results, ref) == []
    # Read as 0, the k scorable directional NULL rows would join P1's n and
    # shrink T by n / (n + k); the harness T is the reference T without them.
    k = ref["null_excess_scorable_directional"]
    p1 = _boot(results, "primary", "P1")
    m = ref["readings"]["primary"]["M"]
    assert k > 0 and p1["n_obs"] == m
    assert close(p1["statistic"], ref["readings"]["primary"]["tests"]["P1"]["T"],
                 rel=EXACT)
    assert not close(p1["statistic"], p1["statistic"] * m / (m + k), rel=1e-6)


@pytest.mark.parametrize("name", NAMES)
def test_verdict_known_answer(cache, name):
    results, decision = cache.registered(name)
    assert verdict_failures(name, results, decision) == []


@pytest.mark.parametrize("name", NAMES)
def test_numbers_known_answer(cache, name):
    results, decision = cache.registered(name)
    assert numbers_failures(name, results, decision, cache.reference(name)) == []


@pytest.mark.parametrize("name", NAMES)
def test_registered_settings(cache, name):
    results, _ = cache.registered(name)
    s = results["settings"]
    assert (s["n_boot"], s["n_perm"], s["cluster_column"]) == (
        REGISTERED_DRAWS, REGISTERED_DRAWS, "scoring_session")
    assert (s["bar_primary_z"], s["bar_strength_z"], s["bar_perm_p"]) == (
        PRIMARY_BAR, STRENGTH_BAR, PERM_P_BAR)


def test_scenario_rows_and_statements_are_verbatim(cache):
    """D24 on the produced verdicts: every row cell and every statement the
    eleven scenarios produce is a byte-for-byte substring of EXPERIMENT.md."""
    text = EXPERIMENT_MD.read_bytes()
    seen = 0
    for name in NAMES:
        _, decision = cache.registered(name)
        for rd in READINGS:
            d = decision["readings"][rd]
            quotes = [r["outcome"] for r in d["rows"]] + [r["verdict"] for r in d["rows"]]
            quotes += list(d["statements"])
            for q in quotes:
                assert q.encode("utf-8") in text, (name, rd, q[:60])
            seen += len(quotes)
    assert seen > 40


# ------------------------------------------------------ the real-path refusal

@pytest.mark.parametrize("how", ["renamed_copy", "symlink", "hardlink"])
def test_scenario_db_at_the_real_path_is_refused_everywhere(cache, tmp_path,
                                                             monkeypatch, how):
    """A stamped scenario database copied to <tmp>/repo/news_experiment.db
    (the real_db_path override) is the live database to every entry point,
    reached by its path, a symlink or a hard link, and sqlite3 never opens
    it; the same bytes under another name stay SYNTHETIC."""
    real = tmp_path / "repo" / "news_experiment.db"
    real.parent.mkdir(parents=True)
    shutil.copy2(cache.db("S-NULL"), real)
    target = real
    if how != "renamed_copy":
        target = tmp_path / "links" / "alias.db"
        target.parent.mkdir()
        (os.symlink if how == "symlink" else os.link)(real, target)
    elsewhere = tmp_path / "elsewhere" / "scenario.db"
    elsewhere.parent.mkdir()
    shutil.copy2(real, elsewhere)
    assert data.classify(elsewhere, real) is data.DbClass.SYNTHETIC

    def refuse(database, *args, **kwargs):
        if same_file(database, real):
            raise RealDatabaseOpened(f"connect on the live path: {database}")
        return guarded_connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", refuse)
    files = {"unlock_path": tmp_path / "u.json", "run_once_path": tmp_path / "m.json"}
    # Valid content (C.1 ruling B2), so the refusal below is the live path's.
    files["unlock_path"].write_text(json.dumps({
        "schema": "c2_unlock/1", "stage": "C.2", "approver": "test",
        "utc_time": "2026-10-20T06:00:00Z",
        "experiment_sha256": data.sha256_file(EXPERIMENT_MD),
        "manifest_sha256": "0" * 64}))
    files["run_once_path"].write_text(json.dumps({
        "schema": "c2_run_once/1",
        "snapshot_sha256": data.sha256_file(real)}))
    assert data.load_unlock(files["unlock_path"])["stage"] == "C.2"
    assert data.classify(target, real) is data.DbClass.LIVE_REAL
    for phase in ("SYNTHETIC", "GATE", "VERDICT"):
        with pytest.raises(data.RealDatabaseRefused):
            with data.open_phase(phase, target, real_db_path=real, **files):
                pass
    log = tmp_path / "gate.jsonl"
    assert gate.run(target, log, real_db_path=real,
                    unlock_path=files["unlock_path"]) == gate.EXIT_REFUSED
    assert not log.exists()
    for fn in (family.compute, family.companion_horizons):
        with pytest.raises(data.RealDatabaseRefused):
            fn(target, real_db_path=real, unlock_path=files["unlock_path"],
               marker_path=files["run_once_path"])

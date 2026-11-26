#!/usr/bin/env python
"""Independent recomputation of the registered 9.8 gate, Stage C.2b, attempt 20261125.

Written from EXPERIMENT.md 9.1, 9.7, 9.8, 10.1 (and the Task 5 / Task 7 ranges)
only. Imports nothing from news_eval. Reads the frozen snapshot read-only and
immutable, and only the allowed columns:
  query_date, scoring_session, state, run_kind, exclusion_reason,
  outcome_state, excess_1session
plus grouped COUNT(*) over the judgment column by scoring_session.
Every SQL statement is appended to verify_gate.sql.log. No row is printed.

Usage:
  verify_gate.py explore   counts of the allowed categorical columns only
  verify_gate.py compute   full computation, writes own_gate.json
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import sys
from collections import Counter, defaultdict
from typing import Any, Iterable, Sequence

REPO = "/home/kiros-li/Documents/GitHub/AiTrader"
SNAP_DIR = REPO + "/reports/c2/snap_20261125"
SNAP = SNAP_DIR + "/news_experiment_snapshot.db"
SNAP_JSON = SNAP_DIR + "/snapshot.json"
BARS = REPO + "/analysis_bars.db"
OUT_DIR = REPO + "/reports/c2/verify_gate_20261125"
SQL_LOG = OUT_DIR + "/verify_gate.sql.log"
OWN_JSON = OUT_DIR + "/own_gate.json"

ALLOWED_COLS = (
    "query_date",
    "scoring_session",
    "state",
    "run_kind",
    "exclusion_reason",
    "outcome_state",
    "excess_1session",
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Registered constants, quoted from the text.
FIRST_SESSION = "2026-07-28"  # 10.1: "counting 2026-07-28 as session 1"
HARD_STOP_ORDINAL = 120  # 10.1: "the 120th trading session"
SOURCE_FAILED_LIMIT = 0.20  # 9.1 / Task 7: "exceeds 20 percent"
STALE_SESSIONS = 3  # 9.7: "more than 3 sessions before the latest resolved session"
FACTOR = 11.156  # 9.8: "11.156 x (sigma / 30)^2 x (1 + (k_eff - 1) x rho)"
DELTA_BP = 30.0  # 9.8
BP = 10000.0  # 9.8: "10,000 x excess_1session"
MIN_CLUSTERS = 60  # 9.8
MIN_M = 1000  # 9.8


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log_sql(db_label: str, sql: str, params: Sequence[Any] = ()) -> None:
    with open(SQL_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"[{now()}] [{db_label}] {' '.join(sql.split())} | params={list(params)!r}\n")


def run(con: sqlite3.Connection, db_label: str, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
    log_sql(db_label, sql, params)
    return con.execute(sql, tuple(params)).fetchall()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def open_snapshot() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{SNAP}?mode=ro&immutable=1", uri=True)


def integrity() -> dict[str, Any]:
    meta = json.load(open(SNAP_JSON, encoding="utf-8"))
    st = os.stat(SNAP)
    sha = sha256_file(SNAP)
    sidecars = [s for s in ("-wal", "-shm", "-journal") if os.path.exists(SNAP + s)]
    out = {
        "snapshot_path": SNAP,
        "sha256_computed": sha,
        "sha256_snapshot_json": meta.get("sha256"),
        "sha256_match": sha == meta.get("sha256"),
        "mode_octal": oct(stat.S_IMODE(st.st_mode)),
        "mode_is_0444": stat.S_IMODE(st.st_mode) == 0o444,
        "bytes": st.st_size,
        "bytes_snapshot_json": meta.get("bytes"),
        "sidecars_present": sidecars,
        "snapshot_json_utc_time": meta.get("utc_time"),
        "snapshot_json_collection_rows_total": meta.get("collection_rows_total"),
        "snapshot_json_collection_query_dates": meta.get("collection_query_dates"),
    }
    out["ok"] = bool(out["sha256_match"] and out["mode_is_0444"] and not sidecars
                     and out["bytes"] == out["bytes_snapshot_json"])
    return out


def load_rows(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every row of news_observation, allowed columns only."""
    sql = "SELECT " + ", ".join(ALLOWED_COLS) + " FROM news_observation"
    return [dict(zip(ALLOWED_COLS, r)) for r in run(con, "snapshot", sql)]


def nonempty(v: Any) -> bool:
    return v is not None and v != ""


def explore() -> None:
    con = open_snapshot()
    cols = run(con, "snapshot", "PRAGMA table_info(news_observation)")
    names = [c[1] for c in cols]
    print("columns:", len(names), "allowed present:", [c for c in ALLOWED_COLS if c in names],
          "judgment present:", "judgment" in names)
    print("declared types:", {c[1]: c[2] for c in cols if c[1] in ALLOWED_COLS})
    rows = load_rows(con)
    print("rows total:", len(rows))
    print("run_kind:", dict(Counter(r["run_kind"] for r in rows)))
    coll = [r for r in rows if r["run_kind"] == "collection"]
    print("collection state:", dict(Counter(r["state"] for r in coll)))
    print("collection state x outcome_state:",
          dict(Counter((r["state"], r["outcome_state"]) for r in coll)))
    jud = [r for r in coll if r["state"] == "judged"]
    print("judged exclusion_reason:", dict(Counter(r["exclusion_reason"] for r in jud)))
    print("judged outcome_state x excl_empty x excess_null x sess_nonempty:",
          dict(Counter((r["outcome_state"], r["exclusion_reason"] == "",
                        r["excess_1session"] is None, nonempty(r["scoring_session"]))
                       for r in jud)))
    print("excess python types (judged):", dict(Counter(type(r["excess_1session"]).__name__ for r in jud)))
    print("non-judged collection with excess not null:",
          sum(1 for r in coll if r["state"] != "judged" and r["excess_1session"] is not None))
    bad_q = sum(1 for r in coll if not (isinstance(r["query_date"], str) and DATE_RE.match(r["query_date"])))
    bad_s = sum(1 for r in jud if nonempty(r["scoring_session"])
                and not (isinstance(r["scoring_session"], str) and DATE_RE.match(r["scoring_session"])))
    print("malformed query_date (collection):", bad_q, "malformed non-empty scoring_session (judged):", bad_s)
    qd = sorted({r["query_date"] for r in coll})
    ss = sorted({r["scoring_session"] for r in jud if nonempty(r["scoring_session"])})
    print("query_dates:", len(qd), qd[0], qd[-1], "| judged scoring_sessions:", len(ss), ss[0], ss[-1])
    print("non-judged collection rows with non-empty scoring_session:",
          dict(Counter(r["state"] for r in coll if r["state"] != "judged" and nonempty(r["scoring_session"]))))
    con.close()


# ----------------------------------------------------------------------------
# 9.1  source_failed day rule (applies to query_date)
# ----------------------------------------------------------------------------
def source_failed_shares(coll: list[dict[str, Any]]) -> dict[str, Any]:
    tot: Counter = Counter()
    sf: Counter = Counter()
    epc: Counter = Counter()
    for r in coll:
        q = r["query_date"]
        tot[q] += 1
        if r["state"] == "source_failed":
            sf[q] += 1
        if r["state"] == "excluded_pre_call":
            epc[q] += 1
    per_day = {}
    for q in sorted(tot):
        den_b = tot[q] - epc[q]
        per_day[q] = {
            "rows": tot[q],
            "source_failed": sf[q],
            "excluded_pre_call": epc[q],
            "share_a": sf[q] / tot[q],
            "share_b": (sf[q] / den_b) if den_b > 0 else None,
        }

    def top(key: str) -> dict[str, Any]:
        best = max((d for d in per_day if per_day[d][key] is not None),
                   key=lambda d: (per_day[d][key], d))
        return {"query_date": best, "share": per_day[best][key],
                "source_failed": per_day[best]["source_failed"],
                "denominator": per_day[best]["rows"] - (per_day[best]["excluded_pre_call"] if key == "share_b" else 0)}

    excl_a = sorted(d for d in per_day if per_day[d]["share_a"] > SOURCE_FAILED_LIMIT)
    excl_b = sorted(d for d in per_day
                    if per_day[d]["share_b"] is not None and per_day[d]["share_b"] > SOURCE_FAILED_LIMIT)
    return {
        "query_dates": len(per_day),
        "source_failed_rows_total": sum(sf.values()),
        "days_with_any_source_failed": {d: {k: per_day[d][k] for k in ("rows", "source_failed", "excluded_pre_call", "share_a", "share_b")}
                                        for d in per_day if per_day[d]["source_failed"] > 0},
        "max_share_a_all_collection_rows": top("share_a"),
        "max_share_b_excluding_excluded_pre_call": top("share_b"),
        "excluded_query_dates_a": excl_a,
        "excluded_query_dates_b": excl_b,
        "any_day_over_0_20_a": bool(excl_a),
        "any_day_over_0_20_b": bool(excl_b),
        "denominators_agree_on_exclusions": excl_a == excl_b,
    }


# ----------------------------------------------------------------------------
# 10.1  hard stop from trading_calendar
# ----------------------------------------------------------------------------
def load_calendar() -> list[str]:
    con = sqlite3.connect(f"file:{BARS}?mode=ro", uri=True)
    try:
        return [r[0] for r in run(con, "analysis_bars", "SELECT date FROM trading_calendar ORDER BY date")]
    finally:
        con.close()


def hard_stop_info(cal: list[str]) -> dict[str, Any]:
    malformed = sum(1 for d in cal if not (isinstance(d, str) and DATE_RE.match(d)))
    weekend = sum(1 for d in cal if isinstance(d, str) and DATE_RE.match(d)
                  and dt.date.fromisoformat(d).weekday() >= 5)
    dup = len(cal) - len(set(cal))
    if FIRST_SESSION not in cal:
        raise SystemExit("FIRST_SESSION not in trading_calendar")
    i0 = cal.index(FIRST_SESSION)
    if i0 + HARD_STOP_ORDINAL - 1 >= len(cal):
        raise SystemExit("trading_calendar does not reach the 120th session")
    hs = cal[i0 + HARD_STOP_ORDINAL - 1]
    return {
        "calendar_dates": len(cal), "calendar_first": cal[0], "calendar_last": cal[-1],
        "calendar_malformed": malformed, "calendar_weekend_dates": weekend, "calendar_duplicates": dup,
        "known_holidays_present": [h for h in ("2026-09-07", "2026-11-26", "2026-12-25", "2027-01-01") if h in cal],
        "first_session": FIRST_SESSION, "ordinal": HARD_STOP_ORDINAL, "hard_stop_session": hs,
    }


# ----------------------------------------------------------------------------
# 9.7  S*
# ----------------------------------------------------------------------------
def cutoff(coll: list[dict[str, Any]], cal: list[str]) -> dict[str, Any]:
    judged = [r for r in coll if r["state"] == "judged"]
    pending_all = [r for r in judged if r["outcome_state"] == "pending"]
    resolved = [r for r in judged if r["outcome_state"] == "resolved" and nonempty(r["scoring_session"])]
    latest_resolved = max((r["scoring_session"] for r in resolved), default=None)
    latest_resolved_any_state = max((r["scoring_session"] for r in coll
                                     if r["outcome_state"] == "resolved" and nonempty(r["scoring_session"])),
                                    default=None)
    cand = {
        "judged_sessions": sorted({r["scoring_session"] for r in judged if nonempty(r["scoring_session"])}),
        "resolved_judged_sessions": sorted({r["scoring_session"] for r in resolved}),
        "all_collection_sessions": sorted({r["scoring_session"] for r in coll if nonempty(r["scoring_session"])}),
    }
    cal_idx = {d: i for i, d in enumerate(cal)}
    data_idx = {d: i for i, d in enumerate(cand["judged_sessions"])}

    def sessions_before(s: str, unit: str) -> int | None:
        """How many sessions s lies before the latest resolved session."""
        idx = cal_idx if unit == "calendar" else data_idx
        if latest_resolved is None or s not in idx or latest_resolved not in idx:
            return None
        return idx[latest_resolved] - idx[s]

    readings = {}
    for pend_label, pend in (("pending_any_exclusion_reason", pending_all),
                             ("pending_exclusion_reason_empty", [r for r in pending_all if r["exclusion_reason"] == ""])):
        for unit in ("calendar", "data"):
            holding, stale = [], []
            for r in pend:
                s = r["scoring_session"]
                if not nonempty(s):
                    holding.append(r)  # cannot be placed: reported, treated as holding at ''
                    continue
                gap = sessions_before(s, unit)
                (stale if (gap is not None and gap > STALE_SESSIONS) else holding).append(r)
            earliest = min((r["scoring_session"] for r in holding if nonempty(r["scoring_session"])), default=None)
            for cand_label, sessions in cand.items():
                ok = [s for s in sessions if earliest is None or s < earliest]
                readings[f"{pend_label}|stale_unit_{unit}|candidates_{cand_label}"] = {
                    "pending_rows": len(pend), "stale_pending_rows": len(stale),
                    "holding_pending_rows": len(holding),
                    "earliest_nonstale_pending_session": earliest,
                    "S_star": ok[-1] if ok else None,
                }
    primary_key = "pending_any_exclusion_reason|stale_unit_calendar|candidates_judged_sessions"
    prim = readings[primary_key]
    distinct = sorted({str(v["S_star"]) for v in readings.values()})
    return {
        "judged_collection_rows": len(judged),
        "judged_outcome_state_counts": dict(Counter(r["outcome_state"] for r in judged)),
        "pending_judged_rows": len(pending_all),
        "pending_judged_rows_with_exclusion_reason": sum(1 for r in pending_all if r["exclusion_reason"] != ""),
        "latest_resolved_session": latest_resolved,
        "latest_resolved_session_any_collection_state": latest_resolved_any_state,
        "stale_pending_rows": prim["stale_pending_rows"],
        "earliest_nonstale_pending_session": prim["earliest_nonstale_pending_session"],
        "S_star": prim["S_star"],
        "primary_reading": primary_key,
        "readings": readings,
        "distinct_S_star_values_across_readings": distinct,
        "readings_split": len(distinct) > 1,
        "judged_sessions_count": len(cand["judged_sessions"]),
        "judged_sessions_first": cand["judged_sessions"][0] if cand["judged_sessions"] else None,
        "judged_sessions_last": cand["judged_sessions"][-1] if cand["judged_sessions"] else None,
        "judged_sessions_not_in_calendar": sum(1 for s in cand["judged_sessions"] if s not in cal_idx),
        "S_star_calendar_ordinal_from_first_session": (
            cal_idx[prim["S_star"]] - cal_idx[FIRST_SESSION] + 1
            if prim["S_star"] in cal_idx and FIRST_SESSION in cal_idx else None),
    }


# ----------------------------------------------------------------------------
# 9.8  the gate
# ----------------------------------------------------------------------------
def other_conditions(r: dict[str, Any], excluded_dates: set[str]) -> bool:
    """Scorable conditions of 9.7 except judgment and except excess not null."""
    return (r["run_kind"] == "collection" and r["state"] == "judged"
            and r["outcome_state"] == "resolved" and r["exclusion_reason"] == ""
            and nonempty(r["scoring_session"]) and r["query_date"] not in excluded_dates)


def anova(groups: dict[str, list[float]], c_for_n0: int | None = None) -> dict[str, Any]:
    """sigma (ddof 1) and the one-way ANOVA ICC of 9.8. Values are already in bp."""
    allx = [x for g in groups.values() for x in g]
    n = len(allx)
    c = len(groups)
    grand = math.fsum(allx) / n
    sst = math.fsum((x - grand) ** 2 for x in allx)
    sigma = math.sqrt(sst / (n - 1))
    means = {k: math.fsum(g) / len(g) for k, g in groups.items()}
    ssb = math.fsum(len(g) * (means[k] - grand) ** 2 for k, g in groups.items())
    ssw = math.fsum((x - means[k]) ** 2 for k, g in groups.items() for x in g)
    msb = ssb / (c - 1)
    msw = ssw / (n - c)
    sum_nc2 = sum(len(g) ** 2 for g in groups.values())
    c_n0 = c if c_for_n0 is None else c_for_n0
    n0 = (n - sum_nc2 / n) / (c_n0 - 1)
    rho_raw = (msb - msw) / (msb + (n0 - 1.0) * msw)
    return {"N": n, "C_G": c, "sigma": sigma, "MSB": msb, "MSW": msw, "n0": n0,
            "C_used_in_n0": c_n0, "sum_nc2": sum_nc2,
            "rho_raw": rho_raw, "rho": max(0.0, rho_raw),
            "_sst": sst, "_ssb": ssb, "_ssw": ssw}


def anova_crosscheck(groups: dict[str, list[float]]) -> dict[str, float]:
    """Second, independent route (numpy, pooled variances) for the same quantities."""
    import numpy as np
    arrs = {k: np.asarray(g, dtype=np.float64) for k, g in groups.items()}
    allx = np.concatenate(list(arrs.values()))
    n, c = allx.size, len(arrs)
    sigma = float(np.std(allx, ddof=1))
    ssw = float(sum(((a - a.mean()) ** 2).sum() for a in arrs.values()))
    sst = float(((allx - allx.mean()) ** 2).sum())
    msw = ssw / (n - c)
    msb = (sst - ssw) / (c - 1)
    nc = np.array([a.size for a in arrs.values()], dtype=np.float64)
    n0 = (n - float((nc ** 2).sum()) / n) / (c - 1)
    rho_raw = (msb - msw) / (msb + (n0 - 1.0) * msw)
    return {"sigma": sigma, "MSB": msb, "MSW": msw, "n0": n0, "rho_raw": rho_raw}


def gate_from(groups: dict[str, list[float]], m_c: dict[str, int], c_for_n0: int | None = None) -> dict[str, Any]:
    a = anova(groups, c_for_n0)
    m_total = sum(m_c.values())
    c_dir = sum(1 for v in m_c.values() if v >= 1)
    k_eff = sum(v * v for v in m_c.values()) / m_total
    required = FACTOR * (a["sigma"] / DELTA_BP) ** 2 * (1.0 + (k_eff - 1.0) * a["rho"])
    out = {k: v for k, v in a.items() if not k.startswith("_")}
    out.update({
        "M": m_total, "C": c_dir, "k_eff": k_eff, "sum_mc2": sum(v * v for v in m_c.values()),
        "Required": required,
        "pass_C_ge_60": c_dir >= MIN_CLUSTERS,
        "pass_M_ge_1000": m_total >= MIN_M,
        "pass_M_ge_Required": m_total >= required,
    })
    out["passes"] = bool(out["pass_C_ge_60"] and out["pass_M_ge_1000"] and out["pass_M_ge_Required"])
    return out


def directional_counts(con: sqlite3.Connection, excluded_dates: list[str], bound: str) -> dict[str, int]:
    """The one allowed count over the judgment column, grouped by scoring_session."""
    not_in = ""
    params: list[Any] = []
    if excluded_dates:
        not_in = " AND query_date NOT IN (" + ",".join("?" for _ in excluded_dates) + ")"
        params.extend(excluded_dates)
    sql = (
        "SELECT scoring_session, COUNT(*) FROM news_observation "
        "WHERE run_kind = 'collection' AND state = 'judged' AND outcome_state = 'resolved' "
        "AND exclusion_reason = '' AND excess_1session IS NOT NULL "
        "AND scoring_session IS NOT NULL AND scoring_session <> ''" + not_in +
        " AND scoring_session <= ? AND judgment IN ('POSITIVE','NEGATIVE') GROUP BY scoring_session"
    )
    params.append(bound)
    return {s: int(k) for s, k in run(con, "snapshot", sql, params)}


def rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1e-300)


def compute() -> None:
    t_start = now()
    integ = integrity()
    if not integ["ok"]:
        raise SystemExit("snapshot integrity check failed: " + json.dumps(integ))
    con = open_snapshot()
    cols = [c[1] for c in run(con, "snapshot", "PRAGMA table_info(news_observation)")]
    rows = load_rows(con)
    coll = [r for r in rows if r["run_kind"] == "collection"]

    s91 = source_failed_shares(coll)
    excluded = s91["excluded_query_dates_a"]  # primary: share over every collection row of the day
    cal = load_calendar()
    hs = hard_stop_info(cal)
    s97 = cutoff(coll, cal)
    s_star = s97["S_star"]
    if s_star is None:
        raise SystemExit("no S* could be determined")
    bound = min(s_star, hs["hard_stop_session"])

    excl_set = set(excluded)
    base = [r for r in rows if other_conditions(r, excl_set)]
    in_set = [r for r in base if r["scoring_session"] <= s_star]
    after_s_star = len(base) - len(in_set)
    restricted = [r for r in in_set if r["scoring_session"] <= hs["hard_stop_session"]]
    dropped_by_hard_stop = len(in_set) - len(restricted)
    null_excess = sum(1 for r in restricted if r["excess_1session"] is None)
    gate_rows = [r for r in restricted if r["excess_1session"] is not None]

    groups: dict[str, list[float]] = defaultdict(list)
    for r in gate_rows:
        groups[r["scoring_session"]].append(BP * float(r["excess_1session"]))
    groups = dict(sorted(groups.items()))
    n_c = {s: len(g) for s, g in groups.items()}

    m_c = directional_counts(con, excluded, bound)
    bad_m = [s for s, v in m_c.items() if s not in n_c or v > n_c[s] or v < 1]
    g = gate_from(groups, m_c)
    xc = anova_crosscheck(groups)
    crosscheck = {k: rel(g[k], xc[k]) for k in xc}
    a_raw = anova(groups)
    sst_identity = rel(a_raw["_sst"], a_raw["_ssb"] + a_raw["_ssw"])

    # Added line 3: C versus C_G
    line3: dict[str, Any] = {"C": g["C"], "C_G": g["C_G"], "C_equals_C_G": g["C"] == g["C_G"]}
    if g["C"] != g["C_G"]:
        alt = gate_from(groups, m_c, c_for_n0=g["C"])
        line3["with_C_G_in_n0"] = {"n0": g["n0"], "rho": g["rho"], "Required": g["Required"], "passes": g["passes"]}
        line3["with_C_in_n0"] = {"n0": alt["n0"], "rho": alt["rho"], "Required": alt["Required"], "passes": alt["passes"]}

    # Added line 5: is the S* cluster final
    coll_rows_qd_eq_s_star = sum(1 for r in coll if r["query_date"] == s_star)
    s_gate_by_qd = dict(sorted(Counter(r["query_date"] for r in gate_rows if r["scoring_session"] == s_star).items()))
    s_judged_by_qd = dict(sorted(Counter(r["query_date"] for r in coll
                                         if r["state"] == "judged" and r["scoring_session"] == s_star).items()))
    line5: dict[str, Any] = {
        "S_star": s_star,
        "collection_rows_with_query_date_eq_S_star": coll_rows_qd_eq_s_star,
        "S_star_cluster_final": coll_rows_qd_eq_s_star > 0,
        "S_star_cluster_gate_rows": n_c.get(s_star, 0),
        "S_star_cluster_gate_rows_by_query_date": s_gate_by_qd,
        "S_star_cluster_judged_rows_by_query_date": s_judged_by_qd,
        "S_star_cluster_directional_rows": m_c.get(s_star, 0),
        "S_star_cluster_directional_rows_by_query_date": (
            {next(iter(s_gate_by_qd)): m_c.get(s_star, 0)} if len(s_gate_by_qd) == 1
            else "not split: the cluster draws on more than one query_date and a per-query_date "
                 "judgment count is outside the one allowed statement shape"),
        "latest_query_date_in_snapshot": max(r["query_date"] for r in coll),
    }
    if not line5["S_star_cluster_final"] and s_star in groups and len(groups) > 2:
        g2 = {s: v for s, v in groups.items() if s != s_star}
        m2 = {s: v for s, v in m_c.items() if s != s_star}
        wo = gate_from(g2, m2)
        line5["NOT_REGISTERED_without_S_star_cluster"] = {
            k: wo[k] for k in ("N", "C_G", "sigma", "n0", "rho_raw", "rho", "M", "C", "k_eff", "Required",
                               "pass_C_ge_60", "pass_M_ge_1000", "pass_M_ge_Required", "passes")}
        line5["pass_decision_differs_without_S_star_cluster"] = wo["passes"] != g["passes"]

    # Reading sensitivity: denominator (b) for 9.1, only when it changes the exclusions
    alt_91 = None
    if not s91["denominators_agree_on_exclusions"]:
        alt_91 = "exclusion sets differ between denominators (a) and (b): see s91; gate computed under (a)"

    out = {
        "schema": "own_gate/20261125",
        "written_by": "GateVerifier-FableXHigh (claude-fable-5-2), own code, no news_eval import",
        "started": t_start,
        "integrity": integ,
        "table": {"columns_in_news_observation": len(cols), "rows_total": len(rows),
                  "run_kind_counts": dict(Counter(r["run_kind"] for r in rows)),
                  "collection_rows": len(coll),
                  "collection_state_counts": dict(Counter(r["state"] for r in coll)),
                  "exclusion_reason_null_rows_collection": sum(1 for r in coll if r["exclusion_reason"] is None)},
        "s91": s91,
        "s91_primary_denominator": "a (every collection row of the query_date)",
        "s91_excluded_query_dates": excluded,
        "s91_note": alt_91,
        "s97": s97,
        "s101": {**hs, "S_star": s_star, "bound_min_S_star_hard_stop": bound,
                 "S_star_before_hard_stop": s_star < hs["hard_stop_session"],
                 "gate_rows_dropped_by_hard_stop_restriction": dropped_by_hard_stop,
                 "rows_after_S_star_meeting_other_conditions": after_s_star},
        "gate": {**g,
                 "null_excess_among_rows_meeting_other_conditions": null_excess,
                 "factor": FACTOR, "delta_bp": DELTA_BP,
                 "n_c": n_c, "m_c": dict(sorted(m_c.items())),
                 "first_cluster": min(n_c), "last_cluster": max(n_c),
                 "clusters_with_zero_directional": sorted(s for s in n_c if m_c.get(s, 0) == 0),
                 "m_c_inconsistent_sessions": bad_m,
                 "Required_with_factor_3.34_squared_NOT_REGISTERED":
                     (2.50 + 0.84) ** 2 * (g["sigma"] / DELTA_BP) ** 2 * (1.0 + (g["k_eff"] - 1.0) * g["rho"])},
        "internal_checks": {"numpy_crosscheck_relative_difference": crosscheck,
                            "sst_equals_ssb_plus_ssw_relative_difference": sst_identity},
        "added_lines": {"line3": line3, "line5": line5},
        "finished": now(),
    }
    if bad_m:
        raise SystemExit("directional counts inconsistent with gate rows: " + repr(bad_m[:5]))
    if max(crosscheck.values()) > 1e-9 or sst_identity > 1e-9:
        raise SystemExit("internal cross-check failed: " + json.dumps(crosscheck))
    con.close()
    with open(OWN_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=False)
        fh.write("\n")
    gg = out["gate"]
    print("integrity ok:", integ["ok"], "| 9.1 excluded:", excluded,
          "| max a:", s91["max_share_a_all_collection_rows"], "| max b:", s91["max_share_b_excluding_excluded_pre_call"])
    print("pending judged:", s97["pending_judged_rows"], "| latest resolved:", s97["latest_resolved_session"],
          "| S*:", s_star, "| split:", s97["readings_split"], "| hard stop:", hs["hard_stop_session"], "| bound:", bound)
    print({k: gg[k] for k in ("N", "C_G", "sigma", "MSB", "MSW", "n0", "rho_raw", "rho", "M", "C", "k_eff",
                              "Required", "pass_C_ge_60", "pass_M_ge_1000", "pass_M_ge_Required", "passes")})
    print("null excess:", null_excess, "| dropped by hard stop:", dropped_by_hard_stop, "| after S*:", after_s_star)
    print("line3:", line3)
    print("line5:", {k: v for k, v in line5.items()})
    print("checks:", out["internal_checks"])
    print("wrote", OWN_JSON)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "explore":
        explore()
    elif mode == "compute":
        compute()
    else:
        raise SystemExit("usage: verify_gate.py explore|compute")

"""GateVerifier-FableXHigh, Stage C.2b, attempt 20261116.

Independent recomputation of the registered 9.8 gate from the frozen snapshot,
written from EXPERIMENT.md 9.1 (842-858), 9.7 and 9.8 (912-958), 10.1
(1072-1087), Task 7 (2475-2484) and Task 5 (2200-2232) only.

Columns read from news_observation: query_date, scoring_session, state,
run_kind, exclusion_reason, outcome_state, excess_1session, plus ONE grouped
count over judgment (m_c). No row is printed. No mean, sum or per-cluster
aggregate of excess_1session is written anywhere: only sigma, MSB, MSW, rho.
Every SQL statement is appended to verify_gate.sql.log before it runs.
"""
import bisect
import datetime
import hashlib
import json
import math
import os
import sqlite3
import stat
import sys
from fractions import Fraction

os.nice(0)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SNAP_DIR = os.path.join(ROOT, "reports", "c2", "snap_20261116")
SNAP = os.path.join(SNAP_DIR, "news_experiment_snapshot.db")
SNAP_JSON = os.path.join(SNAP_DIR, "snapshot.json")
BARS = os.path.join(ROOT, "analysis_bars.db")
LOG = os.path.join(HERE, "verify_gate.sql.log")
OUT = os.path.join(HERE, "own_gate.json")

SESSION_ONE = "2026-07-28"          # 10.1: counted as session 1
HARD_STOP_ORDINAL = 120             # 10.1: the 120th trading session
SOURCE_FAILED_LIMIT = 0.20          # Task 7 / 9.1: share must EXCEED this
STALE_SESSIONS = 3                  # 9.7: more than 3 sessions before
FACTOR_LITERAL = 11.156             # 9.8: the literal registered factor
FACTOR_EXACT = (2.50 + 0.84) ** 2   # 11.1556, reported as an alternate only
DELTA_BP = 30.0
MIN_CLUSTERS = 60
MIN_M = 1000
SCALE = 10000.0


def q(con, sql, params=()):
    with open(LOG, "a") as fh:
        fh.write("%s\t%s\t%s\tparams=%r\n" % (
            datetime.datetime.now().isoformat(timespec="seconds"),
            os.path.basename(sys.argv[0]), " ".join(sql.split()), tuple(params)))
    return con.execute(sql, params).fetchall()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def session_distance(sessions, later, earlier):
    """Number of sessions `earlier` sits before `later` in an ordered list."""
    return bisect.bisect_left(sessions, later) - bisect.bisect_left(sessions, earlier)


out = {"schema": "own_gate/20261116", "verifier": "GateVerifier-FableXHigh"}

# ---------------------------------------------------------------- integrity
manifest = json.load(open(SNAP_JSON))
sha = sha256_file(SNAP)
mode = stat.S_IMODE(os.stat(SNAP).st_mode)
sidecars = [s for s in ("-wal", "-shm", "-journal") if os.path.exists(SNAP + s)]
out["integrity"] = {
    "snapshot_sha256": sha,
    "manifest_sha256_field": manifest.get("sha256"),
    "sha256_matches_manifest": sha == manifest.get("sha256"),
    "file_mode_octal": oct(mode),
    "mode_is_0444": mode == 0o444,
    "sidecars_present": sidecars,
    "bytes": os.path.getsize(SNAP),
    "bytes_match_manifest": os.path.getsize(SNAP) == manifest.get("bytes"),
}
if not (sha == manifest.get("sha256") and mode == 0o444 and not sidecars):
    raise SystemExit("snapshot integrity check failed: %r" % out["integrity"])

con = sqlite3.connect("file:%s?mode=ro&immutable=1" % SNAP, uri=True)

rows_total = q(con, "SELECT COUNT(*) FROM news_observation WHERE run_kind='collection'")[0][0]
out["integrity"]["collection_rows"] = rows_total
out["integrity"]["collection_rows_match_manifest"] = rows_total == manifest.get("collection_rows_total")

# ---------------------------------------------------------------- 9.1
day_state = q(con, "SELECT query_date, state, COUNT(*) FROM news_observation "
                   "WHERE run_kind='collection' GROUP BY query_date, state")
days = {}
for qd, st, n in day_state:
    days.setdefault(qd, {})[st] = n


def share_table(exclude_pre_call):
    table = {}
    for qd, counts in days.items():
        sf = counts.get("source_failed", 0)
        den = sum(counts.values())
        if exclude_pre_call:
            den -= counts.get("excluded_pre_call", 0)
        table[qd] = (sf, den, (sf / den) if den > 0 else None)
    return table


def summarize(table):
    valid = [(v[2], qd) for qd, v in table.items() if v[2] is not None]
    top = max(s for s, _ in valid)
    top_date = min(qd for s, qd in valid if s == top)
    sf, den, _ = table[top_date]
    return {
        "largest_share": top,
        "largest_share_date": top_date,
        "largest_share_source_failed": sf,
        "largest_share_denominator": den,
        "excluded_query_dates": sorted(qd for s, qd in valid if s > SOURCE_FAILED_LIMIT),
        "days_with_zero_denominator": sorted(qd for qd, v in table.items() if v[2] is None),
    }


den_a = summarize(share_table(False))   # every collection row of the query_date
den_b = summarize(share_table(True))    # collection rows other than excluded_pre_call
excluded_dates = den_a["excluded_query_dates"]   # primary reading: denominator (a)
out["s9_1"] = {
    "query_dates": len(days),
    "source_failed_rows_total": sum(c.get("source_failed", 0) for c in days.values()),
    "days_with_any_source_failed": sum(1 for c in days.values() if c.get("source_failed", 0) > 0),
    "denominator_a_all_collection_rows": den_a,
    "denominator_b_without_excluded_pre_call": den_b,
    "excluded_sets_agree": den_a["excluded_query_dates"] == den_b["excluded_query_dates"],
    "any_day_above_0_20": bool(den_a["excluded_query_dates"] or den_b["excluded_query_dates"]),
    "primary_excluded_query_dates": excluded_dates,
    "primary_excluded_count": len(excluded_dates),
}

# ---------------------------------------------------------------- calendar (10.1)
bars = sqlite3.connect("file:%s?mode=ro" % BARS, uri=True)
cal = [r[0] for r in q(bars, "SELECT date FROM trading_calendar ORDER BY date")]
bars.close()
cal_ok_format = all(isinstance(d, str) and len(d) == 10 for d in cal)
weekend_dates = [d for d in cal if datetime.date.fromisoformat(d).weekday() >= 5] if cal_ok_format else None
if SESSION_ONE not in cal:
    raise SystemExit("trading_calendar does not contain %s" % SESSION_ONE)
i1 = cal.index(SESSION_ONE)
if i1 + HARD_STOP_ORDINAL - 1 >= len(cal):
    raise SystemExit("trading_calendar ends before the 120th session")
hard_stop = cal[i1 + HARD_STOP_ORDINAL - 1]
out["s10_1_calendar"] = {
    "calendar_rows": len(cal),
    "calendar_first": cal[0],
    "calendar_last": cal[-1],
    "duplicates": len(cal) - len(set(cal)),
    "iso_format_ok": cal_ok_format,
    "weekend_dates": len(weekend_dates) if weekend_dates is not None else None,
    "session_1": SESSION_ONE,
    "hard_stop_session": hard_stop,
}

# ---------------------------------------------------------------- 9.7 S*
grid = q(con, "SELECT run_kind, state, outcome_state, COUNT(*), MAX(scoring_session), "
              "SUM(scoring_session IS NULL OR scoring_session='') "
              "FROM news_observation GROUP BY run_kind, state, outcome_state")
jc = [(st, os_, n, mx, empt) for rk, st, os_, n, mx, empt in grid if rk == "collection"]
judged = [r for r in jc if r[0] == "judged"]
latest_resolved_judged = max((r[3] for r in judged if r[1] == "resolved" and r[3]), default=None)
latest_resolved_any_collection = max((r[3] for r in jc if r[1] == "resolved" and r[3]), default=None)
latest_session_judged = max((r[3] for r in judged if r[3]), default=None)
latest_session_collection = max((r[3] for r in jc if r[3]), default=None)
latest_session_all_rows = max((r[4] for r in grid if r[4]), default=None)

pending = q(con, "SELECT scoring_session, exclusion_reason, COUNT(*) FROM news_observation "
                 "WHERE run_kind='collection' AND state='judged' AND outcome_state='pending' "
                 "GROUP BY scoring_session, exclusion_reason")
pending_total = sum(n for _, _, n in pending)
pending_no_reason = sum(n for _, er, n in pending if er == "")
pending_with_reason = pending_total - pending_no_reason
pending_empty_session = sum(n for s, _, n in pending if not s)

data_sessions = [r[0] for r in q(
    con, "SELECT DISTINCT scoring_session FROM news_observation "
         "WHERE run_kind='collection' AND state='judged' AND scoring_session IS NOT NULL "
         "AND scoring_session<>'' ORDER BY scoring_session")]
sessions_not_in_calendar = [s for s in data_sessions if s not in set(cal)]


def s_star(unit, count_excluded_rows, latest_resolved):
    """S* under one reading. unit: 'calendar' or 'data'."""
    sess = cal if unit == "calendar" else data_sessions
    rows = [(s, n) for s, er, n in pending if s and (count_excluded_rows or er == "")]
    stale = sum(n for s, n in rows
                if latest_resolved and session_distance(sess, latest_resolved, s) > STALE_SESSIONS)
    live = sorted(s for s, n in rows
                  if not (latest_resolved and session_distance(sess, latest_resolved, s) > STALE_SESSIONS))
    earliest = live[0] if live else None
    if earliest is None:
        star = latest_session_judged
    else:
        before = [s for s in data_sessions if s < earliest]
        star = before[-1] if before else None
    return {"s_star": star, "stale_pending_rows": stale,
            "earliest_non_stale_pending_session": earliest,
            "pending_rows_counted": sum(n for _, n in rows)}


readings = {}
for unit in ("calendar", "data"):
    for cnt in (True, False):
        key = "unit=%s|rows_with_exclusion_reason_%s" % (unit, "count" if cnt else "ignored")
        readings[key] = s_star(unit, cnt, latest_resolved_judged)
star_values = sorted({str(v["s_star"]) for v in readings.values()})
primary = readings["unit=calendar|rows_with_exclusion_reason_count"]   # literal: any judged collection row
S_STAR = primary["s_star"]
if S_STAR is None:
    raise SystemExit("S* is undefined under the primary reading")
out["s9_7"] = {
    "judged_collection_rows_by_outcome_state": {r[1]: r[2] for r in judged},
    "pending_judged_collection_rows": pending_total,
    "pending_with_empty_exclusion_reason": pending_no_reason,
    "pending_with_exclusion_reason": pending_with_reason,
    "pending_with_empty_scoring_session": pending_empty_session,
    "latest_resolved_session": latest_resolved_judged,
    "latest_resolved_session_any_collection_state": latest_resolved_any_collection,
    "latest_scoring_session_judged_collection": latest_session_judged,
    "latest_scoring_session_any_collection_row": latest_session_collection,
    "latest_scoring_session_any_row": latest_session_all_rows,
    "stale_pending_rows": primary["stale_pending_rows"],
    "earliest_non_stale_pending_session": primary["earliest_non_stale_pending_session"],
    "s_star": S_STAR,
    "readings": readings,
    "s_star_distinct_values_across_readings": star_values,
    "s_star_split": len(star_values) > 1,
    "distinct_scoring_sessions_judged_collection": len(data_sessions),
    "scoring_sessions_not_in_trading_calendar": sessions_not_in_calendar,
    "non_judged_collection_rows_with_outcome_pending": sum(r[2] for r in jc if r[0] != "judged" and r[1] == "pending"),
}

BOUND = min(S_STAR, hard_stop)
out["s10_1_bound"] = {
    "s_star": S_STAR,
    "hard_stop_session": hard_stop,
    "bound_min_s_star_hard_stop": BOUND,
    "s_star_on_or_after_hard_stop": S_STAR >= hard_stop,
    "hard_stop_binds": hard_stop < S_STAR,
}

# ---------------------------------------------------------------- 9.8 gate rows
BASE = ("run_kind='collection' AND state='judged' AND outcome_state='resolved' "
        "AND exclusion_reason=''")
SESS_OK = "scoring_session IS NOT NULL AND scoring_session<>''"
if excluded_dates:
    QD_OK = "query_date NOT IN (%s)" % ",".join("?" * len(excluded_dates))
    qd_params = tuple(excluded_dates)
else:
    QD_OK = "1=1"
    qd_params = ()

n_base = q(con, "SELECT COUNT(*) FROM news_observation WHERE " + BASE)[0][0]
n_empty_session = q(con, "SELECT COUNT(*) FROM news_observation WHERE " + BASE +
                    " AND NOT (" + SESS_OK + ")")[0][0]
n_on_excluded_dates = q(con, "SELECT COUNT(*) FROM news_observation WHERE " + BASE + " AND " + SESS_OK +
                        " AND NOT (" + QD_OK + ")", qd_params)[0][0]
n_null_excess = q(con, "SELECT COUNT(*) FROM news_observation WHERE " + BASE + " AND " + SESS_OK +
                  " AND " + QD_OK + " AND scoring_session<=? AND excess_1session IS NULL",
                  qd_params + (BOUND,))[0][0]
n_unbounded = q(con, "SELECT COUNT(*) FROM news_observation WHERE " + BASE + " AND " + SESS_OK +
                " AND " + QD_OK + " AND excess_1session IS NOT NULL", qd_params)[0][0]
n_after_s_star = q(con, "SELECT COUNT(*) FROM news_observation WHERE " + BASE + " AND " + SESS_OK +
                   " AND " + QD_OK + " AND excess_1session IS NOT NULL AND scoring_session>?",
                   qd_params + (S_STAR,))[0][0]
n_after_hard_stop = q(con, "SELECT COUNT(*) FROM news_observation WHERE " + BASE + " AND " + SESS_OK +
                      " AND " + QD_OK + " AND excess_1session IS NOT NULL AND scoring_session>?",
                      qd_params + (hard_stop,))[0][0]
n_after_bound = q(con, "SELECT COUNT(*) FROM news_observation WHERE " + BASE + " AND " + SESS_OK +
                  " AND " + QD_OK + " AND excess_1session IS NOT NULL AND scoring_session>?",
                  qd_params + (BOUND,))[0][0]

GATE_WHERE = (BASE + " AND excess_1session IS NOT NULL AND " + SESS_OK + " AND " + QD_OK +
              " AND scoring_session<=?")
gate_params = qd_params + (BOUND,)
gate = q(con, "SELECT scoring_session, excess_1session FROM news_observation WHERE " + GATE_WHERE,
         gate_params)

N = len(gate)
clusters = {}
for sess, ex in gate:
    if not isinstance(ex, float):
        raise SystemExit("non-real excess_1session in a gate row")
    if not math.isfinite(ex):
        raise SystemExit("non-finite excess_1session in a gate row")
    clusters.setdefault(sess, []).append(ex)
C_G = len(clusters)
n_c = {s: len(v) for s, v in clusters.items()}
sum_nc2 = sum(v * v for v in n_c.values())

# ---- float pipeline (math.fsum), x = 10,000 * excess_1session
xs = {s: [SCALE * e for e in v] for s, v in clusters.items()}
allx = [x for v in xs.values() for x in v]
grand = math.fsum(allx) / N
sst = math.fsum((x - grand) ** 2 for x in allx)
sigma = math.sqrt(sst / (N - 1))
cmean = {s: math.fsum(v) / len(v) for s, v in xs.items()}
ssb = math.fsum(len(v) * (cmean[s] - grand) ** 2 for s, v in xs.items())
ssw = math.fsum((x - cmean[s]) ** 2 for s, v in xs.items() for x in v)
MSB = ssb / (C_G - 1)
MSW = ssw / (N - C_G)

# ---- exact rational pipeline as a self-check on the floats
fx = {s: [Fraction(10000) * Fraction(e) for e in v] for s, v in clusters.items()}
f_all = [x for v in fx.values() for x in v]
f_grand = sum(f_all, Fraction(0)) / N
f_sst = sum(((x - f_grand) ** 2 for x in f_all), Fraction(0))
f_cmean = {s: sum(v, Fraction(0)) / len(v) for s, v in fx.items()}
f_ssb = sum((len(v) * (f_cmean[s] - f_grand) ** 2 for s, v in fx.items()), Fraction(0))
f_ssw = sum(((x - f_cmean[s]) ** 2 for s, v in fx.items() for x in v), Fraction(0))
f_msb = f_ssb / (C_G - 1)
f_msw = f_ssw / (N - C_G)
f_sigma = math.sqrt(f_sst / (N - 1))


def rel(a, b):
    a = float(a)
    b = float(b)
    if a == b:
        return 0.0
    return abs(a - b) / max(abs(a), abs(b))


# ---- optional third check with numpy
np_check = None
try:
    import numpy as np
    arr = np.asarray(allx, dtype=np.float64)
    np_check = {"sigma_rel_diff": rel(float(arr.std(ddof=1)), sigma), "numpy": np.__version__}
except Exception as exc:  # numpy is optional here
    np_check = {"unavailable": repr(exc)}

# ---------------------------------------------------------------- m_c, M, C, k_eff
mc_rows = q(con, "SELECT scoring_session, COUNT(*) FROM news_observation WHERE " + GATE_WHERE +
            " AND judgment IN ('POSITIVE','NEGATIVE') GROUP BY scoring_session", gate_params)
m_c = {s: n for s, n in mc_rows if n > 0}
M = sum(m_c.values())
C = len(m_c)
k_eff = sum(v * v for v in m_c.values()) / M
m_c_outside_gate_clusters = sorted(s for s in m_c if s not in n_c)
m_c_exceeds_n_c = sorted(s for s in m_c if s in n_c and m_c[s] > n_c[s])


def rho_block(c_for_n0, msb, msw):
    n0 = (N - sum_nc2 / N) / (c_for_n0 - 1)
    raw = (msb - msw) / (msb + (n0 - 1) * msw)
    return n0, raw, max(0.0, raw)


def required(factor, sig, keff, rho):
    return factor * (sig / DELTA_BP) ** 2 * (1 + (keff - 1) * rho)


n0, rho_raw, rho = rho_block(C_G, MSB, MSW)            # primary: the ANOVA's own cluster count
n0_c, rho_raw_c, rho_c = rho_block(C, MSB, MSW)        # alternate: the symbol C read as directional clusters
req = required(FACTOR_LITERAL, sigma, k_eff, rho)
req_c = required(FACTOR_LITERAL, sigma, k_eff, rho_c)
req_exact_factor = required(FACTOR_EXACT, sigma, k_eff, rho)

f_n0 = (Fraction(N) - Fraction(sum_nc2, N)) / (C_G - 1)
f_rho_raw = (f_msb - f_msw) / (f_msb + (f_n0 - 1) * f_msw)

cond_c = C >= MIN_CLUSTERS
cond_m = M >= MIN_M
cond_req = M >= req

out["s9_8"] = {
    "rows_base_conditions": n_base,
    "rows_dropped_empty_scoring_session": n_empty_session,
    "rows_dropped_on_9_1_excluded_dates": n_on_excluded_dates,
    "null_excess_among_rows_meeting_other_conditions": n_null_excess,
    "rows_before_session_bound": n_unbounded,
    "rows_after_s_star": n_after_s_star,
    "rows_after_hard_stop": n_after_hard_stop,
    "rows_dropped_by_bound": n_after_bound,
    "N": N,
    "C_G": C_G,
    "sum_n_c_squared": sum_nc2,
    "n_c_min": min(n_c.values()),
    "n_c_max": max(n_c.values()),
    "gate_first_session": min(n_c),
    "gate_last_session": max(n_c),
    "sigma": sigma,
    "MSB": MSB,
    "MSW": MSW,
    "n0": n0,
    "rho_raw": rho_raw,
    "rho": rho,
    "M": M,
    "C": C,
    "k_eff": k_eff,
    "sum_m_c_squared": sum(v * v for v in m_c.values()),
    "m_c_min": min(m_c.values()),
    "m_c_max": max(m_c.values()),
    "C_equals_C_G": C == C_G,
    "gate_clusters_without_directional_row": sorted(s for s in n_c if s not in m_c),
    "m_c_sessions_outside_gate_clusters": m_c_outside_gate_clusters,
    "m_c_exceeds_n_c_sessions": m_c_exceeds_n_c,
    "factor": FACTOR_LITERAL,
    "required": req,
    "cond_C_ge_60": cond_c,
    "cond_M_ge_1000": cond_m,
    "cond_M_ge_required": cond_req,
    "gate_pass": bool(cond_c and cond_m and cond_req),
    "alternate_n0_with_C_directional": {"n0": n0_c, "rho_raw": rho_raw_c, "rho": rho_c, "required": req_c,
                                        "cond_M_ge_required": M >= req_c},
    "alternate_factor_11_1556": {"factor": FACTOR_EXACT, "required": req_exact_factor,
                                 "cond_M_ge_required": M >= req_exact_factor},
    "n_c": dict(sorted(n_c.items())),
    "m_c": dict(sorted(m_c.items())),
}
out["self_check"] = {
    "sst_vs_ssb_plus_ssw_rel_diff": rel(sst, ssb + ssw),
    "exact_vs_float_rel_diff": {
        "sigma": rel(f_sigma, sigma),
        "MSB": rel(f_msb, MSB),
        "MSW": rel(f_msw, MSW),
        "n0": rel(f_n0, n0),
        "rho_raw": rel(f_rho_raw, rho_raw),
    },
    "numpy": np_check,
}
out["written_at_local"] = datetime.datetime.now().isoformat(timespec="seconds")

tmp = OUT + ".tmp"
with open(tmp, "w") as fh:
    json.dump(out, fh, indent=1, sort_keys=False)
    fh.write("\n")
os.replace(tmp, OUT)

# short console summary: counts, dates, booleans and the gate reals only
s = out["s9_8"]
print("integrity ok sha=%s.. rows=%d" % (sha[:12], rows_total))
print("9.1 excluded=%d max_a=%.6f@%s max_b=%.6f@%s" % (
    len(excluded_dates), den_a["largest_share"], den_a["largest_share_date"],
    den_b["largest_share"], den_b["largest_share_date"]))
print("9.7 pending=%d stale=%d earliest_pending=%s latest_resolved=%s S*=%s split=%s" % (
    pending_total, primary["stale_pending_rows"], primary["earliest_non_stale_pending_session"],
    latest_resolved_judged, S_STAR, out["s9_7"]["s_star_split"]))
print("10.1 hard_stop=%s bound=%s dropped=%d" % (hard_stop, BOUND, n_after_bound))
print("9.8 N=%d C_G=%d null_excess=%d M=%d C=%d" % (N, C_G, n_null_excess, M, C))
print("    sigma=%.12g MSB=%.12g MSW=%.12g n0=%.12g" % (sigma, MSB, MSW, n0))
print("    rho_raw=%.12g rho=%.12g k_eff=%.12g required=%.12g" % (rho_raw, rho, k_eff, req))
print("    conds C>=60:%s M>=1000:%s M>=Req:%s pass:%s" % (cond_c, cond_m, cond_req, s["gate_pass"]))
print("self-check", json.dumps(out["self_check"]))

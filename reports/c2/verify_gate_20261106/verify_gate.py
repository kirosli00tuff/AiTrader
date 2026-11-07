#!/usr/bin/env python3
"""GateVerifier-FableXHigh, Stage C.2b, attempt 20261106.

Independent recomputation of the EXPERIMENT.md 9.8 gate from the frozen
snapshot, written from the registered text alone (9.1 lines 842-858, 9.7 and
9.8 lines 912-958, 10.1 lines 1072-1087, Task 7 rule lines 2475-2484, Task 5
power arithmetic lines 2200-2232). Imports nothing from news_eval. Written
before reports/c2/gate_log.jsonl or anything under news_eval/ was opened.

Column rule: from news_observation only query_date, scoring_session, state,
run_kind, exclusion_reason, outcome_state, excess_1session are selected, plus
exactly one COUNT over the judgment column grouped by scoring_session. No row
is ever printed. Every SQL statement is appended to verify_gate.sql.log.
"""
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import time

import numpy as np

ROOT = "/home/kiros-li/Documents/GitHub/AiTrader"
SNAP = f"{ROOT}/reports/c2/snap_20261106/news_experiment_snapshot.db"
SNAP_JSON = f"{ROOT}/reports/c2/snap_20261106/snapshot.json"
BARS = f"{ROOT}/analysis_bars.db"
OUT_DIR = f"{ROOT}/reports/c2/verify_gate_20261106"
OUT_JSON = f"{OUT_DIR}/own_gate.json"
SQL_LOG = f"{OUT_DIR}/verify_gate.sql.log"

ALLOWED_COLS = {
    "query_date", "scoring_session", "state", "run_kind",
    "exclusion_reason", "outcome_state", "excess_1session",
}

# Registered constants, with the line of EXPERIMENT.md they come from.
Z_CONST = 11.156                      # 9.8: "11.156 is (2.50 + 0.84)^2 from Task 5"
Z_CONST_EXACT = (2.50 + 0.84) ** 2    # 11.1556, sensitivity only
DELTA_BP = 30.0                       # 9.8: (sigma / 30)^2
SOURCE_FAILED_LIMIT = 0.20            # Task 7: "exceeds 20 percent" (strict)
STALE_SESSIONS = 3                    # 9.7: "more than 3 sessions before" (strict)
HARD_STOP_INDEX = 120                 # 10.1: 120th trading session
HARD_STOP_SESSION_1 = "2026-07-28"    # 10.1: counting 2026-07-28 as session 1
MIN_CLUSTERS = 60                     # 9.8: C at least 60
MIN_M = 1000                          # 9.8: M at least 1,000
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def log_sql(db_label, sql, params=()):
    with open(SQL_LOG, "a") as fh:
        fh.write(f"-- {time.strftime('%Y-%m-%dT%H:%M:%S%z')} [{db_label}]\n")
        fh.write(sql.strip() + "\n")
        if params:
            fh.write(f"-- params: {list(params)}\n")
        fh.write("\n")


def run(conn, db_label, sql, params=()):
    log_sql(db_label, sql, params)
    return conn.execute(sql, params).fetchall()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_integrity():
    with open(SNAP_JSON) as fh:
        meta = json.load(fh)
    sha = sha256_of(SNAP)
    st = os.stat(SNAP)
    mode = stat.S_IMODE(st.st_mode)
    sidecars = [SNAP + s for s in ("-wal", "-shm", "-journal")]
    present = [s for s in sidecars if os.path.exists(s)]
    ok = (sha == meta["sha256"] and mode == 0o444 and not present
          and st.st_size == meta["bytes"])
    return {
        "snapshot_path": SNAP,
        "sha256_computed": sha,
        "sha256_recorded": meta["sha256"],
        "sha256_match": sha == meta["sha256"],
        "bytes_computed": st.st_size,
        "bytes_recorded": meta["bytes"],
        "file_mode_octal": oct(mode),
        "mode_is_0444": mode == 0o444,
        "sidecars_present": present,
        "integrity_ok": ok,
    }, meta


def open_snapshot():
    uri = f"file:{SNAP}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def open_bars():
    uri = f"file:{BARS}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def main():
    t_start = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if os.path.exists(SQL_LOG):
        os.remove(SQL_LOG)
    if os.path.exists(OUT_JSON):
        os.remove(OUT_JSON)

    integrity, meta = check_integrity()
    if not integrity["integrity_ok"]:
        print("INTEGRITY FAILURE", json.dumps(integrity, indent=1))
        sys.exit(2)

    out = {"worker": "GateVerifier-FableXHigh", "model": "claude-fable-5-1",
           "attempt": "20261106", "started": t_start,
           "integrity": integrity, "readings": [], "warnings": []}

    con = open_snapshot()
    S = "snapshot"

    # ---- schema check: the allowed columns exist -------------------------------
    cols = run(con, S, "PRAGMA table_info(news_observation)")
    names = {r[1] for r in cols}
    missing = sorted(ALLOWED_COLS - names)
    if missing:
        print("MISSING COLUMNS", missing)
        sys.exit(2)
    out["schema"] = {"news_observation_column_count": len(cols),
                     "allowed_columns_present": True,
                     "judgment_column_present": "judgment" in names}

    # ---- vocabularies of the allowed categorical columns -----------------------
    out["vocab"] = {}
    out["vocab"]["run_kind"] = dict(run(
        con, S, "SELECT run_kind, COUNT(*) FROM news_observation GROUP BY run_kind"))
    out["vocab"]["state_collection"] = dict(run(
        con, S, "SELECT state, COUNT(*) FROM news_observation "
                "WHERE run_kind='collection' GROUP BY state"))
    out["vocab"]["outcome_state_judged_collection"] = dict(run(
        con, S, "SELECT outcome_state, COUNT(*) FROM news_observation "
                "WHERE run_kind='collection' AND state='judged' GROUP BY outcome_state"))
    out["vocab"]["exclusion_reason_class_judged_collection"] = dict(run(
        con, S, "SELECT CASE WHEN exclusion_reason IS NULL THEN 'NULL' "
                "WHEN exclusion_reason='' THEN 'EMPTY' ELSE 'NONEMPTY' END AS cls, COUNT(*) "
                "FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY cls"))
    out["vocab"]["scoring_session_class_judged_collection"] = dict(run(
        con, S, "SELECT CASE WHEN scoring_session IS NULL THEN 'NULL' "
                "WHEN scoring_session='' THEN 'EMPTY' ELSE 'SET' END AS cls, COUNT(*) "
                "FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY cls"))

    # ---- 9.1 / Task 7: the 20 percent source_failed day rule on query_date -----
    # Reading: "a day's queries" = every collection row of that query_date,
    # whatever its state. Sensitivity: the denominator without excluded_pre_call.
    rows = run(con, S, "SELECT query_date, state, COUNT(*) FROM news_observation "
                       "WHERE run_kind='collection' GROUP BY query_date, state")
    by_day = {}
    for qd, st_, n in rows:
        d = by_day.setdefault(qd, {"total": 0, "source_failed": 0, "excluded_pre_call": 0})
        d["total"] += n
        if st_ == "source_failed":
            d["source_failed"] += n
        if st_ == "excluded_pre_call":
            d["excluded_pre_call"] += n
    excluded_days = []
    excluded_days_alt = []
    max_share, max_share_day = 0.0, None
    max_share_alt, max_share_day_alt = 0.0, None
    for qd in sorted(by_day):
        d = by_day[qd]
        share = d["source_failed"] / d["total"] if d["total"] else 0.0
        denom_alt = d["total"] - d["excluded_pre_call"]
        share_alt = d["source_failed"] / denom_alt if denom_alt else 0.0
        if share > SOURCE_FAILED_LIMIT:
            excluded_days.append(qd)
        if share_alt > SOURCE_FAILED_LIMIT:
            excluded_days_alt.append(qd)
        if share > max_share:
            max_share, max_share_day = share, qd
        if share_alt > max_share_alt:
            max_share_alt, max_share_day_alt = share_alt, qd
    out["day_rule_9_1"] = {
        "query_dates_collection": len(by_day),
        "collection_rows_total": sum(d["total"] for d in by_day.values()),
        "source_failed_rows_total": sum(d["source_failed"] for d in by_day.values()),
        "limit_strict_greater_than": SOURCE_FAILED_LIMIT,
        "excluded_query_dates": excluded_days,
        "excluded_query_date_count": len(excluded_days),
        "max_source_failed_share": max_share,
        "max_source_failed_share_query_date": max_share_day,
        "max_share_numerator_denominator": [by_day[max_share_day]["source_failed"],
                                            by_day[max_share_day]["total"]] if max_share_day else None,
        "sensitivity_denominator_without_excluded_pre_call": {
            "excluded_query_dates": excluded_days_alt,
            "max_source_failed_share": max_share_alt,
            "max_source_failed_share_query_date": max_share_day_alt,
        },
    }
    out["readings"].append(
        "9.1/Task 7 denominator: all collection rows of the query_date (every state). "
        "Sensitivity with excluded_pre_call removed from the denominator is also reported.")

    # ---- trading calendar (hard stop, 10.1) ------------------------------------
    bars = open_bars()
    cal = [r[0] for r in run(bars, "analysis_bars", "SELECT date FROM trading_calendar ORDER BY date")]
    bars.close()
    bad_cal = [d for d in cal if not isinstance(d, str) or not ISO_DATE.match(d)]
    if bad_cal:
        out["warnings"].append(f"trading_calendar has {len(bad_cal)} non-ISO dates; first: {bad_cal[0]!r}")
    cal_index = {d: i for i, d in enumerate(cal)}
    if HARD_STOP_SESSION_1 not in cal_index:
        print("session 1 not in trading_calendar")
        sys.exit(2)
    i1 = cal_index[HARD_STOP_SESSION_1]
    hard_stop = cal[i1 + HARD_STOP_INDEX - 1]
    out["hard_stop_10_1"] = {
        "trading_calendar_rows": len(cal),
        "calendar_first": cal[0], "calendar_last": cal[-1],
        "session_1": HARD_STOP_SESSION_1,
        "hard_stop_session_index": HARD_STOP_INDEX,
        "hard_stop_session": hard_stop,
        "calendar_is_strictly_increasing": all(cal[i] < cal[i + 1] for i in range(len(cal) - 1)),
    }

    # ---- 9.7 cutoff S* --------------------------------------------------------
    # Judged collection rows by (scoring_session, outcome_state, exclusion class).
    rows = run(con, S,
               "SELECT scoring_session, outcome_state, "
               "CASE WHEN exclusion_reason='' THEN 1 ELSE 0 END AS unexcluded, COUNT(*) "
               "FROM news_observation WHERE run_kind='collection' AND state='judged' "
               "GROUP BY scoring_session, outcome_state, unexcluded")
    sess_rows = {}          # session -> {outcome_state -> count} (all judged collection rows)
    sess_rows_unexcl = {}   # same, exclusion_reason = '' only
    bad_sess = 0
    for ss, os_, unex, n in rows:
        if ss is None or ss == "" or not ISO_DATE.match(ss):
            bad_sess += n
            continue
        sess_rows.setdefault(ss, {}).setdefault(os_, 0)
        sess_rows[ss][os_] += n
        if unex == 1:
            sess_rows_unexcl.setdefault(ss, {}).setdefault(os_, 0)
            sess_rows_unexcl[ss][os_] += n
    if bad_sess:
        out["warnings"].append(f"{bad_sess} judged collection rows have NULL/empty/non-ISO scoring_session")

    data_sessions = sorted(sess_rows)                 # distinct sessions among judged collection rows
    data_index = {s: i for i, s in enumerate(data_sessions)}
    not_in_cal = [s for s in data_sessions if s not in cal_index]
    if not_in_cal:
        out["warnings"].append(f"{len(not_in_cal)} scoring_sessions not in trading_calendar; first {not_in_cal[0]}")

    def cutoff(sess_map, index, label):
        """S* under 9.7 with 'sessions' counted on the given index."""
        resolved = [s for s, m in sess_map.items() if m.get("resolved", 0) > 0]
        latest_resolved = max(resolved) if resolved else None
        pending_total = sum(m.get("pending", 0) for m in sess_map.values())
        stale_rows, live_sessions = 0, []
        for s, m in sess_map.items():
            p = m.get("pending", 0)
            if p == 0:
                continue
            gap = (index[latest_resolved] - index[s]) if (latest_resolved and s in index and latest_resolved in index) else None
            if gap is not None and gap > STALE_SESSIONS:
                stale_rows += p
            else:
                live_sessions.append(s)
        earliest_live = min(live_sessions) if live_sessions else None
        all_sessions = sorted(sess_map)
        if earliest_live is None:
            s_star = all_sessions[-1] if all_sessions else None
        else:
            before = [s for s in all_sessions if s < earliest_live]
            s_star = before[-1] if before else None
        return {
            "index": label,
            "latest_resolved_session": latest_resolved,
            "pending_judged_rows": pending_total,
            "stale_pending_rows": stale_rows,
            "live_pending_rows": pending_total - stale_rows,
            "earliest_non_stale_pending_session": earliest_live,
            "S_star": s_star,
            "sessions_after_S_star_with_judged_rows": sum(1 for s in all_sessions if s_star is None or s > s_star),
        }

    cut_primary = cutoff(sess_rows, cal_index, "trading_calendar")
    cut_alt_index = cutoff(sess_rows, data_index, "distinct_scoring_sessions_in_snapshot")
    cut_alt_unexcl = cutoff(sess_rows_unexcl, cal_index, "trading_calendar, exclusion_reason='' rows only")
    out["cutoff_9_7"] = cut_primary
    out["cutoff_9_7_sensitivity"] = {
        "sessions_counted_on_snapshot_sessions": cut_alt_index,
        "pending_check_on_unexcluded_rows_only": cut_alt_unexcl,
        "agree_S_star": (cut_primary["S_star"] == cut_alt_index["S_star"] == cut_alt_unexcl["S_star"]),
        "agree_stale": (cut_primary["stale_pending_rows"] == cut_alt_index["stale_pending_rows"]),
    }
    out["readings"].append(
        "9.7 stale rule: 'sessions' counted on the exchange trading_calendar (primary); "
        "sensitivity counted on the distinct scoring_sessions present among judged collection rows.")
    out["readings"].append(
        "9.7 pending check: every judged collection row, regardless of exclusion_reason (primary); "
        "sensitivity restricted to exclusion_reason = ''.")
    s_star = cut_primary["S_star"]
    if s_star is None:
        print("no S*")
        sys.exit(2)
    gate_cut = min(s_star, hard_stop)
    out["gate_restriction"] = {"S_star": s_star, "hard_stop": hard_stop,
                               "scoring_session_max_inclusive": gate_cut,
                               "binding": "S_star" if s_star <= hard_stop else "hard_stop"}

    # ---- 9.8 gate rows G -------------------------------------------------------
    excluded_set = set(excluded_days)
    rows = run(con, S,
               "SELECT query_date, scoring_session, excess_1session FROM news_observation "
               "WHERE run_kind='collection' AND state='judged' AND outcome_state='resolved' "
               "AND exclusion_reason='' AND scoring_session IS NOT NULL AND scoring_session<>''")
    g_sessions, g_values = [], []
    null_excess_other_conditions_met = 0
    rows_before_cut_and_dayrule = len(rows)
    dropped_day_rule, dropped_after_cut = 0, 0
    for qd, ss, ex in rows:
        if qd in excluded_set:
            dropped_day_rule += 1
            continue
        if ss > gate_cut:
            dropped_after_cut += 1
            continue
        if ex is None:
            null_excess_other_conditions_met += 1
            continue
        g_sessions.append(ss)
        g_values.append(float(ex))
    y = np.asarray(g_values, dtype=np.float64) * 10000.0
    sess_arr = np.asarray(g_sessions)
    N = int(y.size)
    uniq, inv = np.unique(sess_arr, return_inverse=True)
    C_G = int(uniq.size)
    n_c = np.bincount(inv, minlength=C_G).astype(np.float64)
    sigma = float(np.std(y, ddof=1))
    grand = float(np.mean(y))
    sums = np.bincount(inv, weights=y, minlength=C_G)
    means = sums / n_c
    ssb = float(np.sum(n_c * (means - grand) ** 2))
    ssw = float(np.sum((y - means[inv]) ** 2))
    msb = ssb / (C_G - 1)
    msw = ssw / (N - C_G)
    n0 = (N - float(np.sum(n_c ** 2)) / N) / (C_G - 1)
    rho_raw = (msb - msw) / (msb + (n0 - 1.0) * msw)
    rho = max(0.0, rho_raw)
    out["gate_rows_G"] = {
        "rows_meeting_state_outcome_exclusion_session_conditions_before_dayrule_and_cut": rows_before_cut_and_dayrule,
        "dropped_by_day_rule": dropped_day_rule,
        "dropped_scoring_session_after_cut": dropped_after_cut,
        "null_excess_1session_among_rows_meeting_other_conditions": null_excess_other_conditions_met,
        "N": N, "C_G": C_G,
        "n_c_min": int(n_c.min()), "n_c_max": int(n_c.max()),
        "sum_n_c_sq": float(np.sum(n_c ** 2)),
        "G_first_session": str(uniq[0]), "G_last_session": str(uniq[-1]),
    }
    out["sigma_rho"] = {
        "sigma_bp_ddof1": sigma, "grand_mean_bp": grand,
        "SSB": ssb, "SSW": ssw, "MSB": msb, "MSW": msw, "n0": n0,
        "rho_raw": rho_raw, "rho": rho, "rho_floored": rho_raw < 0,
    }

    # ---- 9.8 directional counts m_c, M, C, k_eff --------------------------------
    # The one allowed judgment query: COUNT grouped by scoring_session.
    sql = ("SELECT scoring_session, COUNT(*) FROM news_observation "
           "WHERE run_kind='collection' AND state='judged' AND outcome_state='resolved' "
           "AND exclusion_reason='' AND excess_1session IS NOT NULL "
           "AND scoring_session IS NOT NULL AND scoring_session<>'' "
           "AND scoring_session<=? ")
    params = [gate_cut]
    if excluded_days:
        sql += "AND query_date NOT IN (" + ",".join("?" * len(excluded_days)) + ") "
        params += excluded_days
    sql += "AND judgment IN ('POSITIVE','NEGATIVE') GROUP BY scoring_session"
    mrows = run(con, S, sql, params)
    m_c = {ss: int(n) for ss, n in mrows}
    M = sum(m_c.values())
    C = len(m_c)
    k_eff = sum(v * v for v in m_c.values()) / M if M else float("nan")
    out["directional_9_8"] = {
        "M": M, "C": C, "k_eff": k_eff,
        "m_c_min": min(m_c.values()) if m_c else None,
        "m_c_max": max(m_c.values()) if m_c else None,
        "sum_m_c_sq": sum(v * v for v in m_c.values()),
        "directional_sessions_subset_of_G_sessions": set(m_c) <= set(uniq.tolist()),
        "C_equals_C_G": C == C_G,
        "G_sessions_without_directional_rows": sorted(set(uniq.tolist()) - set(m_c)),
    }
    out["m_c"] = dict(sorted(m_c.items()))

    # ---- Required and the pass decision -----------------------------------------
    de = 1.0 + (k_eff - 1.0) * rho
    required = Z_CONST * (sigma / DELTA_BP) ** 2 * de
    required_exact = Z_CONST_EXACT * (sigma / DELTA_BP) ** 2 * de
    cond_C = C >= MIN_CLUSTERS
    cond_M = M >= MIN_M
    cond_R = M >= required
    out["required_9_8"] = {
        "z_const_used": Z_CONST, "z_const_exact_sensitivity": Z_CONST_EXACT,
        "delta_bp": DELTA_BP, "design_effect": de,
        "required": required, "required_with_exact_const": required_exact,
        "M_over_required": M / required if required else None,
    }
    out["pass_9_8"] = {
        "C_at_least_60": cond_C, "M_at_least_1000": cond_M, "M_at_least_Required": cond_R,
        "gate_passes": bool(cond_C and cond_M and cond_R),
        "M_minus_required": M - required,
    }
    # Sensitivity: rho with the directional cluster count C in n0 and MSB/MSW
    # denominators would be a mis-reading (the ANOVA is over G); recorded only
    # when C differs from C_G so the reviewer can see its size.
    if C != C_G:
        n0_alt = (N - float(np.sum(n_c ** 2)) / N) / (C - 1)
        rho_alt = max(0.0, (msb - msw) / (msb + (n0_alt - 1.0) * msw))
        out["sigma_rho"]["sensitivity_n0_with_directional_C"] = {"n0": n0_alt, "rho": rho_alt}

    con.close()
    out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(OUT_JSON, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=False, default=str)
    os.chmod(OUT_JSON, 0o444)
    summary = {
        "excluded_query_dates": excluded_days, "max_source_failed_share": round(max_share, 6),
        "S_star": s_star, "hard_stop": hard_stop, "gate_cut": gate_cut,
        "pending": cut_primary["pending_judged_rows"], "stale": cut_primary["stale_pending_rows"],
        "N": N, "C_G": C_G, "null_excess": null_excess_other_conditions_met,
        "sigma": round(sigma, 6), "rho_raw": round(rho_raw, 9), "rho": round(rho, 9),
        "M": M, "C": C, "k_eff": round(k_eff, 6), "required": round(required, 6),
        "pass": out["pass_9_8"]["gate_passes"], "warnings": out["warnings"],
    }
    print(json.dumps(summary))


if __name__ == "__main__":
    main()

"""Post-log diagnostic, counts only, allowed columns only (query_date, scoring_session,
state, run_kind, exclusion_reason, outcome_state). Written AFTER own_gate.json and after
the gate log was opened; it changes nothing in own_gate.json. SQL is logged."""
import sqlite3, datetime, os, sys, json, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SNAP = os.path.join(ROOT, "reports", "c2", "snap_20261116", "news_experiment_snapshot.db")
LOG = os.path.join(HERE, "verify_gate.sql.log")


def q(con, sql, params=()):
    with open(LOG, "a") as fh:
        fh.write("%s\t%s\t%s\tparams=%r\n" % (
            datetime.datetime.now().isoformat(timespec="seconds"),
            os.path.basename(sys.argv[0]), " ".join(sql.split()), tuple(params)))
    return con.execute(sql, params).fetchall()


G = ("run_kind='collection' AND state='judged' AND outcome_state='resolved' AND exclusion_reason='' "
     "AND excess_1session IS NOT NULL AND scoring_session IS NOT NULL AND scoring_session<>''")
con = sqlite3.connect("file:%s?mode=ro&immutable=1" % SNAP, uri=True)
rel = q(con, "SELECT (scoring_session=query_date), (scoring_session>query_date), (scoring_session<query_date), COUNT(*), "
             "COUNT(DISTINCT scoring_session) FROM news_observation WHERE " + G + " GROUP BY 1,2,3")
last = q(con, "SELECT query_date, COUNT(*) FROM news_observation WHERE " + G +
              " AND scoring_session=? GROUP BY query_date", ("2026-11-16",))
same_by_sess = dict(q(con, "SELECT scoring_session, COUNT(*) FROM news_observation WHERE " + G +
                           " AND scoring_session=query_date GROUP BY scoring_session"))
own = json.load(open(os.path.join(HERE, "own_gate.json")))
n_c = own["s9_8"]["n_c"]
m_c = own["s9_8"]["m_c"]
sess = sorted(n_c)
out = {
    "gate_rows_by_relation[same,later,earlier,count,sessions]": rel,
    "last_session_2026-11-16_gate_rows_by_query_date": last,
    "sessions_with_same_day_rows": len(same_by_sess),
    "same_day_rows_total": sum(same_by_sess.values()),
    "same_day_rows_in_last_session": same_by_sess.get("2026-11-16", 0),
    "median_same_day_rows_per_session_having_any": statistics.median(same_by_sess.values()) if same_by_sess else None,
    "n_c_last5": {s: n_c[s] for s in sess[-5:]},
    "m_c_last5": {s: m_c.get(s, 0) for s in sess[-5:]},
    "n_c_median": statistics.median(n_c.values()),
    "m_c_median": statistics.median(m_c.values()),
    "query_dates_max": q(con, "SELECT MAX(query_date), COUNT(DISTINCT query_date) FROM news_observation WHERE run_kind='collection'")[0],
    "sessions_in_gate_not_a_query_date": len([s for s in sess if s not in {r[0] for r in q(con, "SELECT DISTINCT query_date FROM news_observation WHERE run_kind='collection'")}]),
}
json.dump(out, open(os.path.join(HERE, "extra_counts.json"), "w"), indent=1)
print(json.dumps(out))

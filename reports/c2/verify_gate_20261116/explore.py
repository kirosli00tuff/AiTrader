"""Exploration for GateVerifier 20261116: counts only, allowed columns only.
Every SQL statement is appended to verify_gate.sql.log before it runs."""
import sqlite3, datetime, os, sys

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


con = sqlite3.connect("file:%s?mode=ro&immutable=1" % SNAP, uri=True)
cols = q(con, "PRAGMA table_info(news_observation)")
names = [c[1] for c in cols]
need = ["query_date", "scoring_session", "state", "run_kind", "exclusion_reason",
        "outcome_state", "excess_1session", "judgment"]
print("ncols", len(names), "missing", [n for n in need if n not in names])
print("types", {c[1]: c[2] for c in cols if c[1] in need})
print("run_kind", q(con, "SELECT run_kind, COUNT(*) FROM news_observation GROUP BY run_kind"))
print("state(coll)", q(con, "SELECT state, COUNT(*) FROM news_observation WHERE run_kind='collection' GROUP BY state"))
print("state x outcome_state (coll)", q(con, "SELECT state, outcome_state, COUNT(*) FROM news_observation WHERE run_kind='collection' GROUP BY state, outcome_state"))
print("excl_reason (coll judged)", q(con, "SELECT exclusion_reason, outcome_state, COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY exclusion_reason, outcome_state"))
print("excl_reason NULL count (coll)", q(con, "SELECT COUNT(*) FROM news_observation WHERE run_kind='collection' AND exclusion_reason IS NULL"))
print("sess format (coll judged)", q(con, "SELECT LENGTH(scoring_session), scoring_session GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]', COUNT(*), MIN(scoring_session), MAX(scoring_session) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY 1, 2"))
print("qd format (coll)", q(con, "SELECT LENGTH(query_date), query_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]', COUNT(*), MIN(query_date), MAX(query_date), COUNT(DISTINCT query_date) FROM news_observation WHERE run_kind='collection' GROUP BY 1, 2"))
print("excess typeof (coll judged) by outcome_state", q(con, "SELECT outcome_state, typeof(excess_1session), COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY 1, 2"))
print("typeof key cols (coll)", q(con, "SELECT typeof(query_date), typeof(scoring_session), typeof(state), typeof(exclusion_reason), typeof(outcome_state), COUNT(*) FROM news_observation WHERE run_kind='collection' GROUP BY 1,2,3,4,5"))

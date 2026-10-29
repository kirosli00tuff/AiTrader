"""Exploration of the C.2 snapshot schema on permitted columns only.

Prints column names (metadata) and aggregate counts of categorical values.
No row-level values of any outcome column are printed.
"""
import sqlite3

SNAP = "/home/kiros-li/Documents/GitHub/AiTrader/reports/c2/snap_20261028/news_experiment_snapshot.db"
URI = f"file:{SNAP}?mode=ro&immutable=1"

SQL_LOG = []


def q(con, sql, params=()):
    SQL_LOG.append(sql.strip())
    return con.execute(sql, params).fetchall()


con = sqlite3.connect(URI, uri=True)

print("== tables ==")
for (name,) in q(con, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print(" ", name)

print("== news_observation columns (names only) ==")
cols = [r[1] for r in q(con, "PRAGMA table_info(news_observation)")]
print(" ", ", ".join(cols))

print("== run_kind counts ==")
for r in q(con, "SELECT run_kind, COUNT(*) FROM news_observation GROUP BY run_kind ORDER BY run_kind"):
    print(" ", r)

print("== state counts (collection) ==")
for r in q(con, "SELECT state, COUNT(*) FROM news_observation WHERE run_kind='collection' GROUP BY state ORDER BY state"):
    print(" ", r)

print("== outcome_state counts (collection, judged) ==")
for r in q(con, "SELECT outcome_state, COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY outcome_state ORDER BY outcome_state"):
    print(" ", r)

print("== exclusion_reason counts (collection, judged) ==")
for r in q(con, "SELECT exclusion_reason, COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY exclusion_reason ORDER BY exclusion_reason"):
    print(" ", r)

print("== exclusion_reason NULL vs '' (collection, judged) ==")
for r in q(con, "SELECT (exclusion_reason IS NULL) AS is_null, (exclusion_reason = '') AS is_empty, COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY 1, 2"):
    print(" ", r)

print("== scoring_session NULL/empty counts (collection, judged) ==")
for r in q(con, "SELECT (scoring_session IS NULL) AS is_null, (scoring_session = '') AS is_empty, COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY 1, 2"):
    print(" ", r)

print("== typeof(excess_1session) counts (collection, judged, resolved) ==")
for r in q(con, "SELECT typeof(excess_1session), COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' AND outcome_state='resolved' GROUP BY 1"):
    print(" ", r)

print("== typeof(scoring_session), typeof(query_date) (collection) ==")
for r in q(con, "SELECT typeof(scoring_session), typeof(query_date), COUNT(*) FROM news_observation WHERE run_kind='collection' GROUP BY 1, 2"):
    print(" ", r)

print("== query_date range, distinct count (collection) ==")
for r in q(con, "SELECT MIN(query_date), MAX(query_date), COUNT(DISTINCT query_date), COUNT(*) FROM news_observation WHERE run_kind='collection'"):
    print(" ", r)

print("== scoring_session range, distinct count (collection, judged) ==")
for r in q(con, "SELECT MIN(scoring_session), MAX(scoring_session), COUNT(DISTINCT scoring_session), COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' AND scoring_session IS NOT NULL AND scoring_session <> ''"):
    print(" ", r)

print("== scoring_session length distribution (collection, judged) ==")
for r in q(con, "SELECT LENGTH(scoring_session), COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY 1"):
    print(" ", r)

con.close()

with open("/home/kiros-li/Documents/GitHub/AiTrader/reports/c2/verify_gate/explore_schema.sql.log", "w") as fh:
    for s in SQL_LOG:
        fh.write(s + ";\n")

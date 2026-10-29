"""State breakdown of the one collection day with a material source_failed count (counts by state only)."""
import sqlite3
SNAP = "/home/kiros-li/Documents/GitHub/AiTrader/reports/c2/snap_20261028/news_experiment_snapshot.db"
con = sqlite3.connect(f"file:{SNAP}?mode=ro&immutable=1", uri=True)
SQL = "SELECT state, COUNT(*) FROM news_observation WHERE run_kind='collection' AND query_date='2026-10-07' GROUP BY state ORDER BY state"
for r in con.execute(SQL):
    print(r)
con.close()
with open("/home/kiros-li/Documents/GitHub/AiTrader/reports/c2/verify_gate/explore_day_20261007.sql.log", "w") as fh:
    fh.write(SQL + ";\n")

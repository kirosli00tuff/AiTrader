import sqlite3, re, collections, statistics, os
DB = os.path.expanduser("~/Documents/GitHub/AiTrader/news_experiment.db")
FORBIDDEN = re.compile(r"\b(ret_\w+|bench_\w+|excess_\w+|net_bp|cost_bp_round_trip|outcome_state|anchor_\w+|scoring_session|bar_source|delay_rolled)\b", re.I)
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
def q(sql, *a):
    assert not FORBIDDEN.search(sql), "outcome column in query: " + sql
    return con.execute(sql, a).fetchall()
W = "run_kind='collection'"
J = W + " AND state='judged'"
def pct(a, b): return f"{100*a/b:.1f}%" if b else "n/a"

print("== 1. Skew diagnostic (EXPERIMENT.md Amendment 6), on judged rows")
rows = q(f"SELECT judgment, COUNT(*) FROM news_observation WHERE {J} GROUP BY judgment")
d = dict(rows); P, N, U = d.get("POSITIVE",0), d.get("NEGATIVE",0), d.get("NEUTRAL",0); T = P+N+U
print(f"pooled: POS {P} ({pct(P,T)}), NEG {N} ({pct(N,T)}), NEU {U} ({pct(U,T)}), total {T}")
print(f"NEUTRAL rate {pct(U,T)} vs 80% reportable-failure bar")
print(f"minority directional share {pct(min(P,N),P+N)} vs 10% floor")
days = q(f"SELECT query_date, SUM(judgment='POSITIVE'), SUM(judgment='NEGATIVE') FROM news_observation WHERE {J} GROUP BY query_date ORDER BY query_date")
mixed = sum(1 for _,p,n in days if p>0 and n>0)
print(f"mixed day clusters {mixed} of {len(days)} vs 30 floor")
half = len(days)//2; first = {x[0] for x in days[:half]}
for name, sel in (("first half", lambda d: d in first), ("second half", lambda d: d not in first)):
    c = collections.Counter()
    for qd, j in q(f"SELECT query_date, judgment FROM news_observation WHERE {J}"):
        if sel(qd): c[j]+=1
    t = sum(c.values())
    print(f"{name}: POS {pct(c['POSITIVE'],t)}, NEG {pct(c['NEGATIVE'],t)}, NEU {pct(c['NEUTRAL'],t)}, n {t}, minority dir {pct(min(c['POSITIVE'],c['NEGATIVE']),c['POSITIVE']+c['NEGATIVE'])}")

print("\n== 2. Per-day judged counts (cluster size k)")
ks = [p+n+q2 for (_,p,n),q2 in zip(days, [r[0] for r in q(f"SELECT SUM(judgment='NEUTRAL') FROM news_observation WHERE {J} GROUP BY query_date ORDER BY query_date")])]
print(f"days {len(ks)}, mean k {statistics.mean(ks):.1f}, median {statistics.median(ks)}, min {min(ks)}, max {max(ks)}")
dirs = [p+n for _,p,n in days]
print(f"directional per day: mean {statistics.mean(dirs):.1f}, min {min(dirs)}, max {max(dirs)}")

print("\n== 3. Concentration: which names carry the news")
sym = q(f"SELECT symbol, stratum, COUNT(*) c FROM news_observation WHERE {J} GROUP BY symbol ORDER BY c DESC")
tot = sum(r[2] for r in sym)
print(f"symbols with >=1 judged headline: {len(sym)} of {q(f'SELECT COUNT(DISTINCT symbol) FROM news_observation WHERE {W}')[0][0]}")
top10 = sum(r[2] for r in sym[:10]); top40 = sum(r[2] for r in sym[:40])
print(f"top 10 names {pct(top10,tot)} of judged, top 40 {pct(top40,tot)}")
print("top 10:", ", ".join(f"{s}({st}) {c}" for s,st,c in sym[:10]))

print("\n== 4. Sector mix of judged, with directional balance")
for sec, c, p, n in q(f"SELECT COALESCE(sector,'?'), COUNT(*), SUM(judgment='POSITIVE'), SUM(judgment='NEGATIVE') FROM news_observation WHERE {J} GROUP BY sector ORDER BY 2 DESC"):
    print(f"{sec:28s} {c:5d} ({pct(c,T)})  POS:NEG {p}:{n}")

print("\n== 5. Sources")
for s, c in q(f"SELECT COALESCE(source_name,'?'), COUNT(*) FROM news_observation WHERE {J} GROUP BY source_name ORDER BY 2 DESC LIMIT 8"):
    print(f"{s:30s} {c:5d} ({pct(c,T)})")

print("\n== 6. Timing: publication hour (UTC) and publish-to-call delay")
hrs = collections.Counter(); delays = []
for pub, called in q(f"SELECT published_ts, called_ts FROM news_observation WHERE {J} AND published_ts IS NOT NULL"):
    try:
        hrs[int(pub[11:13])] += 1
    except Exception: pass
print("hour UTC: " + " ".join(f"{h:02d}:{hrs[h]}" for h in sorted(hrs)))
rth = sum(v for h,v in hrs.items() if 14 <= h <= 19)
print(f"published 14:00-19:59 UTC (roughly US regular hours): {pct(rth, sum(hrs.values()))}")

print("\n== 7. Strength by judgment")
for j, s, c in q(f"SELECT judgment, strength, COUNT(*) FROM news_observation WHERE {J} GROUP BY judgment, strength ORDER BY judgment, strength"):
    print(f"{j:9s} s{s}: {c}")

print("\n== 8. Short-side tradeability of NEGATIVE calls")
for et, sh, c in q(f"SELECT etb, shortable, COUNT(*) FROM news_observation WHERE {J} AND judgment='NEGATIVE' GROUP BY etb, shortable"):
    print(f"etb={et} shortable={sh}: {c} ({pct(c,N)})")

print("\n== 9. Stories and duplicates")
sg = q(f"SELECT story_group_id, COUNT(*) FROM news_observation WHERE {J} AND story_group_id IS NOT NULL GROUP BY story_group_id HAVING COUNT(*)>1")
print(f"story groups with >1 judged row: {len(sg)}, rows in them {sum(c for _,c in sg)}")
ms = q(f"SELECT COUNT(*) FROM news_observation WHERE {J} AND (SELECT COUNT(DISTINCT symbol) FROM news_observation o2 WHERE o2.story_group_id=news_observation.story_group_id AND o2.run_kind='collection')>1")[0][0]
print(f"judged rows whose story touches >1 symbol: {ms}")

print("\n== 10. Model health and spend")
for k, v in zip(("rows","parse_ok","strength_ok","neutral_anomaly","cost_usd","in_tok","cached_tok","out_tok","mean_latency_ms"),
    q(f"SELECT COUNT(*), SUM(parse_ok), SUM(strength_parse_ok), SUM(neutral_strength_anomaly), ROUND(SUM(cost_usd),4), SUM(input_tokens), SUM(cached_input_tokens), SUM(output_tokens), ROUND(AVG(latency_ms)) FROM news_observation WHERE {W} AND model_id IS NOT NULL")[0]):
    print(f"{k}: {v}")
print("distinct prompt_sha256:", q(f"SELECT COUNT(DISTINCT prompt_sha256) FROM news_observation WHERE {W} AND prompt_sha256 IS NOT NULL")[0][0],
      "| distinct model_id:", q(f"SELECT GROUP_CONCAT(DISTINCT model_id) FROM news_observation WHERE {W}")[0][0],
      "| distinct spec_version:", q(f"SELECT GROUP_CONCAT(DISTINCT spec_version) FROM news_observation WHERE {W}")[0][0],
      "| collector shas:", q(f"SELECT COUNT(DISTINCT collector_git_sha) FROM news_observation WHERE {W}")[0][0])

# B.2 blind interim read (2026-09-28)

Planning chat, through Desktop Commander. No CLI session. Read-only
database connection. Every query passed through
`scripts/blind_interim_20260928.py`, which refuses any query naming an
outcome column (`ret_*`, `bench_*`, `excess_*`, `net_bp`,
`cost_bp_round_trip`, `outcome_state`, `anchor_*`, `scoring_session`,
`bar_source`, `delay_rolled`). Ad hoc follow-up queries touched only
symbol, stratum, sector, sector_source, state, judgment, headline and
collector_git_sha. No outcome was read.

Data at the time: 41 day clusters (2026-07-28 to 2026-09-25), 19,091
collection rows, 5,613 judged. It led to EXPERIMENT.md Amendment 8.

## 1. Amendment 6 skew diagnostic (reported early, not interpreted)

| check | value | registered threshold | status |
|---|---|---|---|
| minority directional share (NEGATIVE / directional) | 29.3% | >= 10% | informative |
| mixed day clusters | 41 of 41 | >= 30 | informative |
| NEUTRAL rate | 43.1% | < 80% failure bar | pass |

Pooled: POSITIVE 2,258 (40.2%), NEGATIVE 936 (16.7%), NEUTRAL 2,419
(43.1%). Chronological halves: first POS 40.5 / NEG 19.6 / NEU 40.0
(minority directional 32.6%), second POS 40.0 / NEG 14.4 / NEU 45.6
(minority directional 26.5%). The NEGATIVE share is drifting down. It is
still far above the floor, and worth tracking weekly.

## 2. Cluster size

Judged per day: mean 136.9, median 132, min 45, max 259. Directional per
day: mean 77.9, min 30, max 152. The design effect was sized on k = 40.
Projection to 60 clusters at the registered 30 bp effect, 180 bp sigma, z
2.50 and 80% power (n = 402 independent): power holds for rho up to about
0.143 (all judged) or 0.138 (directional only). At sigma 250 bp, the
ceilings fall to about 0.071 and 0.065. Rho and sigma need outcome data.
See Amendment 8.4.

## 3. Coverage and concentration

386 of 400 symbols have at least one judged headline. The top 10 names
carry 13.8% of judged rows and the top 40 carry 32.2%. Top two: STRK (170)
and BAC.PRL (157), both preferreds.

## 4. Preferreds, share classes, closed-end funds

- Preferred and share-class symbols: 7 symbols, 421 judged rows (7.5%),
  187 directional. Headlines describe the parent company or unrelated
  topics.
- Closed-end funds admitted despite the fund exclusion: BCAR, BCX, BIT,
  BMEZ, BSTZ, BUI, GDV, HQH, PSUS. 31 judged rows (0.6%).
- Both are handled by the Amendment 8.2 sensitivity exclusion.

## 5. Relevance look (not the registered sample)

54 common-stock judged rows with `id % 97 = 11`: 39 company-specific
(72%), 7 roundups (13%), 5 off-topic (9%), 3 closed-end funds (6%).
Off-topic examples: BBW (Build-A-Bear) with a semiconductor tariff story,
CPA (Copa) with a LATAM Airlines story, MRX (Marex) with a Cantor/Kalshi
story. Amendment 8.3 registers a 200-row fixed-seed sample before C.2.

## 6. Timing

30.3% of judged headlines were published 14:00 to 19:59 UTC (roughly US
regular hours). The rest are off-hours and score next-open to next-close.

## 7. Strength by judgment

NEGATIVE: s2 462, s3 291, s4 174, s5 9. POSITIVE: s2 884, s3 877, s4 492,
s5 5. NEUTRAL: s1 2,419 (fixed by design). Only 14 rows reach strength 5.

## 8. Short side

NEGATIVE calls: 835 (89.2%) easy-to-borrow and shortable at decision time,
101 (10.8%) neither.

## 9. Integrity

- One prompt hash, one model (`claude-haiku-4-5`), one spec version
  (`EXPERIMENT.md@amendment-3-accepted-2026-07-28`) across all rows.
- Seven collector_git_sha values. Only two commits in that range touch
  news_experiment/: 284e720 (daily scheduler, collector behaviour
  unchanged) and 647a8ab (bar-absent reopen, horizon fill and per-formation
  benchmark in outcomes.py and maintain.py, "no judgment altered"). The
  other values are log and doc commits moving the repo head.
- parse_ok and strength_parse_ok on every judged row, zero NEUTRAL
  strength anomalies, 3 unparseable model responses in total.
- Spend $3.10. Cached input tokens 0 of 1.91M, the known caching-layout
  gap in Task 3. Not changed mid-collection.
- 271 judged rows share a story group with another symbol.

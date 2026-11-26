# GateVerifier-FableXHigh brief, Stage C.2b, attempt date 20261125

Model: fable. Effort: xhigh (agent file worker-xhigh). Spawned by the Stage C.2b lead (Opus 5.5). You do not spawn workers. Under the review cap (docs/DECISIONS.md V11; the attempt-4 planner note item 1) you are the one review of this gate.

## Objective

Recompute the registered 9.8 gate from one frozen snapshot with your own code, then compare with the registered gate log entry. Nothing else. The gate numbers decide whether the outcome columns of a pre-registered experiment unlock, so your value is independence: a different model reading the registered text literally. If the literal text and the log disagree, say so.

## Inputs

- Snapshot: reports/c2/snap_20261125/news_experiment_snapshot.db (repo root /home/kiros-li/Documents/GitHub/AiTrader). Check it against reports/c2/snap_20261125/snapshot.json (sha256, mode 0444, no -wal, -shm or -journal beside it). Open it only as `file:<abs path>?mode=ro&immutable=1` with uri=True.
- The registered text, EXPERIMENT.md, read ONLY by these line ranges with sed -n (the file is about 3,300 lines, never read it whole):
  - 842-858: 9.1, the cluster is scoring_session, and the 20 percent source_failed day rule applies to query_date
  - 912-958: 9.7 (scorable row, S*) and 9.8 (the gate, exact)
  - 1072-1087: 10.1 (the hard stop and the restriction of the gate rows)
  - 2475-2484: the Task 7 source_failed day rule
  - 2200-2232: the Task 5 power arithmetic, for the 11.156 factor
  If you need another range to settle a reading, take it (grep -n first) and name it in your report.
- For the hard-stop session only: analysis_bars.db, opened `file:<abs path>?mode=ro`, statement `SELECT date FROM trading_calendar ORDER BY date` and nothing else. 10.1 defines the session count. Read no other table in that file.

## Column rule (binding)

From the snapshot table news_observation you may read ONLY: query_date, scoring_session, state, run_kind, exclusion_reason, outcome_state, excess_1session. In addition, one count over the judgment column grouped by session is allowed, of this shape and no other:
`SELECT scoring_session, COUNT(*) ... WHERE <scorable conditions> AND judgment IN ('POSITIVE','NEGATIVE') GROUP BY scoring_session`.
Never select a row-level judgment, strength or reason, and never print a row. Do not read any other outcome column (net_bp, ret_*, bench_*, cost_bp_round_trip and so on). `PRAGMA table_info` is fine. Log every SQL statement you run to reports/c2/verify_gate_20261125/verify_gate.sql.log.

## Compute, in your own Python

Run everything as:
`cd ~/Documents/GitHub/AiTrader && export PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 && nice -n 10 .venv-eval/bin/python <your script>`
Never use the repo .venv. Do not import anything from news_eval. Write your own code from the registered text; do not copy or open any earlier verifier's code.

Following 9.1, 9.7, 9.8 and 10.1 literally, compute and write every one of these:
- the 9.1 excluded query_dates, with the largest source_failed share and its date
- S*, the latest resolved session, the pending judged row count, stale pending rows, and the earliest non-stale pending session
- the hard-stop session from trading_calendar, and the restriction scoring_session <= min(S*, hard stop) applied to the gate rows
- N (gate rows, NEUTRAL included), C_G (clusters among the gate rows), the count of NULL excess_1session among rows meeting the other conditions
- sigma (ddof 1 of 10,000 x excess_1session), MSB, MSW, n0, rho_raw, rho (floored at 0)
- m_c per cluster, M, C (clusters with at least one directional scorable row), k_eff
- Required, each of the three pass conditions, and the pass decision

## Five report lines added for this attempt (attempt-4 planner note item 3)

Your report must carry each of these as its own numbered line, even where the answer is "not applicable":
1. The largest source_failed share under both denominators, each with its date: (a) source_failed over every collection row of the query_date; (b) source_failed over the collection rows of the query_date other than excluded_pre_call. Say whether any day crosses 0.20 under either.
2. S* under each defensible reading of the 9.7 pending-row rules (the stale rule's session unit, and whether rows carrying an exclusion_reason count), whenever any judged collection row is pending. Flag any split. If no judged collection row is pending, say so and give the one S*.
3. Whether C equals C_G, and if not, the n0 and Required under each.
4. At the hard-stop snapshot only: the 10.1 bound min(S*, hard-stop session) recomputed from trading_calendar, and the number of gate rows it drops. If your S* is before the hard-stop session, write "not applicable" with the one-line reason. Either way, still apply the restriction in your compute, as 9.8 and 10.1 require.
5. Whether the S* cluster is final in this snapshot, meaning its own query_date has been collected (attempt-3 finding F1): give the S* session, the number of collection rows whose query_date equals S*, and the S* cluster's gate rows and directional rows with the query_dates they come from (counts only). If it is not final, also give M and Required without that cluster, labelled NOT REGISTERED, only to say whether the pass decision would differ.

## Order of work (binding)

1. Before your numbers are on disk, do NOT open: reports/c2/gate_log.jsonl, anything under news_eval/, reports/c1_verdict_mapping.md, reports/C.1_RETURN.md, reports/C.2_RETURN.md, reports/C.3_RETURN.md, reports/C.2b_RETURN_*.md, reports/C.2b_STATE_*.md, reports/c2_gate_verify.md, reports/c2_gate_verify_20261106.md, reports/c2_gate_verify_20261116.md, reports/c2/verify_gate/ (attempt 1), reports/c2/verify_gate_20261106/ (attempt 2), reports/c2/verify_gate_20261116/ (attempt 3), or docs/prompts/. Do not run any git command that shows the content of those files.
2. Write your code to reports/c2/verify_gate_20261125/verify_gate.py and your numbers to reports/c2/verify_gate_20261125/own_gate.json. Record `date` immediately after own_gate.json exists.
3. Only then open reports/c2/gate_log.jsonl and take the entry whose inputs_sha256 equals the snapshot's sha256. Compare every numeric and logical field you computed in reports/c2/verify_gate_20261125/compare.py, output in compare.out: exact for counts, dates and booleans, within 1e-9 relative for reals. Name any log field you did not recompute. Check that the entry's manifest_sha256 equals `sha256sum reports/c3_harness_freeze.json`, and that the snapshot has exactly one entry in the log.
4. Only on a mismatch may you read news_eval/gate.py, cutoff.py, stats.py or data.py, to diagnose it. Never edit them.

## Output

reports/c2_gate_verify_20261125.md, containing: a result line (MATCH or MISMATCH, and the pass decision); the model you ran as; times from `date`; inputs and integrity; a table of every compared quantity (own value, log value, relative difference); the five added report lines; findings, each marked BLOCKING, SHOULD FIX or NOTE, including any place where you had to choose a reading of the text, or where the text and the log could be read differently. No projection, no forecast, and no interpretation of what the numbers mean for the experiment.

Write only under reports/c2/verify_gate_20261125/ and to reports/c2_gate_verify_20261125.md. No commits and no git add. Never open the live news_experiment.db. Never run news_eval.gate or news_eval.run_c2. Never stop or touch the collector, its timer or service, or any other Claude session on this machine. Keep tool output short. Never delete with a glob, a relative path or an unguarded variable. Put any large scratch under /home/kiros-li/.cache, not /tmp.

## Return

The report path, the MATCH or MISMATCH result, the number of quantities compared, the largest relative difference, the count of findings by level, and anything unfinished, in at most 200 words.

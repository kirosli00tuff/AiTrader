# Stage C.1 Task 8b: leakage, look-ahead, fabrication, double-run and verdict-divergence review of news_eval/

Reviewer: LeakageAuditor-FableMax (worker-max on fable). Written 2026-10-11 before the freeze.
Scope: news_eval/*.py, news_eval/schema.sql, news_eval/requirements-eval.lock, tests/test_news_eval_*.py,
reports/c1_verdict_mapping.md, read against docs/prompts/STAGE_C.1.md and EXPERIMENT.md (Amendments 5, 6,
8.1 to 8.4, 9.1 to 9.15, Task 5, Task 6, Task 7).

Method: every file in news_eval/ was read in full; EXPERIMENT.md by section. Attacks that could be
demonstrated were run as probes under reports/c1_scratch/task8b/ with .venv-eval/bin/python
(Python 3.12.13, numpy 2.5.3, SQLite 3.53.1) and PYTHONPYCACHEPREFIX set. Every probe wraps
sqlite3.connect to raise on the repository's news_experiment.db (realpath or inode) and uses a stand-in:
reports/c1_scratch/task8b/fake_repo/news_experiment.db, an UNSTAMPED copy of the S-NULL fixture
(application_id 0, meta table dropped), which classifies NON_SYNTHETIC exactly as a real copy does.
The real database, its -wal/-shm, analysis_bars.db and market_ai_lab.db were not opened, read, copied or
stat-by-opened. reports/c2_UNLOCK.json, reports/c2_RUN_ONCE.json and reports/c2/ were not created.
Probe outputs are beside each probe as probe*.out.

Counts: 3 BLOCKING, 7 SHOULD FIX, 12 NOTE. Ranked within each severity by how much it would change the
verdict or the blindness guarantee.

---

## BLOCKING

### B1. A `-wal` sidecar beside the 0444 snapshot changes what the gate and the verdict read while the snapshot's sha256, the gate log's `inputs_sha256` and every precondition stay satisfied

- Where: news_eval/data.py:150 `_connect_ro` opens `file:<path>?mode=ro` with no `immutable=1`;
  news_eval/run_c2.py:296-330 `_check_snapshot` checks mode bits, meta, sha256 and classification but
  never looks for `<snapshot>-wal`, `-shm` or `-journal`; news_eval/gate.py:128 `inputs_sha256 =
  sha256_file(db_path)` hashes the main file only; tests/test_news_eval_run_c2.py:609 asserts header
  bytes 18,19 == 1,1 as the guarantee that "a read-only open never creates -wal/-shm files beside it"
  (run_c2.py:16-17). That guarantee does not hold: SQLite applies an existing -wal whose salt and page
  size match the file regardless of the header's journal-mode bytes.
- Attack / failing input: take a legitimate snapshot (journal_mode DELETE, 0444). Make a writable copy,
  switch it to WAL with autocheckpoint off, insert rows (the probe inserted 600 resolved directional judged
  rows copied from existing ones), copy its -wal to `<snapshot>-wal`. The read-only open through the
  loader now reads the WAL contents.
- Demonstrated: reports/c1_scratch/task8b/probe5_wal_sidecar.py and probe5b_wal_followup.py
  (probe5.out, probe5b.out). Clean: collection rows 7600, gate N=3543, M=2470, sigma=141.555. With the
  planted -wal: collection rows 8200, gate N=4143, M=3070, sigma=140.797, and the gate entry's
  `inputs_sha256` still equals the clean file hash; the snapshot's sha256 is unchanged;
  `_check_snapshot` passes. The read-only open also created `<snapshot>-shm` in the snapshot directory.
  Opening the same file with `?mode=ro&immutable=1` returned 7600 (WAL ignored).
- Consequence: the design's statement that "the 9.8 gate has run on the exact bytes analysed"
  (run_c2.py:5) is false whenever a sidecar exists at either read. A gate PASS can be logged against data
  the verdict never sees, or the verdict can compute on data the gate never saw, in both cases under the
  same recorded hash. This is the item 6 case "compute on different bytes than the gate passed". It needs a
  file placed beside the snapshot, so it is a hostile-or-mistake path, but the hash chain is the only
  integrity binding C.2 has and it does not cover it.
- Fix: (1) open every non-live database (snapshot, synthetic, any NON_SYNTHETIC) with
  `?mode=ro&immutable=1`; keep plain `mode=ro` for the LIVE_REAL path only (the collector may hold a
  legitimate WAL on the live file). (2) In `_check_snapshot`, `gate.evaluate` and `_Phase.open` for a
  non-live file, refuse when `<db>-wal`, `<db>-shm` or `<db>-journal` exists. (3) Hold one connection
  from precondition 4 through compute (see S4) so the bytes hashed are the bytes read. (4) Record the
  absence of sidecars in snapshot.json and run_meta. (5) Add a test that plants a -wal and expects
  refusal, replacing the header-bytes assertion as the guarantee.

### B2. The unlock file and the run-once marker are existence-only checks on caller-supplied paths; any readable file passes, so a real snapshot can reach GATE in C.1 with `--unlock README.md`

- Where: news_eval/data.py:442 `if not os.path.isfile(self._unlock)` and :446 for the marker;
  news_eval/run_c2.py:163 `take_snapshot` uses the same `os.path.isfile(unlock)`; the CLI overrides at
  run_c2.py:638-654 and gate.py:228-230 accept any path. No content, schema or binding is checked.
  reports/c1_verdict_mapping.md D22 records "The unlock condition is that the file exists" as a lead
  decision; the demonstrated consequence is that the condition is met by any file the caller names.
- Attack / failing input (no `--real-db` override needed): `python -m news_eval.run_c2 snapshot --source
  news_experiment.db --out-dir X --unlock README.md` copies the live database through the backup API
  (run_c2.py:208-226 opens the source directly, not through the loader) into a NON_SYNTHETIC snapshot;
  then `python -m news_eval.gate --db X/news_experiment_snapshot.db --log L --unlock README.md` is
  admitted and reads `scoring_session` and row-level `excess_1session` into memory, logging sigma, rho,
  k_eff, C, M, Required and PASS/FAIL. With `--marker README.md` as well, VerdictPhase reads every column.
- Demonstrated on the stand-in: reports/c1_scratch/task8b/probe2_override_bypass.py (probe2.out) cases
  (c) VERDICT with unlock=README and marker=README returned 3684 rows of (id, judgment, excess_1session);
  (e) the gate CLI exited 0 and appended a log line with db_class NON_SYNTHETIC; probe5b_wal_followup.py
  shows `take_snapshot(..., unlock_path=README.md)` succeeding and `gate.evaluate(snapshot,
  unlock_path=README.md)` running.
- Consequence: in C.1 the blindness guarantee rests on nobody passing `--unlock <existing file>`; the
  registered unlock path reports/c2_UNLOCK.json is the default, not a requirement. The same applies in
  C.2 to the marker: VerdictPhase accepts any existing `run_once_path`.
- Fix: the unlock must parse as JSON with schema `c2_unlock/1` and named fields (stage "C.2", approver,
  UTC time, EXPERIMENT.md sha256, the C.1 manifest sha256), validated in `_Phase._admit` and in
  `take_snapshot`; the marker must parse as `c2_run_once/1` and VerdictPhase must compare its
  `snapshot_sha256` with the sha256 of the file it is about to open (hash before `sqlite3.connect`, with
  the sidecar check of B1). Tests currently write "{}" into both files (tests/test_news_eval_data.py:137,
  141; test_news_eval_gate.py:463, 483, 495; test_news_eval_run_c2.py:131, 307) and would be updated.

### B3. The `--real-db` / `real_db_path` override REPLACES the compiled-in live path, so the live database itself can be classified NON_SYNTHETIC and admitted to GATE and VERDICT

- Where: news_eval/data.py:131-147 `is_live_real` compares only against the supplied path (or the
  module attribute `REAL_DB_PATH`, which tests monkeypatch). A nonexistent override makes
  `os.stat(real)` raise FileNotFoundError and the function return False; the real file then goes through
  `_classify_open` (data.py:156), is NON_SYNTHETIC (application_id 0), and `_admit` only asks for the
  unlock file (B2). Overrides exist on every entry point: gate.py:228, run_c2.py:640/654,
  relevance.py `--real-db`, and the `real_db_path=` keyword of every phase and of family.compute.
- Attack / failing input: `python -m news_eval.gate --db news_experiment.db --log L --real-db /nonexistent
  --unlock README.md`. A session copying a test command line with `--real-db <tmp>` while naming the
  real file as `--db` does the same by accident.
- Demonstrated on the stand-in: probe2_override_bypass.py (probe2.out): (a) with the real path correct,
  GATE refuses with RealDatabaseRefused before connect; (b) with `real_db_path=<nonexistent>` and
  `unlock_path=README.md`, `gate.evaluate` on the same file RAN (db_class NON_SYNTHETIC, C=64, M=2470,
  PASS, sigma a number); (c) VERDICT returned 3684 rows; (e) the CLI exited 0 and wrote a log line.
  (d) RELEVANCE under the same override correctly refused (NotSyntheticRefused), so guardrail read 3 is
  not widened by this path.
- Fix: keep a module constant for the repository's real database that no override and no monkeypatch
  can replace (for example `_REPO_REAL_DB = str(REPO_ROOT / "news_experiment.db")`), and have
  `is_live_real` return True when the path matches EITHER that constant OR the override (realpath or
  inode). Overrides then add a fake live path for tests and never remove the real one. No test needs the
  repository file classified as non-live: every test guards sqlite3.connect against it and never opens it.
  The same "add, never replace" rule should apply to `UNLOCK_PATH` and `RUN_ONCE_PATH` once B2's content
  validation exists.

---

## SHOULD FIX

### S1. `_check_snapshot` never binds the snapshot to the real database

- Where: news_eval/run_c2.py:296-330. `meta["source_realpath"]` is recorded by `take_snapshot` but never
  compared with `os.path.realpath(cfg.real_db)`, and the snapshot's class is only required to be not
  LIVE_REAL (SYNTHETIC passes).
- Failing input: a snapshot taken from a synthetic fixture, a stale copy, or any other file.
- Demonstrated: probe2_override_bypass.py case (f): `take_snapshot(S-NULL.db, ...)` then
  `_check_snapshot` PASSED with db_class SYNTHETIC and source_realpath ending in S-NULL.db.
- Consequence: the single registered C.2 run (marker written, 9.15) could be spent on the wrong file,
  with every hash consistent.
- Fix: refuse unless `meta["source_realpath"] == os.path.realpath(cfg.real_db)` and the snapshot class is
  NON_SYNTHETIC; record the source's st_size and st_mtime in snapshot.json and show them in run_meta.

### S2. gate.py never verifies the frozen manifest, and the gate log entry carries no manifest hash, so `_check_gate_pass` cannot tell which code produced the PASS it accepts

- Where: news_eval/gate.py:114-186 (no `freeze.check_manifest`, no manifest field in the entry);
  news_eval/run_c2.py:351-378 accepts any line with matching `inputs_sha256`, `pass`, `status` and
  `s_star`.
- Failing input: a gate run under a locally edited cutoff.py or stats.py (or a hand-written JSON line)
  on the frozen snapshot bytes; files restored before `run_c2 run`; the manifest check passes; the forged
  PASS is accepted. 9.15 says the gate "may repeat", so several entries for one hash are expected and
  `passes[-1]` is taken.
- Argued from code (no probe).
- Fix: `gate.evaluate` on a NON_SYNTHETIC database runs `freeze.check_manifest` first and writes
  `manifest_sha256` and the full constants pins into the entry; `_check_gate_pass` requires the entry's
  `manifest_sha256 == facts["manifest_sha256"]` and refuses entries without it; record the gate log's
  sha256 in the marker (already done) and in the snapshot directory.

### S3. The manifest check verifies the `--repo-root` tree, not the modules Python imported

- Where: news_eval/run_c2.py:274-280 `_check_manifest(cfg.manifest, cfg.repo_root)`; run_c2.py:616-621
  and 647-653 let `--repo-root` and `--manifest` name any tree.
- Failing input: `run_c2 run --repo-root <clean clone> --manifest <clean clone>/reports/c1_harness_freeze.json`
  while the imported news_eval/ (from sys.path or cwd) is modified. The tests themselves use
  `--repo-root REPO` with imported modules from REPO, so they would not catch a divergence.
- Argued from code.
- Fix: in `_check_manifest`, also hash `module.__file__` for every `news_eval.*` module in sys.modules
  and compare with the manifest's `files` entries by relative name; refuse when
  `Path(cfg.repo_root).resolve() != freeze.REPO_ROOT` unless an explicit test flag is set.

### S4. Snapshot TOCTOU: hashed at precondition 4, read at compute, never re-hashed, no held connection

- Where: news_eval/run_c2.py:318 (hash) versus :493 `family.compute(cfg.snapshot, ...)` and the second
  open in `family.companion_horizons`. The snapshot is 0444 but its directory is writable, so
  `mv other.db news_experiment_snapshot.db` between the checks and the compute substitutes bytes under
  the recorded hash. `take_snapshot` (run_c2.py:186-189) already re-hashes after its own read; `run` does
  not.
- Argued from code (the mechanism is a plain rename; B1 is the same class via a sidecar).
- Fix: open one connection (with immutable=1) in `_check_snapshot`, record `(st_dev, st_ino)`, pass the
  connection or re-check the inode at every open, and re-hash the file after compute; on any mismatch
  write STOPPED with the reason and never write results.json.

### S5. The run-once property rests on the operator not passing `--marker`; a different marker path (or a deleted marker) recomputes

- Where: news_eval/run_c2.py:289-293 `_check_marker_absent(cfg.marker)`; :651 `--marker` "(tests)";
  VerdictPhase accepts any `run_once_path` (data.py:446). The out-dir check (:397-403) is per
  `--out-dir`, so a rerun with `--marker /tmp/k --out-dir /tmp/o` passes every precondition.
- Argued from code; the test suite relies on these overrides (tests/test_news_eval_run_c2.py:154-156).
- Fix: in `_config`, refuse `--marker`, `--unlock`, `--real-db` and `--repo-root` unless an explicit
  `--test-mode` flag (or an environment variable the tests set) is present, and refuse `--test-mode`
  whenever the snapshot's `source_realpath` is the compiled-in real database. Commit
  reports/c2_RUN_ONCE.json immediately after the run so deletion is visible in git (procedural, for the
  C.2 prompt).

### S6. Verdict row selection: "Clears gross, fails net in every stratum" is selected when the E-tests ABSTAINED, which Amendment 5 says is "not a negative" (lead decision D7; reserved, reported)

- Where: news_eval/verdict.py:423 `if n_clear == 0: selected = ROW_CLEARS_FAILS_NET`. Only `clear` is
  counted; `abstain_interval`, `abstain_floor` and `degenerate` are treated the same as `net_negative`
  and `below_econ_bar`.
- Binding text: EXPERIMENT.md lines 327-340 (Amendment 5, the economic family): the E-tests "are reported
  with intervals whatever they say, and a wide interval spanning zero is an abstention, not a negative";
  line 383's verdict cell asserts "**The signal exists and is not tradeable at taker execution at this
  sizing.**". Amendment 5 itself expects wide E-test intervals ("under-powered relative to the pooled
  primary"), so this case is plausible, and Amendment 5 pre-registered no row for "clears gross, net
  abstains".
- Demonstrated: reports/c1_scratch/task8b/probe8_verdict_mapping.py (probe8.out). Case A (all four
  E-tests abstain_interval) and case B (all four abstain_floor) both select
  `clears_gross_fails_net_every_stratum` and print the "not tradeable" cell. Case C (all net_negative)
  selects the same row, correctly.
- The verdict strings themselves are byte-for-byte correct: every constant in VERBATIM_QUOTES is a
  substring of EXPERIMENT.md, and lines 383 to 388 equal `| <outcome> | <verdict> |` exactly for all six
  rows (checked programmatically, see Coverage).
- Suggested ruling for the lead (not decided here): select ROW_CLEARS_FAILS_NET only when every E-test is
  `net_negative` or `below_econ_bar`; when any E-test is an abstention and none is `clear`, report the
  Amendment 6 row, state "no Amendment 5 net row applies: the E-tests abstained" with the per-stratum
  statuses, and quote Amendment 5's abstention sentence. Whatever is ruled belongs in
  reports/c1_verdict_mapping.md C before the freeze.

### S7. A hard stop after the marker (SIGKILL, OOM, power loss) leaves a marker, no results and no STOPPED file; the registered attempt ends with nothing recorded

- Where: news_eval/run_c2.py:586-611 catches BaseException (KeyboardInterrupt and SystemExit included)
  but nothing can run after SIGKILL; `_check_marker_absent` then refuses forever. The machine has a
  recorded OOM incident (CLAUDE.md).
- Argued from code.
- Decision reserved to the lead: 9.15 forbids "a rerun with changed settings"; whether an identical-
  settings resume is admissible is a pre-registration reading. If admitted, the marker could carry
  status "started" and `_check_marker_absent` could allow one resume iff the marker's manifest, snapshot,
  gate-log and relevance hashes equal the current facts and no results.json or results_STOPPED.json
  exists. If not admitted, document that an OOM kill is a STOPPED verdict with no file, and lower the
  risk: check free memory before compute (CLAUDE.md compute limits) and set OPENBLAS_NUM_THREADS=1.

---

## NOTE

### N1. The synthetic marker is forgeable and blind to in-place value edits (marker.py:25-33)
Demonstrated: probe4_marker.py (probe4.out). (a) `UPDATE news_observation SET excess_1session =
excess_1session * 10` on 3685 rows of a stamped copy: still SYNTHETIC. (b) `marker.write_marker` on the
unstamped stand-in real copy: NON_SYNTHETIC becomes SYNTHETIC, and VERDICT then returns 3684 rows with
NO unlock and NO marker. Hostile only (needs write access and intent). The STATE file already records
the UPDATE residual. Option: have the generator write a sentinel every row carries (for example
`collector_git_sha = 'SYNTHETIC'`) and have `_classify_open` require `COUNT(*) WHERE collector_git_sha
!= 'SYNTHETIC'` to be 0 before calling a database SYNTHETIC; or accept and document.

### N2. A planted `-journal` makes the read-only open fail loudly, not silently (probe5b.out)
`OperationalError: attempt to write a readonly database` from the GATE phase. Denial of service only;
`immutable=1` (B1 fix) removes it too.

### N3. Environment facts outside the manifest: determinism verified; three pins missing
probe6_compute_hash.py (probe6.out): `family.compute` on S-NULL gave the identical sha256
7b0657abc38d63edb5e053d66b1e341eb94d3180851d3d0da11aeb1cb898d7c1 under PYTHONHASHSEED 1, 987654321 and
random; OPENBLAS_NUM_THREADS/OMP_NUM_THREADS 1, 8 and unset; LC_ALL unset and C. Not pinned anywhere:
`sqlite3.sqlite_version` (3.53.1 here), numpy's BLAS build (`np.show_config()`), thread counts. The
bootstrap uses `w @ s_c` (stats.py, a BLAS gemv). Suggest recording all three in run_meta and in the
manifest `pins`, and setting OPENBLAS_NUM_THREADS=1 for the C.2 run as hygiene.

### N4. `python -m news_eval.relevance draw` defaults `--db` to the live database (relevance.py:390) and never calls envcheck
It is guardrail read 3 and the loader pins the six columns, the filter and the date, but the default
means a worker's casual `draw --out x` performs the real read ahead of the lead and outside .venv-eval.
Suggest requiring an explicit `--db` (or `--live`) and calling `envcheck.assert_numpy_sane()`.

### N5. The gate log is plain JSONL that `_check_gate_pass` trusts (run_c2.py:351-378)
Forgeable by hand; its sha256 reaches run_meta only. S2 is the substantive fix.

### N6. The 9.12 condition reads git's committer date (run_c2.py:458-485)
A commit of docs/SUCCESSOR_PREREG_DRAFT.md with a backdated GIT_COMMITTER_DATE after the snapshot would
make it hold. Hostile only. Record the commit sha and author date beside the committer date.

### N7. Story trigger reads an empty scored set as share 0.0, fired False (family.py:693)
A zero from an empty pool. Harmless because an empty set is `abstention_floor` first, but prefer None.

### N8. The stale-pending rule counts observed sessions, not calendar sessions (cutoff.py:183)
Sessions missing from the order (no judged row that day, including the two unrecoverable collection
gaps) shorten the index distance, so a calendar-stale row can be called non-stale and hold S* back. The
error is in the conservative direction only (a smaller analysis set, never a later one).

### N9. n0 and the ANOVA use C_G (every gate cluster) while the pass uses C_dir (stats.py:663, 702)
reports/c1_verdict_mapping.md D1 names them apart; 9.8 writes one C. The difference is clusters whose
scorable rows are all NEUTRAL and is negligible; documented, no change proposed.

### N10. `_readable` widening in `directional_counts_by_cluster` mutates instance state (data.py:645-649)
Restored in `finally`; single-threaded. Verified: `SELECT judgment` is denied again after the call
(probe3.out, GATE section).

### N11. The pre-authorizer window in `_classify_open` runs exactly one statement on a non-synthetic file
Traced (probe3.out): `marker.is_synthetic` executed only `PRAGMA application_id` before returning False.
The LIVE_REAL path never enters `_classify_open`. No row of a real copy is read there.

### N12. `SELECT rowid` is allowed in the RELEVANCE phase (probe3.out)
rowid is the alias of the allowed `id` column; the authorizer reports it as `id`. Not a leak.

---

## Attacks tried that failed (coverage)

- Classification (probe1_classify.py, probe1.out): symlink, hard link and relative path to the stand-in
  real file all LIVE_REAL; `cp`, `cp --reflink=auto` and a copy named `weird?mode=rw#x.db` all
  NON_SYNTHETIC (refused by RELEVANCE, admitted to GATE only with an unlock); the URI builder percent-
  encodes `?` and `#` (no URI parameter injection); `mode=ro` is enforced (CREATE TABLE fails).
- Authorizer with raw SQL bypassing the builder (probe3_authorizer.py, probe3.out), RELEVANCE phase on
  the stand-in LIVE_REAL file: 34 of 38 statements denied, including every outcome and label column in
  SELECT, WHERE, ORDER BY and GROUP BY; COUNT(excess_1session); SUM, TOTAL, MAX, typeof, group_concat,
  ROW_NUMBER and sqlite_version (SQLITE_FUNCTION denied for everything but count); IN and EXISTS
  subqueries and a CTE over outcome columns; sqlite_master, sqlite_schema and the pragma_table_info
  table-valued function; PRAGMA table_info, user_version, journal_mode; ATTACH; CREATE TEMP VIEW and
  TABLE; `SELECT *`. Allowed: `SELECT 1`, `COUNT(*)`, the pinned six-column statement, `SELECT rowid`.
  SCHEMA phase: only `PRAGMA table_info(news_observation)` allowed; `SELECT 1`, `SELECT id`, `COUNT(*)`,
  other PRAGMAs denied. GATE phase on synthetic: judgment, strength, net_bp, ret_1session denied;
  excess_1session and scoring_session allowed by design; judgment denied again after the widening call.
- RELEVANCE phase with `real_db_path` pointed elsewhere refuses the stand-in real file
  (NotSyntheticRefused): guardrail read 3 cannot be widened to a copy.
- Determinism under PYTHONHASHSEED, BLAS/OMP thread counts and locale: identical output (N3).
- Fabrication from absent input, by code reading: NULL excess rows are excluded and counted
  (data.py GateRows.null_excess_count; family.scorable_filter DROP_EXCESS_NULL; D25); NULL net_bp rows
  excluded and counted in E-tests; empty subsets give `degenerate` or `abstain_floor` (stats.py
  `_boot_refusal`, verdict.primary_status/e_status), never a number; a missing p or null diagnostic
  reads as not confirmed / uninformative (verdict.permutation_confirms, null_informative), the
  conservative side; a query_date with zero rows raises; a non-finite result raises in `family._plain`;
  S* None means an empty analysis set and the runner refuses at precondition 5. The one zero-from-empty
  found is N7.
- Look-ahead, by code reading against 9.1, 9.6, 9.7: the day rule is on query_date (D18), the cutoff on
  scoring_session (string ISO order, `<=` in the loader and `>` in family agree), the halves on the
  primary reading's D clusters, the sensitivity reading on the same split; S* comes from counts only,
  the same function in gate.py, family.py and run_c2.py; the gate PASS must carry the same S* as the run.
  compute() never names ret_2/5/10session (ANALYSIS_COLUMNS) and companion_horizons runs only under
  9.12.
- Judgment reaching the gate code: gate.py's import closure (cutoff, data, envcheck, stats) and its AST
  are tested (tests/test_news_eval_gate.py:174-222); `judgment` appears in GATE SQL only inside the
  COUNT of `directional_counts_by_cluster`, where it is a filter and never a group key.
- Verdict text: all 25 VERBATIM_QUOTES are byte-for-byte substrings of EXPERIMENT.md; the six table
  rows at lines 383 to 388 equal `| <outcome> | <verdict> |` exactly, so the table is fully covered.
  Row selection logic matches mapping B and C, D5 (null-intercepted positives are abstentions, not
  powered negatives; verified in probe8 case D) and 9.3 (a significant reversal does not block the
  powered negative). The one mapping divergence from Amendment 5's own text is S6.
- Constants against the binding text: 2.50, 2.24, 0.0125 (Task 5, Amendment 3, Amendment 6); 0.10 and
  30 (Amendment 6); 60, 1000, 30 (Task 5, 9.2); 30 bp and 4.96 bp (Task 5, Task 6, 9.10); 10,000, 11.156,
  0.84 (9.5, 9.8, 9.9, Task 5); 0.80 and 0.10 (Amendment 6, 9.10); 0.20 and 3 (Task 7, 9.7); seeds
  20261010, 20261011, 20261012 and the 9.11 stream order; 8.2 rule (a) symbols. All match.
- Freeze coverage (freeze.py): every file under news_eval/ (schema.sql and the lock included),
  tests/test_news_eval_*.py and the mapping are hashed; unlisted files under those globs and any .pyc
  fail the check; python and numpy versions and every UPPER_CASE constant are pinned and compared at run
  time (so running under .venv's 3.14/1.26.4 refuses). Gaps are S2, S3 and N3.
- Tests and CLI defaults opening the real path: none found. Every test module guards sqlite3.connect
  against the repository file by realpath and inode and points REAL_DB_PATH into tmp; `data schema` and
  `relevance draw` default to the real file for guardrail reads 2 and 3 only (N4).
- Memory: permutation and bootstrap chunks are capped at 1e6 elements (stats.py MAX_CHUNK_ELEMENTS);
  the probes' full computes ran in 8 to 11 seconds on S-NULL.

## Items reserved to the lead

S6 (row selection when the E-tests abstain), S7 (the 9.15 reading of an identical-settings resume) and
D22 (unlock as existence, B2) are decisions the lead owns; this file reports them and does not decide.

## Unfinished or not verified

- The double-run with a different `--marker` (S5) and the rename TOCTOU (S4) were argued from code, not
  run end to end, to keep one heavy computation at a time on the shared machine.
- A hot `-journal` that SQLite would roll back on open was not crafted; the read-only open refuses it
  (N2), so the silent-alteration path through a journal is closed by `mode=ro` already.
- Nothing was run under .venv (forbidden). The probes used .venv-eval only.
- No probe opened the real database; every statement about it is inferred from the stand-in, whose
  header (application_id 0) matches what a real copy carries by the loader's own classification rule.

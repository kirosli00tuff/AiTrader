# Stage C.1 Task 8b re-check: do the fixes close the attacks, and do they open new ones?

Reviewer: LeakageAuditor-FableMax (worker-max on fable), 2026-10-11, after the lead's rulings
(reports/c1_rulings.md) and the two fix records (reports/c1_scratch/fix_harness/fix_report.md,
reports/c1_scratch/fix_verdict/fix_report.md), before the freeze.

Method: the changed functions in news_eval/data.py, gate.py, run_c2.py, freeze.py, relevance.py,
constants.py, verdict.py, report.py and family.py were read in full; every original probe was re-run or
adapted; four new probes exercise the fixed paths with a VALID c2_unlock/1 file and a scratch manifest
written into reports/c1_scratch/task8b/recheck/ (never reports/c2_UNLOCK.json or
reports/c1_harness_freeze.json). NEWS_EVAL_TEST_MODE=1 was set only inside the probes that need an
override. The connect guard on the repository's news_experiment.db stayed in force; the B3 checks on the
repository path use os.stat and realpath only, and the refusals they exercise happen before any
sqlite3.connect (the guard would have raised otherwise). Probe sources and outputs:
reports/c1_scratch/task8b/recheck{1,2,4}_*.py, recheck3_module_main.sh, recheck{1,2,3,4}.out,
probe{1,3,4,6}_recheck.out. The full test suite was not run (the lead's run was in progress).

## Original findings

| finding | status | evidence |
|---|---|---|
| B1 planted -wal changes the bytes read | closed | recheck1.out: GATE phase, gate.evaluate and `_check_snapshot` refuse SidecarPresent for -wal, -shm and -journal, and for a -wal beside the realpath of a symlink; `recheck_snapshot` catches a -wal planted after the precondition; the immutable open with the -wal present reads 7600 = clean and creates no -shm. data.py:262-292 (`sidecars`, `refuse_sidecars`, `_connect_ro(immutable)`), :295-313 (`_classify_open` refuses before the open), run_c2.py:398-454. The live branch keeps plain `mode=ro` and no sidecar check (recheck4.out, data.py:625-628), so guardrail reads 2 and 3 are unaffected by the collector's own WAL. Residual: a swap, read and swap back between the two re-checks is not caught (ruling S4, accepted). |
| B2 unlock and marker checked for existence only | closed | recheck1.out: README, wrong stage, wrong experiment_sha256, wrong or missing manifest_sha256 all refused (UnlockInvalid, naming the field); marker README, wrong sha and missing schema refused (RunOnceMarkerInvalid); `take_snapshot` with README refused (probe2_after_fix.out). data.py:342-410, gate.py:132-157, run_c2.py:366-377. Residuals, both by design and recorded as new NOTEs below: the data layer admits GATE with an unlock lacking `manifest_sha256` (binding is in gate.py and run_c2.py), and a hand-written marker carrying the file's sha256 admits VERDICT. |
| B3 `--real-db` replaced the compiled live path | closed | recheck1.out: `is_live_real(repo db, real_db_path=nonexistent)` True by stat; classify LIVE_REAL without connect; GATE, VERDICT and gate.evaluate on the repository path with the override refuse RealDatabaseRefused before connect; a symlink to it is live; `take_snapshot(source=repo db)` refused in test mode. data.py:90-93, 229-259. |
| S1 snapshot not bound to the real source | closed | recheck2.out: a snapshot of S-NULL with real_db = the stand-in refused at `source_realpath`; outside test mode RunConfig itself refuses non-default paths (config), so the only non-test path to `_check_snapshot` uses the registered defaults and requires NON_SYNTHETIC (run_c2.py:431-451; the fixer's probe_variants_after_fix.out shows the "classifies SYNTHETIC" refusal directly). New NOTE below on snapshot.json being self-attesting. |
| S2 gate PASS not bound to the frozen code | closed | recheck3.out: `python -m news_eval.gate` with the scratch manifest writes `manifest_sha256`; with gate.py's manifest entry altered it refuses with both the files difference and the loaded-module difference, and writes no log line; recheck1.out: an unlock naming another manifest is refused. run_c2.py:474-506 accepts only a PASS with the run's manifest sha. gate.py:132-157, 173-175. |
| S3 manifest check on `--repo-root`, not the imported code | closed | recheck3.out negative run: "loaded: news_eval.gate: news_eval/gate.py sha256 ... != 000..." proves the `__main__` module is checked under its spec name; freeze.py:343-403 (`loaded_module_differences`, `verify`); RunConfig refuses a non-default repo_root outside test mode (run_c2.py:324-346). |
| S4 snapshot TOCTOU | closed (residual accepted) | recheck2.out: untouched passes; a same-bytes swap (new inode) and a touch (mtime only) both raise SnapshotChanged; run_c2.py:767-820 re-checks before and after compute and writes only STOPPED on mismatch. Residual as ruled: no held connection. |
| S5 overrides permit a second run | closed | recheck2.out: `run --marker X` and `snapshot --unlock X` exit 2 outside test mode with nothing written; RunConfig with a non-default marker refused (config); with every default it builds; in test mode a snapshot claiming the repository database as source is refused ("test mode refuses a snapshot of the repository's live database"). `is_test_mode` accepts exactly "1" ("true" and "1 " are not test mode). recheck3.out: `python -m news_eval.gate --manifest` and `relevance draw --real-db` exit 2 outside test mode. data.py:203-218, run_c2.py:870-886. |
| S6 "fails net" row selected when the E-tests abstained | closed as ruled | recheck4.out and probe8_after_fix.out: all-abstain_interval and all-abstain_floor select `clears_gross_net_abstains` with only the Amendment 6 row; all-net_negative keeps the fails-net row; a mixed pattern (net_negative, abstain_interval, below_econ_bar, abstain_interval) selects net_abstains per the ruling; the sensitivity reading uses the same selection; the disagreement statement and the summary render the new value without KeyError; the Amendment 5 sentence is byte-exact in EXPERIMENT.md. verdict.py:440-456, 458-521, 554-559, 620-636; report.py `_net_abstention`; mapping C and D7 revised. The only remaining `VERDICT_TABLE[...]` lookups are guarded (verdict.py:559, 629) or iterate real rows (verdict.py:417, report.py:329). |
| S7 hard kill after the marker | ruled, risk lowered | recheck2.out: `_check_memory` refuses on None (unreadable) and on 1000 MB, passes at 5000 MB; it is the last precondition, before the marker; the marker-present message states the STOPPED reading. run_c2.py:533-557, 559-571, 380-389. No resume path, per 9.15. |
| N1 marker forgeable, in-place edits undetected | open, accepted | probe4_recheck.out unchanged: an edited stamped copy stays SYNTHETIC; a forged marker on the stand-in admits VERDICT with no unlock. Mapping D27 records the residual. |
| N2 planted -journal fails loudly | closed by B1 | recheck1.out: -journal now refused as SidecarPresent before any open. |
| N3 environment pins | closed | freeze.py:181-198 pins and compares sqlite_version, records BLAS; run_meta records versions and thread variables (run_c2.py:680-687). probe6_recheck.out: `family.compute` on S-NULL gives the identical sha256 33ae7f19f6aa6cb80e84fc2dae60384734c0918d9fdab0f556198a35308c29ca under PYTHONHASHSEED 1 and 4242, OPENBLAS/OMP 1 and 8/unset, LC_ALL unset and C; P1 z unchanged at 0.4278526963052854 (the hash differs from the pre-fix 7b0657... only because the JSON gained `net_abstention` and `story.trigger.reason`). |
| N4 relevance draw defaults to the live database | closed | recheck3.out: `draw` without `--db` is an argparse error; `--real-db` outside test mode exits 2 with nothing written; a synthetic draw in test mode works. relevance.py `draw` calls envcheck first. |
| N5 gate log forgeable | closed by S2 | a forged line needs the run's manifest sha; the unlock binds that sha to the manifest file. |
| N6 9.12 committer date | closed | run_c2.py:612-647 requires both author and committer dates before the snapshot and records the sha. |
| N7 story share 0.0 on an empty pool | closed | recheck4.out: `story_trigger([])` gives share None, fired False, reason set, JSON-serialisable; the only consumers read `fired` (family.py:788, 813) or print through `_pct` (report.py). |
| N8 stale rule in data sessions | accepted | ruling 8a NOTE 1 / 8b N8. |
| N9 n0 uses C_G | accepted | mapping D1. |
| N10 `_readable` widening | verified harmless again | probe3_recheck.out: judgment denied after the widening call. |
| N11 pre-authorizer window | verified again | probe3_recheck.out: exactly `PRAGMA application_id` on a non-synthetic file. |
| N12 `select rowid` allowed in RELEVANCE | accepted | alias of the allowed id column. |

## Regression hunt (the lead's list)

- immutable=1 on a file that could change underneath: every non-live open is per `with` block (one
  connection, closed before the next open), so no connection outlives a change; a snapshot that changes
  between precondition 4 and compute, or during compute, is caught by `recheck_snapshot`
  (identity, sidecars, sha256) and ends as STOPPED with nothing but results_STOPPED.json written. The
  live file is never opened immutable (recheck4.out). Argued from code, with the S4 probe as evidence.
- classification order: `_classify_open` and the VERDICT branch of `_Phase.open` call `refuse_sidecars`
  before any open; `_check_snapshot` calls it before hashing (data.py:295-313, 621-650;
  run_c2.py:398-408). Verified by recheck1.out.
- test-mode env leaking into a real run: with NEWS_EVAL_TEST_MODE=1 set, a run on a snapshot of the
  repository database is refused at `_check_snapshot` and at `take_snapshot`; run_meta records
  `test_mode`; "true" and "1 " are not test mode (recheck2.out). Fails safe.
- manifest self-reference: the frozen gate.py verifies the manifest that hashes gate.py; a modified
  gate.py fails both the files entry and the loaded-module entry (recheck3.out), and a rewritten
  manifest fails the unlock's `manifest_sha256` (recheck1.out). The chain unlock -> manifest -> files
  holds; the unlock additionally binds EXPERIMENT.md's sha256.
- loaded-module check under `python -m`: positive and negative runs in recheck3.out; the `__main__`
  module is checked under `news_eval.gate`.
- memory precondition failing open: None and low values refuse (recheck2.out); it runs before the
  marker.
- marker schema and snapshot binding: schema and sha256 checked against the bytes about to be opened,
  hashed after the sidecar check and before connect (data.py:636-645, 385-410; recheck1.out).
- S6 for the sensitivity reading: same `decide_reading`; disagreement and summary handle the new value
  (recheck4.out).
- N7's None reaching arithmetic: no arithmetic consumer; `_pct(None)` prints n/a (grep in this
  re-check; recheck4.out).
- RELEVANCE phase: statement unchanged and pinned (`RELEVANCE_SQL`, six columns, three filter columns,
  `query_date <= 2026-10-09` enforced on the live class); raw reads of judgment, excess_1session,
  scoring_session and PRAGMA still denied (recheck4.out); the live branch opens plain `mode=ro` without
  a sidecar check, so a collector WAL cannot block guardrail read 3.

## New findings

No BLOCKING or SHOULD FIX finding. Four NOTEs.

- NOTE R1. The data layer does not bind the unlock to the manifest: `load_unlock` (data.py:342-383)
  validates five fields and leaves `manifest_sha256` to gate.py and run_c2.py, so
  `data.open_phase("GATE", snapshot, unlock_path=<valid unlock without manifest_sha256>)` admits a
  NON_SYNTHETIC file through the Python API (recheck1.out, last B2 line). The same API admits VERDICT
  with a hand-written marker carrying the file's sha256 (recheck1.out, "residual"). Both need a valid
  c2_unlock/1 with EXPERIMENT.md's sha256, which exists only in C.2, and a caller bypassing the runner.
  Option: have `_admit` require `manifest_sha256` to be present and well-formed (64 hex) even when it
  cannot verify it, and have `check_run_once` also require the marker's `manifest_sha256` to match the
  unlock's. Low priority.
- NOTE R2. snapshot.json is self-attesting: `source_realpath`, `source_st_size`, `source_st_mtime` and
  `sha256` are written by `take_snapshot` and checked only against each other and against
  `realpath(cfg.real_db)` (run_c2.py:398-454). A forged snapshot.json over any NON_SYNTHETIC file passes
  `_check_snapshot` (recheck2.out shows it in test mode; outside test mode the same comparison applies
  with the compiled path). Hostile insider only, and nothing in the harness can verify the source without
  reading the live database, which D21 forbids. Procedural mitigation for the C.2 prompt: commit
  snapshot.json and the gate log immediately, and compare `collection_rows_total` in snapshot.json with
  the CLAUDE.md status-check counts recorded in the C.2 return.
- NOTE R3. In the VERDICT branch of `_Phase.open` (data.py:636-645) the file is hashed (its bytes read
  through open()) after `is_live_real` returned False and before `_classify_open` re-checks the live
  status after the SQLite open. A swap to a link of the live database inside that window would hash the
  live file's bytes once. Hostile race only. Option: re-run `is_live_real` after hashing, or hash from an
  fd whose fstat (st_dev, st_ino) is compared with the compiled live file's.
- NOTE R4. gate.py's log entry does not record `test_mode` (gate.py:160-233), so a PASS produced with
  NEWS_EVAL_TEST_MODE=1 and default paths is indistinguishable from a production PASS. The behaviour is
  identical without overrides, so this is a record-keeping gap: add `"test_mode": data.is_test_mode()`
  to the entry.

Also noted, not a finding: `_ALWAYS_LIVE` (data.py:93) is a module global read at call time, so an
in-process monkeypatch could change it; no test does (grep of tests/test_news_eval_*.py), and a CLI user
cannot.

## Hygiene

No probe opened the repository's news_experiment.db (connect guard in force; the B3 refusals happened
before connect). reports/c2_UNLOCK.json, reports/c2_RUN_ONCE.json, reports/c2/ and
reports/c1_harness_freeze.json do not exist. No .pyc under news_eval/. NEWS_EVAL_TEST_MODE is not set
in the shell. No probe process left running. Files written: reports/c1_review_leakage_recheck.md and
files under reports/c1_scratch/task8b/ only.

# Stage C.1 lead rulings on the Task 8 reviews

Lead: Opus 5.5 (xhigh). Inputs: reports/c1_review_verify.md (8a,
KnownAnswerVerifier-FableXHigh) and reports/c1_review_leakage.md (8b,
LeakageAuditor-FableMax). Every BLOCKING and SHOULD FIX finding is fixed
before the freeze, and the full suite is rerun afterwards. Fix workers:
HarnessFixer-OpusXHigh (loader, gate, runner, freeze, relevance) and
VerdictFixer-OpusXHigh (verdict, report, family). The fix record for each
item is appended below its ruling once the fix is verified.

## 8a (BLOCKING 0, SHOULD FIX 0, NOTE 9)

The independent recompute on S-EFFECT, S-PREMIUM and S-HIGHRHO agreed on
112 of 112 rows.

| finding | ruling |
|---|---|
| NOTE 1 S* staleness counts data sessions | Accept as built (D16). It errs toward an earlier S* and a smaller set, never a later one, and needs no exchange calendar. Open choice. |
| NOTE 2 S* scan includes rows on excluded days | Accept. It follows 9.7's literal text ("no judged collection row is still pending in the snapshot") and errs toward a smaller set. Open choice. |
| NOTE 3 D5 | Kept as built. Reported to the user under Decisions. |
| NOTE 4 S2 clusters include strength-3-only clusters | Accept. 9.2 counts S1/S2 clusters as those holding parse-ok scored rows. |
| NOTE 5 unreachable blocked_by_null on a degenerate null | Accept, no change. It is unreachable from family.compute, and in any case it reads conservatively. |
| NOTE 6 block null within (session, block size) classes | Accept. It is conservative, and the story version does not govern (mapping C.2). |
| NOTE 7 prompt "n0 floored" vs EXPERIMENT.md "rho floored" | Prompt/EXPERIMENT.md contradiction, so EXPERIMENT.md is followed (rho floored). n0 > 0 whenever C_G >= 2. Recorded in the return document. |
| NOTE 8 two encodings of 9.7 (data.py SQL, family.py) | Already covered. The gate's N, M and C and family's counts are pinned to the same SCENARIOS expected counts in 11 scenarios (tests/test_news_eval_known_answers.py), so drift in either fails a known answer. |
| NOTE 9 runtime | Noted for the C.2 ETA. |

## 8b (BLOCKING 3, SHOULD FIX 7, NOTE 12)

### B1 WAL sidecar. FIX.
- Every non-live database (snapshot, synthetic, any NON_SYNTHETIC) is opened `?mode=ro&immutable=1`. That includes the classification open. The live file keeps plain `mode=ro`, because the collector may hold a legitimate WAL there.
- A non-live database with `-wal`, `-shm` or `-journal` beside it is refused before any open (a new LoaderRefusal).
- `_check_snapshot` and `gate.evaluate` refuse the same way.
- snapshot.json and run_meta record that no sidecar was present.
- A planted-sidecar test replaces the header-bytes assertion as the guarantee.

### B2 Unlock and marker checked for existence only. FIX.
- The unlock must parse as a JSON object with these fields:
  - `schema` = "c2_unlock/1"
  - `stage` = "C.2"
  - `approver` (non-empty)
  - `utc_time` (ISO 8601 UTC, ending Z)
  - `experiment_sha256` (equal to the sha256 of EXPERIMENT.md on disk)
  - `manifest_sha256`
- The loader validates the first five fields wherever the unlock is required (GATE and VERDICT on NON_SYNTHETIC, `run_c2 snapshot`). gate.py and run_c2.py also require `manifest_sha256` to equal the sha256 of the manifest they verified.
- The run-once marker must parse with `schema` = "c2_run_once/1", and its `snapshot_sha256` must equal the sha256 of the file VERDICT is about to open, hashed before connect.
- Mapping D22 is revised.

### B3 `--real-db` replaces the compiled live path. FIX.
- A compiled constant for the repository's news_experiment.db is always treated as live (realpath or inode).
- An override adds a fake live path and never removes the real one. The same "add, never replace" rule applies to every entry point.

### S1 Snapshot not bound to the real source. FIX.
- `_check_snapshot` requires `source_realpath` to equal the realpath of the configured real database.
- Outside test mode it also requires the class NON_SYNTHETIC.
- snapshot.json records the source's st_size and st_mtime.

### S2 Gate PASS not bound to the frozen code. FIX.
- `gate.evaluate` on a NON_SYNTHETIC database verifies the manifest first (files, and the loaded news_eval modules per S3) and refuses on any mismatch.
- Every entry carries `manifest_sha256`. It is null only for a synthetic database with no manifest check.
- `_check_gate_pass` accepts only a PASS whose `manifest_sha256` equals the run's verified manifest.

### S3 The manifest check covers `--repo-root`, not the imported code. FIX.
- The check also hashes `__file__` of every loaded `news_eval.*` module against the manifest's `files`.
- A `--repo-root` other than freeze.REPO_ROOT is refused outside test mode.

### S4 Snapshot TOCTOU. FIX.
- The precondition records (st_dev, st_ino, st_size, st_mtime_ns) and the sha256.
- Both are re-checked immediately before compute and again after compute, before any results file is written.
- Any mismatch is STOPPED with its reason, and no results.json is written.
- Opens are immutable (B1).
- Residual: holding one connection open from precondition to compute is not done. With the re-checks before and after, the remaining case is swap, read and swap back between them. That needs hostile intent and is recorded.

### S5 Overrides permit a second run. FIX.
- Test mode is the environment variable `NEWS_EVAL_TEST_MODE=1`.
- In run_c2, gate and relevance, every CLI path override (`--real-db`, `--unlock`, `--marker`, `--repo-root`, `--manifest`) is refused outside test mode.
- run_c2's config refuses non-default values for those outside test mode, so the Python API gets the same rule.
- Test mode refuses any snapshot whose `source_realpath` is the compiled real database.
- Procedural, for the C.2 prompt: commit reports/c2_RUN_ONCE.json right after the run, so a deleted marker shows in git.

### S6 "Fails net in every stratum" selected when the E-tests abstained. FIX (lead ruling; D7 revised).
- Amendment 5, EXPERIMENT.md line 342: "a wide interval spanning zero is an abstention, not a negative". EXPERIMENT.md wins over D7.
- New selection when the gross reading is `clears_gross` and no E-test is `clear`:
  - Every E-test is `net_negative` or `below_econ_bar`: "Clears gross, fails net in every stratum" plus the Amendment 6 row. Task 6 counts below_econ_bar as failing: "fails the economic question even if its interval excludes zero".
  - Otherwise, when any E-test is `abstain_interval`, `abstain_floor` or `degenerate`: no Amendment 5 net row applies. The selection is the new value `clears_gross_net_abstains`. The report gives the Amendment 6 row, every stratum's status, and Amendment 5's sentence quoted verbatim.
- The 1-3 and 4-clear rows are unchanged.
- Reported to the user under Decisions.

### S7 Hard kill after the marker. Ruling: no resume path. Risk lowered.
- 9.15: "Any stop after the marker is a STOPPED verdict with its reason, never a rerun with changed settings." A resume path would be a second compute path, which is what 9.15 forbids. So a kill after the marker (marker present, neither results.json nor results_STOPPED.json) is a STOPPED verdict with reason "process killed". The marker-present refusal message says so.
- Lower the risk with a precondition before the marker: free memory (MemAvailable) of at least 2,048 MB, else refuse with nothing written.
- run_meta records the thread environment variables.
- Reported to the user under Decisions.

### NOTES
| finding | ruling |
|---|---|
| N1 the synthetic marker can be forged by a writer | Accept and document. The attack needs write access and intent, and a copy of the real database, which is itself a guardrail breach. Residual in the return document. |
| N2 a planted -journal fails loudly | Covered by B1. |
| N3 environment pins | FIX. The manifest pins and run_meta add sqlite3.sqlite_version and numpy's BLAS name and version. The freeze check compares the Python, numpy and SQLite versions with the running process. run_meta records the OPENBLAS/OMP/MKL thread variables. |
| N4 relevance draw defaults to the live database | FIX. `draw` requires an explicit `--db` and calls envcheck first. |
| N5 gate log forgeable | Covered by S2. |
| N6 9.12 reads the committer date | FIX. Record the commit sha, author date and committer date. The condition holds only when both dates precede the snapshot time. |
| N7 story share 0.0 on an empty pool | FIX. None, not 0.0. Fired is False and the reason is stated. |
| N8 stale counts data sessions | Same as 8a NOTE 1. Accept. |
| N9 n0 uses C_G | Accept. Mapping D1 names C_G and C_dir apart. |
| N10, N11, N12 | Accept. Each was verified harmless by the auditor's probes. |

## Fix record (verified before the freeze)

| finding | fix (worker; evidence) | verified by |
|---|---|---|
| B1 | data.py immutable non-live opens, `SidecarPresent` before any open; run_c2 `_check_snapshot` sidecar refusal; `sidecars_absent` recorded (HarnessFixer; reports/c1_scratch/fix_harness/fix_report.md) | Fable re-check: closed (reports/c1_review_leakage_recheck.md) |
| B2 | `load_unlock` (c2_unlock/1 fields), `check_run_once` (c2_run_once/1, snapshot sha before connect); gate and run_c2 bind `manifest_sha256` (HarnessFixer) | Fable re-check: closed |
| B3 | compiled live path always live; overrides add, never replace (HarnessFixer) | Fable re-check: closed |
| S1 | snapshot bound to the configured real source; NON_SYNTHETIC outside test mode (HarnessFixer) | Fable re-check: closed |
| S2 | gate verifies the manifest for NON_SYNTHETIC; entry carries `manifest_sha256`; `_check_gate_pass` binds it (HarnessFixer) | Fable re-check: closed, verified under `python -m` |
| S3 | `freeze.loaded_module_differences` (HarnessFixer) | Fable re-check: closed |
| S4 | identity and sha re-check before and after compute, STOPPED on mismatch (HarnessFixer) | Fable re-check: closed (same-bytes swap and touch stop the run) |
| S5 | `NEWS_EVAL_TEST_MODE`; CLI flags and RunConfig overrides refused outside it (HarnessFixer) | Fable re-check: closed |
| S6 | verdict.py `clears_gross_net_abstains`, `net_abstention`, A5 quote in VERBATIM_QUOTES (VerdictFixer); report line "No E-test cleared, so no Amendment 5 row permits trading on this result." (lead) | Fable re-check: selects as ruled on both readings |
| S7 | MemAvailable >= 2,048 MB precondition, fails closed when unreadable; marker-present message; thread variables in run_meta (HarnessFixer) | Fable re-check: refuses on None |
| N3, N4, N6, N7 | sqlite pin and compare, BLAS recorded; `draw --db` required with envcheck; author and committer dates; story share None (HarnessFixer, VerdictFixer) | Fable re-check |

## Re-check findings (LeakageAuditor-FableMax, delta re-check)

No new BLOCKING or SHOULD FIX finding. Rulings on its four NOTEs:

| finding | ruling |
|---|---|
| R1 the loader does not bind the unlock to the manifest | Partly fixed inline by the lead. `load_unlock` now also requires `manifest_sha256` to be present and well formed (64 lowercase hex). Its equality with the verified manifest stays in gate.py and run_c2.py, the only callers that verify one. A hand-written marker with the file's sha256 is accepted as a residual: it needs a valid C.2 unlock and a caller bypassing the runner. Tests: test_news_eval_data.py::test_unlock_field_refused_and_named[manifest_sha256-*]. |
| R2 snapshot.json is self-attesting | Accept. The harness cannot verify the source without reading the live database, which D21 forbids. Procedural item for the C.2 prompt: commit snapshot.json and the gate log right away, and compare `collection_rows_total` with the C.2 status-check count. Goes under Decisions. |
| R3 race between the VERDICT hash and the live re-check | Accept as a hostile-race residual, recorded in the return document. |
| R4 gate entry lacks `test_mode` | Fixed inline by the lead: the entry carries `"test_mode": data.is_test_mode()`. Test: test_news_eval_gate.py::test_log_entry_fields. |

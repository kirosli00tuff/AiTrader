# Stage C.3 rulings

Lead: Opus 5.5, second lead after the planned self-wipe. Written 2026-11-05 from about 22:50 America/Vancouver. Sources: reports/c3_review_diff.md (D), reports/c3_review_runonce.md (R), reports/c3_tests_record.md observations 3 and 4 (T), reports/c3_review_fix.md (F, the check of the fix below).

Both Part C reviewers ran on Fable. Their transcripts read `message.model` claude-fable-5-1 only: DiffReviewer 50 messages, RunOnceAuditor 46.

**The rule applied.** A fix stays inside Amendment 10.1, 10.2 and A5. Without `--hard-stop`, precondition 6 stays exactly as frozen in C.1. A hole that can only be closed outside that goes to the C.2b prompt as a procedural item (the auditor's brief). So one SHOULD FIX is fixed in code, four go to the C.2b prompt, and one is a record fix. Those four are the lead's call and sit under Open choices, for the planner to reverse.

## Every finding

| ID | Level | Finding | Ruling | Action |
|---|---|---|---|---|
| R SF-1 | SHOULD FIX | The first-snapshot and no-PASS checks hold only inside the log named on the command line, and `--gate-log` is caller-chosen | **Accepted, fixed in code** | Under `--hard-stop` outside test mode, RunConfig refuses any log but `GATE_LOG_REL`. Hunks 41 to 43. Normal mode untouched |
| R SF-2 | SHOULD FIX | A later snapshot that passes after the hard-stop FAIL is accepted in normal mode with no label | **Accepted, procedural** | Closing it means changing normal-mode precondition 6, which A3 freezes. Item P1 |
| R SF-3 | SHOULD FIX | A hand-edited log flips precondition 6 and the 10.2 label | **Accepted as a hole, the suggested code fix declined, procedural** | See below. Item P3 |
| R SF-4 | SHOULD FIX | The VERDICT phase opens through the Python API on a forged two-field marker | **Accepted, procedural** | The fix sits in data.py, frozen and outside 10.1, 10.2 and A5. Item P4 |
| R SF-5 | SHOULD FIX | Deleting the marker re-arms the run | **Accepted, procedural** | No in-scope code can see a deleted file. Item P5 |
| D SF-1 | SHOULD FIX | The stat block in the change record is stale | **Accepted, fixed** | Block regenerated from git |
| R N-1 | NOTE | `--ha` and `--hard` select the mode | No change | Every accepted spelling sets the same mode and the marker records it. `allow_abbrev=False` would also change normal-mode parsing. Item P2 spells the flag |
| R N-2 | NOTE | A corrupted future session on a pending-free snapshot arms `--hard-stop` | No code change | A guard would be a new rule, and a rule that needs rows on the hard-stop session could refuse a genuine gap. Item P6 |
| R N-3 | NOTE | `report.write` trusts `run_meta` | No change | Direct API only. The CLI always passes its own |
| R N-4 | NOTE | Non-dict JSON lines in the log are skipped | No change | Same as C.1, harmless to the decision |
| R N-5 | NOTE | `RunConfig.hard_stop` is read by truthiness | No change | Direct API only. The CLI passes a bool |
| D N-1 | NOTE | The timer fires at 00:00 on this clock, so the window rule is an hour early | **Rejected, wrong on the facts** | `timedatectl`: "America/Vancouver (MST, -0700)". `TZ=America/Vancouver date` reads the same as `date`. `systemctl --user list-timers`, 22:39: next fire "Thu 2026-11-05 23:00:58 MST". The 22:55 to 23:45 pause stands |
| D N-2 | NOTE | The verdict test's name still says lines 383 to 388 | No change | Keeps C.1's numbering, and the comment at the anchor states the shift |
| D N-3 | NOTE | Three hard-stop conditions beyond A3's list | **Stand** | Reviewer and lead agree they follow from 10.1 and 10.2. The consequence, no operational slack, goes to item P1 |
| D N-4 | NOTE | PASS sentence in place of the label | **Stands** | Printing NOT met after a PASS would be false |
| D N-5 | NOTE | Label sits after the registered rows and before the statements | **Stands** | The label follows the registered row, as 10.2 says. The statements are quotations |
| D N-6 | NOTE | Identity evidence used a run_meta with no `mode` key | **Closed by a test** | test_the_normal_mode_key_changes_no_report_byte |
| D N-7 | NOTE | The identity hash sorts JSON keys | No change | No key-order change is possible in normal mode, and report text is hashed raw |
| D N-8 | NOTE | Selections without the restriction: sensitivity pair counts, sector flags, relevance sample | No change | As C.1 treats rows beyond S*. None is an outcome-derived quantity |
| D N-9 | NOTE | Stale manifest names in test comments | No change | Outside A5's need |
| D N-10 | NOTE | The real-manifest test skips until the re-freeze | Expected | Part D must show 0 skipped |
| D N-11 | NOTE | cutoff.py adds two functions | No change | `hard_stop_record` selects no rows |
| D N-12 | NOTE | The hook note did not fire for that reviewer | No change | The hook did fire for the lead |
| T obs 3 | Observation | `usable[-1]` decides between conflicting entries, and no test pins it | **Pinned, no behaviour change** | test_the_last_usable_entry_is_the_one_read. Same rule as normal mode's `passes[-1]`. Only a hand-edited log can conflict, and item P3 compares every entry |
| T obs 4 | Observation | Nothing asserts the gross reading of the hard-stop FAIL run | **Closed by two tests** | test_a_powered_negative_on_a_fail_run_meets_the_10_2_interval_rule and test_an_abstention_is_reported_in_those_words |

## Why the SF-3 code fix was declined

The auditor proposed recomputing `gate.evaluate` inside `_hard_stop_gate` and refusing on any difference from the log.

1. **It would not close the hole.** The same forged PASS is accepted in normal mode (the auditor's A5), and A3 freezes that check. Dropping the flag gets past the recomputation and prints no gate line and no label at all.
2. **It adds an outcome-column read to the runner before the marker.** The auditor's E1 shows the runner runs only two COUNT queries there today. That is the strongest form of the check this stage hinges on, and it should stay that way.
3. **It risks refusing the single real run.** The comparison is on floats, across two processes. A false refusal at the hard stop could only be cured by another re-freeze.

The control belongs outside the code: an independent rerun of the frozen gate before the run (P3), against a git-tracked log, with the marker's `gate_log_sha256` tying the run to that log.

## Procedural items for the C.2b prompt

- **P1 (R SF-2, D N-3).** Once a snapshot's S* reaches 2027-01-15, that snapshot is the hard-stop snapshot, and no later snapshot is gated or run. The single run is `--hard-stop` on it. A degenerate gate on it stops the stage for the planner: the code refuses every later snapshot too.
- **P2 (R SF-1, R N-1, F N-2).** Every gate run and the run use `reports/c2/gate_log.jsonl`, spelled relative from the repo root. The command spells `--hard-stop` in full. `--hard-stop` with any other log exits 2 at check config.
- **P3 (R SF-3, T obs 3, F N-3).** Before the run, an independent verifier reruns the frozen gate on the snapshot and compares every log entry for that sha256 with its output, except the time. It also checks the log's git history shows no removed or changed line. The log is committed before the run.
- **P4 (R SF-4).** The verifier confirms no `c2_run_once/1` file exists outside the registered path, and the return states that `family.compute` was called only through `run_c2`.
- **P5 (R SF-5).** The marker and the out-dir go in the same commit as the run, and the return records the marker's sha256 and that commit.
- **P6 (R N-2).** Before the run, confirm S* is not later than the snapshot's date, and compare the count of sessions on or before the hard stop with 120 minus the recorded gaps. Counts only.

## Two things a reader should hold

- **A powered negative can print beside the NOT met label.** S-HIGHRHO at the hard stop does: M is below Required, and P1's upper bound is below 30 bp with no primary clearing. That is what 10.2's third bullet registers, not a defect.
- **The diff review's "16 mutants" is a miscount.** MUTANTS held 15 when it ran. M10, added for R SF-1, makes 16.

## The fix check

FixChecker-FableXHigh, reports/c3_review_fix.md: 0 BLOCKING, 0 SHOULD FIX, 4 NOTE. Its transcript reads `message.model` claude-fable-5-1 only, 27 messages. It tried twelve spellings of the log path through RunConfig and one through `run_c2.main`: every refusal came before anything was written, and every acceptance resolved to the registered file's inode. It read the fix as closing R SF-1, with normal mode and test mode as at c757324 in the compared class. It ran no pytest, because the lead's suite was running.

| ID | Level | Finding | Ruling | Action |
|---|---|---|---|---|
| F N-1 | NOTE | The powered-negative loop has no non-empty guard | **Accepted, closed** | `assert set(readings) == {"primary", "sensitivity"}` added. Test file only, after that review |
| F N-2 | NOTE | A3 does not say another `--gate-log` refuses | **Accepted, procedural** | Item P2 now says exit 2 for any other path |
| F N-3 | NOTE | The pin compares a path, not content, so a pruned or replaced file at that path passes | **Accepted, procedural** | Item P3's rerun covers a changed entry. Item P3 also has the verifier check the log's git history for a removed line |
| F N-4 | NOTE | `GATE_LINE_FIELDS` is in the same diff but was not in this review's scope | No change | Covered by the diff review, N-3 |

# C.3 review: the SF-1 fix (gate log pin under --hard-stop)

Reviewer: FixChecker-FableXHigh (claude-fable-5-1). Written 2026-11-05 22:51
local (`date`), before the collector window. Scope: does the lead's edit close
run-once SF-1 (reports/c3_review_runonce.md lines 26-56), do nothing else to
the harness, and is it really covered by its tests. Everything below was
recomputed from the working tree, `git show c757324:news_eval/run_c2.py`, and
short scripts under the scratchpad (fixcheck/attack.py). No gate or run_c2
run on data, no file under reports/c2* opened, no pytest run (the lead's
suite was running; the 22:54 condition was not reached before the window).

Findings: 0 BLOCKING, 0 SHOULD FIX, 4 NOTE.

## The change (news_eval/run_c2.py, diff against index)

Three edits, as the brief states:
- line 154: `GATE_LOG_REL = "reports/c2/gate_log.jsonl"`, which matches the
  path spelled at docs/prompts/STAGE_C.2.md lines 155, 216 and 248 exactly.
- lines 342 and 357-360: `hard_stop: bool = False` on RunConfig, and in
  `__post_init__`, after the five frozen entries, `if self.hard_stop:
  registered["gate_log"] = freeze.REPO_ROOT / GATE_LOG_REL`.
- lines 71-81: the docstring paragraph under precondition 6 ("Outside test
  mode the log must be GATE_LOG_REL (RunConfig), so those checks see every
  gate run").

## Check 1: refusal outside test mode, through RunConfig and main

Script: scratchpad/fixcheck/attack.py, NEWS_EVAL_TEST_MODE unset
(`data.is_test_mode()` printed False), symlinks created only under the
scratchpad. Results, with `os.path.samefile` against the registered file for
each acceptance:

| gate_log given | result | resolves to registered file |
|---|---|---|
| `reports/c2/gate_log.jsonl`, cwd = repo root | ACCEPTED | yes |
| absolute registered path | ACCEPTED | yes |
| `own_log.jsonl` (relative, other) | REFUSED check=config | n/a |
| `reports/c2/../c2/gate_log.jsonl` | ACCEPTED | yes |
| `..` segments out to a scratch file | REFUSED config | n/a |
| symlink to another file | REFUSED config | n/a |
| symlink to the registered file | ACCEPTED | yes (same inode) |
| path through a symlinked directory (`linkdir -> reports/c2`) | ACCEPTED | yes (same inode) |
| registered path with trailing slash | ACCEPTED | yes (`Path()` strips it; opening it opens the registered file) |
| empty string | REFUSED config | n/a |
| `reports/c2/gate_log.jsonl` with cwd elsewhere | REFUSED config | n/a |
| `reports/c2/gate_log.jsonl.bak` | REFUSED config | n/a |

Every acceptance resolves to the same inode as the registered file, so no
accepted spelling reads a different log. Every refusal happens in
`RunConfig.__post_init__`, i.e. at construction, before `run()` is entered.

Through main: `run_c2.main(["run", "--hard-stop", ..., "--gate-log",
<scratch other.jsonl>, ...])` returned 2 (EXIT_REFUSED), printed `C.2 REFUSED
at precondition config: gate_log='...'` to stderr, and the --out-dir did not
exist afterwards. Code path (run_c2.py lines 963-987): `data.override_refusal`
on the test-only flags, then `_config` which constructs RunConfig and raises
Refused; `run(cfg)` is never reached, so nothing is written. Clean.

## Check 2: the registered spelling and the repository compared against

Relative `reports/c2/gate_log.jsonl` from the repo root (STAGE_C.2.md line
248's spelling) is accepted; from any other cwd it is refused (table above),
which is the correct behaviour since the registered command is run from the
repo root. The pin compares against `freeze.REPO_ROOT / GATE_LOG_REL`, and
`freeze.REPO_ROOT = Path(__file__).resolve().parent.parent` (news_eval/
freeze.py line 62): the repository the code is imported from, the same root
the frozen manifest and repo_root pins already use. Clean.

## Check 3: normal mode identical to c757324

`git show c757324:news_eval/run_c2.py` lines 311-346 against the working tree
lines 330-369: the `registered` dict's five entries (manifest, unlock, marker,
repo_root, real_db) are byte-identical, the comparison
(`os.path.realpath(getattr) != os.path.realpath(want)`) is identical, and the
refusal text (`"... differ(s) from the registered default; path overrides
are test-only (NEWS_EVAL_TEST_MODE=1 is set by the test suite only; C.1
ruling S5)"`) is identical. The only differences are the trailing
`hard_stop: bool = False` field (after `argv`, so every existing keyword
construction is unchanged; `_config` passes it by keyword) and the
`if self.hard_stop:` block. attack.py confirmed: normal mode with
`own_log.jsonl` outside test mode is ACCEPTED, as in C.1. Clean.

## Check 4: test mode never reaches the branch

`__post_init__` line 348: `if data.is_test_mode(): return` precedes the
`registered` dict and the new branch. Existing tests that stage their own log
run with NEWS_EVAL_TEST_MODE=1 and are not refused. Clean.

## Check 5: can the new tests fail, and is M10 real

- M10 (tests/test_news_eval_hardstop.py lines 1332-1335) replaces
  `"    if self.hard_stop:"` with `"    if False:"` in the dedented source of
  `RunConfig.__post_init__`. Verified by script: after `textwrap.dedent` the
  old text occurs exactly once (count_old 1). The mutated function is
  compiled in run_c2's globals and set on the class; the dataclass-generated
  `__init__` calls `__post_init__` by attribute name
  (`RunConfig.__init__.__code__.co_names == ('__setattr__', '__post_init__')`),
  so the monkeypatched method is the one invoked. Under the mutant
  `registered` lacks `gate_log`, `other.jsonl` is accepted, and
  `kill_gate_log_pin` reaches `raise AssertionError(...)`: a real kill.
- apply_edit's dedent (line 1346) is a no-op for every other mutant: for all
  16 other Edit targets `textwrap.dedent(source) == source` and the old text
  still occurs exactly once (script output, 17 edits listed). The
  `edit.module is run_c2` PRECONDITIONS swap is correctly skipped for the
  class target (RunConfig is not the module), and `__post_init__` is not in
  PRECONDITIONS anyway.
- failing_checks (line 1369) catches `Exception`. pytest's `Failed` is
  not an Exception subclass (verified: `issubclass(pytest.fail.Exception,
  Exception)` is False), so a `pytest.fail`/`pytest.skip` inside a kill check
  would propagate and error the test rather than be swallowed. None of the
  kill checks uses them; kill_gate_log_pin uses `assert` and
  `AssertionError`, both Exception. A `Refused` under the unmutated code with
  the wrong reason trips the `assert "gate_log=" in exc.reason` and is
  counted as a failure; a missing env var in `mp.delenv` would raise KeyError
  and be caught, but test_mutant_is_killed first requires
  `failing_checks(...) == []` on the unmutated code, so such a baseline fault
  surfaces. Nothing swallows a real failure silently.
- test_hard_stop_refuses_another_gate_log_outside_test_mode: fails if the
  pin is absent (pytest.raises). test_hard_stop_accepts_the_registered_gate_log
  _outside_test_mode: fails if the registered relative or absolute spelling
  is refused; it chdirs to REPO_ROOT, matching the registered command.
  test_the_cli_refuses_hard_stop_with_another_gate_log: exercises main with
  the data path attributes set to the compiled defaults; asserts rc,
  "precondition config", "gate_log=" and that out does not exist. All can
  fail.
- test_the_last_usable_entry_is_the_one_read: stages a pass-True copy at
  line 1 and the real entry at line 2, asserts line 2 and pass False;
  `usable[-1]` (run_c2.py line 546) is what makes it pass, `usable[0]` would
  fail it. Can fail.
- test_the_normal_mode_key_changes_no_report_byte: writes the report with
  and without `mode` in run_meta and asserts byte equality. Fails if report
  ever prints the key. Can fail.

## Check 6: weakened or vacuous assertions

- test_a_powered_negative_on_a_fail_run_meets_the_10_2_interval_rule (lines
  650-663): the rule is written as `p1_upper < 30.0` and no `P*` status equal
  to `verdict.CLEAR`. EXPERIMENT.md lines 1093-1094 (10.2, third bullet):
  "A powered negative arises only under Task 6's interval rule: P1's upper
  bound below 30 bp and no primary clearing (D5)." The test's rule matches
  the amendment's words. It loops over every reading in
  `fail_run["decision"]["readings"]` and asserts all four conditions for
  each, so it holds for every reading it loops over.
  NOTE 1: the loop has no non-emptiness guard; if the readings dict were
  empty the test would pass vacuously. The sibling test
  test_an_abstention_is_reported_in_those_words indexes
  `readings["primary"]` on the same fixture, so in the suite as it stands the
  dict is non-empty, but the powered-negative test does not assert that
  itself. I could not run the fixture to count the readings.
- test_an_abstention_is_reported_in_those_words (lines 666-674): builds an
  abstention reading by hand and checks the report's wording through
  `report._reading_verdict`. It asserts the constant equals "abstention"
  and that the line "- Gross reading: abstention. " is printed. It does not
  exercise the selection rule (the docstring says so). Not vacuous, not
  weakened.
- test_the_normal_mode_key_changes_no_report_byte: asserts equality of two
  real report renderings; not vacuous.

## Check 7: mapping to Amendment 10.1 and A3

10.1 (EXPERIMENT.md lines 1074-1081): the readout applies "If no gate run
has passed by the hard stop" and the hard-stop snapshot is "the first
snapshot whose S* is on or after the hard-stop session". Both are statements
over every gate run, and `_hard_stop_gate`'s `earlier` check (run_c2.py
lines 536-544) can only see the entries in the log it is handed. Pinning the
log, in hard-stop mode only, to the one file every registered gate command
appends to (STAGE_C.2.md lines 155, 216, 248) is what makes those two
sentences checkable; it is the fix SF-1 proposed and no wider.

A3 (STAGE_C.3.md lines 122-129): "Every other precondition is unchanged" and
"Without --hard-stop, precondition 6 is exactly as frozen in C.1." The pin
lives in the config check (ruling S5's mechanism), not in precondition 6,
and is dead without the flag (checks 3 and 4). Precondition 6's text as
frozen is untouched; the docstring addition is under the new --hard-stop
paragraph only.

NOTE 2: A3's text does not itself say that a hard-stop run with a different
--gate-log is refused. The refusal is a stricter condition than A3 spells
out, in hard-stop mode only; it is justified by 10.1 but should be named in
the C.2b prompt so the operator expects exit 2 for any other log path. This
is a documentation point, not a code change.

NOTE 3: the pin is a path comparison, not a content check. A registered
file that does not hold every gate entry since C.2 (hand-pruned, or a
replaced file at the same path) passes the pin. SF-1 itself listed the
procedural half ("that file holds every gate entry since C.2") as the
companion; the C.2b verifier's rerun of the gate against every entry is the
place that catches it, not this fix. Within SF-1's own scope the fix is
complete.

NOTE 4: `GATE_LINE_FIELDS` (line 158) appears in the same diff but belongs
to the earlier A3 build (the 10.2 gate line), not to this fix; it is not
part of what SF-1 asked for and I did not review it here.

## What I could not check

- No pytest run: the lead's full suite was in progress and `date` did not
  reach 22:54 before the collector window. The kill chain was verified by
  script (mutant text count, dedent no-op on all 17 edits, dataclass
  dispatch), not by running test_mutant_is_killed.
- The number of readings in the `fail_run` fixture (NOTE 1) was not counted;
  that needs the fixture to run.

## Verdict on SF-1

The fix closes SF-1: under --hard-stop outside test mode every tried
spelling that does not resolve to reports/c2/gate_log.jsonl in the running
repository is refused at construction with nothing written, through both
RunConfig and main; every accepted spelling resolves to that same inode.
Normal mode and test mode are byte-for-byte as at c757324 in the compared
class. The tests can fail and M10 is a real mutant. No BLOCKING or SHOULD FIX
finding.

# C.3 review: run-once and hard-stop mode (RunOnceAuditor, Fable 5.1, xhigh)

Date: 2026-11-05 22:30 to 22:50 local. Everything below was run on synthetic
stand-ins (news_eval.synthetic S-HIGHRHO and S-EFFECT, dates shifted by SQL on
copies, synthetic marker stripped so the copy classifies NON_SYNTHETIC) in
temp directories, with NEWS_EVAL_TEST_MODE=1 set inside the audit processes
only and a sqlite3.connect guard that aborts on news_experiment.db or
analysis_bars.db. No real database, no reports/c2* file, no outcome value was
read. No code or test was edited.

Scratch (scripts, raw output, staged trees):
/tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/3a66552d-c1d6-473e-aa89-0ed2d027fbdb/scratchpad/runonce/
- harness.py: staging (synthetic build, shift, demark, unlock, snapshot, gate run); replaces run_c2.run with a stub that runs check_preconditions and write_marker and never computes, so each scenario shows exactly what the preconditions decide.
- attacks.py, attacks.out (scenarios A1 to C2); attacks2.py, attacks2.out (D to E2); h1.py (H1).
- results.json, results2.json: every scenario as (name, outcome, detail).

Mode of reading: "ACCEPTED" means the preconditions passed and the marker was
written in the stated mode; "REFUSED" names the precondition and reason.

## Findings

Severity classes used: OPERATOR (reachable by an operator following the
registered procedure), FORGED (needs a deliberately hand-written or deleted
file), CORRUPT (needs corrupted collection rows).

### SF-1 SHOULD FIX (OPERATOR). The "first snapshot" rule of 10.1 is enforced only inside the gate log file named on the command line, and --gate-log is a required, caller-chosen, unpinned path.

File: news_eval/run_c2.py lines 527-537 (`_hard_stop_gate`, the "earlier" check
over `others`), 931 (`--gate-log` required, no registered default), 341-362
(`RunConfig.__post_init__` pins manifest, unlock, marker, repo_root, real_db;
not gate_log).

Demonstration (attacks2.out): A = S-HIGHRHO shifted 84 days (S* 2027-01-18,
first to reach the hard stop, gate FAIL); F = the same data shifted 85 days
(S* 2027-01-19, a later snapshot, gate FAIL).

    [ACCEPTED] F1 later snapshot --hard-stop, own log only (A's entry elsewhere): hard_stop
    [REFUSED]  F2 later snapshot --hard-stop, shared log holding A's earlier entry: gate_pass | --hard-stop: an earlier gate log entry for another snapshot passed or already reached the hard stop 2027-01-15 (lines [1])
    [ACCEPTED] F3 first snapshot --hard-stop, shared log (A first, F after): hard_stop
    [ACCEPTED] G3 later PASS snapshot (S-EFFECT shifted 85), --hard-stop, own log: hard_stop

With one shared log (the registered reports/c2/gate_log.jsonl of the C.2
prompt) the rule holds (F2, F3). With any other log it does not (F1, G3): a
later snapshot becomes "the hard-stop snapshot". The registered procedure
names the log only in prose (docs/prompts/STAGE_C.2.md 155, 216, 248); the
code does not know it. Mitigating fact: reports/c2/gate_log.jsonl is
git-tracked, so a second log file would be visible in the tree.

Minimal fix inside A3: in hard-stop mode only, refuse when
`os.path.realpath(cfg.gate_log)` differs from a registered default
(`REPO_ROOT / "reports/c2/gate_log.jsonl"`) outside test mode, in
`_hard_stop_gate` or `__post_init__` under `if self.hard_stop`. Normal mode
and precondition 6 as frozen are untouched. Alternatively a procedural line
in the C.2b prompt: the hard-stop run is refused by the operator unless the
--gate-log is reports/c2/gate_log.jsonl and that file holds every gate entry
since C.2.

### SF-2 SHOULD FIX (OPERATOR, procedural for C.2b). After the hard-stop snapshot has failed, a later snapshot whose gate passes is accepted in NORMAL mode, with no hard-stop line and no label.

File: news_eval/run_c2.py 565-580 (normal-mode precondition 6 looks only at
entries for this snapshot's sha256; `others` is never consulted).

Demonstration (attacks2.out), shared log = [A's FAIL at S* 2027-01-18, G's
PASS at S* 2027-01-19]:

    [ACCEPTED] G1 later PASS snapshot, NORMAL mode, log holds A's earlier hard-stop FAIL: normal
    [REFUSED]  G2 later PASS snapshot, --hard-stop, same shared log: gate_pass | ... an earlier gate log entry for another snapshot ... already reached the hard stop

10.1 says the verdict runs once on the hard-stop snapshot when no gate run
has passed by the hard stop; G1 runs it on a later one instead and the report
carries no 10.2 line. Because gate rows and the analysis set are restricted
to scoring_session <= hard stop in both modes (A2, verified in C.3 tests), a
later PASS can only arise from rows on or before the hard stop changing
between snapshots (late resolutions, a changed source_failed day), so the
window is narrow but real. The normal-mode check cannot change (A3: "Without
--hard-stop, precondition 6 is exactly as frozen in C.1"), so this is a
procedural item: the C.2b prompt should state that once a snapshot's S* has
reached the hard stop, no later snapshot is gated or run, and the single run
is `--hard-stop` on that first snapshot.

### SF-3 SHOULD FIX (FORGED). The gate log is unsigned and never recomputed: a hand-edited entry flips precondition 6 and, in hard-stop mode, the printed 10.2 line and label.

File: news_eval/run_c2.py 509-540 (`_hard_stop_gate` reads C, M, required,
sigma, rho, pass from the entry), 565-580 (normal mode); news_eval/report.py
363-376 (`_hard_stop_lines` prints the entry's numbers and chooses the label
from `entry["pass"]`).

Demonstration (attacks.out), the real FAIL entry for snapshot A with only
`"pass": true` changed, or the JSON line given a duplicate `"pass"` key
(json.loads keeps the last):

    [ACCEPTED] A4 hs log: forged PASS only (hand edit): hard_stop
    [ACCEPTED] A4 hs log: duplicate mine FAIL then forged PASS: hard_stop      (usable[-1] wins, line 538)
    [ACCEPTED] A4 hs log: duplicate key pass false then true: hard_stop
    [ACCEPTED] A5 normal log: forged PASS (hand edit): normal
    [ACCEPTED] A5 normal log: duplicate key pass false then true: normal

In hard-stop mode the forged PASS also removes the "registered power rule NOT
met" label and prints "The gate passed on this snapshot" (report.py 373-375;
A9 output). The gate_log_sha256 in the marker records the forged file, so the
forgery is detectable after the fact only by re-running the gate.

Minimal fix inside A3 (hard-stop mode only, before the marker, no new column
read: gate.evaluate reads exactly what the registered 9.8 gate reads, see E2
below): in `_hard_stop_gate`, call `gate.evaluate(cfg.snapshot,
real_db_path=cfg.real_db, unlock_path=cfg.unlock, manifest_path=cfg.manifest)`
and refuse unless its C, M, required, sigma, rho, pass, status, s_star and
analysis_cutoff equal the chosen entry's. Normal mode (A5 lines) stays as
frozen in C.1; that half is a procedural item (the C.2b verifier re-runs the
gate and compares the printed line against the log).

### SF-4 SHOULD FIX (FORGED). The VERDICT phase, through the Python API, opens a NON_SYNTHETIC snapshot on a two-field forged marker at any path; run_c2 is not involved and nothing records the read.

File: news_eval/data.py 391-412 (`check_run_once` checks only `schema` and
`snapshot_sha256`), 602-609 (`_Phase.__init__` accepts `run_once_path` from
any caller; ruling S5's refusal lives only in the CLIs); news_eval/family.py
105-107 (`_phase_kwargs` passes `marker_path` straight through).

Demonstration (h1.py, run against the staged A snapshot and its valid unlock):

    forged = {"schema": "c2_run_once/1", "snapshot_sha256": <sha256 of the snapshot>}
    with data.open_phase("VERDICT", snap, real_db_path=live, unlock_path=unlock, run_once_path=forged) as ph:
        ph.select(("id","scoring_session"), ...)
    -> H1 ACCEPTED: VERDICT phase opened with a forged 2-field marker; rows 7747

On the real tree the same two lines plus `family.compute(snapshot,
marker_path=forged)` would read every outcome column of the real snapshot
without touching reports/c2_RUN_ONCE.json, so the registered run would still
look unrun. This is an outcome-exposure path, not a second verdict file; it
needs a deliberately written file and a deliberate API call. A fix
(check_run_once validating the full c2_run_once/1 body including `mode`,
`manifest_sha256`, `gate_log_sha256`, `utc_time`, `argv`, and refusing a
non-default `run_once_path` outside test mode) is in the C.1-frozen loader,
outside 10.1, 10.2 and A5. Procedural item for C.2b: the verifier confirms
no `c2_run_once/1` file exists anywhere but the registered path and the
return document states that family.compute was never called outside run_c2.

### SF-5 SHOULD FIX (FORGED, procedural). Deleting the marker re-arms the single run; nothing else records that a verdict ran.

File: news_eval/run_c2.py 402-411 (`_check_marker_absent`: `os.path.lexists`),
658-677 (`write_marker`: exclusive create, mode 0o444). The marker is a
0o444 file in a writable directory; `rm` succeeds. reports/c2_RUN_ONCE.json
is neither tracked nor ignored (git check-ignore prints nothing), so its
disappearance is invisible to `git status` unless it was committed first.

Demonstration (attacks.out), same snapshot, fresh out-dir each time:

    [ACCEPTED] A6a first --hard-stop accepted (marker written): hard_stop
    [REFUSED]  A6b retry, same marker left: marker_absent
    [REFUSED]  A6c retry, same marker left, normal mode: marker_absent
    [ACCEPTED] A6d marker DELETED then --hard-stop again (second verdict): hard_stop
    [REFUSED]  A6e marker replaced by {}: marker_absent
    [REFUSED]  A6f marker is a dangling symlink: marker_absent
    [ACCEPTED] A6g run that would STOP (marker written) / [REFUSED] A6h retry after STOPPED: marker_absent

Held paths: a marker left from a normal run blocks a hard-stop run and vice
versa (A6b, A6c); a replaced, empty or dangling marker blocks (A6e, A6f); a
STOPPED run cannot be retried (A6h). Only deletion re-arms. No in-scope code
fix; procedural for C.2b: commit reports/c2_RUN_ONCE.json and the out-dir in
the same commit as the run, and record the marker's sha256 and the commit in
the return document.

### N-1 NOTE (OPERATOR). argparse abbreviation: `--hard`, `--ha` and a repeated `--hard-stop` all select hard-stop mode, and the marker's `argv` records what was typed.

File: news_eval/run_c2.py 918-920 (`argparse.ArgumentParser(prog=...)`, default
`allow_abbrev=True`), 933-936.

    [ACCEPTED] A3 flag form ('--hard',): hard_stop
    [ACCEPTED] A3 flag form ('--ha',): hard_stop
    [ACCEPTED] A3 flag form ('--hard-stop', '--hard-stop'): hard_stop
    [SYSTEMEXIT] A3 flag form ('--hard-stop=1',): 2      (argparse error, nothing written)
    [SYSTEMEXIT] A3 flag form ('--HARD-STOP',): 2
    [SYSTEMEXIT] A3 flag form ('--hard_stop',): 2

The mode cannot be confused (every accepted spelling sets `hard_stop=True`
and `_mode` records `hard_stop`); the exposure is a marker/run_meta argv that
does not literally contain `--hard-stop`. Minimal fix: `allow_abbrev=False`
in `_parser()`. Not precondition 6; applies to both modes only as a parser
strictness change.

### N-2 NOTE (CORRUPT). One judged resolved row with a future ISO-shaped scoring_session, on a snapshot with no non-stale pending rows, moves S* past the hard stop and arms --hard-stop on data that never reached it.

File: news_eval/cutoff.py 168-218 (`compute_s_star`: S* is the last session
before the earliest non-stale pending row, else the last session), 56
(`_ISO_DATE_RE` `^\d{4}-\d{2}-\d{2}$`, so `9999-99-99` passes); run_c2.py
505-508 (the only hard-stop test is `s_star >= HARD_STOP_SESSION`).

Demonstration (attacks2.out), unshifted S-HIGHRHO (sessions end 2026-10-27):

    [INFO] stage D: s_star=2026-10-26 case=before_earliest_nonstale_pending   (one future row added; pending rows still hold S*)
    [REFUSED] D1 --hard-stop with one future resolved row (unshifted data): gate_pass | S* 2026-10-26 is earlier than 2027-01-15
    [INFO] stage D2: s_star=2027-02-02 case=latest_session_no_nonstale_pending C=64 M=2526 (every pending row resolved, then one future row)
    [ACCEPTED] D2 --hard-stop: future row, no pending rows: hard_stop
    [REFUSED] D3 --hard-stop 9999-99-99 session (pending rows present): gate_pass | S* 2026-10-26 ...
    [EXC] stage D4 '2027-1-5': gate REFUSED ValueError: scoring_session must be an ISO date string  (fails closed, no log entry)

D2's accepted run would compute the hard-stop readout on 64 sessions. The
pending rule defends the realistic case (D1, D3): a live collector always
leaves non-stale pending rows near the end. The path needs both a corrupted
row and a pending-free snapshot. Optional cheap guard inside A3: in hard-stop
mode, refuse unless some judged session in `[hard_stop - a few sessions,
hard_stop]` exists in `session_status`, or unless the count of sessions on or
before the hard stop is at least the registered 120 minus excluded days. The
lead decides whether that is a new rule.

### N-3 NOTE (FORGED, API only). `report.write` prints the 10.2 line and label from whatever `run_meta["mode"]` says, and omits them when `run_meta` is None.

File: news_eval/report.py 355-360, 629-651. run_c2 always passes its own
`_run_meta` (run_c2.py 748-750), so the CLI path cannot omit or forge it;
only a direct API call can.

    [INFO] A9 report._hard_stop_entry(None): None
    [INFO] A9 report._hard_stop_entry({"mode":"hard_stop","gate_entry":{...}}): {'pass': False}
    [INFO] A9 _hard_stop_lines(pass=False): ... / Label (Amendment 10.2): registered power rule NOT met.
    [INFO] A9 _hard_stop_lines(pass=True):  ... / The gate passed on this snapshot, so the registered power rule is met and the Amendment 10.2 label does not apply.

Also: a hard-stop run on a snapshot whose entry PASSED is accepted (G3) and
records `mode: hard_stop` while printing the "gate passed" sentence. That is
the C.3 lead ruling, consistent, but a reader of the marker alone sees
hard_stop mode for a run whose gate passed. No fix proposed.

### N-4 NOTE. Non-dict JSON lines in the gate log are skipped silently; blank lines and an unterminated last line are tolerated.

File: news_eval/run_c2.py 551-562 (`[1,2]` and `null` parse, are not dicts,
and are dropped without a message).

    [ACCEPTED] A4 hs log: non-dict JSON line then mine: hard_stop
    [ACCEPTED] A4 hs log: blank lines then mine: hard_stop
    [ACCEPTED] A4 hs log: unterminated last line: hard_stop

Harmless to the decision (the entry still has to be this snapshot's, status
ok, S*- and manifest-matched), but a corrupted log should probably refuse the
way a non-JSON line does (line 557). Normal-mode behaviour is C.1-frozen;
hard-stop mode could add `isinstance(entry, dict)` to the refusal.

### N-5 NOTE (API). `RunConfig.hard_stop` is used by truthiness.

    [INFO] A8c API hard_stop='yes': _mode -> hard_stop ; hard_stop=1 -> hard_stop ; 0, '', None -> normal

run_c2.py 365-367. The CLI always passes a bool. Only a direct API caller can
pass a string; no fix needed, recorded for completeness.

## Paths tried that held

Each line is a scenario in attacks.out or attacks2.out with its refusal.

- A1 normal mode with a status ok FAIL entry after the hard stop: REFUSED gate_pass "FAIL or degenerate entry" (invariant 3 holds at the CLI).
- A2 --hard-stop with that entry: ACCEPTED in hard_stop mode (the intended path).
- B1 S* exactly on the hard stop (shift 81, S* 2027-01-15): ACCEPTED; B2 same snapshot normal mode: REFUSED gate_pass.
- C1 S* one session before (shift 80, S* 2027-01-14): REFUSED "S* 2027-01-14 is earlier than 2027-01-15"; C2 the log entry's s_star and analysis_cutoff forged to the hard stop: still REFUSED, because run_c2 recomputes S* from the snapshot counts (run_c2.py 478-493), never from the log.
- A4 under --hard-stop, all REFUSED at gate_pass with nothing written: pass=1, pass="true", pass=null ("no usable gate entry"); status missing, status="OK" ("degenerate entry"); entry without analysis_cutoff/hard_stop_session (a pre-C.3 entry); analysis_cutoff = S* (an unrestricted gate line); sigma missing; required=null; another manifest_sha256; an entry copied from another snapshot (inputs_sha256 differs) as the only entry; another snapshot's PASS earlier in the log; another snapshot's entry with S* >= hard stop earlier in the log.
- A4 accepted by design: another snapshot's PASS later in the log (not "by the hard stop"); another snapshot's FAIL with S* < hard stop earlier in the log.
- A6b/c/e/f/h marker left, replaced by `{}`, dangling symlink, left after a STOPPED run: REFUSED marker_absent.
- A7 two runs passing preconditions at once: the second `write_marker` REFUSED "marker appeared: another run holds it" (O_EXCL, run_c2.py 197-204, 672-676).
- A8a/A8b outside test mode: RunConfig with non-default manifest/unlock/marker/real_db REFUSED at "config"; the CLI with those flags REFUSED (exit 2) by `override_refusal` before parsing paths. In test mode `_check_snapshot` refuses a snapshot whose source_realpath is the repository's news_experiment.db (run_c2.py 452-454), so NEWS_EVAL_TEST_MODE=1 leaking into the operator's shell cannot run the registered snapshot (it would need a snapshot of a copied database at a non-registered path, which is SF-4's forged-file class).
- D1, D3, D4 (N-2 above): a future or `9999-99-99` session with pending rows present does not move S*; a non-ISO session refuses the gate before any entry is written.
- E1: in a full hard-stop precondition pass the only SQL run before the marker is the two COUNT ... GROUP BY statements of the GATE phase (`query_date, state` and `scoring_session, outcome_state`); no outcome column is selected (invariant 6 holds in run_c2). E2: the separately run gate (registered, before any marker) selects `scoring_session, excess_1session` under the gate filters with `scoring_session <= ?` bound to the analysis cutoff, plus `judgment IN (...)` inside one COUNT, which is exactly 9.8's registered read.
- Restriction (invariant 5): the gate entry on the shifted data carries analysis_cutoff 2027-01-15 and the gate rows / analysis set stop at the hard stop (tests test_no_row_after_the_hard_stop_is_in_the_gate_rows_or_analysis_set, test_gate_counts_match_independent_restricted_sql in tests/test_news_eval_hardstop.py were read, not re-run here; the E2 trace shows the `scoring_session <= ?` bound in the gate SQL). I did not independently recompute the family analysis set under the restriction in this review; see "Not verified".

## Not verified in this review

- A full `run_c2 run --hard-stop` through compute to results.json was not executed here (the stub stops after the marker); the C.3 test suite's fail_run fixture covers it and was read, not re-run.
- The restriction inside family.build_analysis was checked by reading (family.py 344-357, 375-387: `cutoff.analysis_cutoff` in both the drop filter and the judged_beyond count) and by the gate SQL trace, not by an independent SQL recount in this session.
- The hard-stop date itself (constants.HARD_STOP_SESSION = "2027-01-15" against trading_calendar) is outside this brief; analysis_bars.db was never opened.

## Counts

BLOCKING 0. SHOULD FIX 5 (SF-1 operator-reachable via an unpinned --gate-log; SF-2 procedural; SF-3, SF-4, SF-5 forged-file class). NOTE 5.

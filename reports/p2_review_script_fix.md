# Stage P.2: independent review of the SF-1 and SF-2 fix in publish/go_public.sh

Reviewer: FixReview-FableXHigh (Claude Fable 5.1, id claude-fable-5-1, effort xhigh). Brief:
reports/p2_scratch/briefs/D2b_FixReviewer.md. Written 2026-11-07; probes and harness runs 11:40 to 11:59 MST,
report 13:02 MST (times from `date` and file mtimes). I did not write the fix or the D2 review.

Object under review: the uncommitted working-tree change on top of 73aa37a, `git diff 73aa37a -- publish/go_public.sh
publish/checks/test_go_public.sh` (numstat 23/5 and 186/1). Working-tree sha256 prefixes: go_public.sh fb80708cb61ad79b,
test_go_public.sh b4d4583bc3831d69; at 73aa37a c297bec7a6072f78 and ccd2685bfdc8928b. All match the fix report.

Everything ran in /home/kiros-li/.cache/p2-tmp/FixReviewer/ (TMPDIR=/home/kiros-li/.cache/p2-tmp,
XDG_CACHE_HOME=.../FixReviewer/xdg, `nice -n 10`, one harness run at a time). The AiTrader tree was read only (working
tree files, `git show`, read-only `git grep`/`rev-parse`); gh was never run; go_public.sh never ran against a real repo;
no network host was contacted (the harness sets GIT_ALLOW_PROTOCOL=file). publish/research-archive/ was not read.

## Verdict

Both findings are fixed as D2 wrote them. No BLOCKING finding. No SHOULD FIX. Six NOTEs, the first two of which the
lead should read: the config channel (GIT_CONFIG_*) stays open by D2's own instruction, and GIT_TEMPLATE_DIR is one
word that could join the unset list. The diff adds no new path that pushes, force-pushes, rewrites or deletes a ref,
flips visibility, or sets the bio; it touches only lines 58 to 62, 118 to 123 and 158 to 175 of the script.

## 1. Check 1, SF-1: inherited GIT_* variables

**Fixed for the repository-selection class.** go_public.sh:61-62 unsets GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_NAMESPACE GIT_SHALLOW_FILE GIT_GRAFT_FILE at top
level, right after `set -euo pipefail` (57). Lines 1 to 56 are comments; `here`/`aitrader` (75-76) use `cd`/`pwd` only;
the first git invocation in any mode is line 159 (`require_committed`), or 290 in `--build-profile`. Nothing re-sets
any of the nine later (grep: only lines 61-62 name them; 273-276 and 295-297 set GIT_AUTHOR_*/GIT_COMMITTER_* per
command). The builders inherit the cleared environment; build_archive.sh:108 clears a similar list for itself.

Against `git rev-parse --local-env-vars` (git 2.53.0): GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_CONFIG
GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS GIT_DIR GIT_GRAFT_FILE GIT_IMPLICIT_WORK_TREE GIT_INDEX_FILE GIT_NO_REPLACE_OBJECTS
GIT_OBJECT_DIRECTORY GIT_PREFIX GIT_REPLACE_REF_BASE GIT_SHALLOW_FILE GIT_WORK_TREE. The unset covers every one that
selects a repository, work tree, index or object store. Not covered and why that is acceptable: GIT_IMPLICIT_WORK_TREE
is read only together with GIT_DIR; GIT_PREFIX is set by git itself for aliases and hooks; GIT_NO_REPLACE_OBJECTS and
GIT_REPLACE_REF_BASE pick replace refs inside the same repository, AiTrader has none (`git for-each-ref refs/replace`
is empty), the build repos are fresh and the public-repo clone is `--single-branch main`; GIT_CONFIG* is the config
channel, NOTE 1 below.

Harness evidence (my runs, section 4): s17 (GIT_DIR and GIT_WORK_TREE together, dry and real run) and s18 (eight
variables one at a time, dry run) fail 52 checks on the 73aa37a script and pass 70 of 70 on the fixed one; the revert
R1 fails exactly those 52. In the kept 73aa37a sandbox: with GIT_DIR alone the decoy repository's HEAD holds the stub
builders' commits (`archive rebuilt`, `news third`, `news second`, `news first`); with GIT_OBJECT_DIRECTORY alone the
decoy gained 17 loose objects (3 to 20); with both GIT_DIR and GIT_WORK_TREE the decoy was re-initialised
(`warning: re-init: ignored --initial-branch=main`), both builders failed and the dry run exited 1. The harness log
shows the variable reaching the run (`exported for the next run: GIT_DIR=<scenario>/decoy/.git`), so the red result is
not a setup artefact.

### NOTE 1. The config channel stays open, by design. go_public.sh:61-62 (nothing unsets GIT_CONFIG_COUNT/KEY_n/VALUE_n, GIT_CONFIG_PARAMETERS, GIT_CONFIG_GLOBAL, GIT_CONFIG_SYSTEM).

Scenario: an exported `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=url.<x>.pushInsteadOf GIT_CONFIG_VALUE_0=https://github.com/kirosli00tuff/`
sends the script's explicit-URL pushes elsewhere, with every gate passing. Evidence, my sandbox: a `git push
https://github.com/kirosli00tuff/decoy.git main:main` under that environment moved a local bare repo's main; the same
`insteadOf` redirect through a GIT_CONFIG_GLOBAL file sent `ls-remote` of the https URL to the local repo. This is
precisely the mechanism test_go_public.sh uses (go_env, line 292), so it cannot be closed without redesigning the
harness's redirect (for instance a PATH git wrapper that rewrites URLs, which the harness already half has) and
running the script with GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null, which also drops Kiros's own config. D2's
SF-1 fix text says explicitly not to unset GIT_CONFIG_COUNT or GIT_CONFIG_PARAMETERS, and an exported config is no
more powerful than ~/.gitconfig. So: SF-1 as written is fixed completely; the brief's check-1 wording ("config and
push selection") is not fully met, and that is a recorded design choice, not an oversight. The lead decides whether
it stays a NOTE. It is not a regression: 73aa37a and cfcd878 have the same exposure.

### NOTE 2. GIT_TEMPLATE_DIR is not cleared. go_public.sh:292 (`git init -q -b main "$dir"`), 253 (`git_gh clone`).

Scenario: with GIT_TEMPLATE_DIR exported, both the fresh profile build and the public-repo clone are created with that
template's hooks, which then run inside the script's `commit` (297, 275) and `push` (419, 426). Evidence, my sandbox:
`GIT_TEMPLATE_DIR=<dir with hooks/pre-push> git init t1` and `git clone ... t2` both produced `.git/hooks/pre-push`.
A hook is arbitrary code, so this is the same class as PATH or GIT_EXEC_PATH, which no script can close, and the
config forms (`init.templateDir`, `core.hooksPath`) fall under NOTE 1. Still, adding GIT_TEMPLATE_DIR to line 61 costs
one word and removes the environment form. Pre-existing, not introduced by the fix.

### NOTE 3. GIT_DEFAULT_HASH and GIT_DEFAULT_REF_FORMAT are not cleared; the failure mode is closed. go_public.sh:292, 262, 426.

With GIT_DEFAULT_HASH=sha256 the profile build is a sha256 repository. PUBLIC path: `git -C "$work" fetch -q "$build" main`
(262) fails (my probe: rc 128), it is not inside an `if`, so `set -e` ends the run before any push. PRIVATE path:
`cat-file -e` of the sha1 remote id fails (rc 128), `is_fast_forward` says no, the plan is a force-push, and the
`--force-with-lease=refs/heads/main:<sha1>` is rejected at the lease (`cannot parse expected object name`, rc 129, the
remote unchanged). Fail-closed in both paths; no wrong repository, no moved ref.

### NOTE 4. GIT_LITERAL_PATHSPECS makes the HEAD mark check stricter, never looser. go_public.sh:170.

With GIT_LITERAL_PATHSPECS=1 the `:!publish/go_public.sh` and `:!publish/research-archive/` exclusions are read as
literal paths, so the git grep covers all of publish/ (go_public.sh never matches itself: the mark is split). Probe on
the real repository, read-only: rc 1 without the variable, rc 0 with it (1 hit file, the research-archive SOURCES.txt
mark D2's N-5 describes). The direction is a stop, so it is safe. GIT_GLOB_PATHSPECS, GIT_NOGLOB_PATHSPECS and
GIT_ICASE_PATHSPECS keep the prefix match of `publish/` and the exclusions.

### NOTE 5. GIT_AUTHOR_DATE and GIT_COMMITTER_DATE reach the appended commit. go_public.sh:273-276.

plan_append's commit sets the four name and email variables but not the dates, so exported dates would stamp the
appended public commit. build_profile (295-297) sets both dates. Cosmetic: no repository or ref selection changes, the
parent and tree self-checks (278-281) still hold. Pre-existing.

### NOTE 6. Discovery variables are harmless here. GIT_CEILING_DIRECTORIES, GIT_DISCOVERY_ACROSS_FILESYSTEM.

Every git call names its repository with `-C <repo root>` or a path, and the cwd is never excluded by a ceiling
(probe: `GIT_CEILING_DIRECTORIES=<repo> git -C <repo> rev-parse --is-inside-work-tree` prints true). `remote_head`
(208) runs `ls-remote` from the caller's cwd without `-C`; it needs no repository, and repo-local config of whatever
repository the cwd is in would apply, which is the pre-existing behaviour of running from the AiTrader root.

Out of scope for any script, listed so the lead knows they were considered: PATH, GIT_EXEC_PATH, GIT_SSH_COMMAND
(reachable only after a URL rewrite, NOTE 1), GIT_ASKPASS/SSH_ASKPASS, GIT_PROXY_COMMAND and https proxies,
GIT_SSL_NO_VERIFY, LD_PRELOAD. GIT_QUARANTINE_PATH was probed with rev-parse only (rc 0); its documented effect is to
forbid ref updates, which would be a hard stop.

## 2. Check 2, SF-2: the three gate checks

**Fixed, in both modes.**

| Site (fixed lines) | Old behaviour (73aa37a) | New behaviour | Modes |
|---|---|---|---|
| 118-123, step 1 grep | `\|\| true`: exit 2 read as "no marks" | status captured; `> 1` calls `stop` "grep could not read everything under <where> (exit N) ... unchecked" and returns; 0 and 1 as before | real: `die`; dry: recorded, plan still printed, exit 1 |
| 158-164, uncommitted check | `[[ -n "$(git status ...)" ]]`: a failed status gave "" and passed | status and output captured; non-zero status stops "git status of publish/ failed (exit N) ... unchecked"; non-empty output gives the old stop | same |
| 169-175, HEAD marks | `if git grep -q ...`: 1 and 128 both "no marks" | status captured; `case`: 0 stop (marks), 1 pass, anything else stop "git grep of HEAD failed (exit N) ... unchecked" | same |

The `(( grep_rc > 1 ))` and `case` forms are correct under `set -e`: the `|| rc=$?` captures without aborting, and the
assignments are separate from the `local` declarations. In a dry run with a failed `git status`, the uncommitted check
is reported as unchecked and skipped for that run (correct: it cannot be evaluated), and the HEAD check still runs.

Harness evidence: s19 (a mode-000 folder under publish/llm-news-drift/ holding a mark; grep really exits 2 with EACCES,
`git status` does not list it) and s20-status/s20-grep (PATH wrapper makes the named subcommand exit 128) fail 32
checks on 73aa37a and pass 38 of 38 on the fixed script; the reverts R2a, R2b and R2c each fail exactly their own
scenario (12, 10, 10). In the kept 73aa37a sandbox, s19's real run printed `step 1: no confirm marks under publish/`,
pushed all three repos (hook: llm-news-drift ff, research-archive NONFF, kirosli00tuff ff), PATCHed the bio and made
research-archive public (2 MUTATE calls), with a mark sitting in the unreadable folder; s20-status's real run exited 0
with the same two mutations after `fatal: test_go_public.sh made git status fail`. Both are the exact failure D2
described. All six precondition checks pass on both scripts, so the red results come from the gates.

**Every other check that gates a push, flip or bio change, traced for error direction (fixed line numbers):**

| Line | Check | On a tool error |
|---|---|---|
| 113 | `left_out` count of archive marks, `2>/dev/null \|\| true` | Informational `say` only; the archive is excluded from the gate and skipped in steps 4, 6, 7 in that state. Not a gate. Fix report 9 says the same. |
| 133-152 | check_scope: `command -v gh`; `gh api -i /user \| tr \| awk` under pipefail; scope test | Missing gh: stop. gh failure: pipeline fails, stop. No header: scopes empty, stop/exit 1. Closed. |
| 179 | archive_on_github: `gh repo view ... >/dev/null 2>&1` | Failure = "no repo": the archive is skipped (no push, no flip) and its marks are left out of steps 1 and the HEAD check, which matters only for the skipped repo. Documented in the header (44-48). Pre-existing, direction safe. |
| 188-198 | read_visibility | Failure, empty, other: stop. Closed (s06, M05, M06, M16). |
| 208, 221, 244 | remote_head under pipefail, `if ! old=$(...)` | ls-remote failure: stop. Closed. |
| 213-215 | is_fast_forward: `cat-file -e \|\| return 1`; `merge-base --is-ancestor` | Any error reads as "not a fast-forward": news stops; private plans a lease-guarded force; public is never here. Conservative. |
| 253, 257 | clone in `if !`; HEAD != old | stop, stop. Closed. |
| 262-263 | fetch, read-tree outside `if` | `set -e` ends the run. Closed. |
| 266 | `if git diff --cached --quiet` | An error (>= 2) reads as "changes": the commit then runs; an empty commit fails without `--allow-empty` (`set -e`), and 278-281 die unless parent == old and tree == the build's. Closed by the self-checks. |
| 290-291 | `git log -1 ... README.md` outside `if`; empty date dies | Closed. |
| 336, 348 | plan_bio: bio.txt read under pipefail in `if !`; `gh api /user --jq .bio` | Unreadable bio.txt: stop. Unreadable current bio: bio_plan=change, the bio is PATCHed after the pushes (idempotent, line 521, never early). Pre-existing, direction is more action but harmless. |
| 400-401 | confirm: `read -r \|\| answer=""`, exact match | Closed (s15). |
| 422-424 | force re-check: `\|\| now=""`, must equal PRIVATE | Closed (s06-race, M13). |
| 450-456 | finish_dry_run: any recorded stop exits 1 | Closed. |
| 482 | `aitrader_sha=$(git rev-parse --short HEAD)` outside `if` | `set -e`. Closed. |

No other gate reads a grep, git or gh error as clean in the permissive direction. shellcheck `-o all` SC2312 sites left
in the fixed script (126, 208, 253, 257, 278, 280, 298, 397, 398, 461) are counts inside messages, the pipelines above
that `if !` plus pipefail catch, self-checks that die on mismatch, or `archive_state` (always exits 0 printing yes/no).

Minor, agreed with fix report 9: when grep exits 2 and also found marks, the error message replaces the hit list. The
run stops either way; a rerun after the error is fixed shows the marks.

## 3. Check 3: no new unsafe path

The script diff is four hunks: 58-62 (comment and unset), 118-123, 158-164, 169-175. Steps 3 to 7 (lines 178-536) are
byte-identical to 73aa37a. Order unchanged: check_marks 471, check_scope 472, require_committed 473, visibility 480,
builds and plans 485-493, dry run exits at 497, confirm 509, pushes 511-517, bio 520-524, flips 526-533. So: no new
force-push, rewrite or delete (the only force is 426, PRIVATE only, lease-guarded, re-checked at 422-424); no push
without the mark check (check_marks runs before any build in every mode but `--build-profile`, which pushes nothing);
the bio is set after the pushes and never in a dry run; step 6 flips every repo in the plan that GitHub reports
PRIVATE, which is P.1 behaviour, unchanged by the fix (in the current real state llm-news-drift and kirosli00tuff are
PUBLIC and are left alone; research-archive is the one PRIVATE repo). Harness: all 220 original checks pass on the
fixed script, and M02, M03, M04, M11, M12, M13 and M18 (force on append, dry-run push, flip already-public, news force,
public rebuild, no force re-check, dry-run bio) are still caught.

The new harness code adds no production path: the git wrapper's `git_fail` branch is active only under STUB_STATE
(inside go_env), `run_gp_env` exports with `local -x` so nothing leaks past the function, and `make_decoy` and
`dir_digest` touch only the scenario folder. `dir_digest` hashes path, type, mode and content, not mtimes, so reads of
the decoy do not count as changes and writes to its index, objects or refs do. The wrapper's `-C`/`-c` skip handles
the two-argument forms the script uses; the joined `-ck=v` form would be mis-parsed, and the script never uses it.

## 4. Check 4: harness and mutants (my runs, sandbox copies)

Method: for each variant, a throwaway git repo under .../FixReviewer/variants/<name>/ with the cfcd878 baseline
committed as publish/go_public.sh (so s09 reads it with `git show` from that repo, GO_PUBLIC_BASELINE set to that
commit), then the variant script and the fixed harness written in place, and `nice -n 10 publish/checks/test_go_public.sh`.
The runner is .../FixReviewer/run_variants.py (the original go_public_mutants.py anchors, applied to the fixed
script, plus the four reverts from ScriptFix/make_mutants.py, both reproduced rather than reused); logs in
.../FixReviewer/logs/<name>.log; summary in .../FixReviewer/summary.txt. 24 runs, 11:48 to 11:59 MST, 18 to 42 s each.

| Variant | Result | Failures by scenario |
|---|---|---|
| FIXED (working tree) | 340 passed, 0 failed, exit 0 | none |
| C1_73aa37a (unfixed) | 256 passed, 84 failed, exit 1 | s17 14, s18-GIT_DIR 6, -GIT_WORK_TREE 5, -GIT_INDEX_FILE 6, -GIT_OBJECT_DIRECTORY 6, -GIT_COMMON_DIR 6, -GIT_NAMESPACE 5, -GIT_SHALLOW_FILE 2, -GIT_GRAFT_FILE 2, s19 12, s20-status 10, s20-grep 10. s00 to s16: 0 failures (220/220) |

s17 to s20 therefore fail against 73aa37a and pass against the fixed script, as the brief asks. Counts equal the fix
report's section 4.

Original mutant set (go_public_test.md section 4), anchors applied to the fixed script, against the 340-check harness:

| Mutant | Result (original 220-check result in brackets) |
|---|---|
| M00 identity | = FIXED, 340/0 (220/0) |
| M01 baseline cfcd878 | 172 failed (99) |
| M02 append push with --force | 4 failed: s02 2, s03 1, s14 1 (4) |
| M03 dry run pushes | 40 failed (18) |
| M04 flips already-public | 5 failed (5) |
| M05 failed lookup read as PRIVATE | 8 failed (8) |
| M06 empty answer read as PRIVATE | 4 failed (4) |
| M07 no diff still commits | 9 failed (9) |
| M08 bio patched when equal | 6 failed (6) |
| M09 tree replace keeps dropped files | 3 failed (3) |
| M10 no trailer | 3 failed, s17 now checks the message too (2) |
| M11 news may force | 3 failed (3) |
| M12 PUBLIC step 4 rebuilds | 99 failed (62) |
| M13 no force re-check | 6 failed (6) |
| M14 real run skips the mark check | 16 failed, s19 adds 11 (5) |
| M15 real run skips the committed check | 32 failed, s20 adds 20 (12) |
| M16 INTERNAL accepted | 7 failed (7) |
| M17 force branch without its PRIVATE test | **survived**, 340/0 (survived) |
| M18 dry run sets the bio | 12 failed (8) |

Caught 17 of 18, missed 1 (M17). M17 is the equivalent mutant D2's N-7 verified by reading: `plan_rebuild ... yes` is
reached only from the `PRIVATE)` branch at line 328, so the inner test at 234 sees no other value; I confirmed the same
two lines in the fixed script. The new scenarios raise the sensitivity to the gate mutants (M14, M15) and to anything
that breaks the expected plan (M01, M03, M12), which is the right direction.

Fix author's reverts: R1_no_unset 288/52 (s17 and the eight s18 only), R2a_step1_grep_or_true 328/12 (s19 only),
R2b_status_vacuous 330/10 (s20-status only), R2c_head_grep_if 330/10 (s20-grep only). Each revert fails exactly its
matching scenario, as the fix report's section 6 claims.

## 5. Check 5: lint

`bash -n` passes on both files. shellcheck 0.11.0 (/home/kiros-li/.cache/p2-tmp/scvenv/bin/shellcheck, offline) at
default settings: both files exit 0 with no findings. With `-o all`, go_public.sh: SC2250 271 (brace style), SC2310 12,
SC2312 11, SC2249 1; at 73aa37a: 264, 12, 12, 1. On the changed lines the only `-o all` notes are SC2250; the three old
gate sites no longer carry SC2312.

## Not checked

- The real extract.sh and build_archive.sh under the fixed script (stub builders stand in, as in every harness run);
  the real builders are exercised first by E3. Same gap as D2's N-7.
- gh was never run and GitHub never contacted; the real repos' state was read only through the fix report's section 8.
- A real index or object corruption behind the `git status` and `git grep` gates: s20 injects exit 128 through the
  PATH wrapper. The grep failure (s19) is a real EACCES.
- GIT_QUARANTINE_PATH beyond a rev-parse probe; the out-of-scope variables listed at the end of section 1.
- The harness in place (from the AiTrader tree): only sandbox copies were run here. The fix report ran it in place
  with the same sha256 and 340/0.
- publish/research-archive/ working-tree state (another worker is editing it; excluded by the brief).
- That GIT_ALTERNATE_OBJECT_DIRECTORIES has no scenario (it only adds objects to read; the fix report dropped a check
  that could not fail). Accepted by reading, not tested.
- The harness's s19 relies on not running as root; its precondition check guards it, so this is only a note that the
  scenario would report a setup failure, not a false pass, under root.

## Sandbox leftovers, kept for inspection

/home/kiros-li/.cache/p2-tmp/FixReviewer/ (97 MB): run_variants.py, runner.out, summary.txt, logs/ (24 harness logs),
variants/ (24 throwaway repos), probes/ (the sha256, template-dir and config-redirect probes), go_public_73aa37a.sh,
and the kept 73aa37a harness sandbox xdg/p2-tmp/go_public_test.VnkW7g (s17, s18-*, s19, s20-* folders with run
outputs, state logs and the decoy repos). The other 22 harness sandboxes were deleted by the runner with
`find <absolute guarded path> -mindepth 1 -delete` plus `rmdir`.

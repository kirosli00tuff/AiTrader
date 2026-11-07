# F5 review of R53 and R54: FixChecker2-FableXHigh (Fable 5.1, claude-fable-5-1), 2026-11-07 08:46 to 08:52 MST

Independent, read only. Inputs: reports/p1_rulings.md R50, R53, R54. reports/P.1_STATE.md planner note (08:38) and the
GateFix returns at 08:40 and 08:42. docs/prompts/STAGE_P.1.md lines 612-629 (H6). The R54 rerun section of
reports/p1_scratch/go_public_test.md and reports/p1_scratch/kept_evidence/GateFix__test_output.txt (40 PASS, 0 FAIL in
that file). Base for the diff: reports/p1_scratch/fixcheck_base/go_public.r50.sh, which is byte-identical to
bb09341:publish/go_public.sh. Temp work under /home/kiros-li/.cache/p1-tmp/FixChecker2/, deleted at the end.
I wrote my own stub gh and my own trees, not GateFix's. The real gh was never called. Nothing under publish/ was edited.

Grades: BLOCKING 0, SHOULD FIX 0, NOTE 6.

## 1. R54, step 1 (check_marks)

Diff of go_public.r50.sh (210 lines) against publish/go_public.sh (232 lines, sha256 de7004f4b5d6485b...). Five hunks:
header comment (lines 11-12 and 23-25), check_marks (57-73), require_committed (89-101), new archive_state (107-109),
and main (186 and 192-199). bash -n clean. shellcheck 0.11.0 (GateFix's extracted binary, read only): 0 findings.

What the code does, read line by line:
- archive_state prints yes or no from the unchanged archive_on_github (`gh repo view kirosli00tuff/research-archive`).
- main computes with_archive once, before step 1, and passes the same value to check_marks, require_committed, the
  main skip line, the public list, step 4, step 6 and print_web_steps. --check-only calls check_marks with the same
  function's answer. So --check-only and the full run use one decision.
- check_marks with no: counts the marks under publish/research-archive/ (lines, grep -rnF, `|| true` inside the group
  so a zero count survives set -e and pipefail), prints one say line with that count, and adds exactly one option to the
  main grep, `--exclude-dir=research-archive`. Nothing else is added to the skip array. With yes the array is empty, the
  grep is the R50 grep, and the text is the R50 text ("under publish/").
- --exclude-dir matches by directory base name. find shows exactly one directory of that name under publish/, and no
  symlinks. The command-line argument is publish/ itself, so the exclusion cannot touch it.
- Child bash resolves grep to /usr/bin/grep (GNU grep 3.12). Kiros's ~/.bashrc only aliases grep for colour, which a
  script does not inherit.

Steps 2 to 7 and --build-profile: sed-extracted bodies of check_scope, archive_on_github, confirm, remote_head,
is_fast_forward, push_build, build_profile, set_bio and print_web_steps diff empty against the base. main from
`local public=` to the end is identical to the base. The main skip line keeps its R50 text and position.
--help prints all 30 header lines, including the new ones.

Proofs, run from the temp copies with my stub gh (logs every call, answers `api -i /user` with configurable scopes,
answers `repo view`, fails the archive repo view when STUB_ARCHIVE=missing, exits 99 on anything else). extract.sh in
every copy was replaced by a guard that exits 1, so no run could get past the prompt. Copied script cmp-identical to
the repo's. Trees: tr (copy of the real tree, 38 marks: 20 archive, 18 outside), ta (the 18 outside marks replaced
by [RESOLVED], 20 archive marks left), tb (ta plus one planted mark at publish/llm-news-drift/README.md:92).

| Run | Tree, gh state | Exit | Key output |
|---|---|---|---|
| C0 | tr, archive missing | 1 | skip line "(20 confirm marks there)", then 18 hits listed, "18 confirm marks remain under publish/ outside publish/research-archive/" |
| Ca (a) | ta, archive missing | 0 | skip line (20), "step 1: no confirm marks under publish/ outside publish/research-archive/", "step 2: gh has the user scope" |
| Cb (b) | tb, archive missing | 1 | skip line (20), one hit tb/publish/llm-news-drift/README.md:92, "1 confirm marks remain under publish/ outside publish/research-archive/", step 2 not reached |
| Cc (c) | ta, archive present | 1 | no skip line, 20 hits, all 20 under publish/research-archive/, "20 confirm marks remain under publish/. Resolve each one" |
| Cd | ta, missing, scopes without user | 1 | step 1 passes, step 2 prints `gh auth refresh -h github.com -s user` |

gh calls per run: C0, Cb, Cc: repo view only. Ca, Cd: repo view, then api -i /user. These match GateFix T1, T11, T13,
T12 and T2.

## 2. R54, require_committed (lead decision 08:41)

Code: the function takes with_archive. The uncommitted-changes check (`git status --porcelain -- publish/`) is the R50
line, unchanged. The HEAD check keeps `publish/ ':!publish/go_public.sh'` and, with no, appends the pathspec
`:!publish/research-archive/` and changes the refusal text to "under publish/ outside publish/research-archive/".
With yes the pathspec and the text are the R50 ones.

Full-run proofs on temp git repos (each publish/ committed, stub gh, stdin "no" at the prompt):

| Run | Repo, gh state | Exit | Key output |
|---|---|---|---|
| Fa | ra: 20 archive marks committed, missing | 1 | steps 1 and 2 pass, require_committed passes, main skip line, prompt lists "llm-news-drift kirosli00tuff", "stopped. Nothing was changed." |
| Fb | rb: ra plus one mark under llm-news-drift committed, then removed from the working copy and hidden with update-index --skip-worktree (git status 0 lines), missing | 1 | steps 1 and 2 pass, "HEAD still holds confirm marks under publish/ outside publish/research-archive/. Commit the resolved files first.", no prompt |
| Fc | rc: as ra, present | 1 | step 1 refuses on the 20 archive marks, no prompt |
| Fc2 | rc with the 19 archive files skip-worktree and their marks removed from the working copy (HEAD only), present | 1 | step 1 "no confirm marks under publish/", step 2 passes, "HEAD still holds confirm marks under publish/. Commit the resolved files first.", no prompt |
| Fc3 | same repo as Fc2, missing | 1 | archive HEAD marks left out, require_committed passes, stops at the prompt |
| Fd | rd: ra plus an uncommitted edit to publish/profile/bio.txt, missing | 1 | "publish/ has uncommitted changes. The builds read committed files: commit them first." |
| Fe | ra, missing, empty stdin | 1 | exits at `read -r` under set -e before the guard, nothing ran |

Harness totals: 51 checks pass, 0 fail (exit codes plus fixed-string text checks). 0 unexpected stub gh calls in 12
runs. The guard never fired. Real publish/ after: 38 marks, no planted line, git status shows only
` M publish/go_public.sh`. Fb, Fc2 and Fc3 match GateFix T11-full-head, T11-full-present and T11-full-archhead.

H6 says step 1 refuses on any mark under publish/. The code now leaves the archive out while the archive repo view
fails. That deviation is the lead's R54 choice under the planner's 08:38 note, and the header comment, the step 1
line and the require_committed refusal all state the scope, so Kiros can see it.

## 3. R53, publish/checks/test_scan_history.py at bb09341

The pre-R53 text exists as an unreachable blob, c414e98b0a6eec9748eefd070c52b557b3f09190, found with
`git fsck --unreachable --no-reflogs` (the blocked commit's `git add` wrote it, no commit holds it). It is 447 lines,
HEAD's file is 448, and the working tree equals HEAD. Unified diff, blob to HEAD, one hunk at line 445: 1 line removed,
2 lines added. The removed line was one string literal (the plain literal that follows the f-string part of `text`).
The added lines are the comment `# Split literals: same runtime string, and the repo secret hook does not see an sk-
run.` and the same literal split into three pieces: `"risk"`, `"-adjusted-return-calculation-function-name\nsk"`,
`"-learn-is-a-python-library-name-here\n"`. Both junctions end in `sk` and start with `-`.

Runtime proof, in memory only: `ast.dump(ast.parse(blob)) == ast.dump(ast.parse(HEAD))` is True (the parser folds
adjacent literals and drops comments, so an identical AST means identical bytecode constants and no other change).
The `text` JoinedStr's last Constant is 87 bytes in both, sha256 prefix 7ba0ca09aec4f130 in both. Re-derived from
HEAD's source with tokenize: the three pieces evaluated separately and concatenated are 86 bytes (sha256 prefix
00763adf03c8b6d1), and one newline (the f-string's own trailing `\n`, which the parser folds into the same constant)
plus those 86 bytes gives the 87-byte constant with sha256 prefix 7ba0ca09aec4f130. The hook pattern
`sk-(ant-)?[A-Za-z0-9_-]{16,}` (ops/check_secrets.sh line 29) matches 1 line of the blob (2 matches on it) and 0 lines
of HEAD, and still matches twice inside the runtime string, which is what the negative-control test needs.

Test run: `PYTHONDONTWRITEBYTECODE=1 nice -n 10 .venv/bin/python -m pytest -q -p no:cacheprovider
--basetemp=<my temp>/pytest-tmp publish/checks/test_scan_history.py` (Python 3.14.4, pytest 9.1.1): 21 passed in
2.16 s. No .pyc under publish/checks and no .pytest_cache afterwards.

## 4. Findings

- N1 (NOTE, wording). R53 says the lead "split both literals". The blob shows one literal, split at its two sk- runs
  into three pieces. The code is right. No action needed, unless the rulings text wants "one literal, split at both
  runs".
- N2 (NOTE, same as R52 N4). archive_state answers no on any failure of `gh repo view`: gh missing, not logged in, a
  stale session bus, no network. The step 1 line then gives "no GitHub repo yet" as the reason. Safe direction: the
  same answer keeps the archive out of steps 4, 6 and 7, so no repo is published with unchecked marks, and step 2 then
  stops on a broken gh. No action.
- N3 (NOTE). `--exclude-dir=research-archive` is matched by base name at any depth, while the git pathspec
  `:!publish/research-archive/` is anchored. Today publish/ has exactly one directory of that name. A future folder
  of the same name elsewhere under publish/ would be left out of step 1 but not of the HEAD check. No action now.
- N4 (NOTE). `"${skip[@]}"` on an empty array under `set -u` needs bash 4.4 or later. This machine runs bash 5.3.9,
  and the archive-present runs (Cc, Fc, Fc2) exercised that path. No action.
- N5 (NOTE, pre-existing, not R54). With an empty stdin at the prompt (Fe), the script exits 1 from `read -r` under
  set -e with no "stopped" line. Nothing runs. No action.
- N6 (NOTE). "N confirm marks" counts lines, not files: 20 lines in 19 files under the archive. The planner note says
  19 files and GateFix says 20 marks. Both are right. The refusal count uses the same line count. No action.

## 5. Not checked

Steps 3 to 7 never ran, by design (H6 tests steps 1 and 2 only). The real gh was not called. I ran the hook's regex
over the file rather than the hook script itself, which reads the index. shellcheck ran from GateFix's extracted
binary, not an installed one. Cleanup: `find /home/kiros-li/.cache/p1-tmp/FixChecker2 -mindepth 1 -delete`.

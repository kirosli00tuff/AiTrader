# Stage P.1 review F4: post-F3 doc wave check (FixChecker-FableXHigh)

Reviewer: FixChecker-FableXHigh (worker-xhigh, Claude Fable 5.1, claude-fable-5-1). Read only. 2026-11-07, 08:18 to 08:25 MST.

Brief: reports/p1_scratch/briefs/FixChecker-FableXHigh.md with COMMON.md. Inputs read: reports/p1_rulings.md R19, R39 to
R42, R46 to R51. reports/p1_review_claims.md S5, N1 to N3. reports/p1_scratch/docfix_drift_report.md. The R50 rerun
section of reports/p1_scratch/go_public_test.md. Every number below is recomputed from the raw inputs with my own
commands. Scripts and outputs are in /home/kiros-li/.cache/p1-tmp/FixChecker/. No gh command ran. No name, reason
text, rule literal or headline is printed here.

## Verdict

The doc wave made exactly the ruled changes, each true to its source, and changed nothing else in the public tree.
Findings: BLOCKING 0, SHOULD FIX 0, NOTE 4. None needs action before G1. N1 is already applied in the working file
(R51) and G2 must build from the working file, not from DocFixDrift run1.

## 1. llm-news-drift: DriftRules run1 (before) against DocFixDrift run1 (after)

Builds: before /home/kiros-li/.cache/p1-tmp/DriftRules/run1, HEAD fe6686c652606d60ca2e1442619f8f998e22f41a. After
/home/kiros-li/.cache/p1-tmp/DocFixDrift/run1, HEAD 7b3de381d058bf34210e3fae1da1783c75430f76. Both: 50 commits, one
ref (refs/heads/main), `rev-list --all` 50, `status --porcelain` 0 lines.

History before the last commit: `git rev-list HEAD~1` gives 49 commits in each build, and the two lists are identical
(sha256 of the list 76fcd384f58382ca1ab13a5450c0ae59617b2d7c5a59bf0a184c8b2cd5d7facf in both). The last commit has the
same author, committer, dates and message in both builds (`cmp` equal) and the same 14-file list. Only its tree differs.

`diff -r --exclude=.git` (saved as FixChecker/diff_r.txt, 77 lines) and `git ls-tree -r HEAD` both name five changed
files and nothing else, all mode 100644: EXCLUDE.txt, LICENSE_NOTE.md, docs/AI_USE.md, docs/HOW_TO_VERIFY.md,
docs/TIMELINE.md. Every hunk, with its category and the source check:

| file, lines (after) | category | check |
|---|---|---|
| docs/TIMELINE.md 110-122, extraction column, 13 ids | R19 id map | each old 7-char id is the prefix of an old_full row in id_map_r39.tsv and each new 7-char id is the prefix of that row's new_full. Pass |
| docs/HOW_TO_VERIFY.md 140, 144 | R19 id map | 2fe830d to 09a900d, per the map. Pass |
| docs/HOW_TO_VERIFY.md 246 | R19 id map | 0fb83aa to fc56589, per the map. `5681f74` on the same line is unchanged and exists in the after build (2026-10-28). Pass |
| EXCLUDE.txt 8 (new line) | R41 | one comment line above the six paths (lines 9-14). Text as R41 says. Pass |
| LICENSE_NOTE.md 7-8 | R42 and R46 | "lines 769-772 quote two short news headlines as examples and paraphrase a third" in place of "a few". See the source check below and N1 |
| docs/AI_USE.md 18 | R47 N1 | adds "the session that scheduled the daily collection from the trading calendar" to the Fable 5 list. Pass |
| docs/AI_USE.md 20 | R47 N3 | adds the three P.1 reviews at xhigh on Fable 5.1 "as the first lines of each report name it". Pass |
| docs/AI_USE.md 25-27 | R47 N2 | "which starts at STAGE_C.1.md (2026-10-10) because B.1 ran in the planning chat with no CLI prompt". Pass, see N2 and section 5 |
| docs/AI_USE.md 175 | R47 N2 | "The first is STAGE_C.1.md (2026-10-10)." Pass, see N2 |
| docs/HOW_TO_VERIFY.md 271-272 | R47 N2 | same clause as AI_USE.md 25-27. Pass, see section 5 |

Nothing in the diff falls outside these categories.

Id map (reports/p1_scratch/id_map_r39.tsv, 7 rows). For rows 1 to 6: the new id exists in the after build as a
commit with the subject the map gives, the same subject and author date as the old id in
/tmp/claude-1000/p1/RebuildTest/final1, and the same subject and author date as the AiTrader commit in TIMELINE's
AiTrader column (66b9e3c, 86adee9, 84cb7fb, f4e2f3a, 7d01388, fb858af). Row 7 (e93542e to fe6686c) is the scratch
HEAD of the before build. It is not in the after build (whose HEAD is 7b3de38), and no doc cites either id: TIMELINE
says "the commit that adds this file". Old ids: 0 hits for each of the seven 7-char prefixes and each 40-char form in
the whole after HEAD tree (`git grep`). The mapped `09a900d` is the single parent of `a92da39` (the C.3 commit), so
HOW_TO_VERIFY line 140 ("the last commit before C.3 changed the harness") stays true after the remap. Every hex token
of 7 to 40 characters in README.md, LICENSE_NOTE.md, AI_USE.md (6), HOW_TO_VERIFY.md (12) and TIMELINE.md (108
distinct) resolves to a commit in the after build or in AiTrader, except two sha256 prefixes in TIMELINE (the freeze
manifests, 19dc1da7 and 77c9bd73), which are not commit ids and are outside this diff.

R41 line. git-filter-repo 2.47.0 skips lines starting with `#` in `--paths-from-file`
(git_filter_repo.py get_paths_from_file, line 2368) and publish/checks/verify_extract.py parse_list skips them too
(line 74), so the comment changes no filter result. The build confirms it: the 49 earlier commits are unchanged. The
six paths that follow the comment (EXCLUDE.txt lines 9-14) exist in the after HEAD tree and each is byte-equal to the
same-named file in publish/llm-news-drift/reports/. In the after build's whole history each of the six paths is touched
by exactly one commit, the scratch HEAD 7b3de38, so no original version sits at any of them.

R42 and R46 sentence. EXPERIMENT.md in the after build is byte-equal to AiTrader's. The R46 grep returns lines 769 and
770. Double-quote marks per line: 769 none, 770 one, 771 one, 772 one, 773 one, 774 none. I read lines 768 to 774:
the sample-headline sentence begins on 769, the first quoted headline opens on 770 and closes on 771, an unquoted
paraphrase of a second item follows, and the second quoted headline opens on 772 and closes on 773. So "two quoted,
one paraphrased" is accurate, and the whole passage spans 769 to 773. The after build says 769-772, which misses the
closing quote mark (N1, already ruled in R51 and applied in the working file, section 5).

R47 N1. AiTrader RETURN.md lines 125-128: prompt "Schedule the daily news collection from the trading calendar",
date 2026-07-29, model Fable 5 (claude-fable-5). The after build holds 948f78e with that subject, author date
2026-07-29 16:49:50 -0700, the same as AiTrader's 284e720. The clause is true to source.

R47 N2. After build docs/prompts/README.md row B.1: "none", "planning chat", 2026-09-23, "no CLI session". Row C.1:
STAGE_C.1.md, 2026-10-10. The build's docs/prompts/ holds README.md and STAGE_C.1, C.2, C.2b, C.3 and P.1 only, so
"starts at STAGE_C.1.md (2026-10-10)" is true. "B.1" alone understates: AiTrader docs/STAGES.md lines 33-36 (B.1),
37-42 (B.2) and 43 (B.3) each say planning chat, no CLI session, and the build's AI_USE.md line 17 says "Stages B.1 to
B.3 ran here, with no CLI session". R51 corrects this to "B.1 to B.3" in the working files (section 5).

R47 N3. First lines of the three reports: reports/p1_review_leak.md line 3 "LeakAuditor-FableXHigh (worker-xhigh,
Fable 5.1)", reports/p1_review_archive.md line 3 "ArchiveAuditor-FableXHigh (Fable 5.1, worker-xhigh)",
reports/p1_review_claims.md line 1 "ClaimsReviewer-FableXHigh" and line 3 "Claude Fable 5.1 (claude-fable-5-1),
worker-xhigh". All three name Fable 5.1 and xhigh. The clause is true to source.

## 2. Profile

publish/profile/README.md (21 lines, mtime 08:11:49). The archive appears once, line 15: "research-archive (coming
soon): 18 research projects from July to September 2026, each in its own folder with its history kept and a one-page
card." No link, no URL and no github.com path points at it. The only links are llm-news-drift (line 8),
PropExperiment (line 12) and llm-news-drift's AI_USE.md (line 21). Em dash U+2014: 0. Dashes U+2012 to U+2015: 0.
Semicolons: 0. Two confirm marks remain, as the R50 rerun recorded.

## 3. go_public.sh

Diff of reports/p1_scratch/fixcheck_base/go_public.sh (188 lines) against publish/go_public.sh (210 lines, mtime
08:12:41): saved as FixChecker/go_public.diff, 76 lines. `bash -n` passes. The tree_clean copy under
/home/kiros-li/.cache/p1-tmp/DocFixProfile/tests/ is byte-identical to the current script, so the R50 stub tests ran
on this exact file.

Steps 1 and 2. Header lines 1-19, the function bodies of check_marks, check_scope, require_committed, remote_head,
is_fast_forward, push_build, build_profile and set_bio, and main() up to require_committed are byte-identical to the
base. The only change before step 1 is lines 48-51, where the two `export` lines are split into assignments plus one
`export` (N3): the exported values are the same strings.

Skip logic, by reading. One flag `with_archive` is set at lines 173-177 from `archive_on_github`, which is a
`gh repo view` read. Step 3 (lines 186-188, llm-news-drift extract and push) is unconditional. Step 4: the archive
build and push (190-194) sit inside `if with_archive == yes`, the profile build and push (195-197) are unconditional.
Step 5 (set_bio) has no archive part. Step 6 loops over `public`, which is `(llm-news-drift)`, then the archive only
when the flag is yes, then the profile repo, so llm-news-drift and the profile can never be dropped and the archive
is dropped when skipped. Step 7 passes the flag to print_web_steps, which names the archive in the pin line only when
yes. The confirm prompt lists `public`. The gh writes in the script are `gh api -X PATCH /user` (bio) and
`gh repo edit --visibility public` inside the step 6 loop. The only other archive calls are `gh repo view` (a read, in
archive_on_github and in push_build inside the guard) and `git push` inside the guard. With the flag at no, no gh write
and no push can reach the archive.

R50 test results read: T0 to T10 as recorded in go_public_test.md, T6 and T7 PASS with the expected prompt lines.
Rerun here with the stub gh first on PATH (logs in FixChecker/gh_T6.log, gh_T7.log, outputs T6.out, T7.out, the real
gh never called): T6 (archive missing, answer "no") exit 1, prints the skip line, the prompt lists
"llm-news-drift kirosli00tuff", stub log holds exactly `api -i /user` and `repo view kirosli00tuff/research-archive`.
T7 (archive present) exit 1, no skip line, the prompt lists all three, same two stub calls. T8 (functions sourced):
pin line "llm-news-drift and PropExperiment" for no, "llm-news-drift, PropExperiment and research-archive" for yes.
All match the recorded results.

## 4. Leaks in the after build

FixChecker/leak_scan.py reads publish/checks/llm-news-drift.replace-text (6 rules, literal left sides of lengths 19,
9, 13, 27, 28, 20, no regex) and prints counts only. In DocFixDrift's numbering rules 3 and 4 are the two R39 names
and rules 5 and 6 the R40 reason in its two forms. Results on /home/kiros-li/.cache/p1-tmp/DocFixDrift/run1:

| scope | hits per rule 1 to 6 |
|---|---|
| HEAD tree, 191 blobs, exact | 0, 0, 0, 0, 0, 0 |
| HEAD tree, case-insensitive | 0, 0, 0, 0, 0, 0 |
| HEAD tree path names | 0, 0, 0, 0, 0, 0 |
| last commit message, author and committer | 0, 0, 0, 0, 0, 0 |
| every object in the store, 498, case-insensitive | 0, 0, 0, 0, 0, 0 |
| all 50 commit messages and idents | 0, 0, 0, 0, 0, 0 |

Positive control, the same scan on AiTrader's working docs/DECISIONS.md and docs/prompts/STAGE_P.1.md: 1, 1, 1, 1,
1, 0 and 2, 4, 2, 2, 1, 1, the same as DocFixDrift's control, so the literals load and match. The rule file is
unchanged since DriftRules (mtime 05:38).

## 5. R51: the three lines changed after the DocFixDrift builds

The after build's last commit carries 14 files. Each one compared with the working file under
publish/llm-news-drift/: 11 identical (ALLOWLIST.txt, EXCLUDE.txt, README.md, docs/TIMELINE.md, extract.sh and the six
reports/ files), 3 differ by exactly one line each. No working file under publish/llm-news-drift/ is outside the 14.
The three working files have mtime 08:17:37, after the rebuild at 08:13:54 to 08:13:59.

| working file, line | run1 | working | source |
|---|---|---|---|
| LICENSE_NOTE.md 7 | lines 769-772 | lines 769-773 | EXPERIMENT.md: the passage spans 769 to 773, closing quote mark on 773 (section 1). Correct |
| docs/AI_USE.md 26 | B.1 | B.1 to B.3 | docs/STAGES.md 33-43: B.1, B.2 and B.3 each planning chat, no CLI session. AI_USE.md 17 agrees. Correct |
| docs/HOW_TO_VERIFY.md 272 | B.1 | B.1 to B.3 | same source. Correct |

No other file the build carries changed after the build. publish/checks/llm-news-drift.replace-text and the build's
extract.sh are unchanged.

## Findings

N1. NOTE. LICENSE_NOTE.md in DocFixDrift run1 says lines 769-772. The passage runs to the closing quote mark on
773. R51 already corrects the working file to 769-773 (section 5). G2 must build from the working tree, not from
run1, and FixChecker should see 769-773 in the G2 build. No action beyond that.

N2. NOTE. R47 says one clause each. AI_USE.md got two N2 clauses (lines 25-27 and line 175). F3-N2 named line 173 as
well as lines 23-25, so both sit inside the finding, and both are true to source. No action.

N3. NOTE. go_public.sh lines 48-51 differ from the base in form (the two `export` lines split, shellcheck SC2155, as
the R50 rerun declared). The exported values are identical and every step 1 and 2 function body is byte-identical.
Not a ruled change, but harmless. No action.

N4. NOTE. The archive skip fires on any failure of `gh repo view`, not only a missing repo, for example a transient
API error after step 2 passed. The skip is the safe direction (nothing is pushed or flipped for the archive) and the
skip line names the command that failed. No action.

## Not checked, or limits

- The G2 build does not exist yet. Section 5 checks the working files, not a build that holds them.
- Steps 3 to 7 of go_public.sh were never executed (H6). My check of them is by reading and by the stub prompt tests,
  which stop before step 3.
- shellcheck was not rerun (not installed). `bash -n` only.
- Rule file semantics: I counted literal hits as filter-repo would apply them, plus case-insensitive. I did not scan
  for fragments or stems of the literals.

## Files written

/home/kiros-li/Documents/GitHub/AiTrader/reports/p1_review_fixcheck.md (this file).
/home/kiros-li/.cache/p1-tmp/FixChecker/: diff_r.txt, go_public.diff, leak_scan.py, fn.sh, gh_T6.log, gh_T7.log,
T6.out, T7.out. None holds a name, the reason text, a rule literal or a headline.

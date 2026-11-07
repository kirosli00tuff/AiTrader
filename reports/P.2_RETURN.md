# Stage P.2 return: research-archive without solana, private on GitHub

Date: 2026-11-07, 10:24:28 MST (session start, reports/P.2_STATE.md) to 13:55:39 MST (the end checks; the final commit follows, with its own time in git).
Lead: Opus 5.5 (claude-opus-5-5), effort max, tmux session stage-p2, six lead contexts.
Prompt: docs/prompts/STAGE_P.2.md. Kiros's confirmation of the 12 card lessons: /home/kiros-li/planner-drafts/P2_KIROS_CONFIRMED.md
(A4, copy in reports/p2_scratch/P2_KIROS_CONFIRMED.copy.md).
Record: reports/P.2_STATE.md (the log), reports/p2_rulings.md (P2-R1 to P2-R43 and the class ruling),
reports/p2_review_archive.md (D1), reports/p2_review_script.md (D2), reports/p2_review_script_fix.md (FixReview),
reports/p2_review_archive_recheck.md (D1r), reports/p2_review_return.md (ReturnCheck), reports/p2_github_before.json and
reports/p2_github_after.json (E4, redacted), and the worker reports in reports/p2_scratch/. That folder (worker
reports, briefs, scan outputs, helper scripts) stays local and is not committed (open choice 3).

Draft note: ReturnDrafter-OpusXHigh (Opus 5.5, xhigh) drafted the header and sections 2 to 5 from the record on
disk, 13:36 to 13:52 MST. The fifth lead wrote sections 1, 6 and 7, and the sixth lead amended them after
ReturnCheck-FableXHigh checked the facts (P2-R37 to P2-R42). The sixth lead wrote section 8 and the end checks and
put the file together. The drafter marked two claims "Untraced"; the sixth lead traced both from the record (2.3, 2.6). Times are MST, as logged.

## 1. Summary

Stage P.2 is done, with one decision left for Kiros. research-archive was rebuilt without the six solana repos:
12 experiment projects, 420 commits, HEAD 4c06138. The build is deterministic: three identical builds in each of
three rounds, and a fourth in the dry run. The open P.1 items are closed, and Kiros's 12 lessons stand word for word.
Fable reviews D1 and D1r found 46 program-audit files dedicated to the two solana audits, holding 9 on-chain identifiers. One
EXCLUDE.txt rule removed them and pruned one commit. Scans: private terms 0, gitleaks 0, and no finding new against
P.1. A fresh clone runs 2,421 tests passed, 32 failed and 10 skipped, each a known cause listed in the
README. go_public.sh now covers the archive. D2's two SHOULD FIX items (inherited GIT_* variables, gate errors read
as clean) were fixed and passed a second Fable review, harness 340 of 340. research-archive is on GitHub, PRIVATE,
main 4c06138, with description and topics. Nothing was made public and no public repo was pushed. The dry run
shows the three planned actions. One confirm mark stays: the kept sources still name the solana repos 6,557 times
(SOURCES.txt:27), so go-live waits for Kiros (section 7.1).

## 2. Guardrail evidence

### 2.1 Start checks, verbatim

Written by the first lead at 10:24 (STATE 10:24:28). /home/kiros-li/.cache/p2-tmp/start_gates.txt (28 lines):

```
=== date
Sat Nov  7 10:24:37 MST 2026
=== status check (start)
active
=== DAILY RUN 2026-11-07T06:01:10Z ===
action:     collected
target:     2026-11-05
formation:  2026-10-01
GAP:        3 session(s) missing, UNRECOVERABLE by design: 2026-08-28, 2026-09-15, 2026-10-30
rows:       0 before, 998 after
spend:      0.421472 USD over 767 calls
exit:       4
69|35548|13381
=== git status --short
 M COLLECTION_LOG.md
?? reports/p1_scratch/
=== git log --oneline -3
e5c1810 docs: V10 and Stage P.2 prompt (research-archive without solana)
84586ac publish: Kiros confirmed every mark in llm-news-drift and the profile (licence: all rights reserved for now)
cfcd878 Stage P.1 public repos and GitHub profile
=== free -m
               total        used        free      shared  buff/cache   available
Mem:           15118        6836        4212        2812        7213        8282
Swap:           4095           1        4094
=== df -h /home /tmp
Filesystem                         Size  Used Avail Use% Mounted on
/dev/mapper/ubuntu--vg-ubuntu--lv  466G  102G  341G  23% /
tmpfs                              7.4G  2.3G  5.2G  31% /tmp
```

/home/kiros-li/.cache/p2-tmp/start_gates_gh.txt (17 lines), the gh part of gate 0.1 and gate 0.2:

```
=== gh auth status
github.com
  ✓ Logged in to github.com account kirosli00tuff (keyring)
  - Active account: true
  - Git operations protocol: https
  - Token: gho_************************************
  - Token scopes: 'gist', 'read:org', 'repo', 'user', 'workflow'
exit=0
=== gh repo view kirosli00tuff/research-archive
GraphQL: Could not resolve to a Repository with the name 'kirosli00tuff/research-archive'. (repository)
exit=1
=== replace-text exists?
exists: yes, lines=4
=== tmux
TMUX=/tmp/tmux-1000/default,1179749,0
stage-p2
stage-p2: 1 windows (created Sat Nov  7 10:24:21 2026)
```

Gate results (STATE 10:24:28 to 10:24:40): timer active, collection counts 69|35548|13381, HEAD e5c1810 after 84586ac
(0.1 asks for 84586ac or later), 8,282 MB available. `gh repo view kirosli00tuff/research-archive` failed with exit 1,
so the gate passed. The rule file existed with 4 lines; its literals were not printed. Rule 5 was added later
(10:34:28), so the builds ran with 5 rules.

### 2.2 End checks, verbatim

```
=== date
Sat Nov  7 13:55:39 MST 2026
=== status check (end)
active
=== DAILY RUN 2026-11-07T06:01:10Z ===
action:     collected
target:     2026-11-05
formation:  2026-10-01
GAP:        3 session(s) missing, UNRECOVERABLE by design: 2026-08-28, 2026-09-15, 2026-10-30
rows:       0 before, 998 after
spend:      0.421472 USD over 767 calls
exit:       4
69|35548|13381
=== gh auth status
github.com
  ✓ Logged in to github.com account kirosli00tuff (keyring)
  - Active account: true
  - Git operations protocol: https
  - Token: gho_************************************
  - Token scopes: 'gist', 'read:org', 'repo', 'user', 'workflow'
exit=0
=== gh repo view kirosli00tuff/research-archive --json visibility,defaultBranchRef
{"defaultBranchRef":{"name":"main"},"visibility":"PRIVATE"}
exit=0
=== git -C ~/Documents/GitHub/research-archive rev-parse HEAD
4c06138700a342d9bea18cecd085b208a061ee94
=== free -m
               total        used        free      shared  buff/cache   available
Mem:           15118        5741        1793        1998        9913        9377
Swap:           4095        1081        3014
```

### 2.3 Outcome blindness and scope

Built from the record only.

- Databases: the only database access in the record is the CLAUDE.md status check's count query on
  news_experiment.db, at the start (2.1) and the end (2.2), on allowed columns only. Six briefs say "Do not read news_experiment.db, EXPERIMENT.md,
  news_eval/ or reports/c2*" (A2_ArchiveText.md:67, B_ScriptCoder.md:82, C3_ScanRunner.md:31, C4_TestRunner.md:21,
  D1_ArchiveReviewer.md:34, D2_ScriptReviewer.md:25). S1_Exclude.md, D2b_FixReviewer.md, R2_reruns.md and the inline
  ScriptFix brief do not repeat that line. Their reports name only publish/, the builds and their sandboxes as
  inputs, and the tool calls in their transcripts (ScriptFix 51, ExcludeS1 56, FixReview 31, C3r 16, C4r 12, D1r
  33) name none of news_experiment.db, sqlite3, outcomes.py or scoring.py (sixth lead's check; the one C4r match is
  an archive test file, test_integrity_scoring.py). No STATE line records any other database open by the lead. The archive tests ran in fresh archive clones in a loopback-only namespace
  (tests_report.md, Method).
- Outcome columns: none read. No step touches the experiment, and no STATE line or report names an outcome,
  return, excess, benchmark or cost column.
- news_experiment/outcomes.py and scoring.py: not run. STATE logs no run, and no brief names either script.
- EXPERIMENT.md: not edited. At 13:42 its sha256 prefix is 964996723df6, the value P.1 recorded
  (reports/P.1_RETURN.md 2.3). The last commit touching it is 2359d16, before this stage, and C1 does not list it
  (`git show --stat 73aa37a`). A2 read only its git log metadata (archive_text_report.md item 5).
- Collector: news-collect.timer active at the start (2.1). No collector file is in C1 or in `git status --short` at
  13:42. COLLECTION_LOG.md shows as modified (the wrapper's appends) and was never staged: C1 staged explicit paths
  (STATE 10:54:36), and `git show --stat 73aa37a` lists no COLLECTION_LOG.md.
- Source repos: read only. A2, D1 and D1r read them with `git --no-optional-locks` or read-only `git log`
  (archive_text_report.md line 4, p2_review_archive.md line 9, p2_review_archive_recheck.md line 17).
  ExcludeS1 wrote nothing there (s1_exclusion_report.md line 5). Every build clones each source first (the "clone"
  lines in 3.9).
- Paid calls: none in the record. No brief allowed one.
- Keys and private literals: none printed in the record. gh masks its token (2.1). The rule file's literals were
  never printed (STATE 10:24:40). The lead added rule 5 inline so no worker saw the literal (STATE 10:34:28). The
  build report and grep_scan.py print counts only. C1's private-literal count over its 21 staged files was 0 (STATE
  10:54:36). D1r's transcript holds five solattn commit ids read from D1's sandbox; they are not p1-private literals
  and nothing was written to the tree (P2-R28). The drafter's own slip: between 13:36 and 13:42 the drafter ran
  reports/p2_scratch/precommit_private_scan.py with `--help` by mistake. The script took `--help` as its repo
  argument, loaded the private pattern files and stopped with a Python error. Only the first 5 traceback lines were
  shown, with no literal and no count in them. Nothing was written. The lead's final private scan of the 22
  staged files (13:59) found the email handle, a private replace-text term (rule 2), in six lines of five files,
  each in a list of counted scan terms (STATE lines 103 and 126, p2_review_archive_recheck.md, p2_review_return.md,
  p2_rulings.md and this return's 3.5). The lead replaced it with "the email handle" in all five, re-staged them,
  and the rerun found 0 (P2-R43). The commit carries the redacted files only.
- GitHub: one repo created, research-archive, PRIVATE (E1). No push to a public repo and no visibility change: E4
  before and after differ only by research-archive, absent before and PRIVATE after (STATE 13:17:03). The bio was not
  set: STATE logs no bio call, and the dry run reports "bio: unchanged" (3.9).
- go_public.sh: the real script ran once, with `--dry-run` (E3, STATE 13:14:09). Every other run was a copy in a
  sandbox with a stub gh and local bare repos (go_public_test.md lines 5 to 7, p2_review_script.md Method,
  go_public_fix.md lines 6 to 8, p2_review_script_fix.md lines 11 to 14).
- AiTrader: not pushed. `git status -sb` at 13:42 shows main ahead of origin/main by 1 (C1). History not rewritten:
  `git log` shows 73aa37a on e5c1810, 84586ac and cfcd878, so the solana cards from bb09341 stay in history.

### 2.4 Order of events, with every gh call

Times are MST from reports/P.2_STATE.md. "gh read" means a call that changes nothing. "gh CHANGE" means a call that
changes GitHub.

| Time | Event |
|---|---|
| 10:24:28 | Session start, lead 1 (Opus 5.5, max) in tmux stage-p2. Start checks (2.1). gh read: `gh auth status`, exit 0. |
| 10:24:40 | Gate 0.1, gh read: `gh repo view kirosli00tuff/research-archive`, exit 1, "Could not resolve to a Repository". Gate 0.2: the rule file exists. tmux session stage-p2 present. |
| 10:30:19 | B spawned (ScriptCoder-OpusXHigh). |
| 10:32:02 | A1 done (3.2). |
| about 10:33:34 | A2 spawned (ArchiveText-OpusHigh). Time from its first transcript entry (reports/p2_scratch/cost_tokens.md); STATE 10:34:28 says only "spawned earlier". |
| 10:34:28 | R43: rule 5 added to the private rule file by the lead (backup beside it, mode 600). |
| 10:34:35 | A3 done: the profile README links the archive, 12 projects, no "coming soon". |
| 10:34:55 to 10:37 | A4: P2_KIROS_CONFIRMED.md found at 10:36 (mtime 10:27:11). SendMessage to A2 at 10:37: do not change the text of the 12 lesson sections. |
| 10:37:32 | Lead finding: the 12 kept sources name the six left-out repos (open choice 1). |
| 10:38:41 | A2 returned. A4 done: the 12 lesson marks removed, no text edits. |
| 10:39:04 | One confirm mark added to SOURCES.txt after the V10 line (open choice 1). |
| 10:39:49 | Briefs for C3, C4, D1 and D2 written. |
| 10:40:46 | Lead scratch pre-build from the working tree: HEAD 2bc0033, 421 commits (open choice 7). |
| 10:54:25 | B returned. |
| 10:54:36 | C1 committed: 73aa37a "Stage P.2 archive sources (no solana)". |
| 10:55:11 to 10:57:42 | Self-wipe 1. Lead 2 starts. |
| 10:59:29 | C2 done: two scratch builds and the final, HEAD 2bc0033 (3.4). |
| 11:00:53 | C3, C4, D1 and D2 spawned. |
| 11:01 to 11:17 | D2 ran `gh --version` and `gh repo edit --help` only, offline (p2_review_script.md, Method). |
| 11:03:33 to 11:03:38 | C3 and C4 returned. The lead ran bulktext and headlines on 2bc0033 (open choice 8). |
| 11:17:55 | D2 returned. |
| 11:19:00 | P2-R2 and P2-R3 ruled FIX. ScriptFix spawned. |
| 11:22:07 | D1 returned. |
| 11:22:44 | P2-R1 ruled: FIX by exclusion. |
| 11:33:52 | ScriptFix returned. READY FOR WIPE. |
| 11:36:20 | Self-wipe 2 done. Lead 3 starts. |
| 11:40:51 | ExcludeS1 and FixReview spawned. |
| 11:43:57 | Rulings drafted, P2-R1 to P2-R21. Rerun briefs written. |
| 11:47 to 11:49 | ExcludeS1 returned. P2-R22 and P2-R23. P2-R4 edit made. |
| 11:50:42 | Rebuild round 2: HEAD d4f2b75, 420 commits. |
| 11:51:29 | C3r, C4r and D1r spawned (four workers running with FixReview). |
| 11:54:01 to 11:54:12 | C3r and C4r returned (report mtimes). |
| 11:55:17 | P2-R24 ruled, to be applied after D1r returns. |
| about 11:59 to 13:02 | The 5-hour usage limit stopped the lead, FixReview (its runner had finished at 11:59:15) and D1r's final reply. D1r's report mtime is 12:00:50. |
| 13:02 to 13:02:05 | FixReview resumed by SendMessage. The lead resumed at 13:02:05. |
| 13:03:44 | P2-R24 done: rebuild round 3, HEAD 4c06138, 420 commits. |
| 13:04:42 | P2-R25 to P2-R29 ruled. |
| 13:04:47 | FixReview returned (report mtime). |
| 13:05:31 | P2-R30 and P2-R31 ruled. READY FOR WIPE. |
| 13:08:04 | Self-wipe 3 done. Lead 4 starts. |
| 13:08:57 | grep_scan rerun on 4c06138 (lead, 6 s). |
| 13:12:11 | Rulings complete to P2-R35, 0 PENDING. SOURCES.txt mark updated to lines 27 to 34. |
| 13:12:29 | E4 before, gh read: `gh repo list kirosli00tuff --limit 100 --json name,visibility` through reports/p2_scratch/gh_list_redacted.py, exit 0, "rows=19 redacted=2 leaked=0". |
| 13:13:07 to 13:13:14 | E1, gh CHANGE: `gh repo create kirosli00tuff/research-archive --private --source ~/Documents/GitHub/research-archive --push`, exit 0 (output in 3.8). Check: gh read `gh repo view`, and `git ls-remote`. |
| 13:13:34 | E2a, gh CHANGE: `gh repo edit` with the description; the topic list was empty after a lead shell error, so only the description was set. No output, exit 0. Check: gh read `gh repo view`. |
| 13:13:44 | E2b, gh CHANGE: `gh repo edit --add-topic` with the four topics from metadata.json. No output, exit 0. Check: gh read `gh repo view`. |
| 13:14:09 to 13:14:34 | E3: `TMPDIR=/home/kiros-li/.cache/p2-tmp publish/go_public.sh --dry-run < /dev/null`, exit 1, 111 lines (3.9). gh reads only. STATE does not list them one by one; D2's reading of the code (p2_review_script.md N-5) lists `gh repo view` per repo, `gh api -i /user`, `gh api /user --jq .bio`, `git ls-remote` for the three repos and a clone of the public profile repo. |
| 13:15 to 13:16 | P2-R36: lead finding in the E3 build folder, and the profile README edit. No gh call. |
| 13:17:03 | E4 after, gh read: the same command, exit 0, "rows=20 redacted=2 leaked=0". |
| 13:17:41 to 13:20:25 | Self-wipe 4. Lead 5 starts. |
| 13:32:28 to 13:35:06 | Self-wipe 5. Lead 6 starts. |
| 13:36:11 | ReturnDrafter and ReturnCheck spawned. |
| 13:48 to 13:55 | ReturnCheck returned 13:48 and ReturnDrafter 13:52; rulings P2-R37 to P2-R42; end checks 13:55:39; then the final commit (no push). |

Three gh calls changed GitHub: E1, E2a and E2b. STATE logs each one with its output and a read-back check before
the next one ran (13:13:07, 13:13:34, 13:13:44). Every other gh call read only. No worker called the real gh with a
changing command: B, ScriptFix and FixReview used a stub gh or none (go_public_test.md lines 5 to 6,
go_public_fix.md line 6, p2_review_script_fix.md line 13), and D2's two calls were offline.

### 2.5 git status --short and git diff --stat

```
$ git status --short
 M COLLECTION_LOG.md
M  PROGRESS.md
M  RETURN.md
M  docs/STAGES.md
M  docs/prompts/README.md
M  publish/checks/test_go_public.sh
M  publish/go_public.sh
M  publish/profile/README.md
M  publish/research-archive/EXCLUDE.txt
M  publish/research-archive/README.md
M  publish/research-archive/SOURCES.txt
M  publish/research-archive/cards/experiments/ORBExperiment/CARD.md
M  publish/research-archive/cards/experiments/program-audit/CARD.md
A  reports/P.2_RETURN.md
M  reports/P.2_STATE.md
A  reports/p2_github_after.json
A  reports/p2_github_before.json
A  reports/p2_review_archive.md
A  reports/p2_review_archive_recheck.md
A  reports/p2_review_return.md
A  reports/p2_review_script.md
A  reports/p2_review_script_fix.md
A  reports/p2_rulings.md
?? reports/p1_scratch/
?? reports/p2_scratch/

$ git diff --cached --stat
 PROGRESS.md                                        |   14 +
 RETURN.md                                          |   15 +
 docs/STAGES.md                                     |    3 +-
 docs/prompts/README.md                             |    2 +-
 publish/checks/test_go_public.sh                   |  187 +++-
 publish/go_public.sh                               |   28 +-
 publish/profile/README.md                          |    3 -
 publish/research-archive/EXCLUDE.txt               |    5 +
 publish/research-archive/README.md                 |   14 +-
 publish/research-archive/SOURCES.txt               |   12 +-
 .../cards/experiments/ORBExperiment/CARD.md        |    2 +-
 .../cards/experiments/program-audit/CARD.md        |    4 +-
 reports/P.2_RETURN.md                              | 1169 ++++++++++++++++++++
 reports/P.2_STATE.md                               |  273 +++++
 reports/p2_github_after.json                       |   82 ++
 reports/p2_github_before.json                      |   78 ++
 reports/p2_review_archive.md                       |  233 ++++
 reports/p2_review_archive_recheck.md               |  147 +++
 reports/p2_review_return.md                        |   82 ++
 reports/p2_review_script.md                        |   90 ++
 reports/p2_review_script_fix.md                    |  255 +++++
 reports/p2_rulings.md                              |   70 ++
 22 files changed, 2743 insertions(+), 25 deletions(-)
```

### 2.6 Ids and hashes the stage fixed

| Item | Value | Source |
|---|---|---|
| Base commit | e5c1810 "docs: V10 and Stage P.2 prompt (research-archive without solana)", after 84586ac | 2.1 |
| C1 | 73aa37ab13471bad5f192c8ae3c527e1fede7347 "Stage P.2 archive sources (no solana)", 2026-11-07 10:54:35 -0700. 27 files changed, 1,419 insertions, 418 deletions. STATE counts 21 staged files for the private-literal scan; 27 - 21 = 6, the number of deleted solana cards (`git show --name-status 73aa37a`: 2 added, 19 modified, 6 deleted, so the 21 scanned files are the added and modified ones) | `git log` and `git show --stat 73aa37a` (drafter, 13:42); STATE 10:32:02, 10:54:36 |
| Build round 1 | HEAD 2bc0033bbd1f605388d98b35b89a8095e9c79ede, 421 commits, `git rev-list --all \| sha256sum` 37c0a348...4f235d, .git 10,108,992 bytes after gc | STATE 10:59:29; archive_build_report.md lines 29 to 31 |
| Build round 2 | HEAD d4f2b756a5f209b5b1defdc8e1025fcd98720f6e, 420 commits, rev-list sha256 prefix a516df99cdbbb0e0, .git 9,179,350 bytes after gc | STATE 11:50:42; archive_build_report_r2.md lines 29 to 31 |
| Build round 3 (final) | HEAD 4c06138700a342d9bea18cecd085b208a061ee94, 420 commits, rev-list sha256 prefix b512bfa367bc5ef4, .git 9,229,082 bytes after gc, root 51a625cd486e70e2e1cc52ed177fc6bb565a23a3, refs/heads/main only at build time (after E1 the local archive also has refs/remotes/origin/main at 4c06138, p2_review_return.md NOTE 7) | STATE 13:03:44; archive_build_report_r3.md lines 29 to 31. Re-read by the drafter at 13:42: HEAD 4c06138, 420 commits, prefix b512bfa367bc5ef4 |
| Final build inputs (sha256) | EXCLUDE.txt c3c9c35510fef72c..., README.md 771d7270f2ce207e..., mailmap.txt 4004f62e0f3584bf... The SOURCES.txt hash there (cd9a40fec82b327d...) predates the 13:12:11 mark edit; SOURCES.txt is not copied into the archive, and the E3 rebuild with the edited file gave the same HEAD | archive_build_report_r3.md lines 11 to 15; 3.4 |
| Build tools | git 2.53.0, git-filter-repo 2.47.0 (`--version` a40bce548d2c), python 3.14.4 | archive_build_report_r3.md line 10 |
| GitHub research-archive | `git ls-remote`: HEAD and refs/heads/main both 4c06138700a342d9bea18cecd085b208a061ee94, no other ref. Visibility PRIVATE, default branch main | STATE 13:13:07 |
| go_public.sh and harness (sha256 prefixes) | At 73aa37a: c297bec7a6072f78 (script), ccd2685bfdc8928b (harness). Working tree after ScriptFix: fb80708cb61ad79b, b4d4583bc3831d69 | p2_review_script_fix.md lines 7 to 9 |
| GitHub heads read by E3 | llm-news-drift main 3fb1324465f67b36701d2ecab879bb5b1e2780c8. kirosli00tuff main b72c1226571587d321999ddd0e52b1ec0aaf3f48, the 10:21 web edit on top of the go-live commit 54c7795 (P2-R36) | 3.9; STATE 13:15 |
| EXPERIMENT.md | sha256 prefix 964996723df6, unchanged | drafter, 13:42 |
| Frozen files | No new freeze in the record | |

## 3. Results

### 3.1 Source table (12)

All 12 sources are in the experiments group; the solana group is gone (A1, 3.2). Every row comes from the final
build report, reports/p2_scratch/archive_build_report_r3.md (Merge order lines 33 to 52, Removed paths summary lines
54 to 71, per-source rule blocks from line 132), the build of 13:03 (20:03:22Z to 20:03:43Z), HEAD 4c06138. Dates
are first and last author dates after filtering, in each commit's own offset (-07:00). Sources are cloned from
/mnt/large-storage/Archive/GitHub/<name> (3.9, the clone lines). Card only (no history): none.

| # | Source | Commits before, after, pruned | First to last | Paths before, kept, removed | Removed from history, and replace-text rules that changed blobs |
|---|---|---|---|---|---|
| 1 | MLCryptoEngine | 91, 91, 0 | 2026-07-30 to 08-22 | 299, 295, 4 | .env.example; 3 recorded exchange-message fixtures (tests/fixtures/coinbase_, hyperliquid_, kraken_messages.ndjson) |
| 2 | HFExperiment | 13, 13, 0 | 2026-08-23 to 08-28 | 98, 97, 1 | .env.example. Rule 3: 19 blobs (73 hits) and 1 message before, 0 after (the counts P.1 gives for the paper account ID) |
| 3 | NPDExperiment | 11, 11, 0 | 2026-08-25 | 75, 74, 1 | .env.example |
| 4 | InsiderExperiment | 7, 7, 0 | 2026-08-25 | 73, 72, 1 | .env.example |
| 5 | NPLExperiment | 41, 41, 0 | 2026-08-26 to 09-21 | 166, 165, 1 | .env.example |
| 6 | ETFExperiment | 28, 28, 0 | 2026-08-28 | 109, 107, 2 | .env.example; tests/fixtures/farside-recent.html |
| 7 | ORBExperiment | 59, 59, 0 | 2026-08-28 to 08-29 | 157, 155, 2 | .env.example; reports/stage_a1r/task6_delisted.json (R36). Rule 4: 1 blob |
| 8 | PMExperiment | 36, 36, 0 | 2026-08-29 to 09-02 | 32, 30, 2 | data/.gitkeep; .env.example |
| 9 | retail-power-limits | 3, 3, 0 | 2026-08-29 | 21, 21, 0 | nothing |
| 10 | VRPExperiment | 12, 12, 0 | 2026-08-29 to 08-30 | 47, 46, 1 | .env.example. Rules 1 and 2: 6 blobs each; rule 4: 1 blob |
| 11 | program-audit | 83, 82, 1 | 2026-08-29 to 09-13 | 1,724, 301, 1,423 | work/ 1,359; the findings files on solattn and solclear 46 (P2-R1); 8 in data or log folders; 10 database or pickle files. Pruned: c7c537a4116e, which added only an excluded file. Rules 1 and 2: 3 blobs each; rule 3: 30 blobs; rule 4: 24 blobs |
| 12 | MBTExperiment | 23, 23, 0 | 2026-09-02 to 09-12 | 94, 92, 2 | .env.example; docs/evidence/cme_outright_rates_crypto_20260903.csv. Rule 5: 1 blob |

Totals (drafter's sums of the table):
- Source commits: 91 + 13 + 11 + 7 + 41 + 28 + 59 + 36 + 3 + 12 + 83 + 23 = 407. Kept: 407 - 1 = 406.
- Archive commits: 406 imported + 12 merges + 1 empty root (51a625cd) + 1 cards commit = 420, the count every build
  report and D1r give. D1 counted the same structure on 2bc0033 (root + 12 merges + 407 + cards = 421).
- Paths before: 299 + 98 + 75 + 73 + 166 + 109 + 157 + 32 + 21 + 47 + 1,724 + 94 = 2,895 (ExcludeS1 also counts 2,895
  (source, path) rows, s1_exclusion_report.md section 3). Kept: 295 + 97 + 74 + 72 + 165 + 107 + 155 + 30 + 21 + 46
  + 301 + 92 = 1,455. Removed: 4 + 1 + 1 + 1 + 1 + 2 + 2 + 2 + 0 + 1 + 1,423 + 2 = 1,440.
- The final archive has 1,469 distinct history paths (D1r section 2): 1,455 kept + README.md + EXCLUDE.txt + 12
  cards = 1,469.

After the build, replace-text rules 1 to 5 hit 0 blobs and 0 messages in the whole archive, and rules 1 to 4 also 0
identities (archive_build_report_r3.md line 110). One identity holds all 420 author and all 420 committer fields, the
GitHub noreply address of kirosli00tuff (lines 112 to 115).

### 3.2 Removals

- A1, the six solana sources (lead, STATE 10:32:02): six rows out of SOURCES.txt; cards/solana/ removed with git rm
  (6 cards); in the README the solana rows, the line-33 mark, the layout, the keypair wording, the soltool removal
  bullet and 6 Tests rows removed; in EXCLUDE.txt the solana wording, the soltool html exception and the R37 solclear
  line removed; build_archive.sh's group check now accepts experiments only; metadata.json says 12 with no solana
  topic. Grep of publish/research-archive and publish/profile for the six names and solana: 0. The AI counts were
  recounted for 12 (reports/p2_scratch/ai_counts_p1build.txt: 122 trailer commits, Opus 5 39, Fable 5.1 82, Fable 5
  1, CLAUDE.md in 8 of 12). After P2-R1 the README says 121 and Fable 5.1 81 (D1r section 3).
- D1 checked A1 at blob level on 2bc0033: no solana folder, path or commit; 4 blobs shared with the six original
  repos, all boilerplate also in the 12 sources' own histories; 0 commit ids shared with any of the 18 source repos
  (p2_review_archive.md, summary table).
- P2-R1, the solana audit files (D1 S1): one regex rule in EXCLUDE.txt, `regex:^findings/(.*/)?[^/]*(solattn|solclear)`
  (now line 52), removed the 46 program-audit findings paths on the two solana repos, 2,520,593 bytes at HEAD (D1 S1).
  The rule matches exactly those 46 across the full history of all 12 sources and nothing else
  (s1_exclusion_report.md section 3). D1 reported 8 on-chain identifiers in the 46 files (p2_review_archive.md line
  56). ExcludeS1 found the same 8 in 10 blobs before and in 0 after (s1_exclusion_report.md section 2). The ninth, a
  mint with prefix AMBh, was found at the D1r recheck; it left with the excluded files and is in 0 blobs (P2-R27).
  One program-audit commit, c7c537a4116e (2026-09-05), added only an excluded file and was
  pruned. ExcludeS1 edited the claims that depend on the removal (s1_exclusion_report.md section 6): the
  program-audit card's count (84 to 83) and Data line, the README AI counts (122 to 121, Fable 5.1 82 to 81) and the
  README removal list.
- P2-R24: the P2-R1 comment in EXCLUDE.txt (lines 49 to 50) named solana and the two repos, and EXCLUDE.txt ships at
  the archive root. It was reworded. The built EXCLUDE.txt now holds solana 0, solattn 1 and solclear 1, all three
  in the regex on line 52 (it held 1, 2 and 2; STATE 13:03:44).
- Rule 5 (R43), counts only: the full legal name sat in exactly 1 blob across the 12 sources (MBTExperiment LICENSE),
  in 0 messages and 0 identities (STATE 10:34:28). In the build, MBTExperiment rule 5: 1 blob and 1 hit before, 0
  after; whole archive, rule 5: 0 blobs, 0 messages (archive_build_report_r3.md lines 108 and 110).

Removed paths by EXCLUDE.txt rule, final build (archive_build_report_r3.md lines 132 onward; EXCLUDE.txt has 16 rules,
and 8 of them removed something):

| Rule (EXCLUDE.txt) | Paths removed | Where |
|---|---|---|
| `regex:(?i)(^\|.*/)\.env[^/]*$` (env files, templates included) | 10 | MLCryptoEngine, HF, NPD, Insider, NPL, ETF, ORB, PM, VRP, MBT, 1 each |
| `regex:(?i)(^\|.*/)fixtures?/(.*/)?[^/]+\.(json\|jsonl\|ndjson\|csv\|tsv\|html?\|txt\|xml\|bin)$` | 4 | MLCryptoEngine 3, ETF 1 |
| `reports/stage_a1r/task6_delisted.json` (R36) | 1 | ORB |
| data, raw, cache and log folders (regex, code files kept) | 9 | PM 1, program-audit 8 |
| database, pickle and array files (regex) | 10 | program-audit |
| `regex:^findings/(.*/)?[^/]*(solattn\|solclear)` (P2-R1) | 46 | program-audit |
| `work/` | 1,359 | program-audit |
| `docs/evidence/cme_outright_rates_crypto_20260903.csv` | 1 | MBT |
| Total | 1,440 | 10 + 4 + 1 + 9 + 10 + 46 + 1,359 + 1 |

The R1 and R2 content pre-pass found 12 hits, all in program-audit and all in paths EXCLUDE.txt removes anyway ("R1
new" and "R2 new" 0, "hits covered" 12; report lines 54 to 71 and 288 to 300). The first build (2bc0033) removed
1,377 program-audit paths (archive_build_report.md line 70); the difference to 1,423 is the 46 P2-R1 paths.

### 3.3 Open items closed

| Item | Origin | What was done | Evidence |
|---|---|---|---|
| R36 | P.1 3.11 | ORBExperiment card says task6_delisted.json is excluded, and why (6,421 names from a vendor endpoint) | archive_text_report.md item 1 |
| F3-S1 | P.1 3.11 | MLCryptoEngine card: 3 pre-rewrite ids replaced by archive ids f0e5bc7, 3a26c5e, 4ec20ee | item 2. D1: all three exist in the build and in none of the 18 source repos |
| F3-S2 | P.1 3.11 | MBTExperiment card says 206 seconds (23:51:07 to 23:54:33) | item 3 |
| F3-S3, F3-S4 | P.1 3.11 | The "tests were not run" line removed; the Tests section rewritten with the measured rows | item 4. C4 and C4r: 12 of 12 rows match (3.6) |
| F3-S6 | P.1 3.11 | The V7 sentence cut | item 5 |
| F3-N4 | P.1 3.11 | Each card says N commits in the original repo and N+1 in the archive folder | item 6. program-audit later 83 after the prune (ExcludeS1 E1) |
| F3-N7 | P.1 3.11 | README removal classes include bulk vendor reference data | item 7. ExcludeS1 E5 added the findings class |
| F2-N7 | P.1 3.11 | One README line says .env.example is not in the archive, so setup steps that copy it do not run as written | item 8 |
| F2-N8 | P.1 3.11 | README trimmed from 1,228 to 842 words at A2 (73aa37a); 852 words as built in 4c06138, after the ExcludeS1 README edits; table 324. Over the 500 to 650 aim | item 10; p2_review_return.md NOTE 5; open choice 4 |
| Licence mark | V10 | Licence line kept, mark removed | item 11 |
| R43 | P.1 3.11, V10 | README: "My full name became my handle, kirosli00tuff." Rule 5 added by the lead; build count 0 after | item 9; STATE 10:34:28; 3.2 |
| A3 | prompt | Profile README links https://github.com/kirosli00tuff/research-archive, 12 projects, no "coming soon" | STATE 10:34:35 |
| A4 | prompt | The 12 lesson marks removed on Kiros's note, "Agreed with everything." (10:27 America/Vancouver), no text edits | STATE 10:34:55, 10:38:41 |
| R35, R37, R38; F3-S1 for solattn, solcopy and solclear; F3-S4's solclear row | P.1 3.11 | No longer apply: the solana cards and rows are gone | A1 |
| P2-R4 | D1 N1 | ORB card line 8: "within about two minutes" (127 s) | STATE 11:49; D1r section 3 |
| P2-R24 | C3r flag | EXCLUDE.txt comment without solana or the two names | STATE 13:03:44 |
| P2-R36 | lead, E3 | Profile README mirrors Kiros's 10:21 web edit (3 lines deleted), so the append is the archive link only | STATE 13:15; reports/p2_rulings.md |

D1 confirmed all 12 A2 items done and 0 confirm marks in README.md and the 12 cards (p2_review_archive.md, summary
table). One mark remains under publish/, at publish/research-archive/SOURCES.txt:27, not copied into the archive
(section 7.1).

### 3.4 Determinism

Every build in a round came from the same inputs and gave the same `git rev-list --all | sha256sum`.
build_archive.sh reads its config (SOURCES.txt, EXCLUDE.txt, README.md, the cards) from the publish/research-archive
working tree ("Config dir" in each build report, line 9). So rounds 2 and 3 include the uncommitted P2-R1, P2-R4 and
P2-R24 edits, and 4c06138 equals a build from HEAD only once those edits are committed (p2_review_return.md NOTE 4).

| Round | Builds | HEAD | Commits | rev-list sha256 | Notes |
|---|---|---|---|---|---|
| 1, from C1 73aa37a | lead pre-build pre.N4Y3wk (10:40:46, working-tree config before C1, 18 s); c2a.CwINlb (18 s); c2b.TepiiX (22 s); final to ~/Documents/GitHub/research-archive, new folder, no --force (21 s) | 2bc0033 | 421 | 37c0a348...4f235d in all | .git 9.8M (du), 10,108,992 bytes after gc; tree 31M; fsck --strict 0 lines; largest blob 667,208 bytes, experiments/MLCryptoEngine/uv.lock (STATE 10:40:46, 10:59:29) |
| 2, after P2-R1 | r2s1b.mHaaPY, r2s1c.kQBjHp, final --force; each 25 s | d4f2b75 | 420 | prefix a516df99cdbbb0e0 in all | .git 8.9M (du), tree 29M, fsck --strict 0 lines, same largest blob (STATE 11:50:42). D1r: both scratch builds hold the same 5,556 objects as the final |
| 3, after P2-R24 | r3s1d.yMwVCr, r3s1e.BELN4M, final --force | 4c06138 | 420 | prefix b512bfa367bc5ef4 in all | .git 8.9M (du), fsck --strict 0 lines. Final 21 s (report lines 5); the scratch build times are not logged. `git diff --stat d4f2b75 4c06138`: EXCLUDE.txt only, 2 insertions, 2 deletions (STATE 13:03:44) |
| E3 dry run | go_public.BT42Js/research-archive, built by go_public.sh from the working-tree build_archive.sh | 4c06138 | 420 | not recorded | "done: 420 commits, head 4c06138..." (3.9; STATE 13:14:09) |

ExcludeS1's two scratch builds (s1a.2ibDRb, HEAD 83e9c04, before the README and card edits; s1b.6GrGU0, HEAD
e3ca7b3e2f42, after them) used intermediate inputs, so their HEADs differ by design. Both have HEAD~1 b86f2399fedc,
the same MBTExperiment merge as the final (s1_exclusion_report.md section 4, D1r section 2).

### 3.5 Scans

| Run | Build | gitleaks git / dir | secrets (findings / low-tier) | paths | hygiene (findings / low-tier) | bulktext (findings / low-tier) | headlines | New against P.1 |
|---|---|---|---|---|---|---|---|---|
| C3, 11:00 to 11:01 (scan_report.md) | 2bc0033 | 0 (408 commits scanned) / 0 | 3,273 / 13,198 | 2 | 29 / 20 | lead: 68 / 47 | lead: 0 / 0 | 0 in every tool |
| C3r, 11:51:12 to 11:52:23 (scan_report_r2.md) | d4f2b75 | 0 (407 commits scanned) / 0 | 3,247 / 13,181 | 2 | 15 / 20 | 56 / 43 | 0 / 0 | 0 in every tool, and 0 against the first run |
| lead, 13:08:57 (scans/p2r3_grep_scan.md) | 4c06138 | not rerun | not rerun | not rerun | not rerun | not rerun | not rerun | grep_scan only |

- gitleaks scans fewer commits than rev-list shows because the 12 import merges and the empty root add no diff: 408
  = 421 - 12 - 1, and 407 = 420 - 12 - 1 (P2-R11; scan_report_r2.md note c). P.1's build had 13 gitleaks findings,
  all under solana/ paths (scan_report.md section 2).
- The two paths findings are the two .html files EXCLUDE.txt keeps on purpose (experiments/MLCryptoEngine/desktop/
  index.html, experiments/NPDExperiment/reports/session_record.html; D1 N3, P2-R6).
- The lead's bulktext and headlines run on 2bc0033: 68 findings and 47 low-tier, the same multiset (path, kind, blob)
  as P.1 outside solana/; headlines 0 and 0, as in P.1 (STATE 11:03:33).
- C3r: every finding that went away sits under one of the 46 S1 paths (path-location keys: secrets 26, secrets
  low-tier 15, hygiene 14 phone_intl, bulktext 8, bulktext low-tier 2). No finding is new in any tool. C3r flagged
  EXCLUDE.txt at the archive root as a new public-term location, which P2-R24 fixed.
- 4c06138 differs from d4f2b75 only in EXCLUDE.txt's comment, so the lead reran grep_scan only and no test (STATE
  13:04:42 UPDATE, P2-R24).

grep_scan.py private terms (R1 to R5, the five rule literals, and T1, T2, the two personal repo names): 0 in blobs, 0
in messages and identities, 0 in paths, in all three runs (p2_grep_scan.md, p2r_grep_scan.md, p2r3_grep_scan.md).

Public terms, blob occurrences / files / commits whose message hits / paths:

| Term | 2bc0033 (C3) | d4f2b75 (C3r) | 4c06138 (lead) |
|---|---|---|---|
| solattn | 7,415 / 158 / 7 / 25 | 3,496 / 134 / 7 / 0 | 3,495 / 134 / 7 / 0 |
| solclear | 6,864 / 132 / 8 / 25 | 2,761 / 92 / 7 / 0 | 2,760 / 92 / 7 / 0 |
| solcopy | 20 / 8 / 1 / 0 | 20 / 8 / 1 / 0 | 20 / 8 / 1 / 0 |
| solana | 328 / 43 / 0 / 0 | 283 / 25 / 0 / 0 | 282 / 24 / 0 / 0 |
| solback, solceil, soltool, the email handle | 0 | 0 | 0 |
| Total occurrences | 14,627 | 6,560 | 6,557 |

Sums: 7,415 + 6,864 + 20 + 328 = 14,627; 3,496 + 2,761 + 20 + 283 = 6,560; 3,495 + 2,760 + 20 + 282 = 6,557. Each equals
the scan's own stdout line (scan_report.md line 64, scan_report_r2.md command 3, p2r3_grep_scan.stdout.txt). The 4c06138
counts differ from d4f2b75 by EXCLUDE.txt's comment only (solana 1, solattn 1, solclear 1; STATE 13:08:57).

The mention class on 4c06138 (STATE 13:08:57; p2r3_grep_scan.md "by source folder"):

| Source | Occurrences |
|---|---|
| program-audit | 4,989 (solattn 2,302, solclear 2,626, solana 50, solcopy 11; CROSS_REPO.md 111 and CROSS_REPO.json 59 of these) |
| ORBExperiment | 694 |
| NPLExperiment | 488 |
| MLCryptoEngine | 191 |
| ETFExperiment | 87 |
| retail-power-limits | 50 |
| VRPExperiment | 23 |
| PMExperiment | 18 |
| MBTExperiment | 10 |
| InsiderExperiment | 5 |
| EXCLUDE.txt (archive root) | 2 |
| Total | 6,557 = 4,989 + 694 + 488 + 191 + 87 + 50 + 23 + 18 + 10 + 5 + 2 |

Commit messages: 14 distinct (solattn 7, solclear 7, one message in both, solcopy 1: 7 + 7 - 1 + 1 = 14). Paths: 0.
Full commit ids of the two solana repos remain as pointers in 40 blobs on 8 program-audit paths, one id per repo
(D1r section 1, P2-R23, P2-R25).

### 3.6 Tests

Fresh `git clone --no-local` of the archive, each project's own suite, no keys, loopback-only network, lock files
where present (tests_report.md and tests_report_r2.md, Method). C4 ran on 2bc0033 (11:00 to 11:03), C4r on d4f2b75
(11:51 to 11:53). The counts below are the same in both runs, row for row, with the same failing ids and causes
(tests_report_r2.md, Comparison 1). No test ran on 4c06138: no code changed (P2-R24).

| Project | Passed | Failed | Errors | Skipped | Cause of failures and skips | README Tests row |
|---|---|---|---|---|---|---|
| ETFExperiment | 241 | 0 | 0 | 1 | skip: live capture fixture not present | same |
| HFExperiment | 149 | 9 | 0 | 0 | the replaced paper account ID (account_mode_mismatch) | same |
| InsiderExperiment | 101 | 0 | 0 | 4 | skips: dispersion store and source bar store not present | same |
| MBTExperiment | 180 | 1 | 0 | 0 | .env.example absent | same |
| MLCryptoEngine | 494 | 21 | 0 | 2 | FileNotFoundError on the 3 excluded fixtures: 11 kraken, 6 hyperliquid, 4 coinbase | same |
| NPDExperiment | 114 | 0 | 0 | 1 | skip: local store not built | same |
| NPLExperiment | 446 | 0 | 0 | 1 | skip: cohort ledgers not present | same |
| ORBExperiment | 418 | 0 | 0 | 1 | skip: cost model not frozen in this tree | same |
| PMExperiment | 110 | 1 | 0 | 0 | .env.example absent | same |
| VRPExperiment | 50 | 0 | 0 | 0 | | same |
| retail-power-limits | 112 | 0 | 0 | 0 | | same |
| program-audit | 6 | 0 | 0 | 0 | `python3 -B tools/test_orchestrator_lock.py`, "Ran 6 tests", OK | same |

What the counts show: the archived code still runs from a fresh clone without keys or network, and every failure
traces to a file the archive removed or replaced (21 fixtures, 9 account ID, 2 .env.example). No failure names a
missing dependency, a key or the blocked network (tests_report.md, Results). ExcludeS1 also ran program-audit's
tests on its scratch build s1a: 6 passed, 0 failed, 0 skipped (s1_exclusion_report.md section 5).

Totals: 2,421 passed, 32 failed, 0 errors, 10 skipped, in each run. These are the sums of the 12 per-project rows of
tests_report_r2.md (the same rows as tests_report.md), confirmed by ReturnCheck (reports/p2_review_return.md F8):
- Passed: 241 + 149 + 101 + 180 + 494 + 114 + 446 + 418 + 110 + 50 + 112 + 6 = 2,421.
- Failed: 9 + 1 + 21 + 1 = 32. Errors: 0.
- Skipped: 1 + 4 + 2 + 1 + 1 + 1 = 10.

The test reports' own total line was wrong (P2-R37). Both say "Totals over the 12: 2,280 passed, 32 failed, 0 errors,
11 skipped" (tests_report.md line 37, tests_report_r2.md line 40), and STATE line 219 (C4r, 11:54:12) copied it. The
12 rows are right. The raw junit XML agrees with the rows: in both sandboxes (/home/kiros-li/.cache/p2-tmp/TestRunner/
Oyd49o/logs and fEf8KE/logs) the 11 pytest projects give 2,415 passed, 32 failed, 0 errors, 10 skipped, and
program-audit's log gives "Ran 6 tests ... OK", so 2,415 + 6 = 2,421 passed (drafter's recount; ReturnCheck F8 found
the same). The README Tests section gives per-project rows only and no total (publish/research-archive/README.md lines
71 to 76), so the archive text is not affected.

### 3.7 The go_public.sh change

B, ScriptCoder-OpusXHigh, 10:30:19 to 10:54:25 (reports/p2_scratch/go_public_test.md):
- Plan first, then push. Steps 3 and 4 build and prepare every repo, the script prints the plan, asks once
  (`Type "go public" to continue:`), then pushes, sets the bio and flips visibility. A real run that hits any stop
  dies before the first push.
- Visibility is read once per repo, and only the exact strings PUBLIC and PRIVATE are stored. A failed call, an empty
  answer or any other string stops.
- llm-news-drift keeps its extraction, and its push is a fast-forward or nothing, never forced, whatever the
  visibility (open choice 2).
- A PRIVATE repo is rebuilt; if the rebuild is not a fast-forward it is force-pushed with
  `--force-with-lease=refs/heads/main:<old>`, only after a second visibility read right before the push.
- A PUBLIC repo takes plan_append: clone GitHub's main into a fresh mktemp -d, check the clone's HEAD against
  ls-remote, replace the tracked tree with the build's (`git read-tree -u --reset`), show `git diff --cached --stat`,
  commit "update from AiTrader <short sha>" with the Co-Authored-By line, self-check the parent and the tree, then a
  plain `git push <url> main:main`. No diff means no commit.
- bio.txt is checked while planning, so a bad bio stops before any push. `--dry-run` runs every step up to the push,
  prints the plan and exits before the prompt.
- Figures: diff 416 lines (352 insertions, 64 deletions); script 520 lines; new harness publish/checks/
  test_go_public.sh 906 lines; 220 of 220 checks in 22 scenario blocks against local bare repos and a stub gh; bash -n
  and shellcheck 0.11.0 clean. Mutants: 19 runs, M00 to M18. M00 is the unchanged script (220/0, a control), M17
  survived as an equivalent mutant, and the other 17 failed. STATE 10:54:25 records this as "18 of 19 mutants
  caught"; the table supports 17 of the 18 mutants M01 to M18 caught, the count FixReview also gives.

D2 found two SHOULD FIX items (5.2). ScriptFix-OpusXHigh, 11:19:00 to 11:33:52 (reports/p2_scratch/go_public_fix.md):
- SF-1: go_public.sh lines 58 to 62 unset GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY,
  GIT_ALTERNATE_OBJECT_DIRECTORIES, GIT_COMMON_DIR, GIT_NAMESPACE, GIT_SHALLOW_FILE and GIT_GRAFT_FILE right after
  `set -euo pipefail`. GIT_CONFIG_* and PATH are left alone, as D2 advised.
- SF-2: the three inherited gates (lines 118 to 123, 158 to 165, 169 to 175) stop on a grep exit 2 or a failed git
  status or git grep. A dry run reports it and exits 1.
- Figures: 23 insertions and 5 deletions in go_public.sh (520 to 538 lines); the harness grew from 906 to 1,091 lines
  with 12 scenario blocks (s17, s18 for each of 8 variables, s19, s20 twice) and 120 checks. The unfixed 73aa37a
  script gives 256 passed, 84 failed, every failure in a new scenario; in s19 and s20 it pushed all three stand-in
  repos, set the bio and made research-archive public, inside the sandbox (STATE 11:33:52). The fixed script gives 340
  of 340, in the sandbox and in place. Reverting each fix alone fails exactly its own scenario. bash -n and
  shellcheck clean.

FixReview-FableXHigh checked the fix independently (5.3): fixed script 340/0; 73aa37a 256/84, failing only in s17 to
s20; original mutants 17 of 18 caught, M17 equivalent by reading; reverts R1 288/52, R2a 328/12, R2b 330/10, R2c
330/10 (p2_review_script_fix.md section 4).

`git diff --numstat 73aa37a` at 13:46: go_public.sh 23 insertions, 5 deletions; test_go_public.sh 186 insertions, 1
deletion. These changes are uncommitted until the final commit, which is why the E3 dry run reports "publish/ has
uncommitted changes".

Not exercised by any harness: the real extract.sh and build_archive.sh under the script (first run for real by E3),
real gh output formats, and a Ctrl-C during a push (p2_review_script.md section 5, p2_review_script_fix.md "Not
checked").

### 3.8 GitHub

E1, 13:13:07, exit 0 at 13:13:14. The output as STATE records it, lines separated by " / " there:

```
https://github.com/kirosli00tuff/research-archive
To https://github.com/kirosli00tuff/research-archive.git
 * [new branch]      HEAD -> main
branch 'main' set up to track 'origin/main'.
```

Check (gh read and git): visibility PRIVATE, default branch main, description "", topics null, homepage "";
`git ls-remote` HEAD and refs/heads/main both 4c06138700a342d9bea18cecd085b208a061ee94, no other ref. The local archive
now has remote origin and main tracks origin/main (gh's doing).

E2 (metadata.json already had the research-archive entry, homepage "", so no edit there):
- E2a, 13:13:34: description set to "12 research projects from July to September 2026, each with its git history
  kept and a one-page card." The topic list came out empty (a lead shell error), so no topic was added. No output,
  exit 0. Check: topics null, homepage "", PRIVATE.
- E2b, 13:13:44: `--add-topic "research-archive,trading-research,backtesting,pre-registration"`. No output, exit 0.
  Check: topics backtesting, pre-registration, research-archive, trading-research; description as E2a; homepage "";
  PRIVATE.

E4, `gh repo list kirosli00tuff --limit 100 --json name,visibility`, redacted copies in reports/p2_github_before.json
(13:12:29, 19 rows) and reports/p2_github_after.json (13:17:03, 20 rows). The helper redacted 2 names and leaked 0
both times.

| Repo | Before (13:12:29) | After (13:17:03) |
|---|---|---|
| research-archive | absent | PRIVATE |
| AiTrader | PUBLIC | PUBLIC |
| kirosli00tuff | PUBLIC | PUBLIC |
| llm-news-drift | PUBLIC | PUBLIC |
| PropExperiment | PUBLIC | PUBLIC |
| the portfolio repo | PUBLIC | PUBLIC |
| NPLExperiment | PRIVATE | PRIVATE |
| program-audit | PRIVATE | PRIVATE |
| PMExperiment | PRIVATE | PRIVATE |
| VRPExperiment | PRIVATE | PRIVATE |
| ORBExperiment | PRIVATE | PRIVATE |
| NPDExperiment | PRIVATE | PRIVATE |
| InsiderExperiment | PRIVATE | PRIVATE |
| HFExperiment | PRIVATE | PRIVATE |
| ETFExperiment | PRIVATE | PRIVATE |
| retail-power-limits | PRIVATE | PRIVATE |
| solattn | PRIVATE | PRIVATE |
| solclear | PRIVATE | PRIVATE |
| MLCryptoEngine | PRIVATE | PRIVATE |
| the roofing concept repo | PRIVATE | PRIVATE |

One difference: research-archive, absent to PRIVATE. Against reports/p1_github_after.json the before list differs
only in kirosli00tuff and llm-news-drift, PRIVATE to PUBLIC: the go-live at about 10:18, before this stage (STATE
13:12:29, prompt line 8).

### 3.9 The --dry-run output, verbatim

/home/kiros-li/.cache/p2-tmp/e3_dry_run.txt (111 lines, including the exit line), from E3 at 13:14:09 to 13:14:34:

```
== dry run: nothing on GitHub is changed
/home/kiros-li/Documents/GitHub/AiTrader/publish/research-archive/SOURCES.txt:27:# [KIROS: confirm] 10 of the 12 kept sources still name three of those six repos, or the word solana, in their
a real run would stop here: step 1: 1 confirm marks remain under publish/. Resolve each one, then run again.
== step 2: gh has the user scope
a real run would stop here: publish/ has uncommitted changes. The builds read committed files: commit them first.
a real run would stop here: HEAD still holds confirm marks under publish/. Commit the resolved files first.
== llm-news-drift: GitHub reports it PUBLIC
== research-archive: GitHub reports it PRIVATE
== kirosli00tuff: GitHub reports it PUBLIC
== builds go to /home/kiros-li/.cache/p2-tmp/go_public.BT42Js (kept for inspection, delete it when done)
source: /home/kiros-li/Documents/GitHub/AiTrader
ref: HEAD = 73aa37ab13471bad5f192c8ae3c527e1fede7347
replace-text: publish/checks/llm-news-drift.replace-text at HEAD
commits to filter: 62 (the cut commit and 61 after it)
filter-repo: a. allowlist, mailmap and replace-text
filter-repo: b. exclude list on original paths
filter-repo: c. move publish/llm-news-drift/ to the root
cut: 74532e7 -> f99fe723b846c7f0982546973e30b1adcf94bd47
first: f99fe723b846c7f0982546973e30b1adcf94bd47 2026-07-27T20:00:45-07:00 Propose the stage 0 pre-registration for the news-drift experiment, specification only, nothing built, pending operator review
last:  3367d9b090c34d71338203f2afc67f6f8dcf0681 2026-11-07T10:24:20-07:00 docs: V10 and Stage P.2 prompt (research-archive without solana)
commits: 53
git: 2.53.0, git-filter-repo: a40bce548d2c
out: /home/kiros-li/.cache/p2-tmp/go_public.BT42Js/llm-news-drift
== step 3: llm-news-drift prepared, nothing pushed yet
[ETFExperiment] clone /mnt/large-storage/Archive/GitHub/ETFExperiment (master)
[ETFExperiment] pre-pass: R1 and R2 over every (path, blob) in history
[ETFExperiment] git-filter-repo
[ETFExperiment] check and count
[HFExperiment] clone /mnt/large-storage/Archive/GitHub/HFExperiment (main)
[HFExperiment] pre-pass: R1 and R2 over every (path, blob) in history
[HFExperiment] git-filter-repo
[HFExperiment] check and count
[InsiderExperiment] clone /mnt/large-storage/Archive/GitHub/InsiderExperiment (master)
[InsiderExperiment] pre-pass: R1 and R2 over every (path, blob) in history
[InsiderExperiment] git-filter-repo
[InsiderExperiment] check and count
[MBTExperiment] clone /mnt/large-storage/Archive/GitHub/MBTExperiment (main)
[MBTExperiment] pre-pass: R1 and R2 over every (path, blob) in history
[MBTExperiment] git-filter-repo
[MBTExperiment] check and count
[MLCryptoEngine] clone /mnt/large-storage/Archive/GitHub/MLCryptoEngine (main)
[MLCryptoEngine] pre-pass: R1 and R2 over every (path, blob) in history
[MLCryptoEngine] git-filter-repo
[MLCryptoEngine] check and count
[NPDExperiment] clone /mnt/large-storage/Archive/GitHub/NPDExperiment (main)
[NPDExperiment] pre-pass: R1 and R2 over every (path, blob) in history
[NPDExperiment] git-filter-repo
[NPDExperiment] check and count
[NPLExperiment] clone /mnt/large-storage/Archive/GitHub/NPLExperiment (main)
[NPLExperiment] pre-pass: R1 and R2 over every (path, blob) in history
[NPLExperiment] git-filter-repo
[NPLExperiment] check and count
[ORBExperiment] clone /mnt/large-storage/Archive/GitHub/ORBExperiment (main)
[ORBExperiment] pre-pass: R1 and R2 over every (path, blob) in history
[ORBExperiment] git-filter-repo
[ORBExperiment] check and count
[PMExperiment] clone /mnt/large-storage/Archive/GitHub/PMExperiment (main)
[PMExperiment] pre-pass: R1 and R2 over every (path, blob) in history
[PMExperiment] git-filter-repo
[PMExperiment] check and count
[VRPExperiment] clone /mnt/large-storage/Archive/GitHub/VRPExperiment (main)
[VRPExperiment] pre-pass: R1 and R2 over every (path, blob) in history
[VRPExperiment] git-filter-repo
[VRPExperiment] check and count
[program-audit] clone /mnt/large-storage/Archive/GitHub/program-audit (main)
[program-audit] pre-pass: R1 and R2 over every (path, blob) in history
[program-audit] git-filter-repo
[program-audit] check and count
[retail-power-limits] clone /mnt/large-storage/Archive/GitHub/retail-power-limits (main)
[retail-power-limits] pre-pass: R1 and R2 over every (path, blob) in history
[retail-power-limits] git-filter-repo
[retail-power-limits] check and count
building the archive at /home/kiros-li/.cache/p2-tmp/go_public.BT42Js/research-archive
[MLCryptoEngine] merge: import MLCryptoEngine history (2026-07-30..2026-08-22, 91 commits)
[HFExperiment] merge: import HFExperiment history (2026-08-23..2026-08-28, 13 commits)
[NPDExperiment] merge: import NPDExperiment history (2026-08-25..2026-08-25, 11 commits)
[InsiderExperiment] merge: import InsiderExperiment history (2026-08-25..2026-08-25, 7 commits)
[NPLExperiment] merge: import NPLExperiment history (2026-08-26..2026-09-21, 41 commits)
[ETFExperiment] merge: import ETFExperiment history (2026-08-28..2026-08-28, 28 commits)
[ORBExperiment] merge: import ORBExperiment history (2026-08-28..2026-08-29, 59 commits)
[PMExperiment] merge: import PMExperiment history (2026-08-29..2026-09-02, 36 commits)
[retail-power-limits] merge: import retail-power-limits history (2026-08-29..2026-08-29, 3 commits)
[VRPExperiment] merge: import VRPExperiment history (2026-08-29..2026-08-30, 12 commits)
[program-audit] merge: import program-audit history (2026-08-29..2026-09-13, 82 commits)
[MBTExperiment] merge: import MBTExperiment history (2026-09-02..2026-09-12, 23 commits)
replace-text scan of the whole archive
done: 420 commits, head 4c06138700a342d9bea18cecd085b208a061ee94
archive: /home/kiros-li/.cache/p2-tmp/go_public.BT42Js/research-archive
report:  /home/kiros-li/.cache/p2-tmp/go_public.BT42Js/archive_build_report.md
== step 4: research-archive prepared, nothing pushed yet
== profile: built 327dc285d1daf0684209aad7a1044fed3c1a19b9 in /home/kiros-li/.cache/p2-tmp/go_public.BT42Js/kirosli00tuff
== step 4: the profile repo prepared, nothing pushed yet
== dry run: a real run would do this:
  llm-news-drift (PUBLIC): push 3fb1324465f67b36701d2ecab879bb5b1e2780c8 -> 3367d9b090c34d71338203f2afc67f6f8dcf0681, a fast-forward
  research-archive (PRIVATE): nothing to push, GitHub's main already is the rebuild 4c06138700a342d9bea18cecd085b208a061ee94
  kirosli00tuff (PUBLIC): push b72c1226571587d321999ddd0e52b1ec0aaf3f48 -> ebe5f95128c69acadbd3059e317fe0d0f712eaf9, a fast-forward that appends one commit, "update from AiTrader 73aa37a":
       README.md | 7 +++++--
       1 file changed, 5 insertions(+), 2 deletions(-)
  bio: unchanged, GitHub already has the text of bio.txt
  make public: research-archive
  already public, left alone: llm-news-drift kirosli00tuff
== step 7: do these on github.com, they have no gh command:
  1. Profile page, "Customize your pins": pin llm-news-drift, PropExperiment and research-archive.
  2. Settings > Public profile > Contributions: turn on "Include private contributions on my profile".
  3. Settings > Public profile: set the avatar.
== dry run: nothing was pushed, no bio was set and no repo was made public. Builds and clones: /home/kiros-li/.cache/p2-tmp/go_public.BT42Js
== dry run: a real run would have stopped (3):
  - step 1: 1 confirm marks remain under publish/. Resolve each one, then run again.
  - publish/ has uncommitted changes. The builds read committed files: commit them first.
  - HEAD still holds confirm marks under publish/. Commit the resolved files first.
exit 1
```

Notes:
- It ran before the final commit, as planned (open choice 18). So llm-news-drift and the profile were built from HEAD
  73aa37a (the "ref: HEAD = 73aa37a..." line and the "update from AiTrader 73aa37a" message), while the archive was
  built by the working-tree build_archive.sh and reproduced 4c06138 (STATE 13:14:09).
- The three would-stops are expected (STATE 13:14:09, D2 N-5): the one confirm mark at SOURCES.txt:27, publish/ not
  committed, and HEAD still holding marks. The mark line it quotes is line 27 as of 13:12:11.
- E3's three expectations (prompt Part E) are met: llm-news-drift a fast-forward, 3fb1324 to 3367d9b; kirosli00tuff
  one appended commit; research-archive PRIVATE, "nothing to push" because GitHub's main already is 4c06138, and
  "make public: research-archive".
- The profile line shows `README.md | 7 +++++--` because it was built from 73aa37a's README. After P2-R36 the planner's
  own dry run after the final commit will show `README.md | 4 ++--`, the archive link only (STATE 13:15, P2-R36). The
  llm-news-drift target will then be newer than 3367d9b, because the final commit touches allowlisted paths
  (docs/STAGES.md and docs/prompts/README.md; p2_review_return.md finding 2). It must still be a fast-forward from
  3fb1324.

## 4. Delegation record

Spawn and return times are from reports/P.2_STATE.md. Agent types come from STATE's spawn lines, and for A2 and B
from their transcripts' meta.json (worker-high and worker-xhigh). "Served" is the model on the assistant lines of
each transcript: for the reviewers as STATE records the lead's count, and for every row the models column of the
per-file rows in reports/p2_scratch/cost_tokens.md. Transcripts sit under
~/.claude/projects/-home-kiros-li-Documents-GitHub-AiTrader/<lead session>/subagents/. Tokens per spawn are in
section 8.

| # | Agent | Type | Model, effort | Objective | Spawned | Returned | Transcript | Status and deviations |
|---|---|---|---|---|---|---|---|---|
| 1 | ScriptCoder-OpusXHigh (B) | worker-xhigh | opus, xhigh | Part B: go_public.sh for public repos, with a harness | 10:30:19 | 10:54:25 | 7c6505c3 / agent-a9f934c7cd5e9b6b3 | Done, 1,427 s. 220/220, mutants as in 3.7. Kept llm-news-drift on extraction and fast-forward (its brief item 4, open choice 2). Served claude-opus-5-5 |
| 2 | ArchiveText-OpusHigh (A2) | worker-high | opus, high | A2: the P.1 open items in the README and cards | about 10:33:34 (transcript; STATE says "spawned earlier") | 10:38:41 | 7c6505c3 / agent-aba10fc6ef7d99d0d | Done, 290 s. Items 1 to 9, 11 and 12 applied; item 10 trimmed but over the length aim (open choice 4). SendMessage at 10:37: do not change the lesson text. Served claude-opus-5-5 |
| 3 | ScanRunner-SonnetHigh (C3) | worker-high | sonnet, high | C3 scans on 2bc0033 | 11:00:53 | 11:03:33 | 6b3df7ac / agent-a2b0dee917bfc5632 | Done, about 121 s. bulktext and headlines were not in its brief; the lead ran them (open choice 8). Served claude-sonnet-5-5 |
| 4 | TestRunner-SonnetHigh (C4) | worker-high | sonnet, high | C4 fresh-clone tests on 2bc0033 | 11:00:53 | 11:03:38 | 6b3df7ac / agent-ab29a076863ddc2fc | Done, about 179 s. Rows right; the report's total line was wrong (3.6, P2-R37). Served claude-sonnet-5-5 |
| 5 | ArchiveReviewer-FableXHigh (D1) | worker-xhigh | fable, xhigh | D1: independent review of the 2bc0033 build, README and cards | 11:00:53 | 11:22:07 | 6b3df7ac / agent-a0cd118a10118fd17 | Done, 1,268 s. 0 BLOCKING, 1 SHOULD FIX, 9 NOTE. Served claude-fable-5-1 on 152 assistant lines (STATE 11:22:07) |
| 6 | ScriptReviewer-FableXHigh (D2) | worker-xhigh | fable, xhigh | D2: push-safety review of e5c1810..73aa37a | 11:00:53 | 11:17:55 | 6b3df7ac / agent-a048c5c9da4c70dde | Done, 1,016 s. 0 BLOCKING, 2 SHOULD FIX, 9 NOTE. Served claude-fable-5-1 on all 55 assistant lines (STATE 11:17:55) |
| 7 | ScriptFix-OpusXHigh | worker-xhigh | opus, xhigh | Fix D2 SF-1 and SF-2, new scenarios red before and green after | 11:19:00 | 11:33:52 | 6b3df7ac / agent-a5c6d9bce8bc068bd | Done, 882 s. Brief inline in the spawn, no brief file. Not in the prompt's plan. Served claude-opus-5-5 (also its report header) |
| 8 | ExcludeS1-OpusHigh | worker-high | opus, high | P2-R1 steps a to c: path set, address scan, EXCLUDE rule, claim edits, scratch build, program-audit tests | 11:40:51 | 11:47 | a6eca48f / agent-ae1775ee25fbde7d6 | Done, 475 s. Not in the plan. Served claude-opus-5-5 on 97 lines (STATE 11:56) |
| 9 | FixReview-FableXHigh | worker-xhigh | fable, xhigh | Independent check of the SF-1 and SF-2 fix | 11:40:51 | 13:04:47 (report mtime) | a6eca48f / agent-a47b11b8336e5424a | Done. Stopped by the usage limit about 11:59 after its runner finished (11:59:15); resumed by SendMessage at 13:02 to write the report; active 521 s + 151 s = 672 s. 0 BLOCKING, 0 SHOULD FIX, 6 NOTE. A fresh spawn, not a SendMessage to D2 (open choice 11). Served {'claude-fable-5-1': 62, '<synthetic>': 1} (STATE 13:04:47) |
| 10 | ScanRunner-SonnetHigh (C3r) | worker-high | sonnet, high | C3 rerun on d4f2b75, with bulktext and headlines | 11:51:29 | 11:54:01 (report mtime) | a6eca48f / agent-a80ab2390e600a140 | Done, 191 s. Served claude-sonnet-5-5 on 28 lines (STATE 12:00:50) |
| 11 | TestRunner-SonnetHigh (C4r) | worker-high | sonnet, high | C4 rerun on d4f2b75 | 11:51:29 | 11:54:12 (report mtime) | a6eca48f / agent-a89874c5830954e79 | Done, 198 s. Rows right; the same wrong total line as C4 (3.6, P2-R37). Served claude-sonnet-5-5 on 21 lines (STATE 12:00:50) |
| 12 | ArchiveRecheck-FableXHigh (D1r) | worker-xhigh | fable, xhigh | Recheck of the S1 rebuild d4f2b75 | 11:51:29 | 12:00:50 (report mtime) | a6eca48f / agent-af1f8cb3ee45349de | Done. Report complete (147 lines); its final reply was cut by the usage limit (HTTP 429). 0 BLOCKING, 0 SHOULD FIX, 5 NOTE. Served claude-fable-5-1 on 64 lines plus 1 synthetic error line (STATE 12:00:50) |
| 13 | ReturnDrafter-OpusXHigh | worker-xhigh | opus, xhigh | Header and sections 2 to 5 of this return | 13:36:11 | 13:52:32 (transcript) | bfca6777 / agent-ab984e1896a247f28 | Done, 991 s. Took the lead's 13:50 message (P2-R37, P2-R39, P2-R40) while running. Ran precommit_private_scan.py with --help by mistake: no literal or count shown (2.3). Served claude-opus-5-5 on all 132 assistant lines |
| 14 | ReturnCheck-FableXHigh | worker-xhigh | fable, xhigh | Independent check of the return's facts and sections 1 and 7 | 13:36:11 | 13:48:48 (transcript; report run ended 13:48:37) | bfca6777 / agent-a0c9beb72aea3cb94 | Done, 767 s. 8 MATCH, 2 MISMATCH, 0 UNVERIFIABLE; BLOCKING 1, SHOULD FIX 1, NOTE 7, ruled P2-R37 to P2-R42 (5.6). Not in the prompt's plan (open choice 25). Served claude-fable-5-1 on all 99 assistant lines |

Lead contexts (STATE wipe lines; spans from the per-file rows in cost_tokens.md, converted from UTC to MST):

| Context | Transcript | From | To | Ended by |
|---|---|---|---|---|
| Lead 1 | 7c6505c3-48da-4ce2-b919-14c19f45ba1c | 10:24:28 | 10:55:11 | self-wipe 1, done 10:57:42 |
| Lead 2 | 6b3df7ac-8e2b-44ec-895e-608c0f7a5607 | 10:57:42 | 11:33:52 | self-wipe 2, done 11:36:20 |
| Lead 3 | a6eca48f-71e5-4629-9fef-0065050fdaa1 | 11:36:20 | 13:05:31, stopped by the usage limit about 11:59 to 13:02:05 | self-wipe 3, done 13:08:04 |
| Lead 4 | c6e57c48-2efc-46b0-97fd-ed51d0860335 | 13:08:04 | 13:17:41 | self-wipe 4, done 13:20:25 |
| Lead 5 | 09500226-236c-493d-830a-bdc7da5fa256 | 13:20:25 | 13:32:28 | self-wipe 5, done 13:35:06 |
| Lead 6 | bfca6777-d73e-4174-b511-00105d40933f | 13:35:06 | the final commit (end checks 13:55:39) | the final commit, no wipe (open choice 28) |

STATE line 206 (in the 11:56 RESUME HERE, step 5) names 6b3df7ac as the transcript of "leads 1, 2". That is wrong:
there are two files. Lead 1 is 7c6505c3 (its first user message is the launch prompt, "Read docs/prompts/STAGE_P.2.md
in full and execute it as your prompt...", entries 10:24:22 to 10:55:20), and lead 2 is 6b3df7ac (10:57:16 to
11:33:59). A2 and B are subagents of 7c6505c3 (cost_tokens.md per-file rows).

Deviations from the prompt's delegation plan:
- The plan lists the lead, A2, B, C3, C4, D1 and D2. Added: ScriptFix (fix of D2's SHOULD FIX items), ExcludeS1
  (P2-R1), FixReview (independent check of the fix), C3r, C4r and D1r (reruns after the S1 rebuild), ReturnDrafter
  and ReturnCheck (open choices 24 and 25).
- Lead work done inline that the plan gives to no worker: the R43 rule (so no worker saw the literal), the bulktext
  and headlines scans on 2bc0033, the grep_scan rerun on 4c06138, every build, every gh call and every ruling.
- The 5-hour usage limit stopped lead 3, FixReview and D1r's final reply from about 11:59 to 13:02. FixReview was
  resumed by message. D1r's report was already complete.
- Five planned self-wipes (10:55, 11:33, 13:05, 13:17, 13:32), six lead contexts up to this draft.

## 5. Verification

The four Fable reviews, each finding with its class, the lead's ruling (reports/p2_rulings.md) and the fix. What
each review judged: D1 the archive build 2bc0033 with README and cards at 73aa37a; D2 the go_public.sh diff
e5c1810..73aa37a and its harness; FixReview the uncommitted fix on top of 73aa37a; D1r the S1 rebuild d4f2b75. D1r
did not see the final 4c06138. The only delta from d4f2b75 to 4c06138 is the EXCLUDE.txt comment (P2-R24): `git diff
--stat d4f2b75 4c06138` lists EXCLUDE.txt only, 2 insertions and 2 deletions, and the commit count stays 420 (STATE
13:03:44). D1r's verdict therefore carries over for every other file. The comment change was checked by the lead
(term counts in the built EXCLUDE.txt) and by the grep_scan rerun (3.5).

### 5.1 D1, ArchiveReviewer-FableXHigh (reports/p2_review_archive.md): BLOCKING 0, SHOULD FIX 1, NOTE 9

D1 also confirmed on 2bc0033: 421 commits as root + 12 merges + 407 + cards; one identity on all 842 author and
committer slots; fsck --strict clean; 2,703 blobs, none over 1 MB; 0 EXCLUDE.txt matches in 1,515 historical paths;
README, EXCLUDE.txt and the 12 cards byte-identical to 73aa37a; 158 of 158 card figures traced; the AI figures (122;
82, 39, 1; 8 of 12 with CLAUDE.md); 12 of 12 Tests rows; all 12 A2 items; no confirm mark in README or cards.

| Finding | Class | Ruling | Fix |
|---|---|---|---|
| S1: 46 program-audit findings files on solattn and solclear, 2,520,593 bytes, with the two repos' commit ids, file inventories, figures and 8 on-chain addresses (D1's count, line 56; the ninth was found at the D1r recheck, P2-R27) | SHOULD FIX | P2-R1: FIX by exclusion (11:22:44) | One EXCLUDE.txt regex, claim edits traced, rebuilt as d4f2b75, then 4c06138 (P2-R24). D1r: fixed (5.4) |
| N1: ORB card "within two minutes" for 127 s | NOTE | P2-R4 | Fixed: "within about two minutes" (11:49) |
| N2: PM card quotes a fragment in lower case | NOTE | P2-R5 | No change |
| N3: two excluded_path scan hits | NOTE | P2-R6 | No change, scan artefact |
| N4: /home/kiros-li in 425 blobs | NOTE | P2-R7 | No change, the OS username |
| N5: public third-party business addresses | NOTE | P2-R8 | No change |
| N6: Hyperliquid 0x addresses in NPL docs | NOTE | P2-R9 | No change |
| N7: 4 blobs shared with the six originals | NOTE | P2-R10 | No change, boilerplate |
| N8: gitleaks 408 of 421 commits | NOTE | P2-R11 | No change |
| N9: counting definition for the public terms | NOTE | P2-R12 | Use C3's counting; final counts from the reruns (3.5). D1r reproduced C3's 2bc0033 table exactly (D1r section 4) |

D1 did not check: bulktext and headlines (the lead ran them), the Tauri desktop app, ~/.config/p1-private/, and the
public llm-news-drift README.

### 5.2 D2, ScriptReviewer-FableXHigh (reports/p2_review_script.md): BLOCKING 0, SHOULD FIX 2, NOTE 9

D2 reran the harness in its sandbox: 220/220, per-scenario counts equal to the author's. Every item on its hunt list
traced clean (force-push of a public repo, a repo made public by mistake, a push without the mark check, a dry run
that changes GitHub, llm-news-drift on a force path, test hooks reaching production).

| Finding | Class | Ruling | Fix |
|---|---|---|---|
| SF-1: GIT_DIR, GIT_WORK_TREE and GIT_INDEX_FILE not cleared; with GIT_DIR exported a dry run rewrote the stand-in AiTrader HEAD (GitHub unaffected) | SHOULD FIX | P2-R2: FIX (11:19:00) | ScriptFix, lines 58 to 62. FixReview: fixed (5.3) |
| SF-2: three inherited gates (old lines 113, 148, 155) read a grep or git error as clean | SHOULD FIX | P2-R3: FIX (11:19:00) | ScriptFix, lines 118 to 123, 158 to 165, 169 to 175. FixReview: fixed |
| N-1: bare `main` and a tail-matched ls-remote pattern | NOTE | P2-R13 | No change in P.2, hardening item |
| N-2: window between the second visibility read and the force push | NOTE | P2-R14 | No change; the lease refuses a moved ref |
| N-3: a late stop leaves earlier repos pushed | NOTE | P2-R15 | No change, by design |
| N-4: the public append path replaces the whole tracked tree, so web edits are deleted at the next update | NOTE | P2-R16 | No change; carried to section 7.2 |
| N-5: facts for the E3 dry run | NOTE | P2-R17 | Used in E3; all three expectations met (3.9) |
| N-6: the Co-Authored-By trailer names Claude Opus 5.5 | NOTE | P2-R18 | Kept |
| N-7: untested die paths; the real builders not under the harness | NOTE | P2-R19 | No change; all are stop paths |
| N-8: two functions differ in form only | NOTE | P2-R20 | No change |
| N-9: harness 906 lines | NOTE | P2-R21 | Accepted (now 1,091 lines after ScriptFix) |

D2 did not check: the real builders under the script, real gh output formats, the author's mutants, and a Ctrl-C
during a push.

### 5.3 FixReview, FixReview-FableXHigh (reports/p2_review_script_fix.md): BLOCKING 0, SHOULD FIX 0, NOTE 6

Verdict: SF-1 and SF-2 are fixed as D2 wrote them. The unset at lines 61 to 62 runs before the first git call (line
159) and covers every repository, work-tree, index and object-store variable in `git rev-parse --local-env-vars`. All
three gates stop in both modes, and no other gate reads an error as clean. The diff adds no path that pushes,
force-pushes, rewrites or deletes a ref, flips visibility or sets the bio. Harness and mutant figures in 3.7.

| Finding | Class | Ruling | Fix |
|---|---|---|---|
| NOTE 1: the GIT_CONFIG_* channel stays open; a pushInsteadOf there could redirect a push | NOTE | P2-R30 | No script change in P.2; go-live from a fresh login shell with no GIT_* exported; hardening item (7.4) |
| NOTE 2: GIT_TEMPLATE_DIR not cleared | NOTE | P2-R31 | No change; hardening item (7.4) |
| NOTE 3: GIT_DEFAULT_HASH and GIT_DEFAULT_REF_FORMAT not cleared; they fail closed | NOTE | P2-R32 | No change; hardening item |
| NOTE 4: GIT_LITERAL_PATHSPECS makes the HEAD mark check stricter | NOTE | P2-R33 | No change |
| NOTE 5: GIT_AUTHOR_DATE and GIT_COMMITTER_DATE reach the appended commit | NOTE | P2-R34 | No change; covered by the fresh-shell instruction; hardening item (7.4) |
| NOTE 6: discovery variables are harmless | NOTE | P2-R35 | No change |

FixReview did not check: the real builders, gh or GitHub, a real index or object corruption behind the gates (s20
injects exit 128 through a wrapper), GIT_QUARANTINE_PATH beyond a rev-parse probe, and the harness in place (sandbox
copies only; the fix report ran it in place, 340/0).

### 5.4 D1r, ArchiveRecheck-FableXHigh (reports/p2_review_archive_recheck.md): BLOCKING 0, SHOULD FIX 0, NOTE 5

Verdict: S1 is fixed, and the rebuild changed only what P2-R1 and the traced edits intended. Recomputed on d4f2b75:
0 history paths with solattn or solclear (46 before); 0 of 2,642 blobs hold any of the on-chain identifiers, D1's 8
plus the ninth D1r found (10 of 2,703 blobs held D1's 8 before); 46 paths removed, exactly the rule's matches, 0 added; only program-audit's commit count changed, 83
to 82; 4 new blobs (README.md, EXCLUDE.txt and two cards) equal to the working copies; one identity on all 420
commits; fsck --strict clean; largest blob 667,208 bytes; each changed README and card statement recomputed on the
build; public-term counts as C3r (3.5).

| Finding | Class | Ruling | Fix |
|---|---|---|---|
| NOTE 1: D1's 84 and 89 "before" blob counts for full solana commit ids do not reproduce; 65 and 70 do; after 40 blobs on 8 paths, one id per repo | NOTE | P2-R25 | Mention class (P2-R23) |
| NOTE 2: EXCLUDE.txt is a fourth new blob, by design | NOTE | P2-R26 | No change; P2-R24 then changed only its comment |
| NOTE 3: a ninth on-chain identifier (a mint, prefix AMBh) left with the excluded files, 0 blobs | NOTE | P2-R27 | The return says 9 identifiers |
| NOTE 4: D1r's own transcript holds five solattn commit ids read from D1's sandbox | NOTE | P2-R28 | Audit trail only; not p1-private literals; nothing written to the tree |
| NOTE 5: the program-audit card's Result cites CROSS_REPO.md, whose first finding is on solclear | NOTE | P2-R29 | Mention class (P2-R22); offered to Kiros (7.1 C) |

D1r did not check: the C3r and C4r reruns, ~/.config/p1-private/, go_public.sh, the README Tests table beyond the
statements it lists, and the GitHub side.

### 5.5 Lead items and checks that were not Fable reviews

Lead rulings on worker items:
- ExcludeS1 items 1 and 3 (full solana commit ids in kept files; message subjects 8 to 7): P2-R23, mention class.
- ExcludeS1 item 2 (CROSS_REPO.md and .json keep a solclear finding, 73 lines naming the two repos): P2-R22, stays in
  the mention class; named in the SOURCES.txt mark; exclusion offered to Kiros (7.1 C).
- ExcludeS1 item 5 (EXCLUDE.txt line 22 keeps P.1's "1,359 paths" comment): untouched (open choice 16).
- C3r's new public-term location, EXCLUDE.txt: P2-R24, comment reworded, rebuilt as 4c06138.
- The profile web edit found in the E3 build folder (13:15): P2-R36, mirrored in publish/profile/README.md.
- The class ruling on the mentions, with the 4c06138 counts (3.5).

Checks by Sonnet workers against fixed references:
- C3 against P.1 (d358b35a): 0 new findings in gitleaks, secrets, paths and hygiene. C3r: 0 new against P.1 and 0 new
  against the first run, and every finding gone sits under an S1 path (3.5).
- C4 against the README Tests section: 12 of 12 rows agree on counts and causes, and with the P.1 report for these 12
  projects. C4r: equal to C4 row for row, and the README Tests section is byte-identical between the two builds
  (3.6). Both reports' own total line was wrong; the rows are right (3.6, P2-R37).

Lead checks (STATE):
- The 10:40:46 pre-build and the three C2 builds give the same HEAD and rev-list hash (10:59:29).
- bulktext and headlines on 2bc0033 against P.1: the same multiset outside solana/, headlines 0 (11:03:33).
- Round 2 and round 3: three identical builds each (11:50:42, 13:03:44). 4c06138 against d4f2b75: EXCLUDE.txt only, 2
  insertions, 2 deletions, checked by fetching the final into scratch r2s1b as refs/heads/new; the built EXCLUDE.txt
  holds solana 0, solattn 1, solclear 1 (13:03:44).
- grep_scan on 4c06138 differs from C3r's d4f2b75 table only in the HEAD line and EXCLUDE.txt's (1, 1, 1) (13:08:57).
- E1 read-back: PRIVATE, ls-remote main 4c06138. E2a and E2b read-backs. E3: all three expectations met. E4: one
  difference (3.8).
- C1 private-literal count over the 21 staged files: 0 (10:54:36).

Drafter's checks while drafting (13:36 to 13:52):
- Test totals: the rows and the junit XML give 2,421 passed, 32 failed, 0 errors, 10 skipped, not the 2,280 and 11 in
  both test reports' total line and STATE line 219 (3.6). ReturnCheck found the same independently (F8); the lead
  ruled it P2-R37.
- Mutants: B's table supports 17 of 18 mutants caught, not STATE's "18 of 19" (3.7).
- STATE line 206's "leads 1, 2" for 6b3df7ac is wrong: two transcripts (section 4).
- Local archive re-read at 13:42: HEAD 4c06138, 420 commits, rev-list sha256 prefix b512bfa367bc5ef4 (2.6).

### 5.6 ReturnCheck, ReturnCheck-FableXHigh (reports/p2_review_return.md): BLOCKING 1, SHOULD FIX 1, NOTE 7

Model: claude-fable-5-1 on all 99 assistant lines of agent-a0c9beb72aea3cb94 (lead count at its return, 13:53).
Report run 13:36:16 to 13:48:37. Claims F1 to F10: 8 MATCH, 2 MISMATCH (F8 part 1, F10), 0 UNVERIFIABLE, each
recomputed from the raw repos, read-only gh calls and the files, the mark figures with its own counter (scratch
/home/kiros-li/.cache/p2-tmp/ReturnCheck.jrnhxy). It ran in parallel with ReturnDrafter, so it checked the lead's
sections 1, 6 and 7 and the record, not sections 2 to 5.

| Finding | Class | Ruling | Fix |
|---|---|---|---|
| 1. Test totals: 2,421 passed, 32 failed, 0 errors, 10 skipped, not 2,280 and 11 | BLOCKING | P2-R37 | Sections 1, 3.6 and 5, PROGRESS.md and docs/STAGES.md; ReturnDrafter told by message before it finished; STATE and tests_report_r2.md keep their lines with an appended correction |
| 2. 7.5 step 3: the llm-news-drift target will be newer than 3367d9b | SHOULD FIX | P2-R38 | 7.5 step 3 reworded; COLLECTION_LOG.md line added to 7.6 |
| 3. 7.1 file counts are distinct paths, one path per blob | NOTE | P2-R41 | 7.1 wording |
| 4. The archive build reads publish/research-archive from the working tree | NOTE | P2-R42 | No change to go_public.sh; the fact and the mark-deletion check in 7.6 |
| 5. README 852 words as built, 842 at A2 | NOTE | P2-R40 | Open choice 4 |
| 6. D1 found 8 identifiers; the ninth came at D1r | NOTE | P2-R39 | Section 1 and PROGRESS.md |
| 7. The local clone also has refs/remotes/origin/main | NOTE | no change | none |
| 8. d4f2b75 and 4c06138 are sibling builds, not ancestor and child | NOTE | no change | none |
| 9. Open choice 23's line count not rechecked; item 26's ids checked for existence only | NOTE | no change | Lead check: the fifth lead's 13:20:25 line is STATE line 263, so "about 265 lines" holds |

Not done by ReturnCheck: the private terms were not recounted, because its brief kept ~/.config/p1-private/ out of
scope. The lead's p2r3 grep_scan rows read 0.

## 6. Open choices

Every decision a lead made on its own, with the reason. Choices 1 to 22 come from reports/P.2_STATE.md (the RESUME
HERE lists at 10:58, 11:06, 11:56 and 13:17:41); 23 to 26 are the fifth lead's; 27 to 30 are the sixth lead's.

1. The 12 kept sources name the six left-out repos (first count on the P.1 build: about 4,600 HEAD-tree lines, 20
   messages, 68 paths). No rewrite of other projects' records, because V10 removes the six sources, not mentions of
   them. A class ruling and one gate mark in SOURCES.txt instead, so go_public.sh refuses until Kiros decides. P2-R1
   later narrowed the class by excluding the dedicated audit files. Final counts: 6,557 occurrences, 14 messages,
   0 paths.
2. llm-news-drift keeps extraction plus fast-forward only, not the append path (prompt Part B bullet 1 against
   bullet 3): its history is an extraction of AiTrader, so an appended commit would break the match.
3. reports/p2_scratch/ stays untracked, like reports/p1_scratch/.
4. The README at 852 words as built (842 at A2, before the P2-R1 and P2-R24 edits; the table alone 324) is
   accepted as about one page, against the 500 to 650 aim.
5. The full-name rule (R43, rule 5: full name to kirosli00tuff, one blob in the MBTExperiment LICENSE) was added
   by the lead inline, so no worker saw the literal.
6. The 12 lesson marks were removed by the lead on Kiros's written confirmation (P2_KIROS_CONFIRMED.md, copy in
   reports/p2_scratch/), with no text edits.
7. A scratch pre-build from the working tree before C1, to fix the card ids before committing.
8. The lead ran bulktext and headlines on the first final build, which the C3 brief left out: identical to P.1
   outside solana/.
9. Second self-wipe after D1 and D2 returned (context 166,920 at 11:04).
10. Third self-wipe at 13:05 at about 207k context: planned at 181k at 11:56, it waited for a quiet point, and the
    5-hour usage limit stopped the lead and two Fable workers from about 11:59 to 13:02.
11. The fix review went to a fresh narrow Fable spawn (FixReview), not a SendMessage to D2, so the check of the fix
    was not anchored on D2's own findings.
12. P2-R4 fixed a NOTE (ORB card, "within about two minutes") because the S1 rebuild ran anyway.
13. P2-R22: CROSS_REPO.md and .json stay in the mention class. Excluding them would orphan the program-audit card's
    Result line and its Kiros-confirmed lesson, and the repo stays private in this stage. Offered to Kiros (7.1 C).
14. bulktext and headlines were folded into C3r instead of a separate lead run.
15. Rerun outputs got new names (p2r_, _r2, _r3), and the first-run files were kept.
16. EXCLUDE.txt line 22 keeps P.1's "1,359 paths" comment, untouched.
17. P2-R36: the profile README mirrors Kiros's 10:21 web edit instead of asking Kiros, because the edit is Kiros's
    own recent choice and restoring the lines is a one-line change (7.2).
18. E3 ran before the final commit, as planned, so its llm-news-drift and profile builds come from HEAD 73aa37a.
19. The grep_scan rerun on 4c06138 ran inline by the lead (6 s), not by a worker.
20. E2 took two calls: E2a set only the description after a lead shell error left the topic list empty, and E2b
    set the topics. Both logged.
21. Fourth self-wipe at about 170k context, at the first quiet point after Part E.
22. The SOURCES.txt mark counts are blob occurrences across history from grep_scan.py, not HEAD-only counts.
23. Fifth self-wipe at 164k context, right after resuming (13:20) and before any spawn. A fresh lead starts near
    94k and the STATE file had grown to about 265 lines, so the fifth lead wrote the judgment sections (1, 6 and 7)
    and the briefs first, then wiped at that quiet point.
24. The header and sections 2 to 5 were drafted by ReturnDrafter-OpusXHigh from the record, as in P.1, and the lead
    checked them. This departs from CLAUDE.md's "the lead keeps the final synthesis" for those sections; sections 1,
    6 and 7 are the lead's.
25. ReturnCheck-FableXHigh was added, though the prompt's plan does not list it: an independent recompute of the
    facts only the lead produced (final build 4c06138, the GitHub state, the mark counts, the profile README, the
    dry-run plan) and a check of sections 1 and 7, per CLAUDE.md's rule that every number entering a verdict gets an
    independent Fable check.
26. The cost counter is reports/p1_scratch/cost_tokens.py copied to reports/p2_scratch/ with the 10:20 cutoff and
    the P.2 markers, run by the lead inline (no CostCounter spawn). Six Haiku summarizer calls fall in class
    "other" and are left out, as in P.1. STATE's note that leads 1 and 2 share transcript 6b3df7ac was wrong: lead 1
    is 7c6505c3.
27. docs/STAGES.md: besides the one P.2 RUN line the prompt asks for, the Stage P heading changed from "P.1 RUN,
    nothing public yet" to "P.1 and P.2 RUN; llm-news-drift and the profile public, research-archive private",
    because the old heading stopped being true at about 10:18 (prompt summary).
28. No sixth wipe. The context hook read about 166k at about 13:45 while ReturnDrafter and ReturnCheck were
    running (no quiet point), and about 15 steps were left after they returned (13:32:28 RESUME HERE rule; P.1
    did the same).
29. ReturnCheck's BLOCKING item (the test totals) went to the running ReturnDrafter by message, not by a
    re-spawn. STATE line 219 and tests_report_r2.md line 40 keep the wrong totals as logged; an appended STATE
    line and a note under line 40 carry the correction (P2-R37).
30. The email handle found by the final private scan (P2-R43) was replaced in place, in the lead's files and in
    two Fable reports (D1r and ReturnCheck), with the neutral label "the email handle", like "the portfolio
    repo". Only the term name changed; every count stays as the reviewers wrote it.

## 7. Decisions for the user

Each item gives the lead's recommendation first.

### 7.1 The one remaining mark (go_public.sh stops on it)

`grep -rn '\[KIROS: confirm\]' publish/` finds one mark, publish/research-archive/SOURCES.txt:27. Lines 27 to 34,
verbatim:

```
# [KIROS: confirm] 10 of the 12 kept sources still name three of those six repos, or the word solana, in their
# own files. Occurrences across all blobs of the 4c06138 build: program-audit 4,989 (170 of them in
# findings/agentA/CROSS_REPO.md and .json), ORBExperiment 694, NPLExperiment 488, MLCryptoEngine 191,
# ETFExperiment 87, retail-power-limits 50, VRPExperiment 23, PMExperiment 18, MBTExperiment 10, InsiderExperiment 5.
# 14 commit messages name them, and so does EXCLUDE.txt line 52 at the archive root, the rule that drops
# program-audit's audit files on two of them. No path names them. Details in AiTrader reports/P.2_RETURN.md
# section 7. Delete these eight lines to publish the archive as built, or pick another option given there.
# go_public.sh refuses while this mark remains.
```

What it covers is the mention class (reports/p2_rulings.md, class ruling). On the 4c06138 build
(reports/p2_scratch/scans/p2r3_grep_scan.md) the 12 kept sources name solattn, solclear or solcopy, or say solana,
6,557 times across all blobs: solattn 3,495 in 134 files, solclear 2,760 in 92, solana 282 in 24 and solcopy 20 in
8 (distinct paths, one path per blob). Fourteen commit messages name them, and so does EXCLUDE.txt line 52 at the archive root. No path does. Kept
program-audit files also quote full commit ids of the two solana repos, as pointers. The material dedicated to the
solana repos (46 files with 9 on-chain identifiers) is already out (P2-R1, P2-R27).

- A (recommended): accept the class as built. Delete lines 27 to 34 of SOURCES.txt and commit. The archive goes
  public as 4c06138. Reason: V10 drops the six sources, not every mention of them. What remains is names and
  pointers in the kept projects' own logs and audits, not solana research, and rewriting those records would make
  the archive disagree with the originals it preserves.
- B: replacement rules. Kiros asks for replace-text rules that turn the names into neutral labels across the 12
  sources. A later stage then rebuilds, rescans and reviews. Every affected commit id changes, and ids such as
  AUDIT-A-solclear-11 read oddly afterwards. If "No solana" means no mention anywhere, pick B.
- C: also exclude findings/agentA/CROSS_REPO.md and .json (P2-R22, 170 of the 6,557). The program-audit card's
  Result line and its confirmed lesson rest on that file, so the card needs an edit too. C goes with A or B, not
  instead of them.
- D: keep the archive private for now. go_public.sh then stops for every repo, so the llm-news-drift fast-forward
  and the profile's archive link wait too.

### 7.2 Profile README: edit it in publish/, not on github.com (P2-R16, P2-R36)

Recommendation: make profile changes in publish/profile/README.md and let go_public.sh push them. The next append
builds the README from publish/, so it puts back anything a web edit removed. Kiros's 10:21 web edit (b72c122)
deleted "# Kiros" and the two intro lines. The lead mirrored that in publish/profile/README.md (P2-R36), so the
append adds only the archive link. To bring the lines back, restore them in publish/profile/README.md before
go-live.

### 7.3 Personal email address in a public commit

Recommendation: turn on GitHub Settings > Emails > "Keep my email addresses private" (and "Block command line
pushes that expose my email"). b72c122, the web edit, carries the personal Gmail address in its author field in the
public kirosli00tuff repo, because GitHub web edits use the primary address unless that setting is on. This is
pre-existing and outside the stage (no public push, no history rewrite), and the append keeps b72c122 as its parent.
Rewriting that public history is possible but not recommended: the commit has been public since 10:21.

### 7.4 go_public.sh hardening (P2-R30, P2-R31, P2-R32, P2-R34)

Recommendation: run go-live from a shell with no GIT_* variable exported, and leave the reviewed script as it is.
A later stage can clear the GIT_CONFIG_* channel and GIT_TEMPLATE_DIR, add GIT_DEFAULT_HASH and
GIT_DEFAULT_REF_FORMAT to the unset list, and set the author and committer dates in plan_append. None of these is a
regression: 73aa37a and cfcd878 have the same exposure.

### 7.5 Go-live command for the planner

After 7.1 is resolved and committed (the dry run stops while publish/ has uncommitted changes or HEAD holds a mark):

1. Open a new tmux pane, for example `tmux new-session -s golive`. Run `env | grep '^GIT_'`; if it prints a name,
   `unset` it first.
2. `cd ~/Documents/GitHub/AiTrader`
3. `TMPDIR=/home/kiros-li/.cache/p2-tmp publish/go_public.sh --dry-run`, then check the plan: llm-news-drift
   (PUBLIC) a fast-forward; research-archive (PRIVATE) nothing to push, GitHub's main already 4c06138, and
   "make public: research-archive"; kirosli00tuff (PUBLIC) one appended commit, README.md | 4 ++-- (the archive
   link, P2-R36); bio unchanged; no would-stop line. The llm-news-drift target will be newer than 3367d9b: the final
   P.2 commit touches docs/STAGES.md and docs/prompts/README.md, both on publish/llm-news-drift/ALLOWLIST.txt, so
   the extraction gains at least that commit. It must still be a fast-forward from 3fb1324.
4. `TMPDIR=/home/kiros-li/.cache/p2-tmp publish/go_public.sh`, and at the prompt `Type "go public" to continue:`
   type `go public` (go_public.sh lines 399 to 401; any other answer stops with nothing changed).

### 7.6 What the next session must do first

- The planner pushes AiTrader: C1 73aa37a and the final commit "Stage P.2 research-archive (no solana), private".
  AiTrader is public, so the push publishes reports/P.2_* and reports/p2_*. The private-literal scan of the staged
  files is in section 2.5.
- Resolve 7.1, then go live per 7.5. Nothing else blocks it.
- build_archive.sh reads publish/research-archive from the working tree, so 4c06138 was built from edits that only
  the final P.2 commit puts into HEAD; after that commit the two agree (ReturnCheck NOTE 4). Deleting the mark
  lines (7.1 A) leaves the build unchanged: the script skips comment lines of SOURCES.txt (lines 189 to 196), and
  the E3 dry run rebuilt 4c06138 after the mark text had changed.
- COLLECTION_LOG.md is on the llm-news-drift allowlist and holds uncommitted collector appends. Stage commits never
  include it (prompt line 191), so the public copy shows it as of the last commit that did.
- No frozen file changed, and no experiment work waits on this stage.

## 8. Session cost

Wall clock: 2026-11-07 10:24:28 to 13:55:39 MST (the end checks), 3 h 31 min; the final commit follows within
minutes and carries its own time in git. Pause, shown apart: the 5-hour usage limit from about 11:59 to 13:02
(about 63 min; STATE lines 221 and 222, and the resume message at 13:01 in lead 3's transcript), which stopped lead 3, FixReview and D1r's final reply. Active time
about 2 h 28 min. Five planned self-wipes took 2 to 3 minutes each (section 4, lead contexts).

Estimate against actual: the first ETA table (STATE line 16, written about 10:45) put the final commit at about
14:40 G. Revised return ETAs: about 13:00 (STATE line 98), 12:50 (line 149) and 13:40 (line 217). The fifth lead's
chat table said 14:25 G and its RESUME HERE about 14:30 (line 317). The sixth lead's chat table at 13:35 said
14:38. Actual: end checks 13:55:39, final commit right after. The stage missed the prompt's 13:00 aim by about an
hour, about the length of the usage-limit pause.

Final ETA table: one row per lead context and per spawn, start and end from each transcript's first and last entry
(MST), tokens summed from the transcripts by reports/p2_scratch/cost_tokens.py (each assistant message counted
once), rerun at 13:55:52, and laid out by reports/p2_scratch/cost_tables.py. Status and deviations per spawn are in
section 4. Rows are transcripts: FixReview, resumed by message after the pause, and ReturnDrafter, which took a lead
message while running, keep one row each. Rows 10 and 12 (lead 3 and FixReview) span the pause.

| # | Spawn or lead context | Session | Model | Start | End | Minutes | Input | Output | Cache read | Cache creation |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | lead 1 7c6505c3 | 7c6505c3 | opus-5-5 | 10:24 | 10:55 | 31.0 | 156 | 112,499 | 14,476,032 | 256,345 |
| 2 | ScriptCoder-OpusXHigh (B) | 7c6505c3 | opus-5-5 | 10:30 | 10:54 | 23.8 | 64 | 138,255 | 5,538,050 | 247,944 |
| 3 | ArchiveText-OpusHigh (A2) | 7c6505c3 | opus-5-5 | 10:33 | 10:38 | 4.8 | 70 | 33,372 | 3,740,619 | 126,656 |
| 4 | lead 2 6b3df7ac | 6b3df7ac | opus-5-5 | 10:57 | 11:33 | 36.7 | 128 | 66,750 | 8,568,870 | 176,320 |
| 5 | ScanRunner-SonnetHigh (C3) | 6b3df7ac | sonnet-5-5 | 11:00 | 11:02 | 2.0 | 24 | 11,136 | 977,700 | 106,055 |
| 6 | TestRunner-SonnetHigh (C4) | 6b3df7ac | sonnet-5-5 | 11:00 | 11:03 | 3.0 | 22 | 8,903 | 879,172 | 78,790 |
| 7 | ArchiveReviewer-FableXHigh (D1) | 6b3df7ac | fable-5-1 | 11:00 | 11:21 | 21.1 | 2,478 | 99,469 | 13,253,647 | 267,554 |
| 8 | ScriptReviewer-FableXHigh (D2) | 6b3df7ac | fable-5-1 | 11:00 | 11:17 | 16.9 | 550 | 72,398 | 2,469,163 | 190,999 |
| 9 | ScriptFix-OpusXHigh | 6b3df7ac | opus-5-5 | 11:18 | 11:33 | 14.7 | 82 | 76,873 | 6,287,434 | 212,011 |
| 10 | lead 3 a6eca48f | a6eca48f | opus-5-5 | 11:35 | 13:05 | 89.7 | 112 | 100,428 | 8,139,266 | 374,136 |
| 11 | ExcludeS1-OpusHigh | a6eca48f | opus-5-5 | 11:40 | 11:48 | 7.9 | 110 | 33,751 | 6,209,485 | 150,881 |
| 12 | FixReview-FableXHigh | a6eca48f | fable-5-1 | 11:40 | 13:05 | 84.4 | 490 | 59,797 | 2,234,895 | 530,672 |
| 13 | ScanRunner-SonnetHigh (C3r) | a6eca48f | sonnet-5-5 | 11:50 | 11:54 | 3.2 | 32 | 17,236 | 1,430,495 | 119,385 |
| 14 | TestRunner-SonnetHigh (C4r) | a6eca48f | sonnet-5-5 | 11:50 | 11:54 | 3.3 | 26 | 8,654 | 1,065,965 | 82,639 |
| 15 | ArchiveRecheck-FableXHigh (D1r) | a6eca48f | fable-5-1 | 11:51 | 12:00 | 9.9 | 1,034 | 44,768 | 3,775,631 | 146,579 |
| 16 | lead 4 c6e57c48 | c6e57c48 | opus-5-5 | 13:07 | 13:18 | 10.5 | 140 | 52,633 | 9,398,099 | 149,290 |
| 17 | lead 5 09500226 | 09500226 | opus-5-5 | 13:19 | 13:32 | 12.7 | 68 | 79,878 | 4,980,590 | 191,132 |
| 18 | lead 6 bfca6777 | bfca6777 | opus-5-5 | 13:34 | 13:55 | 21.2 | 142 | 90,119 | 11,175,040 | 203,717 |
| 19 | ReturnDrafter-OpusXHigh | bfca6777 | opus-5-5 | 13:36 | 13:52 | 16.5 | 132 | 101,592 | 13,397,617 | 341,175 |
| 20 | ReturnCheck-FableXHigh | bfca6777 | fable-5-1 | 13:36 | 13:48 | 12.8 | 1,093 | 57,589 | 4,069,507 | 180,727 |

| Share | Input | Output | Cache read | Cache creation | Total | Percent of total |
|---|---|---|---|---|---|---|
| lead (6 files) | 746 | 502,307 | 56,737,897 | 1,350,940 | 58,591,890 | 46.0 |
| worker (14 files) | 6,207 | 763,793 | 65,329,380 | 2,782,067 | 68,881,447 | 54.0 |
| all | 6,953 | 1,266,100 | 122,067,277 | 4,133,007 | 127,473,337 | 100.0 |

Claude Code's own summarizer calls (class other, not spawned by the lead, not in the totals above):

| file | model | Start | Input | Output | Cache read | Cache creation |
|---|---|---|---|---|---|---|
| 031ce7fb | haiku-5-5 | 11:06 | 2 | 2,036 | 11,382 | 63,312 |
| ec1dc96e | haiku-5-5 | 11:19 | 2 | 2,271 | 13,932 | 61,989 |
| ea9d5695 | haiku-5-5 | 11:22 | 2 | 3,611 | 13,932 | 62,553 |
| cd685228 | haiku-5-5 | 11:43 | 2 | 2,126 | 13,932 | 60,994 |
| cb259cd9 | haiku-5-5 | 11:53 | 2 | 2,906 | 13,932 | 62,530 |
| 2a20c5df | haiku-5-5 | 13:18 | 2 | 2,825 | 11,382 | 63,846 |
| de5e33fe | haiku-5-5 | 13:42 | 2 | 2,920 | 13,932 | 60,875 |

Per model, P.2 lead contexts plus their subagents (deduped assistant messages; class other not included):

| model | messages | input | output | cache_read | cache_creation |
|---|---|---|---|---|---|
| claude-opus-5-5 | 586 | 1,204 | 886,150 | 91,911,102 | 2,429,607 |
| <synthetic> | 3 | 0 | 0 | 0 | 0 |
| claude-fable-5-1 | 182 | 5,645 | 334,021 | 25,802,843 | 1,316,531 |
| claude-sonnet-5-5 | 52 | 104 | 45,929 | 4,353,332 | 386,869 |
| ALL | 823 | 6,953 | 1,266,100 | 122,067,277 | 4,133,007 |

Deviation: the last lead context (bfca6777) passed the 150k self-wipe mark (the context hook read about 166k at
about 13:45) and did not wipe, because two workers were running and about 15 steps were left after they returned
(open choice 28). Its steps after the 13:55:52 rerun are not in the table. Every count here is measured from the
transcripts, none is estimated.


STAGE P.2 "RESEARCH-ARCHIVE TO GITHUB (NO SOLANA)"

BEGIN PROMPT - SUMMARY OF PROMPT

Summary: Kiros, 2026-11-07 10:22: "Put up research-archive. No solana." Stage P.1 built research-archive
locally (18 sources, d358b35a at /home/kiros-li/.cache/p1-tmp/ArchiveRules/real1) and left items open
(reports/P.1_RETURN.md section 3.11). llm-news-drift and the profile repo went public at about 10:18 (commit
84586ac). This stage:
- drops the six solana sources from the archive
- fixes the open items that remain
- rebuilds, rescans and gets an independent Fable review
- creates research-archive on GitHub as PRIVATE and pushes it
- fixes publish/go_public.sh so it updates a repo that is already public with an appended commit, never a rebuild
- points the profile README at the archive

It makes nothing public and pushes nothing to a public repo. The planner runs go_public.sh afterwards, once Kiros
has confirmed the card lessons. It reads no experiment outcome, touches no collector file and spends nothing.

Decisions in force: docs/DECISIONS.md V1 to V10. V10 holds this stage's decisions.

Binding, in priority order: CLAUDE.md invariants, docs/DECISIONS.md V7 and V10, docs/prompts/STAGE_P.1.md Part D
(the archive rules, the scans and EXCLUDE.txt), then this prompt.

Read first:
- reports/P.1_RETURN.md sections 1, 3.11 and 7.1 to 7.4, by search
- reports/p1_rulings.md: R34 to R43 and R49, by search
- publish/research-archive/ (SOURCES.txt, README.md, the 12 experiments cards, build_archive.sh by its header)
- publish/go_public.sh in full
- publish/profile/README.md
- docs/prompts/STAGE_P.1.md Part D and Part H, by search

Lead: Opus 5.5, effort max. Ultracode: off.
- Reviewers: Fable xhigh, with the model confirmed from each transcript. Opus max in a fresh context only if Fable
  is unavailable, and the return says so.
- Routing (V9): Sonnet high for counts, scans that are only run, test runs and formatting. Opus high for card and
  README text. Opus xhigh for go_public.sh.
- At most 4 workers at once, and at most 1 heavy job. Worker briefs give exact paths. Workers return a path and at
  most 200 words.

Why this lead and effort: a public, permanent repo with 12 histories, and a script that pushes to public repos.
The silent failures are a solana file left in the history, a leaked literal, a card claim the source does not
support, and a go_public.sh that force-pushes over a public repo.

Usage and time: launched 2026-11-07 about 10:35, a Saturday with no collector run. No fixed end, but aim for the
return by 13:00. Checkpoint to reports/P.2_STATE.md after every step.
- Self-wipe at about 150k tokens of lead context, at a quiet point: write RESUME HERE (at most 60 lines), append
  "READY FOR WIPE <time>", keep the final message under 10 lines, then run this one command and end the turn:
  setsid nohup bash -c 'sleep 120; tmux send-keys -t stage-p2 "/clear"; sleep 1; tmux send-keys -t stage-p2 Enter; sleep 8; tmux send-keys -t stage-p2 "Read the newest RESUME HERE section of reports/P.2_STATE.md and every STATE line after it, then the parts of docs/prompts/STAGE_P.2.md it points to, and continue Stage P.2 as a fresh lead after a planned self-wipe. First append a line Lead self-wipe done to the STATE file with the time. Re-spawn any unfinished worker from its brief. Do not redo finished work. Run unattended."; sleep 1; tmux send-keys -t stage-p2 Enter' >/dev/null 2>&1 &
- Deleting files: never use rm or rmdir with a glob, a relative path or an unguarded variable. A permission prompt
  has no one to answer it. Use literal absolute paths, "${VAR:?}", find <abs dir> -mindepth 1 -delete, or a fresh
  mktemp -d under /home/kiros-li/.cache/p2-tmp (the /tmp tmpfs has a quota).

Do not stop to ask, and do not use AskUserQuestion. Decide, log the choice under Open choices in the return
document, and continue.

============================================================
PART 0: START GATES (FIXED HERE)
============================================================

0.1 Quoted verbatim in the return: `git status --short`, `git log --oneline -3` (must show 84586ac or later),
`free -m`, `df -h /home /tmp`, and `gh auth status` after
`export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`.
Run `gh repo view kirosli00tuff/research-archive`. It must fail (no repo yet). If it succeeds, stop.
0.2 Confirm that ~/.config/p1-private/research-archive.replace-text exists. Never print its literals.
0.3 Write reports/P.2_STATE.md with the ETA table.

============================================================
PART A: DROP SOLANA AND FIX THE OPEN ITEMS (FIXED HERE)
============================================================

A1. Owner: the lead. Remove the six solana rows from SOURCES.txt and remove publish/research-archive/cards/solana/
with git rm. Remove every solana mention from the archive README: the group, the table rows, the solana mark on
line 33, and counts (18 becomes 12, and the commit total is recounted from the build). Grep publish/research-archive
and publish/profile for solattn, solback, solceil, solclear, solcopy, soltool and "solana", and leave zero hits.
The original repos stay private and untouched.

A2. Owner: ArchiveText-OpusHigh (opus, high). Apply the P.1 open items that still apply:
- R36: the ORBExperiment card says task6_delisted.json is excluded, and why.
- F3-S1: the MLCryptoEngine card cites no pre-rewrite commit id. Use the archive ids or none.
- F3-S2: the MBTExperiment card says 206 seconds.
- F3-S3: README line 85 and the Tests section agree.
- F3-S4: the README Tests rows match the new build.
- F3-S6: the README line on where llm-news-drift names these repos is accurate, or cut.
- F3-N4: each card's commit count says what it counts.
- F3-N7: the README removal classes include bulk vendor reference data.
- F2-N7: one README line says .env.example files are not in the archive, so the setup steps that copy them do
  not run as written.
- F2-N8: trim the README to about one page, keeping the table, the honest-results line, the AI line, the layout
  and the exclusions.
- The licence line stays "I have not chosen a licence yet. Until I do, the default applies: all rights reserved."
  Its mark is removed (V10).
- R43: the full legal name in the LICENSE files is replaced by the handle kirosli00tuff, by adding a rule to the
  private replace-text file (V10). If the name sits only in solana sources, record that and add no rule.
- Leave the 12 "One thing learned" marks in place, unless the planner note in A4 says Kiros confirmed them.
Every changed sentence is traced to a file or commit in the source repo, or to the build.

A3. Owner: the lead. Update publish/profile/README.md: the archive line becomes a link to
https://github.com/kirosli00tuff/research-archive, with the source count of 12 and no "coming soon".

A4. Kiros's confirmation. If /home/kiros-li/planner-drafts/P2_KIROS_CONFIRMED.md exists when Part A ends, follow it
for the 12 lesson marks: remove the marks it confirms, and apply any edits it gives. Otherwise leave them, and the
return lists each one.

============================================================
PART B: GO_PUBLIC.SH FOR PUBLIC REPOS (FIXED HERE)
============================================================

Owner: ScriptCoder-OpusXHigh (opus, xhigh). Change publish/go_public.sh so that:
- For a repo that GitHub reports as PUBLIC, step 3 and step 4 never rebuild history and never force-push. They
  clone the remote main into a fresh mktemp -d, replace its tracked tree with the new build's tree, show a
  `git diff --stat`, commit with message "update from AiTrader <short sha>" and the Co-Authored-By line, and
  push as a fast-forward. No diff means no commit.
- For a PRIVATE repo, today's behaviour stays: rebuild, then force-push if needed.
- llm-news-drift keeps its extraction, and its push must stay a fast-forward. Today's guard stays.
- Step 1's archive exclusion ends once the repo exists. It already does, so keep it.
- A new flag, --dry-run, runs every step up to the push and prints what it would push, change or flip, and
  changes nothing on GitHub.
Test it against local bare repos in a mktemp -d, standing in for public and private remotes, with a stub for
`gh repo view` visibility. Never test against GitHub.

============================================================
PART C: BUILD AND VERIFY (FIXED HERE)
============================================================

C1. Commit publish/ and this stage's files so far: "Stage P.2 archive sources (no solana)". This is the first of
two commits. The build reads committed history.
C2. Run build_archive.sh twice into two fresh directories under /home/kiros-li/.cache/p2-tmp and confirm identical
hashes. Then build into ~/Documents/GitHub/research-archive, with --force only if that folder holds an earlier
build. Record HEAD, the commit count, the size and the largest blob.
C3. Owner: ScanRunner-SonnetHigh (sonnet, high). On the final build's full history:
- gitleaks
- the P.1 scan_history.py secrets and paths scans (D6)
- a grep of every blob, message and path for the six solana names, "solana", every literal in the private
  replace-text file, kiros1134, and the two withheld personal repo names
Expect zero, or a written ruling for each hit.
C4. Owner: TestRunner-SonnetHigh (sonnet, high). The fresh-clone tests for the 12 sources, as P.1 ran them.
Record the counts per source.

============================================================
PART D: REVIEW (FIXED HERE)
============================================================

Two reviewers run in parallel. Each has its model confirmed from its transcript.

D1. ArchiveReviewer-FableXHigh (fable, xhigh). The final build's full history, and the README and cards. Check:
- no solana trace
- no secret, keypair, account ID, personal contact or vendor bulk data
- every card and README claim traced
- the A2 items done
Output: reports/p2_review_archive.md, with each finding marked BLOCKING, SHOULD FIX or NOTE.

D2. ScriptReviewer-FableXHigh (fable, xhigh). The go_public.sh diff and its tests. Hunt for any path that
force-pushes or rewrites a public repo, makes a repo public by mistake, or pushes without the mark check. Output:
reports/p2_review_script.md.

The lead rules on every finding in reports/p2_rulings.md. BLOCKING and SHOULD FIX findings are fixed, and the
affected checks rerun.

============================================================
PART E: GITHUB, PRIVATE ONLY (FIXED HERE)
============================================================

E1. `gh repo create kirosli00tuff/research-archive --private --source ~/Documents/GitHub/research-archive --push`.
E2. Set the description and topics from publish/profile/metadata.json. Add an archive entry there if it is
missing.
E3. Run `publish/go_public.sh --dry-run` and quote its output. It must show:
- llm-news-drift: a fast-forward or nothing
- kirosli00tuff: an appended commit (the archive link)
- research-archive: private, to be made public
Never run go_public.sh without --dry-run.
E4. Record `gh repo list kirosli00tuff --limit 100 --json name,visibility` before and after.

============================================================
SCOPE
============================================================

This stage does NOT:
- make any repo public, push to any public repo, change any other repo's visibility, or set the bio
- include any solana source, or write inside any source repo
- touch the collector, EXPERIMENT.md, news_eval/, news_experiment/, reports/c2* or any frozen file
- rewrite AiTrader history. The solana cards in commit bb09341 stay in AiTrader's history.
- print a replace-text literal, or push AiTrader. The planner pushes.

============================================================
GUARDRAILS
============================================================

- Start and end checks quoted verbatim.
- Commits stage explicit paths only: publish/, reports/P.2_*, reports/p2_*, PROGRESS.md, RETURN.md, docs/STAGES.md
  and docs/prompts/README.md. Never COLLECTION_LOG.md. There are two commits: C1 and the final one, "Stage P.2
  research-archive (no solana), private".
- Every gh call that changes something is logged to STATE with its output before the next one runs.
- Before ending, confirm no worker or shell is still running.

============================================================
DELEGATION PLAN
============================================================

| Step | Owner | Model | Effort | Parallel or serial | Why this tier |
|---|---|---|---|---|---|
| 0, A1, A3, A4, C1, C2, rulings, E, return | lead | opus | max | serial | public repo and gh calls stay with the lead |
| A2 | ArchiveText-OpusHigh | opus | high | parallel with B | traced text edits |
| B | ScriptCoder-OpusXHigh | opus | xhigh | parallel with A2 | a script that pushes to public repos |
| C3 | ScanRunner-SonnetHigh | sonnet | high | after C2 | runs fixed scans |
| C4 | TestRunner-SonnetHigh | sonnet | high | after C2, parallel with C3 | runs suites, lists failures |
| D1 | ArchiveReviewer-FableXHigh | fable | xhigh | parallel with D2 | independent history and claims check |
| D2 | ScriptReviewer-FableXHigh | fable | xhigh | parallel with D1 | independent push-safety check |

    DELEGATION PLAN (the lead executes this; it does not do worker tasks)
    1. Decompose each part into subtasks with one objective, inputs, output path and format, allowed tools,
       and boundaries.
    2. Route per CLAUDE.md and V9. State model and effort for each subtask before spawning; confirm each
       reviewer's model from its transcript.
    3. Run independent workers at once, at most 4.
    4. Collect results as files plus short summaries.
    5. Verify with the independent reviewers as listed.
    6. Synthesize in the lead against this prompt, and write the synthesis to disk before ending.
    7. Unattended run: no pauses to ask. Checkpoint to reports/P.2_STATE.md after each step.

============================================================
DELIVERABLE
============================================================

Write reports/P.2_RETURN.md, one PROGRESS.md and RETURN.md entry, one docs/STAGES.md line under Stage P, and the
P.2 row's Run column in docs/prompts/README.md. Then make the final commit. No push. Sections:
1. Summary, at most 200 words.
2. Guardrail evidence.
3. Results: the source table (12), removals, the open items closed, determinism, scans, tests, the go_public.sh
   change, and the --dry-run output.
4. Delegation record.
5. Verification.
6. Open choices.
7. Decisions for the user: every remaining mark with its file and line and text, then the exact go-live command
   for the planner (go_public.sh, run in a tmux pane, with the typed "go public").
8. Session cost, never estimated.

The last thing before ending: list every open choice in section 6.

END PROMPT

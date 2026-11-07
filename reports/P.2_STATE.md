# Stage P.2 STATE (research-archive to GitHub, no solana)

Lead: Opus 5.5 (claude-opus-5-5), effort max. Prompt: docs/prompts/STAGE_P.2.md. Scratch: reports/p2_scratch/
(untracked, like reports/p1_scratch/), temp builds under /home/kiros-li/.cache/p2-tmp.

## Log (times from `date`, MST, UTC-7)

- 10:24:28 Session start. Start checks in /home/kiros-li/.cache/p2-tmp/start_gates.txt and start_gates_gh.txt
  (copied verbatim into the return). Timer active. Collection counts 69|35548|13381. HEAD e5c1810 (after 84586ac).
  free 8282 MB available. gh logged in as kirosli00tuff, scopes include repo and user.
- 10:24:40 0.1 `gh repo view kirosli00tuff/research-archive` fails ("Could not resolve to a Repository"), exit 1. Gate passes.
- 10:24:40 0.2 ~/.config/p1-private/research-archive.replace-text exists (4 lines). Literals not printed.
- 10:24:40 tmux session stage-p2 present (self-wipe target).
- A4 check at start: /home/kiros-li/planner-drafts/P2_KIROS_CONFIRMED.md does not exist. Recheck when Part A ends.

## ETA table (written about 10:45, before the first spawn). Rows marked G are guesses.

| Step | Owner | Model | Effort | Parallel or serial | ETA | Cumulative (from 10:35) |
|---|---|---|---|---|---|---|
| 0 gates, STATE | lead | opus | max | serial | 10:24 to 10:45 | 0:10 |
| B go_public.sh + tests | ScriptCoder-OpusXHigh | opus | xhigh | parallel with A1, A2 | 75 min (G) | ends ~12:00 |
| A1 drop solana | lead | opus | max | serial, parallel with B | 20 min (G) | 0:30 |
| A2 open items | ArchiveText-OpusHigh | opus | high | parallel with B | 45 min (G) | ends ~11:50 |
| A3, A4 profile, Kiros note | lead | opus | max | serial | 10 min (G) | 1:25 |
| C1 commit | lead | opus | max | serial, after A2 and B | 5 min | 1:30 (~12:05) |
| planned self-wipe after C1 | lead | | | quiet point, no worker running | 5 min | 1:35 |
| C2 three builds | lead (scripted, nice 10, one heavy job) | opus | max | serial | 30 min (G) | 2:05 |
| D2 script review | ScriptReviewer-FableXHigh | fable | xhigh | parallel with C2 to C4 | 40 min (G) | 12:10 to 12:50 |
| C3 scans | ScanRunner-SonnetHigh | sonnet | high | after C2, parallel with C4 | 30 min (G) | 2:35 |
| C4 fresh-clone tests | TestRunner-SonnetHigh | sonnet | high | after C2, parallel with C3 | 40 min (G) | 2:45 |
| D1 archive review | ArchiveReviewer-FableXHigh | fable | xhigh | after C2 (needs the final build) | 45 min (G) | 2:50 |
| rulings, fixes, reruns | lead + fix workers | opus | max/high | serial | 30 min (G) | 3:20 |
| E1 to E4 GitHub private | lead | opus | max | serial | 20 min (G) | 3:40 |
| return, end checks, final commit | lead | opus | max | serial | 25 min (G) | 4:05 (~14:40) |

The cumulative ETA misses the 13:00 aim by about 1.5 hours. The guesses are the build times and the review lengths.
- 10:30:19 B spawned: ScriptCoder-OpusXHigh (opus, xhigh), brief reports/p2_scratch/briefs/B_ScriptCoder.md, output reports/p2_scratch/go_public_test.md. Running.
- 10:32:02 A1 done (lead): 6 solana rows out of SOURCES.txt, cards/solana/ removed with git rm (6 cards), README solana rows, line-33 mark, layout, keypair wording, soltool removal bullet and 6 Tests rows removed; AI counts recounted for 12 (reports/p2_scratch/ai_counts_p1build.txt: 122 trailer commits, Opus 5 39, Fable 5.1 82, Fable 5 1, CLAUDE.md in 8 of 12); EXCLUDE.txt solana wording, soltool html exception and R37 solclear line removed; build_archive.sh group check now experiments only; metadata.json 12 and no solana topic. grep of publish/research-archive and publish/profile for the six names and solana: 0.
- 10:34:28 R43 (lead, A2 item done inline so no worker sees the literal): the full name sits in exactly 1 blob across the 12 sources (MBTExperiment LICENSE, exact case, 0 in messages and identities, 0 case variants). Added rule 5 '<name>==>kirosli00tuff' to ~/.config/p1-private/research-archive.replace-text (backup .bak-p2-* beside it, mode 600). Literal never printed. A2 spawned earlier: ArchiveText-OpusHigh (opus, high), brief reports/p2_scratch/briefs/A2_ArchiveText.md.
- 10:34:35 A3 done (lead): publish/profile/README.md archive line is now a link to https://github.com/kirosli00tuff/research-archive with 12 projects and no 'coming soon'.
- 10:34:55 A4: /home/kiros-li/planner-drafts/P2_KIROS_CONFIRMED.md found at 10:36 (mtime 10:27:11, absent at the 10:25 listing). Kiros, 10:27 America/Vancouver: "Agreed with everything." (12 lesson lines shown verbatim; defaults: licence all rights reserved, full legal name replaced by kirosli00tuff, solana cards stay in AiTrader history). Instruction: remove all 12 lesson marks, no text edits. Copy at reports/p2_scratch/P2_KIROS_CONFIRMED.copy.md. Lead removes the marks after A2 ends (A2 is editing the cards). 10:37 SendMessage to A2: do not change the text of the 12 lesson sections.
- 10:37:32 FINDING (lead, on the P.1 build d358b35a, HEAD tree): the 12 kept sources name the six left-out repos or
  the word solana in their own files: 10 sources, about 4,643 lines (program-audit findings/agentA, B, C about 4,000;
  others in progress.md, REGISTRATION.md, DECISIONS.md, retail-power-limits rplimits/cases.py and sources.py, ORB
  tests/test_guards.py, MLCryptoEngine config/venues.yaml), 20 commit messages, 68 paths in history. A zero-hit C3 grep
  is impossible as built. Lead choice (Open choice 1): no rewrite of other projects' records (V10 removes the six
  sources, not mentions), class rulings in reports/p2_rulings.md, and one new confirm mark in
  publish/research-archive/SOURCES.txt (not copied into the archive) so go_public.sh refuses until Kiros accepts or
  asks for replacement rules. The repo stays private in this stage either way.
- 10:38:41 A2 returned (ArchiveText-OpusHigh, 290 s, 145,836 tokens): report reports/p2_scratch/archive_text_report.md. Items 1-9, 11, 12 applied; README 1,228 -> 842 words (table alone 324); 12 marks left, all in cards; lesson text untouched. Open: length over the 500-650 aim; name-to-handle line traceable only once the build shows rule 5.
- 10:38:41 A4 done (lead): removed the 12 lesson marks ('## One thing learned `[KIROS: confirm]`' -> '## One thing learned'), no text edits, per P2_KIROS_CONFIRMED.md. Marks left under publish/: see next line.
- 10:39:04 Open choice 1 applied: one confirm mark (4 comment lines) added to publish/research-archive/SOURCES.txt after the V10 line. SOURCES.txt is not copied into the archive. Solana-term grep of publish/research-archive and publish/profile still 0.
- 10:39:49 Briefs written for C3, C4, D1, D2 (reports/p2_scratch/briefs/). Waiting on B.
- 10:40:46 Lead scratch pre-build (working-tree config, before C1): /home/kiros-li/.cache/p2-tmp/pre.N4Y3wk, exit 0, 18 s, 421 commits (407 imported + 12 merges + root + cards, as predicted), HEAD 2bc0033 (scratch). Source tips vs P.1 d358b35a: 11 same, MBTExperiment different (rule 5: 1 blob before filtering, 0 after, report line 108). Whole-archive literal scan rules 1-5: 0 blobs, 0 messages, 0 identities. So the card ids from d358b35a hold for 11 sources.
- 10:54:25 B returned (ScriptCoder-OpusXHigh, 1,427 s, 249,139 tokens): report reports/p2_scratch/go_public_test.md. 220/220 harness checks against local bare repos and a stub gh, bash -n and shellcheck 0.11.0 clean, 18 of 19 mutants caught (M17 unreachable). Plan-then-ask-once-then-push order. Notes: kept llm-news-drift on extraction + fast-forward only (brief item 4; Open choice 2); confirm prompt after builds; dry run exits 1 until publish/ committed; harness 906 lines.

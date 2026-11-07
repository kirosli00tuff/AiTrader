# Stage prompts

Every prompt that drives a Claude Code stage session, exactly as sent, so
any session's instructions can be audited against its return document.
From 2026-09-23 on, each new prompt is committed here before it is sent.
Earlier AiTrader prompts were not archived. RETURN.md holds their
summaries.

File name: `STAGE_<X.Y>.md`, for example `STAGE_C.1.md`. A revised prompt
that never ran keeps the name with `_draft` and stays in the index.

| Stage | File | Lead as written | Run | Return document | Notes |
|---|---|---|---|---|---|
| B.1 | none | planning chat | 2026-09-23 | this commit | Workflow port through Desktop Commander, no CLI session |
| C.1 | STAGE_C.1.md | Opus 5.5, xhigh (Fable xhigh verification and second grader, Fable max leakage review) | 2026-10-10 22:58 to 2026-10-11 ~03:50 PDT, Claude Code lead Opus 5.5 xhigh, 13 spawns; commits 2b75aba (freeze), 33cadb3 (relevance grades) and the return commit | reports/C.1_RETURN.md | Evaluation harness news_eval/ built on synthetic rows and frozen per Amendment 9, 8.3 relevance sample drawn and graded; no outcome read |
| C.2 | STAGE_C.2.md | Opus 5.5, max (Fable xhigh gate and verdict verification, Fable max verdict review) | attempt 1: 2026-10-28 from 17:20 PDT, Claude Code lead Opus 5.5 max, 1 spawn (GateVerifier, Fable xhigh); commits a1eabc2 (snapshot and gate) and the return commit; rerun on or after 2026-11-04 at 65 judged collection days | reports/C.2_RETURN.md | Snapshot, 9.8 gate, the single verdict run against manifest 77c9bd73, independent recomputation. Attempt 1: gate FAIL on power (M 5,363 < Required 13,335), no verdict run, judgments unread |
| C.3 | STAGE_C.3.md | Opus 5.5, max (Fable xhigh diff review and run-once audit) | 2026-11-05 21:37 to 2026-11-06 MST, Claude Code lead Opus 5.5 max in three sessions after two self-wipes, 5 spawns (HarnessCoder and TestCoder, Opus xhigh; DiffReviewer, RunOnceAuditor and FixChecker, Fable xhigh); manifest 19dc1da7...8bc8; one commit, no push | reports/C.3_RETURN.md | Amendment 10 hard-stop readout built in news_eval and re-frozen under reports/c3_harness_freeze.json; synthetic only, no outcome read |
| C.2b | STAGE_C.2b.md | Opus 5.5, max (Fable xhigh gate verification and pre-run integrity check, Fable xhigh verdict verification, Fable max verdict review) | attempt 2: 2026-11-06 from 00:15 MST after the V8 unlock (manifest 19dc1da7...8bc8), Claude Code lead Opus 5.5 max, 1 spawn (GateVerifier, Fable xhigh); stopped at 00:25 on the 5-hour usage limit and restarted 2026-11-07 01:58 MST after a reboot; commits 7d01388 (snapshot and gate) and the return commit; attempt 3 on or after 2026-11-13 at 71 judged collection days | reports/C.2b_RETURN_<YYYYMMDD>.md (attempt 2: reports/C.2b_RETURN_20261106.md) | Reusable continuation of C.2: one snapshot and gate per attempt, the single run after a PASS, or once in --hard-stop mode on the first snapshot with S* on or after 2027-01-15; carries C.3 items P1 to P6. Attempt 2: gate FAIL on power (M 6,653 < Required 16,068), no verdict run, judgments unread |
| P.1 | STAGE_P.1.md | Opus 5.5, max (Fable xhigh leak audit, archive audit and claims review) | 2026-11-07 01:58 to 08:52 MST, Claude Code lead Opus 5.5 max in eight sessions after seven self-wipes (one fired by the planner's /clear), 33 spawns (Opus xhigh 8, Opus high 10, Sonnet high 9, Fable xhigh 5 for the leak audit, archive audit, claims review and two fix checks, Haiku medium 1). The 5-hour usage limit stopped work from about 05:46 to 06:50, and the planner's 08:06 deadline note kept research-archive local. Commits bb09341 (publish sources) and the return commit. No push | reports/P.1_RETURN.md | Public repos and GitHub profile: llm-news-drift from Stage A onward, research-archive grouping the smaller research repos with history and one card each, the profile README, private-only GitHub changes; Kiros goes public with publish/go_public.sh |

Model names are as written in each prompt at the time. The routing rules
that apply today are in CLAUDE.md.

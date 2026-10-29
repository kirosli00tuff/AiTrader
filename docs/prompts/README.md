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

Model names are as written in each prompt at the time. The routing rules
that apply today are in CLAUDE.md.

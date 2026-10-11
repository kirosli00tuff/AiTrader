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
| C.1 | STAGE_C.1.md | Opus 5.5, xhigh (Fable xhigh verification and second grader, Fable max leakage review) | 2026-10-10, launched by the planning chat | reports/C.1_RETURN.md | Evaluation harness news_eval/ built on synthetic rows and frozen per Amendment 9, 8.3 relevance sample drawn and graded; no outcome read |

Model names are as written in each prompt at the time. The routing rules
that apply today are in CLAUDE.md.

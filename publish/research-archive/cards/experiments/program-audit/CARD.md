# program-audit
Group experiments. First commit 2026-08-29, last commit 2026-09-13, 83 commits.

## Question
A neutral audit of the research program, findings only (README.md). Agent A tested whether the program closed hypotheses too early or too hard. Agent B tested whether it claimed more than its evidence supports. Agent C refereed both (findings/METHOD.md).

## Registered before testing
Not pre-registered as an experiment. The audit rules given to every agent, findings/protocol/COMMON_RULES.md, were first committed on 2026-09-02 17:38:57 -0700. The first findings commit came at 21:48:43 the same day. The design separates a blind pass from a later targeted pass (README.md).

## Dates
First commit 2026-08-29. Last commit 2026-09-13.

## Data
Thirteen of the program's own repositories, read from read-only snapshots at anchored commits listed in findings/ANCHOR.md (findings/METHOD.md). Agents' scratch computations sat under work/ (RESUME.md). The snapshots and work/ are not included in this archive.

## Method
Each repository went through a chain of fresh-context agents: readers, a consolidator, two verifiers for citation and labelling, and an applier (findings/METHOD.md).
Agent C recomputed the highest-severity numeric claims from code, data and Git objects, then adjudicated the A and B findings (findings/METHOD.md).
The audited repositories were never modified. Cleanliness checks ran before and after every run (findings/METHOD.md).
The planned order ended with a SUMMARY.md, a completed METHOD.md and a `findings-frozen` tag (findings/METHOD.md).

## Result
Incomplete. At the last recorded state, Agent A had finished 13 of 13 repositories, and Agents B and C had each finished 10 of 13 (provenance/RUN_LOG.md). Agent A's cross-repository pass over 136 leads found seven findings, none above severity S3 (findings/agentA/CROSS_REPO.md). That pass calls the program's cross-repository record mostly sound (findings/agentA/CROSS_REPO.md). METHOD.md is still marked DRAFT (findings/METHOD.md). No SUMMARY.md and no `findings-frozen` tag exist.

## Why it stopped
Not recorded. The last commits launch B run 16 and C run 16 on 2026-09-13 after earlier runs were cut by session limits (provenance/RUN_LOG.md). No later outcome is recorded.

## One thing learned `[KIROS: confirm]`
The cross-repository failures had one shape: a repository stated a blocker as a fact about the world, and a sibling's dated record said otherwise.

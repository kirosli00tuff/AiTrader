# soltool
Group solana. First commit 2026-09-05, last commit 2026-09-10, 7 commits.

## Question
A read-only screener, not an experiment. Given a Solana mint address, what do seven public screening sources say about it, and which of fourteen fixed rules does that evidence satisfy (README.md)?

## Registered before testing
Not pre-registered. The repo is a tool and states no hypothesis.

## Dates
First commit 2026-09-05. Last commit 2026-09-10.

## Data
Live replies from seven vendors: Helius, RugCheck, Jupiter, GoPlus, Trench Radar, InsightX and DEX Screener. Raw replies go to a local JSONL ledger (README.md). The data is not included in this archive.
docs/gui.md links a screenshot, docs/screenshots/result-full.png, that the build removed as a non-code file over 1 MB, so that image link is broken in this archive.

## Method
- Stage A: scan one mint across the seven sources concurrently and fold the answers into PASS, FAIL or UNVERIFIED.
- List disagreements between sources separately instead of resolving them.
- Stage B: screen newly listed pools in batch with the same scan.
- Stage C: re-check tokens held by a public address on an interval and alert once per change.
- Store every raw vendor payload before the screen updates.

## Result
No experimental result. The tool states these measured facts.
- One verdict comes from fourteen fixed checks with published cut-offs (README.md).
- Sending the configured RugCheck key turned a working 200 into a 401, so the tool calls RugCheck keyless (README.md, docs/vendors/rugcheck.md).
- The InsightX free tier allows 5 calls a minute and 1,000 a month, so continuous discovery polling would use a month of quota in a few hours (README.md).

## Why it stopped
Not recorded. The last commit adds the Stage C position monitor.

## One thing learned `[KIROS: confirm]`
UNVERIFIED is never a pass. Missing evidence is reported as loudly as a failure (README.md).

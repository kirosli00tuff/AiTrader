# NPDExperiment
Group experiments. First commit 2026-08-25, last commit 2026-08-25, 11 commits.

## Question
Given anonymized per-name numeric feature blocks, does a frontier LLM rank next-window cross-sectional returns better than cheap mechanical baselines? It replicates an earlier AiTrader LLM council negative under a changed task.

## Registered before testing
REGISTRATION.md, first committed 2026-08-25 09:39:00 -0700, before the first model call and before the data layer commit at 10:06. Amendments 1 to 5 were added during collection. Amendment 6 arrived after the evaluation ran and is marked as carrying no pre-registration force.

## Dates
First commit 2026-08-25. Last commit 2026-08-25.

## Data
Daily bars from AiTrader's local bar store, opened read-only. Rankings returned by the OpenAI model gpt-5-2025-08-07, whose knowledge cutoff is 2024-09-30. Only days after the cutoff and a guard month were eligible. The data is not included in this archive.

## Method
Each eligible day, 30 names are drawn from the U-LIQ-500 universe by a seeded rule. The model sees nine z-scored features per name, with no tickers, dates or prices, and returns a full ranking. The primary score is the mean daily rank IC against the next-5-session return. Three mechanical baselines are scored on the same days, and a within-day shuffle checks for leakage. Inference uses a day-clustered bootstrap and a within-day permutation null.

## Result
Section 0 fired GO at 96.1 percent coverage (reports/stage_b1/collection.md). The verdict row fired was "does not beat coin" (reports/stage_b2/evaluation.md). The model mean daily rank IC was +0.0061, with an interval from -0.0276 to +0.0397 (reports/stage_b2/evaluation.md). The best baseline, mom_12_1, scored +0.0222, so the primary contrast was -0.0161, permutation p 0.5174 (REGISTRATION.md, Closure). The realized minimum detectable contrast was 0.0512, above the whole realistic effect band of 0.01 to 0.05 (REGISTRATION.md). The repo calls this an underpowered unresolved, not a tight null (REGISTRATION.md).

## Why it stopped
The question was closed by operator decision, not by evidence, on 2026-08-25 (REGISTRATION.md). A powered version would need about 1,700 post-cutoff trading days, and no model has that window (REGISTRATION.md).

## One thing learned `[KIROS: confirm]`
The model leaned against momentum rather than adding noise around it, which widened the contrast and cost the design its power. The repo records this as an observation, not a finding.

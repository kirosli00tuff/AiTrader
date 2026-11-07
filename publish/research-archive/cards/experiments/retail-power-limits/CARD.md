# retail-power-limits
Group experiments. First commit 2026-08-29, last commit 2026-08-29, 3 commits in the original repo. Here `git log -- experiments/retail-power-limits/` shows 4: the extra one adds this card.

## Question
Across four pre-registered experiments, was the binding constraint whether a published effect exists, or whether an achievable sample could detect an effect of the reported size (README.md)?

## Registered before testing
Not pre-registered. This is a written note about four earlier experiments, and it computes no statistic of its own (README.md). The whole note arrived in its first commit.

## Dates
First commit 2026-08-29. Last commit 2026-08-29.

## Data
No market data. Every figure comes from four sibling repositories, mapped to repository, file and commit in SOURCES.md (README.md). The data is not included in this archive.

## Method
Each case's measured detectability is set against its effect band (README.md).
The note traces how the program moved from finding the power problem after collecting to refusing early on a registered power gate (README.md).
Tests fail the build if the scope-limit sentence or any headline figure is removed (README.md).

## Result
NPDExperiment had a minimum detectable contrast of 0.0512 against an effect band of 0.01 to 0.05, and closed unresolved at achievable power (README.md).
InsiderExperiment had a minimum detectable effect of 49.35 bp per month and fired BLOCKED on its power gate (README.md).
ETFExperiment projected 163 admissible days at its deadline against a governing minimum of 300, and closed untestable at achievable power (README.md).
HFExperiment reached z 1.668 against a corrected bar of 2.50 (README.md).
The note says this is not evidence that those anomalies are absent, and that four cases are not a survey (README.md).

## Why it stopped
The note was written and shipped in one stage, with nothing outstanding inside the repository (progress.md).

## One thing learned
Compute the minimum detectable effect from dispersion and sample size alone, and commit the gate before the measurement it judges.

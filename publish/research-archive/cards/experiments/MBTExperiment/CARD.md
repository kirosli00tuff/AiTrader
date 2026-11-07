# MBTExperiment
Group experiments. First commit 2026-09-02, last commit 2026-09-12, 23 commits in the original repo. Here `git log -- experiments/MBTExperiment/` shows 24: the extra one adds this card.

## Question
VRPExperiment left one route open for harvesting the BTC variance premium: CME options on Micro Bitcoin futures through IBKR Canada. This repo measures the two venue figures that route turns on, the margin per short option and the cost legs, against thresholds fixed in advance.

## Registered before testing
REGISTRATION.md, first committed 2026-09-02 23:48:40 -0700 with Section 0, the outcome map and the gates. Sections 1 onward followed at 23:51:07, before any quote was stored. The first measurement commit, the paper harness record, came at 23:54:33, 206 seconds later. A gateway reachability probe at 23:27 came earlier but measured no gate figure.

## Dates
First commit 2026-09-02. Last commit 2026-09-12. The closure documents are dated 2026-09-03 and were committed on 2026-09-12.

## Data
IBKR paper-account what-if previews and market data for CME Micro Bitcoin futures and options. A CME margin rate export for crypto products. Deribit figures were carried as reference only and never fed a gate. The data is not included in this archive.
The CME export, docs/evidence/cme_outright_rates_crypto_20260903.csv, was removed from the whole history, because it is exchange data and nothing shows a right to redistribute it.

## Method
Two gates were registered. MARGIN passes if the initial margin on a short MBT option is at most 12.80 percent of notional, which was 1,000 USD at registration. COST passes if the absent cost legs at p90 stay at or below a registered bp ceiling. Both PASS was required to authorize a sleeve in a third repository. Every broker call was a what-if preview or a market data read. A test walks the code to prove no order can transmit.

## Result
VENUE_BLOCKED, unqualified, on capital (CLOSURE.md). CME maintenance margin on one MBT future, the hedge leg alone, was 1,704.00 USD, or 20.837 percent of notional (CLOSURE.md). That is 1.628x the 12.80 percent ceiling (CLOSURE.md, reports/task8/margin_gate_final.json). 18 paper what-if previews put a single short option at 3,441.42 to 4,599.07 USD, with zero of 18 below the ceiling (CLOSURE.md). The COST gate never fired. It stayed absent at n = 0 of 20 registered windows, and no CME spread was ever measured (CLOSURE.md). The closure says the route is shown to be uncapitalizable at 1,000 USD, not unprofitable (CLOSURE.md).

## Why it stopped
The MARGIN gate failed at a 1,000 USD sleeve. The closure is final at that size. A different capital limit is a different question and needs its own registration in a new repository (CLOSURE.md, REINTRODUCTION.md).

## One thing learned
The safety flag the code relied on was the wrong one: IBKR requires a what-if preview to carry transmit=True, and the property that prevents transmission is whatIf=True.

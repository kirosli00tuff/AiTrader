# HFExperiment
Group experiments. First commit 2026-08-23, last commit 2026-08-28, 13 commits.

## Question
Does a top-five book of 12-1 cross-sectional momentum names earn positive daily excess return over its universe after costs? A second question was whether a real broker could run that book at micro size, with fractional orders of 45 USD per name through its API.

## Registered before testing
REGISTRATION.md, first committed 2026-08-23 15:23:16 -0700 as the first commit. Section 0, the broker outcome map, was registered before any broker measurement. Sections 1 to 12 were committed at 21:40 the same day, before any shadow observation. The shadow series never produced one.

## Dates
First commit 2026-08-23. Last commit 2026-08-28.

## Data
Daily bars from Alpaca, adjusted. The U-LIQ-500 universe rule copied from an earlier AiTrader research round. Paper order tests at Interactive Brokers through its Gateway API. The data is not included in this archive.

## Method
Two series were planned. A shadow series computes the registered book daily from prices alone, with no fills. A live series places micro-size orders to measure execution cost directly. The book re-forms on the first trading session of each month. Section 0 fixed three broker outcomes in advance: GO, DEGRADED and BLOCKED. Stage A.1b tested fractional orders on a paper account while the market was closed.

## Result
Section 0 verdict BLOCKED (REGISTRATION.md). All 20 names in the test book were fractional-eligible at the contract layer, with a size increment of 0.0001 (reports/stage_a1b/a1b_report.md). The API still refused every decimal-quantity order with error 10243 and the cash-quantity order with error 10244 (reports/stage_a1b/a1b_report.md). A whole-share control order was accepted (reports/stage_a1b/a1b_report.md). Five of the ten-order cap were used and no order filled (reports/stage_a1b/a1b_report.md). Stage A.1 reproduced all 124 recorded formation dates (reports/stage_a1/reproduce_log.txt). The signal verdict was never computed (progress.md).

## Why it stopped
The operator closed the experiment on 2026-08-26, the day after the BLOCKED verdict. The shadow timer was disarmed before its first accrual. No capital was deployed (progress.md). The closure entry gives no further reason.

## One thing learned `[KIROS: confirm]`
A broker can mark every instrument as fractional-eligible and still refuse fractional orders through its API, so only a placed order settles the question.

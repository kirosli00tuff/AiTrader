# VRPExperiment
Group experiments. First commit 2026-08-29, last commit 2026-08-30, 12 commits.

## Question
Does the option market charge more volatility than BTC and ETH later deliver? And can a British Columbia resident lawfully harvest that premium, below cost, with about $1,000 (docs/ARTIFACT.md)?

## Registered before testing
REGISTRATION.md, first committed 2026-08-29 21:47:08 -0700. Its commit message says it was committed before any network call. The first measurement commit, venue reachability, came at 23:22:23 the same day. Amendment 1 records a first sealed-read attempt that aborted before any estimator ran (REGISTRATION.md).

## Dates
First commit 2026-08-29. Last commit 2026-08-30.

## Data
Deribit DVOL, the exchange's 30-day implied volatility index, and Deribit index prices for the realized leg, from its public API (REGISTRATION.md, docs/ACCESS.md). Published commission schedules for CME micro crypto options through Interactive Brokers Canada (docs/ARTIFACT.md). The data is not included in this archive.

## Method
The premium is implied volatility (DVOL) minus close-to-close realized volatility over the next 30 days, one observation per day per asset (REGISTRATION.md).
Volatility points convert to basis points of notional at a rate registered before any data (README.md). Standard errors are Newey-West with bandwidth 30 (REGISTRATION.md).
Costs, venue reach and contract size were measured from public pages only. The registered bar asks the premium's lower confidence bound to exceed twice the pessimistic cost (docs/ARTIFACT.md).

## Result
The BTC premium was 198.11 bps of notional, n = 1,955, p = 2.3 × 10⁻⁹ (README.md). The ETH premium was 119.05 bps, n = 1,955, p = 7.9 × 10⁻³, and unstable, with one negative quarter (README.md).
On Micro Ether the central commission-only cost was 122.14 bps, larger than the ETH premium, and the registered bar fails by 8.6 times (docs/ARTIFACT.md). On Micro Bitcoin the BTC lower bound of 142.74 bps clears the bar by 3.28 times on commission alone (docs/ARTIFACT.md). It stays open on two figures that need a brokerage account: initial margin at or below 12.80 percent of notional, and spread plus exchange fees at or below 49.61 bps (docs/ARTIFACT.md).
Verdict: VENUE_BLOCKED, qualified, with one route open on two named figures (README.md).

## Why it stopped
It was a single-stage census with one artifact and no successor in this repository (docs/HANDOVER.md). The open route needs a brokerage account, which the repository does not have and will not open (README.md).

## One thing learned `[KIROS: confirm]`
The arithmetic that decided reachability was not about the premium at all. It was about contract size.

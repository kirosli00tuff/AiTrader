# EXPERIMENT.md — News-drift pre-registration

> **STATUS: PROPOSAL, PENDING OPERATOR REVIEW. NOT BINDING.**
>
> This document is a proposed pre-registration written by Stage 0. It becomes
> binding only when the operator reviews and accepts it. Until then no number
> here constrains anything, and a later session may not cite it as settled.
>
> Written 2026-07-27. Nothing was built, collected, called, or traded to
> produce it. The only computation performed was read-only queries against
> `analysis_bars.db` to check that the proposed universe rule yields a
> workable membership.

## Why this exists

Every prior research attempt in this project built first and measured after.
Seven price-based hypothesis families are dead against buy-and-hold after
costs. The LLM council reached a properly powered negative: 274 scorable calls
across 80 symbol clusters, pooled excess -0.5 bp per call, interval
[-22.5, +21.4], which excludes the 50 bp effect the design was built to detect.

This experiment measures first. Stage 0 is this document. No collection begins
until it is accepted.

---

## TASK 1 — The hypothesis

**A large language model's three-way directional judgment of a single news
headline, given only that headline and its ticker, predicts the sign of that
stock's next-session return in excess of the contemporaneous cross-sectional
move, for US common equities in the rank 1500 to 5000 liquidity band, by a
margin exceeding the band's round-trip cost hurdle.**

Every clause is load-bearing and a later session may not relax one:

- **three-way** — POSITIVE, NEGATIVE, NEUTRAL. Not a score, not a probability.
- **a single news headline** — headline text only, one per call.
- **only that headline and its ticker** — no price, no derived number. Task 3.
- **next-session return** — the horizon in Task 4, not one chosen later.
- **in excess of the contemporaneous cross-sectional move** — the benchmark is
  the unconditional move over the same window, never zero. Task 5.
- **rank 1500 to 5000** — the universe in Task 2.
- **exceeding the band's round-trip cost hurdle** — beating zero is not the bar.

### The economic mechanism

The claim is **delayed information diffusion under limits to arbitrage**. A
headline reaches the market as text before its implications are priced. Prices
adjust over hours to days rather than instantly, because the participants who
would close the gap face costs that scale unfavourably in small names: wide
spreads, thin depth, borrow constraints on the short side, and per-name
research cost that does not amortise across a large book.

**Why it would persist for a fee-paying participant.** The literature places
the effect where institutional capital is least able to operate: small
capitalisations, where a fund large enough to employ analysts cannot take a
position that matters to its own returns without moving the price. A
participant sized at 500 USD per position sits below that constraint. The same
smallness that makes the effect uneconomic for the arbitrageur is what leaves
it available, and is also why the capacity gate in Task 6 is the binding
question rather than an afterthought.

**Three recorded qualifications, carried forward rather than discovered
later.** The effect concentrates in **smaller stocks** and in **negative
news**, and **returns decline as adoption rises**. The second matters for
interpretation: if the measured effect is positive-news-only, that is evidence
against the mechanism rather than partial confirmation. The third matters for
the forward look: an effect measured on history need not survive to the
present, so Task 5 pre-registers a chronological split.

### What would falsify the mechanism rather than the effect

A positive result concentrated in the **liquid** end of the band, or in
**positive** news, or growing rather than shrinking over the sample period,
contradicts the stated mechanism even if it clears the significance bar. Such
a result is recorded as unexplained, not as a confirmation.

---

## TASK 2 — The proposed universe rule

### The rule

**`U-NEWS-1500-5000-stk-w60-m40-p5-s400`**

At each formation date **D**:

1. **Liquidity measure**: median daily dollar volume (`close x volume`) over
   the trailing window. Median, not mean, so one squeeze session cannot buy
   membership. This is the measure `backtest/universe.py` already uses,
   deliberately, so two universe rules in this repository cannot disagree about
   what liquidity means.
2. **Trailing window**: the **60 trading sessions ending the session BEFORE D**.
   The window excludes D, because a window containing the formation date
   decides membership using a bar the period it governs can trade on.
3. **Eligibility inside the window**: at least **40 of 60** bars present, median
   close at or above **5.00 USD**, and no listing-segment break. All measured
   inside the same window.
4. **Rank** every eligible symbol by the liquidity measure, descending, ties on
   symbol ascending. Take **ranks 1500 through 5000**.
5. **Sample 400 symbols**, stratified (below).
6. **Formation schedule**: the first trading session of each **calendar
   quarter**, from the exchange calendar, never from a symbol's own bars.
7. **Membership holds for the whole quarter.** A symbol admitted at D stays a
   member until the next formation date. **A delisted name remains a member
   until it stops trading**, and its final partial session is scored normally.

**Point-in-time by construction.** Only data dated strictly before D enters the
decision. No symbol is admitted or retained on later performance, and no
present-day list is consulted.

### The stratified sample

The band holds ~3,500 names. Sampling the liquid end would defeat the point,
since the mechanism claims the effect lives at the thin end.

Four equal-width rank strata, **100 symbols each**:

| stratum | ranks | width |
|---|---|---|
| S1 | 1500 - 2374 | 875 |
| S2 | 2375 - 3249 | 875 |
| S3 | 3250 - 4124 | 875 |
| S4 | 4125 - 5000 | 876 |

Selection inside a stratum is uniform at random, seeded deterministically from
`sha256(rule_id + formation_date)`, so the draw is reproducible, auditable, and
chosen by nobody. The seed and the resulting member list are recorded at
formation.

**Stratum is a recorded field on every observation**, because the mechanism
predicts a gradient across strata and a pre-registered secondary test checks
it (Task 5).

### What the rule actually yields

Computed read-only against `analysis_bars.db` (consolidated SIP,
`adjustment=all`):

| formation date | window | eligible pool | band members | ADV at rank 1500 | ADV at rank 5000 |
|---|---|---|---|---|---|
| 2020-01-02 | 2019-10-07 .. 2019-12-31 | 7,844 | 3,501 | $21,108,236 (RVLV) | $310,358 (CTAC) |
| 2023-01-03 | 2022-10-06 .. 2022-12-30 | 8,964 | 3,501 | $30,599,824 (VMI) | $589,725 (TERN) |
| 2026-01-02 | 2025-10-07 .. 2025-12-31 | 9,999 | 3,501 | $59,716,980 (LIF) | $1,327,867 (HYDR) |

Sample names across the 2026-01-02 band: LIF, NAMS, PLTM, EXG, HYDR.

### A problem this table exposes, recorded rather than smoothed

**Rank is not a stable proxy for ADV across time, and the cost calibration was
done on ranks.** At the 2026 formation, rank 5000 has ADV 1.33M USD. At the
2020 formation the same rank has 310k USD, which the liquidity calibration
places in **tier 5 or 6**, where the hurdle floor is 6.63 to 43.21 bp rather
than the 4.87 bp the band was justified on.

The band therefore does not carry a constant cost across the sample period, and
a result pooled over 2020 and 2026 pools two different hurdles.

**PROPOSED RESOLUTION, and it is a choice:** cost is charged **per observation
from the symbol's own ADV and price at its formation date**, via
`fees.equity_per_side_bp(price, adv, notional)`, never from a band-level
average. The rank band selects WHICH names are studied; the fee model prices
each one individually. **What would change it:** if per-observation costing
makes the pooled result uninterpretable (a wide cost dispersion swamping the
effect), the alternative is to define the band by absolute ADV thresholds
rather than rank, which is a different rule needing its own pre-registration.

### What a news source must cover

- **400 US-listed common equities per quarter**, refreshed at each formation.
- Symbols at the thin end: ADV as low as ~300k USD, market caps well under 1B
  USD. **A source covering only S&P names is useless here.**
- **Per-headline publication timestamp at minute resolution or better** (Task 4).
- Headline text and the ticker it is filed under.
- Roughly **400 symbol-day queries per trading day**.

Against the integrated Finnhub company-news endpoint at the 60 calls/minute
free tier, 400 queries is under 7 minutes of wall clock per day. The rate limit
is not the binding constraint. **Whether that source's small-cap coverage is
adequate is unresolved and is Open Question 1.**

### Size arithmetic

Two constraints, and the sample must satisfy both.

**Constraint A, news coverage.** 400 symbols is ~7 minutes/day against the
existing rate limit, so coverage is feasible. 3,501 symbols would be ~58
minutes/day of continuous polling for a payload empty on most rows, which is
wasteful rather than impossible.

**Constraint B, the sample size the statistics require** (derived in Task 5):
**1,000 scorable observations across at least 60 distinct trading days.**

Headline arrival for a name in this band is assumed at **0.10 headlines per
symbol per trading day**, with most days empty. That assumption is soft and is
Open Question 2.

```
400 symbols x 0.10 headlines/symbol/day  =  40 headlines/day
40/day x 60 trading days                 =  2,400 raw headlines
x 0.75 surviving the delay and hygiene filters (Task 4)
                                         =  1,800 scorable observations
1,800 >= 1,000 required                  ->  clears with 80% margin
```

At a pessimistic 0.05 headlines/symbol/day the same arithmetic gives 900, which
does **not** clear. **The collection therefore runs until BOTH thresholds are
met** (1,000 observations AND 60 day-clusters), with a hard stop at 120 trading
days. If 120 days do not reach 1,000, the experiment reports an underpowered
abstention and does not lower the bar.

400 was chosen as the smallest sample clearing the requirement at the central
arrival assumption, with the pessimistic case caught by the running-until rule
rather than by a mid-experiment sample increase.

---

## TASK 3 — The prompt and the model

### The model

**DeepSeek V4 Flash**, temperature **0**, `max_tokens` 60.

Pricing, read 2026-07-27 from the published DeepSeek API pricing page:

| | per 1M tokens |
|---|---|
| input, cache miss | $0.14 |
| input, cache hit | $0.0028 |
| output | $0.28 |

**Cost per call.** The system block is ~180 tokens, the user block ~20, the
response ~30.

```
cache hit:   180 x 0.0028/1M  +  20 x 0.14/1M  +  30 x 0.28/1M  = $0.0000117
cache miss:  180 x 0.14/1M    +  20 x 0.14/1M  +  30 x 0.28/1M  = $0.0000364
1,800 observations, cached:   ~$0.021
1,800 observations, uncached: ~$0.066
```

Cost is not a constraint at any plausible sample size. That is itself a reason
to record cost per call anyway (Task 8): a figure nobody checks is how the 25x
crypto fee error survived.

**Caching layout.** The system block is byte-identical on every call and is the
cached prefix. The ticker and headline are the only variable content and sit
**last**, in the user message. Nothing variable appears before the end of the
system block.

**A HARD-RULE CONFLICT, REPORTED NOT RESOLVED.** CLAUDE.md states that
`claude-opus-4-8`, `gpt-5.5`, `gemini-3.1-pro-preview` and `claude-haiku-4-5`
"are the only approved model strings; do not invent others." DeepSeek V4 Flash
is not among them. Read narrowly, the rule governs the **LLM council's** model
strings and this experiment is a separate subsystem that never feeds the
council. Read broadly, it governs the repository. **CLAUDE.md wins and the
conflict is reported rather than resolved silently.** Accepting this document
means accepting a fifth model string for a non-council use, and CLAUDE.md
should be amended at that point. Open Question 5.

### The exact prompt, byte for byte

**System block** (the cached prefix; reproduce exactly, including newlines):

```
You judge whether a news headline is likely to move a US-listed stock's price by the next market close.

Reply with exactly one JSON object and nothing else, in this form:
{"judgment": "POSITIVE", "reason": "<at most 20 words>"}

judgment must be exactly one of POSITIVE, NEGATIVE, NEUTRAL.

POSITIVE means you expect this stock to outperform the broad market by the next close.
NEGATIVE means you expect this stock to underperform the broad market by the next close.
NEUTRAL means you expect no material difference either way.

You are given the ticker and the headline text. You have no price, no chart, no volume, no indicator, and no other information, and you must not assume any.

Do not answer NEUTRAL to be safe. Answer NEUTRAL only when the headline genuinely carries no directional information about this company.
```

**User block** (variable, headline last):

```
TICKER: {ticker}
HEADLINE: {headline}
```

`{ticker}` is the symbol as the universe rule records it. `{headline}` is the
raw headline text, unmodified, with no truncation and no cleaning beyond
stripping leading and trailing whitespace.

### What the model receives, and what it does not

**Receives:** the ticker, the headline text.

**Does NOT receive:** price, return, volume, volatility, indicator, regime,
sector, market cap, liquidity rank, stratum, date, time of day, prior verdicts,
any other headline, or any derived number of any kind.

**Why.** The price-only space is resolved negative across seven hypothesis
families, and the 1,400-token evidence block that preceded this design produced
a powered negative. Adding price back would re-test a settled question and make
a positive result uninterpretable, since it could not be attributed to the
headline. **The stratum and the date are recorded on the observation and
withheld from the model**, which is what lets the Task 5 secondary tests be
honest.

---

## TASK 4 — Horizon and the actionable moment

### The convention, both cases

| headline arrives | scored |
|---|---|
| during the regular session | that session's **close** to the **next session's close** |
| outside the regular session | the next session's **open** to that same session's **close** |

Either way the hold is roughly one session. Regular session means 09:30 to
16:00 America/New_York.

### The minimum delay

**20 minutes** between the publication timestamp and the first actionable
moment. A headline whose publication timestamp falls within 20 minutes before a
close cannot be acted on at that close and **rolls to the next session**, scored
open-to-close there.

**This number is PROVISIONAL and CONSERVATIVE.** It is not measured. It stands
in for source polling latency plus model round trip plus order placement.
**Stage 1 measures the real pipeline latency** and this number is replaced by
the measured **p95**, not the median.

**What would change it.** If Stage 1 measures p95 end-to-end latency below 5
minutes, the delay tightens and more headlines become same-session actionable,
increasing the sample. If Stage 1 measures p95 above 20 minutes, the delay
widens and the experiment must be re-powered before collection continues.
**The delay may only be tightened on measured evidence, never on the
observation that a looser delay yields more observations.**

### Which timestamp counts as publication

**The source's own reported publication timestamp for the article**, normalised
to UTC, at minute resolution or better.

- Never the time the collector fetched it.
- Never the time the model was called.
- If the source reports only a date with no time, the headline is **excluded**
  and recorded with `exclusion_reason = 'no_publication_time'`. It is not
  assumed to have arrived at midnight, at the open, or at any other hour.
- If the source reports a timestamp later than the fetch time, the row is
  recorded and excluded as `clock_inconsistent`.

Fetch time and model-call time are both recorded separately (Task 8) so real
latency is measurable at Stage 1 without a second collection.

### Calendar edge cases

All resolved against the exchange calendar in `analysis_bars.db`
(`trading_calendar`), never against a weekday rule.

- **Holiday.** A headline published on a non-session day is treated as
  out-of-session and scored open-to-close on the next session.
- **Half day.** The early close (usually 13:00 ET) is the session close for
  every purpose, including the 20-minute delay window. The calendar's own
  `close` column is authoritative, not a hardcoded 16:00.
- **A symbol that does not trade that session.** If the scored symbol has no
  bar for the scoring session, the observation is **recorded and excluded**,
  `exclusion_reason = 'symbol_did_not_trade'`. It is never scored as a zero
  return. A halted symbol that resumes the following session is not rolled
  forward: the horizon is fixed at pre-registration, and moving it per
  observation is how a horizon gets chosen by its result.
- **A gap in the price series** is absence, never a filled value. This is the
  storage-layer property already established: no placeholder row is written for
  a session a symbol did not trade.

---

## TASK 5 — Scoring, benchmark, and the bar

### The scored quantity

For observation `i` on symbol `s` over its scoring window:

```
raw_i      = the symbol's return over the window (adjustment=all)
bench_i    = the UNCONDITIONAL move over the SAME window
excess_i   = raw_i - bench_i
signed_i   = +excess_i  if judgment == POSITIVE
             -excess_i  if judgment == NEGATIVE
             (NEUTRAL is not scored)
net_i      = signed_i - cost_i
```

**The benchmark is the unconditional move over the same window, not zero.**
Defined as the **equal-weighted mean return of every eligible band member that
traded that window**, from the same bars. Equal-weighted, because the
hypothesis is about names in this band, not about a cap-weighted index the
band's members barely influence. Using zero would credit the model for the
market's direction, the error the council measurement already had to correct.

**NEUTRAL verdicts are not scored** and are counted separately. A model that
answers NEUTRAL to everything must not be able to produce a null by abstaining.
The **NEUTRAL rate is a recorded primary diagnostic**, and a rate above 80
percent is itself a reportable failure of the design.

`cost_i` is the **per-observation round trip** from
`fees.equity_per_side_bp(price, adv, notional)` at the symbol's own price and
formation-date ADV, doubled. **The hurdle is not a single number**, for the
reason in Task 2. For orientation the band's floors are **3.15 bp** (ranks
1501-3000) and **4.87 bp** (ranks 3001-5000), and every such figure is a floor
assuming a one-tick market.

### The clustering unit

**PROPOSED: cluster by TRADING DAY.**

The prior session clustered by symbol and found the unit could not absorb an
asset-class mix effect, because a symbol belongs entirely to one class. The
analogous confound here is the **day**: a market-wide move on one session
affects every observation scored that session, so residuals correlate within a
day and treating calls as independent overstates significance.

| unit | absorbs | fails to absorb |
|---|---|---|
| **day** | market-wide moves, macro releases, regime | a sector shock, one story hitting several tickers |
| sector | sector shocks | market-wide moves, which are larger |
| news event | one story across tickers | everything else |

**Day is chosen** because the market factor is the largest correlated component
of a one-session equity return, and because benchmarking against the
same-window unconditional move already removes most of it, leaving day
clustering to absorb the residue. Sector is **recorded** and a sector-clustered
variance is reported as a **secondary robustness figure**, so the choice is
checkable rather than asserted.

**News-event clustering is handled by de-duplication rather than by the
variance estimator**: near-identical headlines for the same ticker within 24
hours collapse to the first, and one story naming several tickers produces one
observation per ticker with a shared `story_group_id` recorded. **If more than
10 percent of observations share a `story_group_id`, the primary estimate is
re-run clustered on `story_group_id`** and both are reported.

### The bar

- **Primary test:** is pooled mean `net_i` greater than zero.
- **Estimator:** cluster bootstrap over day clusters, 10,000 resamples,
  two-sided.
- **Four pre-registered primary tests**, so a **Bonferroni** correction gives
  **`|z| >= 2.50`** (0.05/4 two-sided):
  1. pooled net excess over all scored observations,
  2. **NEGATIVE-only** subset (the literature's stronger case),
  3. **thin-end** subset, strata S3 and S4,
  4. **chronological second half**, testing decay.
- **Cluster floor:** at least **60 distinct day clusters**. Below that the
  result is an abstention regardless of the point estimate, following the
  precedent that a thin sample is not a finding.

Anything outside those four is **exploratory** and is labelled so. Exploratory
results may motivate a new pre-registration and may never be reported as a
finding.

### Required sample size

Assumed effect, stated before collection: **30 bp gross** per scored
observation, the middle of the "tens of basis points" the literature describes,
less a representative **5 bp** cost, giving **25 bp net**.

Residual standard deviation: measured median daily volatility in these bands is
2.41 percent (S1-S2) and 1.76 percent (S3-S4). Removing the market factor via
the benchmark leaves an idiosyncratic residual taken **conservatively at
180 bp**.

```
n = (z_alpha/2 + z_beta)^2 * sigma^2 / delta^2
  = (2.50 + 0.84)^2 * (180/30)^2          80% power, Bonferroni z
  = 11.156 * 36
  = 402 independent observations

Design effect for day clustering, k = 40 obs/day, rho = 0.05 post-benchmark:
  DE = 1 + (k-1) * rho = 1 + 39*0.05 = 2.95
  n_required = 402 * 2.95 = 1,186
```

**Pre-registered: 1,000 scorable observations across at least 60 day
clusters, collection continuing until both are met.** The 1,000 figure sits
below the 1,186 the design effect implies, and that gap is deliberate and must
be read honestly: `rho = 0.05` is an assumption, not a measurement. **The
realised `rho` is computed from the collected data and reported, and if it
exceeds 0.05 the required n is recomputed and collection continues.** The stop
rule is "both thresholds met AND realised power adequate at the realised rho",
never "1,000 reached".

---

## TASK 6 — What counts as a negative, and the capacity gate

### The result that ends the experiment

**A powered negative:** at 60 or more day clusters, the pooled net excess
interval's upper bound sits below the assumed 25 bp effect while no primary
test clears `|z| >= 2.50`. This mirrors the council measurement that produced
this project's first powered negative, and the hypothesis is then dead. It is
not re-tested with a different horizon, prompt, or band, because each of those
is a new hypothesis needing its own pre-registration.

**An interval that includes both zero and 25 bp at the cluster floor is an
abstention, not a negative and not a finding.**

### The capacity gate, applied now

**A discrepancy has to be resolved first, and it changes the answer by 10x.**

The prompt states Level 1 caps notional at 5 percent, ~5,000 USD. CONTEXT.md
records Level 1 sizing as ~500 USD per trade. **Both are right about different
things**, verified in config:

| key | value | meaning |
|---|---|---|
| `risk.max_trade_notional_cap_pct` | 0.05 | the Level-1 **ceiling** the RiskGate enforces: 5,000 USD |
| `sizing.default_risk_per_trade_pct` | 0.005 | what the **sizer actually sends**: 500 USD base |
| `sizing.default_position_scale_cap` | 1.0 | scale multiplier, so 100 to 500 USD in practice |

The engine sizes at `base * max(scale, 0.2)` where `base = 0.005 * equity`, so a
real position is **100 to 500 USD**, not 5,000. The ceiling is what is
permitted; it is not what is sent.

**The arithmetic, at both.** Floor: 2,500 USD/year on 100,000 equity. Level 1
caps trades at 10/day (`risk.max_trades_per_day`) and open positions at 5, and a
one-session hold means ~5 exits and 5 entries per day, so **10/day is the
structural maximum**, about 2,520 trades/year.

```
AT THE CONFIGURED SIZER, 500 USD max:
  turnover = 2,520 x 500 = 1,260,000 USD/year
  required net edge = 2,500 / 1,260,000 = 19.8 bp per trade
  available (assumed)  = 25 bp net
  CLEARS BY 5.2 bp, a 26 percent margin

AT THE LEVEL-1 CEILING, 5,000 USD:
  turnover = 2,520 x 5,000 = 12,600,000 USD/year
  required net edge = 2,500 / 12,600,000 = 2.0 bp per trade
  CLEARS COMFORTABLY
```

**IS THAT PLAUSIBLE? Stated plainly: at the configured sizing, no, not
comfortably.**

The margin is 5.2 bp on an assumed 25 bp net. Every input on the favourable
side is optimistic:

- 25 bp net assumes the **middle** of the literature range **and** the cost
  floor, and every cost figure in the calibration is a floor assuming a one-tick
  market. A three-tick market in S3-S4 raises the hurdle from 4.87 to 13.45 bp
  and takes the net to 16.5 bp, **below the 19.8 required**.
- 2,520 trades/year requires a directional verdict on ~10 headlines every
  trading day for a year, all passing the RiskGate. The measured NEUTRAL rate
  could halve that, and halving trades doubles the required per-trade edge to
  39.6 bp.
- "Returns decline as adoption rises" is part of the recorded mechanism.

**Conclusion recorded before collection: the hypothesis clears the capacity
floor at the configured sizing only under favourable assumptions on all three of
effect size, tick width, and trade frequency, and fails if any one lands
unfavourably.** It clears comfortably only at the Level-1 ceiling, which would
require raising `default_risk_per_trade_pct` tenfold. **That is a sizing change
with its own justification and its own risk review, and it is NOT part of this
experiment.**

**What this means for whether to proceed.** The measurement is still worth
making, because it is cheap (~$0.07 in model calls) and because a powered
negative closes a question the project would otherwise keep circling. But **it
should be understood going in as a test of a marginal-capacity hypothesis**, and
a statistically significant positive that does not clear the capacity floor is
a **finding, not a strategy**. That distinction is pre-registered here so it
cannot be blurred later.

---

## TASK 7 — The absent-input rule

Five fabrications are recorded in this project, each producing plausible output
from absent input: the walk-substituted bars, the fabricated volumes, the whale
catalyst constant, the admit-by-default fund classifier, and the news catalyst
hash removed on 2026-07-27, which turned out to be suppressing trades rather
than sitting inert.

**News absence for a small cap on a given day is the common case, not the
exception.** At the assumed 0.10 headlines/symbol/day, roughly **90 percent of
symbol-days have no news**. Any representation rendering absence as a neutral
number would make the modal case a fabrication.

### The rule

**Absence is a distinct recorded state and never a score.**

Four states, mutually exclusive, one per symbol-day:

| state | meaning | scored? |
|---|---|---|
| `no_news` | the source was queried successfully and returned no headline | **no** |
| `judged` | a headline was found and the model returned a parseable verdict | yes, unless NEUTRAL |
| `model_failed` | a headline was found and the model call errored, timed out, or returned unparseable output | **no** |
| `source_failed` | the source query itself failed, so absence is **unproven** | **no** |

**`no_news` and `source_failed` are different and must never merge.** The first
is evidence of absence. The second is absence of evidence: the source was not
reachable, so nothing is known about that symbol-day. Collapsing them would let
an outage read as a quiet news day, the fund-classifier defect in another shape.

**`model_failed` and a returned NEUTRAL are different and must never merge.** A
model that answered NEUTRAL considered the headline and held. A model that
failed never considered it. `model_failed` carries the error class and the raw
response text; NEUTRAL carries the model's own reason string.

**A `no_news` row emits no order, no signal, and no factor value of any kind.**
No neutral verdict is written, no 0.0 confidence, no row in any signal table.
The symbol-day simply has no observation.

### How absence is visible

- Every symbol-day queried writes a row with its state, so the denominator is
  always recoverable. The count of `no_news` rows is the evidence the collector
  ran.
- **Daily coverage summary** per collection day: symbols queried, `no_news`,
  `judged`, `model_failed`, `source_failed`.
- **`source_failed` above 5 percent of a day's queries emits a CRITICAL event**,
  following the `fill_provenance_unclassified` precedent: the marker alone is
  insufficient, because a silent marker is how the prior defects survived.
- **A day whose `source_failed` rate exceeds 20 percent is excluded from the
  day-cluster count entirely**, and the exclusion is recorded. A partially
  collected day is not a day.

---

## TASK 8 — What is recorded

One row per symbol-day queried, in a new table the collector owns. Recording is
free and unrecorded fields are unrecoverable, so the schema is deliberately
wider than the primary test needs.

### Identity and universe

| field | type | meaning |
|---|---|---|
| `id` | INTEGER PK | |
| `rule_id` | TEXT | the universe rule instance |
| `formation_date` | TEXT | ISO date of the formation that admitted this symbol |
| `symbol` | TEXT | |
| `liquidity_rank` | INTEGER | rank at formation, 1500-5000 |
| `stratum` | TEXT | S1 \| S2 \| S3 \| S4 |
| `adv_usd_at_formation` | REAL | median daily dollar volume in the formation window |
| `median_close_at_formation` | REAL | for the tick-floor cost term |
| `sector` | TEXT | recorded for secondary robustness clustering, withheld from the model |

### The observation state

| field | type | meaning |
|---|---|---|
| `query_date` | TEXT | ISO date of the symbol-day queried |
| `state` | TEXT | `no_news` \| `judged` \| `model_failed` \| `source_failed` |
| `exclusion_reason` | TEXT | `''` when scored; else `no_publication_time`, `clock_inconsistent`, `symbol_did_not_trade`, `delay_rolled`, `duplicate_headline`, `day_excluded_source_failures` |

### The headline

| field | type | meaning |
|---|---|---|
| `headline` | TEXT | raw text, unmodified |
| `source_name` | TEXT | which provider served it |
| `source_article_id` | TEXT | the provider's own id, for de-duplication |
| `published_ts` | TEXT | ISO-8601 UTC, **the source's own publication time**, NULL when absent |
| `fetched_ts` | TEXT | ISO-8601 UTC, when the collector received it |
| `story_group_id` | TEXT | shared by near-identical headlines across tickers within 24h |

### The model call

| field | type | meaning |
|---|---|---|
| `model_id` | TEXT | e.g. `deepseek-v4-flash` |
| `prompt_sha256` | TEXT | hash of the exact system block, so a prompt change is detectable |
| `temperature` | REAL | 0 |
| `called_ts` | TEXT | ISO-8601 UTC |
| `latency_ms` | INTEGER | round trip, the Stage 1 latency input |
| `raw_response` | TEXT | **the model's full response text, not only the parsed verdict** |
| `judgment` | TEXT | POSITIVE \| NEGATIVE \| NEUTRAL, NULL when unparseable |
| `reason` | TEXT | the model's own justification string |
| `parse_ok` | INTEGER | 0/1 |
| `error_class` | TEXT | on failure: transport, timeout, http_status, unparseable, exhausted |
| `input_tokens` | INTEGER | |
| `cached_input_tokens` | INTEGER | so the caching claim is checkable, not assumed |
| `output_tokens` | INTEGER | |
| `cost_usd` | REAL | **cost per call**, from the recorded token counts and the recorded rate |

### Prices and outcome

Recorded at **several horizons even though only one is scored**, because
recording is free and the others enable pre-registered follow-ups without a
second collection.

| field | type | meaning |
|---|---|---|
| `anchor_kind` | TEXT | `same_session_close` \| `next_session_open` |
| `anchor_ts` | TEXT | the actionable moment after the delay |
| `anchor_price` | REAL | |
| `ret_intraday` | REAL | anchor to that session's close |
| `ret_1session` | REAL | **the scored horizon** |
| `ret_2session` | REAL | follow-up only |
| `ret_5session` | REAL | follow-up only |
| `ret_10session` | REAL | follow-up only |
| `bench_1session` | REAL | the equal-weighted band move over the scored window |
| `excess_1session` | REAL | `ret_1session - bench_1session` |
| `bar_source` | TEXT | provenance of every bar used, per the existing rule |
| `cost_bp_round_trip` | REAL | from the liquidity-aware fee model at this symbol's price and ADV |
| `net_bp` | REAL | signed excess less cost |

### Provenance of the record itself

| field | type | meaning |
|---|---|---|
| `spec_version` | TEXT | the version of THIS document the row was collected under |
| `collector_git_sha` | TEXT | so a code change mid-collection is visible |

---

## Open questions, unresolved

Listed rather than resolved optimistically.

1. **Small-cap news coverage is unverified.** No source has been checked for
   headline coverage of names at ADV 300k to 2M USD. The whole experiment
   assumes coverage exists at 0.10 headlines/symbol/day. **If real coverage is
   an order of magnitude thinner at the thin end, the strata the mechanism
   predicts most strongly are the strata with no data**, and the experiment
   measures the liquid end while claiming to measure the thin one. Stage 1 must
   measure per-stratum coverage before any scoring, and a strong coverage
   gradient across strata is itself a reason to stop.

2. **The 0.10 headlines/symbol/day arrival rate is an assumption, not a
   measurement.** The sample-size arithmetic rests on it. Stage 1 measures it.

3. **The 180 bp residual volatility and the rho = 0.05 intra-day correlation are
   assumptions.** Both feed the required sample size. Both are computable from
   the collected data and both must be recomputed before the stop rule fires.

4. **Rank drifts against ADV across the sample period** (Task 2). The proposed
   per-observation costing handles the cost side, but the SELECTION side is
   unresolved: rank 5000 in 2020 and rank 5000 in 2026 are different kinds of
   company, so pooling across years pools different populations. Whether that
   matters depends on whether the effect is a function of rank or of absolute
   liquidity, which is exactly what is not known.

5. **DeepSeek V4 Flash is not an approved model string under CLAUDE.md**
   (Task 3). Accepting this document means amending that hard rule.

6. **No provider reliability data exists for DeepSeek.** The provider-exhaustion
   work covers OpenAI, Anthropic and Gemini error shapes. DeepSeek's 429 and
   billing-error semantics are unknown, and the `model_failed` versus
   `source_failed` split assumes they are distinguishable.

7. **Short-side feasibility is untested.** The mechanism is strongest on
   NEGATIVE news, and acting on NEGATIVE means shorting. Borrow availability and
   cost in the rank 1500-5000 band are modelled nowhere in this repository, and
   the fee model has no borrow term. **The single strongest predicted case may
   be the one that cannot be traded**, leaving the POSITIVE-only subset, whose
   effect the literature places lower. This is the most consequential unresolved
   item.

8. **The benchmark's own cost is not modelled.** The unconditional band move is
   a paper quantity with no execution cost. Comparing a costed strategy against
   an uncosted benchmark is the error the buy-and-hold work already corrected
   once, and the treatment should be settled before scoring.

---

## What this document does not do

It does not authorise collection. It creates no table, collector, provider
client, or config key. It promotes, enables, and sizes nothing. Live trading is
untouched and remains off.

Stage 1 begins only if the operator accepts this proposal, and Stage 1's first
job is Open Questions 1, 2 and 7, because any of the three can end the
experiment before a single verdict is scored.

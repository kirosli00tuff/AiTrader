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

## AMENDMENT 1 — 2026-07-27, universe rule from rank to absolute ADV

**Changed:** the universe band is defined by **absolute median daily dollar
volume**, 2,070,000 to 65,300,000 USD, not by liquidity **rank** 1500 to 5000.
Strata are now fixed log-spaced ADV bins, not rank quartiles.

**Why:** Task 2 of the original draft recorded that rank is a proxy that
drifts. Rank 5000 held 310k USD ADV at the 2020 formation and 1.33M at 2026, so
the same rank sat in a 6.63 to 43.21 bp cost tier one year and a 4.87 bp tier
another. Per-observation costing fixed PRICING but not SELECTION: two
economically different companies still entered by occupying the same queue
position in different years. An absolute threshold means membership means the
same thing whenever the rule is applied, and the measurement confirms it: the
ADV band's thin end is 2,071,882 / 2,070,311 / 2,071,925 USD at the three
formations tested, while the rank band's swings 310,358 / 589,725 / 1,327,867,
a 4.3x drift.

**When:** before any collection. **No data existed at the time of this change,
so nothing was changed after seeing a result.**

**The original rank rule is preserved below under "SUPERSEDED", not deleted.
The reasoning that produced it is part of the audit trail.**

## AMENDMENT 2 — 2026-07-27, eligibility price floor derived from the tick

**Changed:** the eligibility price floor is **10.00 USD**, not 5.00.

**Why:** Amendment 1 found the maximum hurdle in every band tested was about
20.3 bp, which is exactly `100 / 5.00`, the one-cent tick at the old floor.
Dispersion is a function of PRICE, not liquidity, so no liquidity band can fix
it and the floor is the only lever. **5.00 was a convention, never a
calculation.** At 10.00 the worst-case tick cost halves to 10.00 bp and the
max-over-median dispersion falls from 5.7x to 3.2x.

**What it costs, stated because it is not free:** the floor is a partial size
filter that was not intended, and its removals are **concentrated in exactly
the population the hypothesis is about**. See "What the floor removes" below.

**When:** before any collection. **No data existed at the time of this change.**

**The 5.00 floor is preserved under SUPERSEDED, not deleted.**

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
move, for US common equities whose median daily dollar volume sits between
2,070,000 and 65,300,000 USD, by a
margin exceeding the band's round-trip cost hurdle.**

Every clause is load-bearing and a later session may not relax one:

- **three-way** — POSITIVE, NEGATIVE, NEUTRAL. Not a score, not a probability.
- **a single news headline** — headline text only, one per call.
- **only that headline and its ticker** — no price, no derived number. Task 3.
- **next-session return** — the horizon in Task 4, not one chosen later.
- **in excess of the contemporaneous cross-sectional move** — the benchmark is
  the unconditional move over the same window, never zero. Task 5.
- **ADV 2,070,000 to 65,300,000 USD** — the universe in Task 2. AMENDED
  2026-07-27 from liquidity rank 1500 to 5000, because rank is a proxy that
  drifts and an absolute band means the same thing at every formation.
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

## TASK 2 — The proposed universe rule (AMENDED, absolute ADV)

### The rule

**`U-NEWS-ADV2M-65M-stk-w60-m40-p5-s400`**

At each formation date **D**:

1. **Liquidity measure**: median daily dollar volume (`close x volume`) over
   the trailing window. Median, not mean, so one squeeze session cannot buy
   membership. Same measure `backtest/universe.py` already uses.
2. **Trailing window**: the **60 trading sessions ending the session BEFORE D**.
   The window excludes D, because a window containing the formation date
   decides membership using a bar the period it governs can trade on.
3. **Eligibility inside the window**: at least **40 of 60** bars present, median
   close at or above **10.00 USD** (AMENDED 2026-07-27 from 5.00, derived in
   "The price floor" below), and no listing-segment break.
4. **THE BAND, ABSOLUTE:** median daily dollar volume **at or above
   2,070,000 USD and at or below 65,300,000 USD**. Not a rank.
5. **Sample 400 symbols**, stratified (below).
6. **Formation schedule**: the first trading session of each calendar quarter,
   from the exchange calendar.
7. **Membership holds for the whole quarter.** A delisted name remains a member
   until it stops trading.

**Point-in-time by construction.** Only data dated strictly before D enters.

### The price floor, derived

**THE REQUIREMENT, STATED BEFORE THE CHOICE.** The floor controls exactly one
term of the hurdle, the tick's proportional cost `tick x multiple / price`. It
cannot touch the regulatory fee or the impact term, so the requirement is
stated on the quantity the lever actually controls, not on the total:

> **The TICK component of the worst-case member's round-trip hurdle must not
> exceed one third of the assumed 30 bp effect, so even the most expensive name
> in the universe keeps two thirds of it.**

One third, because the pre-registered net assumption is 25 bp from 30 gross,
implying about 5 bp of typical cost, and the median hurdle at any candidate
floor sits near 3 bp. A worst case at roughly three times the median is the
natural bound on a bad name. `100 / price <= 10` gives **price >= 10.00 USD**.

### Candidate floors, measured

ADV band 2.07M to 65.3M, 2,000 USD order, hurdle = 0.30 bp regulatory +
`100/price` tick + impact.

**2026-01-02 formation** (base n = 3,123 at the old 5.00 floor):

| floor | members | kept | max H | med H | p90 H | max/med | S4 kept | S3 | S2 | S1 | med px |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5.00 | 3,123 | 100.0% | **20.41** | 3.60 | 11.12 | **5.7x** | 100% | 100% | 100% | 100% | 31.10 |
| 7.50 | 2,943 | 94.2% | 13.71 | 3.39 | 9.12 | 4.0x | 91.5% | 92.3% | 95.9% | 97.6% | 33.13 |
| **10.00** | **2,769** | **88.7%** | **10.41** | **3.21** | **7.64** | **3.2x** | **84.2%** | **85.3%** | **90.9%** | **94.8%** | **35.32** |
| 15.00 | 2,422 | 77.6% | 7.06 | 2.87 | 5.63 | 2.5x | 70.4% | 72.6% | 79.2% | 89.0% | 39.92 |
| 20.00 | 2,132 | 68.3% | 5.41 | 2.62 | 4.56 | 2.1x | 59.2% | 63.3% | 69.2% | 82.6% | 44.49 |

**2020-01-02 formation** (base n = 2,615):

| floor | members | kept | max H | med H | max/med | S4 kept | S1 kept |
|---|---|---|---|---|---|---|---|
| 5.00 | 2,615 | 100.0% | 20.29 | 3.70 | 5.5x | 100% | 100% |
| 7.50 | 2,506 | 95.8% | 13.69 | 3.54 | 3.9x | 93.2% | 98.5% |
| **10.00** | **2,342** | **89.6%** | **10.41** | **3.34** | **3.1x** | **83.4%** | **96.2%** |
| 15.00 | 2,069 | 79.1% | 7.07 | 3.00 | 2.4x | 69.0% | 89.6% |
| 20.00 | 1,790 | 68.5% | 5.41 | 2.75 | 2.0x | 55.9% | 82.1% |

**THE CHOICE: 10.00 USD**, the smallest candidate meeting the stated
requirement. The tick component at the floor is exactly 10.00 bp, one third of
the assumed effect. Total worst-case hurdle is 10.41 bp, the extra 0.41 coming
from the regulatory fee and impact, which no price floor can reduce.

**A STRICTER READING WOULD HAVE GIVEN 15.00, AND I REJECTED IT ON THE
TRADEOFF.** Requiring the TOTAL worst-case hurdle under 10 bp fails 10.00 by
0.41 bp and selects 15.00. That reading makes the floor responsible for the
regulatory fee, which it cannot change, and it costs **30 percent of S4**, the
thinnest ADV stratum and the one where the mechanism is strongest. Accepting a
0.41 bp worse worst case to keep 14 points of the study population is the right
trade, and it is recorded rather than buried.

### What the floor removes, and it is not uniform

**MARKET CAP CANNOT BE COMPUTED. Stated plainly rather than approximated.**
`analysis_bars.db` holds no shares outstanding and no market capitalisation:
`universe_asset` carries symbol, name, exchange, fund classification, bar
counts and provenance, and nothing about size. **So the market-cap distribution
of what the floor removes is unavailable, and any figure claiming otherwise
would be invented.** What IS measurable is the question that actually matters,
whether removal concentrates in the thin ADV strata, and it does:

| floor | S4 (thinnest) kept | S1 (most liquid) kept | concentration |
|---|---|---|---|
| 7.50 | 91.5% | 97.6% | 3.5x more removal in S4 |
| **10.00** | **84.2%** | **94.8%** | **3.0x more removal in S4** |
| 15.00 | 70.4% | 89.0% | 2.7x more removal in S4 |
| 20.00 | 59.2% | 82.6% | 2.3x more removal in S4 |

**The floor is a partial size filter that was not intended, exactly as
anticipated.** Cheap and thinly traded correlate, so every candidate removes
more from the thin end than the liquid end. At 10.00 the removal is 15.8
percent of S4 against 5.2 percent of S1.

**DOES THE GRADIENT SURVIVE? Yes, at 10.00.** All four strata retain 84 percent
or more, every stratum keeps at least 660 members against the 100 the sample
draws, and the ordering of both the hurdle and the liquidity gradient is
unchanged. **At 20.00 it would not survive intact**: S4 falls to 59.2 percent,
and a stratum that has lost 41 percent of its members to a price filter is no
longer the population the hypothesis names.

**THE HONEST RESIDUAL:** even at 10.00 the study population is 15.8 percent
smaller at the thin end than the mechanism would want, and that removal is not
random with respect to the hypothesis. It buys a halving of dispersion. **If a
later reading decides the mechanism matters more than the dispersion, the
correct response is to lower the floor and accept the worse hurdle, not to keep
10.00 and stop reporting the tradeoff.**

### The thresholds, derived

Three constraints, each shown.

**COST fixes the LOWER bound at 2,070,000 USD.** That is the measured tier-4
ADV floor from the 2026-07-27 liquidity calibration. Against a 30 bp working
effect:

| tier | ADV floor | hurdle floor (median) | p90 name | verdict |
|---|---|---|---|---|
| 3 | 13,300,000 | 3.15 bp | 10.14 | room |
| 4 | 2,070,000 | 4.87 bp | 22.63 | room |
| 5 | 235,000 | 6.63 bp | **42.64** | **p90 drowns a 30 bp effect** |
| 6 | below | **43.21 bp** | 652.72 | dead outright |

Tier 5's median survives and its p90 does not, so a band reaching into tier 5
admits names whose individual hurdle exceeds the effect. The lower bound is the
tier-4 floor exactly, unrounded, because rounding down to 2,000,000 would admit
a sliver of tier 5 for legibility, which is the wrong trade.

**MECHANISM fixes the UPPER bound at 65,300,000 USD**, the measured tier-2
floor. Cost is not the binding consideration here: tier 2 is cheaper, at 1.79
bp. The binding consideration is that the documented effect concentrates in
smaller stocks through delayed diffusion and limits to arbitrage, so admitting
tier 2 and above would test the population where the mechanism is weakest and
dilute the very gradient the secondary test looks for. The band is therefore
tiers 3 and 4 in full, and nothing above.

**ORDER SIZE is not binding anywhere in the band**, checked rather than
assumed. At the 2 percent sizer a position is about 2,000 USD:

```
at the lower bound  2,000 / 2,070,000  = 0.097 % of ADV
at the upper bound  2,000 / 65,300,000 = 0.003 % of ADV
1 % participation would need ADV = 200,000
```

**200,000 USD is a tenth of the lower bound**, so the cost constraint already
excludes everything the order-size constraint would have. Participation across
the whole band is at most 0.097 percent, an order of magnitude below any
impact concern. Recorded so a later session does not re-derive it.

### What the amended rule yields, measured

Read-only against `analysis_bars.db`, three formations, both rules:

| | 2020-01-02 | 2023-01-03 | 2026-01-02 |
|---|---|---|---|
| eligible pool | 7,844 | 8,964 | 9,999 |
| **rank band members** | 3,501 | 3,501 | 3,501 |
| **ADV band members** | **2,615** | **2,898** | **3,123** |
| rank thin end ADV | 310,358 | 589,725 | 1,327,867 |
| **ADV thin end** | **2,071,882** | **2,070,311** | **2,071,925** |
| rank liquid end ADV | 21,108,236 | 30,599,824 | 59,716,980 |
| **ADV liquid end** | **65,121,547** | **65,139,698** | **65,270,836** |
| overlap, % of rank band | 53.4 | 67.2 | **87.3** |
| overlap, % of ADV band | 71.5 | 81.1 | **97.8** |
| worst participation, rank | 0.644 % | 0.339 % | 0.151 % |
| **worst participation, ADV** | **0.097 %** | **0.097 %** | **0.097 %** |
| membership retained to next formation, rank | 62.8 % | 60.3 % | |
| membership retained to next formation, ADV | 68.5 % | 61.7 % | |

**WHAT CHANGES, AND IT IS LESS THAN IT LOOKS AT THE CURRENT FORMATION.** At
2026 the two rules select substantially the same names: **97.8 percent of the
ADV band sits inside the rank band, with only 68 ADV-only symbols against 446
rank-only.** **At the current formation this amendment buys interpretability,
not a different study**, and that is stated plainly because it is the honest
reading. What it changes is the PAST and the FUTURE: at 2020 the overlap falls
to 53.4 percent of the rank band, because the rank band's thin end reached to
310k USD ADV, deep in tier 5 and 6.

**WHAT DOES NOT CHANGE:** the count is no longer fixed. Rank guarantees 3,501
members by construction; ADV yields 2,615 to 3,123 as market conditions move.
That is the trade taken deliberately: **a constant economic meaning with a
varying count, rather than a constant count with a varying meaning.** The
sample of 400 is unaffected, since even the smallest band is six times it.

### Cost dispersion, resolved by Amendment 2 rather than by the band

The recorded fallback condition was that a wide cost dispersion swamping the
effect would make a pooled result uninterpretable. Measured, at a 2,000 USD
order:

| | rank band | ADV band |
|---|---|---|
| hurdle median | 3.82 - 5.06 bp | 3.60 - 3.87 bp |
| hurdle p90 | 11.25 - 12.95 bp | 10.51 - 11.23 bp |
| hurdle max | 20.72 - 20.99 bp | 20.29 - 20.41 bp |
| **max / median** | **4.1x - 5.4x** | **5.2x - 5.7x** |

**The ADV band did not reduce dispersion. It was marginally worse.** The reason
redirected the fix: **the maximum hurdle in BOTH bands was about 20.3 bp,
exactly `100 / 5.00`, the tick at the old eligibility price floor.** Dispersion
is driven by PRICE through the one-cent tick, not by liquidity, so an ADV band
cannot fix what ADV does not cause.

**AMENDMENT 2 MADE THAT FIX.** At the 10.00 floor the worst-case hurdle falls
from 20.41 to 10.41 bp and max/median from 5.7x to 3.2x, roughly halving both.
The figures in the table above are at the OLD 5.00 floor and are retained to
show what the band alone did and did not achieve.

### What a news source must cover

- **400 US-listed common equities per quarter**, sampled from a band of **2,342
  to 2,769** at the 10.00 floor, depending on the formation (2,615 to 3,123 at
  the superseded 5.00 floor).
- Thin end at 2.07M USD ADV, median price about **35 USD** at the 10.00 floor
  (was about 31 at the 5.00 floor). Small and mid caps, not an S&P list.
- Per-headline publication timestamp at minute resolution or better.
- Roughly 400 symbol-day queries per trading day, under 7 minutes against the
  integrated Finnhub 60/minute free tier.

Coverage at the thin end remains unverified and is Open Question 1. The band's
thin end is now **6.7x more liquid than under the rank rule at the 2020
formation** (2.07M against 310k), which makes adequate coverage more likely,
not less, and narrows but does not close that question.

### Size arithmetic

Unchanged by the amendment, and shown again so no section describes the old
rule. 400 symbols is the sample; the band is the population it is drawn from.

```
400 symbols x 0.10 headlines/symbol/day  =  40 headlines/day   ASSUMPTION
40/day x 60 trading days                 =  2,400 raw
x 0.75 surviving delay and hygiene       =  1,800 scorable
1,800 >= 1,000 required                  ->  clears with 80% margin
```

Collection runs until BOTH 1,000 scorable observations AND 60 day-clusters are
met, hard stop 120 trading days.

### The stratified sample, restratified (AMENDED)

**Four strata of EQUAL WIDTH IN LOG ADV, with FIXED thresholds.**

| stratum | ADV range (USD) | 2020 n | 2026 n | retained by the 10.00 floor |
|---|---|---|---|---|
| S1 | 27,553,544 - 65,300,000 | 525 | 706 | 96.2% / 94.8% |
| S2 | 11,626,306 - 27,553,544 | 633 | 707 | 91.5% / 90.9% |
| S3 | 4,905,757 - 11,626,306 | 622 | 663 | 88.5% / 85.3% |
| S4 | 2,070,000 - 4,905,757 | 562 | 693 | 83.4% / 84.2% |

Counts are AFTER the 10.00 floor (Amendment 2). At the superseded 5.00 floor
they were 546/692/703/674 in 2020 and 745/778/777/823 in 2026. **Every stratum
retains at least 660 members against the 100 the sample draws**, so the floor
does not threaten stratified sampling at any formation tested.

**100 symbols sampled per stratum**, uniform at random within a stratum, seeded
deterministically from `sha256(rule_id + formation_date)`. 400 total.

**WHY LOG WIDTH AND NOT THE OTHER TWO.**

- **Equal width in ADV is wrong** because ADV is heavily right-skewed. Splitting
  2.07M to 65.3M into four linear bins puts most of the band in the bottom bin
  and leaves the top bin nearly empty, so three strata would carry almost no
  names and the gradient test would have nothing to compare.
- **Equal COUNT is wrong for the same reason the rank rule was wrong.** Its
  boundaries move at every formation, so stratum S4 in 2020 and S4 in 2026 would
  be different economic populations, and a gradient measured across formations
  would confound the gradient with the drift. **Adopting equal-count strata
  inside an absolute band would reintroduce, one level down, exactly the defect
  this amendment removes.**
- **Equal width in LOG ADV is correct.** The boundaries are fixed constants, so
  a stratum means the same thing at every formation. Log spacing matches how
  liquidity is actually distributed and how the measured impact tiers are
  themselves spaced (235k, 2.07M, 13.3M, 65.3M, 277M is approximately
  log-uniform). **And it happens to produce near-equal counts anyway**, 546 to
  703 in 2020 and 745 to 823 in 2026, so it buys the balance equal-count would
  have given without buying its drift.

**The gradient the strata must express:** the mechanism predicts the effect is
strongest in S4 and weakest in S1. The hurdle runs the other way, 4.50 bp in S4
against 2.73 bp in S1, so the NET effect after cost is what the pre-registered
thin-end test (strata S3 and S4) measures.

### SUPERSEDED — the 5.00 USD price floor

The draft and Amendment 1 both used a **5.00 USD** median-close floor, inherited
from `backtest/universe.py`'s `MIN_MEDIAN_CLOSE`. It was a penny-stock
convention, never derived. At 5.00 the one-cent tick costs 20.00 bp on the
cheapest eligible name, which is **two thirds of the entire assumed effect**,
and it set the maximum hurdle in every band tested.

**Why it was replaced:** it was never chosen against a requirement. Amendment 2
states the requirement (the tick component of the worst case must not exceed one
third of the effect) and derives 10.00 from it.

**What would make 5.00 correct again:** evidence that the effect is
concentrated in 5 to 10 USD names strongly enough to outweigh a doubled tick
cost. That is measurable once data exists, by scoring the excluded 5-to-10 band
separately, and `median_close_at_formation` is recorded so the check stays
available.

### SUPERSEDED — the original rank rule, kept for the audit trail

The draft of 2026-07-27 defined the band as **`U-NEWS-1500-5000-stk-w60-m40-p5-s400`**:
ranks 1500 through 5000 by median daily dollar volume, ties on symbol ascending,
with four equal-width rank strata of 875 ranks each (S1 1500-2374, S2 2375-3249,
S3 3250-4124, S4 4125-5000). Its reasoning was that ranks 1500-5000 carried a
3.15 to 4.87 bp hurdle against a tens-of-basis-points effect and sat in genuine
small-cap territory.

**Why it was replaced:** that reasoning was sound about COST and wrong about
STABILITY. It priced the band from a single 2025-07 to 2026-07 calibration
window and assumed the mapping held at other formations. It does not. The draft
recorded the problem itself and proposed per-observation costing, which prices
each name correctly but still lets the selection drift.

**Per-observation costing is RETAINED regardless of the band definition**, since
a symbol's own ADV and price price it more accurately than any band average.

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
Defined as the **equal-weighted mean return of every eligible ADV-band member that
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
reason in Task 2. For orientation the band's tier floors are **3.15 bp** (tier 3, ADV at or
above 13.3M) and **4.87 bp** (tier 4, ADV 2.07M to 13.3M), and every such
figure is a floor assuming a one-tick market. Per-observation costing is
retained: each fill is priced from its OWN ADV and price.

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
  3. **thin-end** subset, strata S3 and S4 (ADV 2.07M to 11.63M),
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
| `risk.max_trade_notional_cap_pct` | 0.05 | **CORRECTED 2026-07-27: UNENFORCED. This row was wrong.** The key is parsed, range-validated, and read by no consumer anywhere. The real per-trade ceiling is `max_trade_risk_pct_of_equity` at `risk_gate.cpp:43`. |
| `sizing.default_risk_per_trade_pct` | 0.005 | what the **sizer actually sends**: 500 USD base. **RAISED to 0.02 on 2026-07-27, so the capacity arithmetic below is superseded: at 2,000 USD per position the required edge falls from 19.8 bp to 4.96 bp.** |
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
| `adv_usd_at_formation` | REAL | median daily dollar volume at formation, 2.07M to 65.3M. **The band variable.** |
| `liquidity_rank` | INTEGER | rank at formation. Recorded but NOT the band variable, so the superseded rank rule stays scoreable as a pre-registered robustness check. |
| `stratum` | TEXT | S1 \| S2 \| S3 \| S4 |
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

4. **RESOLVED BY AMENDMENT 1: rank drift.** The band is now absolute, so a
   member means the same thing at every formation (thin end 2,071,882 /
   2,070,311 / 2,071,925 across the three tested). **What replaced it is
   narrower and still open: cost DISPERSION is unresolved and the amendment
   does not touch it.** Max/median hurdle is 5.2x to 5.7x in the ADV band,
   marginally worse than the rank band's 4.1x to 5.4x, because the maximum
   hurdle in both is about 20.3 bp, which is `100 / 5.00`, the tick floor at
   the eligibility price floor. **Dispersion is driven by PRICE, not
   liquidity. ADDRESSED BY AMENDMENT 2**, which derived a 10.00 floor and
   halved both figures, to a 10.41 bp worst case and 3.2x dispersion. **Not
   eliminated**: the Reg NMS tick is one cent above 1.00 USD, so the worst
   member always pays `100/floor` bp and only a higher floor reduces it, at a
   measured cost in the thin strata.

5. **DeepSeek V4 Flash is not an approved model string under CLAUDE.md**
   (Task 3). Accepting this document means amending that hard rule.

6. **No provider reliability data exists for DeepSeek.** The provider-exhaustion
   work covers OpenAI, Anthropic and Gemini error shapes. DeepSeek's 429 and
   billing-error semantics are unknown, and the `model_failed` versus
   `source_failed` split assumes they are distinguishable.

7. **Short-side feasibility is untested.** The mechanism is strongest on
   NEGATIVE news, and acting on NEGATIVE means shorting. Borrow availability and
   cost in the 2.07M to 65.3M ADV band are modelled nowhere in this repository, and
   the fee model has no borrow term. **The single strongest predicted case may
   be the one that cannot be traded**, leaving the POSITIVE-only subset, whose
   effect the literature places lower. This is the most consequential unresolved
   item.

8. **The benchmark's own cost is not modelled.** The unconditional band move is
   a paper quantity with no execution cost. Comparing a costed strategy against
   an uncosted benchmark is the error the buy-and-hold work already corrected
   once, and the treatment should be settled before scoring.

---

## What would have made RANK the better choice

Recorded so the decision is auditable rather than merely made.

**Rank would have been correct if the hypothesis were about relative position
in the liquidity distribution rather than about absolute tradeability.** If the
mechanism were "the effect lives in whatever is currently the 1500th to 5000th
most liquid name, because that is where institutional attention thins out",
then rank IS the economic variable and holding it fixed is right, while an
absolute band would drift against the thing that matters as the whole market
grew more liquid. Attention and coverage are plausibly relative quantities, so
this is not a strawman.

**Two things decided against it.** First, the cost hurdle that gates the whole
experiment is a function of absolute ADV and absolute price, not of rank, so
the constraint the design must respect is stated in absolute terms. Second, the
literature's mechanism is stated in terms of firm size and analyst coverage,
which are absolute, not in terms of position in a queue.

**What would reverse the amendment:** evidence that the effect tracks rank
better than ADV. That is measurable once data exists, by scoring the same
observations under both memberships, and it is not measurable now.

## What AMENDMENT 2 (the price floor) does NOT fix

1. **Dispersion is halved, not removed.** Max/median falls from 5.7x to 3.2x
   and the worst case from 20.41 to 10.41 bp. The residual is structural: the
   Reg NMS minimum increment is one cent for any equity above 1.00 USD, so the
   worst member always pays `100 / floor` bp and the only lever is a higher
   floor, which costs thin-strata membership at a measured rate.

2. **No driver of dispersion exists beyond price and liquidity INSIDE the
   model, and that is the problem.** The hurdle is regulatory (a constant) plus
   tick over price plus impact over ADV and size, so within the model the floor
   and the band together bound it. **Outside the model two drivers are
   unmodelled**: the actual quoted spread when it exceeds one tick (below), and
   borrow cost on the short side, which the fee model has no term for and which
   falls hardest on exactly the thin names the mechanism names.

3. **THE TICK MULTIPLE IS MULTIPLICATIVE WITH THE FLOOR, AND IT IS THE ONE
   NUMBER THAT COULD INVALIDATE THIS.** Every hurdle figure assumes a ONE-TICK
   market. The calibration recorded the real multiple as unmeasurable without
   paid quote data. Because the tick term is `multiple x 100 / price`, the
   floor and the multiple scale each other exactly:

   | market width | worst case at 5.00 | at 10.00 | at 15.00 |
   |---|---|---|---|
   | 1 tick | 20.4 bp | **10.4 bp** | 7.1 bp |
   | 2 ticks | 40.4 bp | 20.4 bp | 13.7 bp |
   | 3 ticks | **60.4 bp** | **30.4 bp** | 20.4 bp |

   **At three ticks the 10.00 floor leaves the worst member with zero net
   effect**, since 30.4 bp consumes the entire 30 bp assumption. The floor
   improves the multiple's damage proportionally and does not make the design
   robust to it. **Measuring the multiple is worth more than any further floor
   increase**, and it remains the single highest-value unresolved input.

4. **The removal is not random with respect to the hypothesis.** 15.8 percent
   of S4 against 5.2 percent of S1. The study population is smaller at the end
   where the effect is claimed to live.

5. **Market cap was not measurable**, so the size question is answered by an
   ADV-stratum proxy rather than directly. If shares outstanding become
   available, the removal analysis should be redone against actual market cap.

## What AMENDMENT 1 (rank to ADV) does NOT fix

Stated so nobody reads a resolved question into it.

1. **Cost dispersion, which is if anything slightly worse.** Driven by price
   through the tick floor, not by liquidity. See Open Question 4.
2. **The count is no longer fixed**, 2,615 to 3,123 across the formations
   tested. Sampling 400 is unaffected, but any future test that assumes a
   constant population size is not.
3. **Coverage at the thin end is still unverified.** The thin end is 6.7x more
   liquid than the rank rule's at 2020, which makes coverage more likely, but
   the question is narrowed rather than closed.
4. **Short-side feasibility is untouched**, and remains the most consequential
   open item. An absolute band says nothing about borrow.
5. **The thresholds themselves inherit the calibration's limits.** They are the
   measured tier floors from one 2025-07 to 2026-07 window. If the tier
   boundaries are re-measured and move, these thresholds must move with them or
   the band stops meaning what it was derived to mean.
6. **At the current formation this changes almost nothing empirically**, 97.8
   percent overlap. The benefit is interpretability across time, not a
   different study today.

## What this document does not do

It does not authorise collection. It creates no table, collector, provider
client, or config key. It promotes, enables, and sizes nothing. Live trading is
untouched and remains off.

Stage 1 begins only if the operator accepts this proposal, and Stage 1's first
job is Open Questions 1, 2 and 7, because any of the three can end the
experiment before a single verdict is scored.

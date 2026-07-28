# EXPERIMENT.md — News-drift pre-registration

> **STATUS: ACCEPTED BY THE OPERATOR 2026-07-28. BINDING AND CLOSED.**
>
> **Acceptance came BEFORE any collection.** No headline had been scored
> against a price, no observation row existed, and no number in this document
> had been informed by an outcome. That ordering is what makes this a
> pre-registration rather than a description.
>
> **FROM THIS POINT THE SPECIFICATION IS CLOSED.** A later session implements
> it and does not revise it. Where the specification and reality disagree, or
> where the document contradicts itself, the session **reports and stops**
> rather than choosing: a specification that gets quietly adjusted during
> implementation is not a pre-registration, and the adjustment is always in the
> direction that makes the work easier.
>
> Changing anything here now requires a NEW amendment, dated, with its reason,
> and with a statement of what data existed at the time. The three amendments
> below were all made before acceptance and before any data existed.
>
> **Known disagreements found during stage 2 implementation and reported
> rather than resolved:** the rule id string encodes `p5` while Amendment 2
> derived a 10.00 floor; Task 4 scores a delay-rolled headline while Task 8
> lists `delay_rolled` as an exclusion reason; and Task 7's four states do not
> cover a headline excluded before any model call. Each is recorded at its
> site.
>
> This document was a proposed pre-registration written by Stage 0.
>
> Written 2026-07-27. Nothing was built, collected, called, or traded to
> produce it. The only computation performed was read-only queries against
> `analysis_bars.db` to check that the proposed universe rule yields a
> workable membership.
>
> Amendment 3 (2026-07-28) performed **no computation of any kind**: no
> provider was called, no database was read, and no data existed to see.

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

## AMENDMENT 3 — 2026-07-28, the model becomes Claude Haiku 4.5, and a recorded strength field

**Changed, two things.**

1. **The scoring model is `claude-haiku-4-5`**, not DeepSeek V4 Flash.
2. **The response gains a third field, `strength`, an integer 1 to 5 with both
   endpoints anchored in the prompt text. It is RECORDED on every observation
   and GATES NOTHING.**

**WHY THE MODEL CHANGED.** Stage 1 fixed its comparison set before seeing any
result and found that **DeepSeek V4 Flash has no credential in the keystore and
was never tested at all**. Haiku parsed 21 of 21 at temperature zero, returned a
directional verdict on 52.4 percent, and cost $0.000403 per call. **The reason
DeepSeek was named was cost, and cost no longer decides anything**: at the
measured arrival rate the whole collection phase is about **$4.01 on Haiku
against $0.31 on DeepSeek**, a difference of **$3.69** against the 15.00 USD
ceiling Stage 1 ran under. A 13x price ratio on a four-dollar bill is not a
reason to run an untested model behind a credential that does not exist.

**WHAT DID NOT DECIDE IT, stated because the distinction matters.** No claim is
made that Haiku judges better than DeepSeek, or than any other model. Stage 1
produced one usable arm out of four, so the capability question is still open
and is recorded as open. Haiku is chosen because it is **reachable, already
approved, mechanically well-formed at temperature zero, and cheap enough that
cost is not a constraint** — not because it won a comparison that did not
happen.

**THE HARD-RULE CONFLICT IS CLOSED, NOT AMENDED AROUND.** The draft reported a
conflict and refused to resolve it silently: CLAUDE.md names four approved model
strings and DeepSeek V4 Flash is not among them, so accepting the document would
have meant amending a hard rule. **`claude-haiku-4-5` is already one of those
four**, listed as the base-check gate model sharing `ANTHROPIC_API_KEY`.
Choosing it **removes the conflict rather than granting an exception**: no hard
rule is amended, no fifth model string is introduced, and no credential has to be
created. Open Question 5 is closed on that basis, which is a better outcome than
the amendment the draft anticipated.

**WHY THE STRENGTH FIELD.** The judgment is three-way and carries no magnitude,
so every scored observation currently weighs the same whether the headline is a
takeover offer or a routine reiteration. Strength records the model's own read of
how hard the headline points, at a resolution the model can actually hold, and it
makes the calibration question answerable at Stage 4 from data already collected
rather than from a second collection. **It changes no primary test, and it is not
part of the hypothesis.**

**WHEN:** before any collection. **No data existed at the time of this change, so
nothing was changed after seeing a result.** The one measured input, the Stage 1
comparison, measured **parse rate and cost**, not outcomes: no headline in this
experiment has ever been scored against a price.

**The DeepSeek model, its pricing, its cost arithmetic, and the two-field prompt
are preserved under SUPERSEDED in Task 3, not deleted.**

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
  **AMENDMENT 3 added a recorded `strength` field and it is NOT part of this
  clause.** The hypothesis is still about the three-way sign; strength gates
  nothing, no primary test uses it, and its own tests are secondary and are
  labelled so. Task 3 defines it, Task 5 tests it.
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

**THE 0.10 ASSUMPTION ABOVE IS SUPERSEDED BY MEASUREMENT AND IS KEPT ONLY TO
SHOW WHAT THE DESIGN WAS SIZED ON.** Stage 1 measured **0.359 per symbol-day**,
so 60 day-clusters rather than 1,000 observations is the binding stop and the
sample is over-powered about 6.5x. Open Question 2 records that; **Task 3's cost
projection uses the MEASURED rate, not the assumption on this page.**

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

### The model (AMENDED, Claude Haiku 4.5)

**`claude-haiku-4-5`**, temperature **0**, `max_tokens` 60.

**NO HARD RULE IS AMENDED.** `claude-haiku-4-5` is already one of the four
approved model strings in CLAUDE.md, listed as the base-check gate model sharing
`ANTHROPIC_API_KEY`. The conflict the draft reported is **closed by removal**
rather than by exception: no fifth model string, no rule change, no new
credential. Open Question 5 records that.

### Request shape

**`temperature: 0` is CONFIRMED acceptable on this model.** CLAUDE.md records
that `claude-haiku-4-5` accepts `temperature: 0` normally, and Stage 1 exercised
it across 21 calls with zero request errors. **No replacement is needed and none
is proposed.**

**THE QUIRK THAT COST STAGE 1 AN ARM IS RECORDED IN CLAUDE.md AND IS NOT THIS
MODEL'S.** Stage 1 sent `temperature: 0` to `claude-opus-4-8` and every call
returned `HTTP 400 invalid_request_error, "temperature is deprecated for this
model"` — the same shape CLAUDE.md already recorded for the OpenAI GPT-5 family,
which is why the Opus column read 100 percent parse-fail when the model had in
fact never been reached. That is now a hard rule in CLAUDE.md so a later session
does not lose calls to it. **It does not apply to Haiku 4.5**, a different model
generation with the sampling parameters intact.

**`max_tokens` 60 stands.** The amended response is about 35 tokens, so 60 leaves
headroom without permitting a runaway. Haiku 4.5's output ceiling is 64K, so 60
is nowhere near a limit.

### Caching, and THE LAYOUT DOES NOT SATISFY THE REQUIREMENT

**REPORTED PLAINLY: this prompt cannot be cached on this model, and re-ordering
will not fix it.** The layout was designed against DeepSeek's semantics, and the
question is whether it survives Anthropic's.

Anthropic's prompt cache is a **prefix match** with three requirements:

1. **A minimum cacheable prefix, and it is MODEL-SPECIFIC.**
   `claude-haiku-4-5` requires **4,096 tokens**. Below that the prefix silently
   does not cache: no error is raised and `cache_creation_input_tokens` comes
   back 0.
2. **A byte-identical prefix.** Any change anywhere before the breakpoint
   invalidates everything after it. Render order is `tools`, then `system`, then
   `messages`.
3. **At most four `cache_control` breakpoints per request**, each on a content
   block.

**Requirements 2 and 3 are satisfied. Requirement 1 is not, and it is the one
that decides.** The system block is byte-identical on every call, the ticker and
headline are the only variable content and sit last in the user message, and one
breakpoint is all the design needs. **But the system block is about 270 tokens
against a 4,096-token minimum, roughly 15x too short to cache at all.**

**PADDING TO REACH THE MINIMUM IS STRICTLY WORSE, checked rather than assumed.**

```
uncached, as designed:
  290 input x $1.00/1M  +  35 output x $5.00/1M              = $0.000465

padded to 4,096 tokens and cached, per read:
  4,096 x $0.10/1M + 20 x $1.00/1M + 35 x $5.00/1M           = $0.000605
```

Padding costs **30 percent more per call**, on top of adding 3,800 tokens of
filler the model has to read on every judgment. **The prompt stays short and
uncached. The cached-case arithmetic below is recorded for completeness and as a
figure that will not occur.**

**CONSEQUENCE FOR THE SCHEMA, and it turns a dead column into a live one.**
`cached_input_tokens` (Task 8) is expected to be **0 on every row**. A nonzero
value there means the prompt has grown past 4,096 tokens without anyone
noticing, so the field is a **canary for prompt drift** rather than a check on a
caching claim.

### Pricing and cost per call (AMENDED)

Published rates for `claude-haiku-4-5`:

| | per 1M tokens |
|---|---|
| input | $1.00 |
| output | $5.00 |
| cache read (0.1x input) | $0.10 |
| cache write, 5-minute TTL (1.25x input) | $1.25 |

**THE TOKEN COUNTS ARE ESTIMATES AND ARE LABELLED SO, because no provider was
called to produce this document.** The one thing that IS measured is the
character count: the amended system block is **1,232 characters** against the
superseded block's **824**, a factor of **1.495**, counted off this file. At the
superseded document's own ~180-token estimate that puts the amended block at
about **270 tokens**. The user block is unchanged at about **20**. The response
gains `"strength": N, ` and goes from about 30 to about **35**. **The
character-to-token ratio is carried over from the superseded estimate and is not
itself measured**, so a real token count could move these by ten percent either
way without surprising anyone.

```
UNCACHED, which is the case that will occur:
  input   290 x $1.00/1M  = $0.000290
  output   35 x $5.00/1M  = $0.000175
  per call                = $0.000465

CACHED READ, recorded for completeness, unreachable at this prompt size:
  cached prefix 270 x $0.10/1M = $0.000027
  uncached user  20 x $1.00/1M = $0.000020
  output         35 x $5.00/1M = $0.000175
  per call                     = $0.000222

CACHE WRITE, first call, 5-minute TTL, also unreachable:
  270 x $1.25/1M + 20 x $1.00/1M + 35 x $5.00/1M = $0.000533
```

**RECONCILED AGAINST THE ONE MEASURED FIGURE, and the estimate is optimistic.**
Stage 1 recorded **$0.000403 per call** for Haiku on the superseded two-field
prompt. The same arithmetic on the superseded token estimates gives
`200 x $1.00/1M + 30 x $5.00/1M = $0.000350`, **13 percent below the
measurement**. The residual is in the token estimate, not the rate: $0.000403 is
consistent with roughly 250 input and 30 output, or with 200 input and 40
output, and Stage 1 did not report the split. **So every projection below carries
an estimate that ran about 15 percent light on the one case that was measured.**

### The projected total for the collection phase, at the MEASURED arrival rate

Stage 1 measured **0.359 headlines per symbol per trading day**, pooled, against
the pre-registration's assumed 0.10.

```
400 symbols x 0.359            = 143.6 headlines/day, RAW
143.6 x 0.75 surviving filters = 107.7 scorable/day
60 day-clusters is the BINDING stop, not the 1,000 observations
```

**Two figures, because the model is called on HEADLINES and not on SCORABLE
OBSERVATIONS**, and the two differ by the 25 percent that delay, hygiene and
de-duplication remove:

| basis | calls | at the amended $0.000465 | at the measured $0.000403 |
|---|---|---|---|
| scorable only, 60 days | 6,462 | **$3.01** | $2.60 |
| **every raw headline, 60 days** | **8,616** | **$4.01** | $3.47 |
| every raw headline, 120-day hard stop | 17,232 | **$8.01** | $6.95 |

**$4.01 IS THE FIGURE TO PLAN AGAINST**: 60 day-clusters at the raw arrival
rate, at the amended prompt's estimated cost. **$8.01 is the ceiling**, if
collection runs to the 120-day hard stop. The $2.60 in the amending prompt is
the bottom-left cell, scorable-only calls at the superseded prompt's measured
cost, and it is the most optimistic of the six.

**AGAINST THE ASSUMED RATE the pre-registration used**, 1,800 scorable
observations at $0.000465 is **$0.84**, so measuring the arrival rate raised the
projected bill about **3.6x** — and it is still not a constraint at any figure in
the table.

Cost is not a constraint at any plausible sample size. That is itself a reason
to record cost per call anyway (Task 8): a figure nobody checks is how the 25x
crypto fee error survived.

### The strength field, and why five points anchored at both ends

**FIVE POINTS, NOT TEN.** A model does not distinguish ten levels consistently
on a subjective judgment. It clusters on the round numbers and on the ends, so
the extra resolution corresponds to nothing real while the analysis inherits
buckets that look like measurements. Five is the smallest scale that expresses
"barely", "moderately" and "strongly" with one step on each side of the middle,
and at about 1,000 scored observations five buckets already run near 200 each
before any of them is thin.

**BOTH ENDPOINTS ARE ANCHORED IN THE PROMPT TEXT, AND THAT IS THE LOAD-BEARING
PART.** An unanchored number lets the model invent its own meaning per call, so
the same integer means different things on different headlines and the column
carries noise dressed as a scale. **This project has already paid for exactly
that**: the LLM council's self-reported confidence carried no information at all,
with every provider's individual correlation against outcomes negative. Anchoring
gives every call the same two reference points.

**THE EXACT WORDING:**

```
1 means the headline barely tilts the odds, and a move the other way would not surprise you.
5 means you would be surprised if this stock did not move in the stated direction by the next close.
```

Three choices inside that wording, each stated so a later session does not
re-litigate it:

- **Both anchors are framed as SURPRISE, not as probability or confidence.** A
  probability anchor ("1 means about 55 percent") invites a calibrated-sounding
  number the model has no basis for, and this experiment already declined to ask
  for a probability in the primary judgment for that reason. Surprise is a
  judgment a model can actually make from a headline.
- **The anchors are SYMMETRIC about the direction already chosen.** 1 says a
  move the other way would not surprise; 5 says no move this way would surprise.
  They bound one axis from its two ends rather than describing two things.
- **The horizon is repeated in the 5 anchor.** "by the next close" appears in
  the judgment definitions and again here, because a strength judged over an
  unstated horizon is a different quantity from the one being scored.

**THE MIDDLE IS DELIBERATELY THIN.** `2, 3 and 4 fall between those two points.`
is all the prompt says. Defining three intermediate levels in prose would add
wording the model has to reconcile against the endpoints, and the endpoints are
what make the scale comparable across calls. Whatever the middle values mean
beyond "between" is the model's, **which is why the secondary test in Task 5 is a
RANK test and not a regression on the numeric value**: the scale is treated as an
ordering, never as an interval.

### What strength means for a NEUTRAL judgment

**DECIDED: strength is FIXED at 1 when the judgment is NEUTRAL, it is recorded
exactly as returned, and it is used for nothing.**

The anchors are written in terms of "the direction you chose". **NEUTRAL has no
direction, so neither anchor applies, and any number the model produces there is
unanchored** — precisely the defect the anchors exist to remove. A strength on a
NEUTRAL call is not a weak measurement. It is a measurement of nothing.

Three options were considered:

| option | verdict |
|---|---|
| **omit the field on NEUTRAL** | rejected. The response shape becomes variable, the parser gains a branch, and a deliberately absent field can no longer be told apart from one the model failed to emit. |
| **give it a second meaning on NEUTRAL**, e.g. confidence that the headline is genuinely non-directional | rejected. That is a different quantity in the same column, and one column holding two scales is unanalysable without a third column saying which. |
| **FIX IT AT 1** | **CHOSEN.** |

Fixing it at 1 keeps the response shape constant, keeps the parser at one branch,
and makes the recorded value carry no information **by construction rather than
by accident**. NEUTRAL rows are already excluded from scoring (Task 5), so a
consumer filters on `judgment` exactly as it already must.

**A NEUTRAL ROW WHOSE STRENGTH IS NOT 1 IS RECORDED AS RETURNED AND COUNTED,
NEVER DISCARDED.** It is evidence the model did not follow the format, which is
worth knowing, and it is reported in the daily coverage summary. **It is NOT a
parse failure**, because `model_failed` has to keep its one meaning of "the model
never considered this headline" (Task 7).

### When strength itself does not parse

**A BAD STRENGTH NEVER DISCARDS A GOOD JUDGMENT.** If `judgment` parses and
`strength` is missing, non-integer, or outside 1 to 5, the row is recorded with
the judgment intact, `strength` NULL, and `strength_parse_ok = 0`. Strength gates
nothing, so letting it invalidate the primary field would trade the measurement
for the diagnostic. **The reverse does not hold**: if `judgment` does not parse
the row is `model_failed` as before, whatever strength says.

### Strength gates nothing

**PRE-REGISTERED: `strength` is recorded on every observation and is an input to
no threshold, no filter, and no sizing rule.** It does not decide whether an
observation is scored, and it does not decide whether a hypothetical trade would
be taken. It becomes a threshold **only** if Stage 4 measures that it carries
information, and **only** at a value derived from that measurement.

This restates the project's recorded rule — *a quantity not yet measured to carry
information is recorded, never gated on* (CONTEXT.md, 2026-07-27) — and the
reason for restating it is the count. **Six configuration keys have shipped in
this repository parsed, range-validated, and enforced nowhere**, each claiming a
property nobody had measured: `whale_position_scale_cap` and
`dnn_position_scale_cap` (removed 2026-07-18), `max_trade_notional_cap_pct` and
`default_position_sizing_method` (removed 2026-07-27), and the `in_cooldown` /
`cooldown_until_ts` pair, which had a declaration and a read and no assignment
anywhere in the tree including tests. **A threshold on a quantity not yet known
to carry information is a seventh in waiting.**

### The exact prompt, byte for byte (AMENDED, three fields)

**System block** (fixed on every call; reproduce exactly, including newlines. It
is NOT a cached prefix — see "Caching" above):

```
You judge whether a news headline is likely to move a US-listed stock's price by the next market close.

Reply with exactly one JSON object and nothing else, in this form:
{"judgment": "POSITIVE", "strength": 3, "reason": "<at most 20 words>"}

judgment must be exactly one of POSITIVE, NEGATIVE, NEUTRAL.

POSITIVE means you expect this stock to outperform the broad market by the next close.
NEGATIVE means you expect this stock to underperform the broad market by the next close.
NEUTRAL means you expect no material difference either way.

strength must be an integer from 1 to 5. It says how strongly this headline points in the direction you chose.
1 means the headline barely tilts the odds, and a move the other way would not surprise you.
5 means you would be surprised if this stock did not move in the stated direction by the next close.
2, 3 and 4 fall between those two points.
When judgment is NEUTRAL, set strength to 1.

You are given the ticker and the headline text. You have no price, no chart, no volume, no indicator, and no other information, and you must not assume any.

Do not answer NEUTRAL to be safe. Answer NEUTRAL only when the headline genuinely carries no directional information about this company.
```

**User block** (variable, headline last, UNCHANGED by this amendment):

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
withheld from the model**, which is what lets the Task 5 subset and secondary
tests be honest.

**AMENDMENT 3 changes nothing here.** Strength is an output, not an input. The
model still receives the ticker and the headline and nothing else.

### SUPERSEDED — DeepSeek V4 Flash, its pricing, and its cost arithmetic

The draft and Amendments 1 and 2 all named **DeepSeek V4 Flash**, temperature 0,
`max_tokens` 60. Its pricing, read 2026-07-27 from the published DeepSeek API
pricing page:

| | per 1M tokens |
|---|---|
| input, cache miss | $0.14 |
| input, cache hit | $0.0028 |
| output | $0.28 |

Its cost arithmetic, at the superseded two-field prompt's ~180 system, ~20 user
and ~30 response tokens:

```
cache hit:   180 x 0.0028/1M  +  20 x 0.14/1M  +  30 x 0.28/1M  = $0.0000117
cache miss:  180 x 0.14/1M    +  20 x 0.14/1M  +  30 x 0.28/1M  = $0.0000364
1,800 observations, cached:   ~$0.021
1,800 observations, uncached: ~$0.066
```

It also carried a **reported hard-rule conflict**: CLAUDE.md states that
`claude-opus-4-8`, `gpt-5.5`, `gemini-3.1-pro-preview` and `claude-haiku-4-5`
"are the only approved model strings; do not invent others", and DeepSeek V4
Flash is not among them. The draft reported that conflict rather than resolving
it, and recorded that accepting the document would mean amending a hard rule to
admit a fifth model string for a non-council use.

**Why it was replaced:** it was chosen on cost, and Stage 1 established that the
credential does not exist, that the model was therefore never tested, and that
the cost advantage is worth **$3.69 across the entire collection phase**.
Amendment 3 records the comparison at the measured arrival rate.

**What would make it correct again** is stated in full under "What would make
DEEPSEEK the better choice", below the Stage 1 results.

### SUPERSEDED — the two-field response and the prompt that produced it

The draft and Amendments 1 and 2 asked for **two fields, judgment and reason**.
The system block was byte-for-byte:

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

**This is the exact text Stage 1 scored 21 real headlines through**, so the
measured $0.000403 per call and the 52.4 percent directional rate belong to this
block and not to the amended one. It is preserved for that reason as much as for
the audit trail: a later session comparing costs must know which prompt produced
the number.

**Why it was replaced:** it carries no magnitude, so a takeover offer and a
routine reiteration weigh the same in every scored observation, and the
calibration question could not be asked at Stage 4 without a second collection.

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

**`strength` APPEARS IN NO LINE OF THAT FORMULA, AND THAT IS THE POINT.** It does
not weight an observation, it does not filter one, and it does not enter
`signed_i` or `net_i`. Every scored observation counts once regardless of the
strength attached to it. Strength has its own pre-registered secondary tests
below, and those tests are the only place it is used.

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
finding. **The two strength tests below are the one exception: they are
pre-registered, they are secondary, and they are not part of the four.**

### Secondary tests on strength, pre-registered (AMENDMENT 3)

**Two tests, one family, separate from the four primaries, and neither can
confirm the hypothesis.**

The primary question is whether the judgment predicts the sign. These ask a
different question: **whether the model's self-reported strength orders its own
outcomes.** A strength result is a property of the model's self-knowledge, not
evidence for or against the news-drift mechanism, and it is reported as such.

Both run over **scored observations only** — POSITIVE and NEGATIVE, NEUTRAL
excluded exactly as in the primary, and rows with `strength_parse_ok = 0`
excluded because they carry no strength. Both use the same estimator as the
primary: **cluster bootstrap over day clusters, 10,000 resamples, two-sided**,
under the same 60-cluster floor.

**S1, MONOTONICITY.** Spearman rank correlation between `strength` and `net_bp`,
positive expected. **Rank, not Pearson**, because the prompt defines an ordering
and not an interval scale: the distance from 1 to 2 is not claimed equal to the
distance from 4 to 5, so a correlation on the numeric value would assume
something the prompt never asserts.

**S2, TOP AGAINST BOTTOM.** Mean `net_bp` over strengths {4, 5} minus mean
`net_bp` over strengths {1, 2}, positive expected. **The buckets are pooled and
pre-specified HERE rather than chosen after the distribution is seen**: at 1,000
scored observations with an unknown strength distribution, the two extreme single
buckets could each be very thin, and pooling gives two halves whose n is
defensible whatever the distribution turns out to be. Strength 3 is excluded from
S2 by construction. **The five per-bucket means are reported descriptively
alongside**, labelled descriptive, and no bar is applied to them.

**THE BAR, AND THE CORRECTION.** The secondary family carries **its own alpha of
0.05, split two ways**, giving **`|z| >= 2.24`** (0.025 two-sided) on each of S1
and S2.

**The primary family is UNTOUCHED at `|z| >= 2.50`.** The alternative was to fold
all six tests into one family at 0.05/6, which is `|z| >= 2.64` — and that would
**raise a pre-registered primary bar because a secondary question was added
later**, which is exactly the defect pre-registration exists to prevent.

**THE COST OF THAT CHOICE, STATED RATHER THAN HIDDEN.** The two families together
are **not** protected at 0.05 overall. By the union bound the combined
family-wise error rate is up to **0.10**. A secondary that clears 2.24 is
therefore **weaker evidence than a primary that clears 2.50**, it is labelled so
wherever it is reported, and it may never be reported as confirming the
hypothesis.

**THE SECONDARY FAMILY IS NOT GATED ON THE PRIMARY, and the reason is a result
worth being able to see.** A hierarchical design would evaluate S1 and S2 only if
a primary cleared, which would hold the overall rate at 0.05 — and it would
suppress the most interesting outcome available here: **a pooled null that is a
mixture**, with the top strength bucket positive, the bottom negative, and the
mean of them zero. That would say the model knows when it knows while predicting
nothing on average. It would not rescue the hypothesis, it would not be reported
as a finding for the hypothesis, and it must remain visible.

**THE HONEST CAVEAT, AND IT BOUNDS WHAT EITHER TEST CAN SHOW.** Strength will
partly track **headline type** rather than model self-knowledge. An earnings beat
or a takeover offer scores high because that class of headline moves stocks; a
routine filing or an analyst reiteration scores low for the same reason. **So a
monotone result is consistent with "the model can sort headlines by category",
which is a much weaker and much less surprising claim than "the model knows its
own reliability", and a calibration result must not be over-read as the second.**

Separating the two requires holding headline type fixed and varying only
strength, which needs a headline-type taxonomy this design does not have and will
not invent after the fact. **The raw `headline` text is already recorded on every
row (Task 8), so the conditional analysis stays available to a later
pre-registration.** It is not attempted here, and a result that does not
distinguish the two explanations is reported as not distinguishing them.

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
making, because it is cheap (**about $4.01 in model calls at the measured
arrival rate, $8.01 at the 120-day hard stop**; AMENDED from ~$0.07, which was
the superseded DeepSeek rate at the superseded assumed arrival rate — see Task 3)
and because a powered negative closes a question the project would otherwise
keep circling. But **it
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

**A BAD `strength` IS NOT A FOURTH STATE AND MUST NOT BECOME ONE (AMENDMENT 3).**
If `judgment` parses, the model considered the headline, so the state is
`judged` whatever strength says. A missing, non-integer or out-of-range strength
sets `strength` NULL and `strength_parse_ok = 0` on a `judged` row; it never
sets `model_failed`. Routing it to `model_failed` would inflate the one state
that means "the model never considered this headline" with rows where it plainly
did, corrupting the denominator the coverage summary exists to keep recoverable.
**The same rule in the other direction:** a NEUTRAL row whose strength is not 1
is `judged`, is recorded as returned, and is counted as a format-adherence
diagnostic in the daily coverage summary.

**A `no_news` row emits no order, no signal, and no factor value of any kind.**
No neutral verdict is written, no 0.0 confidence, no row in any signal table.
The symbol-day simply has no observation.

### How absence is visible

- Every symbol-day queried writes a row with its state, so the denominator is
  always recoverable. The count of `no_news` rows is the evidence the collector
  ran.
- **Daily coverage summary** per collection day: symbols queried, `no_news`,
  `judged`, `model_failed`, `source_failed`, and (AMENDMENT 3) two
  format-adherence counts, `strength_unparseable` and
  `neutral_strength_not_one`. Both are diagnostics on a `judged` row and neither
  changes a state.
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
| `model_id` | TEXT | `claude-haiku-4-5` (AMENDED from `deepseek-v4-flash`). Recorded per row, not assumed from the spec, so a mid-collection model change is visible. |
| `prompt_sha256` | TEXT | hash of the exact system block, so a prompt change is detectable |
| `temperature` | REAL | 0 |
| `called_ts` | TEXT | ISO-8601 UTC |
| `latency_ms` | INTEGER | round trip, the Stage 1 latency input |
| `raw_response` | TEXT | **the model's full response text, not only the parsed verdict** |
| `judgment` | TEXT | POSITIVE \| NEGATIVE \| NEUTRAL, NULL when unparseable |
| `strength` | INTEGER | **AMENDMENT 3.** 1 to 5 exactly as returned, including a NEUTRAL row whose value is not 1. NULL when absent or unparseable. **Recorded, never gated** (Task 3). |
| `strength_parse_ok` | INTEGER | **AMENDMENT 3.** 0/1. 0 when `judgment` parsed and `strength` did not, which leaves the row `judged` and scoreable. |
| `reason` | TEXT | the model's own justification string |
| `parse_ok` | INTEGER | 0/1, on `judgment`. Independent of `strength_parse_ok`. |
| `error_class` | TEXT | on failure: transport, timeout, http_status, unparseable, exhausted |
| `input_tokens` | INTEGER | |
| `cached_input_tokens` | INTEGER | **expected 0 on every row.** The system block is ~270 tokens against Haiku 4.5's 4,096-token minimum cacheable prefix, so nothing caches. A nonzero value means the prompt grew past the minimum unnoticed, which makes this field a **canary for prompt drift** (Task 3). |
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

1. **ANSWERED BY STAGE 1 (2026-07-28): coverage is adequate and the gradient does not trigger the stop.** 98.0/80.0/72.0/64.0 percent by stratum, pooled arrival 0.359 per symbol-day against an assumed 0.10. Residual: 18 of 50 S4 symbols were silent all window, so S4's effective sample is about two thirds of nominal. ORIGINAL TEXT: Small-cap news coverage is unverified. No source has been checked for
   headline coverage of names at ADV 300k to 2M USD. The whole experiment
   assumes coverage exists at 0.10 headlines/symbol/day. **If real coverage is
   an order of magnitude thinner at the thin end, the strata the mechanism
   predicts most strongly are the strata with no data**, and the experiment
   measures the liquid end while claiming to measure the thin one. Stage 1 must
   measure per-stratum coverage before any scoring, and a strong coverage
   gradient across strata is itself a reason to stop.

2. **ANSWERED BY STAGE 1: measured 0.359, and 71.6 percent arrive off-hours.** The 60 day-clusters, not the 1,000 observations, is now the binding constraint. ORIGINAL: The 0.10 headlines/symbol/day arrival rate is an assumption, not a measurement.** The sample-size arithmetic rests on it. Stage 1 measures it.

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

5. **CLOSED BY AMENDMENT 3, by removing the conflict rather than granting an
   exception.** The model is `claude-haiku-4-5`, already one of CLAUDE.md's four
   approved strings, so no hard rule is amended, no fifth model string is
   introduced, and no credential has to be created. ORIGINAL TEXT: **WORSE THAN
   RECORDED: DeepSeek V4 Flash has NO CREDENTIAL in the keystore, so the named
   candidate could not be tested at all in Stage 1.** It is also not an approved
   model string under CLAUDE.md (Task 3). Accepting this document means amending
   that hard rule.

6. **LARGELY CLOSED BY AMENDMENT 3, and what remains is narrower.** Anthropic's
   error shapes are the ones this repository has already characterised and
   guarded: a 429 is always `rate_limit_error` and always transient, while credit
   exhaustion is a **400** `invalid_request_error` carrying "Your credit balance
   is too low", so keying exhaustion off the status code is itself a bug and
   `provider_health.classify` reads fields across every status. Stage 1 also ran
   21 Haiku calls with zero transport or request errors. **What is NOT closed:
   the collector does not exist, so nothing consumes that classifier on this
   path yet, and the `model_failed` versus `source_failed` split remains a design
   claim rather than an exercised one.** ORIGINAL: **No provider reliability data
   exists for DeepSeek.** The provider-exhaustion work covers OpenAI, Anthropic
   and Gemini error shapes. DeepSeek's 429 and billing-error semantics are
   unknown, and the `model_failed` versus `source_failed` split assumes they are
   distinguishable.

7. **LARGELY ANSWERED BY STAGE 1: ETB is 62.1 to 93.3 percent by stratum, so the negative-news half IS mostly reachable.** Limited to CURRENT classification, not historical, so a forward study must record ETB at decision time. Borrow COST remains unmodelled. ORIGINAL: Short-side feasibility is untested. The mechanism is strongest on
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

9. **NEW, INTRODUCED BY AMENDMENT 3: this experiment now shares a credential with
   the LLM council.** `claude-haiku-4-5` runs on `ANTHROPIC_API_KEY`, which also
   powers the council's base-check gate and one council provider. The exhaustion
   latch is keyed by provider LABEL because the quota belongs to the API key, so
   **a credit exhaustion caused by one is an exhaustion for all three**, and a
   collection run and a council run compete for the same balance. Nothing here is
   wrong, and choosing an approved model is still the right trade against
   introducing a fifth string, but the coupling did not exist under the
   superseded model and is recorded rather than discovered later. The mitigation
   is a separate spend ceiling for collection, and it is not specified here
   because no collector exists to enforce one.

10. **NEW, INTRODUCED BY AMENDMENT 3: the strength distribution is unknown, and
    the secondary tests assume it is not degenerate.** S1 and S2 both need
    strength to vary. If the model answers 3 to nearly everything, S1 has almost
    no rank variation and S2's two pools are nearly empty, and both tests are
    uninformative regardless of what the primary shows. **This cannot be checked
    before collection**, because checking it means calling the model on real
    headlines, which is Stage 1 work this amendment deliberately does not do. The
    distribution is reported as a first-class diagnostic alongside the NEUTRAL
    rate, and the reversal condition is recorded under "What would revisit the
    five-point scale and the anchors".

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

### STAGE 1 RESULTS — measured 2026-07-28, spend 0.0096 USD of a 15.00 USD ceiling

**Measurement only. No collector built, nothing wired into the engine, nothing traded.** Hard ceiling enforced before the first call and never approached.

#### Task 1 — News coverage per stratum

Universe: ADV 2.07M-65.3M, price floor 10.00, four log-ADV strata. 50 symbols
sampled per stratum (200 total), Finnhub company-news, 30 calendar days
(2026-06-28 to 2026-07-28, about 21 trading days).

| stratum | n | any news | silent all window | headlines | per sym/day | median | p90 |
|---|---|---|---|---|---|---|---|
| S1 (most liquid) | 50 | **98.0%** | 1 | 660 | 0.616 | 10 | 27 |
| S2 | 50 | 80.0% | 10 | 315 | 0.294 | 4 | 15 |
| S3 | 50 | 72.0% | 14 | 211 | 0.197 | 2 | 12 |
| S4 (thinnest) | 50 | **64.0%** | 18 | 352 | 0.329 | 1 | 16 |
| POOLED | 200 | | 43 | 1,538 | **0.359** | | |

**THE GRADIENT IS REAL AND DOES NOT FAIL THE STOP CONDITION.** Coverage falls
98.0 to 64.0 percent from S1 to S4, a 1.5x gradient. The pre-registered stop
was that the strata where the mechanism is strongest would be the strata with
NO data. S4 is not that: 64 percent of its symbols carry news and its arrival
rate of 0.329 is 3.3x the assumption. **Stop condition not met.**

**But coverage is CONCENTRATED, and that is the caveat.** 18 of 50 S4 symbols
were silent for the entire window, and the 32 that were not averaged 11
headlines each against S3's 5.9. So S4's healthy pooled rate is produced by a
minority of noisy names. **The effective S4 sample is about two thirds of
nominal**, and the stratified draw should over-sample S4 to compensate or
accept a smaller effective n there.

#### Task 2 — Arrival rate against the requirement

**Measured 0.359 headlines per symbol per trading day, pooled. The
pre-registration assumed 0.10 and does not clear at 0.05.**

```
400 symbols x 0.359 x 0.75 surviving filters = 107.7 scorable/day
1,000 observations reached in about 10 trading days
60 day-clusters is now the BINDING constraint, not the observation count
60 days x 107.7 = ~6,460 observations, 6.5x the requirement
```

**Reachable inside the 120-day hard stop with 2x margin on time and 6.5x on
count.** The design is over-powered at 400 symbols; the sample could fall to
about 150 and still clear, which is a decision for the operator, not this
session.

**OFF-HOURS FRACTION: 71.6 percent** of headlines arrive outside 13:30-20:00
UTC. The case the mechanism depends on is the majority case, not the exception.

#### Task 3 — ETB fraction per stratum

Alpaca `/v2/assets`, 30 symbols per stratum. `shortable` and `easy_to_borrow`
agreed on every symbol resolved.

| stratum | n | shortable | ETB | unresolved |
|---|---|---|---|---|
| S1 | 30 | 83.3% | **83.3%** | 0 |
| S2 | 30 | 93.3% | **93.3%** | 0 |
| S3 | 30 | 80.0% | **80.0%** | 0 |
| S4 | 29 | 62.1% | **62.1%** | 1 |

**This is the best news in the session.** Open Question 7 named short-side
feasibility as the most consequential unresolved item, on the worry that the
NEGATIVE-news half of the mechanism might be untradeable. **It is largely
reachable: 62 to 93 percent by stratum.** The gradient runs the wrong way (S4
lowest) so the thin end loses most, but a 62 percent floor is not a blocker.

**LIMITATION, stated: this is CURRENT classification, not historical.** ETB
status at a past formation is not recoverable from this endpoint. Correct for
forward collection, wrong for any backfilled study, and a forward study must
record ETB at decision time rather than reconstructing it.

#### Task 4 — Pipeline latency, measured

| leg | median | p95 | max |
|---|---|---|---|
| news API response | 0.17 s | 0.49 s | |
| scoring call round trip | 1.04 s | 1.91 s | 14.00 s |
| **total headline-to-scored-decision** | **~1.2 s** | **~2.4 s** | **~14.5 s** |

**The provisional 20-minute delay is confirmed as conservative by three orders
of magnitude at p95.** The measured path is seconds. **It is NOT reduced here**,
because this measures API latency alone and excludes polling interval, order
placement, and venue acknowledgement, none of which this session exercised. The
honest revision: the 20 minutes is dominated by the POLLING CADENCE, not by
call latency, so the delay should be re-derived from the collector's poll
interval once a collector exists. Until then 20 minutes stands.

#### Task 5 — The tick multiple: MEASURABLE, still unmeasured

**Amendment 2 recorded the tick multiple as "unmeasurable without paid quote
data". THAT IS FALSIFIED.** The Alpaca paper tier serves
`/v2/stocks/{symbol}/quotes/latest` and `/snapshot`, both returning bid and ask.
Reachability is established.

**But this session could not measure it, and reports that rather than the
numbers it collected.** Sampled at 06:31 UTC, outside US regular hours
(13:30-20:00 UTC):

| stratum | n | ticks wide, median | p25 | p75 | max |
|---|---|---|---|---|---|
| S1 | 10 | 870.5 | 99.0 | 1,714.0 | 10,359.0 |
| S4 | 10 | 303.5 | 6.0 | 1,343.0 | 3,429.0 |

**These are not spreads and must not be read as any.** The most liquid stratum
shows a WIDER median than the thinnest, which is backwards and is the proof
that these are stale after-hours quotes rather than markets. **The tick multiple
remains unmeasured. What it now takes is one script run during RTH**, which is
a scheduling problem rather than a data-access problem, and it is the highest
value remaining measurement because the multiple is multiplicative with the
price floor.

#### Task 6 — The model comparison: INCONCLUSIVE, and one reason is my own error

**Comparison set fixed before any result was seen:** `claude-haiku-4-5`,
`claude-opus-4-8`, `gemini-3.1-pro-preview`. 21 real headlines drawn from the
sample, temperature zero, the exact EXPERIMENT.md prompt.

**DeepSeek V4 Flash, the CANDIDATE model the whole specification names, could
not be tested: no credential exists in the keystore.** OpenAI was recorded
exhausted and not called.

| model | n | parse fail | directional | cost/call | spend |
|---|---|---|---|---|---|
| claude-haiku-4-5 | 21 | **0.0%** | 52.4% | $0.000403 | $0.0085 |
| claude-opus-4-8 | 21 | **100%** | n/a | $0 | $0 |
| gemini-3.1-pro-preview | 2 | 0.0% | 50.0% | $0.000559 | $0.0011 |

**THE OPUS RESULT IS MY BUG, NOT A MODEL FAILURE, and reporting it as a model
failure would have been the dishonest reading.** Every call returned
`HTTP 400: temperature is deprecated for this model`. My request sent
`temperature: 0`. **Opus 4.8 was never tested.** CLAUDE.md already records this
exact quirk for the OpenAI GPT-5 family; it applies to Anthropic Opus 4.8 too
and is now recorded.

**Gemini latched EXHAUSTED after 2 calls** on HTTP 429 with quota language,
per the recorded latching rule, and was not retried.

**NO CLAIM OF DIFFERENCE BETWEEN MODELS IS MADE.** One model produced a usable
sample. The 100 percent agreement between haiku and gemini rests on n=2 and is
meaningless. With one usable arm there is nothing to correct for
multiple comparisons, and applying a correction to a comparison that did not
happen would be theatre.

**WHETHER CAPABILITY MATTERS IS UNANSWERED.** That was the question deciding
whether the experiment can run on the cheap tier, and it remains open. What IS
established: haiku parsed 21 of 21 at temperature zero and cost $0.000403 per
call, so **the cheap tier is mechanically capable of producing well-formed
verdicts at a workable price.** Whether its judgments are as good is untested.
#### Tick multiple, attempt 2 (2026-07-28 06:49 UTC): BLOCKED, NOT MEASURED

**The market was closed and the measurement was not taken.** Alpaca `/v2/clock`
returned `is_open: false`, next open 13:30 UTC, 6h41m away. A session cannot
wait that long, so the honest outcome is no measurement rather than a second
set of after-hours numbers, which Stage 1 already proved worthless (S1 870
ticks against S4's 303, the liquidity ordering backwards).

**Nothing was changed on no data.** `alpaca_equity_spread_tick_multiple` stays
at 1.0, the floor, with its yaml note that it therefore understates small caps
by construction. Moving a cost-model value without a measurement is the
fabrication this project has corrected five times.

**The blocker is converted into one command.**
`scripts/measure_tick_multiple_rth.py` resolves the stratified universe, sweeps
at 14:00, 16:30 and 19:30 UTC so the open, middle and close are separated,
records bid, ask, cents, ticks, bp, stratum, ADV and price per observation,
discards crossed, locked, zero-size and over-60-second-stale quotes with counts
by reason, and applies the Stage 1 monotonicity check before any number is
believed. **It REFUSES to run outside RTH**, verified: exit 2.

**Still the highest-value remaining measurement**, because the multiple is
multiplicative with the price floor and at three ticks the 10.00 floor puts the
worst member at 30.4 bp, the entire assumed effect.

#### The Stage 1 verdict

**STAGE 1 CLEARS ON EVERY STOP CONDITION IT WAS DESIGNED TO TEST. It does not
clear on everything it was asked to answer, and the gap is named rather than
smoothed.**

**Answered, and passing:**
- **Open Question 1, coverage.** Real gradient, 98.0 to 64.0 percent, but S4 is
  not empty and the stop condition is not met. Caveat: coverage is concentrated
  in a minority of S4 names.
- **Open Question 2, arrival rate.** 0.359 against an assumed 0.10. The sample
  is reachable in about 10 trading days for count and 60 for clusters, inside
  the 120-day stop with 6.5x margin on observations.
- **Open Question 7, short side, the one flagged most consequential.** ETB is 62
  to 93 percent by stratum, so the NEGATIVE-news half of the mechanism is
  largely tradeable. Limited to current classification.
- **Latency.** The 20-minute delay is conservative by orders of magnitude at the
  API layer, and its real driver is the polling cadence, which does not exist
  yet.

**Answered, and it changes a recorded belief:**
- **The tick multiple is MEASURABLE**, contradicting Amendment 2. Paper-tier
  quotes are reachable. It is still unmeasured because this session ran outside
  RTH, and that is now a scheduling task rather than a blocked one.

**NOT answered:**
- **Does capability matter.** The comparison failed: the named candidate has no
  credential, one arm died on my own malformed request, and one exhausted after
  two calls. **This must be redone before the cheap-tier decision is made.**
- **Open Questions 3, 6, 8** were not in scope for this session.

**Nothing measured here says stop.** The two conditions that would have ended
the experiment, an empty thin stratum and an unreachable sample size, both came
back clearly on the passing side, and the short-side worry that looked most
likely to kill it came back mostly fine. **The experiment is not cleared to
collect, because the model comparison is unresolved and the tick multiple is
unmeasured, and both are cheap to finish.**

**FOLLOW-UP NOTE, added by AMENDMENT 3 and deliberately not folded into the
verdict above, which is a record of what Stage 1 found.** Amendment 3 does **not**
resolve the model comparison. It chooses a model on grounds the comparison did
not test: reachability, approval under CLAUDE.md, mechanical parse rate at
temperature zero, and a cost that no longer decides anything. **Whether
capability matters is still unanswered**, and a later session that wants that
answer must re-run the comparison with a working Opus request shape and a Gemini
budget that survives past two calls. Neither this amendment nor Stage 1 licenses
a claim that Haiku is the best of the four.

## What would make DEEPSEEK the better choice

Recorded so the decision is auditable rather than merely made, in the same shape
as the rank-versus-ADV note above.

**Three conditions, and ALL THREE have to hold.**

1. **A credential has to exist.** Stage 1's blocker was not price or capability,
   it was that no DeepSeek key is in the keystore, so the named candidate was
   never called once.
2. **A head-to-head has to show DeepSeek is not worse.** Scored on the same
   headlines at temperature zero through the identical amended prompt, with parse
   rate, directional rate, and agreement reported, and with a multiple-comparison
   correction applied to any claim of difference. Stage 1 produced one usable arm
   out of four and made no such claim; a replacement must clear that bar rather
   than inherit its silence.
3. **The cost difference has to become decision-relevant, and at this volume it
   is not.** The gap is $0.0004286 per call.

**The volume arithmetic, stated so nobody has to re-derive it:**

```
gap per call                       = $0.000465 - $0.0000364 = $0.0004286
collection phase (8,616 calls)     = $3.69
a full year of live operation at this universe size:
  143.6 calls/day x 252 sessions   = 36,187 calls  -> $15.51/year
the gap first reaches $100 at       = 233,000 calls, about 27x the whole
                                      collection phase
```

**So the cost argument does not return until the universe or the arrival rate
grows by roughly two orders of magnitude**, and at that scale the design would be
re-powered anyway and this pre-registration would not be the governing document.

**And CLAUDE.md would still have to be amended**, because DeepSeek is not one of
the four approved model strings. Amendment 3's cleanest property is that it needs
no rule change; a reversal gives that back.

**What would NOT be a reason to reverse:** that Haiku's per-call cost is 13x
DeepSeek's. That ratio was true when the draft named DeepSeek and it is true now.
A ratio on a four-dollar bill is not a constraint, and treating it as one is what
put an untested model with no credential into the specification in the first
place.

## What would revisit the five-point scale and the anchors

**THE SCALE.** Two conditions, either sufficient, both measurable from the first
collection:

- **DEGENERATE USE.** More than 80 percent of scored observations land on one
  value, or fewer than three of the five values ever occur. The model is not
  using the scale, and the correct response is to **reduce** resolution to three
  points, not to add explanation to the middle — a scale the model collapses does
  not become finer by being described more.
- **SATURATED USE.** All five buckets populated, S1 clearing its bar, and a
  top-versus-bottom gap large relative to the per-bucket spread. Only then is a
  finer scale worth testing, and **only on new data under a new
  pre-registration**. Re-bucketing the same observations at a different
  resolution is choosing a specification after seeing the result.

**THE ANCHORS.** Two conditions:

- **SKEW.** A median strength of 1 or of 5 says the anchors sit in the wrong
  place relative to how this model reads headlines, and the wording is re-derived
  rather than the scale changed.
- **TYPE DOMINANCE.** A later session builds the headline-type taxonomy this
  design does not have, and finds that strength is explained by type while
  conditional-on-type strength carries no information. The anchors are then
  measuring the wrong thing — they ask about this headline's force and are being
  answered about its category — and asking a self-knowledge question requires
  wording that references the model's own uncertainty rather than the headline's
  content. That is a different field, not a re-tuned one.

**WHAT WOULD NOT BE A REASON TO REVISIT EITHER:** that strength failed to predict
outcomes. **A null on S1 and S2 is a result about the model, not a defect in the
scale**, and re-wording the anchors until strength predicts something is fitting
the instrument to the answer. The scale changes on how the model USES it, never
on what it PREDICTS.

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

**STATUS UPDATE 2026-07-28, after acceptance and after stage 2.** The paragraph
below described this document at the moment it was written, and two of its
clauses are now historical rather than current: **stage 2 HAS built a
collector** (`news_experiment/`, standalone, demonstrated, no engine
integration) and it **does create a table**, `news_observation`, in its own
database. **What has NOT changed is the part that matters: collection has not
started, nothing is promoted, nothing is sized, and live trading is untouched
and remains off.** The collector refuses `--run-kind collection` unless the
operator explicitly clears it, because the tick multiple is still unmeasured
and its result may amend the cost model or the band. The original text follows.

It does not authorise collection. It creates no table, collector, provider
client, or config key. It promotes, enables, and sizes nothing. Live trading is
untouched and remains off.

Stage 1 begins only if the operator accepts this proposal, and Stage 1's first
job is Open Questions 1, 2 and 7, because any of the three can end the
experiment before a single verdict is scored.

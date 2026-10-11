# Stage C.1 Task 9c: relevance grade adjudication (Amendment 8.3, 9.13)

Lead: Opus 5.5 (xhigh), 2026-10-11.

**Inputs**
- **Sample:** reports/c1_relevance_sample.csv. 200 rows drawn by the frozen relevance.py at commit 2b75aba, sha256 c470731e4a6522aa9c0b9d57f839c862dae328867a3d620fc6b0d7ced84b8a76.
- **Grader input:** reports/c1_relevance_grader_input.csv. It holds the symbol, the issuer name and the headline (9.13), with names from analysis_bars.db universe_asset.name for all 140 symbols.
- **Grades:**
  - reports/c1_relevance_grades_opus.csv (RelevanceGrader-OpusXHigh)
  - reports/c1_relevance_grades_fable.csv (RelevanceGrader-FableXHigh)
  - Each grader was blind to the other.

**Output**
- reports/c1_relevance_final.csv (columns id, grade, reason, source), built by reports/c1_relevance_scripts/build_final.py (issuer names joined by reports/c1_relevance_scripts/names_join.py).
- reports/c1_relevance_summary.json, from the frozen `relevance summarize`.

Nothing is filtered on these grades (Amendment 8.3).

## Agreement

The graders agreed on 164 of 200 rows: raw agreement 0.820, Cohen's kappa 0.648.

| Opus grade | Fable grade | rows |
|---|---|---|
| company-specific | company-specific | 131 |
| off-topic | off-topic | 27 |
| roundup | roundup | 6 |
| roundup | off-topic | 32 |
| company-specific | off-topic | 3 |
| off-topic | roundup | 1 |

Agreed rows keep the shared grade.

## The rule applied to the disagreements

The rubric is Amendment 8.3, verbatim:
- company-specific: the headline is about the symbol's issuer
- roundup: the issuer is one of several named
- off-topic

The stage prompt adds a clarification for preferred shares. 9.13 gives each grader only the symbol, the issuer name and the headline, so the classes describe the headline.

**Ruling.** A headline that does not name the issuer is graded as follows:
- If it does not otherwise refer to the issuer unambiguously, the issuer is not "one of several named" and the headline is not about the issuer, so the grade is **off-topic**.
- This covers "N stocks" lists, mover lists, market wraps, analyst-call roundups that name other firms, sector and industry pieces, fund letters, and generic templates.
- Whether the article body names the issuer is not visible to the grader, so it is not graded.

All six agreed roundups name the issuer in the headline, which is consistent with this rule.

**The alternative reading, recorded.** The Opus grader counted an unnamed multi-stock list as a roundup when the issuer was plausibly one of the stocks in the article. The news source tags articles by the tickers they mention. Under that reading, the 32 rows below would move from off-topic to roundup:
- roundup: 39 of 200 (19.5%) instead of 7 (3.5%)
- off-topic: 30 (15.0%) instead of 62 (31.0%)
- company-specific: unchanged at 131 (65.5%)

The pre-registered 54-row look (EXPERIMENT.md 8.3) reported 13% roundup without stating its rule, so it does not settle the question. The ruling above is the literal reading. The alternative is reported so that a reader can apply it; it moves no row between company-specific and the other two classes.

**Outcome.** The lead's rulings coincide with the Fable grader on all 36 disagreements. The rule was taken from the rubric's wording ("named", "the headline is about"), not chosen to follow either grader. The four rows not covered by the unnamed-list rule are ruled individually below.

## Final rates (reports/c1_relevance_summary.json)

| set | n | company-specific | roundup | off-topic |
|---|---|---|---|---|
| all sampled rows | 200 | 131 (65.5%) | 7 (3.5%) | 62 (31.0%) |
| 8.2 rule (a) exact removed | 181 | 124 (68.5%) | 4 (2.2%) | 53 (29.3%) |
| rule (a) plus rule (b) approximation b1 removed | 180 | 124 (68.9%) | 4 (2.2%) | 52 (28.9%) |
| rule (a) plus rule (b) approximation b2 removed | 180 | 124 (68.9%) | 4 (2.2%) | 52 (28.9%) |

Rule (b) has no exact form on the six sampled columns (mapping D23, relevance.py docstring). C.2 recomputes it exactly. Both grader sets are in the summary JSON under `rates.opus` and `rates.fable`.

## Individual rulings (not the unnamed-list rule)

- **id 11888 SOC (Sable Offshore): off-topic.** The headline is "'Trump administration ratchets up its fight to get more oil flowing from California'". Opus read it as company-specific from outside knowledge that Sable's Santa Ynez restart is at the centre of that fight. The headline's subject is federal-state oil policy, and it neither names Sable nor refers to it uniquely.
- **id 15442 MGEE (MGE Energy): off-topic.** The headline is "Are You Looking for a High-Growth Dividend Stock?". Opus read it as company-specific, because Zacks' single-stock template is usually about the tagged stock. The headline itself names no issuer and carries no information about MGE Energy.
- **id 19800 INDB (Independent Bank Corp.): off-topic.** "Independent Bank Corporation" is the registered name of IBCP (Michigan). INDB is "Independent Bank Corp." (Massachusetts). The headline is about a different issuer whose name nearly collides with INDB's.
- **id 22436 STRK (a Strategy Inc preferred): roundup.** The headline is "Strive purchases $169M in bitcoin, nearly 6 times more than Strategy's recent buy". Strategy is the issuer of STRK itself, so the preferred-share clarification does not exclude it. Strategy is named as one of the two companies in the headline.

## Every disagreement, with the final grade

| id | symbol | headline | Opus | Fable | final | lead reason |
|---|---|---|---|---|---|---|
| 435 | SHBI | Twilio To Rally Around 26%? Here Are 10 Top Analyst Forecasts For Tuesday | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 625 | PSN | Dow Tumbles 400 Points; Procter & Gamble Shares Fall After Q4 Results | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 1704 | FLNG | Buy 23 July Lo-Price Hi-Growth Dividend Dogs Out Of 46 | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 2438 | EPR | Sell Alert: 2 Risky REITs To Avoid | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 2481 | ADEA | Powell Industries Posts Downbeat Q3 Results, Joins Clearpoint Neuro, Ichor Holdings And Other Big Stocks Mo... | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 3410 | ADV | Nasdaq Falls Over 100 Points; Eli Lilly Shares Gain On Upbeat Earnings | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 3983 | VNT | The London Company Small Cap Q2 2026 Performance Update | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 9891 | HE | Top 3 Utilities Stocks That May Rocket Higher This Quarter | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 11247 | TBN | Yext Posts Upbeat Q2 Earnings, Joins Fervo Energy, MiniMed Group And Other Big Stocks Moving Higher On Tuesday | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 11888 | SOC | 'Trump administration ratchets up its fight to get more oil flowing from California' - Associated Press | company-specific | off-topic | off-topic | California oil policy headline; Sable not named |
| 11916 | EPR | 5 Elite Dividend Stocks That Pay You Every Single Month | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 13064 | WFC.PRL | Bank Preferred Stocks Are Sending a Warning About Interest Rates | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 13324 | PBA | Midstream Taps Private Equity To Fund Growth Projects | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 14713 | BLSH | This Coinbase Analyst Is No Longer Bearish; Here Are Top 5 Upgrades For Monday | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 15442 | MGEE | Are You Looking for a High-Growth Dividend Stock? | company-specific | off-topic | off-topic | Generic dividend headline; MGE Energy not named |
| 15508 | ARQQ | Quantum Computing Stocks Lose Their Momentum—and the Lone Holdout Isn't Really a Quantum Play | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 15658 | GLAD | Want $7,000 In Passive Income? Invest $25,000 In Each of These 3 Dividend Stocks | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 16278 | BEAM | In Vivo Gene Editing Market Size, Share & Trends Analysis - Global Opportunity Analysis & Industry Forecast... | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 16565 | CHRN | Cigna downgraded, Humana upgraded: Wall Street's top analyst calls | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 18556 | ZSQR | Stay updated with the stocks that are on the move in today's after-hours session. | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 18636 | DBVT | European Equities Traded in the US as American Depositary Receipts Edge Lower in Thursday Trading | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 18659 | FULT | Improve Your Retirement Income with These 3 Top-Ranked Dividend Stocks | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 18660 | FULT | Dividend Champion, Contender, And Challenger Highlights: Week September 27 | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 18734 | BGC | 1 Safe-and-Steady Stock for Long-Term Investors and 2 We Avoid | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 19492 | MEC | 3 Russell 2000 Stocks with Open Questions | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 19689 | MATX | 3 Cash-Producing Stocks That Fall Short | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 19800 | INDB | Independent Bank Corporation Announces Date for Its Third Quarter 2026 Earnings Release | company-specific | off-topic | off-topic | Independent Bank Corporation is IBCP, not INDB |
| 20355 | COLL | 3 Healthcare Stocks That Concern Us | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 20381 | MQ | 1 Unprofitable Stock with Impressive Fundamentals and 2 We Avoid | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 21195 | AFG | Dividend Champion, Contender, And Challenger Highlights: Week October 4 | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 22436 | STRK | Strive purchases $169M in bitcoin — nearly 6 times more than Strategy's recent buy | off-topic | roundup | roundup | Strategy named beside Strive; one of two named |
| 22699 | IRTC | 2 Unprofitable Stocks with Competitive Advantages and 1 We Brush Off | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 22832 | PRCT | Intel downgraded, Marvell upgraded: Wall Street's top analyst calls | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 22845 | STC | 3 of Wall Street’s Favorite Stocks That Fall Short | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 23169 | LEVI | 1 Profitable Stock with Solid Fundamentals and 2 We Brush Off | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |
| 23248 | ECO | Shares of oil and gas-related companies are trading lower as crude prices pull back amid renewed optimism o... | roundup | off-topic | off-topic | issuer not named in the headline; not one of several named |

Each grader's own reason for every row is in its grade file.

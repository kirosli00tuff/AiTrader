# AiTrader / Market AI Lab — Independent Audit

**Date:** 2026-07-27
**Auditor:** independent read-only pass, no prior work on this codebase
**Scope:** assessment only. No source, config, schema, test, or tracking file was changed. No test suite was run. No process was started or signalled. No network or provider call was made. This file is the only thing committed.
**Method:** read CLAUDE.md, PROGRESS.md, CONTEXT.md, RETURN.md, WEEKLOG.md, LIVE_READINESS.md, and the prior AUDIT.md in full or by scoped section, then read the composition path, the RiskGate, the real-fill gate, the base-check gate, and the factor writers in source. Line and file counts were taken from the tree. Quoted incident history is cited to file and line.

**A note on the database.** The constraint permitted reading the production database with SELECT only. No `.db` or `.sqlite` file exists in this checkout (the database is gitignored and regenerated). Every row count, mean, and replay result in this report therefore comes from the tracking files, not from a query I ran. Those numbers are marked inferred below.

**Replaces** the prior AUDIT.md dated 2026-07-05, which is now stale (it predates the council measurement sessions, the provenance work, the fee model, the survivorship repair, and the composition finding).

---

## Three lead findings

**1. Nothing in this system has been shown to make money, and the evidence is now strong enough to say so rather than to keep hoping.** Seven price-based hypothesis families are resolved against buy-and-hold-after-costs with zero survivors (PROGRESS.md:250, RETURN.md:911). The LLM council reached a properly powered negative: 274 scorable calls across 80 symbol clusters, pooled excess -0.5 bp per call, interval [-22.5, +21.4], which excludes the 50 bp effect the design was built to detect (PROGRESS.md:193). Zero trades in all history carry a council decision id (PROGRESS.md:220). The parts that have earned their place are not the trading intelligence. They are the deterministic safety spine and the measurement discipline that produced these negatives. That is a real and unusual asset, and it is worth being clear that it is the asset.

**2. The gate the system actually enforces is not the gate it documents, and factors that failed every measurement still suppress trades through it.** Composed confidence is the weight-normalised mean of participating factors (`signal_engine/factor_engine.cpp:113-126`), and the RiskGate blocks any order whose confidence is below `min_confidence_default` 0.65 (`risk/risk_gate.cpp:75`). The documented gate reads as a floor on a trade's conviction. The effective gate is a floor on an average that includes `dnn_advisory` and `whale_signal`, neither of which has demonstrated skill, both of which participate at nonzero weight, and both of which sit below the mean and therefore drag it down. Replaying 716 recorded evaluations without those factors moved every one and flipped 386 across the 0.65 floor, all permissive (PROGRESS.md:141-154, inferred). A persistently pessimistic factor with no skill suppresses trades while no threshold ever changes. The mean is the wrong composition rule for a gate.

**3. The RL "real fills" gate, a CLAUDE.md hard rule, is counting synthetic fills, and reads roughly forty times higher than the real evidence it claims to measure.** `count_closed_trades` excludes only `bar_source = 'synthetic'` (`ml_factor/real_dataset.py:220`) and counts `'unknown'` as real by design (`:218-219`). The provenance column was added by an `ALTER` that defaulted every pre-existing row to `'unknown'` (`storage/storage.cpp:115`). Because the offline synthetic loop is the declared continuous training environment, that `'unknown'` bucket is dominated by synthetic fills written before the column existed. WEEKLOG.md:55 states the counter reads 243 of 500 while real-path native exits total 6 lifetime. The gate that exists to withhold RL until real evidence accrues is being fed the synthetic history it was meant to exclude. RL ships off, so nothing has broken, but the gate itself fails toward permitting.

---

## Task 1 — What is actually here

C++20 engine core plus a Python advisory and UI tier, communicating through a shared SQLite database (C++ writes, Python reads) and an optional localhost JSON-over-HTTP bridge used only with `--bridge`. Line counts are from the tree (implementation and test source, excluding docs and generated files).

| Subsystem | Files / lines | What it does | Depends on it | Runs today | Output ever used | State |
|---|---|---|---|---|---|---|
| `risk/` | 2 / 220 | Deterministic RiskGate, latching kill switch | Every order in the loop | Yes | Yes, blocks orders | Live |
| `core/` | 19 / 6,591 | Run loop, engine, provenance, control-file readers, sleeves, bar aggregation, rehydration | Whole system | Yes | Yes | Live |
| `config/` | 8 / 2,624 | YAML-subset parser, typed structs, load-time validation, fees | Engine, harness | Yes | Yes | Live |
| `signal_engine/` | 6 / 1,510 | Factor combine, `compose_gate_verdict`, council gate, strategy (RSI-2 + momentum + regime) | Engine | Yes | Yes | Live |
| `learning/` | 3 / 273 | Adaptive tuner, `validate_not_weakening_limits`, 30-trade gate | Engine | Yes on gate, dormant on tuning | Weights nudged only past 30 closed | Live gate, dormant tuner |
| `market_data/` | 8 / 1,566 | Alpaca feed, synthetic-regime feed, replay, backfill, universe resolution | Engine, discovery | Yes | Yes | Live |
| `execution/` | 4 / 628 | Mode router, Alpaca paper adapter, IBKR live adapter, disabled live adapters | Engine | Paper yes, IBKR no | Paper fills | Live paper, dormant IBKR |
| `storage/` | 3 / 1,640 | SQLite DAO, schema, migrations, append-only audit log | Everything | Yes | Yes | Live |
| `account_manager/` | 5 / 625 | Credentials (encrypted keystore), live-enable gate, log masking | Engine, bridge, API | Yes, except `try_enable_live` | Yes | Live except enable path |
| `llm_consensus/` | 13 / 3,477 | Real 3-provider council, Haiku base-check gate, evidence renderer, provider health, persistence | Bridge `/score/llm`, discovery | Only with keys + bridge | Measured, never moved a trade | Dormant-sound, negative result |
| `ml_factor/` | 8 / 1,265 | Supervised MLP (`dnn_advisory`), real-data trainer, registry, real-fill counter | Bridge `/score/dnn`, RL gate | Champion is synthetic-trained | Advisory score with bridge | Dormant-sound |
| `rl_advisory/` | 7 / 821 | PPO module, gym env, real-fill gate, `/score/rl` | Bridge, only if `rl_enabled` | No (shipped off, untrained) | Never | Dormant, provably inert |
| `whale_signal/` | 4 / 758 | SEC EDGAR 13F/Form 4 adapters, scorer, mock fallback | Bridge `/score/whale` | Only if `WHALE_LIVE`/`SEC_EDGAR` on | Advisory score, no demonstrated skill | Dormant-sound |
| `python_bridge/` | 3 / 659 | stdlib HTTP bridge exposing score/marketdata/execute | Engine with `--bridge` | Only with `--bridge` | Yes when on | Dormant-sound |
| `api_server/` | 10 / 5,641 | Read-only FastAPI backend, controls, supervisor, stack lifecycle | React GUI | Yes when GUI runs | Yes | Live |
| `ui/` | 5 / 2,958 | Dash dashboard (fallback) | Operator | Yes | Yes | Live (fallback) |
| `web/` | 70 / 8,620 | React + TypeScript GUI | Operator | Yes | Yes | Live |
| `discovery/` | 11 / 3,417 | Universe screen, Stage A/B/C funnel, watchlist, budget | Long-term sleeve | Ships disabled | Watchlist never gained a member on merit | Dormant, one live blocker |
| `adaptive/` | 9 / 1,744 | News feed, materiality filter, defensive-only react | Watchlist shaping | Ships disabled | Adaptive table empty in production | Dormant-sound |
| `research_satellite/` | 3 / 458 | Long-term council thesis sleeve | Sleeve split | Ships off | Every pass "no catalyst" at conviction 0.0 | Dormant |
| `news_ingestion/` | 3 / 113 | Catalyst scoring | Council evidence, discovery | Mock only | Hash-constant, now ignored by real services | Near-dead |
| `backtest/` | 5 / 866 | Harness linking the engine's own libraries, fee model, universe rule | Research | Yes in research | Every negative result | Live in research |
| `ops/` | 8 / 2,513 | Watchdog, weeklog, demo, logpipe, backup | Operator | Yes | Yes | Live |
| `scripts/` | 9 / 2,361 | Start, verify, quarantine, provider-list | Operator | On demand | Yes | Live tools |
| `tests/` | 91 / 21,909 | 59 pytest files, 31 ctest files, fixtures | CI/operator | Yes | Yes | Live |

**Dead or near-dead.** `news_ingestion` is a mock catalyst provider that every real service now ignores (CONTEXT.md:104, 116). It writes a hash constant no consumer trusts. It is the clearest removal candidate.

**Dormant but sound.** `rl_advisory`, `discovery`, `adaptive`, `research_satellite`, the whale adapters, and the real council all ship off or behind the bridge, are tested, and behave. Verified claim in the record: with the flags off, a 12,000-step run is behaviorally identical to the pre-feature baseline (PROGRESS.md:23, 25).

**Live.** The safety spine, the run loop, storage, config, the strategy layer, the paper feed and execution, both UIs, the API backend, and the backtest harness.

---

## Task 2 — What earns its place

Judged against a recorded need, one sentence each.

- **RiskGate and kill switch (`risk/`).** Keep. Final authority on every order, pure and deterministic, and the one unit the record shows thoroughly tested.
- **The live-enable gate and its four blocks (`account_manager/`, `execution/`).** Keep. `try_enable_live` is never called and live is unreachable by construction, which is the point.
- **Provenance system (`core/provenance.hpp` and the bar-source axis).** Keep. It exists because the feed substituted walk prices for live data for 19 hours, wrote 916 synthetic bars into the real table, and executed two trades against them while every health signal stayed green (CONTEXT.md:217, PROGRESS.md:691-698).
- **Fee model (`config` fees block, `core/fees.hpp`, `backtest/fees.py`).** Keep. Paper fills understated live crypto cost 25.3x, and re-costing moved a crypto family from about -1 bp to -48.78 bp net (CONTEXT.md:63-69, PROGRESS.md:282).
- **Survivorship repair (`backtest/universe.py`, corporate-actions sweep).** Keep. The first pool build showed zero member deaths in 2023 and zero in 2024, a span containing the SVB collapse (CONTEXT.md:54, PROGRESS.md:256).
- **The classifier fail-closed rule (`backtest`, universe).** Keep. A bare-bool classifier admitted seven pooled vehicles including an S&P 500 tracker in 51 of 124 books and simultaneously excluded four large-cap asset managers (CONTEXT.md:50, PROGRESS.md:224-236).
- **The backtest harness that links the engine's own libraries.** Keep. It exists so the harness cannot measure a parallel implementation, the mismatch that benched the DNN (CONTEXT.md:100).
- **Provider health, exhaustion latch, typed transport (`llm_consensus`, `core/bridge`).** Keep. Each was written from a specific failing-open incident: a billing 429 retried as transient at scale, a generic "unreachable" that was false for three of four outcomes (CONTEXT.md:48, 78).
- **`entry_decision` recording.** Keep. Three diagnostics in a row could not attribute a filter to outcomes because rejections wrote nothing (CONTEXT.md:108).
- **Position rehydration.** Keep. Five positions were stranded across restarts, one 5.6 percent past a breached stop, because exit state lived only in memory (CONTEXT.md:112, PROGRESS.md:503-510).
- **The strategy layer and adaptive tuner.** Keep for now, on a thin basis. They exercise the loop and the tuner learns from real closed-trade PnL past a 30-trade gate, but the strategy has produced almost no real-path fills (6 lifetime native exits) so its own value is not yet measured.

The measurement discipline in `backtest/` and the research sessions is the highest-value thing here. It is what turned a plausible pitch into a set of honest negatives.

---

## Task 3 — What does not earn its place

Recommendations only. Nothing deleted. Confidence stated.

- **`news_ingestion` mock catalyst provider. Remove. Confidence high.** It emits a per-symbol hash constant that every real service now ignores (CONTEXT.md:104, 116). What would break: nothing on the real path. History lost: none of value. To prove safe: confirm no live consumer reads `catalyst_score` (the record says none does). This is the cleanest cut.
- **`research_satellite`. Remove or shelve. Confidence medium.** Every recorded pass screens out at conviction 0.0 (PROGRESS.md:530). It ships off and has never produced a thesis that acted. What would break: the sleeve split would need its satellite arm stubbed. History lost: the design intent, which is documented. To prove safe: confirm the 70/30 sleeve machinery does not assume a live satellite. Uncertain whether the sleeve accounting is load-bearing elsewhere, so shelve before removing.
- **`discovery` funnel. Do not remove, but stop carrying it as if it works. Confidence medium.** The conviction floor sits above what the pipeline produces, so the watchlist has never gained a member on merit (PROGRESS.md:103). It is dormant with a known blocker, not sound-and-waiting. To prove safe to remove: nothing, because I would not remove it. It is the one place a future information axis could plug in.
- **`rl_advisory`. Keep in tree, correct the gate, do not enable. Confidence high that it is inert.** It appears in zero recorded evaluations and is the only layer whose removal replays as neutral (PROGRESS.md:155). It is well built. The problem is not the module, it is the gate feeding it (see Task 4 and Task 4B).
- **The Dash UI (`ui/`) as a permanent second UI. Consider removing. Confidence low.** Two full UIs (Dash and React) is 2,958 plus 8,620 lines of surface. The React app is the stated primary. To prove safe: confirm no operator workflow depends on Dash-only panels. I am uncertain it is dead weight rather than a deliberate fallback, so this is a flag, not a call.

I could not connect `whale_signal` to a recorded need beyond "it is advisory and bounded." It has no demonstrated skill and it drags the gate (Task 4B). It is well written. That combination is exactly what the removal discipline is meant to catch, and the record already shows it cannot be removed for free because it participates. Keep, but see Task 4B.

---

## Task 4 — What is wrong that nobody has noticed

Every finding cites the file and the reasoning. The system has a recorded pattern of failing open. I looked for more of that shape and found it.

**4.1 The RL real-fill gate counts synthetic fills. Failing-open, hard-rule.** Detailed as lead finding 3. `count_closed_trades` (`ml_factor/real_dataset.py:193-227`) excludes `bar_source = 'synthetic'` and counts `'unknown'` as real. The `ALTER TABLE trades ADD COLUMN bar_source TEXT DEFAULT 'unknown'` (`storage/storage.cpp:115`) laundered every pre-provenance row, most of them offline synthetic fills, into the counted bucket. WEEKLOG.md:55 confirms the effect: 243 counted against 6 real-path lifetime. Verified: the code paths and the WEEKLOG note. Inferred: that the `'unknown'` mass is mostly synthetic, which I could not confirm without the database, though the operator's own note says so. The comment at `:218-219` asserts "historical fills predate the provenance column and were real," which is the invariant stated in prose and false for this database.

**4.2 The base-check gate fails open toward spending. Failing-open, cost.** `HaikuGate.should_review` returns `proceed=True` on any exception and on a missing key (`llm_consensus/gate.py:142-160`). The gate exists to screen out low-signal setups before the paid three-provider council. A gate outage therefore sends every candidate to the full paid council, the expensive direction, logged only at `warning`. This is defensible for a single trade (do not suppress a real setup on a gate hiccup) but it is the wrong default for a cost control, and it interacts badly with provider exhaustion: the same Anthropic key powers the gate and one council provider, so the conditions that error the gate are the conditions that make the spend it triggers most wasteful. Verified in code.

**4.3 `KillSwitch::trip` is a silent no-op when the switch is disabled.** `risk/risk_gate.cpp:99-105` returns `false` and does nothing if `!enabled_`. A disabled kill switch cannot trip. This is almost certainly fine because the engine enables it, but the failure mode is silent: a misconfiguration that leaves the switch disabled would make a loss-triggered or operator-triggered trip a no-op with no error. Verified in code. I did not confirm the engine always enables it, so this is a flag to check, not a confirmed defect.

**4.4 Documentation and code disagree on the RiskGate check count.** CLAUDE.md and PROGRESS.md say "14 hard checks." A later verification session recorded "eight of the RiskGate's 18 refusal sites have no test" (PROGRESS.md:554). The source has more than 14 `fail(...)` sites. The number is cosmetic, but the same session's substantive point stands: the pure predicates are well tested and the engine wiring that consumes them is not, including the four-block live gate which is never driven end to end. Verified that the count claims differ.

**4.5 The three ctest failures are a documentation-versus-reality gap, not a code defect, and they have persisted.** Multiple sessions record ctest at 24/27 or 25/28 because the operator's uncommitted `strategy.profile: active_quant` edit to the shipped config makes tests that assert shipped defaults fail (PROGRESS.md:403, 569). The record is honest that this is the "operator edits the shipped default because there is no runtime lever" pattern, and a control-file lever was later added (CONTEXT.md:102). The residue is that the shipped test suite does not pass against the file the operator actually runs, and that has been true for days. Verified from the record.

**4.6 Absence-as-evidence, the general shape, is mostly closed but the RL gate is the surviving instance.** The record has systematically closed this class: a missing volume no longer renders as zero, an absent council field no longer renders as flat, an unclassified symbol is no longer admitted, a benched factor no longer averages in as a confident zero (CONTEXT.md:50, 104, 110, 116). The RL gate (4.1) is the same shape still open: an unlabelled fill is treated as a real fill. That it survived while its siblings were fixed is itself the finding.

---

## Task 4B — The composition path specifically

I read `signal_engine/factor_engine.cpp` (`combine` at :73-138, `compose_gate_verdict` at :145-204) and the current factor writers directly.

**What dnn_rl is.** `dnn_rl` appears in no source file (`grep` across `.cpp`, `.hpp`, `.py`, `.yaml` returns nothing outside the tracking files). The engine writes exactly four factor names: `rule_based`, `dnn_advisory`, `whale_signal`, and `rl_advisory` only when `rl_enabled` (`core/engine.cpp:359-364`). The design document is `docs/DNN_ADVISORY_DESIGN.md`, renamed from `DNN_RL_DESIGN.md` on or before 2026-07-05 (PROGRESS.md:82), and CONTEXT.md:126 states plainly "The DNN factor is named `dnn_advisory`, not `dnn_rl`." The DNN and RL layers were one conceptual factor early on and were split into supervised `dnn_advisory` (serving) and PPO `rl_advisory` (shipped off) on 2026-07-05 (CONTEXT.md:130). The recorded `dnn_rl` weight of 0.1512 matches the shipped `dnn_advisory_factor_weight` of 0.15 normalised (`config/default_config.yaml:707`).

**Conclusion on dnn_rl: it is a legacy artifact of the rename, not a live factor. Nothing currently produces it.** The 2,100 `dnn_rl` rows are the DNN factor's own history under its pre-rename name. The removal session called it "a factor nobody named" and "the single largest driver" (PROGRESS.md:154), but that framing obscures the truth: it is `dnn_advisory` across a rename boundary, and it dominates the historical record only because it accumulated the most rows under its old name. Any analysis over the full record that treats `dnn_rl` and `dnn_advisory` as two factors is double-listing one factor's history. This is verified from source (the name is gone from code, the writers are the current four, the weight matches) and inferred where it touches the row counts (from the record, not a query).

**Is the weight-normalised mean the right rule.** No. `combine` computes `cv.confidence = wconf / used_weight`, the weight-normalised mean of participating factors' confidences (`factor_engine.cpp:113-126`). A factor whose confidence sits below the current mean lowers the mean when present. So a persistently pessimistic factor with no demonstrated skill suppresses trades, and its removal raises confidence and passes more of them, with no threshold changing. The record proves this on the production data: removing `dnn_advisory`, `whale_signal`, and `rl_advisory` (plus the legacy `dnn_rl` rows) changed every one of 716 evaluations and flipped 386 across the 0.65 floor, all permissive (PROGRESS.md:141-155, CONTEXT.md:46, inferred). `whale_signal` carried a mean confidence of 0.5466 and `dnn_rl` a mean of 0.2285, both nonzero-weight, both below the blend, so both were a drag rather than a contribution. A gate should ask "is the conviction high enough to trade," and averaging in the low, skill-free opinion of a factor that failed every measurement answers a different question.

**The participation rule does not cover this and should not be expected to.** `compose_gate_verdict` drops a factor reporting `participating=false` from the denominator and deliberately keeps a participating factor reporting genuine low confidence (`:168-179`), because excluding a real low read would inflate confidence on a weak setup. A benched factor and a pessimistic-but-participating factor are indistinguishable in a mean and are opposite cases. This is correct as far as it goes. It means the mean rule cannot be rescued by the participation flag. The composition rule itself is what needs rethinking, and the honest options are: exclude a factor with no demonstrated skill from the confidence denominator entirely (make it advise direction and sizing only, not the gate), or replace the mean with a rule where an unskilled low read cannot pull a strong native conviction under the floor.

**Does the effective gate match the documented one.** No. The documented gate is `min_confidence_default` 0.65, a Level-1 value, presented as a floor on a trade's confidence (`risk/risk_gate.cpp:75`). The effective gate is a floor on a weighted average of the native conviction and several advisory opinions, so the native signal must clear a bar well above 0.65 to pull the average over it, and the factors that failed every measurement move that bar. On the fast tier the record already had to patch this twice: excluding the un-run council (`council_ran`, 2026-07-15) and excluding a benched dnn (participation, 2026-07-23), each because a structural zero was dragging genuine conviction under the floor (CONTEXT.md:110, 146). Those patches treated symptoms. The mean is the cause.

---

## Task 5 — Where the discipline is thinner than it claims

The project claims pre-registration before looking, a holdout touched once, and errors clustered by the right unit. Checked against the record and the code, the discipline is real and unusually strong, and it has three thin spots, two of which the record confesses itself.

**Pre-registration is real and commit-anchored.** Sessions record the pre-registration commit hash before computation: `b819bf7` and an amendment `8eb78be` before scoring (PROGRESS.md:191), `8ef4988` (PROGRESS.md:161), `00c2d17` (PROGRESS.md:240), `a0a9ef6` as the standing holdout (PROGRESS.md:235). This is stronger than most research hygiene. I did not verify the hashes against git history, because this checkout's git begins 2026-07-23 and the earlier commits are not present here. That is a verification gap, not evidence of a problem.

**Holdout touched once is claimed and internally consistent.** "Fit inspected first, holdout evaluated ONCE after, no specification changed in between" (PROGRESS.md:240), and "NOTHING RE-SCORED ... prior and future results are not comparable across the correction" (PROGRESS.md:235). Two fit-time fixes are disclosed as made toward the committed spec before the holdout was touched, with both sets of numbers stated (PROGRESS.md:249, 265). I cannot independently confirm the holdout was opened exactly once, but the record does not contradict itself on this point.

**Thin spot one, confessed: the pre-registered clustering unit did not absorb the effect it needed to.** The 2026-07-27 scoring session pre-registered the symbol as the clustering unit, then found that clustering on symbol cannot absorb an asset-class mix effect, because a symbol belongs entirely to one class and the between-class difference passes through the cluster correction untouched (PROGRESS.md:165). Two primaries crossed the Bonferroni bar (abstention z 2.66, rejection z -2.581) and both dissolved on decomposition into a disguised crypto-versus-equity comparison (PROGRESS.md:163). The clustering was the wrong unit for the question, the session says so, and it recorded the lesson rather than reporting the two crossings as findings. This is the discipline working, but it is also a case where the pre-registered method was insufficient and the crossings would have been reportable to a less careful reader.

**Thin spot two, confessed: a per-trade standard error treated correlated trades as independent.** For H-A, "the registered per-trade SE wrongly treated five correlated same-night trades as independent, an owned specification error" (PROGRESS.md:287). As registered the effect read z 2.91 and crossed the bar. Properly clustered by night it reads z 1.73 with an interval spanning zero. The as-registered number was the more confident one, and the honest reading is the weaker one. The session reports both and disqualifies the hypothesis. Again the discipline caught it, and again the registered specification was the more permissive one.

**Thin spot three, my observation: a benchmark implementation was corrected after seeing the data, in the direction that weakened the result, which is the safe direction but is still a post-hoc change.** The unconditional benchmark used a 48-bar step that crossed the overnight gap on equities and inflated the benchmark, and fixing it cut Task 1's pooled z from 4.974 to 2.66 (PROGRESS.md:167). The change was toward the committed 4-hour spec and moved the result the uncomfortable way, so it is defensible and was disclosed. It is still a specification touched after data were seen, and I note it because the project's own standard is that specifications do not change after looking. The record frames it as an implementation corrected toward the spec, which is the right frame, but a stricter reading would have frozen the benchmark before the first score.

**A claim the code does not fully support.** The RL gate is described as counting real fills (CLAUDE.md hard rule, `real_dataset.py:207`), and WEEKLOG reports it as 243 of 500 progress. The code counts `'unknown'` as real and the production `'unknown'` bucket is dominated by synthetic fills (Task 4.1). The tracking file states the caveat in one line (WEEKLOG.md:55) but the headline number is quoted without it. The "trains only on real fills" claim is not enforced by the gate that is supposed to enforce it.

**On confidence of reporting overall.** The three council sessions are, if anything, reported less confidently than their method supports. A +92.3 bp thin-sample result was explicitly not called a finding (PROGRESS.md:212), and when the wide sample returned a powered negative the prior positive was named as noise (PROGRESS.md:195). The direction of error in this project is toward under-claiming, which is the rarer and better direction. The thin spots above are real but they are self-caught, and the pattern is a team correcting itself in public rather than hiding a result.

---

## Task 6 — What I would do next

**State it plainly: the price-only research program is finished, and it succeeded at proving a negative.** Seven hypothesis families are dead against buy-and-hold-after-costs, the council does not predict price at any size this system could trade, and the honest boundary is drawn: an effect small enough to survive the intervals would clear neither the 50 bp crypto round trip nor the 2,500 USD capacity floor (PROGRESS.md:206, CONTEXT.md:58-60). Continuing to test price-based hypotheses at Level-1 sizing is not worth doing, and the record already says so.

**So the realistic options are three, and I would not pretend they are all good.**

1. **Stop trading research and keep the system as a demonstration of disciplined negative research.** This is the honest high-value outcome. The safety spine, the provenance and fee and survivorship infrastructure, and the measurement harness are a genuine asset independent of any edge. Preserve them, turn off the advisory layers that failed measurement, and stop spending on the council.

2. **Open a genuinely new information axis.** The record itself names breadth as the only thing that changed the calculus and then showed even breadth produced no survivor at tradeable width because the Level-1 five-position limit is binding (PROGRESS.md:242, 250). A new axis (fundamentals, alternative data, a different holding period, or a capacity model that does not fight the position limit) is the only path that is not re-running a settled negative. This is real work with an uncertain payoff, and it should start from a pre-registration against the corrected universe.

3. **Wipe or archive.** The operator considered this and was advised against it. I agree it should not be wiped, because the infrastructure and the recorded reasoning are the valuable part and they are worth keeping even if no strategy ever ships. Archive-and-preserve is strictly better than wipe.

**What I would fix regardless of the path, because they are correctness, not strategy.** Correct the RL real-fill gate to count only provenance-confirmed real fills (Task 4.1). Reconsider the composition rule so unskilled factors do not gate trades (Task 4B). Remove the dead `news_ingestion` mock (Task 3). Decide the base-check gate's fail direction deliberately (Task 4.2). None of these enable live trading and none touch a Level-1 value.

**What I would not do.** I would not enable RL, the council live path, discovery, or live trading on this evidence. Nothing has earned that, and the gates are the plan.

---

## Verified versus inferred

**Verified by reading source or the tree in this session:** the composition mean rule and the gate wiring; the RiskGate logic and the 0.65 floor; the absence of `dnn_rl` from all source and the current four factor writers; the DNN document rename; the `dnn_advisory` weight of 0.15; the RL gate counting `'unknown'` as real and the `ALTER` default of `'unknown'`; the synthetic-regime feed tagging bars `kSynthetic`; the base-check gate's fail-open on error and missing key; the kill switch's no-op when disabled; the per-directory line counts; that no database file exists in this checkout; that git history here begins 2026-07-23 with 50 commits.

**Inferred from the tracking files, not reproduced by me:** all row counts, means, and replay results (716/386, whale 2,162 rows at 0.5466, dnn_rl 2,100 rows at 0.1512/0.2285, RL 243 versus 6 real); the council negative (274 calls, 80 clusters, the interval); the seven-family results; the fee, survivorship, provenance, and classifier incident histories; the pre-registration commit hashes; the WEEKLOG counter reading. I could not open the production database, so wherever a number came from a query, it came from the record, not from me.

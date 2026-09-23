# CLAUDE.md — AiTrader / Market AI Lab

## Read first: current phase and session rules (added 2026-09-23)

The repo is in **Stage B** of the pre-registered news-drift experiment.
EXPERIMENT.md is ACCEPTED and BINDING (Amendments 1 to 7). The engine
build described under "Project context" below is historical context for
the code, not the current work. Where this section conflicts with older
text in this file, this section wins.

- Stage plan and status: docs/STAGES.md. Locked decisions: docs/DECISIONS.md.
- Orchestration reasoning, the prompt skeleton and launch: docs/ORCHESTRATION.md.
- How the planning chat writes prompts, and the return-document format:
  docs/PROMPT_WRITING.md. Every stage prompt as sent: docs/prompts/.

### Invariants (every session)

- Status check at start and end, output copied verbatim into the return
  document. Counts must not drop between the two:
  `systemctl --user is-active news-collect.timer; tail -8 COLLECTION_LOG.md; sqlite3 news_experiment.db "SELECT COUNT(DISTINCT query_date), COUNT(*), SUM(state='judged') FROM news_observation WHERE run_kind='collection';"`
- EXPERIMENT.md: no edit unless the stage prompt carries an amendment the
  user wrote or approved, and never after any outcome has been computed.
- Outcome blindness until a Stage C prompt unlocks it: do not run
  news_experiment/outcomes.py or news_experiment/scoring.py on collection
  rows, and do not read, print, aggregate or plot any return, excess,
  benchmark or cost column (excess_1session, net_bp, ret_*, bench_*,
  cost_bp_round_trip) or any table holding them. Counts by state,
  judgment, strength, error_class, stratum and query_date are allowed.
- Collector untouched: news_experiment/collect.py, daily.py, store.py,
  universe.py, spec.py, horizon.py, dedup.py, maintain.py, the user units
  in ~/.config/systemd/user, writes to news_experiment.db, and
  COLLECTION_LOG.md (the wrapper appends to it). Never stop, restart or
  edit news-collect.timer or news-collect.service. Read-only SELECTs on
  allowed columns only.
- Gaps stay gaps. Never backfill a missing session.
- The experiment key (anthropic_experiment_key) spends only through the
  collector. Any other paid call needs a logged quote and explicit
  approval in the stage prompt.
- Do not touch RiskGate logic, the live-trading gate, or the adaptive
  limit-weakening invariant. Live trading stays off. Services bind
  loopback. Never print or log a key value.
- No commits unless the stage prompt asks for one. Never force-push.

### Roles

The session reading this file is the LEAD. Default lead model: Opus 5.5
(the `opus` alias). The lead plans, delegates, verifies and synthesizes.
It does not write bulk code, parse logs or run long jobs itself. It keeps
for itself: decomposing the stage and routing each subtask, any
pre-registration or amendment text, judgments on statistical results
(cluster bootstrap, permutation null, power), the final synthesis written
against the original stage prompt, and any decision the prompt reserves.

### Model and effort routing

Route by decision complexity and silent-failure risk, not by task label.
Worker models: haiku, sonnet, opus, fable. Efforts: medium, high, xhigh,
max. No low effort.

| Work | Model | Effort |
|---|---|---|
| Pure extraction: reading, parsing, tabulating files, logs and allowed columns into a fixed schema. No interpretation | haiku | medium |
| Complex extraction: joining sources, messy inputs, light reading comprehension. Still no conclusions | sonnet | medium |
| Mechanical: running a written script, applying a decided edit, test boilerplate | sonnet | medium, or high for multi-part steps |
| Standard coding: modules to spec, harness changes, debugging, test design | opus | high; xhigh when touching news_experiment/, risk/, execution/ or the live gate |
| High-level work: hard reasoning, statistical design, synthesis, drafting with judgment | opus | xhigh, or max for the hardest single pieces |
| Independent or adversarial work: verification of any number entering a verdict, leakage, look-ahead and outcome-exposure audits, review of statistical code | fable | xhigh |
| The single adversarial call a stage hinges on, or a disputed verification | fable | max |

- State model and effort for every subtask before spawning.
- Promote on failure: rerun a failed subtask one tier up. Never demote
  judgment work to save usage.
- Haiku extracts and never interprets, and its output carries row counts
  and source references. Sonnet makes no design or statistical decisions.

### Spawning and budget

- Agent tool: effort is fixed by the agent file, the model is set per
  call. Use .claude/agents/worker-medium, worker-high, worker-xhigh,
  worker-max and always pass `model`. Dynamic workflows set both:
  `agent(prompt, { model: 'opus', effort: 'high' })`. If a model rejects an
  effort level, drop one level and log it.
- The Agent call's description is `<Role>-<Model><Effort>`, for example
  `LogReader-HaikuMed`, `ScoringCoder-OpusXHigh`, `NumberVerifier-FableXHigh`.
- At most 4 subagents at once (.claude/settings.json). Workers do not spawn
  workers unless the prompt says so. Each spawn costs roughly 25k to 35k
  tokens of setup, so small tasks go inline.
- Every brief gives one objective, input paths, an output path and format,
  allowed tools, and boundaries.

### Artifacts, verification, checkpoints

- Workers write full results to reports/ or the stage scratch path and
  return the path, a summary of at most 200 words, and anything
  unfinished. They return failures and non-survivors, not only winners.
  The lead reads the artifact files for anything entering the synthesis.
- Every number entering a verdict gets an independent fable xhigh check by
  a worker that did not produce it, recomputed from raw inputs.
- After each task, append status to reports/<stage>_STATE.md (done,
  running, next, artifact paths, times). On resume, read it first and skip
  finished tasks. The user is not watching: do not stop to ask whether to
  continue. If Fable usage runs out, Fable-routed checks stay pending in
  the STATE file rather than being downgraded.

### ETA tables and session cost

- Estimate table in chat after planning, before the first spawn: one row
  per task and per spawn with owner, model, effort, parallel or serial,
  ETA and cumulative ETA. Say which rows are guesses. Revise in chat when
  the cumulative ETA moves by more than 30 minutes or the user asks.
- Final table at the end, in chat and in the return document: actual
  start and end, time taken, tokens per spawn from the transcripts,
  status and deviations, a cumulative row set against the estimate, with
  pauses shown separately.
- Session cost section: wall-clock time, tokens per model (input, output,
  cache read, cache creation) summed from this session's transcript and
  its subagent transcripts under
  ~/.claude/projects/-home-kiros-li-Documents-GitHub-AiTrader/, one line
  per spawn, lead versus worker share. Token counts only, never estimated.
  If the transcripts are unreadable, say so and report time only.

### Return document

Every session ends by writing reports/<STAGE>_RETURN.md in the eight-part
format in docs/PROMPT_WRITING.md section 4. PROGRESS.md and RETURN.md each
get a short dated entry pointing to it, which satisfies the logging rule
under "Project context".

### Compute limits (stability over speed)

The ThinkPad has 14 GB of RAM and a recorded out-of-memory incident.
- Parallel compute: at most `os.cpu_count() // 2` workers, never more than
  8, and one heavy computation at a time across the lead and all workers.
- Long jobs run at low priority (`nice -n 10` or `os.nice(10)`), write
  progress to disk, and resume by skipping finished pieces.
- Check free memory before any job longer than a few minutes. If the
  estimated peak exceeds half of what is free, chunk it.
- Keep heavy work out of the collector window (about 15:30 to 16:30 PT on
  weekdays) and never starve news-collect.service. A PropExperiment
  session running at the same time shares this machine.

## Project context

AiTrader (Market AI Lab) is a **C++20-first algorithmic trading platform that trades US EQUITIES ONLY**.

**SCOPE, narrowed 2026-07-27 on measured evidence.** Crypto is **collected and never traded**. A crypto round trip costs 50 bp against roughly 0.5 to 0.9 bp for the tier-1 equities the engine trades, the re-costed P26 result splits -48.78 bp crypto against -2.73 equity, and the council abstained on 87 to 94 percent of crypto calls against 43 to 47 percent on equities. **Corrected 2026-07-29:** the figure previously cited here, 1.14 to 4.87 bp for the tradeable bands, was the one-tick floor. The measured fee model puts tiers 3 and 4 at about 17.8 and 41.2 bp median round trip, so tier 4 sits within 20 percent of crypto's 50 bp. The exclusion conclusion stands because the engine trades tier-1 names, but the wide-band cost gap this sentence once relied on is gone and the reasoning is recorded as narrowed. Crypto also carried a 24/7 loop, regional-session carve-outs, and its own fee schedule. **This is a SCOPE change, not a deletion**: bars still poll, carry provenance, and store; every stored crypto row stays; the crypto fee schedule stays in the model; the venue plumbing stays wired. Restoring crypto means adding one class to `mal::scope` (`core/trading_scope.hpp`) and `market_data.tradeable.TRADEABLE_ASSET_CLASSES`, and nothing else. The exclusion lives at the **universe layer** so every consumer inherits it rather than each path filtering separately. **The loop collects continuously and restricts ENTRY to US regular trading hours; exits are never restricted and a position is never trapped.**

Read PROGRESS.md and CONTEXT.md at the start of each session. Update PROGRESS.md at the end of each session with a dated log entry, newest at top. Update CONTEXT.md when a significant decision or API quirk is discovered. Log every user prompt to RETURN.md before starting work, newest at top, recording the prompt, model, changes, and commit message.

- **C++20 is the primary language** for the engine core: the deterministic risk gate, execution/mode router, signal combination, adaptive tuner, account/venue state, storage DAO, and the run loop. Python is the secondary tier: advisory services (LLM consensus, DNN factor, whale signals), the market-data/execution bridge to Alpaca, and the dashboard.
- **Paper trading is the default and the continuous training environment.** The engine runs a continuous paper loop offline with deterministic mocks and needs no API keys. **The loop collects around the clock and takes ENTRIES only inside US regular trading hours**, because material news arrives after the close and must still be recorded, while an after-hours fill is a thin-market artifact that corrupts validation data. Exits are exempt at every hour.
- **The dashboard is a first-class control surface**, not an afterthought — a Plotly Dash app (Paper / Live / Advanced / Accounts tabs) that reads the shared SQLite database and exposes the kill switch, weight controls, the L1 risk-gate editor, and the live-approval readiness view.
- **Live trading is disabled by default and sits behind an explicit in-app approval gate.** It is never on unless a human turns it on through that gate.
- **Layered decision logic:** a deterministic static-safety layer has final authority; an adaptive layer tunes only within safe bounds; the DNN/RL factor and whale/smart-money signals are **advisory inputs only** and never control execution on their own.
- **As of 2026-07-27 the advisory layers are PRESENT BUT DEACTIVATED BY ZERO WEIGHT, pending a measurement that justifies them.** `dnn_advisory` and `whale_signal` carry weight 0.0 in `model_weights`, and `rl_advisory` already did. Every code path stays wired and callable, so restoring a weight reactivates a layer with no other change. **Composed confidence therefore reflects only factors with a measured basis**, which today means the native `rule_based` signal and the council slots. The reason is arithmetic rather than distaste: composed confidence is the weight-normalised MEAN of participating factors, so a factor with no demonstrated skill does not sit neutral, it drags the mean and changes what clears the Level 1 floor while no threshold moves. A factor earns its weight by measurement. See CONTEXT.md Key Decisions.
- **Communication:** the C++ core is the sole writer of the SQLite operational tables; the Python UI/services read from it. The C++ engine reaches the Python advisory services over a small JSON-over-HTTP bridge (`python_bridge/`, localhost) when enabled.

**Tree note (2026-07-27).** `OLD/` holds files nothing references, with the per-file evidence in `OLD/README.md`. `news_ingestion/` is gone: its C++ mock produced a hash of the symbol as a catalyst score, which every real service already ignored, and removing it also fixed the `tuner_floor` failure. **The DNN model registry is DATABASE-backed (`model_registry`), and it is separate from serving, which is FILE-backed (`ml_factor/models/champion.npz`).** Production's registry is empty and that is correct: no promotion has ever run against it, so `bench_state` reports the champion benched and serving the synthetic bootstrap.

See `AUDIT.md` for the current honest state of each layer (what is real vs. scaffolding) and `README.md` / `docs/ARCHITECTURE.md` for the design.

## Build order (do not skip ahead)

Historical. This was the engine build order. The current plan is docs/STAGES.md.

1. Static safety layer with working kill switch and live-trading gate
2. Alpaca paper trading integration only
3. Two native strategies (trend/momentum + mean reversion) plus a regime detector, evaluated on closed bars, to exercise the loop
4. Basic dashboard showing live trades, P&L, win/loss, kill-switch control
5. STOP. Verify the full loop is stable before adding any other venue, the LLM council, the `dnn_advisory` factor, or whale tracking.

## Hard rules

- Live trading off by default, behind explicit in-app approval gate
- The `dnn_advisory` (advisory DNN) and `rl_advisory` factors and whale signals are advisory, never sole execution controllers
- RL ships toggled off, trains only on real fills, and activates only past the `rl_min_real_fills` gate
- Never hardcode API keys; use env vars or a key-gated config
- LLM council model strings: `claude-opus-4-8` (Anthropic), `gpt-5.5` (OpenAI), `gemini-3.1-pro-preview` (Google, the reachable id for Gemini 3.1 Pro). Base-check gate: `claude-haiku-4-5` (via the Anthropic client, shares ANTHROPIC_API_KEY). These are the only approved model strings; do not invent others. Verified reachable 2026-07-12 via `scripts/list_provider_models.sh`. OpenAI GPT-5 family request shape: use `max_completion_tokens` (not `max_tokens`) and omit `temperature` (only the default is allowed). **Anthropic `claude-opus-4-8` has the SAME quirk and it cost a whole measurement arm on 2026-07-28: sending `temperature` returns `HTTP 400 invalid_request_error, "`temperature` is deprecated for this model"`. OMIT `temperature` for Opus 4.8.** `claude-haiku-4-5` accepts `temperature: 0` normally.
- Paper trading is the continuous default training environment
- **US equities only.** Crypto is collected and never traded, excluded at the universe layer (`core/trading_scope.hpp`, `market_data.tradeable.TRADEABLE_ASSET_CLASSES`). The data path, stored history, crypto fee schedule, and venue plumbing are all retained deliberately
- **Level 1 values as shipped (re-derived 2026-07-27, previously frozen since the project began):** sizer `default_risk_per_trade_pct` **0.02**, per-trade ceiling `max_trade_risk_pct_of_equity` **0.025**, `max_open_positions_total` **10**, `max_open_positions_per_venue` **10**, `max_total_open_risk_pct` **0.25**, `max_exposure_per_category_pct` **0.25**, `max_consecutive_losses` **6**, `max_trades_per_day` **10** and `max_daily_loss_total_pct` **0.03** both unchanged. **THE SIZER AND THE CEILING ARE DISTINCT QUANTITIES and neither is derived from the other**: the sizer decides what is SENT, the ceiling decides what is PERMITTED. **Every Level 1 key is now enforced somewhere**, audited 2026-07-27 and guarded by `tests/test_level1_enforcement.py`. `max_trade_notional_cap_pct` and `default_position_sizing_method` were REMOVED for being enforced nowhere, following the 2026-07-18 removal of the two position-scale caps. **The consecutive-loss brake now RELEASES after `cooldown_minutes_after_loss_breach`**: it previously cleared only on a win while refusing the entries that could produce one, an absorbing state responsible for 82.5 percent of every recorded RiskGate block. Derivations in RETURN.md 2026-07-27.
- Safety and manual user control override all intelligence layers

## Working agreement

- Before adding a feature, confirm the vertical slice above is stable
- Keep the architecture modular so layers can be added cleanly
- Prefer established libraries over hand-rolled code for backtesting, market-data normalization, and ML

## Queue

Stage prompts now live in docs/prompts/ and are pasted or launched directly (docs/ORCHESTRATION.md). The queue below stays opt-in and is not the normal path.

A `queue/` directory at the repo root holds inbound prompt files written by chat Claude, named `NNN-short-name.md`. Each file names its model at the top and carries a Status line.

- The queue is OPT-IN and is NOT read at the start of a session. Read it only when the operator asks, in words like "run the queue".
- A pasted prompt is the normal path. When a prompt is pasted directly, ignore `queue/` entirely: do not open, scan, or list it. If the pasted prompt is recognisably the same work as a file there, mark that file DONE and move it to `queue/done/` at the end, and do nothing else with it.
- When running the queue, take the lowest-numbered file whose Status is PENDING and execute it as a normal prompt, including logging it to RETURN.md before work begins. Then set Status to DONE and move the file to `queue/done/`.
- Files whose Status is not PENDING are not picked up.
- Chat Claude writes only prompt files and the queue README, never code, config, or the four tracking files. Everything outside `queue/` remains Claude Code's alone to change.
- If a queue file conflicts with CLAUDE.md, CLAUDE.md wins and the conflict is reported rather than resolved silently.

# CLAUDE.md — AiTrader / Market AI Lab

## Project context

AiTrader (Market AI Lab) is a **C++20-first algorithmic trading platform that trades US EQUITIES ONLY**.

**SCOPE, narrowed 2026-07-27 on measured evidence.** Crypto is **collected and never traded**. A crypto round trip costs 50 bp against 1.14 to 4.87 bp for equities in the tradeable liquidity bands, the re-costed P26 result splits -48.78 bp crypto against -2.73 equity, and the council abstained on 87 to 94 percent of crypto calls against 43 to 47 percent on equities. Crypto also carried a 24/7 loop, regional-session carve-outs, and its own fee schedule. **This is a SCOPE change, not a deletion**: bars still poll, carry provenance, and store; every stored crypto row stays; the crypto fee schedule stays in the model; the venue plumbing stays wired. Restoring crypto means adding one class to `mal::scope` (`core/trading_scope.hpp`) and `market_data.tradeable.TRADEABLE_ASSET_CLASSES`, and nothing else. The exclusion lives at the **universe layer** so every consumer inherits it rather than each path filtering separately. **The loop collects continuously and restricts ENTRY to US regular trading hours; exits are never restricted and a position is never trapped.**

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
- LLM council model strings: `claude-opus-4-8` (Anthropic), `gpt-5.5` (OpenAI), `gemini-3.1-pro-preview` (Google, the reachable id for Gemini 3.1 Pro). Base-check gate: `claude-haiku-4-5` (via the Anthropic client, shares ANTHROPIC_API_KEY). These are the only approved model strings; do not invent others. Verified reachable 2026-07-12 via `scripts/list_provider_models.sh`. OpenAI GPT-5 family request shape: use `max_completion_tokens` (not `max_tokens`) and omit `temperature` (only the default is allowed).
- Paper trading is the continuous default training environment
- **US equities only.** Crypto is collected and never traded, excluded at the universe layer (`core/trading_scope.hpp`, `market_data.tradeable.TRADEABLE_ASSET_CLASSES`). The data path, stored history, crypto fee schedule, and venue plumbing are all retained deliberately
- Safety and manual user control override all intelligence layers

## Working agreement

- Before adding a feature, confirm the vertical slice above is stable
- Keep the architecture modular so layers can be added cleanly
- Prefer established libraries over hand-rolled code for backtesting, market-data normalization, and ML

## Queue

A `queue/` directory at the repo root holds inbound prompt files written by chat Claude, named `NNN-short-name.md`. Each file names its model at the top and carries a Status line.

- The queue is OPT-IN and is NOT read at the start of a session. Read it only when the operator asks, in words like "run the queue".
- A pasted prompt is the normal path. When a prompt is pasted directly, ignore `queue/` entirely: do not open, scan, or list it. If the pasted prompt is recognisably the same work as a file there, mark that file DONE and move it to `queue/done/` at the end, and do nothing else with it.
- When running the queue, take the lowest-numbered file whose Status is PENDING and execute it as a normal prompt, including logging it to RETURN.md before work begins. Then set Status to DONE and move the file to `queue/done/`.
- Files whose Status is not PENDING are not picked up.
- Chat Claude writes only prompt files and the queue README, never code, config, or the four tracking files. Everything outside `queue/` remains Claude Code's alone to change.
- If a queue file conflicts with CLAUDE.md, CLAUDE.md wins and the conflict is reported rather than resolved silently.

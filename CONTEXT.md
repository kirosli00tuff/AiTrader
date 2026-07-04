# Project Context

The reasoning behind AiTrader. Read at the start of each session. Update when a significant decision or API quirk is discovered.

## Why This Project Exists

A 24/7 paper and live AI auto-trading platform. Four layers: static safety, adaptive strategy, DNN advisory, whale advisory. Paper trading is the default and primary training environment. Safety is the final authority and cannot be weakened by any intelligence layer.

## Key Decisions and Rationale

- Alpaca chosen as first real venue. Safest and easiest paper API.
- Coinbase replaces Binance for direct crypto market access. Binance does not operate in Canada. Alpaca crypto remains the paper execution venue.
- LLM council uses three models for reasoning diversity: gpt-5.5, claude-opus-4-8, gemini-3.1-pro.
- Gemini 3 Flash used as a free base-check gate. Screens signals before the paid council, cutting cost.
- Council runs only on native strategy signals, never on a timer or per tick. Cost control.
- Native strategy layer blends momentum and mean reversion with a regime detector. Research shows the blend delivers smoother risk-adjusted returns across regimes than either alone.
- Whitelist limited to high-liquidity majors: BTC, ETH, SPY, QQQ. Mean reversion holds up best in liquid assets. Both strategy families fail on thin alts.
- Whale layer capped at 0.35 advisory weight. Never decisive.
- Adaptive tuner learns from REAL closed-trade PnL, not a simulator. `simulate_outcome` was removed from the default path (Task 3); the tuner may not nudge weights until ≥30 closed native trades have accumulated (thin-evidence guard). That ≥30 rule is a pure predicate (`learning/adapt_gate.hpp`) so it is unit-testable without a full Engine.
- The DNN factor is named `dnn_advisory`, not `dnn_rl`: it is a supervised advisory factor today. True RL is deferred until ≥500 real closed fills (Task 5). Advisory sizing cap stays 0.5 regardless of which model serves.
- Model promotion is GATED: a real-data challenger only becomes champion on an explicit operator action, and only if it was trained on real data with ≥200 samples, beats the champion on walk-forward Sharpe, and has no worse drawdown (`registry.meets_promotion_criteria`). Walk-forward validation is chronological (expanding folds) — never a random split.
- Cost controls are split by owner: the C++ engine enforces daily budget + per-symbol cooldown + neutral-regime skip (`signal_engine/council_gate.cpp`); the Python side caps every provider response at `council_max_tokens`. Config surfaced via the `council:` block.
- Bridge binds loopback-only by default; remote bind requires an explicit `BRIDGE_ALLOW_REMOTE=1` opt-in. All log output is passed through credential masking (`account_manager/log_safety.py`), and a pre-commit hook scans staged content for credential shapes (Task 9).

## Strategy Rationale

- Momentum has deep academic support. Jegadeesh and Titman 1993 documented past winners beating past losers by roughly 12 percent annual excess return, replicated across decades and asset classes.
- Mean reversion works in range-bound liquid markets, fails in strong trends.
- No single strategy survives all regimes. A regime detector shifts weight between the two. This addresses the biggest documented failure mode.
- Transaction costs erode high-frequency mean reversion. Trade less often. Every backtest includes realistic fees and slippage.
- LLM trading evidence is promising but unproven. A 2026 audit of 77 studies found underreported costs and test sets. Council stays one advisory input with adjustable weight, earning trust through paper results.

## Whale Tracking Decisions

- Crypto: ClankApp, free, 8 chains, already the default adapter. Zero cost.
- Equities: SEC EDGAR, free, official government data, no key, adapter stubbed. 13F filings lag 45 days, useful for slow-money context. Form 4 insider trades post within two business days, more actionable.
- Total whale tracking cost: zero.
- Paid upgrades deferred until the free signal proves useful on paper: Whale Alert at 29.95 per month for crypto, Unusual Whales at 50 per month for equities. Reserved env vars WHALE_ALERT_API_KEY and UNUSUAL_WHALES_API_KEY.

## API Notes and Quirks

- SEC EDGAR requires a User-Agent header with app name and contact email. No header means blocked requests. Fair-use limit around 10 requests per second.
- ClankApp response shape needs verification against live data before trusting parsers.
- Alpaca paths verified for paper orders and market data. No live brokerage path.
- Record real API responses as test fixtures for every external feed. One malformed parse in a money loop introduces silent bad data.

## Cost Notes

- Full council calls three flagship models per decision. Gate first with free Flash to skip low-value setups.
- Prompt caching used for fixed system prefixes to lower repeat-call cost.
- Council daily budget capped at 30 calls. Per-symbol cooldown 60 minutes.
- Bot 24/7 usage needs API billing, not a Pro subscription. Machine traffic, not human chat.

## Owner Working Style

- Prefers clear, spartan, active-voice communication.
- No em dashes. No markdown in chat replies. No filler adjectives.
- Wants the model named before each prompt.
- Uses CLAUDE.md for rules, PROGRESS.md for status, CONTEXT.md for reasoning, RETURN.md for prompt outputs and prompt log.

## Model Selection Guide

- Opus for architecture, safety-critical code, complex multi-file logic
- Sonnet for routine edits, file creation, docs, tests, config
- Haiku for one-liners, searches, trivial fixes

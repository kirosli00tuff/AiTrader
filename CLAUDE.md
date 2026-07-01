# CLAUDE.md — AiTrader / Market AI Lab

## Project context

AiTrader (Market AI Lab) is a **C++20-first, multi-venue algorithmic trading platform**.

- **C++20 is the primary language** for the engine core: the deterministic risk gate, execution/mode router, signal combination, adaptive tuner, account/venue state, storage DAO, and the run loop. Python is the secondary tier: advisory services (LLM consensus, DNN factor, whale signals), the market-data/execution bridge to Alpaca, and the dashboard.
- **Paper trading is the default and the continuous training environment.** The engine runs a 24/7 paper loop offline with deterministic mocks and needs no API keys.
- **The dashboard is a first-class control surface**, not an afterthought — a Plotly Dash app (Paper / Live / Advanced / Accounts tabs) that reads the shared SQLite database and exposes the kill switch, weight controls, the L1 risk-gate editor, and the live-approval readiness view.
- **Live trading is disabled by default and sits behind an explicit in-app approval gate.** It is never on unless a human turns it on through that gate.
- **Layered decision logic:** a deterministic static-safety layer has final authority; an adaptive layer tunes only within safe bounds; the DNN/RL factor and whale/smart-money signals are **advisory inputs only** and never control execution on their own.
- **Communication:** the C++ core is the sole writer of the SQLite operational tables; the Python UI/services read from it. The C++ engine reaches the Python advisory services over a small JSON-over-HTTP bridge (`python_bridge/`, localhost) when enabled.

See `AUDIT.md` for the current honest state of each layer (what is real vs. scaffolding) and `README.md` / `docs/ARCHITECTURE.md` for the design.

## Build order (do not skip ahead)

1. Static safety layer with working kill switch and live-trading gate
2. Alpaca paper trading integration only
3. One trivial strategy (e.g. moving-average cross) to exercise the loop
4. Basic dashboard showing live trades, P&L, win/loss, kill-switch control
5. STOP. Verify the full loop is stable before adding any other venue, the LLM council, DNN/RL, or whale tracking.

## Hard rules

- Live trading off by default, behind explicit in-app approval gate
- DNN/RL and whale signals are advisory, never sole execution controllers
- Never hardcode API keys; use env vars or a key-gated config
- LLM council model strings: `claude-opus-4-8` (Anthropic), `gpt-5.5` (OpenAI), `gemini-3.1-pro` (Google). Free base-check gate: `gemini-3-flash`. These are the only approved model strings; do not invent others.
- Paper trading is the continuous default training environment
- Safety and manual user control override all intelligence layers

## Working agreement

- Before adding a feature, confirm the vertical slice above is stable
- Keep the architecture modular so layers can be added cleanly
- Prefer established libraries over hand-rolled code for backtesting, market-data normalization, and ML

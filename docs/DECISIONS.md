# Locked decisions

Current-phase decisions. Older engine-era decisions stay in CONTEXT.md.

- Scope: the experiment scores US single-name equities. Funds are excluded
  and the classifier fails closed. ETFs do not fit the premise (single-name
  news drift) and are not traded.
- Experiment model: Claude Haiku 4.5 (`claude-haiku-4-5`), temperature 0,
  on the separate experiment key (`anthropic_experiment_key`, latch label
  `anthropic_experiment`), never the council key. EXPERIMENT.md
  Amendment 3.
- Universe: ADV 2.07M to 65.3M USD, price floor 10 USD, four log-ADV
  strata, 400 names by seeded stratified sample, quarterly formation.
  EXPERIMENT.md Amendments 1 and 2.
- Gaps are unrecoverable by design. Filling one would query historical
  news and break the forward-only design.
- Live venue: Interactive Brokers through IB Gateway. Alpaca stays the
  market-data and paper source during Stage B. The Alpaca paper account's
  equity is not evidence (July engine positions, beta).
- Benchmark for Stage D: beat SPY or QQQ buy-and-hold at the same capital,
  net of fees and taxes. Pre-registered as the Stage D gate before D.1.
- Orchestration (2026-09-23, ported from PropExperiment): stage sessions
  run an Opus 5.5 lead that plans, routes, verifies and synthesizes, with
  workers on haiku (pure extraction only), sonnet, opus or fable at
  medium, high, xhigh or max. Fable is for independent and adversarial
  verification only. Concurrency capped at 4. Rules in CLAUDE.md,
  rationale and template in docs/ORCHESTRATION.md, prompt-writing rules in
  docs/PROMPT_WRITING.md.
- Unchanged hard rules: RiskGate logic, the live-trading gate and the
  adaptive limit-weakening invariant are never touched. Live trading is off
  by default. Services bind loopback. Keys are never logged.
- 2026-09-28 (user, planning chat): Phidias Propfirm researched as a
  funded venue candidate for AiTrader after Stage C, because its Premium
  tier is a swing account and AiTrader's signal is a next-session hold.
  Recorded, not adopted. Venue for Stages D and E stays IBKR.
  - What fits: Premium permits overnight and weekend holding with no
    same-day flatten, and uses an EOD trailing drawdown. That matches a
    next-session hold.
  - Blocker 1, instrument: Phidias is a futures prop firm. Its listed
    products are CME micros (MES, MNQ, M2K, MYM, currency, energy and
    metal micros). AiTrader's signal is single-name US equity news drift
    on 400 small and mid-cap names. No single-name equity is tradeable
    there, so the signal as registered has no instrument at Phidias.
  - Blocker 2, automation: the Phidias Terms of Use ban "robots, fully
    automated trading algorithms or any form of automated trading",
    except "semi-automated software, provided the User actively monitors
    and manually adjusts all operations". The terms do not define
    semi-automated and do not mention alert or confirmation systems.
  - User's candidate design if semi-automation reads permissively: the
    strategy generates a signal, a Telegram bot pushes it, the user taps
    to confirm, and only that tap submits the order. Unconfirmed against
    Phidias's reading. No build time until Phidias support answers in
    writing. At the measured rate (about 78 directional calls a day
    before any capacity filter) per-trade confirmation is a real
    workload, so the filtered trade count sets whether this is practical.
  - To revisit only if both blockers clear: a futures expression of the
    signal would be a new hypothesis needing its own pre-registration,
    and an equity prop firm that allows overnight holds and automation
    would be the closer fit. Neither is researched yet.
  - Sources checked 2026-09-28: phidiaspropfirm.com/rules, /swing-allowed,
    /accounts, /tou.
- Scope rule (user, 2026-09-28): the AiTrader planning chat does not
  edit PropExperiment files. PropExperiment has its own chat.

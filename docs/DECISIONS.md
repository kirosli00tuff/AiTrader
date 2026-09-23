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

# dnn_advisory Factor — Design

> Research-backed design for Layer 3. The dnn_advisory module is a **core product feature**,
> implemented early, but remains an **advisory factor**, never the direct controller of
> execution and never able to bypass risk or self-enable live trading.
>
> **Naming note:** what this doc originally called the "DNN/RL" layer has been split. The
> shipped supervised factor is **dnn_advisory** (`ml_factor/`, Stage A below). The RL policy
> (Stage B below) is now its own module, **`rl_advisory`** (Stable-Baselines3 PPO), shipped
> OFF behind the `rl_min_real_fills` gate — it trains only on real fills, shares the same 0.5
> sizing cap, and is never a sole controller.

## 1. Research summary

Reviewed practical, production-oriented trading-ML literature and patterns:

- **Supervised DNN for price-direction / directional bias** is the most robust, debuggable
  starting point — feature-engineered tabular/sequence models predicting next-interval
  direction outperform naive baselines and avoid the instability of pure end-to-end RL on
  small data. (e.g. *Feature selection and deep neural networks for stock price direction*,
  ScienceDirect S266682702100030X.)
- **RL (Q-learning / policy methods)** can adapt trading policy to regimes and optimize
  risk-adjusted return (Sharpe, drawdown), and benefits strongly from domain indicators
  (volume, MFI, SMA-cross confirmation) to reduce false signals / overfitting in volatile
  regimes. (*Deep-Learning Based Stock Trading Strategies…*, IJSAT 2025; Xiong et al. 2023.)
- **Champion / challenger promotion** with staged rollout and statistical guardrails is the
  standard safe way to evolve a production model. (HypeLab — five-phase progressive
  rollout, traffic 3%→10%→20%→40%→50% with guardrails.)

### Decision

**Initial practical design = a supervised DNN "advisory head" first, with an RL policy
wrapper added as a second stage.** This gives us a stable, trainable, versioned factor on
day one (works with limited paper data), then layers RL for regime-aware sizing/timing once
enough paper-trading episodes accumulate. Both remain advisory.

## 2. Model design

### Stage A — Supervised Advisory DNN (ship first)
- **Type:** compact feed-forward / 1-D temporal network (MLP over engineered features, with
  an optional GRU branch over short price/window sequences). PyTorch.
- **Inputs (feature vector per market state):**
  - price/return features (multi-horizon returns, volatility, ATR-like range),
  - market-structure / liquidity (spread, depth/volume proxy, order-book imbalance where available),
  - momentum/confirmation indicators (SMA-cross state, MFI, RSI),
  - regime features (rolling vol regime, trend strength),
  - context features (news/catalyst score from `news_ingestion`, time-of-day, venue id, category id),
  - recent-performance features (recent win rate, streak, current drawdown).
- **Heads (multi-task) → the required structured outputs:**
  - `dnn_action_bias` ∈ {strong_sell … strong_buy} (softmax over directional classes → signed scalar bias),
  - `dnn_confidence` ∈ [0,1] (calibrated max-class prob / entropy-based),
  - `dnn_expected_edge` (regression head, expected return net of fees),
  - `dnn_regime_label` (classification head: trend_up / trend_down / chop / high_vol / low_vol),
  - `dnn_risk_flag` (binary head: elevated-risk / abstain recommendation),
  - `dnn_position_scale_hint` ∈ [0,1] (sizing hint; **capped by `dnn_position_scale_cap` = 0.5**).

### Stage B — RL Policy (now the separate `rl_advisory` module)
- **Status:** built as its own module (`rl_advisory/`, Stable-Baselines3 PPO) and shipped
  OFF; the engine never calls it and it stays out of the ensemble until an operator toggles
  `rl_enabled` AND the `rl_min_real_fills` gate (default 500 real fills) is met. There is no
  synthetic-data training path.
- **Algorithm:** PPO (`MlpPolicy`) over a rolling feature window (recent returns, ATR, RSI,
  volume z-score, regime one-hot, current position). Discrete action space = {flat, long,
  short}; equities respect the long-only flag. Flat is a first-class action so the policy can
  *learn when not to trade.*
- **Reward:** realized step PnL minus a mandatory per-trade transaction cost minus a
  drawdown penalty — risk-adjusted, and never rewarding churn.
- **Evaluation:** walk-forward chronological windows (matching dnn_advisory) with a separate
  deterministic eval env averaging 5–20 episodes/window; a challenger competes against the
  supervised champion on validation Sharpe + no-worse drawdown via the shared promotion gate.
- **Output:** an advisory `rl_position_scale_hint` (hard-capped at 0.5) — still advisory.
  Promotion stays OFF by default and requires an explicit operator action.

## 3. Training & evaluation pipeline (`ml_factor/`)

```
storage (paper outcomes) ─▶ build dataset (state, action, outcome, reward)
     │                          │
     │                          ▼
     │                    train challenger  ──▶ version + log (model registry table)
     │                          │
     │                          ▼
     │             evaluate challenger vs champion over
     │             dnn_challenger_evaluation_window_trades (=100)
     │                          │
     ▼                          ▼
champion serves signals    promote if better AND dnn_auto_promote_if_better=true
                           (default FALSE → promotion is a manual/gated action)
                                │
                                ▼
                rollback_on_metric_degradation=true → auto-revert on degradation
```

- **Continual learning:** continuously collects training data (market states, news context,
  decisions, outcomes); retrains periodically (`dnn_retrain_frequency_trades` = 50) or
  conditionally; improves from repeated wins/losses and regime changes. Not a static model.
- **Versioning:** every model gets a semantic id + metrics snapshot, stored in a registry
  table; outputs are logged per inference for audit.
- **Champion/Challenger:** challenger trained in shadow, scored on a held-out rolling window;
  promotion controlled (default manual: `dnn_auto_promote_if_better=false`); rollback on
  degradation (`rollback_on_metric_degradation=true`).

## 4. Wiring into the decision engine

The dnn_advisory outputs enter the **factor-combination engine** as **one weighted factor**
(`dnn_advisory_factor_weight`), alongside LLM consensus, rule-based factors, and the whale
signal. When enabled, `rl_advisory` enters as its own separate weighted factor
(`rl_advisory_factor_weight`, default 0.0 = inert). Each weight is:
- visible in the model-verdict board and weight-control panel,
- editable (slider / numeric), enable/disable-able, and lock-able against adaptive change,
- subject to `dnn_position_scale_cap = 0.5` (RL shares the same 0.5 cap),
- **always downstream of Layer-1 safety** — a factor can lower exposure but its sizing hint
  can never raise a position beyond hard limits.

## 5. Hard constraints (must-nots)

The dnn_advisory and rl_advisory modules **must not**: directly bypass risk controls ·
directly self-enable live trading · become the sole authority over execution. They **must**:
detect patterns, score
directional bias, estimate edge, classify regimes, improve over repeated paper trades, and
**learn when not to trade**.

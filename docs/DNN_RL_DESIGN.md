# DNN / RL Advisory Factor — Design

> Research-backed design for Layer 3. The DNN/RL module is a **core product feature**,
> implemented early, but remains an **advisory factor**, never the direct controller of
> execution and never able to bypass risk or self-enable live trading.

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

### Stage B — RL Policy Wrapper (added after sufficient paper episodes)
- **Algorithm:** start with tabular/contextual Q-learning over discretized DNN outputs +
  regime + risk state (matches IJSAT Q-learning result; simple, auditable), with a path to
  DQN/PPO later. Action space = {no_trade, enter_long, enter_short, scale_up, scale_down,
  exit}. **`no_trade` is a first-class action** so the system can *learn when not to trade.*
- **Reward:** risk-adjusted (realized PnL net fees, penalized by drawdown and by
  Layer-1-limit proximity; large penalty for actions that would have breached a hard limit).
- **Output:** refines `dnn_action_bias` / `dnn_position_scale_hint` only — still advisory.

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

The DNN/RL outputs enter the **factor-combination engine** as **one weighted factor**
(default `dnn_rl_factor_weight = 0.15`), alongside LLM consensus, rule-based factors, and the
whale signal. Its weight is:
- visible in the model-verdict board and weight-control panel,
- editable (slider / numeric), enable/disable-able, and lock-able against adaptive change,
- subject to `dnn_position_scale_cap = 0.5`,
- **always downstream of Layer-1 safety** — the DNN can lower exposure but its sizing hint can
  never raise a position beyond hard limits.

## 5. Hard constraints (must-nots)

The DNN/RL module **must not**: directly bypass risk controls · directly self-enable live
trading · become the sole authority over execution. It **must**: detect patterns, score
directional bias, estimate edge, classify regimes, improve over repeated paper trades, and
**learn when not to trade**.

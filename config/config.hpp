// Market AI Lab — typed configuration.
//
// The config is the *safety contract*. It is loaded once, validated strictly,
// and the `risk` block becomes the immutable Layer-1 hard limits. Adaptive
// logic (Layer 2) is structurally forbidden from weakening these (see
// learning/). Invalid or unsafe values are rejected at load time.
#pragma once

#include <map>
#include <string>
#include <vector>

namespace mal::config {

enum class VenueMode { Disabled, RecommendationOnly, Paper, Live };

VenueMode parse_mode(const std::string& s);
std::string mode_to_string(VenueMode m);

struct SystemConfig {
    double starting_paper_balance = 100000.0;
    VenueMode default_mode_per_venue = VenueMode::Paper;
    bool live_mode_default_enabled = false;
    bool kill_switch_enabled = true;
    bool manual_resume_required_after_kill_switch = true;
    // Directory holding operator control files (e.g. the GUI kill-request file
    // the engine consumes). Matches api_server/store.py; env MAL_CONTROL_DIR
    // overrides at runtime.
    std::string control_dir = ".control";
};

struct VenueConfig {
    std::string name;
    VenueMode mode = VenueMode::Paper;
    bool live_enabled = false;
    std::string paper_adapter;
    std::string live_adapter;
    std::string whale_source;            // optional
    std::string institutional_context;   // optional
    // Paper execution strategy: "api" (call the venue paper API),
    // "sim_live_price" (simulate a fill at the live market price), or "auto"
    // (try the API, fall back to sim-at-live-price if unreachable/geo-blocked).
    // Only meaningful for venues with a real paper API (Alpaca). Default auto.
    std::string paper_execution = "auto";
};

// Continuous (run-forever) engine loop settings.
struct EngineConfig {
    int loop_interval_seconds = 15;       // wall-clock seconds between ticks
    bool respect_market_hours = true;     // skip equity ticks when US RTH closed
    // Council cost cut (Task 5): while true, US-equity symbols skip the Flash
    // gate + council calls outside regular US trading hours. Crypto stays 24/7.
    // Distinct from respect_market_hours (which gates whether equity TICKS run at
    // all in continuous mode); this only suppresses the expensive council call.
    bool equities_market_hours_only = true;
};

// RL advisory (Layer 3, deferred). SHIPS OFF: while rl_enabled is false the
// engine never scores an RL factor and it stays out of the ensemble entirely.
// The PPO trainer refuses to run until at least rl_min_real_fills REAL closed
// fills exist (no synthetic-data training path). Advisory only; the 0.5 sizing
// cap (sizing.dnn_position_scale_cap) applies exactly as it does to dnn_advisory.
struct RlConfig {
    bool rl_enabled = false;              // OFF by default (ships toggled off)
    int rl_min_real_fills = 500;          // training gate: real closed fills required
};

// Market-data source selection.
struct MarketDataConfig {
    std::string source = "mock";          // "mock" (offline) | "alpaca" (live)
    // A price snapshot older than this is considered stale (Level-1 default 60s).
    int data_staleness_seconds = 60;
};

// Layer-1 hard limits. Never weakened by adaptive logic.
struct RiskConfig {
    double max_daily_loss_total_pct = 0.03;
    double max_daily_loss_per_venue_pct = 0.02;
    double max_trade_risk_pct_of_equity = 0.005;
    double max_total_open_risk_pct = 0.03;
    int max_open_positions_total = 5;
    int max_open_positions_per_venue = 2;
    double max_exposure_per_symbol_pct = 0.02;
    double max_exposure_per_market_pct = 0.02;
    double max_exposure_per_category_pct = 0.05;
    int max_consecutive_losses = 3;
    int cooldown_minutes_after_loss_breach = 240;
    double min_confidence_default = 0.65;
    double min_edge_default = 0.02;
    int required_model_agreement_count = 2;
    int stale_signal_reject_minutes = 1;
    // Level-1 ceilings enforced OUTSIDE the deterministic gate (engine/sizing):
    //   max_trades_per_day    — per-day trade counter in the run loop.
    //   max_trade_notional_cap_pct — documented notional ceiling; the gate's own
    //     max_trade_risk_pct_of_equity (0.005) stays the binding, tighter cap.
    int max_trades_per_day = 10;
    double max_trade_notional_cap_pct = 0.05;
    bool kill_switch_enabled = true;
    bool hard_stop_live_if_loss_breach = true;
    bool manual_resume_required_after_kill_switch = true;
};

struct SizingConfig {
    std::string default_position_sizing_method = "fixed_fractional";
    double default_risk_per_trade_pct = 0.005;
    double default_position_scale_cap = 1.0;
    double dnn_position_scale_cap = 0.5;
    double whale_position_scale_cap = 0.35;
};

struct AdaptiveConfig {
    bool adaptive_learning_enabled = true;
    bool adaptive_weight_updates_enabled = true;
    bool manual_weight_override_priority = true;
    int adaptive_threshold_update_frequency_trades = 25;
    int dnn_retrain_frequency_trades = 50;
    int dnn_challenger_evaluation_window_trades = 100;
    bool dnn_auto_promote_if_better = false;
    bool rollback_on_metric_degradation = true;
};

struct WhaleConfig {
    bool whale_tracking_enabled = true;
    double whale_signal_weight = 0.10;
    double whale_min_activity_score = 0.60;
    double whale_min_historical_usefulness = 0.55;
    int whale_max_signal_age_minutes = 15;
    bool whale_contradiction_penalty_enabled = true;
    bool whale_auto_disable_if_unhelpful = true;
};

struct LiveApprovalConfig {
    bool live_approval_required = true;
    bool live_requires_connected_credentials = true;
    bool live_requires_kill_switch_configured = true;
    bool live_requires_recent_performance_visible = true;
    bool live_requires_manual_confirmation = true;
    bool live_requires_positive_paper_expectancy = true;
    double live_requires_drawdown_below_pct = 0.05;
};

struct DashboardConfig {
    int dashboard_refresh_seconds = 5;
    int trade_feed_page_size = 50;
    int equity_curve_default_window_days = 30;
    int pnl_chart_default_window_days = 7;
    bool show_model_verdict_board_by_default = true;
    bool show_weight_control_panel_by_default = true;
    bool show_dnn_panel_by_default = true;
    bool show_whale_panel_by_default = true;
};

// Native strategy layer. Signals are generated ONLY on closed bars (never per
// tick). Two factors (trend/momentum + mean reversion) blended by a regime
// detector. Entries set native ATR stop / target / time-stop at order creation;
// exits execute natively without the council.
struct StrategyConfig {
    bool momentum_enabled = true;
    bool reversion_enabled = true;
    // Strategy A — trend / momentum.
    int ema_fast = 20;
    int ema_slow = 100;
    double adx_min = 20.0;             // ADX filter floor
    int atr_period = 14;
    double atr_vol_floor = 0.0;        // min ATR/price to allow an entry
    // Strategy B — mean reversion (whitelisted symbols only).
    int bb_period = 20;
    double bb_std = 2.0;
    int rsi_period = 14;
    double rsi_oversold = 30.0;
    double rsi_overbought = 70.0;
    int vol_lookback = 20;            // bars for average-volume confirmation
    double vol_multiple = 1.0;        // reversion needs volume > vol_multiple * avg
    // Regime detector thresholds (ADX + realized volatility).
    double regime_adx_trend = 25.0;   // ADX above => trending
    double regime_rvol_high = 0.02;   // realized vol above => volatile/range-bound
    // Direction policy. Equities are always long-only in paper.
    bool crypto_allow_short = false;
    // Native exits (set at order creation; NO council on exit).
    double atr_stop_mult = 2.0;
    double atr_target_mult = 3.0;
    int time_stop_bars = 24;          // force-close after N unresolved bars
    // Regime -> (momentum, reversion) blend weights.
    double trending_momentum_weight = 0.70;
    double trending_reversion_weight = 0.30;
    double range_momentum_weight = 0.30;
    double range_reversion_weight = 0.70;
    double neutral_momentum_weight = 0.50;
    double neutral_reversion_weight = 0.50;
    // Tradable universe for native strategies (parsed from a comma-separated
    // scalar in YAML — the minimal parser has no sequence support).
    std::vector<std::string> whitelist{"BTC/USD", "ETH/USD", "SPY", "QQQ"};
    std::string bar_timeframe = "5min";  // strategies evaluate on closed bars
};

// Council cost controls. The full LLM council runs ONLY on a native strategy
// entry candidate that passes the base-check gate — never on a timer, tick, or exit.
struct CouncilConfig {
    int council_daily_budget = 30;                // max full-council calls per day
    int per_symbol_council_cooldown_minutes = 60;
    int council_max_tokens = 400;                 // per-provider response cap
    // Council-side thresholds. SEPARATE from the gate's risk.min_confidence_default
    // / required_model_agreement_count so they never weaken the Layer-1 gate.
    double council_min_confidence = 0.6;
    int council_min_agreement = 2;
    // Skip the council when regime is neutral AND signal strength is below this.
    double neutral_skip_strength_threshold = 0.5;
};

// Ensemble weights. Editable in UI, auto-normalized, lockable.
struct ModelWeights {
    double llm_primary_weight = 0.27;
    double llm_secondary_weight = 0.18;
    double llm_tertiary_weight = 0.12;
    double rule_based_factor_weight = 0.18;
    double dnn_advisory_factor_weight = 0.15;
    double whale_signal_factor_weight = 0.10;
    // RL advisory factor. 0.0 by default so RL is NON-DECISIVE even once enabled
    // (it can never move the ensemble unless an operator raises this via the UI).
    // Keeps the 6-factor sum at 1.00; excluded from normalization while zero.
    double rl_advisory_factor_weight = 0.0;

    std::map<std::string, double> as_map() const;
    double sum() const;
};

// Offline simulation controls (feed generation + clock). These NEVER affect live
// behavior: Alpaca remains a paper + market-data venue only, with no live path.
// They exist so the offline paper loop can be a real training environment —
// generating native fills that feed the real-fill tuner, train_real, and RL.
struct SimulationConfig {
    // flat_random_walk (default, unchanged) | synthetic_regimes | replay.
    std::string feed_mode = "flat_random_walk";
    // real (wall-clock, for the continuous live-adjacent loop) | simulated
    // (bar time advances internally so finite/synthetic runs close bars fast).
    std::string clock_mode = "real";
    unsigned long long synthetic_seed = 42;  // deterministic synthetic feed
    // Historical replay window (inclusive YYYY-MM-DD; empty => earliest/latest
    // stored bar). Replay drives the loop from real bars in the bars table.
    std::string replay_start_date;
    std::string replay_end_date;
    std::string replay_speed = "fast";       // fast (ignore wall-clock) | realtime
};

// IBKR live venue connection settings. IBKR is live only and connects to a
// locally run IB Gateway session the operator starts and authenticates. No IBKR
// credentials pass through this app. connection_enabled default false: IBKR
// stays disabled behind the approval gate this session.
struct IbkrConfig {
    std::string gateway_host = "127.0.0.1";
    int gateway_port = 4001;          // IB Gateway live socket
    bool connection_enabled = false;  // health check + future live routing; OFF
    bool market_data = false;         // Alpaca serves market data; IBKR data off
};

struct Config {
    SystemConfig system;
    EngineConfig engine;
    MarketDataConfig market_data;
    std::vector<VenueConfig> venues;
    RiskConfig risk;
    SizingConfig sizing;
    StrategyConfig strategy;
    CouncilConfig council;
    RlConfig rl;
    AdaptiveConfig adaptive;
    WhaleConfig whale;
    LiveApprovalConfig live_approval;
    DashboardConfig dashboard;
    SimulationConfig simulation;
    IbkrConfig ibkr;
    ModelWeights model_weights;

    const VenueConfig* find_venue(const std::string& name) const;
};

// Load + validate. Throws std::runtime_error with a precise reason on any
// invalid or unsafe value. On success the returned config is guaranteed
// internally consistent (e.g. live disabled by default everywhere).
Config load_config(const std::string& path);

// Validate an already-populated config. Returns an empty vector when valid,
// otherwise a list of human-readable problems. Pure: no side effects.
std::vector<std::string> validate_config(const Config& cfg);

}  // namespace mal::config

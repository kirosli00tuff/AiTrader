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
};

struct VenueConfig {
    std::string name;
    VenueMode mode = VenueMode::Paper;
    bool live_enabled = false;
    std::string paper_adapter;
    std::string live_adapter;
    std::string whale_source;            // optional
    std::string institutional_context;   // optional
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
    int cooldown_minutes_after_loss_breach = 120;
    double min_confidence_default = 0.65;
    double min_edge_default = 0.02;
    int required_model_agreement_count = 2;
    int stale_signal_reject_minutes = 10;
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

// Ensemble weights. Editable in UI, auto-normalized, lockable.
struct ModelWeights {
    double llm_primary_weight = 0.27;
    double llm_secondary_weight = 0.18;
    double llm_tertiary_weight = 0.12;
    double rule_based_factor_weight = 0.18;
    double dnn_rl_factor_weight = 0.15;
    double whale_signal_factor_weight = 0.10;

    std::map<std::string, double> as_map() const;
    double sum() const;
};

struct Config {
    SystemConfig system;
    std::vector<VenueConfig> venues;
    RiskConfig risk;
    SizingConfig sizing;
    AdaptiveConfig adaptive;
    WhaleConfig whale;
    LiveApprovalConfig live_approval;
    DashboardConfig dashboard;
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

#include "config/config.hpp"

#include <stdexcept>

#include "config/yaml.hpp"

namespace mal::config {

VenueMode parse_mode(const std::string& s) {
    if (s == "disabled") return VenueMode::Disabled;
    if (s == "recommendation_only") return VenueMode::RecommendationOnly;
    if (s == "paper") return VenueMode::Paper;
    if (s == "live") return VenueMode::Live;
    throw std::runtime_error("Invalid venue mode: '" + s + "'");
}

std::string mode_to_string(VenueMode m) {
    switch (m) {
        case VenueMode::Disabled: return "disabled";
        case VenueMode::RecommendationOnly: return "recommendation_only";
        case VenueMode::Paper: return "paper";
        case VenueMode::Live: return "live";
    }
    return "disabled";
}

std::map<std::string, double> ModelWeights::as_map() const {
    return {
        {"llm_primary", llm_primary_weight},
        {"llm_secondary", llm_secondary_weight},
        {"llm_tertiary", llm_tertiary_weight},
        {"rule_based", rule_based_factor_weight},
        {"dnn_advisory", dnn_advisory_factor_weight},
        {"whale_signal", whale_signal_factor_weight},
    };
}

double ModelWeights::sum() const {
    return llm_primary_weight + llm_secondary_weight + llm_tertiary_weight +
           rule_based_factor_weight + dnn_advisory_factor_weight +
           whale_signal_factor_weight;
}

const VenueConfig* Config::find_venue(const std::string& name) const {
    for (const auto& v : venues)
        if (v.name == name) return &v;
    return nullptr;
}

namespace {

using Node = std::shared_ptr<const YamlNode>;

const YamlNode& require(const std::shared_ptr<YamlNode>& root,
                        const std::string& path) {
    auto n = root->at(path);
    if (!n) throw std::runtime_error("Config missing required key: " + path);
    return *n;
}

std::string get_str(const std::shared_ptr<YamlNode>& root,
                    const std::string& path, const std::string& def) {
    auto n = root->at(path);
    if (!n || !n->is_scalar) return def;
    return n->scalar;
}

bool get_bool(const std::shared_ptr<YamlNode>& root, const std::string& path,
              bool def) {
    auto n = root->at(path);
    if (!n || !n->is_scalar) return def;
    const std::string& s = n->scalar;
    if (s == "true" || s == "True" || s == "yes" || s == "1") return true;
    if (s == "false" || s == "False" || s == "no" || s == "0") return false;
    throw std::runtime_error("Config key " + path + " not a bool: '" + s + "'");
}

double get_double(const std::shared_ptr<YamlNode>& root, const std::string& path,
                  double def) {
    auto n = root->at(path);
    if (!n || !n->is_scalar) return def;
    try {
        return std::stod(n->scalar);
    } catch (...) {
        throw std::runtime_error("Config key " + path + " not numeric: '" +
                                 n->scalar + "'");
    }
}

int get_int(const std::shared_ptr<YamlNode>& root, const std::string& path,
            int def) {
    auto n = root->at(path);
    if (!n || !n->is_scalar) return def;
    try {
        return std::stoi(n->scalar);
    } catch (...) {
        throw std::runtime_error("Config key " + path + " not an int: '" +
                                 n->scalar + "'");
    }
}

std::string trim(const std::string& s) {
    size_t a = s.find_first_not_of(" \t");
    if (a == std::string::npos) return "";
    size_t b = s.find_last_not_of(" \t");
    return s.substr(a, b - a + 1);
}

// The minimal YAML parser has no sequence support, so list-valued config (the
// strategy whitelist) is expressed as a comma-separated scalar and split here.
std::vector<std::string> split_csv(const std::string& s) {
    std::vector<std::string> out;
    size_t start = 0;
    while (start <= s.size()) {
        size_t comma = s.find(',', start);
        size_t len = comma == std::string::npos ? std::string::npos : comma - start;
        std::string tok = trim(s.substr(start, len));
        if (!tok.empty()) out.push_back(tok);
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
    return out;
}

}  // namespace

Config load_config(const std::string& path) {
    auto root = load_yaml_file(path);
    Config c;

    // system
    c.system.starting_paper_balance =
        get_double(root, "system.starting_paper_balance", 100000.0);
    c.system.default_mode_per_venue =
        parse_mode(get_str(root, "system.default_mode_per_venue", "paper"));
    c.system.live_mode_default_enabled =
        get_bool(root, "system.live_mode_default_enabled", false);
    c.system.kill_switch_enabled =
        get_bool(root, "system.kill_switch_enabled", true);
    c.system.manual_resume_required_after_kill_switch =
        get_bool(root, "system.manual_resume_required_after_kill_switch", true);

    // engine (continuous-mode loop)
    c.engine.loop_interval_seconds =
        get_int(root, "engine.loop_interval_seconds", c.engine.loop_interval_seconds);
    c.engine.respect_market_hours =
        get_bool(root, "engine.respect_market_hours", c.engine.respect_market_hours);

    // market data source
    c.market_data.source =
        get_str(root, "market_data.source", c.market_data.source);
    c.market_data.data_staleness_seconds = get_int(
        root, "market_data.data_staleness_seconds", c.market_data.data_staleness_seconds);

    // venues
    auto venues_node = root->at("venues");
    if (venues_node && !venues_node->is_scalar) {
        for (const auto& [name, _] : venues_node->map) {
            VenueConfig v;
            v.name = name;
            v.mode = parse_mode(get_str(root, "venues." + name + ".mode", "paper"));
            v.live_enabled =
                get_bool(root, "venues." + name + ".live_enabled", false);
            v.paper_adapter = get_str(root, "venues." + name + ".paper_adapter", "");
            v.live_adapter = get_str(root, "venues." + name + ".live_adapter", "");
            v.whale_source = get_str(root, "venues." + name + ".whale_source", "");
            v.institutional_context =
                get_str(root, "venues." + name + ".institutional_context", "");
            v.paper_execution =
                get_str(root, "venues." + name + ".paper_execution", "auto");
            c.venues.push_back(std::move(v));
        }
    }

    // risk
    auto& r = c.risk;
    r.max_daily_loss_total_pct = get_double(root, "risk.max_daily_loss_total_pct", r.max_daily_loss_total_pct);
    r.max_daily_loss_per_venue_pct = get_double(root, "risk.max_daily_loss_per_venue_pct", r.max_daily_loss_per_venue_pct);
    r.max_trade_risk_pct_of_equity = get_double(root, "risk.max_trade_risk_pct_of_equity", r.max_trade_risk_pct_of_equity);
    r.max_total_open_risk_pct = get_double(root, "risk.max_total_open_risk_pct", r.max_total_open_risk_pct);
    r.max_open_positions_total = get_int(root, "risk.max_open_positions_total", r.max_open_positions_total);
    r.max_open_positions_per_venue = get_int(root, "risk.max_open_positions_per_venue", r.max_open_positions_per_venue);
    r.max_exposure_per_symbol_pct = get_double(root, "risk.max_exposure_per_symbol_pct", r.max_exposure_per_symbol_pct);
    r.max_exposure_per_market_pct = get_double(root, "risk.max_exposure_per_market_pct", r.max_exposure_per_market_pct);
    r.max_exposure_per_category_pct = get_double(root, "risk.max_exposure_per_category_pct", r.max_exposure_per_category_pct);
    r.max_consecutive_losses = get_int(root, "risk.max_consecutive_losses", r.max_consecutive_losses);
    r.cooldown_minutes_after_loss_breach = get_int(root, "risk.cooldown_minutes_after_loss_breach", r.cooldown_minutes_after_loss_breach);
    r.min_confidence_default = get_double(root, "risk.min_confidence_default", r.min_confidence_default);
    r.min_edge_default = get_double(root, "risk.min_edge_default", r.min_edge_default);
    r.required_model_agreement_count = get_int(root, "risk.required_model_agreement_count", r.required_model_agreement_count);
    r.stale_signal_reject_minutes = get_int(root, "risk.stale_signal_reject_minutes", r.stale_signal_reject_minutes);
    r.max_trades_per_day = get_int(root, "risk.max_trades_per_day", r.max_trades_per_day);
    r.max_trade_notional_cap_pct = get_double(root, "risk.max_trade_notional_cap_pct", r.max_trade_notional_cap_pct);
    r.kill_switch_enabled = get_bool(root, "risk.kill_switch_enabled", r.kill_switch_enabled);
    r.hard_stop_live_if_loss_breach = get_bool(root, "risk.hard_stop_live_if_loss_breach", r.hard_stop_live_if_loss_breach);
    r.manual_resume_required_after_kill_switch = get_bool(root, "risk.manual_resume_required_after_kill_switch", r.manual_resume_required_after_kill_switch);

    // sizing
    auto& s = c.sizing;
    s.default_position_sizing_method = get_str(root, "sizing.default_position_sizing_method", s.default_position_sizing_method);
    s.default_risk_per_trade_pct = get_double(root, "sizing.default_risk_per_trade_pct", s.default_risk_per_trade_pct);
    s.default_position_scale_cap = get_double(root, "sizing.default_position_scale_cap", s.default_position_scale_cap);
    s.dnn_position_scale_cap = get_double(root, "sizing.dnn_position_scale_cap", s.dnn_position_scale_cap);
    s.whale_position_scale_cap = get_double(root, "sizing.whale_position_scale_cap", s.whale_position_scale_cap);

    // strategy (native signal layer — evaluated on closed bars only)
    auto& st = c.strategy;
    st.momentum_enabled = get_bool(root, "strategy.momentum_enabled", st.momentum_enabled);
    st.reversion_enabled = get_bool(root, "strategy.reversion_enabled", st.reversion_enabled);
    st.ema_fast = get_int(root, "strategy.ema_fast", st.ema_fast);
    st.ema_slow = get_int(root, "strategy.ema_slow", st.ema_slow);
    st.adx_min = get_double(root, "strategy.adx_min", st.adx_min);
    st.atr_period = get_int(root, "strategy.atr_period", st.atr_period);
    st.atr_vol_floor = get_double(root, "strategy.atr_vol_floor", st.atr_vol_floor);
    st.bb_period = get_int(root, "strategy.bb_period", st.bb_period);
    st.bb_std = get_double(root, "strategy.bb_std", st.bb_std);
    st.rsi_period = get_int(root, "strategy.rsi_period", st.rsi_period);
    st.rsi_oversold = get_double(root, "strategy.rsi_oversold", st.rsi_oversold);
    st.rsi_overbought = get_double(root, "strategy.rsi_overbought", st.rsi_overbought);
    st.vol_lookback = get_int(root, "strategy.vol_lookback", st.vol_lookback);
    st.regime_adx_trend = get_double(root, "strategy.regime_adx_trend", st.regime_adx_trend);
    st.regime_rvol_high = get_double(root, "strategy.regime_rvol_high", st.regime_rvol_high);
    st.crypto_allow_short = get_bool(root, "strategy.crypto_allow_short", st.crypto_allow_short);
    st.atr_stop_mult = get_double(root, "strategy.atr_stop_mult", st.atr_stop_mult);
    st.atr_target_mult = get_double(root, "strategy.atr_target_mult", st.atr_target_mult);
    st.time_stop_bars = get_int(root, "strategy.time_stop_bars", st.time_stop_bars);
    st.trending_momentum_weight = get_double(root, "strategy.trending_momentum_weight", st.trending_momentum_weight);
    st.trending_reversion_weight = get_double(root, "strategy.trending_reversion_weight", st.trending_reversion_weight);
    st.range_momentum_weight = get_double(root, "strategy.range_momentum_weight", st.range_momentum_weight);
    st.range_reversion_weight = get_double(root, "strategy.range_reversion_weight", st.range_reversion_weight);
    st.neutral_momentum_weight = get_double(root, "strategy.neutral_momentum_weight", st.neutral_momentum_weight);
    st.neutral_reversion_weight = get_double(root, "strategy.neutral_reversion_weight", st.neutral_reversion_weight);
    st.bar_timeframe = get_str(root, "strategy.bar_timeframe", st.bar_timeframe);
    {
        auto parsed = split_csv(get_str(root, "strategy.whitelist", ""));
        if (!parsed.empty()) st.whitelist = parsed;
    }

    // council cost controls (entries-only full council; gate + budget + cooldown)
    auto& co = c.council;
    co.council_daily_budget = get_int(root, "council.council_daily_budget", co.council_daily_budget);
    co.per_symbol_council_cooldown_minutes = get_int(root, "council.per_symbol_council_cooldown_minutes", co.per_symbol_council_cooldown_minutes);
    co.council_max_tokens = get_int(root, "council.council_max_tokens", co.council_max_tokens);
    co.council_min_confidence = get_double(root, "council.council_min_confidence", co.council_min_confidence);
    co.council_min_agreement = get_int(root, "council.council_min_agreement", co.council_min_agreement);
    co.neutral_skip_strength_threshold = get_double(root, "council.neutral_skip_strength_threshold", co.neutral_skip_strength_threshold);

    // adaptive
    auto& a = c.adaptive;
    a.adaptive_learning_enabled = get_bool(root, "adaptive.adaptive_learning_enabled", a.adaptive_learning_enabled);
    a.adaptive_weight_updates_enabled = get_bool(root, "adaptive.adaptive_weight_updates_enabled", a.adaptive_weight_updates_enabled);
    a.manual_weight_override_priority = get_bool(root, "adaptive.manual_weight_override_priority", a.manual_weight_override_priority);
    a.adaptive_threshold_update_frequency_trades = get_int(root, "adaptive.adaptive_threshold_update_frequency_trades", a.adaptive_threshold_update_frequency_trades);
    a.dnn_retrain_frequency_trades = get_int(root, "adaptive.dnn_retrain_frequency_trades", a.dnn_retrain_frequency_trades);
    a.dnn_challenger_evaluation_window_trades = get_int(root, "adaptive.dnn_challenger_evaluation_window_trades", a.dnn_challenger_evaluation_window_trades);
    a.dnn_auto_promote_if_better = get_bool(root, "adaptive.dnn_auto_promote_if_better", a.dnn_auto_promote_if_better);
    a.rollback_on_metric_degradation = get_bool(root, "adaptive.rollback_on_metric_degradation", a.rollback_on_metric_degradation);

    // whale
    auto& w = c.whale;
    w.whale_tracking_enabled = get_bool(root, "whale.whale_tracking_enabled", w.whale_tracking_enabled);
    w.whale_signal_weight = get_double(root, "whale.whale_signal_weight", w.whale_signal_weight);
    w.whale_min_activity_score = get_double(root, "whale.whale_min_activity_score", w.whale_min_activity_score);
    w.whale_min_historical_usefulness = get_double(root, "whale.whale_min_historical_usefulness", w.whale_min_historical_usefulness);
    w.whale_max_signal_age_minutes = get_int(root, "whale.whale_max_signal_age_minutes", w.whale_max_signal_age_minutes);
    w.whale_contradiction_penalty_enabled = get_bool(root, "whale.whale_contradiction_penalty_enabled", w.whale_contradiction_penalty_enabled);
    w.whale_auto_disable_if_unhelpful = get_bool(root, "whale.whale_auto_disable_if_unhelpful", w.whale_auto_disable_if_unhelpful);

    // live approval
    auto& la = c.live_approval;
    la.live_approval_required = get_bool(root, "live_approval.live_approval_required", la.live_approval_required);
    la.live_requires_connected_credentials = get_bool(root, "live_approval.live_requires_connected_credentials", la.live_requires_connected_credentials);
    la.live_requires_kill_switch_configured = get_bool(root, "live_approval.live_requires_kill_switch_configured", la.live_requires_kill_switch_configured);
    la.live_requires_recent_performance_visible = get_bool(root, "live_approval.live_requires_recent_performance_visible", la.live_requires_recent_performance_visible);
    la.live_requires_manual_confirmation = get_bool(root, "live_approval.live_requires_manual_confirmation", la.live_requires_manual_confirmation);
    la.live_requires_positive_paper_expectancy = get_bool(root, "live_approval.live_requires_positive_paper_expectancy", la.live_requires_positive_paper_expectancy);
    la.live_requires_drawdown_below_pct = get_double(root, "live_approval.live_requires_drawdown_below_pct", la.live_requires_drawdown_below_pct);

    // dashboard
    auto& d = c.dashboard;
    d.dashboard_refresh_seconds = get_int(root, "dashboard.dashboard_refresh_seconds", d.dashboard_refresh_seconds);
    d.trade_feed_page_size = get_int(root, "dashboard.trade_feed_page_size", d.trade_feed_page_size);
    d.equity_curve_default_window_days = get_int(root, "dashboard.equity_curve_default_window_days", d.equity_curve_default_window_days);
    d.pnl_chart_default_window_days = get_int(root, "dashboard.pnl_chart_default_window_days", d.pnl_chart_default_window_days);
    d.show_model_verdict_board_by_default = get_bool(root, "dashboard.show_model_verdict_board_by_default", d.show_model_verdict_board_by_default);
    d.show_weight_control_panel_by_default = get_bool(root, "dashboard.show_weight_control_panel_by_default", d.show_weight_control_panel_by_default);
    d.show_dnn_panel_by_default = get_bool(root, "dashboard.show_dnn_panel_by_default", d.show_dnn_panel_by_default);
    d.show_whale_panel_by_default = get_bool(root, "dashboard.show_whale_panel_by_default", d.show_whale_panel_by_default);

    // model weights
    auto& mw = c.model_weights;
    mw.llm_primary_weight = get_double(root, "model_weights.llm_primary_weight", mw.llm_primary_weight);
    mw.llm_secondary_weight = get_double(root, "model_weights.llm_secondary_weight", mw.llm_secondary_weight);
    mw.llm_tertiary_weight = get_double(root, "model_weights.llm_tertiary_weight", mw.llm_tertiary_weight);
    mw.rule_based_factor_weight = get_double(root, "model_weights.rule_based_factor_weight", mw.rule_based_factor_weight);
    mw.dnn_advisory_factor_weight = get_double(root, "model_weights.dnn_advisory_factor_weight", mw.dnn_advisory_factor_weight);
    mw.whale_signal_factor_weight = get_double(root, "model_weights.whale_signal_factor_weight", mw.whale_signal_factor_weight);

    auto problems = validate_config(c);
    if (!problems.empty()) {
        std::string msg = "Config validation failed:";
        for (const auto& p : problems) msg += "\n  - " + p;
        throw std::runtime_error(msg);
    }
    (void)require;  // silence unused in case path changes
    return c;
}

std::vector<std::string> validate_config(const Config& cfg) {
    std::vector<std::string> problems;
    auto pct = [&](const std::string& name, double v) {
        if (v < 0.0 || v > 1.0)
            problems.push_back(name + " must be a fraction in [0,1], got " +
                               std::to_string(v));
    };
    const auto& r = cfg.risk;
    pct("risk.max_daily_loss_total_pct", r.max_daily_loss_total_pct);
    pct("risk.max_daily_loss_per_venue_pct", r.max_daily_loss_per_venue_pct);
    pct("risk.max_trade_risk_pct_of_equity", r.max_trade_risk_pct_of_equity);
    pct("risk.max_total_open_risk_pct", r.max_total_open_risk_pct);
    pct("risk.max_exposure_per_symbol_pct", r.max_exposure_per_symbol_pct);
    pct("risk.max_exposure_per_market_pct", r.max_exposure_per_market_pct);
    pct("risk.max_exposure_per_category_pct", r.max_exposure_per_category_pct);
    pct("risk.min_confidence_default", r.min_confidence_default);
    pct("risk.min_edge_default", r.min_edge_default);
    pct("risk.max_trade_notional_cap_pct", r.max_trade_notional_cap_pct);

    if (r.max_trades_per_day < 0)
        problems.push_back("risk.max_trades_per_day must be >= 0");
    if (cfg.market_data.data_staleness_seconds < 1)
        problems.push_back("market_data.data_staleness_seconds must be >= 1");
    if (r.max_open_positions_total < 0)
        problems.push_back("risk.max_open_positions_total must be >= 0");
    if (r.max_open_positions_per_venue < 0)
        problems.push_back("risk.max_open_positions_per_venue must be >= 0");
    if (r.max_consecutive_losses < 1)
        problems.push_back("risk.max_consecutive_losses must be >= 1");
    if (r.required_model_agreement_count < 0)
        problems.push_back("risk.required_model_agreement_count must be >= 0");

    // Per-venue limit must not exceed the total — a cross-limit consistency
    // check that protects against accidentally unbounded venue exposure.
    if (r.max_daily_loss_per_venue_pct > r.max_daily_loss_total_pct)
        problems.push_back(
            "risk.max_daily_loss_per_venue_pct must not exceed "
            "risk.max_daily_loss_total_pct");

    // Sizing caps must be sane fractions; DNN/whale caps bound advisory sizing.
    pct("sizing.dnn_position_scale_cap", cfg.sizing.dnn_position_scale_cap);
    pct("sizing.whale_position_scale_cap", cfg.sizing.whale_position_scale_cap);
    if (cfg.sizing.default_position_scale_cap < 0.0)
        problems.push_back("sizing.default_position_scale_cap must be >= 0");

    // Model weights must be non-negative and have a positive sum (so they can
    // be normalized). They need not pre-sum to 1 — normalization handles that.
    for (const auto& [k, v] : cfg.model_weights.as_map())
        if (v < 0.0)
            problems.push_back("model_weights." + k + " must be >= 0, got " +
                               std::to_string(v));
    if (cfg.model_weights.sum() <= 0.0)
        problems.push_back("model_weights sum must be > 0");

    // SAFETY INVARIANT: live must be disabled by default everywhere.
    if (cfg.system.live_mode_default_enabled)
        problems.push_back(
            "SAFETY: system.live_mode_default_enabled must be false "
            "(live is disabled by default)");
    for (const auto& v : cfg.venues) {
        if (v.mode == VenueMode::Live)
            problems.push_back("SAFETY: venue '" + v.name +
                               "' must not default to live mode");
        if (v.live_enabled)
            problems.push_back("SAFETY: venue '" + v.name +
                               "' live_enabled must be false by default");
    }

    if (cfg.dashboard.dashboard_refresh_seconds < 1)
        problems.push_back("dashboard.dashboard_refresh_seconds must be >= 1");

    // Continuous-mode loop interval must be a positive number of seconds.
    if (cfg.engine.loop_interval_seconds < 1)
        problems.push_back("engine.loop_interval_seconds must be >= 1");

    // Market-data source must be a known value.
    if (cfg.market_data.source != "mock" && cfg.market_data.source != "alpaca")
        problems.push_back(
            "market_data.source must be 'mock' or 'alpaca', got '" +
            cfg.market_data.source + "'");

    // Per-venue paper-execution strategy must be a known value.
    for (const auto& v : cfg.venues) {
        const auto& pe = v.paper_execution;
        if (pe != "api" && pe != "sim_live_price" && pe != "auto")
            problems.push_back("venue '" + v.name +
                               "' paper_execution must be 'api', "
                               "'sim_live_price', or 'auto', got '" + pe + "'");
    }

    // Native strategy layer sanity.
    const auto& st = cfg.strategy;
    pct("strategy.atr_vol_floor", st.atr_vol_floor);
    if (st.ema_fast >= st.ema_slow)
        problems.push_back("strategy.ema_fast must be < strategy.ema_slow");
    if (st.rsi_oversold >= st.rsi_overbought)
        problems.push_back("strategy.rsi_oversold must be < strategy.rsi_overbought");
    if (st.time_stop_bars < 1)
        problems.push_back("strategy.time_stop_bars must be >= 1");
    if (st.atr_stop_mult <= 0.0 || st.atr_target_mult <= 0.0)
        problems.push_back("strategy ATR stop/target multipliers must be > 0");
    if (st.whitelist.empty())
        problems.push_back("strategy.whitelist must not be empty");

    // Council cost controls. Thresholds are separate knobs and must be sane
    // fractions; they never relax the Layer-1 gate.
    const auto& co = cfg.council;
    pct("council.council_min_confidence", co.council_min_confidence);
    pct("council.neutral_skip_strength_threshold", co.neutral_skip_strength_threshold);
    if (co.council_daily_budget < 0)
        problems.push_back("council.council_daily_budget must be >= 0");
    if (co.council_max_tokens < 1)
        problems.push_back("council.council_max_tokens must be >= 1");
    if (co.council_min_agreement < 0)
        problems.push_back("council.council_min_agreement must be >= 0");
    if (co.per_symbol_council_cooldown_minutes < 0)
        problems.push_back("council.per_symbol_council_cooldown_minutes must be >= 0");

    return problems;
}

}  // namespace mal::config

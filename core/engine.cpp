#include "core/engine.hpp"

#include <algorithm>
#include <cmath>
#include <functional>

#include "core/bridge_client.hpp"
#include "core/util.hpp"

namespace mal::core {

namespace {
double clamp01(double x) { return std::clamp(x, 0.0, 1.0); }
double det_unit(const std::string& s, unsigned salt) {
    std::size_t h = std::hash<std::string>{}(s) ^ (salt * 2654435761u);
    return static_cast<double>(h % 100000) / 100000.0;
}
}  // namespace

Engine::Engine(config::Config cfg, EngineOptions opts)
    : cfg_(std::move(cfg)),
      opts_(std::move(opts)),
      tuner_(cfg_.risk, cfg_.adaptive),
      kill_switch_(cfg_.risk.kill_switch_enabled,
                   cfg_.risk.manual_resume_required_after_kill_switch),
      equity_(cfg_.system.starting_paper_balance),
      peak_equity_(cfg_.system.starting_paper_balance),
      rng_(opts_.seed ? opts_.seed : 1) {
    storage_ = std::make_unique<storage::Storage>(opts_.db_path);
    storage_->init_schema(opts_.schema_path);

    // Build a small instrument universe spanning the demo's paper venues.
    std::vector<market_data::MockFeed::Instrument> instruments = {
        {"polymarket", "PRES-2028-YES", "PRES-2028", "politics", 0.52},
        {"polymarket", "FED-CUT-Q3", "FED-CUT", "macro", 0.40},
        {"alpaca", "AAPL", "AAPL", "equity", 195.0},
        {"alpaca", "BTC-USD", "BTC-USD", "crypto", 64000.0},
    };
    feed_ = std::make_unique<market_data::MockFeed>(instruments, opts_.seed);
    news_ = std::make_unique<news::MockCatalystProvider>();
    gate_ = std::make_unique<risk::RiskGate>(cfg_.risk);
    accounts_ = std::make_unique<account::AccountManager>(cfg_);

    weights_.set_from_map(cfg_.model_weights.as_map());

    pstate_.equity = equity_;
    pstate_.start_of_day_equity = equity_;

    // Persist initial venue + approval state (live disabled everywhere).
    const std::string ts = util::now_iso8601();
    for (const auto& [name, st] : accounts_->venues()) {
        storage_->upsert_venue_state(name, config::mode_to_string(st.mode), false,
                                     false, 0, "", ts);
    }
    storage_->set_approval_state(false, false, ts,
                                 "{\"ready\":false,\"reason\":\"live disabled by"
                                 " default\"}");
    storage_->append_event({ts, "startup", "", "", "info",
                            "Engine started (paper mode, live disabled)",
                            "{}"});
    snapshot_balances();
}

signal_engine::FactorSignal Engine::mock_factor(
    const std::string& name, const market_data::MarketState& ms,
    const news::CatalystScore& cat) {
    signal_engine::FactorSignal s;
    s.factor = name;
    // Momentum + catalyst + per-factor deterministic perturbation.
    double momentum = std::tanh(ms.ret_5 * 25.0 + ms.order_book_imbalance * 0.3);
    double noise = det_unit(name + ms.symbol, 17) - 0.5;
    double bias = std::tanh(momentum + 0.4 * cat.score + 0.6 * noise);
    s.bias = std::clamp(bias, -1.0, 1.0);
    s.confidence = clamp01(0.55 + 0.4 * std::abs(bias) - 0.15 * ms.volatility * 5);
    s.edge = std::max(0.0, 0.03 * std::abs(bias) + 0.01 * cat.importance);
    return s;
}

std::vector<signal_engine::FactorSignal> Engine::gather_factors(
    const market_data::MarketState& ms, const news::CatalystScore& cat) {
    std::vector<signal_engine::FactorSignal> out;
    const std::vector<std::string> factors = {
        "llm_primary", "llm_secondary", "llm_tertiary",
        "rule_based",  "dnn_rl",        "whale_signal"};

    // Rule-based is always computed in C++.
    // LLM/DNN/whale come from the bridge if enabled, else mocks.
    for (const auto& f : factors) {
        signal_engine::FactorSignal s = mock_factor(f, ms, cat);

        if (opts_.use_bridge && f != "rule_based") {
            std::string endpoint = "/score/llm";
            if (f == "dnn_rl") endpoint = "/score/dnn";
            else if (f == "whale_signal") endpoint = "/score/whale";
            std::string body = util::to_json(
                {{"symbol", ms.symbol}, {"venue", ms.venue}, {"factor", f}},
                {{"price", ms.price},
                 {"ret_5", ms.ret_5},
                 {"volatility", ms.volatility},
                 {"imbalance", ms.order_book_imbalance},
                 {"catalyst", cat.score}});
            auto resp = bridge::http_post_json(opts_.bridge_host,
                                               opts_.bridge_port, endpoint, body);
            if (resp) {
                s.bias = std::clamp(bridge::json_get_number(*resp, "bias", s.bias),
                                    -1.0, 1.0);
                s.confidence =
                    clamp01(bridge::json_get_number(*resp, "confidence",
                                                    s.confidence));
                s.edge = std::max(0.0, bridge::json_get_number(*resp, "edge",
                                                               s.edge));
            }
        }

        // Apply advisory sizing caps (DNN / whale) by attenuating confidence's
        // influence on sizing later; here we just record the capped scale hint
        // implicitly via the cap used during sizing. Persist the signal.
        storage_->insert_signal({ms.ts, ms.venue, ms.symbol, f, s.bias,
                                 s.confidence, s.edge, "{}"});
        storage_->insert_model_output(
            {ms.ts, f, signal_engine::bias_to_verdict(s.bias), s.confidence,
             s.edge, weights_.get(f) ? weights_.get(f)->weight : 0.0, "{}"});
        out.push_back(s);
    }
    return out;
}

double Engine::simulate_outcome(const signal_engine::CombinedVerdict& v,
                                double notional) {
    // Paper outcome simulation: expected return ~ edge, scaled by confidence,
    // plus mean-zero noise. Drives the learning loop deterministically.
    rng_ ^= rng_ << 13; rng_ ^= rng_ >> 7; rng_ ^= rng_ << 17;
    double u = (rng_ >> 11) * (1.0 / 9007199254740992.0);
    // Mean slightly positive (edge), with enough variance to produce a
    // realistic mix of wins and losses for the learning loop + dashboards.
    double realized_ret = v.edge * v.confidence * 1.0 + (u - 0.5) * 0.10;
    return realized_ret * notional;
}

int Engine::run_iteration() {
    int executed = 0;
    auto states = feed_->poll();
    // Demo paper trades are modeled as round-trips that open and close within
    // the iteration (PnL realized immediately), so open-position/exposure state
    // is flat at the start of each iteration. Cumulative state that must persist
    // across iterations (daily PnL, consecutive losses, kill-switch) is NOT
    // reset here.
    pstate_.open_positions_total = 0;
    pstate_.open_positions_per_venue.clear();
    pstate_.exposure_per_symbol.clear();
    pstate_.exposure_per_market.clear();
    pstate_.exposure_per_category.clear();
    pstate_.open_risk_total = 0.0;
    for (const auto& ms : states) {
        const auto* venue_cfg = cfg_.find_venue(ms.venue);
        if (!venue_cfg) continue;
        // Demo trades only the two primary paper venues.
        if (ms.venue != "polymarket" && ms.venue != "alpaca") continue;

        auto cat = news_->score_for(ms.symbol);
        auto signals = gather_factors(ms, cat);
        auto verdict = signal_engine::combine(signals, weights_);

        // --- Sizing (fixed-fractional, capped) ---
        double base = cfg_.sizing.default_risk_per_trade_pct * equity_;
        double scale = clamp01(std::abs(verdict.bias) * verdict.confidence);
        // Advisory caps: DNN and whale sizing hints cannot raise size beyond
        // their configured caps. We conservatively cap the overall scale.
        scale = std::min(scale, cfg_.sizing.default_position_scale_cap);
        double notional = base * std::max(scale, 0.2);
        double qty = notional / std::max(0.0001, ms.price);
        std::string side = verdict.bias >= 0 ? "buy" : "sell";

        risk::OrderProposal o;
        o.venue = ms.venue;
        o.symbol = ms.symbol;
        o.market = ms.market;
        o.category = ms.category;
        o.side = side;
        o.qty = qty;
        o.price = ms.price;
        o.notional = notional;
        o.confidence = verdict.confidence;
        o.edge = verdict.edge;
        o.model_agreement_count = verdict.agreement_count;
        o.signal_age_minutes = 0;
        o.is_live = false;

        // Refresh dynamic risk state.
        pstate_.equity = equity_;
        pstate_.kill_switch_tripped = kill_switch_.tripped();
        pstate_.manual_resume_pending = kill_switch_.manual_resume_pending();

        // --- LAYER 1: RiskGate (final authority) ---
        auto decision = gate_->evaluate(o, pstate_);
        const std::string ts = util::now_iso8601();

        if (!decision.allowed) {
            storage_->insert_blocked({ts, o.venue, o.symbol, o.side, o.qty,
                                      decision.reason, decision.layer});
            storage_->append_event({ts, "risk_block", o.venue, o.symbol, "warn",
                                    "Order blocked: " + decision.reason, "{}"});
            continue;
        }

        // --- Mode router (paper) ---
        execution::PolymarketPaperAdapter poly;
        execution::AlpacaPaperAdapter alp;
        execution::DisabledLiveAdapter live(o.venue);
        execution::VenueAdapter* paper =
            (o.venue == "polymarket")
                ? static_cast<execution::VenueAdapter*>(&poly)
                : static_cast<execution::VenueAdapter*>(&alp);
        auto fill = router_.route(venue_cfg->mode, *paper, live, o,
                                  /*live_enabled=*/false);
        if (!fill.executed) {
            storage_->append_event({ts, "no_execution", o.venue, o.symbol, "info",
                                    fill.note, "{}"});
            continue;
        }

        // --- Outcome + bookkeeping ---
        double pnl = simulate_outcome(verdict, o.notional) - fill.fee;
        bool win = pnl >= 0;
        equity_ += pnl;
        peak_equity_ = std::max(peak_equity_, equity_);
        pstate_.realized_pnl_today_total += pnl;
        pstate_.realized_pnl_today_per_venue[o.venue] += pnl;
        pstate_.exposure_per_symbol[o.symbol] += o.notional;
        pstate_.exposure_per_market[o.market] += o.notional;
        pstate_.exposure_per_category[o.category] += o.notional;
        pstate_.open_positions_total =
            std::min(pstate_.open_positions_total + 1,
                     cfg_.risk.max_open_positions_total);
        pstate_.consecutive_losses = win ? 0 : pstate_.consecutive_losses + 1;
        accounts_->record_trade_outcome(o.venue, win);

        storage::TradeRow tr;
        tr.ts = ts; tr.venue = o.venue; tr.symbol = o.symbol;
        tr.market = o.market; tr.category = o.category; tr.side = o.side;
        tr.qty = o.qty; tr.price = o.price; tr.notional = o.notional;
        tr.fee = fill.fee; tr.mode = "paper"; tr.pnl = pnl;
        tr.outcome = win ? "win" : "loss";
        tr.combined_conf = verdict.confidence; tr.combined_edge = verdict.edge;
        storage_->insert_trade(tr);
        storage_->upsert_position(o.venue, o.symbol, o.market, o.category, o.side,
                                  o.qty, o.price, o.notional, ts);
        storage_->append_event(
            {ts, "trade", o.venue, o.symbol, "info",
             "Paper " + o.side + " " + o.symbol + " pnl=" + std::to_string(pnl),
             util::to_json({{"verdict", verdict.verdict}},
                           {{"pnl", pnl}, {"confidence", verdict.confidence}})});

        // Update per-factor performance estimate for adaptive tuning: factors
        // whose direction agreed with the realized move are rewarded.
        for (const auto& s : signals) {
            int side_sign = (verdict.bias >= 0) ? 1 : -1;
            int f_sign = (s.bias >= 0) ? 1 : -1;
            double agree = (f_sign == side_sign) ? 1.0 : -1.0;
            factor_perf_[s.factor] =
                0.9 * factor_perf_[s.factor] + 0.1 * agree * (win ? 1.0 : -1.0);
        }

        // Kill-switch enforcement: trip on daily-loss breach.
        double daily_loss = -pstate_.realized_pnl_today_total;
        if (daily_loss >= cfg_.risk.max_daily_loss_total_pct * equity_) {
            if (kill_switch_.trip("daily loss breach")) {
                for (const auto& [name, _] : accounts_->venues())
                    accounts_->trip_kill_switch(name);
                storage_->append_event({ts, "kill_switch", "", "", "critical",
                                        "KILL SWITCH TRIPPED: daily loss breach",
                                        "{}"});
            }
        }
        ++executed;
        ++trade_count_;
    }
    snapshot_balances();
    return executed;
}

void Engine::maybe_adapt(int iteration) {
    if (!cfg_.adaptive.adaptive_learning_enabled) return;
    if (!cfg_.adaptive.adaptive_weight_updates_enabled) return;
    if (trade_count_ == 0) return;
    if (iteration % 3 != 0) return;  // periodic cadence for the demo

    const std::string ts = util::now_iso8601();
    auto proposed = tuner_.propose_weight_update(weights_, factor_perf_);
    auto changed = tuner_.apply_and_record(weights_, proposed, "adaptive", ts);
    for (const auto& f : changed) {
        auto e = weights_.get(f);
        storage::WeightChangeRow wc;
        wc.ts = ts;
        wc.factor = f;
        wc.source = "adaptive";
        wc.old_weight = 0.0;
        wc.new_weight = e ? e->weight : 0.0;
        wc.locked = e && e->locked;
        storage_->insert_weight_change(wc);
    }
    if (!changed.empty()) {
        storage_->append_event({ts, "weight_change", "", "", "info",
                                "Adaptive weight update applied", "{}"});
        // Record param history entries from the tuner.
        for (const auto& h : tuner_.history()) {
            if (h.ts == ts)
                storage_->insert_param_history(
                    {h.ts, h.param, h.old_value, h.new_value, h.source,
                     h.reason});
        }
    }
}

void Engine::snapshot_balances() {
    const std::string ts = util::now_iso8601();
    double dd = peak_equity_ > 0 ? (peak_equity_ - equity_) / peak_equity_ : 0.0;
    storage_->insert_balance({ts, "AGGREGATE", equity_, equity_,
                              pstate_.realized_pnl_today_total, 0.0, dd});
    for (const auto& [name, st] : accounts_->venues()) {
        double vpnl = 0.0;
        auto it = pstate_.realized_pnl_today_per_venue.find(name);
        if (it != pstate_.realized_pnl_today_per_venue.end()) vpnl = it->second;
        storage_->insert_balance(
            {ts, name, cfg_.system.starting_paper_balance + vpnl, 0.0, vpnl, 0.0,
             0.0});
        storage_->upsert_venue_state(
            name, config::mode_to_string(st.mode), st.live_enabled,
            st.kill_switch_tripped, st.consecutive_losses, "", ts);
    }
}

void Engine::run(int iterations) {
    for (int i = 0; i < iterations; ++i) {
        run_iteration();
        maybe_adapt(i);
    }
    const std::string ts = util::now_iso8601();
    storage_->append_event(
        {ts, "summary", "", "", "info",
         "Paper loop complete: " + std::to_string(trade_count_) + " trades",
         util::to_json({}, {{"final_equity", equity_}})});
}

}  // namespace mal::core

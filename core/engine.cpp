#include "core/engine.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <functional>
#include <thread>

#include "core/bridge_client.hpp"
#include "core/util.hpp"
#include "learning/adapt_gate.hpp"

namespace mal::core {

namespace {
// Bounded per-symbol bar history kept in memory for indicators. (The minimum
// closed-trade adapt gate now lives in learning/adapt_gate.hpp so it is
// unit-testable without a full Engine — see kMinClosedTradesForAdapt there.)
constexpr size_t kBarHistoryCap = 300;
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
      rng_(opts_.seed ? opts_.seed : 1),
      bar_agg_(opts_.native_bar_seconds) {
    storage_ = std::make_unique<storage::Storage>(opts_.db_path);
    storage_->init_schema(opts_.schema_path);

    continuous_ = opts_.continuous;

    // Build a small instrument universe spanning the demo's paper venues.
    // Alpaca instruments are the native-strategy whitelist (crypto + equities).
    // Polymarket instruments remain for the generic factor loop (not whitelisted,
    // so they get no native bars/strategy).
    std::vector<market_data::Instrument> instruments = {
        {"polymarket", "PRES-2028-YES", "PRES-2028", "politics", 0.52},
        {"polymarket", "FED-CUT-Q3", "FED-CUT", "macro", 0.40},
        {"alpaca", "BTC/USD", "BTC/USD", "crypto", 64000.0},
        {"alpaca", "ETH/USD", "ETH/USD", "crypto", 3400.0},
        {"alpaca", "SPY", "SPY", "equity", 545.0},
        {"alpaca", "QQQ", "QQQ", "equity", 470.0},
    };

    // Select the market-data source: CLI override else config.
    std::string source =
        !opts_.data_source.empty() ? opts_.data_source : cfg_.market_data.source;
    if (source == "alpaca") {
        feed_ = std::make_unique<market_data::AlpacaFeed>(
            instruments, opts_.bridge_host, opts_.bridge_port, opts_.seed);
        alpaca_feed_ = true;
    } else {
        feed_ = std::make_unique<market_data::MockFeed>(instruments, opts_.seed);
    }
    news_ = std::make_unique<news::MockCatalystProvider>();
    gate_ = std::make_unique<risk::RiskGate>(cfg_.risk);
    accounts_ = std::make_unique<account::AccountManager>(cfg_);

    weights_.set_from_map(cfg_.model_weights.as_map());

    // Seed in-memory bar history from any persisted bars (empty on a fresh DB).
    for (const auto& sym : cfg_.strategy.whitelist) {
        auto bars = storage_->recent_bars(sym, cfg_.strategy.bar_timeframe,
                                          static_cast<int>(kBarHistoryCap));
        std::vector<strategy::Bar> hist;
        hist.reserve(bars.size());
        for (const auto& b : bars)
            hist.push_back({b.open, b.high, b.low, b.close, b.volume});
        bar_history_["alpaca|" + sym] = std::move(hist);
    }

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
    const market_data::MarketState& ms, const news::CatalystScore& cat,
    bool council_allowed) {
    std::vector<signal_engine::FactorSignal> out;
    std::vector<std::string> factors = {
        "llm_primary", "llm_secondary", "llm_tertiary",
        "rule_based",  "dnn_advisory",  "whale_signal"};
    // RL advisory (Task 4) is DEFERRED and ships OFF. Only when rl_enabled does
    // it join the ensemble and get scored via /score/rl; while off it never
    // appears as a factor and the RL service is never called. Advisory only —
    // its ensemble weight defaults to 0.0 so it can never be decisive.
    if (cfg_.rl.rl_enabled) factors.push_back("rl_advisory");

    // Rule-based is always computed in C++.
    // LLM/DNN/whale come from the bridge if enabled, else mocks. The three LLM
    // slots are the COUNCIL: when council_allowed is false (cost-control skip)
    // they stay on the in-process mock rather than making the expensive call.
    for (const auto& f : factors) {
        signal_engine::FactorSignal s = mock_factor(f, ms, cat);

        const bool is_llm = f == "llm_primary" || f == "llm_secondary" ||
                            f == "llm_tertiary";
        const bool may_call = opts_.use_bridge && f != "rule_based" &&
                              (council_allowed || !is_llm);
        if (may_call) {
            std::string endpoint = "/score/llm";
            if (f == "dnn_advisory") endpoint = "/score/dnn";
            else if (f == "whale_signal") endpoint = "/score/whale";
            else if (f == "rl_advisory") endpoint = "/score/rl";
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

bool Engine::is_whitelisted(const std::string& symbol) const {
    const auto& wl = cfg_.strategy.whitelist;
    return std::find(wl.begin(), wl.end(), symbol) != wl.end();
}

void Engine::update_bars(const market_data::MarketState& ms, long epoch_seconds) {
    if (!is_whitelisted(ms.symbol)) return;
    const std::string key = ms.venue + "|" + ms.symbol;
    auto closed = bar_agg_.add(key, epoch_seconds, ms.price, ms.volume);
    if (!closed) return;

    const std::string& tf = cfg_.strategy.bar_timeframe;
    // Persist the closed bar (idempotent on venue,symbol,timeframe,timestamp).
    storage_->upsert_bar({ms.venue, ms.symbol, tf, ms.ts, closed->open,
                          closed->high, closed->low, closed->close,
                          closed->volume});

    // Append to bounded in-memory history (oldest-first).
    auto& hist = bar_history_[key];
    hist.push_back(*closed);
    if (hist.size() > kBarHistoryCap)
        hist.erase(hist.begin(),
                   hist.begin() + (hist.size() - kBarHistoryCap));

    // Recompute + persist the symbol's regime (advisory; surfaced in the UI).
    auto rr = strategy::detect_regime(hist, cfg_.strategy);
    storage_->upsert_regime(ms.symbol, strategy::regime_to_string(rr.regime),
                            rr.adx, rr.rvol, ms.ts);

    // Native trading happens ONLY here (on a closed bar) unless the legacy
    // bootstrap simulator is explicitly enabled.
    if (!opts_.bootstrap_sim) handle_bar_close(ms, *closed, epoch_seconds);
}

void Engine::sync_portfolio_state() {
    pstate_.open_positions_total = 0;
    pstate_.open_positions_per_venue.clear();
    pstate_.exposure_per_symbol.clear();
    pstate_.exposure_per_market.clear();
    pstate_.exposure_per_category.clear();
    pstate_.open_risk_total = 0.0;
    for (const auto& [key, ap] : open_positions_) {
        const auto& p = ap.pos;
        double notional = p.entry_price * p.qty;
        ++pstate_.open_positions_total;
        ++pstate_.open_positions_per_venue[p.venue];
        pstate_.exposure_per_symbol[p.symbol] += notional;
        pstate_.exposure_per_market[p.market] += notional;
        pstate_.exposure_per_category[p.category] += notional;
        pstate_.open_risk_total += std::abs(p.entry_price - p.stop_price) * p.qty;
    }
    pstate_.equity = equity_;
    pstate_.kill_switch_tripped = kill_switch_.tripped();
    pstate_.manual_resume_pending = kill_switch_.manual_resume_pending();
}

void Engine::handle_bar_close(const market_data::MarketState& ms,
                              const strategy::Bar& bar, long now_epoch) {
    const std::string key = ms.venue + "|" + ms.symbol;
    const auto* venue_cfg = cfg_.find_venue(ms.venue);
    if (!venue_cfg) return;
    const std::string ts = util::now_iso8601();

    // ---------- EXIT path: manage an open position (NO council) ----------
    auto it = open_positions_.find(key);
    if (it != open_positions_.end()) {
        auto& ap = it->second;
        ++ap.pos.bars_held;
        auto reason = strategy::check_exit(ap.pos, bar);
        if (reason == strategy::ExitReason::None) return;

        double exit_price = strategy::exit_fill_price(ap.pos, reason, bar);
        std::string close_side =
            ap.pos.direction == strategy::Direction::Long ? "sell" : "buy";
        double notional = exit_price * ap.pos.qty;

        // Exits execute natively at the exit price — no RiskGate, no council.
        double fee = notional * 0.0001;
        double pnl = strategy::realized_pnl(ap.pos, exit_price) - fee;
        bool win = pnl >= 0;
        equity_ += pnl;
        peak_equity_ = std::max(peak_equity_, equity_);
        pstate_.realized_pnl_today_total += pnl;
        pstate_.realized_pnl_today_per_venue[ms.venue] += pnl;
        pstate_.consecutive_losses = win ? 0 : pstate_.consecutive_losses + 1;
        accounts_->record_trade_outcome(ms.venue, win);

        storage::TradeRow tr;
        tr.ts = ts; tr.venue = ms.venue; tr.symbol = ms.symbol;
        tr.market = ap.pos.market; tr.category = ap.pos.category;
        tr.side = close_side; tr.qty = ap.pos.qty; tr.price = exit_price;
        tr.notional = notional; tr.fee = fee; tr.mode = "paper"; tr.pnl = pnl;
        tr.outcome = win ? "win" : "loss";
        auto exit_verdict = signal_engine::combine(ap.entry_signals, weights_);
        tr.combined_conf = exit_verdict.confidence;
        tr.combined_edge = exit_verdict.edge;
        storage_->insert_trade(tr);
        // Mark the position flat (qty 0) in the positions table.
        storage_->upsert_position(ms.venue, ms.symbol, ap.pos.market,
                                  ap.pos.category, close_side, 0.0, exit_price,
                                  0.0, ts);
        storage_->append_event(
            {ts, "trade_exit", ms.venue, ms.symbol, "info",
             "Native exit (" + strategy::exit_reason_to_string(reason) + ") " +
                 ms.symbol + " pnl=" + std::to_string(pnl),
             util::to_json({{"reason", strategy::exit_reason_to_string(reason)}},
                           {{"pnl", pnl}, {"exit_price", exit_price}})});

        // Real-fill learning: attribute the realized win/loss to each factor
        // whose entry bias agreed with the taken direction.
        int side_sign = (exit_verdict.bias >= 0) ? 1 : -1;
        for (const auto& s : ap.entry_signals) {
            int f_sign = (s.bias >= 0) ? 1 : -1;
            double agree = (f_sign == side_sign) ? 1.0 : -1.0;
            factor_perf_[s.factor] =
                0.9 * factor_perf_[s.factor] + 0.1 * agree * (win ? 1.0 : -1.0);
        }
        ++closed_trade_count_;
        ++trade_count_;

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
        open_positions_.erase(it);
        return;
    }

    // ---------- ENTRY path: consider a new native strategy entry ----------
    // Per-day trade cap (UTC day bucket derived from the bar timestamp).
    std::string utc_day = ms.ts.size() >= 10 ? ms.ts.substr(0, 10) : ms.ts;
    if (trades_today_day_ != utc_day) {
        trades_today_day_ = utc_day;
        trades_today_ = 0;
    }
    if (kill_switch_.tripped()) return;
    if (trades_today_ >= cfg_.risk.max_trades_per_day) return;

    const bool is_crypto = ms.category == "crypto";
    auto decision = strategy::evaluate(bar_history_[key], cfg_.strategy, is_crypto);
    const auto& sig = decision.signal;
    if (!sig.has_signal) return;

    // ---------- Council cost cuts (Task 5) — decided BEFORE any council call --
    // Sizing is a function of the native signal alone (independent of the
    // council), so the order + the cheap risk pre-check can run first.
    double base = cfg_.sizing.default_risk_per_trade_pct * equity_;
    double scale = std::min(clamp01(sig.strength),
                            cfg_.sizing.default_position_scale_cap);
    double notional = base * std::max(scale, 0.2);
    double qty = notional / std::max(0.0001, sig.entry_price);
    std::string side = sig.direction == strategy::Direction::Long ? "buy" : "sell";

    risk::OrderProposal o;
    o.venue = ms.venue; o.symbol = ms.symbol; o.market = ms.market;
    o.category = ms.category; o.side = side; o.qty = qty; o.price = sig.entry_price;
    o.notional = notional; o.signal_age_minutes = 0; o.is_live = false;
    // confidence / edge / agreement are filled from the council verdict below.

    sync_portfolio_state();  // reflect currently-open native positions

    // Cut A — risk pre-check: run the EXISTING RiskGate read-only on a
    // provisional order whose QUALITY fields are set to pass, so only the hard
    // preconditions (kill switch, daily loss, position/exposure/notional caps)
    // can fire. When a hard limit already blocks the trade the council cannot
    // change that, so skip the Flash gate + council + execution entirely. This
    // REUSES RiskGate read-only; it does not modify or duplicate any gate logic.
    {
        risk::OrderProposal pre = o;
        pre.confidence = 1.0;
        pre.edge = 1.0;
        pre.model_agreement_count = cfg_.risk.required_model_agreement_count;
        auto pre_dec = gate_->evaluate(pre, pstate_);
        if (!pre_dec.allowed) {
            storage_->append_event(
                {ts, "risk_precheck", ms.venue, ms.symbol, "info",
                 "Council skipped (risk pre-check): " + pre_dec.reason,
                 util::to_json({{"reason", pre_dec.reason},
                                {"layer", pre_dec.layer}}, {})});
            return;
        }
    }

    // Cut B — market-hours skip: US equities skip the Flash gate + council
    // outside regular US trading hours (crypto stays 24/7). Only the expensive
    // council call is suppressed; native factors + execution still run.
    const bool market_hours_skip =
        cfg_.engine.equities_market_hours_only && ms.category == "equity" &&
        !util::us_equity_market_open();

    // Council cost-control gate: decide whether the full council may run.
    reset_if_new_day(council_state_, utc_day);
    bool council_allowed;
    if (market_hours_skip) {
        council_allowed = false;
        storage_->append_event(
            {ts, "market_hours", ms.venue, ms.symbol, "info",
             "Council skipped: equities outside US regular trading hours",
             util::to_json({{"reason", "market_hours"}, {"symbol", ms.symbol}},
                           {})});
    } else {
        auto cdec = signal_engine::decide_council(
            cfg_.council, council_state_, decision.regime.regime, sig.strength,
            ms.symbol, now_epoch);
        council_allowed = cdec == signal_engine::CouncilDecision::Proceed;
        if (!council_allowed) {
            storage_->append_event(
                {ts, "council_skip", ms.venue, ms.symbol, "info",
                 "Council skipped: " +
                     signal_engine::council_decision_to_string(cdec),
                 util::to_json(
                     {{"reason", signal_engine::council_decision_to_string(cdec)},
                      {"regime",
                       strategy::regime_to_string(decision.regime.regime)}},
                     {{"strength", sig.strength}})});
        } else {
            signal_engine::record_council_call(council_state_, ms.symbol,
                                               now_epoch);
        }
    }

    auto cat = news_->score_for(ms.symbol);
    auto signals = gather_factors(ms, cat, council_allowed);
    auto verdict = signal_engine::combine(signals, weights_);
    o.confidence = verdict.confidence;
    o.edge = verdict.edge;
    o.model_agreement_count = verdict.agreement_count;

    auto gate = gate_->evaluate(o, pstate_);
    if (!gate.allowed) {
        storage_->insert_blocked({ts, o.venue, o.symbol, o.side, o.qty,
                                  gate.reason, gate.layer});
        storage_->append_event({ts, "risk_block", o.venue, o.symbol, "warn",
                                "Native entry blocked: " + gate.reason, "{}"});
        return;
    }

    execution::AlpacaPaperAdapter alp(venue_cfg->paper_execution,
                                      opts_.bridge_host, opts_.bridge_port);
    execution::PolymarketPaperAdapter poly;
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
        return;
    }

    storage::TradeRow tr;
    tr.ts = ts; tr.venue = o.venue; tr.symbol = o.symbol; tr.market = o.market;
    tr.category = o.category; tr.side = o.side; tr.qty = o.qty; tr.price = o.price;
    tr.notional = o.notional; tr.fee = fill.fee; tr.mode = "paper";
    tr.outcome = "open";  // pnl left unset until the native exit closes it
    tr.combined_conf = verdict.confidence; tr.combined_edge = verdict.edge;
    storage_->insert_trade(tr);
    storage_->upsert_position(o.venue, o.symbol, o.market, o.category, o.side,
                              o.qty, o.price, o.notional, ts);
    storage_->append_event(
        {ts, "trade_entry", o.venue, o.symbol, "info",
         "Native " + sig.factor + " " + side + " " + o.symbol + " @ " +
             std::to_string(o.price),
         util::to_json({{"factor", sig.factor},
                        {"regime", strategy::regime_to_string(decision.regime.regime)}},
                       {{"stop", sig.stop_price},
                        {"target", sig.target_price},
                        {"strength", sig.strength}})});

    ActivePosition ap;
    ap.pos.venue = o.venue; ap.pos.symbol = o.symbol; ap.pos.market = o.market;
    ap.pos.category = o.category; ap.pos.factor = sig.factor; ap.pos.opened_ts = ts;
    ap.pos.direction = sig.direction; ap.pos.entry_price = o.price; ap.pos.qty = o.qty;
    ap.pos.stop_price = sig.stop_price; ap.pos.target_price = sig.target_price;
    ap.pos.time_stop_bars = sig.time_stop_bars; ap.pos.bars_held = 0;
    ap.entry_signals = std::move(signals);
    ap.entry_bias = verdict.bias;
    open_positions_[key] = std::move(ap);
    ++trades_today_;
    ++trade_count_;
}

int Engine::run_iteration() {
    int executed = 0;
    auto states = feed_->poll();
    if (alpaca_feed_) {
        last_poll_live_ =
            static_cast<market_data::AlpacaFeed*>(feed_.get())->last_poll_was_live();
    }
    // In continuous mode, optionally skip US equity instruments when the regular
    // trading session is closed. Crypto + prediction markets keep ticking 24/7.
    const bool gate_equity = continuous_ && cfg_.engine.respect_market_hours;
    const bool equity_open = !gate_equity || util::us_equity_market_open();
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
    const long now_epoch = static_cast<long>(
        std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch())
            .count());
    for (const auto& ms : states) {
        // Aggregate whitelisted symbols into bars + regime, and (default path)
        // run the native strategy entry/exit on a closed bar. The legacy generic
        // factor loop below only runs in explicit bootstrap-sim mode.
        update_bars(ms, now_epoch);
        if (!opts_.bootstrap_sim) continue;

        const auto* venue_cfg = cfg_.find_venue(ms.venue);
        if (!venue_cfg) continue;
        // Demo trades only the two primary paper venues.
        if (ms.venue != "polymarket" && ms.venue != "alpaca") continue;
        // Skip equities while the US session is closed (crypto stays 24/7).
        if (!equity_open && ms.category == "equity") continue;

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
        execution::AlpacaPaperAdapter alp(venue_cfg->paper_execution,
                                          opts_.bridge_host, opts_.bridge_port);
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
    // Real-fill learning gate (Task 3): the native path must accumulate a
    // minimum number of CLOSED trades before any weight nudge. The bootstrap
    // sim path keeps its legacy trade-count gate. Pure predicate lives in
    // learning/adapt_gate.hpp so it is unit-testable in isolation.
    if (!learning::has_enough_samples_to_adapt(
            opts_.bootstrap_sim, static_cast<long>(trade_count_),
            static_cast<long>(closed_trade_count_)))
        return;
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

void Engine::run_forever(const volatile std::sig_atomic_t* stop_flag) {
    int interval = opts_.interval_seconds > 0 ? opts_.interval_seconds
                                              : cfg_.engine.loop_interval_seconds;
    if (interval < 1) interval = 1;

    {
        const std::string ts = util::now_iso8601();
        std::string src = alpaca_feed_ ? "alpaca" : "mock";
        storage_->append_event(
            {ts, "continuous_start", "", "", "info",
             "Continuous paper loop started (source=" + src +
                 ", interval=" + std::to_string(interval) + "s)",
             "{}"});
    }

    int iteration = 0;
    while (!(stop_flag && *stop_flag)) {
        run_iteration();
        maybe_adapt(iteration);
        ++iteration;

        // Sleep in 1s slices so a signal interrupts promptly (finish the slice,
        // not the whole interval).
        for (int s = 0; s < interval && !(stop_flag && *stop_flag); ++s) {
            std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    }

    const std::string ts = util::now_iso8601();
    storage_->append_event(
        {ts, "continuous_stop", "", "", "info",
         "Continuous paper loop stopped after " + std::to_string(iteration) +
             " ticks, " + std::to_string(trade_count_) + " trades",
         util::to_json({}, {{"final_equity", equity_}})});
    // SQLite writes autocommit per statement, so state is already durable.
}

}  // namespace mal::core

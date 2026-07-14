#include "core/engine.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <functional>
#include <iterator>
#include <stdexcept>
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

    // Resolve the operator kill-request control file written by the API backend
    // (api_server/store.py). Contract: env MAL_CONTROL_DIR overrides, else the
    // configured system.control_dir (default ".control"); the file is
    // kill_request.json within that dir. Processed requests are archived beside
    // it so a stale request can never re-trip the kill switch on a later run.
    {
        const char* env_dir = std::getenv("MAL_CONTROL_DIR");
        std::string dir = (env_dir && *env_dir) ? std::string(env_dir)
                                                 : cfg_.system.control_dir;
        if (dir.empty()) dir = ".control";
        kill_request_path_ = dir + "/kill_request.json";
        kill_request_archive_path_ = dir + "/kill_request.processed.json";
        controls_path_ = dir + "/controls.json";
        layer_toggles_ = read_layer_toggles(controls_path_);
        prev_layer_toggles_ = layer_toggles_;
        operator_controls_ =
            read_operator_controls(controls_path_, cfg_.strategy.whitelist);
        prev_operator_controls_ = operator_controls_;
    }

    // Resolve the offline feed mode early so alpaca_paper can force the online
    // Alpaca feed below. feed_mode never affects live: Alpaca is paper + data
    // only, IBKR live stays gated off.
    feed_mode_ = !opts_.feed_mode.empty() ? opts_.feed_mode
                                          : cfg_.simulation.feed_mode;

    // Instrument universe. Alpaca is the only trading venue in the loop and its
    // instruments are the native-strategy whitelist (crypto + equities). Alpaca
    // is paper and market data only. IBKR is live only and is not traded here.
    std::vector<market_data::Instrument> instruments = {
        {"alpaca", "BTC/USD", "BTC/USD", "crypto", 64000.0},
        {"alpaca", "ETH/USD", "ETH/USD", "crypto", 3400.0},
        {"alpaca", "SPY", "SPY", "equity", 545.0},
        {"alpaca", "QQQ", "QQQ", "equity", 470.0},
    };
    // Keep the universe so a runtime feed switch (Task 3) can rebuild the tick
    // feed or the bar-driven generators without reconstructing the engine.
    all_instruments_ = instruments;

    // Select the market-data source: CLI override else config. feed_mode
    // alpaca_paper forces the online Alpaca feed (the primary online loop).
    std::string source =
        !opts_.data_source.empty() ? opts_.data_source : cfg_.market_data.source;
    if (feed_mode_ == "alpaca_paper") source = "alpaca";
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

    // --- Offline clock resolution + bar-mode setup ----------------------------
    // feed_mode_ was resolved above. These control ONLY how the offline loop is
    // driven; they never affect live trading (Alpaca is paper + market-data only,
    // IBKR live stays gated off).
    const std::string clock = !opts_.clock_mode.empty() ? opts_.clock_mode
                                                        : cfg_.simulation.clock_mode;
    simulated_clock_ = (clock == "simulated");
    // Launch feed/clock is the fallback for the runtime toggle (Task 3): a
    // missing/invalid controls.json value keeps what the engine launched with, so
    // an offline run is never forced onto the live feed by an absent file.
    launch_feed_clock_ = {feed_mode_, clock};
    bar_step_seconds_ = opts_.native_bar_seconds > 0 ? opts_.native_bar_seconds : 1;
    // Base the simulated clock at 2026-01-05T00:00:00Z (a Monday) so day buckets
    // and any market-hours checks land on sensible weekday dates.
    sim_epoch_ = 1767571200;
    if (feed_mode_ == "synthetic_regimes" || feed_mode_ == "replay") {
        // Bar-driven modes build indicator history purely from the fed bars.
        bar_history_.clear();
        init_bar_mode(instruments);
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
    bool council_allowed, const strategy::StrategySignal* native) {
    std::vector<signal_engine::FactorSignal> out;
    std::vector<std::string> all = {
        "llm_primary", "llm_secondary", "llm_tertiary",
        "rule_based",  "dnn_advisory",  "whale_signal"};
    // RL advisory (Task 4) is DEFERRED and ships OFF. Only when rl_enabled does
    // it join the ensemble and get scored via /score/rl; while off it never
    // appears as a factor and the RL service is never called. Advisory only —
    // its ensemble weight defaults to 0.0 so it can never be decisive.
    if (cfg_.rl.rl_enabled) all.push_back("rl_advisory");
    // Per-layer toggles (controls.json): a layer toggled off drops its factor
    // from the ensemble for this iteration, contributing nothing to direction,
    // sizing, confidence, or edge. rule_based (native) and rl_advisory are not
    // gated here. This removes an advisory input, never safety: the RiskGate
    // still evaluates every order below.
    std::vector<std::string> factors;
    for (const auto& f : all) {
        if (!factor_enabled(f, layer_toggles_)) continue;
        // Council model toggles (controls.json): drop a disabled provider slot for
        // this iteration. The ensemble math handles a reduced provider set via the
        // normalized weights. rule_based and the other factors are untouched.
        if (f == "llm_primary" && !operator_controls_.llm_primary) continue;
        if (f == "llm_secondary" && !operator_controls_.llm_secondary) continue;
        if (f == "llm_tertiary" && !operator_controls_.llm_tertiary) continue;
        factors.push_back(f);
    }

    // Rule-based is always computed in C++.
    // LLM/DNN/whale come from the bridge if enabled, else mocks. The three LLM
    // slots are the COUNCIL: when council_allowed is false (cost-control skip)
    // they stay on the in-process mock rather than making the expensive call.
    for (const auto& f : factors) {
        signal_engine::FactorSignal s = mock_factor(f, ms, cat);

        // The native strategy IS the rule-based factor: when a native entry
        // signal is supplied, drive `rule_based` from that genuine technical
        // setup instead of the hash mock, so its conviction contributes to the
        // combined confidence/edge/agreement the RiskGate evaluates. This does
        // NOT touch the gate or its thresholds; it only reports the real signal.
        if (f == "rule_based" && native && native->has_signal) {
            const double str = clamp01(native->strength);
            const double dir =
                native->direction == strategy::Direction::Long ? 1.0 : -1.0;
            s.bias = dir * std::clamp(0.4 + 0.6 * str, 0.0, 1.0);
            s.confidence = clamp01(0.7 + 0.3 * str);
            s.edge = 0.05 + 0.10 * str;
        }

        const bool is_llm = f == "llm_primary" || f == "llm_secondary" ||
                            f == "llm_tertiary";
        // Source axis (controls.json): only call the real service (bridge) when
        // the layer is set on-real. On-mock keeps the deterministic C++ mock for
        // this factor even though the bridge is up, so the operator can isolate
        // one layer without stopping the run. rule_based is always native C++.
        const bool source_real = factor_source_real(f, layer_toggles_);
        const bool may_call = opts_.use_bridge && f != "rule_based" &&
                              (council_allowed || !is_llm) && source_real;
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
            // The /score/llm call fans out to the full real council (gate + three
            // providers), so it needs the long timeout, or the engine hangs up
            // mid-round-trip and the council returns no verdict (the no-trade
            // stall). Fast local scores use the short timeout. Both from config.
            const int timeout_ms =
                (endpoint == "/score/llm")
                    ? cfg_.council.engine_council_call_timeout_ms
                    : cfg_.council.engine_bridge_call_timeout_ms;
            auto resp = bridge::http_post_json(opts_.bridge_host,
                                               opts_.bridge_port, endpoint, body,
                                               timeout_ms);
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
    // Tick path (flat_random_walk): aggregate streaming ticks into bars; route a
    // just-CLOSED bar through the shared closed-bar handler.
    if (!is_whitelisted(ms.symbol)) return;
    const std::string key = ms.venue + "|" + ms.symbol;
    auto closed = bar_agg_.add(key, epoch_seconds, ms.price, ms.volume);
    if (!closed) return;
    on_closed_bar(ms, *closed, epoch_seconds);
}

void Engine::on_closed_bar(const market_data::MarketState& ms,
                           const strategy::Bar& closed, long epoch) {
    const std::string& tf = cfg_.strategy.bar_timeframe;
    // Persist the closed bar (idempotent on venue,symbol,timeframe,timestamp).
    storage_->upsert_bar({ms.venue, ms.symbol, tf, ms.ts, closed.open,
                          closed.high, closed.low, closed.close, closed.volume});

    // Append to bounded in-memory history (oldest-first).
    const std::string key = ms.venue + "|" + ms.symbol;
    auto& hist = bar_history_[key];
    hist.push_back(closed);
    if (hist.size() > kBarHistoryCap)
        hist.erase(hist.begin(),
                   hist.begin() + (hist.size() - kBarHistoryCap));

    // Recompute + persist the symbol's regime (advisory; surfaced in the UI). An
    // operator regime pin (controls.json, test-only) overrides the detector for
    // that symbol so the UI and the council neutral-skip both see the pin.
    auto rr = strategy::detect_regime(hist, cfg_.strategy);
    rr.regime = pinned_or(ms.symbol, rr.regime);
    storage_->upsert_regime(ms.symbol, strategy::regime_to_string(rr.regime),
                            rr.adx, rr.rvol, ms.ts);

    // Warm-state tracking on the real path (Task 2): log a transition when the
    // symbol crosses cold<->warm. Only the alpaca_paper (real) loop gates entry
    // on warmth; offline feed modes keep building history for tests unchanged.
    if (feed_mode_ == "alpaca_paper") track_warm_state(ms.symbol, ms.venue, key, ms.ts);

    // Native trading happens ONLY on a closed bar unless the legacy bootstrap
    // simulator is explicitly enabled. This is the single closed-bar path shared
    // by the tick feed and the synthetic/replay bar feeds.
    if (!opts_.bootstrap_sim) handle_bar_close(ms, closed, epoch);
}

void Engine::init_bar_mode(
    const std::vector<market_data::Instrument>& instruments) {
    // Idempotent so a runtime feed switch (Task 3) can re-enter a bar-driven mode
    // cleanly: clear any prior generators / replay queue first.
    bar_instruments_.clear();
    synth_gens_.clear();
    replay_queue_.clear();
    replay_pos_ = 0;
    for (const auto& i : instruments)
        if (is_whitelisted(i.symbol)) bar_instruments_.push_back(i);

    if (feed_mode_ == "synthetic_regimes") {
        // One deterministic generator per whitelisted instrument, independently
        // seeded so the feed is reproducible under opts_.seed.
        const uint64_t base = opts_.seed ? opts_.seed : 1;
        for (size_t k = 0; k < bar_instruments_.size(); ++k)
            synth_gens_.emplace_back(bar_instruments_[k].price,
                                     base + 1000ull * (k + 1));
        return;
    }

    // replay: load stored bars for each whitelisted symbol within the window.
    const std::string& tf = cfg_.strategy.bar_timeframe;
    const std::string start = cfg_.simulation.replay_start_date;
    const std::string end = cfg_.simulation.replay_end_date.empty()
        ? std::string()
        : cfg_.simulation.replay_end_date + "T23:59:59Z";
    for (const auto& bi : bar_instruments_) {
        auto rows = storage_->bars_in_range(bi.symbol, tf, start, end);
        for (const auto& r : rows) {
            BarTick t;
            t.ms.venue = bi.venue;
            t.ms.symbol = bi.symbol;
            t.ms.market = bi.market;
            t.ms.category = bi.category;
            t.ms.price = r.close;
            t.ms.ts = r.timestamp;
            t.bar = {r.open, r.high, r.low, r.close, r.volume};
            replay_queue_.push_back(std::move(t));
        }
    }
    std::sort(replay_queue_.begin(), replay_queue_.end(),
              [](const BarTick& a, const BarTick& b) { return a.ms.ts < b.ms.ts; });
    // Council-cooldown spacing keys off the TRUE historical bar time (matching
    // the per-day trade cap, which already uses the bar ts), so cooldowns reflect
    // real historical spacing rather than a synthetic sequential epoch. Fall back
    // to a monotonic epoch only if a stored ts is malformed.
    for (size_t k = 0; k < replay_queue_.size(); ++k) {
        long hist = util::iso8601_to_epoch(replay_queue_[k].ms.ts);
        replay_queue_[k].epoch =
            hist > 0 ? hist
                     : sim_epoch_ + static_cast<long>(k) * bar_step_seconds_;
    }

    if (replay_queue_.empty()) {
        std::string wl;
        for (size_t k = 0; k < bar_instruments_.size(); ++k)
            wl += (k ? "," : "") + bar_instruments_[k].symbol;
        throw std::runtime_error(
            "replay feed: no bars in the 'bars' table for symbols [" + wl +
            "] timeframe " + tf +
            (start.empty() && end.empty() ? "" : " in the configured date range") +
            ". Run the Alpaca historical backfill first (e.g. the paper loop with "
            "--data-source alpaca, or the market_data backfill helper) so the "
            "bars table has data before replay.");
    }
}

int Engine::step_bar_mode() {
    // Operator halt honored BEFORE stepping bars: the bar-driven feed modes
    // (synthetic_regimes / replay) do not go through run_iteration, so the check
    // lives here too. Same latching kill switch, no separate path.
    consume_operator_kill_request();
    consume_layer_toggles();
    consume_operator_controls();
    if (feed_mode_ == "synthetic_regimes") {
        // All whitelisted instruments close a bar at the same simulated instant.
        const std::string ts = util::epoch_to_iso8601(sim_epoch_);
        for (size_t k = 0; k < bar_instruments_.size(); ++k) {
            auto ob = synth_gens_[k].next();
            const auto& bi = bar_instruments_[k];
            market_data::MarketState ms;
            ms.venue = bi.venue;
            ms.symbol = bi.symbol;
            ms.market = bi.market;
            ms.category = bi.category;
            ms.price = ob.close;
            ms.ts = ts;
            strategy::Bar bar{ob.open, ob.high, ob.low, ob.close, ob.volume};
            on_closed_bar(ms, bar, sim_epoch_);
        }
        sim_epoch_ += bar_step_seconds_;
        return static_cast<int>(bar_instruments_.size());
    }
    // replay: one stored bar per step, chronological, until the range is spent.
    if (replay_pos_ >= replay_queue_.size()) return 0;
    const auto& t = replay_queue_[replay_pos_++];
    on_closed_bar(t.ms, t.bar, t.epoch);
    return 1;
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
    // Use the bar's own timestamp so simulated/replay trades + events (and the
    // per-day trade-cap bucket below) advance with bar time, not wall-clock. In
    // the tick path ms.ts is the live feed time, so behavior there is unchanged.
    const std::string ts = ms.ts.empty() ? util::now_iso8601() : ms.ts;

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
    // Warm-state gate (Task 2): on the real paper path, do not evaluate a symbol
    // for entry until its indicators are warm. A cold symbol waits (the cold/warm
    // transition is logged in on_closed_bar); it never fires on partial data.
    if (feed_mode_ == "alpaca_paper" && !symbol_is_warm(key)) return;

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
    // Operator regime pin (test-only) overrides the detected regime used for the
    // council neutral-skip and the surfaced label. The strategy signal selection
    // already ran on the detected regime inside evaluate().
    decision.regime.regime = pinned_or(ms.symbol, decision.regime.regime);
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
    // change that, so skip the base-check gate + council + execution entirely. This
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

    // Cut B — market-hours skip: US equities skip the base-check gate + council
    // outside regular US trading hours (crypto stays 24/7). Only the expensive
    // council call is suppressed; native factors + execution still run.
    // Market-hours skip keys off the SIMULATED timestamp under clock_mode
    // simulated, and real wall-clock under clock_mode real, so an offline
    // simulated run gates equities by simulated bar time, not the wall clock.
    const std::time_t mh_time = simulated_clock_
                                    ? static_cast<std::time_t>(now_epoch)
                                    : std::time(nullptr);
    const bool market_hours_skip =
        cfg_.engine.equities_market_hours_only && ms.category == "equity" &&
        !util::us_equity_market_open(mh_time);

    // Council cost-control gate: decide whether the full council may run. The
    // runtime budget override (controls.json) adjusts the daily budget and the
    // per-symbol cooldown within their validated bounds; a -1 keeps the config.
    reset_if_new_day(council_state_, utc_day);
    config::CouncilConfig rc = cfg_.council;
    if (operator_controls_.council_daily_budget >= 0)
        rc.council_daily_budget = operator_controls_.council_daily_budget;
    if (operator_controls_.per_symbol_cooldown_minutes >= 0)
        rc.per_symbol_council_cooldown_minutes =
            operator_controls_.per_symbol_cooldown_minutes;
    bool council_allowed;
    if (market_hours_skip) {
        council_allowed = false;
        storage_->append_event(
            {ts, "market_hours", ms.venue, ms.symbol, "info",
             "Council skipped: equities outside US regular trading hours",
             util::to_json({{"reason", "market_hours"}, {"symbol", ms.symbol}},
                           {})});
    } else if (!any_council_provider(operator_controls_)) {
        // Model toggles disabled every provider: the council cannot run, so fall
        // back to a clearly logged skip. Native factors + execution still run.
        council_allowed = false;
        storage_->append_event(
            {ts, "council_skip", ms.venue, ms.symbol, "info",
             "Council skipped: all providers disabled (model toggles)",
             util::to_json({{"reason", "no_providers"}, {"symbol", ms.symbol}},
                           {})});
    } else {
        auto cdec = signal_engine::decide_council(
            rc, council_state_, decision.regime.regime, sig.strength,
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
    auto signals = gather_factors(ms, cat, council_allowed, &sig);
    // native_conviction_feeds_gate gates the mild double-count. Default true
    // keeps the native rule_based conviction feeding the gate confidence/edge.
    // When false, the gate confidence/edge come from advisory factors alone and
    // the native setup still drives direction and sizing. RiskGate untouched.
    auto verdict = signal_engine::compose_gate_verdict(
        signals, weights_, cfg_.engine.native_conviction_feeds_gate, 0.05,
        cfg_.adaptive.rule_based_weight_floor);
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
    // IBKR is the only live venue. Every other venue gets a disabled live
    // adapter. Live stays off regardless: route() refuses the Live branch while
    // live_enabled is false, so no live adapter is ever invoked here.
    execution::IbkrLiveAdapter ibkr_live(opts_.bridge_host, opts_.bridge_port);
    execution::DisabledLiveAdapter disabled_live(o.venue);
    execution::VenueAdapter& live =
        (o.venue == "ibkr") ? static_cast<execution::VenueAdapter&>(ibkr_live)
                            : static_cast<execution::VenueAdapter&>(disabled_live);
    auto fill = router_.route(venue_cfg->mode, alp, live, o,
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

void Engine::consume_operator_kill_request() {
    std::ifstream in(kill_request_path_);
    if (!in) return;  // no pending request on disk
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    in.close();
    // Only a positive halt request acts; a cleared (requested=false) file is a
    // no-op left in place. Parsing uses the same tiny JSON helpers as the bridge.
    if (!bridge::json_get_bool(body, "requested", false)) return;

    const std::string why = bridge::json_get_string(body, "reason", "");
    const std::string reason =
        why.empty() ? std::string("operator kill request (GUI)")
                    : "operator kill request (GUI): " + why;

    const std::string ts = util::now_iso8601();
    // SAME latching mechanism as the loss-triggered trip — not a separate path.
    if (kill_switch_.trip(reason)) {
        for (const auto& [name, _] : accounts_->venues())
            accounts_->trip_kill_switch(name);
        storage_->append_event({ts, "kill_switch", "", "", "critical",
                                "KILL SWITCH TRIPPED: " + reason, "{}"});
    }
    // Archive the processed request (atomic rename) so a stale file cannot
    // re-trip on restart. Fall back to deletion if the rename fails.
    std::remove(kill_request_archive_path_.c_str());
    if (std::rename(kill_request_path_.c_str(),
                    kill_request_archive_path_.c_str()) != 0) {
        std::remove(kill_request_path_.c_str());
    }
}

void Engine::consume_layer_toggles() {
    // Read the four toggleable layer states from controls.json each iteration
    // (same control-file pattern as the kill request). Missing or malformed
    // means all layers ON, the safe default. A toggle off drops that layer's
    // factor from the ensemble. It NEVER disables the RiskGate, the kill switch,
    // or any Level-1 limit. Safety has no toggle.
    layer_toggles_ = read_layer_toggles(controls_path_);
    if (layer_toggles_ == prev_layer_toggles_) return;
    const std::string ts = util::now_iso8601();
    auto logone = [&](const char* name, bool oldv, bool newv) {
        if (oldv == newv) return;
        storage_->append_event(
            {ts, "layer_toggle", "", "", "info",
             std::string("Layer ") + name + ": " + (oldv ? "on" : "off") +
                 " -> " + (newv ? "on" : "off"),
             util::to_json({{"layer", name}, {"old", oldv ? "on" : "off"},
                            {"new", newv ? "on" : "off"}}, {})});
    };
    logone("adaptive", prev_layer_toggles_.adaptive, layer_toggles_.adaptive);
    logone("council", prev_layer_toggles_.council, layer_toggles_.council);
    logone("dnn_advisory", prev_layer_toggles_.dnn_advisory,
           layer_toggles_.dnn_advisory);
    logone("whale", prev_layer_toggles_.whale, layer_toggles_.whale);
    // Source-axis changes are logged separately as layer_source (mock/real).
    auto logsrc = [&](const char* name, bool oldr, bool newr) {
        if (oldr == newr) return;
        storage_->append_event(
            {ts, "layer_source", "", "", "info",
             std::string("Layer ") + name + " source: " +
                 (oldr ? "real" : "mock") + " -> " + (newr ? "real" : "mock"),
             util::to_json({{"layer", name}, {"old", oldr ? "real" : "mock"},
                            {"new", newr ? "real" : "mock"}}, {})});
    };
    logsrc("council", prev_layer_toggles_.council_real,
           layer_toggles_.council_real);
    logsrc("dnn_advisory", prev_layer_toggles_.dnn_advisory_real,
           layer_toggles_.dnn_advisory_real);
    logsrc("whale", prev_layer_toggles_.whale_real, layer_toggles_.whale_real);
    prev_layer_toggles_ = layer_toggles_;
}

void Engine::consume_operator_controls() {
    // Read the remaining operator controls (model toggles, budget, regime pins)
    // from controls.json each iteration. Missing/malformed keeps the safe current
    // behavior. Advisory/cost only, never a safety bypass.
    operator_controls_ =
        read_operator_controls(controls_path_, cfg_.strategy.whitelist);
    if (operator_controls_ == prev_operator_controls_) return;
    const std::string ts = util::now_iso8601();
    auto logprov = [&](const char* slot, bool oldv, bool newv) {
        if (oldv == newv) return;
        storage_->append_event(
            {ts, "model_toggle", "", "", "info",
             std::string("Council provider ") + slot + ": " +
                 (oldv ? "on" : "off") + " -> " + (newv ? "on" : "off"),
             util::to_json({{"slot", slot}, {"old", oldv ? "on" : "off"},
                            {"new", newv ? "on" : "off"}}, {})});
    };
    logprov("llm_primary", prev_operator_controls_.llm_primary,
            operator_controls_.llm_primary);
    logprov("llm_secondary", prev_operator_controls_.llm_secondary,
            operator_controls_.llm_secondary);
    logprov("llm_tertiary", prev_operator_controls_.llm_tertiary,
            operator_controls_.llm_tertiary);
    if (operator_controls_.council_daily_budget !=
            prev_operator_controls_.council_daily_budget ||
        operator_controls_.per_symbol_cooldown_minutes !=
            prev_operator_controls_.per_symbol_cooldown_minutes) {
        storage_->append_event(
            {ts, "budget_change", "", "", "info",
             "Council budget: budget " +
                 std::to_string(prev_operator_controls_.council_daily_budget) +
                 " -> " + std::to_string(operator_controls_.council_daily_budget) +
                 ", cooldown " +
                 std::to_string(prev_operator_controls_.per_symbol_cooldown_minutes) +
                 " -> " +
                 std::to_string(operator_controls_.per_symbol_cooldown_minutes),
             util::to_json({}, {{"budget", static_cast<double>(
                                              operator_controls_.council_daily_budget)},
                                {"cooldown", static_cast<double>(
                                                 operator_controls_.per_symbol_cooldown_minutes)}})});
    }
    auto pin_of = [](const OperatorControls& oc, const std::string& s) {
        auto it = oc.regime_pins.find(s);
        return it == oc.regime_pins.end() ? std::string() : it->second;
    };
    for (const auto& sym : cfg_.strategy.whitelist) {
        std::string oldp = pin_of(prev_operator_controls_, sym);
        std::string newp = pin_of(operator_controls_, sym);
        if (oldp == newp) continue;
        storage_->append_event(
            {ts, "regime_pin", "", sym, "info",
             "Regime pin " + sym + ": " + (oldp.empty() ? "auto" : oldp) +
                 " -> " + (newp.empty() ? "auto (cleared)" : newp),
             util::to_json({{"symbol", sym}, {"old", oldp.empty() ? "auto" : oldp},
                            {"new", newp.empty() ? "auto" : newp}}, {})});
    }
    prev_operator_controls_ = operator_controls_;
}

strategy::Regime Engine::pinned_or(const std::string& symbol,
                                   strategy::Regime detected) const {
    auto it = operator_controls_.regime_pins.find(symbol);
    if (it == operator_controls_.regime_pins.end() || it->second.empty())
        return detected;
    return strategy::regime_from_string(it->second);
}

void Engine::track_warm_state(const std::string& symbol, const std::string& venue,
                              const std::string& key, const std::string& ts) {
    const auto& hist = bar_history_[key];
    const bool warm =
        strategy::indicators_warm(static_cast<int>(hist.size()), cfg_.strategy);
    auto it = symbol_warm_.find(key);
    if (it != symbol_warm_.end() && it->second == warm) return;  // no transition
    const bool first = it == symbol_warm_.end();
    symbol_warm_[key] = warm;
    const int need = strategy::min_bars_to_warm(cfg_.strategy);
    const int have = static_cast<int>(hist.size());
    const std::string when = ts.empty() ? util::now_iso8601() : ts;
    const std::string bars_s =
        std::to_string(have) + "/" + std::to_string(need) + " bars";
    std::string msg =
        warm ? "Indicators WARM for " + symbol + " (" + bars_s + ")"
             : std::string(first ? "Indicators COLD for " : "Indicators back COLD for ") +
                   symbol + " (" + bars_s + ") — waiting, no entry";
    storage_->append_event(
        {when, "warm_state", venue, symbol, "info", msg,
         util::to_json({{"symbol", symbol}, {"state", warm ? "warm" : "cold"}},
                       {{"bars", static_cast<double>(have)},
                        {"need", static_cast<double>(need)}})});
}

bool Engine::symbol_is_warm(const std::string& key) const {
    auto it = bar_history_.find(key);
    const int n =
        it == bar_history_.end() ? 0 : static_cast<int>(it->second.size());
    return strategy::indicators_warm(n, cfg_.strategy);
}

std::vector<Engine::SymbolWarm> Engine::warm_states() const {
    std::vector<SymbolWarm> out;
    for (const auto& sym : cfg_.strategy.whitelist) {
        const std::string key = "alpaca|" + sym;
        auto it = bar_history_.find(key);
        const int n =
            it == bar_history_.end() ? 0 : static_cast<int>(it->second.size());
        out.push_back({sym, strategy::indicator_warm_state(n, cfg_.strategy)});
    }
    return out;
}

void Engine::consume_feed_clock() {
    // Read the runtime feed/clock toggle each iteration (same control-file
    // pattern as the layer toggles). Fallback = the launch feed/clock, so a
    // missing/invalid value never forces an offline run onto the live feed.
    const FeedClock req = read_feed_clock(controls_path_, launch_feed_clock_);
    const std::string ts = util::now_iso8601();

    // Clock switch: applies immediately (run_iteration reads simulated_clock_ each
    // tick). No open-position impact, so it is never blocked.
    const bool want_sim = req.clock_mode == "simulated";
    if (want_sim != simulated_clock_) {
        storage_->append_event(
            {ts, "clock_mode", "", "", "info",
             std::string("Clock mode ") + (simulated_clock_ ? "simulated" : "real") +
                 " -> " + (want_sim ? "simulated" : "real"),
             util::to_json({{"old", simulated_clock_ ? "simulated" : "real"},
                            {"new", want_sim ? "simulated" : "real"}}, {})});
        simulated_clock_ = want_sim;
    }

    // Feed switch: enforce the open-position safety rule first.
    if (req.feed_mode == feed_mode_) {
        blocked_feed_request_.clear();
        return;
    }
    if (feed_switch_orphans_position(feed_mode_, req.feed_mode,
                                     has_open_positions())) {
        if (blocked_feed_request_ != req.feed_mode) {  // log once per request
            blocked_feed_request_ = req.feed_mode;
            storage_->append_event(
                {ts, "feed_mode_blocked", "", "", "warn",
                 "Feed switch " + feed_mode_ + " -> " + req.feed_mode +
                     " BLOCKED: " + std::to_string(open_positions_.size()) +
                     " open paper position(s). Close them (or let native exits "
                     "flatten) first; the loop keeps running on " + feed_mode_ + ".",
                 util::to_json({{"old", feed_mode_}, {"new", req.feed_mode},
                                {"reason", "open_position"}},
                               {{"open", static_cast<double>(open_positions_.size())}})});
        }
        return;  // never orphan a position
    }
    blocked_feed_request_.clear();
    apply_feed_switch(req.feed_mode, ts);
}

void Engine::apply_feed_switch(const std::string& new_feed, const std::string& ts) {
    const std::string old_feed = feed_mode_;
    feed_mode_ = new_feed;
    if (new_feed == "synthetic_regimes" || new_feed == "replay") {
        // Bar-driven modes build indicator history from the fed bars. Rebuild the
        // generators / replay queue. Replay may refuse (empty bars) — do NOT
        // crash the running loop; log and fall back to the prior feed.
        try {
            init_bar_mode(all_instruments_);
        } catch (const std::exception& e) {
            feed_mode_ = old_feed;
            storage_->append_event(
                {ts, "feed_mode_blocked", "", "", "warn",
                 "Feed switch " + old_feed + " -> " + new_feed +
                     " refused: " + e.what() + ". Loop stays on " + old_feed + ".",
                 util::to_json({{"old", old_feed}, {"new", new_feed},
                                {"reason", "feed_init_failed"}}, {})});
            return;
        }
    } else {
        // Tick-path modes: rebuild the feed source. alpaca_paper forces the online
        // Alpaca feed; flat_random_walk uses the deterministic mock feed.
        if (new_feed == "alpaca_paper") {
            feed_ = std::make_unique<market_data::AlpacaFeed>(
                all_instruments_, opts_.bridge_host, opts_.bridge_port, opts_.seed);
            alpaca_feed_ = true;
        } else {
            feed_ = std::make_unique<market_data::MockFeed>(all_instruments_,
                                                            opts_.seed);
            alpaca_feed_ = false;
        }
    }
    storage_->append_event(
        {ts, "feed_mode", "", "", "info",
         "Feed mode " + old_feed + " -> " + new_feed +
             (new_feed == "alpaca_paper"
                  ? " (warm-start gate re-armed: entries wait until warm)"
                  : ""),
         util::to_json({{"old", old_feed}, {"new", new_feed}}, {})});
}

int Engine::run_iteration() {
    int executed = 0;
    // Operator halt honored BEFORE any signal this iteration (same latching kill
    // switch as a loss-triggered halt). See consume_operator_kill_request.
    consume_operator_kill_request();
    consume_layer_toggles();
    consume_operator_controls();
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
    // Under the simulated clock, bar time advances internally so finite runs
    // actually cross bar boundaries (real clock is used for the continuous,
    // live-adjacent loop). Each tick advances one bar step.
    long now_epoch;
    if (simulated_clock_) {
        now_epoch = sim_epoch_;
        sim_epoch_ += bar_step_seconds_;
    } else {
        now_epoch = static_cast<long>(
            std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::system_clock::now().time_since_epoch())
                .count());
    }
    for (const auto& ms : states) {
        // Aggregate whitelisted symbols into bars + regime, and (default path)
        // run the native strategy entry/exit on a closed bar. The legacy generic
        // factor loop below only runs in explicit bootstrap-sim mode.
        update_bars(ms, now_epoch);
        if (!opts_.bootstrap_sim) continue;

        const auto* venue_cfg = cfg_.find_venue(ms.venue);
        if (!venue_cfg) continue;
        // Alpaca is the only paper trading venue in the loop.
        if (ms.venue != "alpaca") continue;
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
        // Alpaca is the only paper venue. IBKR is the live-only venue and stays
        // disabled behind the approval gate. live_enabled is false on this path.
        execution::AlpacaPaperAdapter alp(venue_cfg->paper_execution,
                                          opts_.bridge_host, opts_.bridge_port);
        execution::IbkrLiveAdapter ibkr_live(opts_.bridge_host, opts_.bridge_port);
        execution::DisabledLiveAdapter disabled_live(o.venue);
        execution::VenueAdapter& live =
            (o.venue == "ibkr")
                ? static_cast<execution::VenueAdapter&>(ibkr_live)
                : static_cast<execution::VenueAdapter&>(disabled_live);
        auto fill = router_.route(venue_cfg->mode, alp, live, o,
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
    // Adaptive layer toggle (controls.json): skip the weight nudge this
    // iteration when the operator has toggled the adaptive layer off. Advisory
    // only, it never affects the RiskGate or any Level-1 limit.
    if (!layer_toggles_.adaptive) return;
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

void Engine::verify_real_layers_reachable() {
    // Only the real paper path is strict. Offline feed modes keep their mock
    // behavior for tests, so they are a no-op here.
    if (feed_mode_ != "alpaca_paper") return;

    // A layer is checked only when it is BOTH enabled AND set on-real. on-mock is
    // an explicit operator choice and starts silently. Adaptive has no source.
    const bool need_council =
        layer_toggles_.council && layer_toggles_.council_real;
    const bool need_dnn =
        layer_toggles_.dnn_advisory && layer_toggles_.dnn_advisory_real;
    const bool need_whale = layer_toggles_.whale && layer_toggles_.whale_real;
    if (!(need_council || need_dnn || need_whale)) return;

    std::vector<std::string> missing;
    if (!opts_.use_bridge) {
        // The real advisory services run only via the Python bridge.
        if (need_council)
            missing.push_back("LLM council is on-real but the engine has no "
                              "--bridge (the real council runs only via the "
                              "Python bridge)");
        if (need_dnn)
            missing.push_back("dnn_advisory is on-real but the engine has no "
                              "--bridge");
        if (need_whale)
            missing.push_back("whale is on-real but the engine has no --bridge");
    } else {
        const std::string addr =
            opts_.bridge_host + ":" + std::to_string(opts_.bridge_port);
        auto resp = bridge::http_post_json(opts_.bridge_host, opts_.bridge_port,
                                           "/status", "{}",
                                           cfg_.council.engine_bridge_call_timeout_ms);
        if (!resp) {
            if (need_council)
                missing.push_back("LLM council on-real but the Python bridge is "
                                  "unreachable at " + addr);
            if (need_dnn)
                missing.push_back("dnn_advisory on-real but the Python bridge is "
                                  "unreachable at " + addr);
            if (need_whale)
                missing.push_back("whale on-real but the Python bridge is "
                                  "unreachable at " + addr);
        } else {
            if (need_council && !bridge::json_get_bool(*resp, "council_real", false))
                missing.push_back("LLM council on-real but not available: " +
                    bridge::json_get_string(*resp, "council_detail",
                                            "real council unavailable"));
            if (need_dnn && !bridge::json_get_bool(*resp, "dnn_real", false))
                missing.push_back("dnn_advisory on-real but not available: " +
                    bridge::json_get_string(*resp, "dnn_detail",
                                            "real dnn unavailable"));
            if (need_whale && !bridge::json_get_bool(*resp, "whale_real", false))
                missing.push_back("whale on-real but not available: " +
                    bridge::json_get_string(*resp, "whale_detail",
                                            "real whale feed unavailable"));
        }
    }
    if (missing.empty()) return;

    std::string msg =
        "STRICT MODE (feed_mode=alpaca_paper): refusing to start. A layer set "
        "on-real has no reachable real service. Fix the service, or set that "
        "layer to on-mock in controls.json to run it as a deliberate mock:\n";
    for (const auto& m : missing) msg += "  - " + m + "\n";
    // Refuse to start on the real path rather than silently substituting a mock.
    throw std::runtime_error(msg);
}

void Engine::run(int iterations) {
    verify_real_layers_reachable();  // strict mode: no silent mock on real path
    if (feed_mode_ == "replay") {
        // Replay every stored bar in the window, in order, then stop cleanly.
        int i = 0;
        while (step_bar_mode() > 0) maybe_adapt(i++);
    } else if (feed_mode_ == "synthetic_regimes") {
        // `iterations` = number of bar steps (each closes one bar per symbol).
        for (int i = 0; i < iterations; ++i) {
            step_bar_mode();
            maybe_adapt(i);
        }
    } else {
        for (int i = 0; i < iterations; ++i) {
            run_iteration();
            maybe_adapt(i);
        }
    }
    const std::string ts = util::now_iso8601();
    storage_->append_event(
        {ts, "summary", "", "", "info",
         "Paper loop complete: " + std::to_string(trade_count_) + " trades",
         util::to_json({}, {{"final_equity", equity_}})});
}

void Engine::run_forever(const volatile std::sig_atomic_t* stop_flag) {
    verify_real_layers_reachable();  // strict mode: no silent mock on real path
    int interval = opts_.interval_seconds > 0 ? opts_.interval_seconds
                                              : cfg_.engine.loop_interval_seconds;
    if (interval < 1) interval = 1;

    {
        const std::string ts = util::now_iso8601();
        std::string src = alpaca_feed_ ? "alpaca" : "mock";
        storage_->append_event(
            {ts, "continuous_start", "", "", "info",
             "Continuous paper loop started (source=" + src + ", feed=" +
                 feed_mode_ + ", interval=" + std::to_string(interval) + "s)",
             "{}"});
    }

    // The feed and clock are runtime-switchable (Task 3): consume the toggle at
    // the top of every iteration and DISPATCH on the resulting feed_mode_, so a
    // switch takes effect on the next iteration. Bar-driven modes (synthetic /
    // replay) step one bar per iteration; the tick modes (alpaca_paper, the
    // primary online loop, and flat_random_walk) poll the feed and aggregate
    // ticks into closed bars. A switch never orphans an open position (enforced
    // in consume_feed_clock). Sleeping in 1s slices lets a signal interrupt
    // promptly and paces every mode uniformly at the loop interval.
    int iteration = 0;
    bool replay_idle_logged = false;
    while (!(stop_flag && *stop_flag)) {
        consume_feed_clock();
        const bool bar_mode =
            feed_mode_ == "synthetic_regimes" || feed_mode_ == "replay";
        if (bar_mode) {
            const int n = step_bar_mode();
            if (n == 0) {
                // Replay exhausted: idle (do NOT break) so the operator can still
                // switch feeds via controls.json. Log the exhaustion once.
                if (!replay_idle_logged) {
                    replay_idle_logged = true;
                    storage_->append_event(
                        {util::now_iso8601(), "replay_exhausted", "", "", "info",
                         "Replay reached the end of its bars; idling. Switch the "
                         "feed from the GUI to resume another mode.", "{}"});
                }
            } else {
                replay_idle_logged = false;
                maybe_adapt(iteration++);
            }
        } else {
            run_iteration();
            maybe_adapt(iteration++);
        }
        for (int s = 0; s < interval && !(stop_flag && *stop_flag); ++s)
            std::this_thread::sleep_for(std::chrono::seconds(1));
    }

    const std::string ts = util::now_iso8601();
    storage_->append_event(
        {ts, "continuous_stop", "", "", "info",
         "Continuous paper loop stopped after " + std::to_string(iteration) +
             " iterations, " + std::to_string(trade_count_) + " trades",
         util::to_json({}, {{"final_equity", equity_}})});
    // SQLite writes autocommit per statement, so state is already durable.
}

}  // namespace mal::core

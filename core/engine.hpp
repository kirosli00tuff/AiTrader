// Market AI Lab — core engine loop / orchestration.
//
// Wires the four-layer decision architecture together for the continuous paper
// loop: gather advisory factors (LLM consensus, rule-based, DNN/RL, whale) →
// combine (signal_engine) → propose order → Layer-1 RiskGate (final authority)
// → mode router (paper) → record outcome → persist to SQLite. Advisory factors
// come from the Python bridge when available, otherwise deterministic mocks so
// the engine always runs offline.
#pragma once

#include <csignal>
#include <memory>
#include <string>
#include <vector>

#include "account_manager/account_manager.hpp"
#include "config/config.hpp"
#include "execution/execution.hpp"
#include "learning/adaptive.hpp"
#include "market_data/market_data.hpp"
#include "market_data/synthetic_feed.hpp"
#include "news_ingestion/news_ingestion.hpp"
#include "risk/risk_gate.hpp"
#include "signal_engine/council_gate.hpp"
#include "signal_engine/factor_engine.hpp"
#include "signal_engine/strategy.hpp"
#include "storage/storage.hpp"

namespace mal::core {

struct EngineOptions {
    std::string db_path;
    std::string schema_path;
    std::string bridge_host = "127.0.0.1";
    int bridge_port = 8765;
    bool use_bridge = false;  // try the Python bridge for advisory factors
    uint64_t seed = 42;
    // Continuous (run-forever) mode. Empty data_source means "use config".
    bool continuous = false;
    int interval_seconds = 0;        // 0 -> use cfg.engine.loop_interval_seconds
    std::string data_source;          // "mock" | "alpaca"; empty -> use config
    // Bootstrap-only: run the legacy generic factor loop with simulated PnL
    // (simulate_outcome). OFF by default — the native strategy layer is the
    // default trading path and learns from REAL closed-trade fills (Task 3).
    bool bootstrap_sim = false;
    // Seconds per native bar bucket (default 5 min). <= 0 means one bar per tick
    // (testability lever so the native entry/exit path can be exercised quickly).
    long native_bar_seconds = 300;
    // Offline feed/clock overrides (empty => use cfg.simulation.*):
    //   feed_mode  : flat_random_walk | synthetic_regimes | replay
    //   clock_mode : real | simulated
    // These make the offline loop a real training environment; they NEVER touch
    // live behavior (Alpaca stays paper + market-data only, no live path).
    std::string feed_mode;
    std::string clock_mode;
};

class Engine {
public:
    Engine(config::Config cfg, EngineOptions opts);

    // Run one decision iteration across all instruments. Returns number of
    // executed paper trades this iteration.
    int run_iteration();

    // Run N iterations (the demo paper loop).
    void run(int iterations);

    // Run forever (continuous 24/7 paper loop), sleeping interval seconds
    // between ticks. Returns when *stop_flag becomes non-zero (set by a signal
    // handler) — the current tick completes, state is flushed, then it exits.
    void run_forever(const volatile std::sig_atomic_t* stop_flag);

    storage::Storage& storage() { return *storage_; }

    bool last_poll_was_live() const { return last_poll_live_; }

private:
    std::vector<signal_engine::FactorSignal> gather_factors(
        const market_data::MarketState& ms, const news::CatalystScore& cat,
        bool council_allowed = true,
        const strategy::StrategySignal* native = nullptr);
    signal_engine::FactorSignal mock_factor(const std::string& name,
                                            const market_data::MarketState& ms,
                                            const news::CatalystScore& cat);
    void maybe_adapt(int iteration);
    void snapshot_balances();
    double simulate_outcome(const signal_engine::CombinedVerdict& v,
                            double notional);
    // Feed one market-data tick into the 5-min bar aggregator. On a bar close
    // for a whitelisted symbol: persist the bar, update in-memory history, and
    // recompute + persist the symbol's regime. Advisory only — never trades.
    void update_bars(const market_data::MarketState& ms, long epoch_seconds);
    // Shared closed-bar path: persist the bar, update in-memory history + regime,
    // and (unless bootstrap-sim) run the native strategy on it. Reached from the
    // tick aggregator (flat_random_walk) AND directly from the bar-driven feed
    // modes (synthetic_regimes / replay), so all three exercise the same logic.
    void on_closed_bar(const market_data::MarketState& ms,
                       const strategy::Bar& closed, long epoch);
    // Set up the bar-driven feed modes (synthetic_regimes / replay). Builds the
    // per-symbol synthetic generators or loads the replay queue from the bars
    // table; throws with a clear message if replay has no bars for the range.
    void init_bar_mode(const std::vector<market_data::Instrument>& instruments);
    // Advance one step of the bar-driven feed. Returns the number of bars
    // ingested this step (0 => replay exhausted; synthetic never returns 0).
    int step_bar_mode();
    bool is_whitelisted(const std::string& symbol) const;
    // Native trading on a CLOSED bar for a whitelisted symbol: manage the open
    // position's native exit first, else consider a new strategy entry (council
    // gate -> factors/verdict -> RiskGate -> open). Never runs on ticks.
    void handle_bar_close(const market_data::MarketState& ms,
                          const strategy::Bar& bar, long now_epoch);
    // Rebuild aggregate portfolio/exposure state from currently open native
    // positions so the RiskGate sees true open risk when judging a new entry.
    void sync_portfolio_state();

    config::Config cfg_;
    EngineOptions opts_;
    std::unique_ptr<storage::Storage> storage_;
    std::unique_ptr<market_data::Feed> feed_;
    std::unique_ptr<news::MockCatalystProvider> news_;
    std::unique_ptr<risk::RiskGate> gate_;
    std::unique_ptr<account::AccountManager> accounts_;
    signal_engine::WeightState weights_;
    learning::AdaptiveTuner tuner_;
    execution::ModeRouter router_;
    risk::KillSwitch kill_switch_;

    // Aggregate portfolio/risk state, updated as trades happen.
    risk::PortfolioState pstate_;
    double equity_;
    double peak_equity_;
    uint64_t rng_;
    int trade_count_ = 0;
    std::map<std::string, double> factor_perf_;  // running perf per factor

    // Native strategy inputs: 5-min bar aggregation + bounded per-symbol history
    // ("venue|symbol" -> bars, oldest-first) seeded from storage on startup.
    strategy::BarAggregator bar_agg_;
    std::map<std::string, std::vector<strategy::Bar>> bar_history_;

    // An open native position plus the advisory context captured at ENTRY, so
    // realized PnL can be attributed back to the factors when it closes.
    struct ActivePosition {
        strategy::OpenPosition pos;
        std::vector<signal_engine::FactorSignal> entry_signals;
        double entry_bias = 0.0;
    };
    std::map<std::string, ActivePosition> open_positions_;  // key "venue|symbol"
    signal_engine::CouncilGateState council_state_;
    int trades_today_ = 0;              // native entries today (max_trades_per_day)
    std::string trades_today_day_;      // UTC day bucket for the counter above
    long closed_trade_count_ = 0;       // closed native trades (min-sample gate)

    // Continuous-mode state.
    bool continuous_ = false;          // gate equity by market hours when true
    bool alpaca_feed_ = false;         // feed is AlpacaFeed (tracks live status)
    bool last_poll_live_ = false;      // last poll contained real Alpaca data

    // --- Offline feed / clock state (Tasks 2-4) ---------------------------
    // feed_mode_: flat_random_walk (tick path) | synthetic_regimes | replay.
    // simulated_clock_: bar time advances internally (sim_epoch_) instead of
    // against wall-clock, so finite/synthetic runs actually close bars.
    std::string feed_mode_ = "flat_random_walk";
    bool simulated_clock_ = false;
    long sim_epoch_ = 0;               // advancing simulated UTC epoch (seconds)
    long bar_step_seconds_ = 300;      // sim-clock advance per bar step
    // synthetic_regimes: one deterministic generator per whitelisted instrument.
    std::vector<market_data::Instrument> bar_instruments_;
    std::vector<market_data::SyntheticRegimeGenerator> synth_gens_;
    // replay: chronologically-ordered stored bars replayed through on_closed_bar.
    struct BarTick {
        market_data::MarketState ms;
        strategy::Bar bar;
        long epoch = 0;
    };
    std::vector<BarTick> replay_queue_;
    size_t replay_pos_ = 0;
};

}  // namespace mal::core

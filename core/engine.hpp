// Market AI Lab — core engine loop / orchestration.
//
// Wires the four-layer decision architecture together for the continuous paper
// loop: gather advisory factors (LLM consensus, rule-based, DNN/RL, whale) →
// combine (signal_engine) → propose order → Layer-1 RiskGate (final authority)
// → mode router (paper) → record outcome → persist to SQLite. Advisory factors
// come from the Python bridge when available, otherwise deterministic mocks so
// the engine always runs offline.
#pragma once

#include <memory>
#include <string>
#include <vector>

#include "account_manager/account_manager.hpp"
#include "config/config.hpp"
#include "execution/execution.hpp"
#include "learning/adaptive.hpp"
#include "market_data/market_data.hpp"
#include "news_ingestion/news_ingestion.hpp"
#include "risk/risk_gate.hpp"
#include "signal_engine/factor_engine.hpp"
#include "storage/storage.hpp"

namespace mal::core {

struct EngineOptions {
    std::string db_path;
    std::string schema_path;
    std::string bridge_host = "127.0.0.1";
    int bridge_port = 8765;
    bool use_bridge = false;  // try the Python bridge for advisory factors
    uint64_t seed = 42;
};

class Engine {
public:
    Engine(config::Config cfg, EngineOptions opts);

    // Run one decision iteration across all instruments. Returns number of
    // executed paper trades this iteration.
    int run_iteration();

    // Run N iterations (the demo paper loop).
    void run(int iterations);

    storage::Storage& storage() { return *storage_; }

private:
    std::vector<signal_engine::FactorSignal> gather_factors(
        const market_data::MarketState& ms, const news::CatalystScore& cat);
    signal_engine::FactorSignal mock_factor(const std::string& name,
                                            const market_data::MarketState& ms,
                                            const news::CatalystScore& cat);
    void maybe_adapt(int iteration);
    void snapshot_balances();
    double simulate_outcome(const signal_engine::CombinedVerdict& v,
                            double notional);

    config::Config cfg_;
    EngineOptions opts_;
    std::unique_ptr<storage::Storage> storage_;
    std::unique_ptr<market_data::MockFeed> feed_;
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
};

}  // namespace mal::core

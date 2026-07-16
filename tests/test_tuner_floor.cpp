// Tuner floor tests (Task 1). The adaptive tuner never drives the rule_based raw
// weight below the configured floor, and compose_gate_verdict guarantees
// rule_based at least that normalized share so a saturated advisory set cannot
// dilute the native conviction below the RiskGate minimum. A long synthetic run
// keeps generating native entries well past 100 closed trades (the old ~30
// plateau, where the tuner de-weighted rule_based to near zero, is gone).
#include <cstdio>
#include <map>
#include <string>
#include <vector>

#include "config/config.hpp"
#include "core/engine.hpp"
#include "learning/adaptive.hpp"
#include "signal_engine/factor_engine.hpp"
#include "storage/storage.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {
void rm_db(const std::string& p) {
    std::remove(p.c_str());
    std::remove((p + "-wal").c_str());
    std::remove((p + "-shm").c_str());
}
}  // namespace

int main() {
    // 1. Tuner raw-weight floor: a strongly negative rule_based performance
    //    cannot push the proposed weight below the floor.
    {
        config::RiskConfig risk;  // defaults (immutable hard limits)
        config::AdaptiveConfig acfg;
        acfg.rule_based_weight_floor = 0.35;
        learning::AdaptiveTuner tuner(risk, acfg);
        signal_engine::WeightState ws;
        ws.set_from_map({{"rule_based", 0.36}, {"dnn_advisory", 0.30}});
        std::map<std::string, double> perf{{"rule_based", -1.0},
                                           {"dnn_advisory", 0.0}};
        auto prop = tuner.propose_weight_update(ws, perf);
        maltest::check(prop["rule_based"] >= 0.35 - 1e-9,
                       "tuner never drives rule_based below the floor");
    }

    // 2. compose_gate_verdict share floor: with rule_based at a tiny raw weight
    //    and every advisory factor saturated at the cap, the native (high)
    //    confidence still dominates the gate verdict because its share is floored.
    {
        signal_engine::WeightState ws;
        ws.set_from_map({{"rule_based", 0.02}, {"llm_primary", 0.6},
                         {"dnn_advisory", 0.6}, {"whale_signal", 0.6}});
        std::vector<signal_engine::FactorSignal> sigs = {
            {"rule_based", 0.9, 0.95, 0.12},
            {"llm_primary", 0.9, 0.50, 0.02},
            {"dnn_advisory", 0.9, 0.50, 0.02},
            {"whale_signal", 0.9, 0.50, 0.02}};
        auto no_floor =
            signal_engine::compose_gate_verdict(sigs, ws, true, 0.05, 0.0);
        auto with_floor =
            signal_engine::compose_gate_verdict(sigs, ws, true, 0.05, 0.35);
        maltest::check(with_floor.confidence > no_floor.confidence + 0.05,
                       "share floor lifts the gate confidence toward the native "
                       "conviction");
        maltest::check(with_floor.confidence >= 0.65,
                       "share floor keeps the gate confidence at/above the "
                       "RiskGate minimum (0.65)");
    }

    // 3. Long synthetic run: native entries continue well past 100 closed trades.
    //    Without the floor the tuner starved rule_based and entries plateaued near
    //    30 as the gate confidence collapsed; with the floor they keep flowing.
    //    Equities now only enter during US regular hours (crypto stays 24/7), so
    //    the run spans more simulated days to accumulate the same evidence.
    {
        const std::string db = "/tmp/mal_test_floor_run.db";
        rm_db(db);
        config::Config cfg = config::load_config("config/default_config.yaml");
        core::EngineOptions opts;
        opts.db_path = db;
        opts.schema_path = "storage/schema.sql";
        opts.feed_mode = "synthetic_regimes";
        opts.clock_mode = "simulated";
        core::Engine e(cfg, opts);
        e.run(12000);  // ~40 simulated days
        long long closed = e.storage().count_closed_trades();
        maltest::check(closed > 100,
                       "synthetic run keeps generating native entries past 100 "
                       "closed trades (no plateau)");
        rm_db(db);
    }

    return maltest::report("tuner_floor");
}

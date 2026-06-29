// Unit tests for weight normalization, locking, and factor combination.
#include "signal_engine/factor_engine.hpp"

#include "learning/adaptive.hpp"
#include "config/config.hpp"
#include "tests/test_util.hpp"

using namespace mal;
using namespace maltest;

int main() {
    using signal_engine::WeightState;

    // 1. Normalized weights sum to 1.
    {
        WeightState w;
        w.set_from_map({{"a", 2.0}, {"b", 2.0}, {"c", 4.0}});
        auto n = w.normalized();
        double sum = 0;
        for (auto& [k, v] : n) sum += v;
        check_near(sum, 1.0, 1e-9, "normalized weights sum to 1");
        check_near(n["c"], 0.5, 1e-9, "largest weight normalized correctly");
    }

    // 2. Disabled factors are excluded from normalization.
    {
        WeightState w;
        w.set_from_map({{"a", 1.0}, {"b", 1.0}});
        w.set_enabled("b", false);
        auto n = w.normalized();
        check_near(n["a"], 1.0, 1e-9, "disabled factor excluded");
        check_near(n["b"], 0.0, 1e-9, "disabled factor weight zero");
    }

    // 3. Locked factors are immune to adaptive updates.
    {
        WeightState w;
        w.set_from_map({{"a", 0.5}, {"b", 0.5}});
        w.set_locked("a", true);
        auto changed = w.apply_adaptive({{"a", 0.9}, {"b", 0.1}});
        check(w.get("a")->weight == 0.5, "locked weight unchanged");
        check(w.get("b")->weight == 0.1, "unlocked weight changed");
        bool a_changed = false;
        for (auto& c : changed) if (c == "a") a_changed = true;
        check(!a_changed, "locked factor not reported as changed");
    }

    // 4. Combination produces a weighted verdict + agreement count.
    {
        WeightState w;
        w.set_from_map({{"x", 1.0}, {"y", 1.0}});
        std::vector<signal_engine::FactorSignal> sigs = {
            {"x", 0.8, 0.9, 0.05},
            {"y", 0.4, 0.7, 0.03},
        };
        auto v = signal_engine::combine(sigs, w);
        check(v.bias > 0, "combined bias positive");
        check_near(v.bias, 0.6, 1e-9, "combined bias is weighted mean");
        check(v.agreement_count == 2, "both factors agree (count=2)");
        check(v.verdict == "strong_buy" || v.verdict == "buy",
              "verdict is bullish");
    }

    // 5. Opposing factors reduce agreement count.
    {
        WeightState w;
        w.set_from_map({{"x", 1.0}, {"y", 1.0}});
        std::vector<signal_engine::FactorSignal> sigs = {
            {"x", 0.8, 0.9, 0.05},
            {"y", -0.8, 0.9, 0.05},
        };
        auto v = signal_engine::combine(sigs, w);
        check(v.agreement_count <= 1, "opposing factors reduce agreement");
    }

    // 6. Adaptive layer cannot weaken Layer-1 hard limits.
    {
        config::RiskConfig hard;          // defaults
        config::RiskConfig weaker = hard;
        weaker.max_daily_loss_total_pct = 0.10;  // larger => weaker
        auto bad = learning::validate_not_weakening_limits(hard, weaker);
        check(!bad.empty(), "weakening loss limit rejected");

        config::RiskConfig tighter = hard;
        tighter.max_daily_loss_total_pct = 0.01;  // smaller => stronger (ok)
        tighter.min_confidence_default = 0.80;    // higher => stronger (ok)
        auto ok = learning::validate_not_weakening_limits(hard, tighter);
        check(ok.empty(), "tightening limits accepted");
    }

    return report("weights");
}

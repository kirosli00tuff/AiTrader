// Operator controls reader tests (Task 2). read_operator_controls parses the
// flat controls.json keys for the council model toggles, the runtime budget
// (clamped to the server-side bounds), and the per-symbol regime pins;
// any_council_provider enforces the at-least-one-provider council rule. Pure,
// header-only. No network.
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

#include "core/operator_controls.hpp"
#include "test_util.hpp"

using namespace mal::core;

int main() {
    const std::vector<std::string> wl = {"BTC/USD", "ETH/USD", "SPY", "QQQ"};

    // Missing file => safe defaults (all providers on, no budget override, no pins).
    OperatorControls miss = read_operator_controls("/tmp/mal_no_such_oc.json", wl);
    maltest::check(miss.llm_primary && miss.llm_secondary && miss.llm_tertiary,
                   "missing file keeps all council providers on");
    maltest::check(miss.council_daily_budget == -1 &&
                       miss.per_symbol_cooldown_minutes == -1,
                   "missing file keeps the config budget (sentinel -1)");
    maltest::check(miss.regime_pins.empty(), "missing file has no regime pins");
    maltest::check(any_council_provider(miss), "default has council providers");

    // Explicit flat keys: a disabled provider, a runtime budget, valid + invalid
    // regime pins.
    const std::string p = "/tmp/mal_oc_good.json";
    { std::ofstream o(p);
      o << R"({"llm_primary_enabled": false, "llm_secondary_enabled": true, )"
           R"("llm_tertiary_enabled": true, "rt_council_daily_budget": 12, )"
           R"("rt_per_symbol_cooldown_minutes": 45, )"
           R"("regime_pin:BTC/USD": "trending", "regime_pin:SPY": "bogus"})"; }
    OperatorControls oc = read_operator_controls(p, wl);
    maltest::check(!oc.llm_primary && oc.llm_secondary && oc.llm_tertiary,
                   "a disabled provider slot is parsed off");
    maltest::check(oc.council_daily_budget == 12 &&
                       oc.per_symbol_cooldown_minutes == 45,
                   "runtime budget is parsed");
    maltest::check(oc.regime_pins.count("BTC/USD") &&
                       oc.regime_pins["BTC/USD"] == "trending",
                   "a valid regime pin is parsed");
    maltest::check(oc.regime_pins.count("SPY") == 0,
                   "an invalid regime label is ignored");
    std::remove(p.c_str());

    // Budget clamped to the server-side bounds defensively.
    const std::string p2 = "/tmp/mal_oc_clamp.json";
    { std::ofstream o(p2);
      o << R"({"rt_council_daily_budget": 9000, )"
           R"("rt_per_symbol_cooldown_minutes": 99999})"; }
    OperatorControls oc2 = read_operator_controls(p2, wl);
    maltest::check(oc2.council_daily_budget == 500,
                   "budget over the max clamps to 500");
    maltest::check(oc2.per_symbol_cooldown_minutes == 1440,
                   "cooldown over the max clamps to 1440");
    std::remove(p2.c_str());

    // At-least-one-provider rule + regime-label validation.
    OperatorControls none;
    none.llm_primary = none.llm_secondary = none.llm_tertiary = false;
    maltest::check(!any_council_provider(none),
                   "all providers off => council cannot run");
    maltest::check(is_valid_regime_label("range_bound") &&
                       !is_valid_regime_label("sideways"),
                   "regime labels are validated");

    return maltest::report("operator_controls");
}

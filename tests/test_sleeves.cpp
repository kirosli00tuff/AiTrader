// Core-satellite sleeve tests: the HARD CAP holds against an over-conviction
// attempt, drift-band rebalancing triggers and trims the overweight sleeve, and
// the sleeve config validates. Pure math (core/sleeves.hpp) + config; no I/O.
#include "core/sleeves.hpp"

#include "config/config.hpp"
#include "tests/test_util.hpp"

using namespace mal;
using namespace maltest;

int main() {
    // A sleeve config with the satellite ENABLED for the cap/rebalance math
    // (production ships it OFF; the pure functions take the config explicitly).
    auto cfg = []() {
        config::SleeveConfig c;
        c.research_satellite_enabled = true;
        c.quant_core_target_pct = 0.80;
        c.research_satellite_target_pct = 0.20;
        c.drift_band_pct = 0.05;
        return c;
    }();
    const double equity = 100000.0;

    // --- Hard cap ------------------------------------------------------------
    {
        // Cap value = (0.20 + 0.05) * 100000 = 25000.
        check_near(sleeve::satellite_cap_value(cfg, equity), 25000.0, 1e-6,
                   "satellite cap is (target + band) * equity");
        sleeve::Allocations a;
        a.quant_core = 80000.0;
        a.research_satellite = 20000.0;
        // Room for 5000 more (up to the 25000 cap), not for 6000.
        check(sleeve::satellite_has_room(cfg, a, 5000.0, equity),
              "satellite has room up to the cap");
        check(!sleeve::satellite_has_room(cfg, a, 6000.0, equity),
              "satellite has NO room past the cap, even 1 dollar over");
        // An over-conviction research idea asking for a huge position is refused.
        check(!sleeve::satellite_has_room(cfg, a, 100000.0, equity),
              "an over-conviction research position cannot balloon past the cap");
        // A DISABLED satellite never has room.
        auto off = cfg;
        off.research_satellite_enabled = false;
        sleeve::Allocations empty;
        check(!sleeve::satellite_has_room(off, empty, 1000.0, equity),
              "a disabled satellite never opens a position");
    }

    // --- Drift-band rebalancing ---------------------------------------------
    {
        // Satellite overweight (30% vs 20% + 5% band): trim back to 20% target.
        sleeve::Allocations over;
        over.quant_core = 70000.0;
        over.research_satellite = 30000.0;
        auto d = sleeve::decide_rebalance(cfg, over, equity);
        check(d.action == sleeve::RebalanceAction::TrimSatellite,
              "satellite past the band triggers a satellite trim");
        check_near(d.trim_amount, 10000.0, 1e-6,
                   "trim brings the satellite back to its 20% target (30000 -> 20000)");

        // Within the band (23%): no rebalance.
        sleeve::Allocations ok;
        ok.quant_core = 77000.0;
        ok.research_satellite = 23000.0;
        check(sleeve::decide_rebalance(cfg, ok, equity).action ==
                  sleeve::RebalanceAction::None,
              "within the drift band, no rebalance");

        // Satellite underweight (10%): the core is overweight, trim the core.
        sleeve::Allocations under;
        under.quant_core = 90000.0;
        under.research_satellite = 10000.0;
        auto d2 = sleeve::decide_rebalance(cfg, under, equity);
        check(d2.action == sleeve::RebalanceAction::TrimCore,
              "satellite under the band means the core is overweight -> trim core");
        check_near(d2.trim_amount, 10000.0, 1e-6,
                   "trim brings the core back to its 80% target (90000 -> 80000)");
    }

    // --- The 70/30 split -----------------------------------------------------
    {
        config::Config c;  // shipped defaults
        check_near(c.sleeves.quant_core_target_pct, 0.70, 1e-9,
                   "quant_core targets 70 percent by default");
        check_near(c.sleeves.research_satellite_target_pct, 0.30, 1e-9,
                   "research_satellite targets 30 percent by default");
        check_near(c.sleeves.quant_core_target_pct +
                       c.sleeves.research_satellite_target_pct,
                   1.0, 1e-9, "the split sums to 1.0");

        // 30 percent is a CEILING, not a floor. The mechanism is unchanged: the
        // hard cap is still (target + band), just computed off 0.30 now.
        auto s70 = c.sleeves;
        s70.research_satellite_enabled = true;
        check_near(sleeve::satellite_cap_value(s70, equity), 35000.0, 1e-6,
                   "the 70/30 hard cap is (0.30 + 0.05) * equity = 35000");

        sleeve::Allocations at_cap;
        at_cap.quant_core = 65000.0;
        at_cap.research_satellite = 35000.0;
        check(!sleeve::satellite_has_room(s70, at_cap, 1.0, equity),
              "at the 70/30 cap the satellite cannot add even 1 dollar");

        // The satellite is never ENTITLED to its 30 percent: sitting under the
        // target is fine, only exceeding the cap is a problem.
        sleeve::Allocations under;
        under.quant_core = 90000.0;
        under.research_satellite = 5000.0;
        check(sleeve::satellite_has_room(s70, under, 1000.0, equity),
              "a satellite under its target may still add");

        // A satellite past target + band is trimmed back: the same mechanism as
        // at 80/20, just around the new target.
        sleeve::Allocations ballooned;
        ballooned.quant_core = 60000.0;
        ballooned.research_satellite = 40000.0;  // 40% > 30% + 5%
        auto dec = sleeve::decide_rebalance(s70, ballooned, equity);
        check(dec.action == sleeve::RebalanceAction::TrimSatellite,
              "a satellite past the 70/30 band is trimmed");
        check_near(dec.trim_amount, 10000.0, 1e-6,
                   "the trim brings the satellite back to its 30 percent target");
    }

    // --- Config validation ---------------------------------------------------
    {
        config::Config c;  // defaults: 0.70/0.30, band 0.05, research off
        check(config::validate_config(c).empty(),
              "default sleeve config validates clean");

        config::Config bad;
        bad.sleeves.quant_core_target_pct = 0.7;
        bad.sleeves.research_satellite_target_pct = 0.2;  // sums to 0.9, not 1.0
        bool found = false;
        for (const auto& p : config::validate_config(bad))
            if (p.find("sum to 1.0") != std::string::npos) found = true;
        check(found, "sleeve targets that do not sum to 1.0 are rejected");

        config::Config bad2;
        bad2.sleeves.research_satellite_target_pct = 0.2;
        bad2.sleeves.quant_core_target_pct = 0.8;
        bad2.sleeves.drift_band_pct = 0.3;  // band > satellite target
        bool found2 = false;
        for (const auto& p : config::validate_config(bad2))
            if (p.find("drift_band_pct") != std::string::npos) found2 = true;
        check(found2, "a drift band wider than the satellite target is rejected");
    }

    // Default config ships the satellite OFF (nothing changes silently).
    {
        config::SleeveConfig def;
        check(!def.research_satellite_enabled,
              "research_satellite ships OFF by default (operator opt-in)");
        check(def.quant_core_enabled, "quant_core is on by default");
    }

    // --- Discovery ships DISABLED -------------------------------------------
    // With both flags off the engine is the fixed-whitelist two-sleeve system.
    {
        config::DiscoveryConfig def;
        check(!def.discovery_enabled,
              "discovery ships OFF by default (operator opt-in)");
        check(!def.long_term_sleeve_enabled,
              "the long-term sleeve ships OFF by default (operator opt-in)");

        config::Config c;
        check(config::validate_config(c).empty(),
              "default discovery config validates clean");
    }

    // --- Discovery validation: the funnel narrows, it never widens -----------
    {
        auto problems_contain = [](const config::Config& c, const char* needle) {
            for (const auto& p : config::validate_config(c))
                if (p.find(needle) != std::string::npos) return true;
            return false;
        };

        config::Config wide;
        wide.discovery.max_survivors = 20;   // > max_finalists (12)
        check(problems_contain(wide, "max_survivors"),
              "more survivors than finalists is rejected (the funnel narrows)");

        config::Config spendy;
        spendy.discovery.max_council_calls_per_pass = 9;  // > max_survivors (5)
        check(problems_contain(spendy, "max_council_calls_per_pass"),
              "more council calls than survivors is rejected (only survivors "
              "reach the council)");

        // Enabling discovery with no universe fails loudly at load rather than
        // silently doing nothing at 03:00.
        config::Config empty_universe;
        empty_universe.discovery.discovery_enabled = true;
        check(problems_contain(empty_universe, "crypto_universe"),
              "discovery enabled with an empty universe is rejected");

        // The long-term strategy has no sleeve to trade in without the sleeve.
        config::Config orphan;
        orphan.discovery.long_term_sleeve_enabled = true;
        orphan.sleeves.research_satellite_enabled = false;
        check(problems_contain(orphan, "long_term_sleeve_enabled"),
              "the long-term sleeve without research_satellite_enabled is "
              "rejected");

        // A correctly configured opt-in validates.
        config::Config ok;
        ok.discovery.discovery_enabled = true;
        ok.discovery.crypto_universe = {"BTC/USD"};
        ok.discovery.equity_universe = {"SPY"};
        ok.discovery.long_term_sleeve_enabled = true;
        ok.sleeves.research_satellite_enabled = true;
        check(config::validate_config(ok).empty(),
              "a fully configured discovery opt-in validates clean");
    }

    return report("sleeves");
}

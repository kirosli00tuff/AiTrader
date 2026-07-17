// Discovery flag consumption, engine side.
//
// The defect this file exists to catch: the engine read discovery_enabled from
// CONFIG while the GUI toggle wrote it to controls.json, so an operator could
// turn discovery on and the engine would never know. The funnel is Python and
// has its own tests (tests/test_discovery_funnel.py). This is the C++ half: does
// the engine actually read what the operator actually wrote?
//
// A pure reader, so it needs no engine, no bridge, and no network.
#include <cstdio>
#include <fstream>
#include <string>

#include "config/config.hpp"
#include "core/discovery_controls.hpp"
#include "test_util.hpp"

using namespace mal::core;

namespace {

std::string write_tmp(const std::string& name, const std::string& body) {
    const std::string path = "/tmp/mal_test_" + name;
    std::ofstream out(path);
    out << body;
    out.close();
    return path;
}

// The shape the GUI actually writes: discovery_enabled nested inside a
// "discovery" object, alongside blocks carrying their own enable flags. The
// reader is flat, so this pins that it finds the right key in a realistic file
// rather than only in a one-key fixture.
const char* kRealisticControls = R"({
  "layers": {"adaptive": true, "council": true, "dnn_advisory": true, "whale": true},
  "feed_mode": "alpaca_paper",
  "clock_mode": "real",
  "discovery": {
    "discovery_enabled": true,
    "long_term_sleeve_enabled": false,
    "max_finalists": 12,
    "crypto_interval_minutes": 60
  },
  "adaptive_realtime": {
    "adaptive_news_feed_enabled": false,
    "adaptive_react_defensive_enabled": false
  },
  "ts": "2026-07-17T04:58:07Z"
})";

}  // namespace

int main() {
    mal::config::DiscoveryConfig cfg;  // ships disabled

    // --- The shipped default: OFF, and off from the struct itself ------------
    maltest::check(!cfg.discovery_enabled,
                   "discovery_enabled ships false in the config struct");

    // --- THE CENTRAL ASSERTION: the operator's file is what the engine reads --
    // This is the whole defect. controls.json says on, config says off, and the
    // engine must follow the operator. Before the fix it followed config and the
    // GUI toggle was cosmetic.
    {
        const std::string p = write_tmp("discovery_on.json", kRealisticControls);
        auto d = read_discovery_controls(p, cfg);
        maltest::check(d.enabled,
                       "controls.json discovery_enabled=true turns discovery ON "
                       "even though config ships it false (the GUI toggle is real)");
        std::remove(p.c_str());
    }

    // The operator can also turn it back OFF against a config that says on: the
    // control file wins in BOTH directions, or "disable" would not work either.
    {
        mal::config::DiscoveryConfig on;
        on.discovery_enabled = true;
        const std::string p = write_tmp(
            "discovery_off.json", R"({"discovery": {"discovery_enabled": false}})");
        auto d = read_discovery_controls(p, on);
        maltest::check(!d.enabled,
                       "controls.json discovery_enabled=false turns discovery OFF "
                       "even though config says true");
        std::remove(p.c_str());
    }

    // --- Fail-safe posture: unreadable means OFF, never on -------------------
    // Inverted from layer_toggles.hpp on purpose. A broken file must not blind
    // the ensemble there; here it must not START a spender.
    {
        auto d = read_discovery_controls("/tmp/mal_test_does_not_exist.json", cfg);
        maltest::check(!d.enabled, "a missing controls.json leaves discovery OFF");
    }
    {
        const std::string p = write_tmp("discovery_empty.json", "");
        auto d = read_discovery_controls(p, cfg);
        maltest::check(!d.enabled, "an empty controls.json leaves discovery OFF");
        std::remove(p.c_str());
    }
    {
        const std::string p = write_tmp("discovery_malformed.json",
                                        "{\"discovery\": {\"discovery_enabled\":");
        auto d = read_discovery_controls(p, cfg);
        maltest::check(!d.enabled,
                       "a truncated controls.json leaves discovery OFF (a broken "
                       "file must never start a spender)");
        std::remove(p.c_str());
    }
    {
        // No discovery key at all: fall back to config, not to a guess.
        const std::string p = write_tmp("discovery_absent.json",
                                        R"({"layers": {"council": true}})");
        auto d = read_discovery_controls(p, cfg);
        maltest::check(!d.enabled,
                       "controls.json without the key falls back to config (off)");
        mal::config::DiscoveryConfig on;
        on.discovery_enabled = true;
        maltest::check(read_discovery_controls(p, on).enabled,
                       "controls.json without the key falls back to config (on)");
        std::remove(p.c_str());
    }

    // --- No key collision with the neighbouring blocks -----------------------
    // The reader is flat, so a nearby false flag must not be mistaken for this
    // one. adaptive_realtime ships three false flags right beside discovery.
    {
        const std::string p = write_tmp("discovery_collide.json", kRealisticControls);
        maltest::check(read_discovery_controls(p, cfg).enabled,
                       "discovery_enabled is not confused with the adaptive_realtime "
                       "flags sitting false in the same file");
        std::remove(p.c_str());
    }

    // --- Change detection drives the toggle event ----------------------------
    {
        DiscoveryRuntime a, b;
        maltest::check(a == b, "two default DiscoveryRuntimes compare equal");
        b.enabled = true;
        maltest::check(!(a == b),
                       "an enable flip compares unequal, so the engine logs the "
                       "toggle instead of silently changing behavior");
    }

    // --- The trigger interval is a real interval, not a stub -----------------
    maltest::check(kDiscoveryTriggerIntervalSeconds > 0 &&
                       kDiscoveryTriggerIntervalSeconds <= 3600,
                   "the discovery trigger interval is sane (positive, at most "
                   "hourly, so an enabled layer is asked about promptly)");

    return maltest::report("discovery_engine");
}

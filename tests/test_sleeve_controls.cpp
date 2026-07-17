// research_satellite sleeve enable, engine side.
//
// The defect this catches: the engine read cfg_.sleeves.research_satellite_enabled
// while the GUI sleeve toggle wrote .control/controls.json, so the toggle was
// cosmetic. api_server/controls.py said so ("engine consumption is a documented
// follow-up") and the GUI panel told the operator the toggle "records intent".
// The backend half is asserted in tests/test_api_server.py. This is the C++ half:
// does the engine read what the operator actually wrote?
//
// A pure reader, so it needs no engine, no bridge, and no network.
#include <cstdio>
#include <fstream>
#include <string>

#include "config/config.hpp"
#include "core/sleeve_controls.hpp"
#include "core/sleeves.hpp"    // satellite_cap_value: the toggle must not move it
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

// The shape the GUI actually writes: research_satellite nested in a "sleeves"
// object, in a file whose other blocks carry their own enable flags.
const char* kRealisticControls = R"({
  "layers": {"adaptive": true, "council": true},
  "discovery": {"discovery_enabled": true, "long_term_sleeve_enabled": false},
  "sleeves": {"quant_core": true, "research_satellite": true},
  "rebalance_requested": false,
  "ts": "2026-07-17T04:58:07Z"
})";

}  // namespace

int main() {
    mal::config::SleeveConfig cfg;  // ships the satellite disabled

    maltest::check(!cfg.research_satellite_enabled,
                   "research_satellite ships false in the config struct");
    maltest::check(cfg.quant_core_enabled,
                   "quant_core ships true: the core sleeve is the default");

    // --- THE CENTRAL ASSERTION: the operator's file is what the engine reads --
    {
        const std::string p = write_tmp("sleeve_on.json", kRealisticControls);
        auto s = read_sleeve_controls(p, cfg);
        maltest::check(s.research_satellite,
                       "controls.json research_satellite=true enables the sleeve "
                       "even though config ships it false (the GUI toggle is real)");
        std::remove(p.c_str());
    }

    // The control file wins in BOTH directions, or "disable" would not work.
    {
        mal::config::SleeveConfig on;
        on.research_satellite_enabled = true;
        const std::string p = write_tmp(
            "sleeve_off.json", R"({"sleeves": {"research_satellite": false}})");
        maltest::check(!read_sleeve_controls(p, on).research_satellite,
                       "controls.json research_satellite=false disables the sleeve "
                       "even though config says true");
        std::remove(p.c_str());
    }

    // --- Fail-safe posture: unreadable means OFF, never on ------------------
    // A broken file must never allocate capital to a sleeve nobody turned on.
    {
        maltest::check(
            !read_sleeve_controls("/tmp/mal_test_no_such_file.json", cfg)
                 .research_satellite,
            "a missing controls.json leaves the sleeve OFF");
    }
    {
        const std::string p = write_tmp("sleeve_empty.json", "");
        maltest::check(!read_sleeve_controls(p, cfg).research_satellite,
                       "an empty controls.json leaves the sleeve OFF");
        std::remove(p.c_str());
    }
    {
        const std::string p = write_tmp("sleeve_malformed.json",
                                        "{\"sleeves\": {\"research_satellite\":");
        maltest::check(!read_sleeve_controls(p, cfg).research_satellite,
                       "a truncated controls.json leaves the sleeve OFF");
        std::remove(p.c_str());
    }
    {
        // No key at all: fall back to config, not to a guess.
        const std::string p = write_tmp("sleeve_absent.json",
                                        R"({"layers": {"council": true}})");
        maltest::check(!read_sleeve_controls(p, cfg).research_satellite,
                       "controls.json without the key falls back to config (off)");
        mal::config::SleeveConfig on;
        on.research_satellite_enabled = true;
        maltest::check(read_sleeve_controls(p, on).research_satellite,
                       "controls.json without the key falls back to config (on)");
        std::remove(p.c_str());
    }

    // --- The key must not collide with its config-shaped neighbours ---------
    // find_value_start matches the key WITH its closing quote, so
    // "research_satellite" cannot match "research_satellite_enabled". If it ever
    // did, a config-shaped key in the file would silently drive the sleeve.
    {
        const std::string p = write_tmp("sleeve_collide.json", R"({
          "sleeves": {"research_satellite": false},
          "research_satellite_enabled": true,
          "research_satellite_target_pct": 0.30
        })");
        maltest::check(!read_sleeve_controls(p, cfg).research_satellite,
                       "research_satellite is not confused with "
                       "research_satellite_enabled or _target_pct");
        std::remove(p.c_str());
    }

    // --- Change detection drives the toggle event ---------------------------
    {
        SleeveRuntime a, b;
        maltest::check(a == b, "two default SleeveRuntimes compare equal");
        b.research_satellite = true;
        maltest::check(!(a == b),
                       "an enable flip compares unequal, so the engine logs the "
                       "toggle instead of silently reallocating capital");
    }

    // --- The cap is unchanged by the toggle ---------------------------------
    // Enabling a sleeve allocates within the cap. It can never RAISE the cap.
    {
        mal::config::SleeveConfig on;
        on.research_satellite_enabled = true;
        maltest::check(
            mal::sleeve::satellite_cap_value(on, 100000.0) ==
                mal::sleeve::satellite_cap_value(cfg, 100000.0),
            "the hard cap is identical whether the sleeve is on or off: the "
            "toggle allocates within the cap, it never widens it");
    }

    return maltest::report("sleeve_controls");
}

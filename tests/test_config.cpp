// Unit tests for config loading + validation (the safety contract).
#include "config/config.hpp"

#include "tests/test_util.hpp"

using namespace mal;
using namespace maltest;

int main() {
    // 1. The canonical default config loads + validates cleanly.
    {
        try {
            auto cfg = config::load_config("config/default_config.yaml");
            check(cfg.system.starting_paper_balance == 100000,
                  "starting balance parsed");
            check(!cfg.system.live_mode_default_enabled,
                  "live disabled by default");
            check(cfg.venues.size() >= 4, "all venues parsed");
            check(cfg.risk.max_daily_loss_total_pct == 0.03,
                  "risk limit parsed");
            check(validate_config(cfg).empty(), "default config is valid");
        } catch (const std::exception& e) {
            check(false, std::string("default config threw: ") + e.what());
        }
    }

    // 2. Validation rejects an out-of-range percentage.
    {
        config::Config c;
        c.risk.max_daily_loss_total_pct = 1.5;  // > 1.0
        auto problems = validate_config(c);
        check(!problems.empty(), "out-of-range pct rejected");
    }

    // 3. Validation rejects live-by-default (safety invariant).
    {
        config::Config c;
        c.system.live_mode_default_enabled = true;
        auto problems = validate_config(c);
        bool found = false;
        for (const auto& p : problems)
            if (p.find("live_mode_default_enabled") != std::string::npos)
                found = true;
        check(found, "live-by-default rejected");
    }

    // 4. Validation rejects a venue defaulting to live.
    {
        config::Config c;
        config::VenueConfig v;
        v.name = "alpaca";
        v.mode = config::VenueMode::Live;
        c.venues.push_back(v);
        auto problems = validate_config(c);
        bool found = false;
        for (const auto& p : problems)
            if (p.find("must not default to live") != std::string::npos)
                found = true;
        check(found, "venue live-by-default rejected");
    }

    // 5. Validation rejects per-venue loss > total loss.
    {
        config::Config c;
        c.risk.max_daily_loss_total_pct = 0.02;
        c.risk.max_daily_loss_per_venue_pct = 0.05;  // > total
        auto problems = validate_config(c);
        bool found = false;
        for (const auto& p : problems)
            if (p.find("per_venue") != std::string::npos) found = true;
        check(found, "per-venue > total loss rejected");
    }

    // 6. Mode parse round-trip.
    {
        check(config::mode_to_string(config::parse_mode("paper")) == "paper",
              "mode round-trip paper");
        check(config::mode_to_string(config::parse_mode("live")) == "live",
              "mode round-trip live");
    }

    return report("config");
}

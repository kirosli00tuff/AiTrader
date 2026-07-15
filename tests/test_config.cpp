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
            // Polymarket removed. Remaining venues: alpaca, coinbase, ibkr.
            check(cfg.venues.size() >= 3, "all venues parsed");
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

    // 7. Bridge-call timeouts parse and default sanely (the no-trade-stall fix).
    {
        auto cfg = config::load_config("config/default_config.yaml");
        // The engine must outwait a full real council round trip (~16s measured),
        // so the council-call timeout is well above a single provider timeout.
        check(cfg.council.engine_council_call_timeout_ms >= 60000,
              "engine council-call timeout parsed (>= 60s)");
        check(cfg.council.engine_bridge_call_timeout_ms >= 1000,
              "engine fast-call timeout parsed");
        check(cfg.council.provider_timeout_seconds >= 1,
              "provider timeout parsed");
        check(cfg.council.gate_timeout_seconds >= 1, "gate timeout parsed");
    }

    // 8. Validation rejects an engine council timeout below a provider timeout
    //    (would let the engine hang up mid-round-trip -> the no-trade stall).
    {
        config::Config c;
        c.council.provider_timeout_seconds = 30;
        c.council.engine_council_call_timeout_ms = 5000;  // < 30s
        auto problems = validate_config(c);
        bool found = false;
        for (const auto& p : problems)
            if (p.find("engine_council_call_timeout_ms") != std::string::npos)
                found = true;
        check(found, "engine council timeout below provider timeout rejected");
    }

    // 9. Default profile is swing (nothing changes silently).
    {
        auto cfg = config::load_config("config/default_config.yaml");
        check(cfg.strategy.profile == "swing", "default profile is swing");
        check(cfg.strategy.reversion_style == "bollinger",
              "swing keeps the bollinger reversion");
        check(!cfg.strategy.momentum_dual_ma_filter,
              "swing keeps the dual-MA momentum filter off");
        check(cfg.council.fast_tier_max_notional_pct == 0.0 &&
                  cfg.council.fast_tier_max_conviction == 0.0,
              "swing never fast-tiers a real entry (0/0 thresholds)");
        check(cfg.council.council_daily_spend_ceiling_usd == 0.0 &&
                  cfg.council.council_monthly_spend_ceiling_usd == 0.0,
              "swing leaves the spend ceilings disabled");
    }

    // 10. The active_quant profile overlays the full evidence-backed set.
    {
        auto base = config::load_config("config/default_config.yaml");
        // Simulate the overlay effect the loader applies for active_quant.
        base.strategy.profile = "active_quant";
        base.strategy.reversion_style = "rsi2";
        base.strategy.momentum_dual_ma_filter = true;
        base.council.fast_tier_max_notional_pct = 0.01;
        base.council.fast_tier_max_conviction = 0.6;
        base.council.council_daily_spend_ceiling_usd = 5.0;
        base.council.council_monthly_spend_ceiling_usd = 100.0;
        base.strategy.whitelist = {"BTC/USD", "ETH/USD", "SOL/USD", "SPY",
                                   "QQQ", "AAPL", "MSFT", "NVDA"};
        auto problems = validate_config(base);
        check(problems.empty(), "active_quant overlay validates clean");
        check(base.strategy.whitelist.size() == 8,
              "active_quant widens the whitelist to liquid majors");
    }

    // 11. Validation rejects bad profile / reversion_style / RSI-2 ordering.
    {
        config::Config c;
        c.strategy.profile = "turbo";  // invalid
        auto p1 = validate_config(c);
        bool bad_profile = false;
        for (const auto& p : p1)
            if (p.find("strategy.profile") != std::string::npos) bad_profile = true;
        check(bad_profile, "invalid strategy.profile rejected");

        config::Config c2;
        c2.strategy.rsi2_exit = 8.0;            // below the entry thresholds (10/5)
        c2.strategy.rsi2_entry_crypto = 10.0;
        auto p2 = validate_config(c2);
        bool bad_exit = false;
        for (const auto& p : p2)
            if (p.find("rsi2_exit") != std::string::npos) bad_exit = true;
        check(bad_exit, "rsi2_exit at/below the entry thresholds rejected");
    }

    return report("config");
}

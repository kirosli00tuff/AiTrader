// Global-session equity rotation scaffold tests.
//
// The model ships DISABLED. Only NY (Alpaca US equities) has a reachable venue,
// so only US equities trade, exactly as now. The venue-capability gate is the
// standing safety rule: an equity whose region has no capable venue is refused
// (the engine logs venue_unavailable_for_region and never reaches an adapter).
// These tests exercise the pure decision logic the engine gate uses, plus the
// loaded config, with a crafted simulated clock for session detection.
#include <ctime>

#include "config/config.hpp"
#include "config/regional_session.hpp"
#include "test_util.hpp"

using namespace mal::config;

// Build a UTC epoch for a given hour:min, so session detection is tested against
// a SIMULATED timestamp (never the wall clock).
static std::time_t utc_at(int hour, int minute) {
    std::time_t now = 1'700'000'000;  // fixed base day, deterministic
    std::tm tm_utc{};
    gmtime_r(&now, &tm_utc);
    tm_utc.tm_hour = hour;
    tm_utc.tm_min = minute;
    tm_utc.tm_sec = 0;
    return timegm(&tm_utc);
}

int main() {
    Config cfg = load_config("config/default_config.yaml");
    const auto& rg = cfg.regional;

    // Ships DISABLED: rotation off, US-equities-during-US-hours behavior as now.
    maltest::check(!rg.global_equity_rotation_enabled,
                   "global_equity_rotation_enabled defaults false (disabled)");
    maltest::check(rg.sessions.size() == 3,
                   "three regional sessions defined (NY, London, Asia)");

    // Only NY has a reachable venue today. London and Asia are venue-unavailable.
    maltest::check(venue_available_for(Region::NY, rg),
                   "NY equities are tradeable (Alpaca reaches US equities)");
    maltest::check(!venue_available_for(Region::London, rg),
                   "London equities are venue-unavailable today");
    maltest::check(!venue_available_for(Region::Asia, rg),
                   "Asia equities are venue-unavailable today");

    // A US equity maps to NY and is tradeable (exactly as before).
    maltest::check(region_for_equity("SPY", rg) == Region::NY,
                   "a US equity maps to the NY region");
    maltest::check(venue_available_for(region_for_equity("SPY", rg), rg),
                   "the NY US equity clears the venue-capability gate (trades)");

    // The venue-capability gate: an equity placed in a region with no capable
    // venue is refused. This is the exact predicate the engine gate evaluates
    // before any adapter. Inject an Asia symbol to prove the refusal.
    RegionalSessionConfig injected = rg;
    for (auto& s : injected.sessions)
        if (s.region == Region::Asia) s.whitelist.push_back("7203.T");  // Toyota
    maltest::check(region_for_equity("7203.T", injected) == Region::Asia,
                   "an Asia-whitelisted equity maps to the Asia region");
    maltest::check(!venue_available_for(region_for_equity("7203.T", injected),
                                        injected),
                   "the Asia equity is refused: no connected venue reaches it");

    // Session detection uses the SUPPLIED (simulated) time, not the wall clock.
    maltest::check(open_session(utc_at(2, 0), rg) == Region::Asia,
                   "02:00 UTC is the Asia session (simulated-time detection)");
    maltest::check(open_session(utc_at(9, 0), rg) == Region::London,
                   "09:00 UTC is the London session");
    maltest::check(open_session(utc_at(14, 0), rg) == Region::NY,
                   "14:00 UTC is the NY session");

    // Crypto is never gated by a regional session: the model maps equity symbols
    // only, and the engine applies the gate only to category == "equity", so
    // crypto trades in every session. Assert crypto is in no region whitelist.
    bool crypto_in_any = false;
    for (const auto& s : rg.sessions)
        for (const auto& w : s.whitelist)
            if (w == "BTC/USD" || w == "ETH/USD") crypto_in_any = true;
    maltest::check(!crypto_in_any,
                   "crypto is in no equity region whitelist (never session-gated)");

    return maltest::report("regional_session");
}

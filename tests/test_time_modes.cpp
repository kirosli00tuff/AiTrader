// Time-mode tests (Task 3 + 4). iso8601_to_epoch round-trips epoch_to_iso8601 so
// replay council-cooldown spacing can key off the true historical bar ts, and
// us_equity_market_open honors the explicit time argument so the market-hours
// council skip keys off the simulated timestamp under a simulated clock (the
// engine passes now_epoch when simulated_clock_ is set, wall-clock otherwise).
#include <cstdio>
#include <ctime>
#include <string>

#include "core/util.hpp"
#include "test_util.hpp"

using namespace mal;

int main() {
    // Round-trip: parse(format(epoch)) == epoch (Task 4, historical ts).
    long epoch = 1767571200L;  // 2026-01-05T00:00:00Z
    std::string iso = util::epoch_to_iso8601(epoch);
    maltest::check(util::iso8601_to_epoch(iso) == epoch,
                   "iso8601_to_epoch round-trips epoch_to_iso8601");
    maltest::check(util::iso8601_to_epoch("not-a-timestamp") == 0,
                   "a malformed timestamp parses to 0");
    // Two bars an hour apart differ by 3600s under the true historical parse,
    // so replay cooldown spacing reflects real time, not a synthetic sequence.
    long a = util::iso8601_to_epoch("2026-03-02T14:30:00Z");
    long b = util::iso8601_to_epoch("2026-03-02T15:30:00Z");
    maltest::check(b - a == 3600, "historical ts spacing reflects real time");

    // us_equity_market_open honors the explicit time (Task 3). 2026-01-05 is a
    // Monday, 2026-01-04 a Sunday; January is standard time (ET = UTC-5).
    long mon_open = util::iso8601_to_epoch("2026-01-05T15:00:00Z");   // 10:00 ET
    long sun = util::iso8601_to_epoch("2026-01-04T15:00:00Z");        // Sunday
    long mon_night = util::iso8601_to_epoch("2026-01-05T02:00:00Z");  // 21:00 ET Sun
    maltest::check(util::us_equity_market_open((std::time_t)mon_open),
                   "Monday 10:00 ET is market-open at the given time");
    maltest::check(!util::us_equity_market_open((std::time_t)sun),
                   "Sunday is market-closed at the given time");
    maltest::check(!util::us_equity_market_open((std::time_t)mon_night),
                   "outside 09:30-16:00 ET is market-closed at the given time");

    return maltest::report("time_modes");
}

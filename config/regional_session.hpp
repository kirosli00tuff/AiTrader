// Market AI Lab — global-session equity rotation model (SCAFFOLD, DISABLED).
//
// Rotation follows the open regional market, Asia then London then NY, trading
// each region's equities during its session. It ships DISABLED because the paper
// venue Alpaca is US-only and cannot reach Asian or European exchanges. This
// header is the config-driven structure plus the pure venue-capability gate. It
// is deliberately a venue MAPPING, so adding IBKR global routing later is a
// config + adapter change, not an engine rewrite.
//
// THE safety rule (venue-capability gating): the engine only evaluates and
// trades an equity region when a connected venue can actually reach that
// region's exchange. Today only NY (Alpaca US equities) is reachable, so only
// NY equities trade, exactly as now. An equity order for a region with no
// capable venue is refused before it reaches any adapter.
#pragma once

#include <algorithm>
#include <ctime>
#include <string>
#include <vector>

namespace mal::config {

enum class Region { NY, London, Asia, Unknown };

inline std::string region_name(Region r) {
    switch (r) {
        case Region::NY: return "NY";
        case Region::London: return "London";
        case Region::Asia: return "Asia";
        default: return "Unknown";
    }
}

// One regional equity session. Hours are minutes since UTC midnight (the local
// exchange session converted to UTC); tz_label is documentation. venue_available
// is TRUE only when a connected venue can reach the region's exchange.
struct RegionSession {
    Region region = Region::Unknown;
    std::string exchange_id;      // us_equities | lse | tse
    std::string tz_label;         // America/New_York | Europe/London | Asia/Tokyo
    int open_min_utc = 0;         // session open, minutes since UTC midnight
    int close_min_utc = 0;        // session close, minutes since UTC midnight
    bool venue_available = false; // a connected venue can reach this exchange
    std::vector<std::string> whitelist;  // per-region equity whitelist placeholder
};

struct RegionalSessionConfig {
    // Ships DISABLED. When false (always for now) equities behave exactly as
    // today: US equities during US hours through Alpaca, nothing else. Enabling
    // it requires IBKR global market access, per-region whitelists, and this flag
    // on, and it stays off until the operator is deliberately live on IBKR.
    bool global_equity_rotation_enabled = false;
    std::vector<RegionSession> sessions;  // NY, London, Asia

    const RegionSession* find(Region r) const {
        for (const auto& s : sessions)
            if (s.region == r) return &s;
        return nullptr;
    }
};

// Which region an equity symbol belongs to. A symbol explicitly placed in the
// London or Asia whitelist maps there; everything else defaults to NY (US
// equities via Alpaca), so behavior is unchanged while no non-US symbol is
// configured.
inline Region region_for_equity(const std::string& symbol,
                                const RegionalSessionConfig& cfg) {
    for (Region r : {Region::Asia, Region::London}) {
        const auto* s = cfg.find(r);
        if (!s) continue;
        if (std::find(s->whitelist.begin(), s->whitelist.end(), symbol) !=
            s->whitelist.end())
            return r;
    }
    return Region::NY;
}

// THE safety rule: whether a connected venue can reach the region's exchange.
inline bool venue_available_for(Region r, const RegionalSessionConfig& cfg) {
    const auto* s = cfg.find(r);
    return s && s->venue_available;
}

// The region whose session is open at the given UTC time, for status display.
// Uses minutes since UTC midnight, so it honors the caller's clock (the engine
// passes the simulated epoch under clock_mode simulated). Unknown if none open.
inline Region open_session(std::time_t utc_now, const RegionalSessionConfig& cfg) {
    std::tm tm_utc{};
#if defined(_WIN32)
    gmtime_s(&tm_utc, &utc_now);
#else
    gmtime_r(&utc_now, &tm_utc);
#endif
    int mins = tm_utc.tm_hour * 60 + tm_utc.tm_min;
    for (const auto& s : cfg.sessions) {
        int o = s.open_min_utc, c = s.close_min_utc;
        bool open = (o <= c) ? (mins >= o && mins < c)
                             : (mins >= o || mins < c);  // wraps midnight UTC
        if (open) return s.region;
    }
    return Region::Unknown;
}

}  // namespace mal::config

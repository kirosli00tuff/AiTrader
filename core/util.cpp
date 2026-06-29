#include "core/util.hpp"

#include <chrono>
#include <ctime>
#include <sstream>

namespace mal::util {

std::string now_iso8601() {
    using namespace std::chrono;
    auto now = system_clock::now();
    std::time_t t = system_clock::to_time_t(now);
    std::tm tm{};
#if defined(_WIN32)
    gmtime_s(&tm, &t);
#else
    gmtime_r(&t, &tm);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm);
    return buf;
}

namespace {
// True if US Eastern observes DST (EDT) on the given UTC-broken-down date.
// US rule: 2nd Sunday of March 02:00 .. 1st Sunday of November 02:00.
// Approximated from the UTC date (the 02:00-local edge is irrelevant to the
// 09:30–16:00 trading session).
bool is_us_eastern_dst(const std::tm& utc) {
    int m = utc.tm_mon + 1;   // 1..12
    int d = utc.tm_mday;      // 1..31
    int wday = utc.tm_wday;   // 0=Sun
    if (m < 3 || m > 11) return false;
    if (m > 3 && m < 11) return true;
    int prev_sunday = d - wday;        // day-of-month of the most recent Sunday
    if (m == 3) return prev_sunday >= 8;   // on/after 2nd Sunday
    return prev_sunday <= 0;                // November: before 1st Sunday
}
}  // namespace

bool us_equity_market_open(std::time_t utc_now) {
    std::tm utc{};
#if defined(_WIN32)
    gmtime_s(&utc, &utc_now);
#else
    gmtime_r(&utc_now, &utc);
#endif
    int offset_hours = is_us_eastern_dst(utc) ? -4 : -5;  // EDT : EST
    std::time_t eastern = utc_now + offset_hours * 3600;
    std::tm et{};
#if defined(_WIN32)
    gmtime_s(&et, &eastern);
#else
    gmtime_r(&eastern, &et);
#endif
    if (et.tm_wday == 0 || et.tm_wday == 6) return false;  // weekend
    int minutes = et.tm_hour * 60 + et.tm_min;
    constexpr int kOpen = 9 * 60 + 30;   // 09:30 ET
    constexpr int kClose = 16 * 60;      // 16:00 ET
    return minutes >= kOpen && minutes < kClose;
}

std::string json_escape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 8);
    for (char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out += c;
        }
    }
    return out;
}

std::string to_json(const std::map<std::string, std::string>& str_fields,
                    const std::map<std::string, double>& num_fields) {
    std::ostringstream os;
    os << '{';
    bool first = true;
    for (const auto& [k, v] : str_fields) {
        if (!first) os << ',';
        first = false;
        os << '"' << json_escape(k) << "\":\"" << json_escape(v) << '"';
    }
    for (const auto& [k, v] : num_fields) {
        if (!first) os << ',';
        first = false;
        os << '"' << json_escape(k) << "\":" << v;
    }
    os << '}';
    return os.str();
}

}  // namespace mal::util

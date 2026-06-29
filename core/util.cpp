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

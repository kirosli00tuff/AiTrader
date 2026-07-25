#include "core/bridge_client.hpp"

#include <arpa/inet.h>
#include <netdb.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cctype>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <sstream>

namespace mal::bridge {

namespace {

long now_ms() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(steady_clock::now().time_since_epoch())
        .count();
}

// errno as a short stable token, so a payload field stays greppable.
std::string errno_token() {
    switch (errno) {
        case ECONNREFUSED: return "ECONNREFUSED";
        case EHOSTUNREACH: return "EHOSTUNREACH";
        case ENETUNREACH:  return "ENETUNREACH";
        case ETIMEDOUT:    return "ETIMEDOUT";
        case ECONNRESET:   return "ECONNRESET";
        case EPIPE:        return "EPIPE";
        case EAGAIN:       return "EAGAIN";
        case EMFILE:       return "EMFILE";
        case ENFILE:       return "ENFILE";
        default:           return std::string("errno=") + std::to_string(errno);
    }
}

// Parse "HTTP/1.1 200 OK" -> 200. Returns 0 when the line is not a status line.
int status_from(const std::string& resp) {
    if (resp.size() < 12 || resp.compare(0, 5, "HTTP/") != 0) return 0;
    auto sp = resp.find(' ');
    if (sp == std::string::npos) return 0;
    try {
        return std::stoi(resp.substr(sp + 1, 3));
    } catch (...) {
        return 0;
    }
}

}  // namespace

std::string HttpResult::label() const {
    switch (outcome) {
        case HttpOutcome::kOk:            return "ok";
        case HttpOutcome::kConnectFailed: return "connect_failed";
        case HttpOutcome::kSendFailed:    return "send_failed";
        case HttpOutcome::kTimedOut:      return "timed_out";
        case HttpOutcome::kIncomplete:    return "incomplete_response";
        case HttpOutcome::kHttpError:     return "http_error";
    }
    return "unknown";
}

std::string HttpResult::describe() const {
    const std::string took = " after " + std::to_string(elapsed_ms) + " ms";
    switch (outcome) {
        case HttpOutcome::kOk:
            return "ok" + took;
        case HttpOutcome::kConnectFailed:
            // The ONLY outcome that means unreachable. Say so here and nowhere
            // else, because this is the only one that measured it.
            return "bridge unreachable: connect failed (" + detail + ")" + took;
        case HttpOutcome::kSendFailed:
            return "the request could not be sent (" + detail + ")" + took;
        case HttpOutcome::kTimedOut:
            return "no response within the " + std::to_string(deadline_ms) +
                   " ms deadline (waited " + std::to_string(elapsed_ms) +
                   " ms, " + detail +
                   "), the bridge was reachable but had not answered";
        case HttpOutcome::kIncomplete:
            return "the bridge closed the connection without completing the "
                   "response (" + detail + ")" + took;
        case HttpOutcome::kHttpError:
            return "the bridge answered HTTP " + std::to_string(status) + took;
    }
    return "unknown outcome" + took;
}

HttpResult http_post(const std::string& host, int port, const std::string& path,
                     const std::string& body, int timeout_ms) {
    HttpResult r;
    r.deadline_ms = timeout_ms;
    const long started = now_ms();
    const long deadline = started + timeout_ms;
    auto finish = [&](HttpOutcome o, const std::string& detail) {
        r.outcome = o;
        r.detail = detail;
        r.elapsed_ms = now_ms() - started;
        return r;
    };

    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return finish(HttpOutcome::kConnectFailed, errno_token());

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<uint16_t>(port));
    if (::inet_pton(AF_INET, host.c_str(), &addr.sin_addr) != 1) {
        hostent* he = ::gethostbyname(host.c_str());  // e.g. "localhost"
        if (!he) {
            ::close(fd);
            return finish(HttpOutcome::kConnectFailed, "resolve failed");
        }
        std::memcpy(&addr.sin_addr, he->h_addr, he->h_length);
    }

    // Send gets the whole budget. A localhost connect either lands or refuses
    // immediately, so a blocking connect costs nothing and reports errno.
    timeval tv{};
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    ::setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        const std::string why = errno_token();
        ::close(fd);
        return finish(HttpOutcome::kConnectFailed, why);
    }

    std::ostringstream req;
    req << "POST " << path << " HTTP/1.1\r\n"
        << "Host: " << host << "\r\n"
        << "Content-Type: application/json\r\n"
        << "Content-Length: " << body.size() << "\r\n"
        << "Connection: close\r\n\r\n"
        << body;
    const std::string raw = req.str();
    size_t sent = 0;
    while (sent < raw.size()) {
        ssize_t n =
            ::send(fd, raw.data() + sent, raw.size() - sent, MSG_NOSIGNAL);
        if (n <= 0) {
            if (n < 0 && errno == EINTR) continue;
            const std::string why = errno_token();
            ::close(fd);
            return finish(HttpOutcome::kSendFailed, why);
        }
        sent += static_cast<size_t>(n);
    }

    // TOTAL deadline, recomputed before every receive. This is the whole point
    // of the 2026-07-25 change: a funnel that legitimately thinks for 90 s is
    // not a transport failure, and a peer that dribbles one byte a minute is.
    std::string resp;
    char buf[4096];
    while (true) {
        const long remaining = deadline - now_ms();
        if (remaining <= 0) {
            ::close(fd);
            return finish(HttpOutcome::kTimedOut,
                          std::to_string(resp.size()) + " bytes received");
        }
        pollfd pfd{fd, POLLIN, 0};
        int pr = ::poll(&pfd, 1, static_cast<int>(remaining));
        if (pr == 0) {
            ::close(fd);
            return finish(HttpOutcome::kTimedOut,
                          std::to_string(resp.size()) + " bytes received");
        }
        if (pr < 0) {
            if (errno == EINTR) continue;
            const std::string why = errno_token();
            ::close(fd);
            return finish(HttpOutcome::kIncomplete, why);
        }
        ssize_t n = ::recv(fd, buf, sizeof(buf), 0);
        if (n == 0) break;  // peer closed: Connection: close, response complete
        if (n < 0) {
            if (errno == EINTR) continue;
            const std::string why = errno_token();
            ::close(fd);
            return finish(HttpOutcome::kIncomplete, why);
        }
        resp.append(buf, static_cast<size_t>(n));
    }
    ::close(fd);

    const auto pos = resp.find("\r\n\r\n");
    if (pos == std::string::npos)
        return finish(HttpOutcome::kIncomplete,
                      std::to_string(resp.size()) +
                          " bytes received, no header terminator");
    r.status = status_from(resp);
    if (r.status != 200)
        return finish(HttpOutcome::kHttpError,
                      "status " + std::to_string(r.status));
    r.body = resp.substr(pos + 4);
    return finish(HttpOutcome::kOk, "");
}

std::optional<std::string> http_post_json(const std::string& host, int port,
                                          const std::string& path,
                                          const std::string& body,
                                          int timeout_ms) {
    HttpResult r = http_post(host, port, path, body, timeout_ms);
    if (!r.ok()) return std::nullopt;
    return r.body;
}

namespace {
std::optional<size_t> find_value_start(const std::string& json,
                                       const std::string& key) {
    std::string needle = "\"" + key + "\"";
    auto p = json.find(needle);
    if (p == std::string::npos) return std::nullopt;
    p = json.find(':', p + needle.size());
    if (p == std::string::npos) return std::nullopt;
    ++p;
    while (p < json.size() && std::isspace(static_cast<unsigned char>(json[p])))
        ++p;
    return p;
}
}  // namespace

double json_get_number(const std::string& json, const std::string& key,
                       double def) {
    auto p = find_value_start(json, key);
    if (!p) return def;
    try {
        return std::stod(json.substr(*p));
    } catch (...) {
        return def;
    }
}

std::string json_get_string(const std::string& json, const std::string& key,
                            const std::string& def) {
    auto p = find_value_start(json, key);
    if (!p || *p >= json.size() || json[*p] != '"') return def;
    size_t start = *p + 1;
    size_t end = json.find('"', start);
    if (end == std::string::npos) return def;
    return json.substr(start, end - start);
}

bool json_get_bool(const std::string& json, const std::string& key, bool def) {
    auto p = find_value_start(json, key);
    if (!p || *p >= json.size()) return def;
    if (json.compare(*p, 4, "true") == 0) return true;
    if (json.compare(*p, 5, "false") == 0) return false;
    if (json[*p] == '1') return true;
    if (json[*p] == '0') return false;
    return def;
}

}  // namespace mal::bridge

#include "core/bridge_client.hpp"

#include <arpa/inet.h>
#include <netdb.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cctype>
#include <cstring>
#include <sstream>

namespace mal::bridge {

std::optional<std::string> http_post_json(const std::string& host, int port,
                                          const std::string& path,
                                          const std::string& body,
                                          int timeout_ms) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return std::nullopt;

    timeval tv{};
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    ::setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    ::setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<uint16_t>(port));
    if (::inet_pton(AF_INET, host.c_str(), &addr.sin_addr) != 1) {
        // Resolve hostname (e.g. "localhost").
        hostent* he = ::gethostbyname(host.c_str());
        if (!he) { ::close(fd); return std::nullopt; }
        std::memcpy(&addr.sin_addr, he->h_addr, he->h_length);
    }

    if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        ::close(fd);
        return std::nullopt;
    }

    std::ostringstream req;
    req << "POST " << path << " HTTP/1.1\r\n"
        << "Host: " << host << "\r\n"
        << "Content-Type: application/json\r\n"
        << "Content-Length: " << body.size() << "\r\n"
        << "Connection: close\r\n\r\n"
        << body;
    std::string r = req.str();
    if (::send(fd, r.data(), r.size(), 0) < 0) { ::close(fd); return std::nullopt; }

    std::string resp;
    char buf[4096];
    ssize_t n;
    while ((n = ::recv(fd, buf, sizeof(buf), 0)) > 0)
        resp.append(buf, static_cast<size_t>(n));
    ::close(fd);

    auto pos = resp.find("\r\n\r\n");
    if (pos == std::string::npos) return std::nullopt;
    // Only return body for 2xx responses.
    if (resp.compare(0, 12, "HTTP/1.1 200") != 0 &&
        resp.compare(0, 12, "HTTP/1.0 200") != 0)
        return std::nullopt;
    return resp.substr(pos + 4);
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

}  // namespace mal::bridge

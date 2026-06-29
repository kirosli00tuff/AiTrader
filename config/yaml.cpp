#include "config/yaml.hpp"

#include <fstream>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace mal::config {

std::shared_ptr<const YamlNode> YamlNode::at(const std::string& dotted_path) const {
    const YamlNode* cur = this;
    std::string segment;
    std::istringstream ss(dotted_path);
    while (std::getline(ss, segment, '.')) {
        if (cur->is_scalar) return nullptr;
        auto it = cur->map.find(segment);
        if (it == cur->map.end()) return nullptr;
        cur = it->second.get();
    }
    // Return a non-owning view; safe because the tree outlives callers here.
    return std::shared_ptr<const YamlNode>(std::shared_ptr<const YamlNode>{}, cur);
}

namespace {

// Strip a trailing comment that is not inside quotes, then trim whitespace.
std::string strip_comment_and_trim(const std::string& raw) {
    std::string out;
    bool in_single = false, in_double = false;
    for (char c : raw) {
        if (c == '\'' && !in_double) in_single = !in_single;
        else if (c == '"' && !in_single) in_double = !in_double;
        if (c == '#' && !in_single && !in_double) break;
        out.push_back(c);
    }
    size_t b = out.find_first_not_of(" \t\r\n");
    if (b == std::string::npos) return "";
    size_t e = out.find_last_not_of(" \t\r\n");
    return out.substr(b, e - b + 1);
}

std::string unquote(const std::string& s) {
    if (s.size() >= 2 &&
        ((s.front() == '"' && s.back() == '"') ||
         (s.front() == '\'' && s.back() == '\''))) {
        return s.substr(1, s.size() - 2);
    }
    return s;
}

int leading_spaces(const std::string& line, size_t& tab_at) {
    int n = 0;
    for (char c : line) {
        if (c == ' ') ++n;
        else if (c == '\t') { tab_at = static_cast<size_t>(n); return -1; }
        else break;
    }
    return n;
}

}  // namespace

std::shared_ptr<YamlNode> parse_yaml(const std::string& text) {
    auto root = std::make_shared<YamlNode>();

    struct Frame { int indent; std::shared_ptr<YamlNode> node; };
    std::vector<Frame> stack{{-1, root}};

    std::istringstream in(text);
    std::string line;
    int line_no = 0;
    while (std::getline(in, line)) {
        ++line_no;
        size_t tab_at = std::string::npos;
        int indent = leading_spaces(line, tab_at);
        if (indent < 0) {
            throw std::runtime_error("YAML: tab indentation at line " +
                                     std::to_string(line_no));
        }
        std::string content = strip_comment_and_trim(line);
        if (content.empty()) continue;  // blank or comment-only

        auto colon = content.find(':');
        if (colon == std::string::npos) {
            throw std::runtime_error("YAML: expected 'key:' at line " +
                                     std::to_string(line_no));
        }
        std::string key = content.substr(0, colon);
        // trim key
        size_t kb = key.find_first_not_of(" \t");
        size_t ke = key.find_last_not_of(" \t");
        key = (kb == std::string::npos) ? "" : key.substr(kb, ke - kb + 1);
        std::string value = content.substr(colon + 1);
        size_t vb = value.find_first_not_of(" \t");
        value = (vb == std::string::npos) ? "" : value.substr(vb);

        // Pop frames until we find the parent (strictly smaller indent).
        while (stack.size() > 1 && indent <= stack.back().indent) stack.pop_back();
        auto parent = stack.back().node;

        auto node = std::make_shared<YamlNode>();
        if (!value.empty()) {
            node->is_scalar = true;
            node->scalar = unquote(value);
        }
        parent->map[key] = node;
        if (value.empty()) {
            // A new mapping level begins beneath this key.
            stack.push_back({indent, node});
        }
    }
    return root;
}

std::shared_ptr<YamlNode> load_yaml_file(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot open config file: " + path);
    std::ostringstream ss;
    ss << f.rdbuf();
    return parse_yaml(ss.str());
}

}  // namespace mal::config

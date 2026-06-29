// Market AI Lab — minimal YAML subset parser.
//
// Supports the exact subset used by config/*.yaml: indentation-based nested
// mappings, `key: value` scalars, `#` comments, and quoted/unquoted scalars.
// It deliberately does NOT support sequences, anchors, or flow style — the
// canonical config uses none of those. Keeping the parser tiny avoids a heavy
// third-party dependency while remaining auditable (config is the safety
// contract, so its loader must be easy to reason about).
#pragma once

#include <map>
#include <memory>
#include <optional>
#include <string>

namespace mal::config {

// A YAML node is either a scalar (leaf) or a mapping of child nodes.
struct YamlNode {
    bool is_scalar = false;
    std::string scalar;                                  // valid when is_scalar
    std::map<std::string, std::shared_ptr<YamlNode>> map;  // valid otherwise

    // Navigate by dotted path, e.g. "risk.max_daily_loss_total_pct".
    std::shared_ptr<const YamlNode> at(const std::string& dotted_path) const;
};

// Parse YAML text into a root mapping node. Throws std::runtime_error on
// structural errors (inconsistent indentation, tabs, etc.).
std::shared_ptr<YamlNode> parse_yaml(const std::string& text);

// Load + parse a file. Throws std::runtime_error if the file cannot be read.
std::shared_ptr<YamlNode> load_yaml_file(const std::string& path);

}  // namespace mal::config

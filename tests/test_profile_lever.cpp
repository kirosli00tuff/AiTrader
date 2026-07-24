// The strategy profile's runtime lever, C++ half (2026-07-23).
//
// The SHIPPED config carries the SHIPPED profile (swing): the runtime choice
// lives in controls.json ("strategy_profile"), never as an edit to the
// shipped default (that edit got swept into commit 440fda8, which is the
// failure mode this lever removes). The override is applied at load, so the
// active_quant overlay keys off the RESOLVED profile; an invalid or missing
// value means NO override, config decides.
#include <cstdio>
#include <fstream>
#include <string>

#include "config/config.hpp"
#include "core/profile_controls.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {
void write_file(const std::string& path, const std::string& body) {
    std::ofstream out(path);
    out << body;
}
}  // namespace

int main() {
    // The shipped file ships the shipped profile. This is the guard that
    // fails if a future session reintroduces a profile edit to the yaml as
    // the mechanism instead of the control-file lever.
    config::Config shipped = config::load_config("config/default_config.yaml");
    maltest::check(shipped.strategy.profile == "swing",
                   "the SHIPPED config carries the SHIPPED profile (swing); "
                   "select active_quant through controls.json "
                   "strategy_profile, never by editing the shipped default");
    maltest::check(shipped.strategy.whitelist.size() == 4,
                   "shipped (swing) whitelist is the four-name core");

    // The override applies the overlay at load.
    config::Config aq =
        config::load_config("config/default_config.yaml", "active_quant");
    maltest::check(aq.strategy.profile == "active_quant",
                   "the override selects active_quant");
    maltest::check(aq.strategy.reversion_style == "rsi2",
                   "the active_quant overlay applied (rsi2 reversion)");
    maltest::check(aq.strategy.whitelist.size() == 8,
                   "the active_quant overlay applied (eight-name core)");

    // The resolver: valid value wins, invalid and missing mean no override.
    const std::string dir = "/tmp";
    const std::string ok = dir + "/mal_test_profile_ok.json";
    const std::string bad = dir + "/mal_test_profile_bad.json";
    const std::string missing = dir + "/mal_test_profile_missing.json";
    write_file(ok, "{\"strategy_profile\": \"active_quant\", \"x\": 1}");
    write_file(bad, "{\"strategy_profile\": \"yolo_mode\"}");
    std::remove(missing.c_str());
    maltest::check(core::resolve_profile_override(ok) == "active_quant",
                   "a valid control-file profile overrides");
    maltest::check(core::resolve_profile_override(bad).empty(),
                   "an invalid profile value is refused, never guessed");
    maltest::check(core::resolve_profile_override(missing).empty(),
                   "a missing control file means no override, config decides");
    std::remove(ok.c_str());
    std::remove(bad.c_str());

    return maltest::report("profile_lever");
}

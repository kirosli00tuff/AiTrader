// Strict-mode tests (Task 3): on the real paper path (feed_mode alpaca_paper),
// a layer set on-real with no reachable real service makes the engine refuse to
// start (verify_real_layers_reachable throws with exactly what is missing). A
// layer set on-mock is an explicit choice and does not throw. Offline feed modes
// are a no-op. No network: use_bridge is false so an on-real layer is
// unreachable, and offline construction never connects.
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <stdexcept>
#include <string>

#include "config/config.hpp"
#include "core/engine.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {
void rm_db(const std::string& p) {
    std::remove(p.c_str());
    std::remove((p + "-wal").c_str());
    std::remove((p + "-shm").c_str());
}

bool throws_verify(const std::string& feed_mode, const std::string& controls_body,
                   const std::string& tag) {
    const std::string dir = "/tmp/mal_strict_" + tag;
    std::string mk = "mkdir -p " + dir;
    if (std::system(mk.c_str()) != 0) return false;
    const std::string ctl = dir + "/controls.json";
    if (!controls_body.empty()) {
        std::ofstream o(ctl); o << controls_body;
    } else {
        std::remove(ctl.c_str());  // absent => defaults on-real
    }
    setenv("MAL_CONTROL_DIR", dir.c_str(), 1);
    const std::string db = "/tmp/mal_strict_" + tag + ".db";
    rm_db(db);
    config::Config cfg = config::load_config("config/default_config.yaml");
    core::EngineOptions opts;
    opts.db_path = db;
    opts.schema_path = "storage/schema.sql";
    opts.feed_mode = feed_mode;
    opts.use_bridge = false;  // no bridge => an on-real advisory layer is unreachable
    bool threw = false;
    try {
        core::Engine engine(std::move(cfg), opts);
        engine.verify_real_layers_reachable();
    } catch (const std::exception&) {
        threw = true;
    }
    rm_db(db);
    std::remove(ctl.c_str());
    unsetenv("MAL_CONTROL_DIR");
    return threw;
}
}  // namespace

int main() {
    // 1. alpaca_paper + layers on-real (no controls.json => default real) + no
    //    bridge => refuse to start.
    maltest::check(throws_verify("alpaca_paper", "", "onreal"),
                   "alpaca_paper + on-real + no bridge refuses to start");

    // 2. alpaca_paper + every advisory layer on-MOCK (explicit choice) => starts
    //    without error even with no bridge.
    const std::string all_mock =
        R"({"layers":{"adaptive":true,"council":true,"dnn_advisory":true,"whale":true},)"
        R"("council_source":"mock","dnn_advisory_source":"mock","whale_source":"mock"})";
    maltest::check(!throws_verify("alpaca_paper", all_mock, "onmock"),
                   "alpaca_paper + on-mock (by choice) starts without error");

    // 3. Offline feed mode keeps mock behavior: strict check is a no-op even
    //    with layers on-real and no bridge.
    maltest::check(!throws_verify("synthetic_regimes", "", "offline"),
                   "offline feed mode is a strict-check no-op (keeps mock)");

    return maltest::report("strict_mode");
}

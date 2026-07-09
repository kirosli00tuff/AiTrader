// Operator kill-switch wiring test.
//
// The engine consumes the GUI/API kill-request control file and trips the SAME
// latching kill switch used for a loss-triggered halt, archives the processed
// request so a stale file cannot re-trip on restart, and still requires a manual
// resume regardless of what tripped it. Offline synthetic feed, temp SQLite DB
// and temp control dir. No network.
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>

#include "config/config.hpp"
#include "core/engine.hpp"
#include "risk/risk_gate.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {
void rm_db(const std::string& p) {
    std::remove(p.c_str());
    std::remove((p + "-wal").c_str());
    std::remove((p + "-shm").c_str());
}
bool file_exists(const std::string& p) {
    std::ifstream f(p);
    return f.good();
}
void write_kill_request(const std::string& dir, bool requested,
                        const std::string& reason) {
    std::ofstream f(dir + "/kill_request.json");
    f << "{\"requested\": " << (requested ? "true" : "false")
      << ", \"reason\": \"" << reason << "\", \"ts\": \"2026-07-09T00:00:00Z\"}";
}
core::EngineOptions synth_opts(const std::string& db) {
    core::EngineOptions o;
    o.db_path = db;
    o.schema_path = "storage/schema.sql";
    o.feed_mode = "synthetic_regimes";
    o.clock_mode = "simulated";
    o.native_bar_seconds = 300;
    return o;
}
}  // namespace

int main() {
    const std::string ctrl = "/tmp/mal_test_kill_ctrl";
    // Point the engine at a private control dir (the same env var the API uses).
    ::setenv("MAL_CONTROL_DIR", ctrl.c_str(), 1);
    std::system(("mkdir -p " + ctrl).c_str());
    std::remove((ctrl + "/kill_request.json").c_str());
    std::remove((ctrl + "/kill_request.processed.json").c_str());

    config::Config cfg = config::load_config("config/default_config.yaml");
    const std::string db = "/tmp/mal_test_kill.db";
    rm_db(db);

    // --- A. A pending request trips the switch on the next iteration ----------
    {
        core::Engine e(cfg, synth_opts(db));
        e.run(5);  // running normally, no request pending
        maltest::check(!e.kill_switch_tripped(),
                       "kill switch is not tripped before any request");

        write_kill_request(ctrl, true, "operator halt from GUI");
        e.run(1);  // this step consumes the pending request
        maltest::check(e.kill_switch_tripped(),
                       "engine trips the kill switch on the iteration after a "
                       "pending request appears");
        maltest::check(e.manual_resume_pending(),
                       "operator-tripped switch still requires a manual resume");
        maltest::check(!file_exists(ctrl + "/kill_request.json"),
                       "processed request file is removed from the live path");
        maltest::check(file_exists(ctrl + "/kill_request.processed.json"),
                       "processed request is archived, not silently discarded");

        // Once tripped, the switch latches and no new native trade opens.
        long long trades_at_trip = e.storage().count("trades");
        e.run(10);
        maltest::check(e.kill_switch_tripped(),
                       "kill switch latches across later iterations");
        maltest::check(e.storage().count("trades") == trades_at_trip,
                       "no new paper trades open after the operator halt");
    }

    // --- B. Restart with the archived (already-processed) file: no re-trip -----
    {
        core::Engine e2(cfg, synth_opts(db));  // same db + same control dir
        maltest::check(!e2.kill_switch_tripped(),
                       "a fresh engine does not start tripped");
        e2.run(1);
        maltest::check(!e2.kill_switch_tripped(),
                       "an already-processed (archived) request does not re-trip "
                       "the kill switch on restart");
    }

    // --- C. A cleared (requested=false) control file is a no-op ---------------
    {
        write_kill_request(ctrl, false, "cleared");
        core::Engine e3(cfg, synth_opts(db));
        e3.run(1);
        maltest::check(!e3.kill_switch_tripped(),
                       "a requested=false control file never trips the switch");
        std::remove((ctrl + "/kill_request.json").c_str());
    }

    // --- D. Manual resume required regardless of the trip SOURCE ---------------
    {
        risk::KillSwitch ks(true, /*manual_resume_required=*/true);
        maltest::check(ks.trip("operator kill request (GUI): manual test"),
                       "operator-sourced trip latches the switch");
        maltest::check(ks.manual_resume_pending(),
                       "manual resume is pending regardless of the trip source");
        maltest::check(ks.manual_resume(), "manual resume clears the latch");
        maltest::check(!ks.tripped(),
                       "switch clears only after an explicit manual resume");
    }

    rm_db(db);
    std::remove((ctrl + "/kill_request.processed.json").c_str());
    return maltest::report("kill_switch");
}

// The engine's own stop record carries its attribution (2026-07-24).
//
// continuous_start records the launcher (MAL_LAUNCHER) and pid;
// continuous_stop records WHICH signal ended the loop and the pid, and says
// plainly that the sender is whatever engine_stop_requested event precedes it,
// else unattributed. The 2026-07-21 stop could not be attributed because none
// of this existed.
#include <sqlite3.h>

#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <string>

#include "config/config.hpp"
#include "core/engine.hpp"
#include "storage/storage.hpp"
#include "test_util.hpp"

using namespace mal;

namespace {
void rm_db(const std::string& p) {
    std::remove(p.c_str());
    std::remove((p + "-wal").c_str());
    std::remove((p + "-shm").c_str());
}

std::string one(storage::Storage& s, const std::string& sql) {
    sqlite3_stmt* st = nullptr;
    std::string v;
    if (sqlite3_prepare_v2(s.handle(), sql.c_str(), -1, &st, nullptr) ==
        SQLITE_OK) {
        if (sqlite3_step(st) == SQLITE_ROW) {
            const unsigned char* t = sqlite3_column_text(st, 0);
            if (t) v = reinterpret_cast<const char*>(t);
        }
    }
    if (st) sqlite3_finalize(st);
    return v;
}
}  // namespace

int main() {
    const std::string db = "/tmp/mal_test_stop_attr.db";
    rm_db(db);
    setenv("MAL_LAUNCHER", "attribution_test", 1);

    config::Config cfg = config::load_config("config/default_config.yaml");
    core::EngineOptions opts;
    opts.db_path = db;
    opts.schema_path = "storage/schema.sql";
    opts.feed_mode = "flat_random_walk";
    opts.continuous = true;
    core::Engine engine(cfg, opts);

    // A pre-set SIGTERM: run_forever writes its start and stop records and
    // returns without an iteration, exactly the shape of an immediate stop.
    volatile std::sig_atomic_t flag = SIGTERM;
    engine.run_forever(&flag);

    storage::Storage s(db);
    const std::string start_payload = one(
        s, "SELECT payload_json FROM events WHERE kind='continuous_start' "
           "ORDER BY id DESC LIMIT 1");
    maltest::check(start_payload.find("attribution_test") != std::string::npos,
                   "continuous_start records the launcher (MAL_LAUNCHER)");
    maltest::check(start_payload.find("\"pid\"") != std::string::npos,
                   "continuous_start records the pid");

    const std::string stop_payload = one(
        s, "SELECT payload_json FROM events WHERE kind='continuous_stop' "
           "ORDER BY id DESC LIMIT 1");
    maltest::check(stop_payload.find("\"stop_signal\":15") !=
                       std::string::npos,
                   "continuous_stop records WHICH signal ended the loop");
    maltest::check(stop_payload.find("SIGTERM") != std::string::npos,
                   "continuous_stop names the signal in its cause");
    maltest::check(stop_payload.find("\"pid\"") != std::string::npos,
                   "continuous_stop records the pid, pairing with the start");

    unsetenv("MAL_LAUNCHER");
    return maltest::report("stop_attribution");
}

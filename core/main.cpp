// Market AI Lab — engine entry point.
//
// Runs the paper loop and persists everything to the shared SQLite DB.
// Two modes:
//   finite demo:  mal_engine [--iterations N]            (default, 20 ticks)
//   continuous:   mal_engine --continuous [--interval-seconds N]
// Usage: mal_engine --config <yaml> --db <path> --schema <sql> [--iterations N]
//                   [--continuous] [--interval-seconds N] [--data-source mock|alpaca]
//                   [--bridge host:port]
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

#include "config/config.hpp"
#include "core/engine.hpp"

namespace {
std::string arg_value(int argc, char** argv, const std::string& flag,
                      const std::string& def) {
    for (int i = 1; i + 1 < argc; ++i)
        if (flag == argv[i]) return argv[i + 1];
    return def;
}

bool arg_flag(int argc, char** argv, const std::string& flag) {
    for (int i = 1; i < argc; ++i)
        if (flag == argv[i]) return true;
    return false;
}

// Set by SIGINT/SIGTERM; the continuous loop finishes its current tick, flushes,
// and exits cleanly.
volatile std::sig_atomic_t g_stop = 0;
extern "C" void handle_stop(int) { g_stop = 1; }
}  // namespace

int main(int argc, char** argv) {
    try {
        std::string cfg_path =
            arg_value(argc, argv, "--config", "config/default_config.yaml");
        std::string db_path = arg_value(argc, argv, "--db", "market_ai_lab.db");
        std::string schema =
            arg_value(argc, argv, "--schema", "storage/schema.sql");
        int iterations = std::atoi(
            arg_value(argc, argv, "--iterations", "20").c_str());
        std::string bridge = arg_value(argc, argv, "--bridge", "");
        bool continuous = arg_flag(argc, argv, "--continuous");
        int interval_seconds = std::atoi(
            arg_value(argc, argv, "--interval-seconds", "0").c_str());
        std::string data_source = arg_value(argc, argv, "--data-source", "");
        // Bootstrap-sim: legacy generic factor loop with simulated PnL (OFF by
        // default). native-bar-seconds: bar bucket size; <=0 = one bar per tick
        // (testability — exercises the native entry/exit path quickly).
        bool bootstrap_sim = arg_flag(argc, argv, "--bootstrap-sim");
        long native_bar_seconds = std::atol(
            arg_value(argc, argv, "--native-bar-seconds", "300").c_str());

        auto cfg = mal::config::load_config(cfg_path);

        mal::core::EngineOptions opts;
        opts.db_path = db_path;
        opts.schema_path = schema;
        opts.continuous = continuous;
        opts.interval_seconds = interval_seconds;
        opts.data_source = data_source;
        opts.bootstrap_sim = bootstrap_sim;
        opts.native_bar_seconds = native_bar_seconds;
        if (!bridge.empty()) {
            auto colon = bridge.find(':');
            opts.bridge_host = bridge.substr(0, colon);
            opts.bridge_port =
                colon == std::string::npos ? 8765
                                           : std::atoi(bridge.c_str() + colon + 1);
            opts.use_bridge = true;
        }

        std::string source =
            !data_source.empty() ? data_source : cfg.market_data.source;
        int eff_interval =
            interval_seconds > 0 ? interval_seconds
                                 : cfg.engine.loop_interval_seconds;

        std::cout << "Market AI Lab engine starting (live DISABLED by default)\n"
                  << "  config: " << cfg_path << "\n"
                  << "  db:     " << db_path << "\n"
                  << "  mode:   "
                  << (continuous ? "continuous (24/7)" : "finite demo") << "\n";
        if (continuous)
            std::cout << "  every:  " << eff_interval << "s\n";
        else
            std::cout << "  iters:  " << iterations << "\n";
        std::cout << "  source: " << source << "\n"
                  << "  bridge: " << (opts.use_bridge ? bridge : "off (mock)")
                  << "\n";
        // Make it unambiguous which LLM council scores the llm_ factors. The
        // REAL council only runs via the Python bridge with llm.use_real_council
        // = true; the bridge itself prints the authoritative real-vs-mock line.
        std::cout << "  llm:    "
                  << (opts.use_bridge
                          ? "via python bridge (see bridge log: REAL vs mock council)"
                          : "in-process C++ mock (real council needs --bridge + "
                            "llm.use_real_council=true)")
                  << "\n";

        mal::core::Engine engine(std::move(cfg), opts);

        if (continuous) {
            std::signal(SIGINT, handle_stop);
            std::signal(SIGTERM, handle_stop);
            std::cout << "Continuous mode running. Press Ctrl-C to stop.\n";
            engine.run_forever(&g_stop);
            std::cout << "\nShutdown complete.\n";
        } else {
            engine.run(iterations);
        }

        std::cout << "Paper loop complete. Trades="
                  << engine.storage().count("trades")
                  << " Blocked=" << engine.storage().count("blocked_trades")
                  << " Events=" << engine.storage().count("events") << "\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "FATAL: " << e.what() << "\n";
        return 1;
    }
}

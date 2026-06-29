// Market AI Lab — engine entry point.
//
// Runs the offline paper loop and persists everything to the shared SQLite DB.
// Usage: mal_engine --config <yaml> --db <path> --schema <sql> [--iterations N]
//                   [--bridge host:port]
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

        auto cfg = mal::config::load_config(cfg_path);

        mal::core::EngineOptions opts;
        opts.db_path = db_path;
        opts.schema_path = schema;
        if (!bridge.empty()) {
            auto colon = bridge.find(':');
            opts.bridge_host = bridge.substr(0, colon);
            opts.bridge_port =
                colon == std::string::npos ? 8765
                                           : std::atoi(bridge.c_str() + colon + 1);
            opts.use_bridge = true;
        }

        std::cout << "Market AI Lab engine starting (live DISABLED by default)\n"
                  << "  config: " << cfg_path << "\n"
                  << "  db:     " << db_path << "\n"
                  << "  iters:  " << iterations << "\n"
                  << "  bridge: " << (opts.use_bridge ? bridge : "off (mock)")
                  << "\n";

        mal::core::Engine engine(std::move(cfg), opts);
        engine.run(iterations);

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

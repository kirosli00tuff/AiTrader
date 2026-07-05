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

        // --- Startup transparency block (Task 10) ---------------------------
        // One honest snapshot of what is actually active this run.
        {
            const auto& st = cfg.strategy;
            const auto& co = cfg.council;
            const auto& rk = cfg.risk;
            std::string wl;
            for (size_t i = 0; i < st.whitelist.size(); ++i)
                wl += (i ? ", " : "") + st.whitelist[i];
            std::string strategies;
            if (st.momentum_enabled) strategies += "momentum ";
            if (st.reversion_enabled) strategies += "reversion ";
            if (strategies.empty()) strategies = "(none) ";
            std::cout
                << "  ----------------------------------------------------\n"
                << "  council:   "
                << (opts.bootstrap_sim ? "N/A (bootstrap-sim legacy loop)"
                    : opts.use_bridge  ? "entries-only, gated (real via bridge)"
                                       : "entries-only, gated (in-process mock)")
                << "\n"
                << "  strategies: " << strategies
                << (st.crypto_allow_short ? "[crypto short ON]" : "[long-only]")
                << "\n"
                << "  regime:    ADX>=" << st.regime_adx_trend
                << " trending / rvol>=" << st.regime_rvol_high << " range-bound\n"
                << "  whitelist: " << wl << "  (bars " << st.bar_timeframe << ")\n"
                << "  whale:     tracking "
                << (cfg.whale.whale_tracking_enabled ? "on" : "off")
                << ", live feeds default OFF (free-first)\n"
                << "  exits:     ATR stop x" << st.atr_stop_mult << " / target x"
                << st.atr_target_mult << " / time-stop " << st.time_stop_bars
                << " bars (native, no council)\n"
                << "  council $:  budget " << co.council_daily_budget
                << "/day, cooldown " << co.per_symbol_council_cooldown_minutes
                << "m, max_tokens " << co.council_max_tokens << "\n"
                << "  cost cuts: risk pre-check ON; equities market-hours-only "
                << (cfg.engine.equities_market_hours_only ? "ON" : "off")
                << " (crypto 24/7)\n"
                << "  rl:        "
                << (cfg.rl.rl_enabled ? "ON" : "OFF (ships off)")
                << " — advisory cap 0.5, real-fills gate "
                << cfg.rl.rl_min_real_fills
                << ", trains on real fills only\n"
                << "  L1 risk:   daily-loss " << (rk.max_daily_loss_total_pct * 100)
                << "% / per-trade " << (rk.max_trade_risk_pct_of_equity * 100)
                << "% / max " << rk.max_trades_per_day << " trades/day / "
                << rk.max_open_positions_total << " open / cooldown "
                << rk.cooldown_minutes_after_loss_breach << "m\n"
                << "  live:      DISABLED (gated, off by default)\n"
                << "  ----------------------------------------------------\n";
        }

        // Capture the RL gate before the config is moved into the engine so the
        // startup can report the live fill count vs the gate when RL is ON.
        const bool rl_on = cfg.rl.rl_enabled;
        const int rl_gate = cfg.rl.rl_min_real_fills;

        mal::core::Engine engine(std::move(cfg), opts);

        if (rl_on) {
            long long fills = engine.storage().count_closed_trades();
            std::cout << "  rl fills:  " << fills << " / " << rl_gate
                      << (fills >= rl_gate ? " (gate met — challenger training "
                                             "allowed; promotion still manual)"
                                           : " (below gate — trainer refuses)")
                      << "\n";
        }

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

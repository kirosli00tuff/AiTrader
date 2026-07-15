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

#include <cerrno>
#include <fcntl.h>
#include <netdb.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>

#include "config/config.hpp"
#include "core/engine.hpp"
#include "core/layer_toggles.hpp"

namespace {
std::string arg_value(int argc, char** argv, const std::string& flag,
                      const std::string& def) {
    for (int i = 1; i + 1 < argc; ++i)
        if (flag == argv[i]) return argv[i + 1];
    return def;
}

// Best-effort TCP reachability probe for the local IB Gateway. Non-blocking
// connect with a short timeout. It never throws and returns false on any error.
// It opens no data channel and places no order. It only reports whether the
// Gateway socket accepts a connection. IBKR live stays gated off regardless.
bool ibkr_gateway_reachable(const std::string& host, int port, int timeout_ms) {
    struct addrinfo hints {};
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    struct addrinfo* res = nullptr;
    const std::string port_s = std::to_string(port);
    if (getaddrinfo(host.c_str(), port_s.c_str(), &hints, &res) != 0 || !res)
        return false;
    bool ok = false;
    for (struct addrinfo* ai = res; ai && !ok; ai = ai->ai_next) {
        int fd = ::socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (fd < 0) continue;
        int flags = ::fcntl(fd, F_GETFL, 0);
        ::fcntl(fd, F_SETFL, flags | O_NONBLOCK);
        int rc = ::connect(fd, ai->ai_addr, ai->ai_addrlen);
        if (rc == 0) {
            ok = true;
        } else if (errno == EINPROGRESS) {
            fd_set wset;
            FD_ZERO(&wset);
            FD_SET(fd, &wset);
            struct timeval tv;
            tv.tv_sec = timeout_ms / 1000;
            tv.tv_usec = (timeout_ms % 1000) * 1000;
            if (::select(fd + 1, nullptr, &wset, nullptr, &tv) > 0) {
                int err = 0;
                socklen_t len = sizeof(err);
                if (::getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len) == 0 &&
                    err == 0)
                    ok = true;
            }
        }
        ::close(fd);
    }
    freeaddrinfo(res);
    return ok;
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
        // Offline feed/clock overrides (empty => config). These only change how
        // the OFFLINE loop is driven; Alpaca stays paper + market-data only.
        std::string feed_mode = arg_value(argc, argv, "--feed-mode", "");
        std::string clock_mode = arg_value(argc, argv, "--clock-mode", "");

        auto cfg = mal::config::load_config(cfg_path);

        mal::core::EngineOptions opts;
        opts.db_path = db_path;
        opts.schema_path = schema;
        opts.continuous = continuous;
        opts.interval_seconds = interval_seconds;
        opts.data_source = data_source;
        opts.bootstrap_sim = bootstrap_sim;
        opts.native_bar_seconds = native_bar_seconds;
        opts.feed_mode = feed_mode;
        opts.clock_mode = clock_mode;
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
        std::string eff_feed =
            !feed_mode.empty() ? feed_mode : cfg.simulation.feed_mode;
        std::string eff_clock =
            !clock_mode.empty() ? clock_mode : cfg.simulation.clock_mode;

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
            const char* cdenv = std::getenv("MAL_CONTROL_DIR");
            std::string ctl_dir = (cdenv && *cdenv) ? std::string(cdenv)
                : (cfg.system.control_dir.empty() ? std::string(".control")
                                                  : cfg.system.control_dir);
            const auto lt =
                mal::core::read_layer_toggles(ctl_dir + "/controls.json");
            // Query the bridge for the true real-vs-mock availability of each
            // advisory service, so the proof block shows the actual state, not
            // just the configured intent. Non-fatal: if the bridge is down the
            // strict-mode check (verify_real_layers_reachable) reports it.
            std::string st_models, st_gate, st_cdetail, st_ddetail, st_wdetail;
            bool st_bridge_up = false, st_council_real = false,
                 st_dnn_real = false, st_whale_real = false, st_sec = false;
            if (opts.use_bridge) {
                auto s = mal::bridge::http_post_json(
                    opts.bridge_host, opts.bridge_port, "/status", "{}",
                    cfg.council.engine_bridge_call_timeout_ms);
                if (s) {
                    st_bridge_up = true;
                    st_models = mal::bridge::json_get_string(*s, "council_models", "");
                    st_gate = mal::bridge::json_get_string(*s, "council_gate", "");
                    st_cdetail = mal::bridge::json_get_string(*s, "council_detail", "");
                    st_ddetail = mal::bridge::json_get_string(*s, "dnn_detail", "");
                    st_wdetail = mal::bridge::json_get_string(*s, "whale_detail", "");
                    st_council_real = mal::bridge::json_get_bool(*s, "council_real", false);
                    st_dnn_real = mal::bridge::json_get_bool(*s, "dnn_real", false);
                    st_whale_real = mal::bridge::json_get_bool(*s, "whale_real", false);
                    st_sec = mal::bridge::json_get_bool(*s, "sec_edgar", false);
                }
            }
            auto svc_state = [&](bool enabled, bool real, bool avail) -> std::string {
                if (!enabled) return "off";
                if (!real) return "on-mock (by choice)";
                if (!opts.use_bridge) return "on-real but NO --bridge (mock)";
                if (!st_bridge_up) return "on-real but bridge DOWN";
                return avail ? "on-real (available)" : "on-real but UNAVAILABLE";
            };
            const auto& rk = cfg.risk;
            std::string wl;
            for (size_t i = 0; i < st.whitelist.size(); ++i)
                wl += (i ? ", " : "") + st.whitelist[i];
            std::string strategies;
            if (st.momentum_enabled) strategies += "momentum ";
            if (st.reversion_enabled) strategies += "reversion ";
            if (strategies.empty()) strategies = "(none) ";
            // IBKR is the live-only venue. Probe the local IB Gateway only when
            // the operator opted in (connection_enabled). Reachable or not, live
            // stays disabled behind the approval gate. An unreachable Gateway is
            // logged and the engine continues in Alpaca/offline mode.
            const auto& ib = cfg.ibkr;
            const std::string ib_addr =
                ib.gateway_host + ":" + std::to_string(ib.gateway_port);
            std::string ibkr_status;
            if (ib.connection_enabled) {
                const bool up =
                    ibkr_gateway_reachable(ib.gateway_host, ib.gateway_port, 800);
                ibkr_status = std::string("IB Gateway ") +
                              (up ? "REACHABLE" : "UNREACHABLE") + " at " + ib_addr +
                              (up ? "" : " (continuing in Alpaca/offline mode)") +
                              ", live-only, DISABLED behind approval gate";
            } else {
                ibkr_status = "connection check off (set ibkr.connection_enabled="
                              "true to probe " + ib_addr + "), live-only, DISABLED"
                              " behind approval gate";
            }
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
                << " trending / rvol>=" << st.regime_rvol_high << " range-bound"
                << " (leads: trending->momentum, range->reversion, neutral->blend)\n"
                << "  profile:   " << st.profile << "  (reversion=" << st.reversion_style
                << ", dual-MA momentum=" << (st.momentum_dual_ma_filter ? "on" : "off")
                << ")\n"
                << "  rsi-2:     period " << st.rsi2_period << " entry crypto<"
                << static_cast<int>(st.rsi2_entry_crypto) << " equity<"
                << static_cast<int>(st.rsi2_entry_equity) << " exit>"
                << static_cast<int>(st.rsi2_exit) << " trendMA " << st.trend_ma_period
                << " crossback " << (st.rsi2_crossback_confirm ? "on" : "off")
                << (st.reversion_style == "rsi2" ? "  [ACTIVE]" : "  [idle: bollinger]")
                << "\n"
                << "  feed:      " << eff_feed << " / clock " << eff_clock
                << (eff_feed == "alpaca_paper"
                        ? " (PRIMARY online paper loop)"
                    : eff_feed == "replay"
                        ? " (Alpaca = paper + market-data only, no live path)"
                        : "")
                << "\n"
                << "  alpaca:    PAPER + market-data ONLY, no live path"
                << (eff_feed == "alpaca_paper"
                        ? " (ONLINE loop active: real Alpaca bars, paper orders to"
                          " Alpaca paper)"
                        : " (offline feed this run)")
                << "\n"
                << "  ibkr:      " << ibkr_status << "\n"
                << "  levels:    L1 safety on-real (ALWAYS) / L2 council "
                << mal::core::layer_state(lt.council, lt.council_real)
                << " / L3 dnn "
                << mal::core::layer_state(lt.dnn_advisory, lt.dnn_advisory_real)
                << " / L4 whale "
                << mal::core::layer_state(lt.whale, lt.whale_real)
                << " / adaptive " << (lt.adaptive ? "on" : "off")
                << "  [controls.json]\n"
                << "  L2 council: "
                << svc_state(lt.council, lt.council_real, st_council_real)
                << " [" << (st_models.empty()
                        ? "gpt-5.5,claude-opus-4-8,gemini-3.1-pro-preview"
                        : st_models)
                << "] gate " << (st_gate.empty() ? "claude-haiku-4-5" : st_gate)
                << (st_cdetail.empty() ? "" : " — " + st_cdetail) << "\n"
                << "  L3 dnn:    "
                << svc_state(lt.dnn_advisory, lt.dnn_advisory_real, st_dnn_real)
                << (st_ddetail.empty() ? "" : " — " + st_ddetail) << "\n"
                << "  L4 whale:  "
                << svc_state(lt.whale, lt.whale_real, st_whale_real)
                << ", SEC EDGAR "
                << (st_sec ? "ON (active free feed)" : "off (env opt-in)")
                << (st_wdetail.empty() ? "" : " — " + st_wdetail) << "\n"
                << "  thresholds: adx_min " << st.adx_min << " ema " << st.ema_fast
                << "/" << st.ema_slow << " atr_floor " << st.atr_vol_floor
                << " bb " << st.bb_period << "/" << st.bb_std << "sd rsi "
                << st.rsi_period << " [" << st.rsi_oversold << "-"
                << st.rsi_overbought << "] vol_x " << st.vol_multiple << "\n"
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
                << "  tiers:     fast tier when notional<="
                << (co.fast_tier_max_notional_pct * 100) << "% equity AND strength<="
                << co.fast_tier_max_conviction
                << " (else council); 0/0 => council-eligible (swing)\n"
                << "  spend cap: $" << co.council_daily_spend_ceiling_usd
                << "/day, $" << co.council_monthly_spend_ceiling_usd
                << "/month @ ~$" << co.council_est_cost_per_call_usd
                << "/call (0=off, forces fast tier when reached)\n"
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

        // RL fill count vs the gate, always shown (RL ships off; it activates
        // only past the real-fills gate, and promotion stays manual).
        {
            long long fills = engine.storage().count_closed_trades();
            std::cout << "  rl fills:  " << fills << " / " << rl_gate
                      << (fills >= rl_gate ? " (gate met — challenger training "
                                             "allowed; promotion still manual)"
                                           : " (below gate — trainer refuses)")
                      << (rl_on ? " [rl_enabled ON]" : " [rl_enabled OFF, ships off]")
                      << "\n"
                      << "  kill sw:   ARMED"
                      << (engine.kill_switch_tripped() ? " (TRIPPED)" : "")
                      << " (latching, manual resume required)\n"
                      << "  ----------------------------------------------------\n";
        }

        // Per-symbol indicator warm-state (Task 1): confirm the backfill warmed
        // the native indicators. On the real paper path a cold symbol waits (the
        // warm-state gate) and never fires an entry on partial data.
        {
            std::cout << "  warm-start: native indicators seeded from the bars "
                         "table (backfill first for a live entry)\n";
            for (const auto& ws : engine.warm_states()) {
                const auto& s = ws.state;
                auto f = [](bool b) { return b ? '+' : '-'; };
                std::cout << "    " << ws.symbol << ": " << s.bars << " bars -> "
                          << (s.all ? "WARM" : "COLD") << "  [ema100" << f(s.ema_slow)
                          << " adx" << f(s.adx) << " atr" << f(s.atr) << " bb"
                          << f(s.bollinger) << " rsi" << f(s.rsi) << " vol"
                          << f(s.volume) << " rvol" << f(s.rvol) << "]\n";
            }
            std::cout << "  feed/clock: " << eff_feed << " / " << eff_clock
                      << " (runtime-switchable via controls.json + GUI; a switch "
                         "away from alpaca_paper with an open position is blocked)\n"
                      << "  ----------------------------------------------------\n";
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

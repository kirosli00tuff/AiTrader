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
#include "core/adaptive_controls.hpp"
#include "core/layer_toggles.hpp"
#include "core/profile_controls.hpp"

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
    // --help / -h print usage and EXIT before anything else runs. This used to
    // fall through into the 20-iteration demo against the real database, which
    // wrote spurious events into market_ai_lab.db and confused a live trace.
    // Checked before any config load, schema init, or DB open, so asking for
    // help touches nothing.
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--help" || a == "-h") {
            std::cout
                << "mal_engine - Market AI Lab trading engine (paper by "
                   "default, live gated off)\n\n"
                   "Usage: mal_engine [options]\n\n"
                   "Options:\n"
                   "  --help, -h                 print this usage and exit\n"
                   "  --config PATH              config file (default "
                   "config/default_config.yaml)\n"
                   "  --db PATH                  SQLite database. WITHOUT "
                   "this flag a scratch\n"
                   "                             mal_demo.db is used, so a "
                   "stray run can never\n"
                   "                             write into the production "
                   "database\n"
                   "  --schema PATH              schema file (default "
                   "storage/schema.sql)\n"
                   "  --iterations N             finite demo iterations "
                   "(default 20)\n"
                   "  --continuous               run the continuous paper "
                   "loop\n"
                   "  --interval-seconds N       continuous loop interval\n"
                   "  --bridge HOST:PORT         Python advisory bridge "
                   "(off when absent)\n"
                   "  --data-source NAME         market data source "
                   "override\n"
                   "  --feed-mode MODE           alpaca_paper | "
                   "synthetic_regimes | replay | flat_random_walk\n"
                   "  --clock-mode MODE          real | simulated\n"
                   "  --native-bar-seconds N     bar bucket size (default "
                   "300)\n"
                   "  --bootstrap-sim            legacy demo factor loop\n\n"
                   "WITHOUT --help this binary RUNS the engine (a finite "
                   "demo unless --continuous). Without --db it writes to a "
                   "scratch mal_demo.db, never the production database.\n";
            return 0;
        }
    }
    try {
        std::string cfg_path =
            arg_value(argc, argv, "--config", "config/default_config.yaml");
        // No --db means a SCRATCH demo database, never the production one.
        // Every real launcher (scripts/start_paper_trading.sh, the GUI
        // supervisor via api_server/stack.engine_cmd) passes --db explicitly.
        // A bare `mal_engine` used to default to market_ai_lab.db and wrote
        // warn events into the production diagnostic log (five
        // discovery_blocked warnings on 2026-07-17 came from exactly such
        // strays). Touching production now requires ASKING for it.
        std::string db_path = arg_value(argc, argv, "--db", "");
        const bool db_defaulted = db_path.empty();
        if (db_defaulted) db_path = "mal_demo.db";
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
        // Entry-decision recording is ON by default (recording only, never
        // decisive). The flag exists for cost measurement and the guard test.
        bool no_entry_recording = arg_flag(argc, argv, "--no-entry-recording");

        // THE PROFILE'S RUNTIME LEVER (2026-07-23). Resolve the strategy
        // profile through the control-file precedence path: load config once
        // to learn the control dir, read the flat strategy_profile key, and
        // when a valid override exists reload with it applied so the
        // active_quant overlay keys off the RESOLVED profile. Startup-only:
        // the profile is never re-read mid-run, so an unreadable file can
        // never switch a running strategy (see core/profile_controls.hpp and
        // CONTEXT.md for the fallback decision). The banner below prints the
        // resolved profile WITH its source.
        auto cfg = mal::config::load_config(cfg_path);
        std::string profile_source = "config";
        {
            const char* cdenv = std::getenv("MAL_CONTROL_DIR");
            const std::string cdir = (cdenv && *cdenv)
                ? std::string(cdenv)
                : (cfg.system.control_dir.empty() ? std::string(".control")
                                                  : cfg.system.control_dir);
            const std::string ov = mal::core::resolve_profile_override(
                cdir + "/controls.json");
            if (!ov.empty() && ov != cfg.strategy.profile) {
                cfg = mal::config::load_config(cfg_path, ov);
                profile_source = "control file";
            } else if (!ov.empty()) {
                profile_source = "control file (matches config)";
            }
        }

        mal::core::EngineOptions opts;
        opts.db_path = db_path;
        opts.schema_path = schema;
        opts.continuous = continuous;
        opts.interval_seconds = interval_seconds;
        opts.data_source = data_source;
        opts.bootstrap_sim = bootstrap_sim;
        opts.record_entry_decisions = !no_entry_recording;
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

        int eff_interval =
            interval_seconds > 0 ? interval_seconds
                                 : cfg.engine.loop_interval_seconds;
        std::string eff_feed =
            !feed_mode.empty() ? feed_mode : cfg.simulation.feed_mode;
        // THE effective source, from the one resolver the Engine uses. This
        // line printed the CONFIG value and skipped the alpaca_paper override,
        // so a real-path run under `market_data.source: mock` announced
        // "source: mock" and then wrote "source=alpaca" into its own event log.
        std::string source = mal::market_data::resolve_source(
            data_source, cfg.market_data.source, eff_feed);
        std::string eff_clock =
            !clock_mode.empty() ? clock_mode : cfg.simulation.clock_mode;

        std::cout << "Market AI Lab engine starting (live DISABLED by default)\n"
                  << "  config: " << cfg_path << "\n"
                  << "  db:     " << db_path
                  << (db_defaulted
                          ? "  (SCRATCH demo db: no --db given; launchers pass"
                            " --db explicitly)"
                          : "")
                  << "\n"
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
            // The adaptive layer's RUNTIME state, from the same control file the
            // engine consumes each iteration. Read here so the banner reports
            // what is actually running rather than what config launched with.
            const auto adaptive_rt = mal::core::read_adaptive_controls(
                ctl_dir + "/controls.json", cfg.adaptive_realtime);
            // Discovery's RUNTIME state, same control file, same reason. The
            // banner read cfg.discovery.discovery_enabled and so printed
            // "DISABLED (opt-in)" while the operator had discovery ON and the
            // Python funnel agreed it was on. The startup block is where an
            // operator checks what is running, so it must not report the shipped
            // default as the truth.
            const auto discovery_rt = mal::core::read_discovery_controls(
                ctl_dir + "/controls.json", cfg.discovery);
            // The sleeve's RUNTIME state, same control file, same reason as
            // discovery above: the banner read the config default and printed
            // "OFF (opt-in)" while the operator had the sleeve toggled ON.
            const auto sleeve_rt = mal::core::read_sleeve_controls(
                ctl_dir + "/controls.json", cfg.sleeves);
            // Query the bridge for the true real-vs-mock availability of each
            // advisory service, so the proof block shows the actual state, not
            // just the configured intent. Non-fatal: if the bridge is down the
            // strict-mode check (verify_real_layers_reachable) reports it.
            std::string st_models, st_gate, st_cdetail, st_ddetail, st_wdetail;
            bool st_bridge_up = false, st_council_real = false,
                 st_dnn_real = false, st_whale_real = false, st_sec = false,
                 st_whale_alert = false;
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
                    st_whale_alert = mal::bridge::json_get_bool(*s, "whale_alert", false);
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
                << "  profile:   " << st.profile << " [" << profile_source
                << "]  (reversion=" << st.reversion_style
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
                << ", Whale Alert "
                << (st_whale_alert ? "ON (crypto trial)" : "off (opt-in)")
                << (st_wdetail.empty() ? "" : " — " + st_wdetail) << "\n"
                << "  thresholds: adx_min " << st.adx_min << " ema " << st.ema_fast
                << "/" << st.ema_slow << " atr_floor " << st.atr_vol_floor
                << " bb " << st.bb_period << "/" << st.bb_std << "sd rsi "
                << st.rsi_period << " [" << st.rsi_oversold << "-"
                << st.rsi_overbought << "] vol_x " << st.vol_multiple << "\n"
                << "  whitelist: " << wl << "  (bars " << st.bar_timeframe << ")"
                // The banner prints the CONFIGURED whitelist. With discovery on,
                // the engine also merges the active watchlist into the traded
                // universe at construction (after this line prints), and logs
                // the result as a discovery_watchlist event. Say so rather than
                // let this read as the full traded universe.
                << (discovery_rt.enabled
                        ? "  [+ active watchlist symbols, see discovery_onboard "
                          "events]"
                        : "")
                << "\n"
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
                << "  sleeves:   quant_core " << (cfg.sleeves.quant_core_target_pct * 100)
                << "% / research_satellite " << (cfg.sleeves.research_satellite_target_pct * 100)
                << "% (band " << (cfg.sleeves.drift_band_pct * 100) << "%), satellite "
                << (sleeve_rt.research_satellite ? "ON [controls.json]"
                                                 : "OFF (opt-in)")
                << ", hard cap "
                << ((cfg.sleeves.research_satellite_target_pct + cfg.sleeves.drift_band_pct) * 100)
                << "% of equity\n"
                << "  research:  " << cfg.sleeves.research_passes_per_day
                << " passes/day, budget " << cfg.sleeves.research_daily_budget
                << " calls/day, conviction>=" << cfg.sleeves.research_conviction_threshold
                << ", combined ceiling $" << cfg.sleeves.combined_monthly_spend_ceiling_usd
                << "/month (pauses both sleeves)\n"
                << "  discovery: " << (discovery_rt.enabled
                                           ? "ENABLED [controls.json]"
                                           : "DISABLED (opt-in)")
                << ", long-term sleeve "
                << (cfg.discovery.long_term_sleeve_enabled
                        ? "ENABLED"
                        : "DISABLED (opt-in)")
                << "\n"
                << "  universe:  crypto " << cfg.discovery.crypto_universe.size()
                << " -> top " << cfg.discovery.crypto_active_max
                << " by liquidity/volume (daily refresh), equity "
                << cfg.discovery.equity_universe.size()
                << " curated (stable)\n"
                << "  funnel:    A free pre-screen -> "
                << cfg.discovery.max_finalists
                << " finalists (0 tokens) | B haiku gate -> "
                << cfg.discovery.max_survivors
                << " survivors | C four-level -> <= "
                << cfg.discovery.max_council_calls_per_pass << " council calls\n"
                << "  disc $:    budget "
                << cfg.discovery.discovery_daily_council_budget
                << " calls/day @ ~$"
                << cfg.discovery.discovery_est_cost_per_call_usd
                << "/call (SEPARATE from + additive to the trading budget); "
                << "watchlist max " << cfg.discovery.watchlist_max_size
                << ", stale " << cfg.discovery.watchlist_stale_hours << "h\n"
                // Adaptive real-time layer. Three independent flags, all off by
                // default. The line about aggressive entry prints
                // unconditionally and on purpose: the operator should be able to
                // read the guarantee off the startup block without opening a doc.
                // RUNTIME state, not the config state. The operator turns
                // these on in the GUI, which writes controls.json, so a banner
                // reading cfg here would print DISABLED while the layer was
                // actually running: the same config-versus-controls trap that
                // made the toggle itself cosmetic.
                << "  adaptive:  news feed "
                << (adaptive_rt.news_feed_enabled ? "ENABLED"
                                                  : "DISABLED (opt-in)")
                << ", watchlist shaping "
                << (adaptive_rt.watchlist_shaping_enabled
                        ? "ENABLED"
                        : "DISABLED (opt-in)")
                << ", defensive react "
                << (adaptive_rt.react_defensive_enabled ? "ENABLED"
                                                        : "DISABLED (opt-in)")
                << (adaptive_rt == mal::core::AdaptiveRuntime{}
                        ? "" : "  [controls.json]")
                << "\n"
                << "  adapt $:   poll "
                << cfg.adaptive_realtime.poll_interval_seconds
                << "s (free tier), budget "
                << cfg.adaptive_realtime.adaptive_daily_llm_budget
                << " reads/day @ ~$"
                << cfg.adaptive_realtime.adaptive_est_cost_per_call_usd
                << "/read (SEPARATE from + additive to the discovery AND trading "
                << "budgets); the free filter drops the rest\n"
                << "  react:     a live event may TRIM, EXIT, or FLAG only. "
                << "Aggressive entry has no event path: it always routes through "
                << "the discovery funnel + RiskGate. Stale actions (>"
                << adaptive_rt.action_max_age_seconds
                << "s) refused\n"
                << "  cost cuts: risk pre-check ON; equities market-hours-only "
                << (cfg.engine.equities_market_hours_only ? "ON" : "off")
                << " (no equity entry outside US RTH, exits exempt, crypto 24/7)\n"
                << "  global:    equity rotation "
                << (cfg.regional.global_equity_rotation_enabled
                        ? "ENABLED"
                        : "DISABLED (scaffold)")
                << "; open session now "
                << mal::config::region_name(mal::config::open_session(
                       std::time(nullptr), cfg.regional))
                << "\n"
                << "  equities:  NY "
                << (mal::config::venue_available_for(mal::config::Region::NY,
                                                     cfg.regional)
                        ? "tradeable via Alpaca"
                        : "venue-unavailable")
                << ", London "
                << (mal::config::venue_available_for(mal::config::Region::London,
                                                     cfg.regional)
                        ? "tradeable"
                        : "venue-unavailable")
                << ", Asia "
                << (mal::config::venue_available_for(mal::config::Region::Asia,
                                                     cfg.regional)
                        ? "tradeable"
                        : "venue-unavailable")
                << " (only reachable regions trade; crypto 24/7 unaffected)\n"
                << "  rl:        "
                << (cfg.rl.rl_enabled ? "ON" : "OFF (ships off)")
                << " — advisory only (factor weight 0.0 until enabled), "
                   "real-fills gate "
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
                // A symbol with no real bar history is NOT warm, however many
                // bars it holds. Reported as its own word so the banner can
                // never tell the operator a symbol is ready that the entry
                // path has already ruled out.
                std::cout << "    " << ws.symbol << ": " << s.bars << " bars -> "
                          << (!ws.tradeable ? "UNSERVICEABLE"
                                            : (s.all ? "WARM" : "COLD"))
                          << "  [ema100" << f(s.ema_slow)
                          << " adx" << f(s.adx) << " atr" << f(s.atr) << " bb"
                          << f(s.bollinger) << " rsi" << f(s.rsi) << " vol"
                          << f(s.volume) << " rvol" << f(s.rvol) << "]"
                          << (ws.tradeable ? ""
                                           : "  <- no real bar history, held "
                                             "out of the tradeable universe")
                          << "\n";
            }
            // THE universe, resolved once: verified core union verified
            // periphery. Printed from the engine's own resolution point, so
            // the banner states what the engine will actually trade rather
            // than the configured list it was handed.
            {
                const auto uni = engine.universe_report();
                std::string syms;
                for (const auto& s : uni.symbols)
                    syms += (syms.empty() ? "" : ", ") + s;
                std::cout << "  universe:  " << uni.symbols.size()
                          << " tradeable"
                          << (uni.enforced ? "" : " (offline mode: the "
                                                  "real-path invariant does "
                                                  "not apply)")
                          << (syms.empty() ? "" : "  " + syms) << "\n";
                if (!uni.unserviceable.empty()) {
                    std::string bad;
                    for (const auto& s : uni.unserviceable)
                        bad += (bad.empty() ? "" : ", ") + s;
                    std::cout << "             UNSERVICEABLE: " << bad
                              << "  (declared but never served real data; "
                                 "contained per-symbol, never a stack stop)\n";
                }
                if (uni.degraded) {
                    std::cout << "  ** UNIVERSE EMPTY OR NEARLY EMPTY: the "
                                 "engine has nothing it may trade. Nothing is "
                                 "fabricated and nothing is stopped. Fix the "
                                 "core or the data credentials. **\n";
                }
            }
            // Unmanageable open positions, the same LOUD startup shape as the
            // degraded universe: named, explained, and never silently dropped.
            {
                const auto& um = engine.unmanageable_positions();
                if (!um.empty()) {
                    std::cout << "  ** UNMANAGEABLE OPEN POSITIONS: "
                              << um.size() << " **\n";
                    for (const auto& p : um)
                        std::cout << "     " << p.symbol << " (" << p.venue
                                  << ", " << p.sleeve << ", opened "
                                  << p.opened_ts << ", qty "
                                  << p.qty << "): " << p.reason << "\n";
                    std::cout << "     Held out of exit management, never "
                                 "silently dropped or auto-closed. Reconcile "
                                 "through the journalled event path.\n";
                }
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

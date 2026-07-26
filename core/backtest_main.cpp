// mal_backtest — provenance-respecting backtest harness (2026-07-24).
//
// THE STRATEGY IS CALLED, NEVER REIMPLEMENTED. Every decision comes from the
// same compiled functions the live engine links: strategy::evaluate (with its
// EvalTrace), strategy::check_exit, strategy::exit_fill_price,
// strategy::rsi2_exit_triggered, strategy::indicators_warm, and
// risk::RiskGate::evaluate. The harness owns only the ORCHESTRATION the
// engine cannot lend without restructuring: the bar walk, the pessimistic
// fill model, and portfolio bookkeeping. The three-line sizing formula is
// replicated from Engine::handle_bar_close and labelled as such; per-trade
// RETURN metrics are independent of it.
//
// FILLS AND COSTS, pessimistic by default: entries fill at the NEXT bar open
// (never the signal bar close). Exits fill through the engine's own
// exit_fill_price (stop/target price, else close). Fee 0.0001 per side, the
// value measured from all 77 real recorded fills. No further slippage is
// modelled, stated plainly. Intrabar ambiguity (a bar spanning both stop and
// target) resolves as the STOP through check_exit's own risk-first order, and
// every ambiguous bar is counted.
//
// PROVENANCE: only real_feed/backfill bars, quarantined rows excluded
// (Storage::real_bars_in_range). LOOKAHEAD: history is a rolling window of
// the engine's own cap (300) built strictly from bars at or before the
// decision bar; a test corrupts future bars and asserts decisions unchanged.
//
// SCOPE, stated as a limit: native strategy + deterministic gates only. The
// RiskGate runs BY IDENTITY with quality fields set to pass (the engine's
// own risk pre-check shape), because the advisory ensemble's live values
// (whale) were never recorded for historical bars and a replayed council
// would carry hindsight. Council-tier behavior is NOT backtested here.
//
// Output: JSON lines (decision / trade / calib / summary) for
// backtest/report.py, which owns every statistic, interval, and refusal.
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include <sqlite3.h>

#include "config/config.hpp"
#include "core/util.hpp"
#include "risk/risk_gate.hpp"
#include "signal_engine/strategy.hpp"
#include "storage/storage.hpp"

using namespace mal;

namespace {

constexpr size_t kHistoryCap = 300;  // the engine's own kBarHistoryCap
constexpr double kFeeRate = 0.0001;  // measured from all 77 real fills

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

std::vector<std::string> split_csv(const std::string& s) {
    std::vector<std::string> out;
    std::stringstream ss(s);
    std::string item;
    while (std::getline(ss, item, ','))
        if (!item.empty()) out.push_back(item);
    return out;
}

bool is_crypto_symbol(const std::string& s) {
    return s.find('/') != std::string::npos;
}

std::string jesc(const std::string& s) { return util::json_escape(s); }

struct OpenPos {
    strategy::OpenPosition pos;
    std::string entry_ts;
    double entry_fee = 0.0;
    double atr_z_at_entry = 0.0;
    double signal_close = 0.0;  // the signal bar close (fill-gap reporting)
    std::string regime;         // regime at the signal bar (research emission)
};

struct Book {
    double equity;
    double start_of_day_equity;
    std::string day;
    double realized_today = 0.0;
    int consecutive_losses = 0;
    // Harness bookkeeping approximating AccountManager's loss cooldown: when
    // the consecutive-loss cap is reached, the counter resets after
    // cooldown_minutes_after_loss_breach of BAR time, as the live venue
    // state does. Without this a third loss froze the whole tape forever
    // (459 of 459 gate blocks in the first calibration run read
    // max_consecutive_losses), which is not what the live engine does.
    long cooldown_until_epoch = 0;
    std::map<std::string, OpenPos> open;  // symbol -> position
};

void rebuild_pstate(const Book& b, risk::PortfolioState& ps) {
    ps = risk::PortfolioState{};
    ps.equity = b.equity;
    ps.start_of_day_equity = b.start_of_day_equity;
    ps.realized_pnl_today_total = b.realized_today;
    ps.realized_pnl_today_per_venue["alpaca"] = b.realized_today;
    ps.consecutive_losses = b.consecutive_losses;
    for (const auto& [sym, op] : b.open) {
        double notional = op.pos.entry_price * op.pos.qty;
        ++ps.open_positions_total;
        ++ps.open_positions_per_venue["alpaca"];
        ps.exposure_per_symbol[sym] += notional;
        ps.exposure_per_market[op.pos.market] += notional;
        ps.exposure_per_category[op.pos.category] += notional;
        ps.open_risk_total +=
            std::abs(op.pos.entry_price - op.pos.stop_price) * op.pos.qty;
    }
}

}  // namespace

int main(int argc, char** argv) {
    const std::string db_path = arg_value(argc, argv, "--db", "");
    if (db_path.empty()) {
        std::cerr << "mal_backtest --db PATH [--config PATH] "
                     "[--profile swing|active_quant] [--symbols CSV] "
                     "[--start ISO] [--end ISO] [--mode backtest|calibrate] "
                     "[--out FILE] [--set-rsi2-entry-equity N] "
                     "[--set-atr-band-std X] [--strip-volume] "
                     "[--emit-rejections] [--hold-tape]\n";
        return 2;
    }
    const std::string cfg_path =
        arg_value(argc, argv, "--config", "config/default_config.yaml");
    const std::string profile = arg_value(argc, argv, "--profile", "");
    const std::string mode = arg_value(argc, argv, "--mode", "backtest");
    const std::string start = arg_value(argc, argv, "--start", "");
    const std::string end = arg_value(argc, argv, "--end", "");
    const std::string out_path = arg_value(argc, argv, "--out", "");
    const bool strip_volume = arg_flag(argc, argv, "--strip-volume");
    const bool emit_rejections = arg_flag(argc, argv, "--emit-rejections");
    // --hold-tape keeps the pre-streaming in-memory tape (1.13 GB on the
    // deep-history DB). It exists so the streaming path's output identity
    // stays testable. Streaming is the default.
    const bool hold_tape = arg_flag(argc, argv, "--hold-tape");

    config::Config cfg = config::load_config(cfg_path, profile);
    // Registered parameter levers ONLY (P24 pre-registration): each mutates
    // config exactly as an operator could, and the SAME compiled strategy
    // reads it. No code-path variant exists here.
    {
        const std::string v1 =
            arg_value(argc, argv, "--set-rsi2-entry-equity", "");
        if (!v1.empty()) cfg.strategy.rsi2_entry_equity = std::stod(v1);
        const std::string v2 = arg_value(argc, argv, "--set-atr-band-std", "");
        if (!v2.empty()) cfg.strategy.atr_band_std = std::stod(v2);
    }

    std::vector<std::string> symbols =
        split_csv(arg_value(argc, argv, "--symbols", ""));
    if (symbols.empty()) symbols = cfg.strategy.whitelist;

    std::ofstream out_file;
    std::ostream* out = &std::cout;
    if (!out_path.empty()) {
        out_file.open(out_path, std::ios::trunc);
        out = &out_file;
    }

    storage::Storage store(db_path);
    risk::RiskGate gate(cfg.risk);  // THE RiskGate, by identity

    // ---- Source identity: every report names the database it read --------
    // A deep-history analysis DB carries an analysis_meta table (feed,
    // adjustment, bias note); production has none. Emitting it here makes a
    // deep-history result impossible to confuse with a production result.
    *out << "{\"t\":\"meta\",\"db\":\"" << jesc(db_path) << "\"";
    {
        sqlite3* meta_db = nullptr;
        if (sqlite3_open_v2(db_path.c_str(), &meta_db, SQLITE_OPEN_READONLY,
                            nullptr) == SQLITE_OK) {
            sqlite3_stmt* st = nullptr;
            if (sqlite3_prepare_v2(meta_db,
                                   "SELECT key, value FROM analysis_meta",
                                   -1, &st, nullptr) == SQLITE_OK) {
                while (sqlite3_step(st) == SQLITE_ROW) {
                    const auto* k = sqlite3_column_text(st, 0);
                    const auto* v = sqlite3_column_text(st, 1);
                    if (k && v)
                        *out << ",\"" << jesc(reinterpret_cast<const char*>(k))
                             << "\":\""
                             << jesc(reinterpret_cast<const char*>(v)) << "\"";
                }
            }
            sqlite3_finalize(st);
        }
        sqlite3_close(meta_db);
    }
    *out << "}\n";

    // ---- Tape source (2026-07-25): STREAM monthly windows by default, or
    // hold the whole tape with --hold-tape. Both paths read through
    // Storage::real_bars_in_range BY IDENTITY, so the provenance filter
    // cannot drift between them. Both use the same DEFINED order,
    // (timestamp, symbol). The old comparator sorted on timestamp alone and
    // left equal stamps in std::sort's unspecified order, which no
    // streaming merge can replicate. The held tape measured 1.13 GB RSS on
    // the deep-history DB and a 14-way sweep of it OOM-killed the live
    // stack on 2026-07-25. Streaming holds one month at a time.
    auto bar_order = [](const storage::BarRow& a, const storage::BarRow& b) {
        if (a.timestamp != b.timestamp) return a.timestamp < b.timestamp;
        return a.symbol < b.symbol;
    };
    std::map<std::string, long> usable;
    for (const auto& sym : symbols) usable[sym] = 0;
    auto for_each_bar = [&](auto&& fn) {
        const std::string& tf = cfg.strategy.bar_timeframe;
        if (hold_tape) {
            std::vector<storage::BarRow> tape;
            for (const auto& sym : symbols) {
                auto rows = store.real_bars_in_range(sym, tf, start, end);
                for (auto& r : rows) tape.push_back(std::move(r));
            }
            std::sort(tape.begin(), tape.end(), bar_order);
            for (const auto& r : tape) {
                ++usable[r.symbol];
                fn(r);
            }
            return;
        }
        // Window bounds from the DB's own span (bounds only, read-only),
        // clamped to --start/--end. Windows outside the data are empty.
        std::string lo, hi;
        {
            sqlite3* bdb = nullptr;
            if (sqlite3_open_v2(db_path.c_str(), &bdb, SQLITE_OPEN_READONLY,
                                nullptr) == SQLITE_OK) {
                sqlite3_stmt* st = nullptr;
                if (sqlite3_prepare_v2(
                        bdb, "SELECT MIN(timestamp), MAX(timestamp) FROM bars",
                        -1, &st, nullptr) == SQLITE_OK &&
                    sqlite3_step(st) == SQLITE_ROW) {
                    const auto* a = sqlite3_column_text(st, 0);
                    const auto* b = sqlite3_column_text(st, 1);
                    if (a) lo = reinterpret_cast<const char*>(a);
                    if (b) hi = reinterpret_cast<const char*>(b);
                }
                sqlite3_finalize(st);
            }
            sqlite3_close(bdb);
        }
        if (!start.empty() && (lo.empty() || start > lo)) lo = start;
        if (!end.empty() && (hi.empty() || end < hi)) hi = end;
        if (lo.empty() || hi.empty() || lo > hi) return;  // no bars
        int y = std::stoi(lo.substr(0, 4));
        int m = lo.size() >= 7 ? std::stoi(lo.substr(5, 2)) : 1;
        std::string wstart = lo;      // inclusive lower edge of this window
        std::string prev_bound;       // rows at or before this are processed
        std::vector<storage::BarRow> window;
        while (wstart <= hi) {
            const int ny = m == 12 ? y + 1 : y;
            const int nm = m == 12 ? 1 : m + 1;
            char ub[32];
            std::snprintf(ub, sizeof ub, "%04d-%02d-01T00:00:00Z", ny, nm);
            const std::string wend = std::string(ub) < hi ? ub : hi;
            window.clear();
            for (const auto& sym : symbols) {
                auto rows = store.real_bars_in_range(sym, tf, wstart, wend);
                for (auto& r : rows) {
                    // The window edges are inclusive on both sides, so a bar
                    // exactly at the previous bound was already processed.
                    if (!prev_bound.empty() && r.timestamp <= prev_bound)
                        continue;
                    window.push_back(std::move(r));
                }
            }
            std::sort(window.begin(), window.end(), bar_order);
            for (const auto& r : window) {
                ++usable[r.symbol];
                fn(r);
            }
            if (wend == hi) break;
            prev_bound = wend;
            wstart = wend;
            y = ny;
            m = nm;
        }
    };

    // ---- Calibrate mode: replay each recorded decision's bar --------------
    if (mode == "calibrate") {
        // Rebuild the rolling history bar by bar from the provenance-clean
        // tape and ask the SAME strategy at every warm bar; report.py joins
        // these against the recorded decisions by (symbol, ts).
        std::map<std::string, std::vector<strategy::Bar>> hist;
        auto calib_step = [&](const storage::BarRow& r) {
            auto& h = hist[r.symbol];
            h.push_back({r.open, r.high, r.low, r.close, r.volume});
            if (h.size() > kHistoryCap) h.erase(h.begin());
            if (!strategy::indicators_warm(static_cast<int>(h.size()),
                                           cfg.strategy))
                return;
            strategy::EvalTrace tr;
            auto d = strategy::evaluate(h, cfg.strategy,
                                        is_crypto_symbol(r.symbol), &tr);
            *out << "{\"t\":\"calib\",\"ts\":\"" << jesc(r.timestamp)
                 << "\",\"symbol\":\"" << jesc(r.symbol)
                 << "\",\"has_signal\":" << (d.signal.has_signal ? 1 : 0)
                 << ",\"factor\":\"" << jesc(d.signal.factor)
                 << "\",\"first_reject\":\"" << jesc(tr.first_reject)
                 << "\",\"regime\":\"" << jesc(tr.regime)
                 << "\",\"stop\":" << d.signal.stop_price
                 << ",\"target\":" << d.signal.target_price
                 << ",\"strength\":" << d.signal.strength << "}\n";
        };
        for_each_bar(calib_step);
        for (const auto& [sym, n] : usable)
            *out << "{\"t\":\"bars\",\"symbol\":\"" << jesc(sym)
                 << "\",\"usable\":" << n << "}\n";
        *out << "{\"t\":\"summary\",\"mode\":\"calibrate\"}\n";
        return 0;
    }

    // ---- Backtest mode ----------------------------------------------------
    std::map<std::string, std::vector<strategy::Bar>> hist;
    std::map<std::string, std::optional<strategy::StrategySignal>> pending;
    std::map<std::string, double> pending_atr_z;
    std::map<std::string, double> pending_close;
    std::map<std::string, std::string> pending_regime;
    Book book{cfg.system.starting_paper_balance,
              cfg.system.starting_paper_balance, "", 0.0, 0, 0, {}};
    risk::PortfolioState ps;
    long trades = 0, ambiguous = 0, gate_blocks = 0;

    auto step = [&](const storage::BarRow& r) {
        const std::string& sym = r.symbol;
        const bool crypto = is_crypto_symbol(sym);
        const std::string day =
            r.timestamp.size() >= 10 ? r.timestamp.substr(0, 10) : r.timestamp;
        if (book.day != day) {
            book.day = day;
            book.start_of_day_equity = book.equity;
            book.realized_today = 0.0;
        }
        const long bar_epoch = util::iso8601_to_epoch(r.timestamp);
        if (book.cooldown_until_epoch > 0 &&
            bar_epoch >= book.cooldown_until_epoch) {
            book.consecutive_losses = 0;
            book.cooldown_until_epoch = 0;
        }
        strategy::Bar bar{r.open, r.high, r.low, r.close,
                          strip_volume ? 0.0 : r.volume};

        // 1. FILL a pending entry at THIS bar's open (the next bar after the
        // signal), pessimistic by construction.
        if (auto& p = pending[sym]; p.has_value()) {
            const auto& sig = *p;
            double fill_px = bar.open;
            // Sizing: replicated from Engine::handle_bar_close (three lines,
            // labelled glue). Per-trade returns do not depend on it.
            double base = cfg.sizing.default_risk_per_trade_pct * book.equity;
            double scale = std::min(std::clamp(sig.strength, 0.0, 1.0),
                                    cfg.sizing.default_position_scale_cap);
            double notional = base * std::max(scale, 0.2);
            double qty = notional / std::max(0.0001, fill_px);

            risk::OrderProposal o;
            o.venue = "alpaca";
            o.symbol = sym;
            o.market = sym;
            o.category = crypto ? "crypto" : "equity";
            o.side = sig.direction == strategy::Direction::Long ? "buy"
                                                                : "sell";
            o.qty = qty;
            o.price = fill_px;
            o.notional = notional;
            // Quality fields set to PASS: the engine's own risk pre-check
            // shape. The advisory confidence for historical bars was never
            // recorded, so only the HARD limits are exercised (see scope).
            o.confidence = 1.0;
            o.edge = 1.0;
            o.model_agreement_count = cfg.risk.required_model_agreement_count;
            rebuild_pstate(book, ps);
            auto dec = gate.evaluate(o, ps);  // BY IDENTITY
            if (!dec.allowed) {
                ++gate_blocks;
                *out << "{\"t\":\"gate_block\",\"ts\":\"" << jesc(r.timestamp)
                     << "\",\"symbol\":\"" << jesc(sym) << "\",\"reason\":\""
                     << jesc(dec.reason) << "\"}\n";
            } else {
                OpenPos op;
                op.pos.venue = "alpaca";
                op.pos.symbol = sym;
                op.pos.market = sym;
                op.pos.category = o.category;
                op.pos.factor = sig.factor;
                op.pos.opened_ts = r.timestamp;
                op.pos.direction = sig.direction;
                op.pos.entry_price = fill_px;
                op.pos.qty = qty;
                op.pos.stop_price = sig.stop_price;
                op.pos.target_price = sig.target_price;
                op.pos.time_stop_bars = sig.time_stop_bars;
                op.pos.bars_held = 0;
                op.entry_ts = r.timestamp;
                op.entry_fee = notional * kFeeRate;
                op.atr_z_at_entry = pending_atr_z[sym];
                op.signal_close = pending_close[sym];
                op.regime = pending_regime[sym];
                book.open[sym] = op;
            }
            p.reset();
        }

        // 2. EXIT management on the closed bar, the engine's own predicates.
        auto it = book.open.find(sym);
        auto& h = hist[sym];
        if (it != book.open.end()) {
            auto& op = it->second;
            ++op.pos.bars_held;
            bool ind_exit =
                cfg.strategy.reversion_style == "rsi2" &&
                op.pos.factor == "reversion" &&
                strategy::rsi2_exit_triggered(h, cfg.strategy);
            auto reason = strategy::check_exit(op.pos, bar, ind_exit);
            const bool ambi =
                op.pos.direction == strategy::Direction::Long
                    ? (bar.low <= op.pos.stop_price &&
                       bar.high >= op.pos.target_price)
                    : (bar.high >= op.pos.stop_price &&
                       bar.low <= op.pos.target_price);
            if (reason != strategy::ExitReason::None) {
                double exit_px =
                    strategy::exit_fill_price(op.pos, reason, bar);
                double fee = exit_px * op.pos.qty * kFeeRate + op.entry_fee;
                double pnl = strategy::realized_pnl(op.pos, exit_px) - fee;
                double ret = op.pos.entry_price > 0
                                 ? (op.pos.direction ==
                                            strategy::Direction::Long
                                        ? (exit_px / op.pos.entry_price - 1.0)
                                        : (op.pos.entry_price / exit_px - 1.0))
                                 : 0.0;
                ret -= 2 * kFeeRate;  // per-side fees in return terms
                book.equity += pnl;
                book.realized_today += pnl;
                book.consecutive_losses =
                    pnl >= 0 ? 0 : book.consecutive_losses + 1;
                if (book.consecutive_losses >=
                        cfg.risk.max_consecutive_losses &&
                    book.cooldown_until_epoch == 0)
                    book.cooldown_until_epoch =
                        bar_epoch +
                        cfg.risk.cooldown_minutes_after_loss_breach * 60L;
                if (ambi) ++ambiguous;
                ++trades;
                *out << "{\"t\":\"trade\",\"symbol\":\"" << jesc(sym)
                     << "\",\"factor\":\"" << jesc(op.pos.factor)
                     << "\",\"category\":\"" << jesc(op.pos.category)
                     << "\",\"entry_ts\":\"" << jesc(op.entry_ts)
                     << "\",\"exit_ts\":\"" << jesc(r.timestamp)
                     << "\",\"entry_px\":" << op.pos.entry_price
                     << ",\"exit_px\":" << exit_px << ",\"reason\":\""
                     << jesc(strategy::exit_reason_to_string(reason))
                     << "\",\"ret\":" << ret << ",\"pnl\":" << pnl
                     << ",\"bars_held\":" << op.pos.bars_held
                     << ",\"ambiguous\":" << (ambi ? 1 : 0)
                     << ",\"atr_z_at_entry\":" << op.atr_z_at_entry
                     << ",\"fill_gap\":"
                     << (op.signal_close > 0
                             ? (op.pos.entry_price / op.signal_close - 1.0)
                             : 0.0)
                     << ",\"equity\":" << book.equity
                     << ",\"regime\":\"" << jesc(op.regime)
                     << "\",\"stop\":" << op.pos.stop_price
                     << ",\"target\":" << op.pos.target_price << "}\n";
                book.open.erase(it);
            }
        }

        // 3. HISTORY, then ENTRY evaluation on the closed bar (the engine's
        // own order: history updated, warm gate, evaluate).
        h.push_back(bar);
        if (h.size() > kHistoryCap) h.erase(h.begin());
        if (!strategy::indicators_warm(static_cast<int>(h.size()),
                                       cfg.strategy))
            return;
        if (book.open.count(sym)) return;     // one position per symbol
        if (pending[sym].has_value()) return;

        strategy::EvalTrace tr;
        auto d = strategy::evaluate(h, cfg.strategy, crypto, &tr);  // IDENTITY
        if (d.signal.has_signal) {
            pending[sym] = d.signal;
            pending_atr_z[sym] = tr.atr_z;
            pending_close[sym] = bar.close;
            pending_regime[sym] = tr.regime;
            *out << "{\"t\":\"signal\",\"ts\":\"" << jesc(r.timestamp)
                 << "\",\"symbol\":\"" << jesc(sym) << "\",\"factor\":\""
                 << jesc(d.signal.factor) << "\",\"regime\":\""
                 << jesc(tr.regime) << "\",\"atr_z\":" << tr.atr_z << "}\n";
        } else if (emit_rejections) {
            // Research emission (2026-07-25, additive): the FULL per-family
            // condition sets the trace already records, so each gate's
            // marginal rejected set (all other conditions pass) is
            // identifiable offline. Recording only, never decisive.
            *out << "{\"t\":\"reject\",\"ts\":\"" << jesc(r.timestamp)
                 << "\",\"symbol\":\"" << jesc(sym)
                 << "\",\"first_reject\":\"" << jesc(tr.first_reject)
                 << "\",\"atr_z\":" << tr.atr_z << ",\"rsi2\":" << tr.rsi2
                 << ",\"vol_ok\":" << (tr.vol_ok ? 1 : 0)
                 << ",\"regime\":\"" << jesc(tr.regime)
                 << "\",\"mom_reject\":\"" << jesc(tr.momentum_first_reject)
                 << "\",\"rev_reject\":\"" << jesc(tr.reversion_first_reject)
                 << "\",\"trend_ok\":" << (tr.trend_ok ? 1 : 0)
                 << ",\"rsi2_trigger\":" << (tr.rsi2_trigger ? 1 : 0)
                 << ",\"atr_band_ok\":" << (tr.atr_band_ok ? 1 : 0)
                 << ",\"volume_present\":" << (tr.volume_present ? 1 : 0)
                 << ",\"cross_up\":" << (tr.cross_up ? 1 : 0)
                 << ",\"cross_down\":" << (tr.cross_down ? 1 : 0)
                 << ",\"adx_ok\":" << (tr.adx_ok ? 1 : 0)
                 << ",\"atr_floor_ok\":" << (tr.atr_floor_ok ? 1 : 0)
                 << ",\"dual_ma_ok\":" << (tr.dual_ma_ok ? 1 : 0)
                 << ",\"atr_v\":" << tr.atr_v
                 << ",\"close\":" << bar.close << "}\n";
        }
    };
    for_each_bar(step);
    for (const auto& [sym, n] : usable)
        *out << "{\"t\":\"bars\",\"symbol\":\"" << jesc(sym)
             << "\",\"usable\":" << n << "}\n";

    *out << "{\"t\":\"summary\",\"mode\":\"backtest\",\"trades\":" << trades
         << ",\"ambiguous\":" << ambiguous
         << ",\"gate_blocks\":" << gate_blocks
         << ",\"equity_end\":" << book.equity
         << ",\"open_at_end\":" << book.open.size() << "}\n";
    return 0;
}

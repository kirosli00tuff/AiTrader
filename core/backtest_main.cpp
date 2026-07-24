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
                     "[--emit-rejections]\n";
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

    // ---- Load the provenance-clean tape, merged chronologically ----------
    std::vector<storage::BarRow> tape;
    std::map<std::string, int> usable;
    for (const auto& sym : symbols) {
        auto rows = store.real_bars_in_range(sym, cfg.strategy.bar_timeframe,
                                             start, end);
        usable[sym] = static_cast<int>(rows.size());
        for (auto& r : rows) tape.push_back(std::move(r));
    }
    std::sort(tape.begin(), tape.end(),
              [](const storage::BarRow& a, const storage::BarRow& b) {
                  return a.timestamp < b.timestamp;
              });
    for (const auto& [sym, n] : usable)
        *out << "{\"t\":\"bars\",\"symbol\":\"" << jesc(sym)
             << "\",\"usable\":" << n << "}\n";

    // ---- Calibrate mode: replay each recorded decision's bar --------------
    if (mode == "calibrate") {
        // Rebuild the rolling history bar by bar from the provenance-clean
        // tape and ask the SAME strategy at every warm bar; report.py joins
        // these against the recorded decisions by (symbol, ts).
        std::map<std::string, std::vector<strategy::Bar>> hist;
        for (const auto& r : tape) {
            auto& h = hist[r.symbol];
            h.push_back({r.open, r.high, r.low, r.close, r.volume});
            if (h.size() > kHistoryCap) h.erase(h.begin());
            if (!strategy::indicators_warm(static_cast<int>(h.size()),
                                           cfg.strategy))
                continue;
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
        }
        *out << "{\"t\":\"summary\",\"mode\":\"calibrate\"}\n";
        return 0;
    }

    // ---- Backtest mode ----------------------------------------------------
    std::map<std::string, std::vector<strategy::Bar>> hist;
    std::map<std::string, std::optional<strategy::StrategySignal>> pending;
    std::map<std::string, double> pending_atr_z;
    std::map<std::string, double> pending_close;
    Book book{cfg.system.starting_paper_balance,
              cfg.system.starting_paper_balance, "", 0.0, 0, {}};
    risk::PortfolioState ps;
    long trades = 0, ambiguous = 0, gate_blocks = 0;

    for (const auto& r : tape) {
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
                     << ",\"equity\":" << book.equity << "}\n";
                book.open.erase(it);
            }
        }

        // 3. HISTORY, then ENTRY evaluation on the closed bar (the engine's
        // own order: history updated, warm gate, evaluate).
        h.push_back(bar);
        if (h.size() > kHistoryCap) h.erase(h.begin());
        if (!strategy::indicators_warm(static_cast<int>(h.size()),
                                       cfg.strategy))
            continue;
        if (book.open.count(sym)) continue;   // one position per symbol
        if (pending[sym].has_value()) continue;

        strategy::EvalTrace tr;
        auto d = strategy::evaluate(h, cfg.strategy, crypto, &tr);  // IDENTITY
        if (d.signal.has_signal) {
            pending[sym] = d.signal;
            pending_atr_z[sym] = tr.atr_z;
            pending_close[sym] = bar.close;
            *out << "{\"t\":\"signal\",\"ts\":\"" << jesc(r.timestamp)
                 << "\",\"symbol\":\"" << jesc(sym) << "\",\"factor\":\""
                 << jesc(d.signal.factor) << "\",\"regime\":\""
                 << jesc(tr.regime) << "\",\"atr_z\":" << tr.atr_z << "}\n";
        } else if (emit_rejections) {
            *out << "{\"t\":\"reject\",\"ts\":\"" << jesc(r.timestamp)
                 << "\",\"symbol\":\"" << jesc(sym)
                 << "\",\"first_reject\":\"" << jesc(tr.first_reject)
                 << "\",\"atr_z\":" << tr.atr_z << ",\"rsi2\":" << tr.rsi2
                 << ",\"vol_ok\":" << (tr.vol_ok ? 1 : 0) << "}\n";
        }
    }

    *out << "{\"t\":\"summary\",\"mode\":\"backtest\",\"trades\":" << trades
         << ",\"ambiguous\":" << ambiguous
         << ",\"gate_blocks\":" << gate_blocks
         << ",\"equity_end\":" << book.equity
         << ",\"open_at_end\":" << book.open.size() << "}\n";
    return 0;
}

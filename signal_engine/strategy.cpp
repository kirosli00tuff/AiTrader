#include "signal_engine/strategy.hpp"

#include <algorithm>
#include <cmath>

namespace mal::strategy {

std::optional<Bar> BarAggregator::add(const std::string& key, long epoch_seconds,
                                      double price, double volume) {
    auto it = state_.find(key);
    // bucket_seconds_ <= 0 is a testability mode: every tick is its own bucket,
    // so each add() closes the prior bar (lets the native path be exercised fast).
    long bucket = bucket_seconds_ > 0
                      ? epoch_seconds / bucket_seconds_
                      : (it == state_.end() ? 0 : it->second.bucket + 1);
    if (it == state_.end()) {
        Partial p;
        p.bucket = bucket;
        p.bar = Bar{price, price, price, price, volume};
        state_.emplace(key, p);
        return std::nullopt;
    }
    Partial& p = it->second;
    if (bucket == p.bucket) {
        p.bar.high = std::max(p.bar.high, price);
        p.bar.low = std::min(p.bar.low, price);
        p.bar.close = price;
        p.bar.volume += volume;
        return std::nullopt;
    }
    if (bucket < p.bucket) return std::nullopt;  // ignore out-of-order stale tick
    // New bucket: the previous partial bar is now closed.
    Bar closed = p.bar;
    p.bucket = bucket;
    p.bar = Bar{price, price, price, price, volume};
    return closed;
}

std::string regime_to_string(Regime r) {
    switch (r) {
        case Regime::Trending: return "trending";
        case Regime::RangeBound: return "range_bound";
        case Regime::Neutral: return "neutral";
    }
    return "neutral";
}

Regime regime_from_string(const std::string& s) {
    if (s == "trending") return Regime::Trending;
    if (s == "range_bound") return Regime::RangeBound;
    return Regime::Neutral;
}

std::string direction_to_string(Direction d) {
    switch (d) {
        case Direction::Long: return "long";
        case Direction::Short: return "short";
        case Direction::None: return "none";
    }
    return "none";
}

std::vector<double> closes_of(const std::vector<Bar>& bars) {
    std::vector<double> c;
    c.reserve(bars.size());
    for (const auto& b : bars) c.push_back(b.close);
    return c;
}

std::vector<double> ema_series(const std::vector<double>& xs, int period) {
    std::vector<double> out;
    if (xs.empty() || period < 1) return out;
    out.resize(xs.size());
    const double k = 2.0 / (period + 1.0);
    out[0] = xs[0];
    for (size_t i = 1; i < xs.size(); ++i)
        out[i] = (xs[i] - out[i - 1]) * k + out[i - 1];
    return out;
}

double ema(const std::vector<double>& xs, int period) {
    auto s = ema_series(xs, period);
    return s.empty() ? 0.0 : s.back();
}

double sma(const std::vector<double>& xs, int period) {
    if (period < 1 || static_cast<int>(xs.size()) < period) return 0.0;
    double sum = 0.0;
    for (size_t i = xs.size() - period; i < xs.size(); ++i) sum += xs[i];
    return sum / period;
}

std::vector<double> rsi_series(const std::vector<double>& closes, int period) {
    std::vector<double> out(closes.size(), 0.0);
    if (period < 1 || static_cast<int>(closes.size()) <= period) return out;
    // Wilder's smoothing.
    double gain = 0.0, loss = 0.0;
    for (int i = 1; i <= period; ++i) {
        double ch = closes[i] - closes[i - 1];
        if (ch >= 0) gain += ch; else loss -= ch;
    }
    double avg_gain = gain / period;
    double avg_loss = loss / period;
    auto rsi_from = [](double ag, double al) {
        if (al == 0.0) return ag == 0.0 ? 50.0 : 100.0;
        double rs = ag / al;
        return 100.0 - 100.0 / (1.0 + rs);
    };
    out[period] = rsi_from(avg_gain, avg_loss);
    for (size_t i = period + 1; i < closes.size(); ++i) {
        double ch = closes[i] - closes[i - 1];
        double g = ch > 0 ? ch : 0.0;
        double l = ch < 0 ? -ch : 0.0;
        avg_gain = (avg_gain * (period - 1) + g) / period;
        avg_loss = (avg_loss * (period - 1) + l) / period;
        out[i] = rsi_from(avg_gain, avg_loss);
    }
    return out;
}

double rsi(const std::vector<double>& closes, int period) {
    auto s = rsi_series(closes, period);
    return s.empty() ? 0.0 : s.back();
}

double atr(const std::vector<Bar>& bars, int period) {
    if (period < 1 || static_cast<int>(bars.size()) <= period) return 0.0;
    std::vector<double> tr;
    tr.reserve(bars.size());
    for (size_t i = 1; i < bars.size(); ++i) {
        double h = bars[i].high, l = bars[i].low, pc = bars[i - 1].close;
        tr.push_back(std::max({h - l, std::fabs(h - pc), std::fabs(l - pc)}));
    }
    double atr_v = 0.0;
    for (int i = 0; i < period; ++i) atr_v += tr[i];
    atr_v /= period;
    for (size_t i = period; i < tr.size(); ++i)
        atr_v = (atr_v * (period - 1) + tr[i]) / period;
    return atr_v;
}

double adx(const std::vector<Bar>& bars, int period) {
    int n = static_cast<int>(bars.size());
    if (period < 1 || n < 2 * period + 1) return 0.0;
    std::vector<double> plus_dm, minus_dm, tr;
    for (int i = 1; i < n; ++i) {
        double up = bars[i].high - bars[i - 1].high;
        double down = bars[i - 1].low - bars[i].low;
        plus_dm.push_back((up > down && up > 0) ? up : 0.0);
        minus_dm.push_back((down > up && down > 0) ? down : 0.0);
        double h = bars[i].high, l = bars[i].low, pc = bars[i - 1].close;
        tr.push_back(std::max({h - l, std::fabs(h - pc), std::fabs(l - pc)}));
    }
    // Wilder running sums seeded over the first `period` values.
    auto wilder = [&](const std::vector<double>& v) {
        std::vector<double> s(v.size(), 0.0);
        double sum = 0.0;
        for (int i = 0; i < period; ++i) sum += v[i];
        s[period - 1] = sum;
        for (size_t i = period; i < v.size(); ++i)
            s[i] = s[i - 1] - s[i - 1] / period + v[i];
        return s;
    };
    auto s_tr = wilder(tr);
    auto s_pdm = wilder(plus_dm);
    auto s_mdm = wilder(minus_dm);
    std::vector<double> dx;
    for (size_t i = period - 1; i < tr.size(); ++i) {
        double str = s_tr[i];
        if (str == 0.0) { dx.push_back(0.0); continue; }
        double pdi = 100.0 * s_pdm[i] / str;
        double mdi = 100.0 * s_mdm[i] / str;
        double denom = pdi + mdi;
        dx.push_back(denom == 0.0 ? 0.0 : 100.0 * std::fabs(pdi - mdi) / denom);
    }
    if (dx.empty()) return 0.0;
    if (static_cast<int>(dx.size()) < period) {
        double m = 0.0;
        for (double d : dx) m += d;
        return m / dx.size();
    }
    double adx_v = 0.0;
    for (int i = 0; i < period; ++i) adx_v += dx[i];
    adx_v /= period;
    for (size_t i = period; i < dx.size(); ++i)
        adx_v = (adx_v * (period - 1) + dx[i]) / period;
    return adx_v;
}

double realized_vol(const std::vector<double>& closes, int lookback) {
    int n = static_cast<int>(closes.size());
    if (lookback < 2 || n < lookback + 1) return 0.0;
    std::vector<double> rets;
    for (int i = n - lookback; i < n; ++i) {
        double prev = closes[i - 1];
        if (prev != 0.0) rets.push_back((closes[i] - prev) / prev);
    }
    if (rets.size() < 2) return 0.0;
    double mean = 0.0;
    for (double r : rets) mean += r;
    mean /= rets.size();
    double var = 0.0;
    for (double r : rets) var += (r - mean) * (r - mean);
    var /= (rets.size() - 1);
    return std::sqrt(var);
}

double avg_volume(const std::vector<Bar>& bars, int lookback) {
    int n = static_cast<int>(bars.size());
    if (lookback < 1 || n < lookback) return 0.0;
    double sum = 0.0;
    for (int i = n - lookback; i < n; ++i) sum += bars[i].volume;
    return sum / lookback;
}

Bollinger bollinger(const std::vector<double>& closes, int period,
                    double num_std) {
    Bollinger b;
    int n = static_cast<int>(closes.size());
    if (period < 1 || n < period) return b;
    double mean = 0.0;
    for (int i = n - period; i < n; ++i) mean += closes[i];
    mean /= period;
    double var = 0.0;
    for (int i = n - period; i < n; ++i) var += (closes[i] - mean) * (closes[i] - mean);
    var /= period;  // population stdev (standard for Bollinger bands)
    b.sd = std::sqrt(var);
    b.mid = mean;
    b.upper = mean + num_std * b.sd;
    b.lower = mean - num_std * b.sd;
    return b;
}

int min_bars_to_warm(const config::StrategyConfig& cfg) {
    int need = cfg.ema_slow + 2;                     // momentum EMA cross
    need = std::max(need, 2 * cfg.atr_period + 1);   // ADX (Wilder smoothing)
    need = std::max(need, cfg.atr_period + 1);       // ATR
    need = std::max(need, cfg.bb_period);            // Bollinger bands
    need = std::max(need, cfg.rsi_period + 2);       // RSI (reversion reads n-2)
    need = std::max(need, cfg.vol_lookback);         // average volume
    need = std::max(need, cfg.vol_lookback + 1);     // realized vol
    return need;
}

WarmState indicator_warm_state(int bar_count, const config::StrategyConfig& cfg) {
    WarmState w;
    w.bars = bar_count;
    w.ema_slow = bar_count >= cfg.ema_slow + 2;
    w.adx = bar_count >= 2 * cfg.atr_period + 1;
    w.atr = bar_count >= cfg.atr_period + 1;
    w.bollinger = bar_count >= cfg.bb_period;
    w.rsi = bar_count >= cfg.rsi_period + 2;
    w.volume = bar_count >= cfg.vol_lookback;
    w.rvol = bar_count >= cfg.vol_lookback + 1;
    w.all = w.ema_slow && w.adx && w.atr && w.bollinger && w.rsi && w.volume &&
            w.rvol;
    return w;
}

bool indicators_warm(int bar_count, const config::StrategyConfig& cfg) {
    return bar_count >= min_bars_to_warm(cfg);
}

RegimeResult detect_regime(const std::vector<Bar>& bars,
                           const config::StrategyConfig& cfg) {
    RegimeResult r;
    // ADX uses the ATR/Wilder period (14 by default — the standard ADX window).
    r.adx = adx(bars, cfg.atr_period);
    r.rvol = realized_vol(closes_of(bars), cfg.vol_lookback);
    if (r.adx >= cfg.regime_adx_trend) {
        r.regime = Regime::Trending;        // strong directional movement
    } else if (r.rvol >= cfg.regime_rvol_high) {
        r.regime = Regime::RangeBound;      // choppy: weak trend, elevated vol
    } else {
        r.regime = Regime::Neutral;
    }
    return r;
}

StrategySignal evaluate_momentum(const std::vector<Bar>& bars,
                                 const config::StrategyConfig& cfg,
                                 bool allow_short) {
    StrategySignal sig;
    sig.factor = "momentum";
    if (static_cast<int>(bars.size()) < cfg.ema_slow + 2) return sig;
    auto closes = closes_of(bars);
    auto ef = ema_series(closes, cfg.ema_fast);
    auto es = ema_series(closes, cfg.ema_slow);
    size_t n = closes.size();
    bool cross_up = ef[n - 2] <= es[n - 2] && ef[n - 1] > es[n - 1];
    bool cross_down = ef[n - 2] >= es[n - 2] && ef[n - 1] < es[n - 1];
    double adx_v = adx(bars, cfg.atr_period);
    double atr_v = atr(bars, cfg.atr_period);
    double price = closes[n - 1];
    bool adx_ok = adx_v >= cfg.adx_min;
    bool vol_ok = price > 0 && (atr_v / price) >= cfg.atr_vol_floor;
    if (!adx_ok || !vol_ok) return sig;
    Direction dir = Direction::None;
    if (cross_up) dir = Direction::Long;
    else if (cross_down && allow_short) dir = Direction::Short;
    if (dir == Direction::None) return sig;
    sig.has_signal = true;
    sig.direction = dir;
    sig.entry_price = price;
    double adx_span = std::max(1.0, 50.0 - cfg.adx_min);
    sig.strength = std::clamp((adx_v - cfg.adx_min) / adx_span, 0.0, 1.0);
    sig.time_stop_bars = cfg.time_stop_bars;
    if (dir == Direction::Long) {
        sig.stop_price = price - cfg.atr_stop_mult * atr_v;
        sig.target_price = price + cfg.atr_target_mult * atr_v;
    } else {
        sig.stop_price = price + cfg.atr_stop_mult * atr_v;
        sig.target_price = price - cfg.atr_target_mult * atr_v;
    }
    sig.rationale = "EMA" + std::to_string(cfg.ema_fast) + "/" +
                    std::to_string(cfg.ema_slow) + " cross, ADX " +
                    std::to_string(static_cast<int>(adx_v));
    return sig;
}

StrategySignal evaluate_reversion(const std::vector<Bar>& bars,
                                  const config::StrategyConfig& cfg,
                                  bool allow_short) {
    StrategySignal sig;
    sig.factor = "reversion";
    int need = std::max({cfg.bb_period, cfg.rsi_period + 2, cfg.vol_lookback,
                         cfg.atr_period + 1}) + 2;
    if (static_cast<int>(bars.size()) < need) return sig;
    auto closes = closes_of(bars);
    size_t n = closes.size();
    Bollinger bb = bollinger(closes, cfg.bb_period, cfg.bb_std);
    auto rs = rsi_series(closes, cfg.rsi_period);
    double rsi_now = rs[n - 1], rsi_prev = rs[n - 2];
    double price = closes[n - 1], prev_price = closes[n - 2];
    double vavg = avg_volume(bars, cfg.vol_lookback);
    bool vol_ok = vavg > 0 && bars[n - 1].volume > cfg.vol_multiple * vavg;
    double atr_v = atr(bars, cfg.atr_period);
    // Long reentry: prior bar stretched below the lower band, now back inside,
    // RSI leaving oversold. Short reentry is the mirror at the upper band.
    bool long_reentry = prev_price < bb.lower && price >= bb.lower &&
                        rsi_prev <= cfg.rsi_oversold && rsi_now > cfg.rsi_oversold;
    bool short_reentry = prev_price > bb.upper && price <= bb.upper &&
                         rsi_prev >= cfg.rsi_overbought &&
                         rsi_now < cfg.rsi_overbought;
    Direction dir = Direction::None;
    if (long_reentry && vol_ok) dir = Direction::Long;
    else if (short_reentry && vol_ok && allow_short) dir = Direction::Short;
    if (dir == Direction::None) return sig;
    sig.has_signal = true;
    sig.direction = dir;
    sig.entry_price = price;
    double stretch = bb.sd > 0 ? std::fabs(prev_price - bb.mid) / bb.sd : 0.0;
    sig.strength = std::clamp((stretch - cfg.bb_std) / std::max(1e-9, cfg.bb_std),
                              0.0, 1.0);
    sig.time_stop_bars = cfg.time_stop_bars;
    // Target is the mean (the reversion thesis); stop is an ATR beyond entry.
    sig.target_price = bb.mid;
    if (dir == Direction::Long)
        sig.stop_price = price - cfg.atr_stop_mult * atr_v;
    else
        sig.stop_price = price + cfg.atr_stop_mult * atr_v;
    sig.rationale = "BB reentry, RSI " + std::to_string(static_cast<int>(rsi_now));
    return sig;
}

std::string exit_reason_to_string(ExitReason r) {
    switch (r) {
        case ExitReason::Stop: return "stop";
        case ExitReason::Target: return "target";
        case ExitReason::TimeStop: return "time_stop";
        case ExitReason::None: return "none";
    }
    return "none";
}

ExitReason check_exit(const OpenPosition& pos, const Bar& latest_bar) {
    if (pos.direction == Direction::Long) {
        if (latest_bar.low <= pos.stop_price) return ExitReason::Stop;
        if (latest_bar.high >= pos.target_price) return ExitReason::Target;
    } else if (pos.direction == Direction::Short) {
        if (latest_bar.high >= pos.stop_price) return ExitReason::Stop;
        if (latest_bar.low <= pos.target_price) return ExitReason::Target;
    }
    if (pos.time_stop_bars > 0 && pos.bars_held >= pos.time_stop_bars)
        return ExitReason::TimeStop;
    return ExitReason::None;
}

double exit_fill_price(const OpenPosition& pos, ExitReason reason,
                       const Bar& latest_bar) {
    switch (reason) {
        case ExitReason::Stop: return pos.stop_price;
        case ExitReason::Target: return pos.target_price;
        case ExitReason::TimeStop:
        case ExitReason::None: return latest_bar.close;
    }
    return latest_bar.close;
}

double realized_pnl(const OpenPosition& pos, double exit_price) {
    double dir = pos.direction == Direction::Short ? -1.0 : 1.0;
    return dir * (exit_price - pos.entry_price) * pos.qty;
}

BlendedDecision evaluate(const std::vector<Bar>& bars,
                         const config::StrategyConfig& cfg, bool is_crypto) {
    BlendedDecision d;
    d.regime = detect_regime(bars, cfg);
    bool allow_short = is_crypto && cfg.crypto_allow_short;
    switch (d.regime.regime) {
        case Regime::Trending:
            d.momentum_weight = cfg.trending_momentum_weight;
            d.reversion_weight = cfg.trending_reversion_weight;
            break;
        case Regime::RangeBound:
            d.momentum_weight = cfg.range_momentum_weight;
            d.reversion_weight = cfg.range_reversion_weight;
            break;
        case Regime::Neutral:
            d.momentum_weight = cfg.neutral_momentum_weight;
            d.reversion_weight = cfg.neutral_reversion_weight;
            break;
    }
    StrategySignal mom = cfg.momentum_enabled
                             ? evaluate_momentum(bars, cfg, allow_short)
                             : StrategySignal{};
    StrategySignal rev = cfg.reversion_enabled
                             ? evaluate_reversion(bars, cfg, allow_short)
                             : StrategySignal{};
    // Rank by regime-weighted strength; -1 sentinel keeps a no-signal factor last.
    double mom_w = mom.has_signal ? d.momentum_weight * mom.strength : -1.0;
    double rev_w = rev.has_signal ? d.reversion_weight * rev.strength : -1.0;
    if (mom_w < 0 && rev_w < 0) return d;  // neither fired
    if (mom_w >= rev_w) {
        d.signal = mom;
        d.signal.strength = d.momentum_weight * mom.strength;
    } else {
        d.signal = rev;
        d.signal.strength = d.reversion_weight * rev.strength;
    }
    return d;
}

}  // namespace mal::strategy

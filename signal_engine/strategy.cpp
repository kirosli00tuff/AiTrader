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

std::vector<double> atr_series(const std::vector<Bar>& bars, int period) {
    // Prefix ATR: out[j] == atr(bars[0..j], period), the SAME Wilder
    // recurrence and float-op order as atr(), so each value is bit-identical
    // to the windowed call it replaces (the ATR band used to copy
    // atr_mean_period windows per evaluation; this is one pass).
    int n = static_cast<int>(bars.size());
    std::vector<double> out(std::max(n, 0), 0.0);
    if (period < 1 || n <= period) return out;
    std::vector<double> tr;
    tr.reserve(n - 1);
    for (int i = 1; i < n; ++i) {
        double h = bars[i].high, l = bars[i].low, pc = bars[i - 1].close;
        tr.push_back(std::max({h - l, std::fabs(h - pc), std::fabs(l - pc)}));
    }
    double a = 0.0;
    for (int i = 0; i < period; ++i) a += tr[i];
    a /= period;
    out[period] = a;
    for (int j = period + 1; j < n; ++j) {
        a = (a * (period - 1) + tr[j - 1]) / period;
        out[j] = a;
    }
    return out;
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

// The long trend MA / dual-MA / ATR-band lookbacks only gate warmth when the
// RSI-2 reversion style or the dual-MA momentum filter is active. Swing (dual-MA
// off, reversion bollinger) is unchanged: this returns 0 so min_bars_to_warm
// stays the ema_slow+2 longest lookback.
static int trend_warm_need(const config::StrategyConfig& cfg) {
    bool active = cfg.reversion_style == "rsi2" || cfg.momentum_dual_ma_filter;
    if (!active) return 0;
    int need = cfg.trend_ma_period;
    need = std::max(need, cfg.momentum_long_ma);
    need = std::max(need, cfg.atr_mean_period + cfg.atr_period + 1);
    return need;
}

int min_bars_to_warm(const config::StrategyConfig& cfg) {
    int need = cfg.ema_slow + 2;                     // momentum EMA cross
    need = std::max(need, 2 * cfg.atr_period + 1);   // ADX (Wilder smoothing)
    need = std::max(need, cfg.atr_period + 1);       // ATR
    need = std::max(need, cfg.bb_period);            // Bollinger bands
    need = std::max(need, cfg.rsi_period + 2);       // RSI (reversion reads n-2)
    need = std::max(need, cfg.vol_lookback);         // average volume
    need = std::max(need, cfg.vol_lookback + 1);     // realized vol
    need = std::max(need, trend_warm_need(cfg));     // long trend MA (RSI-2/dual-MA)
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
    // trend_ma is true when the trend filter is inactive, so it never gates swing.
    int tw = trend_warm_need(cfg);
    w.trend_ma = tw == 0 || bar_count >= tw;
    w.all = w.ema_slow && w.adx && w.atr && w.bollinger && w.rsi && w.volume &&
            w.rvol && w.trend_ma;
    return w;
}

std::string active_factor_for(Regime r, const config::StrategyConfig& cfg) {
    double mom = 0.0, rev = 0.0;
    switch (r) {
        case Regime::Trending:
            mom = cfg.trending_momentum_weight; rev = cfg.trending_reversion_weight; break;
        case Regime::RangeBound:
            mom = cfg.range_momentum_weight; rev = cfg.range_reversion_weight; break;
        case Regime::Neutral:
            mom = cfg.neutral_momentum_weight; rev = cfg.neutral_reversion_weight; break;
    }
    if (mom > rev) return "momentum";
    if (rev > mom) return "reversion";
    return "blend";
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
                                 bool allow_short, bool is_crypto,
                                 EvalTrace* trace) {
    StrategySignal sig;
    sig.factor = "momentum";
    // Recording only (2026-07-23): `reject` names the FIRST refusing
    // condition in the trace and returns the same empty signal the bare
    // `return sig;` always did. The trace is never consulted by a decision.
    auto reject = [&](const char* why) -> StrategySignal& {
        if (trace) trace->momentum_first_reject = why;
        return sig;
    };
    if (static_cast<int>(bars.size()) < cfg.ema_slow + 2)
        return reject("insufficient_history");
    auto closes = closes_of(bars);
    auto ef = ema_series(closes, cfg.ema_fast);
    auto es = ema_series(closes, cfg.ema_slow);
    size_t n = closes.size();
    bool cross_up = ef[n - 2] <= es[n - 2] && ef[n - 1] > es[n - 1];
    bool cross_down = ef[n - 2] >= es[n - 2] && ef[n - 1] < es[n - 1];
    const bool raw_cross_up = cross_up, raw_cross_down = cross_down;
    double adx_v = adx(bars, cfg.atr_period);
    double atr_v = atr(bars, cfg.atr_period);
    double price = closes[n - 1];
    bool adx_ok = adx_v >= cfg.adx_min;
    bool vol_ok = price > 0 && (atr_v / price) >= cfg.atr_vol_floor;
    if (trace) {
        trace->ema_f = ef[n - 1];
        trace->ema_s = es[n - 1];
        trace->adx_mom = adx_v;
        trace->atr_over_price = price > 0 ? atr_v / price : 0.0;
        trace->cross_up = cross_up;
        trace->cross_down = cross_down;
        trace->adx_ok = adx_ok;
        trace->atr_floor_ok = vol_ok;
    }
    if (!adx_ok || !vol_ok)
        return reject(!adx_ok ? "adx_floor" : "atr_vol_floor");
    // Dual trend filter for time-series momentum. A long needs price above BOTH
    // the medium and long MA (and, when ts_momentum_lookback > 0, a positive
    // return over that lookback). A short is the mirror. OFF by default so swing
    // is unchanged. The evidence: the dual filter lifts the long win rate.
    if (cfg.momentum_dual_ma_filter) {
        double med = sma(closes, cfg.momentum_medium_ma);
        double lng = sma(closes, cfg.momentum_long_ma);
        if (trace) {
            trace->mom_medium_ma = med;
            trace->mom_long_ma = lng;
        }
        if (med == 0.0 || lng == 0.0)
            return reject("dual_ma_history");  // not enough history yet
        bool long_trend_ok = price > med && price > lng;
        bool short_trend_ok = price < med && price < lng;
        if (cfg.ts_momentum_lookback > 0 &&
            n > static_cast<size_t>(cfg.ts_momentum_lookback)) {
            double past = closes[n - 1 - cfg.ts_momentum_lookback];
            double ret = past != 0.0 ? (price - past) / past : 0.0;
            if (trace) trace->ts_return = ret;
            long_trend_ok = long_trend_ok && ret > 0.0;
            short_trend_ok = short_trend_ok && ret < 0.0;
        }
        if (cross_up && !long_trend_ok) cross_up = false;
        if (cross_down && !short_trend_ok) cross_down = false;
        if (trace)
            trace->dual_ma_ok =
                raw_cross_up == cross_up && raw_cross_down == cross_down;
    }
    Direction dir = Direction::None;
    if (cross_up) dir = Direction::Long;
    else if (cross_down && allow_short) dir = Direction::Short;
    if (dir == Direction::None) {
        if (!raw_cross_up && !raw_cross_down) return reject("no_ema_cross");
        if (!cross_up && !cross_down) return reject("dual_ma");
        return reject("short_not_allowed");
    }
    sig.has_signal = true;
    sig.direction = dir;
    sig.entry_price = price;
    double adx_span = std::max(1.0, 50.0 - cfg.adx_min);
    sig.strength = std::clamp((adx_v - cfg.adx_min) / adx_span, 0.0, 1.0);
    sig.time_stop_bars = cfg.time_stop_bars;
    // Crypto uses the wider crypto ATR stop; equities keep atr_stop_mult.
    double stop_mult = is_crypto ? cfg.crypto_atr_stop_mult : cfg.atr_stop_mult;
    if (dir == Direction::Long) {
        sig.stop_price = price - stop_mult * atr_v;
        sig.target_price = price + cfg.atr_target_mult * atr_v;
    } else {
        sig.stop_price = price + stop_mult * atr_v;
        sig.target_price = price - cfg.atr_target_mult * atr_v;
    }
    sig.rationale = "EMA" + std::to_string(cfg.ema_fast) + "/" +
                    std::to_string(cfg.ema_slow) + " cross, ADX " +
                    std::to_string(static_cast<int>(adx_v)) +
                    (cfg.momentum_dual_ma_filter ? " [dual-MA]" : "");
    return sig;
}

StrategySignal evaluate_reversion(const std::vector<Bar>& bars,
                                  const config::StrategyConfig& cfg,
                                  bool allow_short, bool is_crypto,
                                  EvalTrace* trace) {
    StrategySignal sig;
    sig.factor = "reversion";
    // Recording only (2026-07-23): same pattern as evaluate_momentum.
    auto reject = [&](const char* why) -> StrategySignal& {
        if (trace) trace->reversion_first_reject = why;
        return sig;
    };
    int need = std::max({cfg.bb_period, cfg.rsi_period + 2, cfg.vol_lookback,
                         cfg.atr_period + 1}) + 2;
    if (static_cast<int>(bars.size()) < need)
        return reject("insufficient_history");
    auto closes = closes_of(bars);
    size_t n = closes.size();
    Bollinger bb = bollinger(closes, cfg.bb_period, cfg.bb_std);
    auto rs = rsi_series(closes, cfg.rsi_period);
    double rsi_now = rs[n - 1], rsi_prev = rs[n - 2];
    double price = closes[n - 1], prev_price = closes[n - 2];
    double vavg = avg_volume(bars, cfg.vol_lookback);
    // A bar reporting NO volume is not a low-volume bar, it is a bar whose
    // volume the venue did not give us (2026-07-21). The live Alpaca path
    // reports none, so gating on it would be gating on absence. Unknown
    // volume passes this check and the other filters still decide.
    const bool volume_known = bars[n - 1].volume > 0.0;
    bool vol_ok = !volume_known ||
                  (vavg > 0 && bars[n - 1].volume > cfg.vol_multiple * vavg);
    double atr_v = atr(bars, cfg.atr_period);
    // Long reentry: prior bar stretched below the lower band, now back inside,
    // RSI leaving oversold. Short reentry is the mirror at the upper band.
    bool long_reentry = prev_price < bb.lower && price >= bb.lower &&
                        rsi_prev <= cfg.rsi_oversold && rsi_now > cfg.rsi_oversold;
    bool short_reentry = prev_price > bb.upper && price <= bb.upper &&
                         rsi_prev >= cfg.rsi_overbought &&
                         rsi_now < cfg.rsi_overbought;
    if (trace) {
        trace->bb_lower = bb.lower;
        trace->bb_mid = bb.mid;
        trace->bb_upper = bb.upper;
        trace->rsi14 = rsi_now;
        trace->volume = bars[n - 1].volume;
        trace->vol_avg = vavg;
        trace->volume_present = volume_known;
        trace->vol_ok = vol_ok;
    }
    Direction dir = Direction::None;
    if (long_reentry && vol_ok) dir = Direction::Long;
    else if (short_reentry && vol_ok && allow_short) dir = Direction::Short;
    if (dir == Direction::None) {
        if (!long_reentry && !short_reentry) return reject("no_reentry");
        if (!vol_ok) return reject("volume");
        return reject("short_not_allowed");
    }
    sig.has_signal = true;
    sig.direction = dir;
    sig.entry_price = price;
    double stretch = bb.sd > 0 ? std::fabs(prev_price - bb.mid) / bb.sd : 0.0;
    sig.strength = std::clamp((stretch - cfg.bb_std) / std::max(1e-9, cfg.bb_std),
                              0.0, 1.0);
    sig.time_stop_bars = cfg.time_stop_bars;
    // Target is the mean (the reversion thesis); stop is an ATR beyond entry.
    // Crypto uses the wider crypto ATR stop; equities keep atr_stop_mult.
    double stop_mult = is_crypto ? cfg.crypto_atr_stop_mult : cfg.atr_stop_mult;
    sig.target_price = bb.mid;
    if (dir == Direction::Long)
        sig.stop_price = price - stop_mult * atr_v;
    else
        sig.stop_price = price + stop_mult * atr_v;
    sig.rationale = "BB reentry, RSI " + std::to_string(static_cast<int>(rsi_now));
    return sig;
}

StrategySignal evaluate_rsi2_reversion(const std::vector<Bar>& bars,
                                       const config::StrategyConfig& cfg,
                                       bool is_crypto, EvalTrace* trace) {
    StrategySignal sig;
    sig.factor = "reversion";  // same ensemble slot as Bollinger reversion
    // Recording only (2026-07-23): every condition is computed and recorded
    // even past the first refusal (knowing only the first hides how close the
    // others were), then the SAME sequential decision applies in the SAME
    // order as before the trace existed. The trace never decides anything.
    auto reject = [&](const char* why) -> StrategySignal& {
        if (trace) trace->reversion_first_reject = why;
        return sig;
    };
    if (trace) trace->rsi2_style = true;
    // Need enough bars for the long trend MA, the ATR band, and the RSI-2 series.
    int need = std::max({cfg.trend_ma_period, cfg.atr_mean_period + cfg.atr_period + 1,
                         cfg.rsi2_period + 2, cfg.vol_lookback + 1});
    if (static_cast<int>(bars.size()) < need)
        return reject("insufficient_history");
    auto closes = closes_of(bars);
    size_t n = closes.size();
    double price = closes[n - 1];

    // Trend filter: LONG ONLY, and only above the long trend MA (buy dips inside
    // a confirmed uptrend). RSI-2 is a long-only reversion factor here.
    double trend_ma = sma(closes, cfg.trend_ma_period);
    const bool trend_ok = trend_ma > 0.0 && price > trend_ma;

    // Oversold trigger: RSI-2 below the entry threshold (looser for crypto). With
    // cross-back confirmation, wait for RSI-2 to tick back above the threshold
    // (prev below, now above), which cuts whipsaw. Without it, enter while below.
    auto rs = rsi_series(closes, cfg.rsi2_period);
    double rsi_now = rs[n - 1], rsi_prev = rs[n - 2];
    double entry = is_crypto ? cfg.rsi2_entry_crypto : cfg.rsi2_entry_equity;
    bool trigger;
    if (cfg.rsi2_crossback_confirm)
        trigger = rsi_prev <= entry && rsi_now > entry;
    else
        trigger = rsi_now <= entry;

    // Volatility band: ATR within atr_band_std SD of its atr_mean_period mean, so
    // entries skip abnormally quiet or violent tape (improves profit factor).
    // Computed from the prefix ATR series: bit-identical values to the old
    // per-window loop (same recurrence, same indices), one O(n) pass instead
    // of atr_mean_period window copies. The recorded offline baselines pin
    // the identity.
    auto aseries = atr_series(bars, cfg.atr_period);
    double atr_v = aseries.empty() ? 0.0 : aseries.back();
    double band_mean = 0.0, band_sd = 0.0, band_z = 0.0;
    bool band_ok = true;
    const char* band_edge = "";
    {
        std::vector<double> atr_hist;
        atr_hist.reserve(cfg.atr_mean_period);
        int lo = std::max(static_cast<int>(n) - cfg.atr_mean_period,
                          cfg.atr_period);
        for (int j = lo; j < static_cast<int>(n); ++j)
            atr_hist.push_back(aseries[j]);
        if (atr_hist.size() >= 2) {
            for (double a : atr_hist) band_mean += a;
            band_mean /= atr_hist.size();
            double var = 0.0;
            for (double a : atr_hist) var += (a - band_mean) * (a - band_mean);
            var /= atr_hist.size();
            band_sd = std::sqrt(var);
            if (band_sd > 0.0) {
                band_z = (atr_v - band_mean) / band_sd;
                if (std::fabs(atr_v - band_mean) > cfg.atr_band_std * band_sd) {
                    band_ok = false;
                    band_edge = atr_v < band_mean ? "low" : "high";
                }
            }
        }
    }

    // Volume filter: skip below-average volume. A bar reporting NO volume is
    // NOT below average, it is unmeasured (2026-07-21): the live Alpaca path
    // has no venue volume to report, and this check used to run against a
    // uniform random draw, deciding 3,235 live-bar comparisons at a 49.2
    // percent pass rate. Unknown volume does not gate. The trend filter, the
    // RSI-2 trigger, and the ATR band still decide.
    double vavg = avg_volume(bars, cfg.vol_lookback);
    const double vol_now = bars[n - 1].volume;
    const bool volume_present = vol_now > 0.0;
    const bool vol_ok = !(volume_present && vavg > 0 && vol_now < vavg);

    if (trace) {
        trace->rsi2 = rsi_now;
        trace->rsi2_prev = rsi_prev;
        trace->rsi2_entry = entry;
        trace->trend_ma = trend_ma;
        trace->trend_dist_pct =
            trend_ma > 0.0 ? (price - trend_ma) / trend_ma * 100.0 : 0.0;
        trace->trend_ok = trend_ok;
        trace->crossback_confirm = cfg.rsi2_crossback_confirm;
        trace->rsi2_trigger = trigger;
        trace->atr_v = atr_v;
        trace->atr_mean = band_mean;
        trace->atr_sd = band_sd;
        trace->atr_z = band_z;
        trace->atr_band_edge = band_edge;
        trace->atr_band_ok = band_ok;
        trace->volume = vol_now;
        trace->vol_avg = vavg;
        trace->volume_present = volume_present;
        trace->vol_ok = vol_ok;
    }

    // The decision, in the SAME order as before the trace existed.
    if (!trend_ok) return reject("trend_filter");
    if (!trigger) return reject("rsi2_trigger");
    if (!band_ok) return reject("atr_band");
    if (!vol_ok) return reject("volume");

    sig.has_signal = true;
    sig.direction = Direction::Long;
    sig.entry_price = price;
    // Strength scales with how deep RSI-2 dipped below the entry threshold.
    double depth = std::clamp((entry - std::min(rsi_prev, rsi_now)) /
                              std::max(1.0, entry), 0.0, 1.0);
    sig.strength = std::clamp(0.4 + 0.6 * depth, 0.0, 1.0);
    sig.time_stop_bars = cfg.time_stop_bars;
    // WIDE ATR stop (crypto wider still): a tight stop cuts the snapback. The
    // primary exit is the RSI-2 cross above rsi2_exit (engine, ExitReason::Indicator);
    // the ATR target is a profit backstop and the RiskGate keeps its own stops.
    double stop_mult = is_crypto ? cfg.crypto_atr_stop_mult : cfg.atr_stop_mult;
    sig.stop_price = price - stop_mult * atr_v;
    sig.target_price = price + cfg.atr_target_mult * atr_v;
    sig.rationale = "RSI-2 " + std::to_string(static_cast<int>(rsi_now)) +
                    " dip in uptrend (>MA" + std::to_string(cfg.trend_ma_period) + ")";
    return sig;
}

bool rsi2_exit_triggered(const std::vector<Bar>& bars,
                         const config::StrategyConfig& cfg) {
    auto closes = closes_of(bars);
    if (static_cast<int>(closes.size()) <= cfg.rsi2_period + 1) return false;
    double r = rsi(closes, cfg.rsi2_period);
    return r >= cfg.rsi2_exit;
}

std::string exit_reason_to_string(ExitReason r) {
    switch (r) {
        case ExitReason::Stop: return "stop";
        case ExitReason::Target: return "target";
        case ExitReason::TimeStop: return "time_stop";
        case ExitReason::Indicator: return "indicator";
        case ExitReason::None: return "none";
    }
    return "none";
}

ExitReason check_exit(const OpenPosition& pos, const Bar& latest_bar,
                      bool indicator_exit) {
    // Risk-first: the stop is always checked before any profit or signal exit.
    if (pos.direction == Direction::Long) {
        if (latest_bar.low <= pos.stop_price) return ExitReason::Stop;
        if (latest_bar.high >= pos.target_price) return ExitReason::Target;
    } else if (pos.direction == Direction::Short) {
        if (latest_bar.high >= pos.stop_price) return ExitReason::Stop;
        if (latest_bar.low <= pos.target_price) return ExitReason::Target;
    }
    // Strategy-signal exit (RSI-2 crossed above its exit threshold), after the
    // stop/target but before the time-stop.
    if (indicator_exit) return ExitReason::Indicator;
    if (pos.time_stop_bars > 0 && pos.bars_held >= pos.time_stop_bars)
        return ExitReason::TimeStop;
    return ExitReason::None;
}

double exit_fill_price(const OpenPosition& pos, ExitReason reason,
                       const Bar& latest_bar) {
    switch (reason) {
        case ExitReason::Stop: return pos.stop_price;
        case ExitReason::Target: return pos.target_price;
        case ExitReason::Indicator:
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
                         const config::StrategyConfig& cfg, bool is_crypto,
                         EvalTrace* trace) {
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
    if (trace) {
        trace->regime = regime_to_string(d.regime.regime);
        trace->adx = d.regime.adx;
        trace->rvol = d.regime.rvol;
        trace->momentum_weight = d.momentum_weight;
        trace->reversion_weight = d.reversion_weight;
    }
    StrategySignal mom =
        cfg.momentum_enabled
            ? evaluate_momentum(bars, cfg, allow_short, is_crypto, trace)
            : StrategySignal{};
    if (trace && !cfg.momentum_enabled)
        trace->momentum_first_reject = "disabled";
    // Reversion slot uses the RSI-2 factor when reversion_style is rsi2 (long
    // only, dips inside an uptrend), else the Bollinger reentry. Same ensemble
    // slot either way (factor "reversion").
    StrategySignal rev;
    if (cfg.reversion_enabled) {
        rev = cfg.reversion_style == "rsi2"
                  ? evaluate_rsi2_reversion(bars, cfg, is_crypto, trace)
                  : evaluate_reversion(bars, cfg, allow_short, is_crypto, trace);
    } else if (trace) {
        trace->reversion_first_reject = "disabled";
    }
    // Rank by regime-weighted strength; -1 sentinel keeps a no-signal factor last.
    double mom_w = mom.has_signal ? d.momentum_weight * mom.strength : -1.0;
    double rev_w = rev.has_signal ? d.reversion_weight * rev.strength : -1.0;
    if (mom_w < 0 && rev_w < 0) {
        if (trace) {
            trace->selected_factor = "none";
            // The overall first refusal is the regime-weighted LEADING
            // family's; both families' own rejects are recorded beside it.
            trace->first_reject = d.momentum_weight > d.reversion_weight
                                      ? trace->momentum_first_reject
                                      : trace->reversion_first_reject;
        }
        return d;  // neither fired
    }
    if (mom_w >= rev_w) {
        d.signal = mom;
        d.signal.strength = d.momentum_weight * mom.strength;
    } else {
        d.signal = rev;
        d.signal.strength = d.reversion_weight * rev.strength;
    }
    if (trace) trace->selected_factor = d.signal.factor;
    return d;
}

}  // namespace mal::strategy

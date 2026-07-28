// TRADING SCOPE: which asset classes may reach an ENTRY decision (2026-07-27).
//
// The system trades US EQUITIES ONLY. Crypto is retained as DATA and is never
// traded. The evidence, all of it measured in this repository:
//   * a crypto round trip costs 50 bp against 1.14 to 4.87 bp for equities in
//     the tradeable liquidity bands, a 10x to 44x difference in the hurdle,
//   * the P26 re-costed result splits -48.78 bp crypto against -2.73 equity,
//   * the council abstained on 87 to 94 percent of crypto calls against 43 to
//     47 percent on equities, so the expensive half was also the half the
//     advisory layer had least to say about.
// Crypto also carried a 24/7 loop, regional-session carve-outs, venue
// serviceability checks, and its own fee schedule. It was never the promising
// half and it cost the most attention.
//
// THIS IS A SCOPE RULE, NOT A DELETION, and the distinction is the point:
//   * bars still poll, still carry provenance, and still store,
//   * every stored crypto row stays,
//   * the crypto fee schedule stays in the model,
//   * the venue plumbing stays wired,
// so a future hypothesis needing crypto restores it by adding one class here,
// with no rebuild of anything else.
//
// WHY A SEPARATE PREDICATE FROM symbol_is_tradeable. That one answers "has the
// venue ever served this symbol real bars", a DATA question. This answers "is
// this asset class in scope", a POLICY question. Collapsing them would make a
// crypto symbol read as unavailable, which is false, and would fire
// symbol_unavailable alarms about a feed that is working perfectly.
//
// A GATE ON ENTRY ONLY. Nothing here refuses an EXIT, touches RiskGate, the
// live-trading gate, or any Level-1 value. An exit must never be blocked: a
// position is never trapped by a scope change.
//
// Must stay equal to market_data.tradeable on the Python side. A drift-guard
// test pins the two class sets.
#pragma once

#include <string>

namespace mal::scope {

inline constexpr const char* kEquity = "equity";
inline constexpr const char* kCrypto = "crypto";

// THE classification rule, the same one Engine::make_instrument and
// onboard_discovered_symbols already use: an Alpaca crypto pair carries a
// slash, everything else is a US equity. Stated once so no path invents a
// second rule.
inline std::string asset_class(const std::string& symbol) {
    return symbol.find('/') != std::string::npos ? kCrypto : kEquity;
}

// THE scope set. Adding kCrypto here restores crypto trading everywhere at
// once, which is exactly the property that makes this a scope change rather
// than a removal.
inline bool is_tradeable_class(const std::string& asset_class_name) {
    return asset_class_name == kEquity;
}

// Convenience: may this SYMBOL reach an entry decision on scope grounds.
inline bool symbol_in_scope(const std::string& symbol) {
    return is_tradeable_class(asset_class(symbol));
}

}  // namespace mal::scope

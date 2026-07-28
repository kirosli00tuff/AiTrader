// Trading scope (2026-07-27): US equities only, crypto retained as data.
//
// The rule is pure and small on purpose, so it is exhaustively testable
// without an Engine, exactly like core/provenance.hpp. What matters:
//   1. the classification rule is the slash rule the engine already used, so
//      no path invents a second one,
//   2. every crypto shape is out of scope and every equity shape is in,
//   3. the scope set is a SET, so restoring crypto is one edit there and
//      nothing else, which is what makes this a scope change not a deletion.
//
// Mutation check: adding kCrypto to is_tradeable_class fails this suite, and
// tests/test_trading_scope.py fails on the same mutation from the other side.
#include <cstdio>
#include <string>

#include "core/trading_scope.hpp"
#include "test_util.hpp"

using namespace mal;

int main() {
    // --- 1. classification, the slash rule ------------------------------
    maltest::check(scope::asset_class("BTC/USD") == "crypto",
                   "a slashed pair is crypto");
    maltest::check(scope::asset_class("ETH/USD") == "crypto",
                   "ETH/USD is crypto");
    maltest::check(scope::asset_class("SOL/USD") == "crypto",
                   "SOL/USD is crypto");
    maltest::check(scope::asset_class("SPY") == "equity",
                   "an unslashed ticker is equity");
    maltest::check(scope::asset_class("BRK.B") == "equity",
                   "a dotted ticker is still equity");
    maltest::check(scope::asset_class("") == "equity",
                   "an empty symbol classifies rather than throwing");

    // --- 2. the scope set ------------------------------------------------
    maltest::check(scope::is_tradeable_class(scope::kEquity),
                   "equities are in scope");
    maltest::check(!scope::is_tradeable_class(scope::kCrypto),
                   "crypto is OUT of scope: it is collected, never traded");
    maltest::check(!scope::is_tradeable_class("politics"),
                   "an unknown class is out of scope, never admitted by default");
    maltest::check(!scope::is_tradeable_class(""),
                   "an empty class is out of scope");

    // --- 3. the symbol convenience ---------------------------------------
    for (const char* s : {"SPY", "QQQ", "AAPL", "MSFT", "NVDA"})
        maltest::check(scope::symbol_in_scope(s),
                       std::string(s) + " may reach an entry decision");
    for (const char* s : {"BTC/USD", "ETH/USD", "SOL/USD", "SHIB/USD",
                          "UNI/USD"})
        maltest::check(!scope::symbol_in_scope(s),
                       std::string(s) + " may NOT reach an entry decision");

    // --- 4. the shipped cores stay DECLARED and untradeable ---------------
    // Both profiles declare crypto. Those symbols stay declared so they keep
    // being POLLED and STORED; scope is what stops them trading. Pinned here
    // so the two facts are never confused for each other.
    for (const char* s : {"BTC/USD", "ETH/USD", "SOL/USD"})
        maltest::check(!scope::symbol_in_scope(s),
                       std::string(s) + " is declared, polled, and untradeable");

    return maltest::report("test_trading_scope");
}

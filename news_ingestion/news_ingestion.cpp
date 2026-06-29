#include "news_ingestion/news_ingestion.hpp"

#include <functional>

#include "core/util.hpp"

namespace mal::news {

CatalystScore MockCatalystProvider::score_for(const std::string& symbol) {
    // Deterministic per-symbol hash -> stable catalyst values for the demo.
    std::size_t h = std::hash<std::string>{}(symbol) ^ seed_;
    double s = (static_cast<double>(h % 2000) / 1000.0) - 1.0;  // [-1,1]
    double imp = static_cast<double>((h / 2000) % 1000) / 1000.0;
    CatalystScore cs;
    cs.symbol = symbol;
    cs.score = s;
    cs.importance = imp;
    cs.headline = "Mock catalyst for " + symbol;
    cs.ts = util::now_iso8601();
    return cs;
}

}  // namespace mal::news

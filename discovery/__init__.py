"""Discovery engine: a curated universe screened cheap-to-expensive into a few
vetted candidates.

The funnel spends intelligence only at the bottom. Stage A ranks the whole
universe on free Finnhub quant data and native technicals (no LLM tokens).
Stage B screens the finalists with the cheap Haiku gate. Stage C runs the full
four-level framework (council, DNN advisory, whale) on a handful of survivors.
Survivors land on a dynamic watchlist that both sleeves draw candidates from.

Everything here ships DISABLED (``discovery.discovery_enabled`` default false).
With the flag off the engine never calls this package and behaves exactly as the
fixed-whitelist two-sleeve system.

The real-time news-interpretation-and-react adaptive layer is NOT part of this
package. Discovery uses Finnhub's PRE-COMPUTED sentiment as a cheap numeric
signal only. See CONTEXT.md for the deferred react layer.
"""

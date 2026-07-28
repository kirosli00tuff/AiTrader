"""Measure the quoted spread and tick multiple during US regular trading hours.

WHY IT IS A SCRIPT AND NOT A SESSION. The measurement is only valid inside RTH
(13:30-20:00 UTC). Two sessions have now tried and both ran outside it, so the
work is packaged to run unattended at the right time rather than re-attempted
at the wrong one.

  RUN:  .venv/bin/python scripts/measure_tick_multiple_rth.py out.json

REFUSES to run outside RTH rather than producing numbers that look measured.
Read-only. Writes one JSON file. Trades nothing, wires nothing.
"""
from __future__ import annotations
import datetime, json, math, os, statistics as st, sys, time, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from account_manager import credentials as cr

ADV_LO, ADV_HI, PRICE_FLOOR = 2_070_000.0, 65_300_000.0, 10.0
PER_STRATUM = 40
SWEEPS = [(14, 0), (16, 30), (19, 30)]      # UTC: after the open, mid, near the close
TICK = 0.01


def _hdr():
    return {"APCA-API-KEY-ID": cr.get_credential("alpaca_paper_key"),
            "APCA-API-SECRET-KEY": cr.get_credential("alpaca_paper_secret")}


def _open_now() -> bool:
    req = urllib.request.Request("https://paper-api.alpaca.markets/v2/clock", headers=_hdr())
    with urllib.request.urlopen(req, timeout=20) as r:
        return bool(json.loads(r.read().decode()).get("is_open"))


def universe():
    """Stratified sample from the current rule. Same seed discipline as the spec."""
    import hashlib, sqlite3
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backtest"))
    from backtest.universe import WINDOW_SESSIONS, MIN_WINDOW_BARS, classify_fund
    conn = sqlite3.connect("file:analysis_bars.db?mode=ro", uri=True)
    win = [r[0] for r in conn.execute(
        "SELECT date FROM trading_calendar ORDER BY date DESC LIMIT ?", (WINDOW_SESSIONS,))]
    # THE FUND FILTER IS NOT OPTIONAL. The 2026-07-28 run omitted it and 42.1
    # percent of the sampled symbols were pooled vehicles. That is not a
    # rounding error, it is two populations averaged into one median: funds
    # measured 7.5 ticks against 376.5 for operating companies, because an ETF
    # is quoted continuously on IEX and a small-cap operating company is not.
    # The specification's own rule rejects funds (5,387 of them at the
    # 2026-07-01 formation), so a sample that keeps them measures a different
    # universe from the one the pre-registration defines.
    meta = {r[0]: (r[1] or "", r[2] or "")
            for r in conn.execute("SELECT symbol, name, exchange FROM universe_asset")}
    cur = conn.execute(
        "SELECT symbol, close, volume FROM bars WHERE timeframe='1day' AND timestamp>=? "
        "AND timestamp<=? ORDER BY symbol", (min(win), max(win)))
    out, s, cl, dv = [], None, [], []
    def flush():
        if s and len(cl) >= MIN_WINDOW_BARS:
            px = st.median(cl)
            # Tri-state, and None is NOT False: a symbol whose type cannot be
            # established is excluded rather than admitted.
            if px >= PRICE_FLOOR and classify_fund(*meta.get(s, ("", ""))) is False:
                out.append((st.median(dv), s, px))
    for sym, c, v in cur:
        if sym != s:
            flush(); s, cl, dv = sym, [], []
        if c is None: continue
        cl.append(c); dv.append(c * (v or 0.0))
    flush()
    band = [m for m in out if ADV_LO <= m[0] <= ADV_HI]
    lo, hi = math.log10(ADV_LO), math.log10(ADV_HI)
    E = [10 ** (lo + (hi - lo) * i / 4) for i in range(5)]
    strata = {}
    for i in range(4):
        k = f"S{4-i}"
        pool = sorted([m for m in band if E[i] <= m[0] < (E[i+1] if i < 3 else E[4] + 1)],
                      key=lambda m: m[1])
        seed = int(hashlib.sha256(k.encode()).hexdigest()[:16], 16)
        pick = []
        for _ in range(min(PER_STRATUM, len(pool))):
            seed = (seed * 6364136223846793005 + 1442695040888963407) % (2 ** 64)
            pick.append(pool.pop(seed % len(pool)))
        strata[k] = pick
    return strata


def sweep(strata, label):
    rows, disc = [], {"crossed": 0, "locked": 0, "zero": 0, "no_size": 0, "http": 0, "stale": 0}
    now = datetime.datetime.now(datetime.timezone.utc)
    for k, members in strata.items():
        for adv, sym, refpx in members:
            try:
                req = urllib.request.Request(
                    f"https://data.alpaca.markets/v2/stocks/{sym}/quotes/latest", headers=_hdr())
                with urllib.request.urlopen(req, timeout=15) as r:
                    q = json.loads(r.read().decode()).get("quote", {})
            except Exception:
                disc["http"] += 1; continue
            bid, ask = q.get("bp"), q.get("ap")
            bs, as_ = q.get("bs", 0), q.get("as", 0)
            if not bid or not ask or bid <= 0 or ask <= 0: disc["zero"] += 1; continue
            if ask < bid: disc["crossed"] += 1; continue
            if ask == bid: disc["locked"] += 1; continue
            if not bs or not as_: disc["no_size"] += 1; continue
            ts = q.get("t", "")
            try:                                     # stale: quote older than 60s
                qt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if (now - qt).total_seconds() > 60: disc["stale"] += 1; continue
            except Exception:
                pass
            mid = (bid + ask) / 2.0
            rows.append({"sweep": label, "stratum": k, "symbol": sym, "adv": adv,
                         "bid": bid, "ask": ask, "price": mid,
                         "spread_cents": round((ask - bid) * 100, 4),
                         "ticks": (ask - bid) / TICK,
                         "bp": (ask - bid) / mid * 1e4})
            time.sleep(0.05)
    return rows, disc


def _sip_entitled() -> tuple[bool, str]:
    """Whether this key may read the CONSOLIDATED quote, not one venue's book.

    MEASURED 2026-07-28 AND IT IS NOT. `feed=sip` returns HTTP 403
    "subscription does not permit querying recent SIP data", and the default
    feed is byte-identical to `feed=iex`. IEX carries roughly 2-3 percent of
    volume, so its top of book is the NBBO only for names it happens to quote
    tightly. AAPL came back 3 ticks wide and sane; UFPT, GPI and ITIC came back
    7,400, 10,000 and 9,000 ticks wide, which are not markets, they are an
    almost-empty book on a venue that barely trades those names.

    A spread measured on one venue is not the spread the cost model needs, so
    the script refuses rather than producing a table that looks measured. This
    is the same refusal as the market-closed one and for the same reason.
    """
    try:
        req = urllib.request.Request(
            "https://data.alpaca.markets/v2/stocks/AAPL/quotes/latest?feed=sip",
            headers=_hdr())
        with urllib.request.urlopen(req, timeout=20):
            return True, "sip"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read()[:160].decode(errors='replace')}"
    except Exception as e:
        return False, f"{type(e).__name__}"


def main():
    if not _open_now():
        print("REFUSING: market is closed. This measurement is only valid inside RTH.")
        sys.exit(2)
    ok, detail = _sip_entitled()
    if not ok and "--allow-iex-only" not in sys.argv:
        print("REFUSING: this key cannot read consolidated SIP quotes.")
        print(f"  {detail}")
        print("  The default feed is IEX-only, one venue at roughly 2-3 percent of")
        print("  volume. Its top of book is not the NBBO for a small cap, and the")
        print("  2026-07-28 run proved it: 17 to 39 percent of quotes were inside a")
        print("  plausible 5-tick range and the rest ran to 10,047 ticks. The tick")
        print("  multiple CANNOT be measured from this feed at any hour.")
        print("  Pass --allow-iex-only only to reproduce that negative result.")
        sys.exit(3)
    strata = universe()
    allrows, alldisc = [], {}
    captured, missed = [], []
    for h, m in SWEEPS:
        target = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=h, minute=m, second=0, microsecond=0)
        wait = (target - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        # A WINDOW THAT HAS ALREADY PASSED IS MISSED, NEVER RE-TIMED. The
        # original loop left `wait` negative and fell straight through to the
        # sweep, which sampled at the CURRENT time and still stamped every row
        # with the window's label: a row reading 14:00Z taken at 15:41Z. The
        # windows exist to separate the open, the middle and the close, so a
        # late sample is a DIFFERENT measurement and is reported as a miss
        # rather than relabelled. 120s of grace absorbs scheduling jitter
        # without absorbing an hour.
        if wait < -120:
            late = -wait / 60.0
            print(f"MISSED {h:02d}:{m:02d}Z, window passed {late:.0f} min ago, "
                  f"not re-timed")
            missed.append({"window": f"{h:02d}:{m:02d}Z",
                           "minutes_late": round(late, 1),
                           "reason": "window already passed"})
            continue
        if wait > 0:
            print(f"waiting {wait/60:.0f} min for the {h:02d}:{m:02d} UTC sweep"); time.sleep(wait)
        if not _open_now():
            print(f"skipping {h:02d}:{m:02d}, market closed")
            missed.append({"window": f"{h:02d}:{m:02d}Z",
                           "reason": "market closed"})
            continue
        started = datetime.datetime.now(datetime.timezone.utc)
        rows, disc = sweep(strata, f"{h:02d}:{m:02d}Z")
        allrows += rows
        for kk, vv in disc.items(): alldisc[kk] = alldisc.get(kk, 0) + vv
        captured.append({"window": f"{h:02d}:{m:02d}Z",
                         "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "kept": len(rows), "discarded": dict(disc)})
        print(f"sweep {h:02d}:{m:02d}Z  started {started:%H:%M:%S}Z  "
              f"kept {len(rows)}  discarded {disc}")

    print(f"\n{'stratum':<9}{'n':>5}{'ticks med':>11}{'p75':>7}{'p90':>7}{'bp med':>9}{'bp p90':>9}")
    per = {}
    for k in ("S1", "S2", "S3", "S4"):
        t = sorted(r["ticks"] for r in allrows if r["stratum"] == k)
        b = sorted(r["bp"] for r in allrows if r["stratum"] == k)
        if not t: continue
        per[k] = {"n": len(t), "med": st.median(t),
                  "p75": t[int(.75*(len(t)-1))], "p90": t[int(.90*(len(t)-1))],
                  "bp_med": st.median(b), "bp_p90": b[int(.90*(len(b)-1))]}
        p = per[k]
        print(f"{k:<9}{p['n']:>5}{p['med']:>11.2f}{p['p75']:>7.2f}{p['p90']:>7.2f}"
              f"{p['bp_med']:>9.2f}{p['bp_p90']:>9.2f}")
    mono = [per[k]["med"] for k in ("S1","S2","S3","S4") if k in per]
    print(f"\nSANITY monotone (thinnest widest): {mono == sorted(mono)}  ladder {mono}")
    print(f"windows captured: {[c['window'] for c in captured]}")
    print(f"windows missed:   {[m['window'] for m in missed]}")
    json.dump({"rows": allrows, "discarded": alldisc, "per_stratum": per,
               "monotone": mono == sorted(mono),
               "windows_captured": captured, "windows_missed": missed},
              open(sys.argv[1], "w"))


if __name__ == "__main__":
    main()

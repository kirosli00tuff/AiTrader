"""Measure the quoted spread and tick multiple from HISTORICAL consolidated quotes.

REPOINTED 2026-07-29. The latest-quote endpoint refuses feed=sip (403, "does
not permit querying recent SIP data") but the HISTORICAL quotes endpoint
serves the same feed with HTTP 200 for any window older than about 15 minutes.
Measured 2026-07-28: historical SIP carries different venues on the two sides
of the book, which is what a consolidated best bid and offer looks like, while
historical IEX carries one venue on both sides and quoted UFPT 7,286 ticks
wide against SIP's 547 at the same instant.

WHAT REPLACED THE RTH REFUSAL. The old script refused to run outside RTH
because a latest quote taken after hours is stale. A historical query names
its own window, so the run time no longer matters and the refusal is gone.
Three guards replace it:
  1. COMPLETE SESSIONS ONLY: sessions come from trading_calendar and must be
     strictly before today's UTC date, so no partially traded session is ever
     sampled.
  2. WINDOW INSIDE THE SESSION: each sampling window is validated against the
     session's own open and close (converted from the calendar's local times),
     so a half day cannot contribute a window after its close.
  3. NOT RECENT: every window must end at least 16 minutes in the past,
     because the historical endpoint 403s on recent SIP data. Automatic for
     past sessions, asserted anyway.
The windows themselves still separate the open, the middle and the close
(14:00Z, 16:30Z, 19:30Z), because those regimes behave differently. Only the
moment the script RUNS is now unconstrained. A late run cannot mislabel a
window: the query's time bounds are the label.

  RUN:  .venv/bin/python scripts/measure_tick_multiple_rth.py out.json

Read-only. Writes one JSON file. Trades nothing, wires nothing.
"""
from __future__ import annotations
import datetime, json, math, os, sqlite3, statistics as st, sys, time
import urllib.request, urllib.error
from zoneinfo import ZoneInfo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from account_manager import credentials as cr

ADV_LO, ADV_HI, PRICE_FLOOR = 2_070_000.0, 65_300_000.0, 10.0
PER_STRATUM = 40
WINDOWS = [(14, 0), (16, 30), (19, 30)]     # UTC: after the open, mid, near the close
WINDOW_SPAN_S = 300                          # quotes taken from the first 5 min of each window
QUOTES_PER_CELL = 50                         # cap per symbol/session/window request
N_SESSIONS = 3                               # most recent complete sessions
TICK = 0.01
ET = ZoneInfo("America/New_York")
DB = os.path.join(REPO, "analysis_bars.db")


def _hdr():
    return {"APCA-API-KEY-ID": cr.get_credential("alpaca_paper_key"),
            "APCA-API-SECRET-KEY": cr.get_credential("alpaca_paper_secret")}


def complete_sessions(n: int) -> list[dict]:
    """The n most recent COMPLETE sessions with their UTC open/close.

    Strictly before today's UTC date, so a session still trading (or not yet
    traded) can never be sampled. The calendar's open/close are local ET;
    zoneinfo converts them so DST is honoured rather than assumed.
    """
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT date, open, close FROM trading_calendar WHERE date < ? "
        "ORDER BY date DESC LIMIT ?", (today, n)).fetchall()
    conn.close()
    out = []
    for date, o, c in rows:
        y, m, d = (int(x) for x in date.split("-"))
        oh, om = (int(x) for x in o.split(":"))
        ch, cm = (int(x) for x in c.split(":"))
        out.append({
            "date": date,
            "open_utc": datetime.datetime(y, m, d, oh, om, tzinfo=ET)
                        .astimezone(datetime.timezone.utc),
            "close_utc": datetime.datetime(y, m, d, ch, cm, tzinfo=ET)
                         .astimezone(datetime.timezone.utc),
        })
    return sorted(out, key=lambda s: s["date"])


def universe():
    """Stratified sample from the current rule. Same seed discipline as the spec."""
    import hashlib
    from backtest.universe import WINDOW_SESSIONS, MIN_WINDOW_BARS, classify_fund
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    win = [r[0] for r in conn.execute(
        "SELECT date FROM trading_calendar WHERE date <= ? "
        "ORDER BY date DESC LIMIT ?",
        (datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
         WINDOW_SESSIONS))]
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
    excluded_funds = 0

    def flush():
        nonlocal excluded_funds
        if s and len(cl) >= MIN_WINDOW_BARS:
            px = st.median(cl)
            if px < PRICE_FLOOR:
                return
            # Tri-state, and None is NOT False: a symbol whose type cannot be
            # established is excluded rather than admitted.
            verdict = classify_fund(*meta.get(s, ("", "")))
            if verdict is False:
                out.append((st.median(dv), s, px))
            else:
                excluded_funds += 1
    for sym, c, v in cur:
        if sym != s:
            flush(); s, cl, dv = sym, [], []
        if c is None: continue
        cl.append(c); dv.append(c * (v or 0.0))
    flush()
    conn.close()
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
    return strata, excluded_funds


def _fetch_quotes(sym: str, start: datetime.datetime, end: datetime.datetime,
                  feed: str) -> list[dict] | None:
    """Up to QUOTES_PER_CELL quotes in [start, end). None means the request failed."""
    url = (f"https://data.alpaca.markets/v2/stocks/{sym}/quotes"
           f"?start={start:%Y-%m-%dT%H:%M:%SZ}&end={end:%Y-%m-%dT%H:%M:%SZ}"
           f"&limit={QUOTES_PER_CELL}&feed={feed}")
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers=_hdr())
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode()).get("quotes") or []
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 1:
                time.sleep(20); continue      # rate limited: back off once
            return None
        except Exception:
            return None
    return None


def sweep(strata, sessions, feed: str):
    """One row per symbol/session/window: the median over that window's quotes.

    Per-quote filters keep the pre-registered discard taxonomy (crossed,
    locked, zero, no_size). `stale` is gone: a historical query bounds time by
    construction, so a quote outside its window cannot appear. New reasons:
    `http` a request failed, `no_quotes` the venue served no quotes in the
    window, `all_filtered` quotes existed and every one was discarded.
    """
    rows = []
    disc = {"crossed": 0, "locked": 0, "zero": 0, "no_size": 0,
            "http": 0, "no_quotes": 0, "all_filtered": 0}
    now = datetime.datetime.now(datetime.timezone.utc)
    for sess in sessions:
        for h, m in WINDOWS:
            y, mo, d = (int(x) for x in sess["date"].split("-"))
            w0 = datetime.datetime(y, mo, d, h, m, tzinfo=datetime.timezone.utc)
            w1 = w0 + datetime.timedelta(seconds=WINDOW_SPAN_S)
            if w0 < sess["open_utc"] or w1 > sess["close_utc"]:
                continue                      # window outside this session's hours
            if (now - w1).total_seconds() < 16 * 60:
                continue                      # recent SIP is 403; cannot happen for past sessions
            for k, members in strata.items():
                for adv, sym, refpx in members:
                    quotes = _fetch_quotes(sym, w0, w1, feed)
                    time.sleep(0.28)          # stay under the 200 req/min limit
                    if quotes is None:
                        disc["http"] += 1; continue
                    if not quotes:
                        disc["no_quotes"] += 1; continue
                    ticks, bps, mids, diff_venue = [], [], [], 0
                    for q in quotes:
                        bid, ask = q.get("bp"), q.get("ap")
                        bs, as_ = q.get("bs", 0), q.get("as", 0)
                        if not bid or not ask or bid <= 0 or ask <= 0:
                            disc["zero"] += 1; continue
                        if ask < bid: disc["crossed"] += 1; continue
                        if ask == bid: disc["locked"] += 1; continue
                        if not bs or not as_: disc["no_size"] += 1; continue
                        mid = (bid + ask) / 2.0
                        ticks.append((ask - bid) / TICK)
                        bps.append((ask - bid) / mid * 1e4)
                        mids.append(mid)
                        if q.get("bx") != q.get("ax"):
                            diff_venue += 1
                    if not ticks:
                        disc["all_filtered"] += 1; continue
                    rows.append({"session": sess["date"], "window": f"{h:02d}:{m:02d}Z",
                                 "stratum": k, "symbol": sym,
                                 "adv": adv, "price": st.median(mids),
                                 "n_quotes": len(ticks),
                                 "ticks": st.median(ticks), "bp": st.median(bps),
                                 "diff_venue": diff_venue})
    return rows, disc


def _sip_entitled(sessions) -> tuple[bool, str]:
    """Whether HISTORICAL consolidated quotes are readable on this key.

    Re-scoped 2026-07-29 from the latest-quote endpoint, whose 403 covers only
    RECENT SIP data. The historical endpoint's failure modes are its own:
      * 403 on a PAST session's window means the subscription no longer serves
        historical SIP at all, and nothing here can be measured.
      * an EMPTY quote list for AAPL on a past session means the endpoint
        answered but served nothing, which is not entitlement, and refusing
        beats sampling a feed that returns air.
    A 403 caused by a too-recent window cannot occur here because the probe
    window belongs to the newest COMPLETE session.
    """
    probe = sessions[-1]
    y, m, d = (int(x) for x in probe["date"].split("-"))
    w0 = datetime.datetime(y, m, d, 14, 0, tzinfo=datetime.timezone.utc)
    quotes = _fetch_quotes("AAPL", w0, w0 + datetime.timedelta(minutes=5), "sip")
    if quotes is None:
        return False, "historical SIP request failed (HTTP error or refused)"
    if not quotes:
        return False, f"historical SIP served zero AAPL quotes for {probe['date']} 14:00Z"
    return True, f"sip ok, {len(quotes)} AAPL quotes at {probe['date']} 14:00Z"


def _per_stratum(rows):
    per = {}
    for k in ("S1", "S2", "S3", "S4"):
        t = sorted(r["ticks"] for r in rows if r["stratum"] == k)
        b = sorted(r["bp"] for r in rows if r["stratum"] == k)
        if not t: continue
        per[k] = {"n": len(t), "med": st.median(t),
                  "p75": t[int(.75*(len(t)-1))], "p90": t[int(.90*(len(t)-1))],
                  "bp_med": st.median(b), "bp_p75": b[int(.75*(len(b)-1))],
                  "bp_p90": b[int(.90*(len(b)-1))]}
    return per


def main():
    sessions = complete_sessions(N_SESSIONS)
    if len(sessions) < N_SESSIONS:
        print(f"REFUSING: only {len(sessions)} complete sessions in the calendar.")
        sys.exit(2)
    ok, detail = _sip_entitled(sessions)
    if not ok:
        print("REFUSING: historical consolidated SIP quotes are not readable.")
        print(f"  {detail}")
        print("  The tick multiple needs the consolidated tape. One venue's book")
        print("  is not it, which the 2026-07-28 IEX run proved by failing its")
        print("  own monotonicity check.")
        sys.exit(3)
    print(f"entitlement: {detail}")
    print(f"sessions: {[s['date'] for s in sessions]}")
    strata, excluded_funds = universe()
    n_syms = sum(len(v) for v in strata.values())
    print(f"universe: {n_syms} symbols, funds excluded during build: {excluded_funds}")

    rows, disc = sweep(strata, sessions, "sip")

    # IEX comparison arm: the NEWEST complete session only, same symbols, same
    # windows, one venue's book on purpose. Never enters the fee model. It
    # exists to show the SIP/IEX ratio across the whole sample rather than
    # resting the diagnosis on UFPT alone.
    iex_rows, iex_disc = sweep(strata, sessions[-1:], "iex")

    per = _per_stratum(rows)
    print(f"\n{'stratum':<9}{'n':>5}{'ticks med':>11}{'p75':>7}{'p90':>7}{'bp med':>9}{'bp p90':>9}")
    for k in ("S1", "S2", "S3", "S4"):
        if k not in per: continue
        p = per[k]
        print(f"{k:<9}{p['n']:>5}{p['med']:>11.2f}{p['p75']:>7.2f}{p['p90']:>7.2f}"
              f"{p['bp_med']:>9.2f}{p['bp_p90']:>9.2f}")

    mono = [per[k]["med"] for k in ("S1", "S2", "S3", "S4") if k in per]
    monotone = mono == sorted(mono)
    n_diverse = sum(1 for r in rows if r["diff_venue"] > 0)
    venue_diverse = n_diverse > 0
    print(f"\nSANITY monotone (thinnest widest): {monotone}  ladder {mono}")
    print(f"SANITY venue diversity: {n_diverse}/{len(rows)} rows carry different "
          f"venues on the two sides ({'PASS' if venue_diverse else 'FAIL: single-venue feed'})")
    print(f"discards (sip): {disc}")
    print(f"discards (iex comparison): {iex_disc}")

    # Paired SIP/IEX per-symbol comparison on the shared session.
    shared = sessions[-1]["date"]
    sip_by_sym = {}
    for r in rows:
        if r["session"] == shared:
            sip_by_sym.setdefault(r["symbol"], []).append(r["ticks"])
    pairs = []
    for sym in {r["symbol"] for r in iex_rows}:
        s_t = sip_by_sym.get(sym)
        i_t = [r["ticks"] for r in iex_rows if r["symbol"] == sym]
        if s_t and i_t:
            pairs.append({"symbol": sym, "sip_ticks": st.median(s_t),
                          "iex_ticks": st.median(i_t),
                          "ratio": st.median(i_t) / max(st.median(s_t), 1e-9)})
    if pairs:
        ratios = sorted(p["ratio"] for p in pairs)
        print(f"IEX/SIP ratio over {len(pairs)} shared symbols on {shared}: "
              f"median {st.median(ratios):.1f}x  p25 {ratios[int(.25*(len(ratios)-1))]:.1f}x  "
              f"p75 {ratios[int(.75*(len(ratios)-1))]:.1f}x")

    json.dump({"feed": "sip", "endpoint": "/v2/stocks/{symbol}/quotes (historical)",
               "sessions": [s["date"] for s in sessions],
               "windows": [f"{h:02d}:{m:02d}Z" for h, m in WINDOWS],
               "window_span_s": WINDOW_SPAN_S, "quotes_per_cell": QUOTES_PER_CELL,
               "universe_symbols": n_syms, "funds_excluded": excluded_funds,
               "rows": rows, "discarded": disc, "per_stratum": per,
               "monotone": monotone, "venue_diverse_rows": n_diverse,
               "usable": monotone and venue_diverse,
               "iex_comparison": {"session": shared, "rows": iex_rows,
                                  "discarded": iex_disc, "pairs": pairs}},
              open(sys.argv[1], "w"))
    print(f"\nwrote {sys.argv[1]}  usable={monotone and venue_diverse}")


if __name__ == "__main__":
    main()

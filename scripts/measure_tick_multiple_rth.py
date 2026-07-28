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
    from backtest.universe import WINDOW_SESSIONS, MIN_WINDOW_BARS
    conn = sqlite3.connect("file:analysis_bars.db?mode=ro", uri=True)
    win = [r[0] for r in conn.execute(
        "SELECT date FROM trading_calendar ORDER BY date DESC LIMIT ?", (WINDOW_SESSIONS,))]
    cur = conn.execute(
        "SELECT symbol, close, volume FROM bars WHERE timeframe='1day' AND timestamp>=? "
        "AND timestamp<=? ORDER BY symbol", (min(win), max(win)))
    out, s, cl, dv = [], None, [], []
    def flush():
        if s and len(cl) >= MIN_WINDOW_BARS:
            px = st.median(cl)
            if px >= PRICE_FLOOR:
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


def main():
    if not _open_now():
        print("REFUSING: market is closed. This measurement is only valid inside RTH.")
        sys.exit(2)
    strata = universe()
    allrows, alldisc = [], {}
    for h, m in SWEEPS:
        target = datetime.datetime.now(datetime.timezone.utc).replace(
            hour=h, minute=m, second=0, microsecond=0)
        wait = (target - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        if wait > 0:
            print(f"waiting {wait/60:.0f} min for the {h:02d}:{m:02d} UTC sweep"); time.sleep(wait)
        if not _open_now():
            print(f"skipping {h:02d}:{m:02d}, market closed"); continue
        rows, disc = sweep(strata, f"{h:02d}:{m:02d}Z")
        allrows += rows
        for kk, vv in disc.items(): alldisc[kk] = alldisc.get(kk, 0) + vv
        print(f"sweep {h:02d}:{m:02d}Z  kept {len(rows)}  discarded {disc}")

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
    json.dump({"rows": allrows, "discarded": alldisc, "per_stratum": per,
               "monotone": mono == sorted(mono)}, open(sys.argv[1], "w"))


if __name__ == "__main__":
    main()

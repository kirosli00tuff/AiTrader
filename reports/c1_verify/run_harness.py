"""Run the harness (news_eval.gate.evaluate, news_eval.family.compute) on a synthetic db.

Usage: .venv-eval/bin/python reports/c1_verify/run_harness.py <db> <out.json>
Only the two public entry points are called; nothing in news_eval is modified.
"""
from __future__ import annotations

import json
import sys
import time

from news_eval import family, gate


def main(db: str, out: str) -> None:
    t0 = time.time()
    g = gate.evaluate(db)
    t1 = time.time()
    f = family.compute(db)
    t2 = time.time()
    with open(out, "w") as fh:
        json.dump({"gate": g, "family": f,
                   "timing_s": {"gate": t1 - t0, "family": t2 - t1}},
                  fh, indent=1, sort_keys=True, default=str)
    print(f"{db}: gate {t1 - t0:.1f}s, family {t2 - t1:.1f}s -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

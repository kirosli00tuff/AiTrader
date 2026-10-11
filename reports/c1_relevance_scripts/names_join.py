"""Task 9a issuer names: join the drawn six-column sample to local names.

Reads reports/c1_relevance_sample.csv (the frozen draw's output, untouched),
looks up each distinct symbol in analysis_bars.db universe_asset (read-only,
narrow SELECT of symbol and name), and writes the graders' input file
reports/c1_relevance_grader_input.csv: id, symbol, issuer_name, headline and
name_source (9.13: graders receive the symbol, the issuer name and the
headline). Symbols with no local name are listed in
reports/c1_scratch/task9/missing_names.txt for a web lookup. Prints counts only.
"""
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "reports/c1_relevance_sample.csv"
OUT = ROOT / "reports/c1_relevance_grader_input.csv"
MISSING = ROOT / "reports/c1_scratch/task9/missing_names.txt"
BARS = ROOT / "analysis_bars.db"
SOURCE = "analysis_bars.db universe_asset.name"


def main() -> int:
    with open(SAMPLE, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    symbols = sorted({r["symbol"] for r in rows})
    conn = sqlite3.connect(f"file:{BARS}?mode=ro", uri=True)
    try:
        marks = ",".join("?" * len(symbols))
        names = {s: n for s, n in conn.execute(
            f"SELECT symbol, name FROM universe_asset WHERE symbol IN ({marks})",
            symbols) if n and n.strip()}
    finally:
        conn.close()
    # 9.13: each grader receives the symbol, the issuer name and the headline.
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["id", "symbol", "issuer_name", "headline",
                         "name_source"])
        for r in rows:
            name = names.get(r["symbol"], "")
            writer.writerow([r["id"], r["symbol"], name, r["headline"],
                             SOURCE if name else "MISSING"])
    missing = [s for s in symbols if s not in names]
    MISSING.write_text("".join(f"{s}\n" for s in missing), encoding="utf-8")
    print(f"rows={len(rows)} symbols={len(symbols)} named={len(names)} "
          f"missing_symbols={len(missing)} "
          f"missing_rows={sum(r['symbol'] in set(missing) for r in rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

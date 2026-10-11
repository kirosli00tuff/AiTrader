"""Task 9c: build reports/c1_relevance_final.csv from the two grade files and
the lead's adjudication (reports/c1_relevance_adjudication.md). Agreed rows
keep the shared grade; each disagreement takes the lead's ruling below."""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNNAMED_LIST = "issuer not named in the headline; not one of several named"
RULINGS = {  # id -> (grade, reason <= 12 words)
    "11888": ("off-topic", "California oil policy headline; Sable not named"),
    "15442": ("off-topic", "Generic dividend headline; MGE Energy not named"),
    "19800": ("off-topic", "Independent Bank Corporation is IBCP, not INDB"),
    "22436": ("roundup", "Strategy named beside Strive; one of two named"),
}
inp = list(csv.DictReader(open(ROOT / "reports/c1_relevance_grader_input.csv")))
o = {r["id"]: r for r in csv.DictReader(open(ROOT / "reports/c1_relevance_grades_opus.csv"))}
f = {r["id"]: r for r in csv.DictReader(open(ROOT / "reports/c1_relevance_grades_fable.csv"))}
out = []
for r in inp:
    i = r["id"]
    if o[i]["grade"] == f[i]["grade"]:
        out.append((i, o[i]["grade"], o[i]["reason"], "agreed"))
    elif i in RULINGS:
        out.append((i, *RULINGS[i], "lead"))
    else:
        assert {o[i]["grade"], f[i]["grade"]} == {"roundup", "off-topic"}, i
        out.append((i, "off-topic", UNNAMED_LIST, "lead"))
with open(ROOT / "reports/c1_relevance_final.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["id", "grade", "reason", "source"])
    w.writerows(out)
from collections import Counter
print(len(out), Counter(g for _, g, _, _ in out), Counter(s for *_, s in out))

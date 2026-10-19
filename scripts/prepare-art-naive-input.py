#!/usr/bin/env python3
"""Build the fixed-name input expected by HIVDB-Surv-project/ART-naive.

The ART-naive label here enables its calculation pipeline for every reflist
RefID. It does not change the curated Rx/status stored in datasets.csv.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILENAME = "HIV_References_20260910T230606Z.csv"
COLUMNS = (
    "RefID", "HIVDB_RefID", "Blasthit_RefID", "AuthorYr", "PMID", "Title",
    "Journal", "# in HIVDB (acc)", "# in HIVDB (isol)", "# in GenBank",
    "Annotation", "Additional_Anno", "DateEntered",
)


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        yield from csv.DictReader(source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reflist", type=Path, help="source reflist with ref_id column")
    parser.add_argument("--payload", type=Path, default=ROOT / "payload" / "tables")
    parser.add_argument("--output", type=Path, default=ROOT / "local" / "art-naive-input" / FILENAME)
    args = parser.parse_args()
    articles = {row["ref_id"]: row for row in read_rows(args.payload / "articles.csv")}
    ref_ids = {row["ref_id"].strip() for row in read_rows(args.reflist)}
    if not ref_ids or not all(ref_id.isdigit() for ref_id in ref_ids):
        raise ValueError("The reflist must contain numeric ref_id values")
    missing = ref_ids - articles.keys()
    if missing:
        raise ValueError(f"RefIDs missing from articles.csv: {', '.join(sorted(missing, key=int))}")
    rows = []
    for ref_id in sorted(ref_ids, key=int):
        article = articles[ref_id]
        rows.append({
            "RefID": f'S{article["ref_id"]}',
            "HIVDB_RefID": article["ref_id"],
            "Blasthit_RefID": "",
            "AuthorYr": f'{article["first_author"]} ({article["year"]})',
            "PMID": article["medline_id"] if article["medline_id"] != "NULL" else "",
            "Title": article["title"],
            "Journal": article["journal_name"],
            "# in HIVDB (acc)": "",
            "# in HIVDB (isol)": "",
            "# in GenBank": "",
            "Annotation": "ART-naive",
            "Additional_Anno": "",
            "DateEntered": "",
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: int(row["HIVDB_RefID"])))
    print(f"Wrote all {len(rows)} reflist RefIDs to {args.output}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Compare table-facing SQLite counts with the ART-naive reference report."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT.parents[1] / "HIVDB-Surv-project" / "ART-naive"
CLASSES = {"NRTI": "NRTIs", "NNRTI": "NNRTIs", "PI": "PIs", "INSTI": "INSTI"}
GENES = {"PR": "TotalPR", "RT": "TotalRT", "IN": "TotalIN", "CA": "TotalCA"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, nargs="?", default=ROOT / "build" / "hiv-survdb-local.db")
    parser.add_argument("--report", type=Path, default=ART / "report" / "reference_sdrm_summary_with_treatment.csv")
    parser.add_argument("--reflist", type=Path, help="require every reflist ref_id in articles and table patterns")
    args = parser.parse_args()
    with args.report.open(encoding="utf-8-sig", newline="") as source:
        expected = {row["RefID"]: row for row in csv.DictReader(source)}

    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("SQLite integrity_check failed")
    if args.reflist:
        with args.reflist.open(encoding="utf-8-sig", newline="") as source:
            required = {row["ref_id"].strip() for row in csv.DictReader(source)}
        article_ids = {str(row[0]) for row in connection.execute("SELECT ref_id FROM articles")}
        active_ids = {str(row[0]) for row in connection.execute("""
            SELECT DISTINCT R.ref_id FROM dataset_patterns DP
            JOIN datasets D ON D.dataset_name=DP.dataset_name
            JOIN articles R ON R.ref_name=D.ref_name
        """)}
        missing_articles = required - article_ids
        missing_patterns = required - active_ids
        if missing_articles or missing_patterns:
            raise ValueError(
                f"Missing RefIDs: articles={sorted(missing_articles, key=int)}, "
                f"table patterns={sorted(missing_patterns, key=int)}"
            )
        print(f"All {len(required)} reflist RefIDs have articles and table patterns")
    query = """
      SELECT R.ref_id, DP.num_isolates, P.pattern_id,
             GROUP_CONCAT(DISTINCT PG.gene) AS genes,
             GROUP_CONCAT(DISTINCT S.drug_class) AS drug_classes
      FROM dataset_patterns DP
      JOIN patterns P ON P.pattern_id = DP.pattern_id
      JOIN datasets D ON D.dataset_name = DP.dataset_name
      JOIN articles R ON R.ref_name = D.ref_name
      LEFT JOIN pattern_genes PG ON PG.pattern_id = P.pattern_id
      LEFT JOIN pattern_surv_mutations PM ON PM.pattern_id = P.pattern_id
      LEFT JOIN surv_mutations S ON S.mutation = PM.mutation
      WHERE D.status LIKE '%ART-naive%'
      GROUP BY R.ref_id, DP.dataset_name, P.pattern_id, DP.num_isolates
    """
    actual = {}
    for row in connection.execute(query):
        ref = str(row["ref_id"])
        counts = actual.setdefault(ref, {key: 0 for key in (
            "TotalIsolates", "Any", *GENES.values(), *CLASSES.values()
        )})
        n = row["num_isolates"]
        counts["TotalIsolates"] += n
        for gene in (row["genes"] or "").split(","):
            if gene in GENES:
                counts[GENES[gene]] += n
        classes = (row["drug_classes"] or "").split(",")
        if any(drug_class in CLASSES for drug_class in classes):
            counts["Any"] += n
        for drug_class in classes:
            if drug_class in CLASSES:
                counts[CLASSES[drug_class]] += n

    errors = []
    for ref, counts in actual.items():
        if ref not in expected:
            errors.append(f"RefID {ref} absent from report")
            continue
        for column, value in counts.items():
            if value != int(expected[ref][column]):
                errors.append(f"RefID {ref} {column}: SQLite {value}, report {expected[ref][column]}")
    print(f"Compared {len(actual)} ART-naive references against {args.report}")
    if errors:
        print("\n".join(errors[:30]))
        raise SystemExit(f"{len(errors)} count mismatches")
    print("All isolate, gene, and SDRM-positive counts match")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Audit a reflist against the curated article and dataset tables."""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reflist", type=Path)
    parser.add_argument("--report", type=Path, help="write every affected row to a CSV file")
    args = parser.parse_args()

    reflist = read_csv(args.reflist.expanduser())
    articles = read_csv(Path("payload/tables/articles.csv"))
    datasets = read_csv(Path("payload/tables/datasets.csv"))
    if not reflist:
        print("Reflist is empty", file=sys.stderr)
        return 2
    if not {"ref_name", "ref_id"}.issubset(reflist[0]):
        print("Reflist must have ref_name and ref_id columns", file=sys.stderr)
        return 2

    article_by_name = {row["ref_name"]: row["ref_id"] for row in articles}
    article_by_id = {row["ref_id"]: row["ref_name"] for row in articles}
    dataset_names = {row["dataset_name"] for row in datasets}
    datasets_by_ref = {}
    for row in datasets:
        datasets_by_ref.setdefault(row["ref_name"], []).append(row["dataset_name"])
    names = Counter(row["ref_name"] for row in reflist)
    repeated = sorted(name for name, count in names.items() if count > 1)
    missing_articles = sorted({name for name in names if name not in article_by_name})
    missing_datasets = sorted({name for name in names if name not in datasets_by_ref})
    mapped_datasets = sorted({
        name for name in names
        if name in datasets_by_ref and name not in dataset_names
    })
    mismatched_ids = sorted({
        (row["ref_name"], row["ref_id"], article_by_name[row["ref_name"]])
        for row in reflist
        if row["ref_name"] in article_by_name
        and row["ref_id"] != article_by_name[row["ref_name"]]
    })
    renamed_ids = sorted({
        (row["ref_name"], row["ref_id"], article_by_id[row["ref_id"]])
        for row in reflist
        if row["ref_name"] not in article_by_name
        and row["ref_id"] in article_by_id
    })

    if args.report:
        report_path = args.report.expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "record_number", "ref_name", "ref_id", "issues",
                "article_ref_id", "article_ref_name_for_id",
                "dataset_names_for_ref", "dataset_name_matches_ref",
            ])
            writer.writeheader()
            for number, row in enumerate(reflist, start=1):
                name = row["ref_name"]
                ref_id = row["ref_id"]
                issues = []
                if names[name] > 1:
                    issues.append("repeated_ref_name")
                if name not in article_by_name:
                    issues.append("absent_from_articles")
                elif ref_id != article_by_name[name]:
                    issues.append("ref_id_differs_from_article")
                if name not in datasets_by_ref:
                    issues.append("absent_from_datasets")
                elif name not in dataset_names:
                    issues.append("dataset_name_differs_from_ref")
                if ref_id in article_by_id and article_by_id[ref_id] != name:
                    issues.append("ref_id_has_another_article_name")
                if not name:
                    issues.append("blank_ref_name")
                if not ref_id:
                    issues.append("blank_ref_id")
                if issues:
                    writer.writerow({
                        "record_number": number,
                        "ref_name": name,
                        "ref_id": ref_id,
                        "issues": ";".join(issues),
                        "article_ref_id": article_by_name.get(name, ""),
                        "article_ref_name_for_id": article_by_id.get(ref_id, ""),
                        "dataset_names_for_ref": ";".join(datasets_by_ref.get(name, [])),
                        "dataset_name_matches_ref": name in dataset_names,
                    })

    print(f"Reflist: {len(reflist)} rows, {len(names)} distinct ref_name values")
    for label, values in (
        ("Repeated ref_name", repeated),
        ("Absent from articles.csv", missing_articles),
        ("Absent from datasets.csv", missing_datasets),
        ("Has dataset rows under other dataset_name values", mapped_datasets),
        ("RefID differs from articles.csv (reflist ID, article ID)", mismatched_ids),
        ("Same RefID uses another article ref_name (reflist name, ID, article name)", renamed_ids),
    ):
        print(f"{label}: {len(values)}")
        for value in values[:10]:
            print(f"  {value}")
        if len(values) > 10:
            print(f"  ... {len(values) - 10} more")
    if args.report:
        print(f"Full row-level report: {report_path}")
    return 1 if any((repeated, missing_articles, missing_datasets,
                     mapped_datasets, mismatched_ids)) else 0


if __name__ == "__main__":
    raise SystemExit(main())

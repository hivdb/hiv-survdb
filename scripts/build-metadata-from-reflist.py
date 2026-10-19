#!/usr/bin/env python3
"""Build article, dataset, and journal CSVs from a prepared reflist."""

import argparse
import csv
from collections import defaultdict
from pathlib import Path


CONTINENTS = {
    "Africa", "Asia", "Europe", "North America", "Oceania", "South America"
}
RX_VALUES = {
    "ART-naive", "INSTI-naive", "ART-naive;INSTI-naive",
    "PI-naive", "INSTI-naive;PI-naive",
}
ARTICLE_FIELDS = (
    "ref_name", "ref_id", "doi", "medline_id", "url", "first_author",
    "title", "journal_name", "year", "published",
)
DATASET_FIELDS = (
    "dataset_name", "ref_name", "continent_name", "status", "annotation",
    "action", "url",
)
SOURCE_FIELDS = ("ref_name", "ref_id", "Author", "Title", "Journal", "RefYear", "PMID", "Rx", "Cont")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"Empty CSV: {path}")
        return list(reader)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reflist", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("local/metadata-preview"))
    args = parser.parse_args()
    reflist = read_csv(args.reflist.expanduser())
    if not reflist or not set(SOURCE_FIELDS) <= reflist[0].keys():
        parser.error(f"reflist needs: {', '.join(SOURCE_FIELDS)}")

    old_articles = read_csv(Path("payload/tables/articles.csv"))
    old_by_id = {row["ref_id"]: row for row in old_articles}
    old_journals = read_csv(Path("payload/tables/journals.csv"))
    refs = {}
    names = {}
    for line, row in enumerate(reflist, start=2):
        key = row["ref_id"]
        if not key.isdecimal() or not row["ref_name"]:
            parser.error(f"line {line}: blank name or invalid RefID")
        if not row["RefYear"].isdecimal() or not row["Journal"]:
            parser.error(f"line {line}: missing year or journal")
        if row["Rx"] not in RX_VALUES:
            parser.error(f"line {line}: unsupported Rx {row['Rx']!r}")
        parts = {part.strip() for part in row["Cont"].split(",")}
        if not parts or parts - (CONTINENTS | {"Central America"}):
            parser.error(f"line {line}: invalid Cont {row['Cont']!r}")
        if key in refs and any(refs[key][field] != row[field] for field in SOURCE_FIELDS):
            parser.error(f"line {line}: RefID {key} has conflicting metadata")
        if row["ref_name"] in names and names[row["ref_name"]] != key:
            parser.error(f"line {line}: {row['ref_name']} has multiple RefIDs")
        refs[key] = row
        names[row["ref_name"]] = key

    articles = []
    datasets = []
    for row in sorted(refs.values(), key=lambda value: value["ref_name"].casefold()):
        name = row["ref_name"]
        previous = old_by_id.get(row["ref_id"], {})
        articles.append({
            "ref_name": name,
            "ref_id": row["ref_id"],
            "doi": previous.get("doi", "NULL") or "NULL",
            "medline_id": row["PMID"] or "NULL",
            "url": previous.get("url", "NULL") or "NULL",
            "first_author": row["Author"],
            "title": row["Title"],
            "journal_name": row["Journal"],
            "year": row["RefYear"],
            "published": previous.get("published") or (
                "FALSE" if row["Journal"] == "Direct Genbank Submission" else "TRUE"
            ),
        })
        continents = {
            "North America" if part.strip() == "Central America" else part.strip()
            for part in row["Cont"].split(",")
        }
        for continent in sorted(continents):
            datasets.append({
                "dataset_name": name if len(continents) == 1 else f"{name}-{continent}",
                "ref_name": name,
                "continent_name": continent,
                "status": row["Rx"],
                "annotation": "",
                "action": "NULL",
                "url": "NULL",
            })

    pmids = [row["medline_id"] for row in articles if row["medline_id"] != "NULL"]
    if len(pmids) != len(set(pmids)):
        parser.error("nonempty PMID occurs in multiple articles")
    dataset_names = [row["dataset_name"] for row in datasets]
    if len(dataset_names) != len(set(dataset_names)):
        parser.error("generated dataset_name collision")
    journal_names = {row["journal_name"] for row in old_journals}
    journal_names.update(row["journal_name"] for row in articles)
    journals = [{"journal_name": name} for name in sorted(journal_names, key=str.casefold)]

    output = args.output_dir.expanduser()
    write_csv(output / "articles.csv", ARTICLE_FIELDS, articles)
    write_csv(output / "datasets.csv", DATASET_FIELDS, datasets)
    write_csv(output / "journals.csv", ("journal_name",), journals)
    print(
        f"Wrote {len(articles)} articles, {len(datasets)} datasets, "
        f"and {len(journals)} journals to {output}"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Split imported isolate CSVs by dataset continent and remove stale files."""

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


TABLES = Path("payload/tables")
ISOLATES = TABLES / "isolates.d"
NORTH_AMERICA_OVERRIDES = {
    # The payload country table currently puts Central America and the Caribbean
    # under South America. The prepared reflist treats them as Central America.
    "ATG", "BHS", "BLZ", "BRB", "CRI", "CUB", "DMA", "DOM", "GRD",
    "GTM", "HND", "HTI", "JAM", "KNA", "LCA", "MEX", "MSR", "NIC",
    "PAN", "PRI", "SLV", "TTO", "VCT",
}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def filename(name):
    return re.sub(r"['\"]", "", re.sub(r"\s+", "-", name.lower())) + "-iso.csv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write split files and prune stale files")
    args = parser.parse_args()

    _, articles = read_csv(TABLES / "articles.csv")
    _, datasets = read_csv(TABLES / "datasets.csv")
    _, countries = read_csv(TABLES / "countries.csv")
    article_names = {row["ref_name"] for row in articles}
    datasets_by_ref = defaultdict(dict)
    for row in datasets:
        name, ref_name, continent = row["dataset_name"], row["ref_name"], row["continent_name"]
        if ref_name not in article_names:
            parser.error(f"dataset {name} has no article {ref_name}")
        if continent in datasets_by_ref[ref_name]:
            parser.error(f"duplicate continent {continent} for {ref_name}")
        datasets_by_ref[ref_name][continent] = name

    continent_by_country = {
        row["country_code"]: row.get("continent_name", row.get("countinent_name"))
        for row in countries
    }
    continent_by_country.update({code: "North America" for code in NORTH_AMERICA_OVERRIDES})
    outputs = {}
    errors = []
    counts = defaultdict(int)
    for ref_name in sorted(article_names, key=str.casefold):
        path = ISOLATES / filename(ref_name)
        if not path.exists():
            errors.append(f"missing imported file: {path}")
            continue
        columns, rows = read_csv(path)
        if not rows or "dataset_name" not in columns or "country_code" not in columns:
            errors.append(f"empty or malformed imported file: {path}")
            continue
        if any(row["dataset_name"] != ref_name for row in rows):
            errors.append(f"unexpected dataset_name in {path}")
            continue
        choices = datasets_by_ref.get(ref_name, {})
        if not choices:
            errors.append(f"no dataset metadata for {ref_name}")
            continue
        for row in rows:
            if row["gene"] not in {"PR", "RT", "IN"}:
                continue
            country = row["country_code"]
            if country not in continent_by_country:
                errors.append(f"{ref_name}: unknown country_code {country!r}")
                continue
            continent = continent_by_country[country]
            if len(choices) == 1:
                # A one-continent study keeps the importer's name. Some legacy
                # country assignments disagree with the source study's Cont.
                dataset_name = next(iter(choices.values()))
            else:
                dataset_name = choices.get(continent)
                if not dataset_name:
                    errors.append(
                        f"{ref_name}: {country} maps to {continent}, outside "
                        f"{', '.join(sorted(choices))}"
                    )
                    continue
            target = ISOLATES / filename(dataset_name)
            outputs.setdefault(target, (columns, []))[1].append({**row, "dataset_name": dataset_name})
            counts[dataset_name] += 1

    expected = {row["dataset_name"] for row in datasets}
    empty = sorted(expected - counts.keys())
    if empty:
        errors.append(f"{len(empty)} datasets have no isolates: {', '.join(empty[:30])}")
    if errors:
        print(f"Reconciliation stopped with {len(errors)} issues:")
        for error in errors[:80]:
            print("  " + error)
        if len(errors) > 80:
            print(f"  ... and {len(errors) - 80} more")
        return 1

    existing = set(ISOLATES.glob("*-iso.csv"))
    stale = existing - outputs.keys()
    print(
        f"Prepared {len(outputs)} isolate files for {len(expected)} datasets; "
        f"{len(stale)} stale files to remove"
    )
    if args.apply:
        # Write all new files before deleting any old file. The caller should
        # save a backup of the payload tables before running this option.
        for path, (columns, rows) in outputs.items():
            write_csv(path, columns, rows)
        for path in stale:
            path.unlink()
        print("Isolate files reconciled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

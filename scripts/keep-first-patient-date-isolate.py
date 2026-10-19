#!/usr/bin/env python3
"""Keep one isolate per patient/gene/date, using sorted file and row order."""

import argparse
import csv
import os
import tempfile
from collections import defaultdict
from pathlib import Path


DIRECTORY = Path("payload/tables/isolates.d")
KEY_COLUMNS = ("patient_id", "gene", "isolate_date")
PRIMARY_KEY_COLUMNS = ("dataset_name", "isolate_name", "gene")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="rewrite affected CSV files")
    args = parser.parse_args()

    files = {}
    groups = defaultdict(list)
    for path in sorted(DIRECTORY.glob("*-iso.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames
            rows = list(reader)
        if not columns or not set(KEY_COLUMNS + PRIMARY_KEY_COLUMNS) <= set(columns):
            parser.error(f"missing required columns in {path}")
        files[path] = (columns, rows)
        for index, row in enumerate(rows):
            if not row["isolate_date"] or row["isolate_date"] == "NULL":
                parser.error(f"missing isolate_date in {path}, row {index + 2}")
            groups[tuple(row[column] for column in KEY_COLUMNS)].append((path, index))

    keep = {path: set(range(len(rows))) for path, (_, rows) in files.items()}
    removed = 0
    for locations in groups.values():
        if len(locations) == 1:
            continue
        for path, index in locations[1:]:
            keep[path].remove(index)
            removed += 1

    primary_keys = set()
    for path, (_, rows) in files.items():
        for index in keep[path]:
            row = rows[index]
            primary_key = tuple(row[column] for column in PRIMARY_KEY_COLUMNS)
            if primary_key in primary_keys:
                parser.error(f"primary key collision after deduplication: {primary_key}")
            primary_keys.add(primary_key)

    affected = [
        path for path, (_, rows) in files.items()
        if len(keep[path]) != len(rows)
    ]
    if args.apply:
        for path in affected:
            columns, rows = files[path]
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8-sig", newline="", dir=DIRECTORY,
                    prefix=path.name + ".", suffix=".tmp", delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    writer = csv.DictWriter(handle, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(row for index, row in enumerate(rows) if index in keep[path])
                os.replace(temporary, path)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()

    verb = "Removed" if args.apply else "Would remove"
    print(f"{verb} {removed} rows from {len(affected)} files")


if __name__ == "__main__":
    main()

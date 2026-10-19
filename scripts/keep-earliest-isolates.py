#!/usr/bin/env python3
"""Keep the earliest row for each dataset/isolate/gene key."""

import argparse
import csv
import os
import tempfile
from pathlib import Path


DIRECTORY = Path("payload/tables/isolates.d")
KEY_COLUMNS = ("dataset_name", "isolate_name", "gene")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="rewrite affected CSV files")
    args = parser.parse_args()

    affected = 0
    removed = 0
    same_date_ties = 0
    for path in sorted(DIRECTORY.glob("*-iso.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames
            rows = list(reader)
        if not columns or not set(KEY_COLUMNS + ("isolate_date",)) <= set(columns):
            parser.error(f"missing required columns in {path}")

        winner = {}
        for index, row in enumerate(rows):
            key = tuple(row[name] for name in KEY_COLUMNS)
            date = row["isolate_date"]
            if not date or date == "NULL":
                parser.error(f"missing isolate_date in {path}, row {index + 2}")
            previous = winner.get(key)
            if previous is None or date < rows[previous]["isolate_date"]:
                winner[key] = index
            elif date == rows[previous]["isolate_date"]:
                same_date_ties += 1

        if len(winner) == len(rows):
            continue
        affected += 1
        removed += len(rows) - len(winner)
        if not args.apply:
            continue
        kept_indexes = set(winner.values())
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8-sig", newline="", dir=DIRECTORY,
                prefix=path.name + ".", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(row for index, row in enumerate(rows) if index in kept_indexes)
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    verb = "Removed" if args.apply else "Would remove"
    print(f"{verb} {removed} rows from {affected} files; {same_date_ties} equal-date ties kept in CSV order")


if __name__ == "__main__":
    main()

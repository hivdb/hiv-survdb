#!/usr/bin/env python3
"""Remove imported isolate genes outside the PR/RT/IN database schema."""

import argparse
import csv
import os
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    directory = Path("payload/tables/isolates.d")
    affected = []
    removed = 0
    for path in sorted(directory.glob("*-iso.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames
            rows = list(reader)
        kept = [row for row in rows if row["gene"] in {"PR", "RT", "IN"}]
        if len(kept) == len(rows):
            continue
        removed += len(rows) - len(kept)
        affected.append(path.name)
        if args.apply:
            if not kept:
                path.unlink()
                continue
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8-sig", newline="", dir=directory,
                    prefix=path.name + ".", suffix=".tmp", delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    writer = csv.DictWriter(handle, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(kept)
                os.replace(temporary, path)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
    print(f"{'Removed' if args.apply else 'Would remove'} {removed} rows from {len(affected)} files")
    if affected:
        print("Affected files: " + ", ".join(affected[:12]))


if __name__ == "__main__":
    main()

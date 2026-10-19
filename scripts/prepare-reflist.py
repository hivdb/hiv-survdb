#!/usr/bin/env python3
"""Fix shifted continents and give distinct HIVDB references distinct names."""

import argparse
import csv
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path


SOURCE_VALUES = {"Plasma", "PBMC", "Dried Blood Spot"}
CONTINENTS = {
    "Africa", "Asia", "Europe", "North America", "Oceania",
    "South America", "Central America",
}


def suffix(index):
    """Return a, b, ..., z, aa, ab, ... for a zero-based index."""
    value = ""
    while True:
        index, remainder = divmod(index, 26)
        value = chr(97 + remainder) + value
        if index == 0:
            return value
        index -= 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?", help="defaults to input (in place)")
    args = parser.parse_args()
    input_path = args.input.expanduser()
    output = args.output.expanduser() if args.output else input_path

    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows or not {"ref_name", "ref_id", "Iso", "Cont"}.issubset(rows[0]):
        parser.error("input must contain ref_name, ref_id, Iso, and Cont columns")
    columns = {name: rows[0].index(name) for name in ("ref_name", "ref_id", "Iso", "Cont")}

    ids_by_name = defaultdict(set)
    for number, row in enumerate(rows[1:], start=2):
        if len(row) <= max(columns.values()):
            parser.error(f"row {number} is incomplete")
        name, ref_id = row[columns["ref_name"]], row[columns["ref_id"]]
        if not name or not ref_id.isdecimal():
            parser.error(f"row {number} has invalid ref_name or ref_id")
        ids_by_name[name].add(ref_id)

    original_names = set(ids_by_name)
    replacements = {}
    for name, ids in ids_by_name.items():
        if len(ids) > 1:
            for index, ref_id in enumerate(sorted(ids, key=int)):
                new_name = name + suffix(index)
                if new_name in original_names:
                    parser.error(f"generated name already exists: {new_name}")
                replacements[(name, ref_id)] = new_name

    fixed_cont = 0
    renamed_rows = 0
    for number, row in enumerate(rows[1:], start=2):
        name, ref_id = row[columns["ref_name"]], row[columns["ref_id"]]
        new_name = replacements.get((name, ref_id))
        if new_name:
            row[columns["ref_name"]] = new_name
            renamed_rows += 1
        sources = {part.strip() for part in row[columns["Cont"]].split(",")}
        if sources and sources <= SOURCE_VALUES:
            continents = {part.strip() for part in row[columns["Iso"]].split(",")}
            if not continents or not continents <= CONTINENTS:
                parser.error(f"row {number}: cannot recover Cont from Iso={row[columns['Iso']]!r}")
            row[columns["Cont"]] = row[columns["Iso"]]
            fixed_cont += 1

    if output.resolve() == input_path.resolve():
        if not fixed_cont and not renamed_rows:
            print("No changes needed")
            return
        backup = input_path.with_name(input_path.name + ".bak")
        if backup.exists():
            parser.error(f"backup already exists: {backup}")
        shutil.copy2(input_path, backup)
        print(f"Saved original as {backup}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8-sig", newline="", dir=output.parent,
            prefix=output.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            csv.writer(handle).writerows(rows)
        os.replace(temporary, output)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    print(
        f"Fixed Cont in {fixed_cont} rows; renamed {renamed_rows} rows "
        f"across {len({name for name, _ in replacements})} conflicting names; wrote {output}"
    )


if __name__ == "__main__":
    main()

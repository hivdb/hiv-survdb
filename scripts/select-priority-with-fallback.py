#!/usr/bin/env python3
"""Select priority-1 links, falling back to priority-0 only when necessary.

The source surveillance workflows select only Priority=1. A small number of
curated RefIDs have no such links; without this explicit fallback they cannot
appear in the table despite having eligible clinical HIV-1 isolates.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ART_ROOT = ROOT / "local" / "art-method-run" / "ART-naive"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--art-root", type=Path, default=DEFAULT_ART_ROOT)
    args = parser.parse_args()
    matches = list((args.art_root / "step_output" / "09_exclude_isolate_filters").glob("*isolate-filters-filtered.csv"))
    if len(matches) != 1:
        raise ValueError(f"Expected one step-9 filtered CSV, found {len(matches)}")
    with matches[0].open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = reader.fieldnames
        if not fieldnames or not {"RefID", "IsolateID", "Priority"}.issubset(fieldnames):
            raise ValueError("Step-9 CSV lacks RefID, IsolateID, or Priority")
        groups = defaultdict(list)
        for row in reader:
            groups[row["RefID"]].append(row)
    selected = []
    fallback = []
    for ref_id in sorted(groups, key=int):
        rows = groups[ref_id]
        priorities = {row["Priority"] for row in rows}
        if not priorities <= {"0", "1"}:
            raise ValueError(f"Invalid Priority for RefID {ref_id}: {priorities}")
        priority = "1" if "1" in priorities else "0"
        kept = [row for row in rows if row["Priority"] == priority]
        selected.extend(kept)
        if priority == "0":
            fallback.append((ref_id, len(kept)))
    out = args.art_root / "step_output" / "08_select_refid_priority"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "reference_patient_regions_priority_selected.csv").open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)
    with (out / "priority-zero-fallback-refids.csv").open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(("RefID", "SelectedIsolates"))
        writer.writerows(fallback)
    print(f"Selected {len(selected)} isolates for {len(groups)} RefIDs; {len(fallback)} used Priority=0 fallback")
    if fallback:
        print("Fallback RefIDs: " + ", ".join(ref_id for ref_id, _ in fallback))


if __name__ == "__main__":
    main()

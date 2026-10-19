#!/usr/bin/env python3
"""List calculated mutation CSVs for all curated datasets."""

import csv
import re
from pathlib import Path


tables = Path("payload/tables")
with (tables / "datasets.csv").open(encoding="utf-8-sig", newline="") as source:
    datasets = csv.DictReader(source)
    for row in datasets:
        stem = re.sub(r"\s+", "-", row["dataset_name"].lower().replace("'", "").replace('"', ""))
        path = tables / "isolate_mutations.d" / f"{stem}-isomuts.csv"
        if path.is_file():
            print(path)

#!/usr/bin/env python3
"""Map one permanent CPR report per ref_name to all of its datasets."""

import argparse
import csv
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DATASETS = Path("payload/tables/datasets.csv")
PREVIEW = Path("local/cpr-ref-report-links-preview.csv")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def slug(name):
    return re.sub(r"\s+", "-", name.lower()).replace("'", "").replace('"', "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urls", type=Path, default=Path("local/cpr-reports/permanent_urls.csv"))
    parser.add_argument("--output", type=Path, default=Path("local/cpr-ref-links-mapping.csv"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    preview = read_csv(PREVIEW)
    refs = {row["dataset_name"]: row for row in preview}
    if len(refs) != len(preview):
        parser.error("duplicate ref_name in CPR preview")
    try:
        links = {}
        for row in read_csv(args.urls):
            ref = row["ref_name"] if "ref_name" in row else row["dataset_name"]
            if ref not in refs or ref in links:
                raise ValueError(f"unexpected or duplicate ref_name: {ref}")
            url = row["url"].strip()
            parsed = urlparse(url)
            load = parse_qs(parsed.query).get("load", [])
            if (parsed.scheme != "https" or parsed.netloc != "hivdb.stanford.edu"
                    or parsed.path != "/cpr/report/" or load != [f"hiv-survdb/{slug(ref)}"]):
                raise ValueError(f"invalid permanent CPR URL for {ref}: {url}")
            links[ref] = url
        if len(set(links.values())) != len(links):
            raise ValueError("two references share a CPR URL")
        datasets = read_csv(DATASETS)
        mapping = []
        for row in datasets:
            ref = row["ref_name"]
            if ref not in refs:
                raise ValueError(f"dataset has no reference CPR input: {row['dataset_name']}")
            mapping.append({"dataset_name": row["dataset_name"], "ref_name": ref,
                            "continent_name": row["continent_name"],
                            "report_url": links.get(ref, "")})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=mapping[0])
            writer.writeheader()
            writer.writerows(mapping)
        if args.apply:
            if set(links) != set(refs):
                raise ValueError(f"cannot apply: {len(set(refs) - set(links))} reference URLs missing")
            for row in datasets:
                row["url"] = links[row["ref_name"]]
            temporary = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="",
                                             dir=DATASETS.parent, prefix="datasets.",
                                             suffix=".tmp", delete=False) as handle:
                    temporary = Path(handle.name)
                    writer = csv.DictWriter(handle, fieldnames=datasets[0])
                    writer.writeheader()
                    writer.writerows(datasets)
                os.replace(temporary, DATASETS)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
            print(f"Applied {len(links)} reference URLs to {len(datasets)} datasets")
        print(f"Wrote {args.output}: {len(links)}/{len(refs)} reference URLs")
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()

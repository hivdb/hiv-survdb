#!/usr/bin/env python3
"""Apply one permanent CPR report URL per SurvDB dataset."""

import argparse
import csv
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DATASETS = Path("payload/tables/datasets.csv")
PREVIEW = Path("local/cpr-report-links-preview.csv")
URLS = Path("local/cpr-reports/permanent_urls.csv")
URL_PREFIX = "hiv-survdb/"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def apply_links(datasets, preview, links):
    expected = {row["dataset_name"]: row for row in preview}
    if len(expected) != len(preview):
        raise ValueError("duplicate dataset in CPR preview")
    if set(expected) != {row["dataset_name"] for row in datasets}:
        raise ValueError("CPR preview and datasets.csv contain different datasets")
    if len(links) != len(set(links)):
        raise ValueError("duplicate dataset CPR URL")
    for row in datasets:
        name = row["dataset_name"]
        preview_row = expected[name]
        url = links.get(name, "")
        if preview_row["report_status"] == "no POL genes":
            if url:
                raise ValueError(f"CA-only dataset has a POL CPR report: {name}")
            row["url"] = ""
            continue
        if not url:
            raise ValueError(f"missing CPR report for dataset: {name}")
        slug = preview_row["fasta_file"].removesuffix("-seq.fas")
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.netloc != "hivdb.stanford.edu"
                or parsed.path != "/cpr/report/"
                or parse_qs(parsed.query).get("load") != [URL_PREFIX + slug]):
            raise ValueError(f"incorrect CPR report for dataset {name}: {url}")
        row["url"] = url
    if set(links) != {name for name, row in expected.items()
                      if row["report_status"] != "no POL genes"}:
        raise ValueError("CPR links contain missing or unexpected datasets")
    return datasets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path, default=PREVIEW)
    parser.add_argument("--urls", type=Path, default=URLS)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    datasets = read_csv(DATASETS)
    preview = read_csv(args.preview)
    url_rows = read_csv(args.urls)
    links = {row["dataset_name"]: row["url"] for row in url_rows}
    if len(links) != len(url_rows):
        parser.error("duplicate dataset in permanent_urls.csv")
    try:
        datasets = apply_links(datasets, preview, links)
    except ValueError as exc:
        parser.error(str(exc))
    if args.apply:
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
        print(f"Applied {len(links)} dataset CPR URLs to {len(datasets)} datasets")
    else:
        print(f"Validated {len(links)} dataset CPR URLs for {len(datasets)} datasets")


if __name__ == "__main__":
    main()

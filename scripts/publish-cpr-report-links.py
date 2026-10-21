#!/usr/bin/env python3
"""Copy verified CPR report assets to permanent S3 keys and record URLs."""

import argparse
import csv
import hashlib
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


BUCKET = "cprstorage"
URL_PREFIX = "https://hivdb.stanford.edu/cpr/report/?load=hiv-survdb/"


def aws(*arguments):
    command = ["aws", "s3api", *arguments, "--output", "json"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{' '.join(command[:4])}: {result.stderr.strip()}")
    return json.loads(result.stdout or "{}")


def head(key):
    return aws("head-object", "--bucket", BUCKET, "--key", key)


def copy_asset(kind, uuid, slug):
    source = f"{kind}/{uuid}"
    target = f"{kind}/hiv-survdb/{slug}"
    for attempt in range(4):
        original = head(source)
        if original["ContentLength"] == 0:
            raise RuntimeError(f"empty CPR asset: {source}")
        aws("copy-object", "--bucket", BUCKET, "--copy-source", f"{BUCKET}/{source}",
            "--key", target, "--metadata-directive", "COPY")
        copied = head(target)
        latest = head(source)
        if copied["ETag"] == latest["ETag"] and copied["ContentLength"] == latest["ContentLength"]:
            return
        if attempt < 3:
            time.sleep(2)
    raise RuntimeError(f"source CPR asset changed during copy: {source}")


def write_links(output_dir, preview):
    rows = []
    for row in preview:
        slug = row["fasta_file"][:-8]
        path = output_dir / "permanent" / f"{slug}.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["fasta_sha256"] != row["fasta_sha256"]:
                raise ValueError(f"stale permanent link for {row['dataset_name']}")
            rows.append((data["dataset_name"], data["url"]))
    path = output_dir / "permanent_urls.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("dataset_name", "url"))
        writer.writerows(rows)
    return len(rows), path


def publish_one(index, total, row, args):
    dataset = row["dataset_name"]
    slug = row["fasta_file"][:-8]
    fasta = args.fasta_dir / row["fasta_file"]
    digest = hashlib.sha256(fasta.read_bytes()).hexdigest()
    receipt = json.loads((args.output_dir / "receipts" / f"{slug}.json").read_text())
    if digest != row["fasta_sha256"] or digest != receipt["fasta_sha256"]:
        raise ValueError(f"FASTA changed since report submission: {dataset}")
    output = args.output_dir / "permanent" / f"{slug}.json"
    if output.is_file():
        existing = json.loads(output.read_text())
        if existing["process_key"] != receipt["process_key"]:
            raise ValueError(f"published link has a different process key: {dataset}")
        return f"SKIP {dataset}: {existing['url']}"
    for kind in ("main", "tree"):
        copy_asset(kind, receipt["process_key"], slug)
    url = URL_PREFIX + slug
    output.write_text(json.dumps({"dataset_name": dataset, "fasta_sha256": digest,
                                  "process_key": receipt["process_key"], "url": url}),
                      encoding="utf-8")
    return f"PUBLISHED {index}/{total} {dataset}: {url}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path, default=Path("local/cpr-ref-report-links-preview.csv"))
    parser.add_argument("--fasta-dir", type=Path, default=Path("local/cpr-fasta-ref"))
    parser.add_argument("--output-dir", type=Path, default=Path("local/cpr-reports"))
    parser.add_argument("--dataset", help="publish one ref_name from the preview")
    parser.add_argument("--available", action="store_true",
                        help="publish only reports with saved receipts so far")
    parser.add_argument("--workers", type=int, default=4,
                        help="number of references to copy to S3 concurrently")
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 8:
        parser.error("workers must be 1-8")
    with args.preview.open(encoding="utf-8", newline="") as handle:
        preview = [row for row in csv.DictReader(handle) if row["report_status"] != "no POL genes"]
    selected = [row for row in preview if not args.dataset or row["dataset_name"] == args.dataset]
    if not selected:
        parser.error(f"no POL dataset named {args.dataset}")
    if args.available:
        selected = [row for row in selected if
                    (args.output_dir / "receipts" / f"{row['fasta_file'][:-8]}.json").is_file()]
    missing = []
    for row in selected:
        slug = row["fasta_file"][:-8]
        if not (args.output_dir / "receipts" / f"{slug}.json").is_file():
            missing.append(row["dataset_name"])
    if missing:
        parser.error(f"{len(missing)} CPR reports still missing; first: {', '.join(missing[:5])}")

    errors = 0
    (args.output_dir / "permanent").mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(publish_one, index, len(selected), row, args): row
                   for index, row in enumerate(selected, 1)}
        for future in as_completed(futures):
            try:
                print(future.result(), flush=True)
            except (OSError, RuntimeError, ValueError) as exc:
                errors += 1
                print(f"ERROR {futures[future]['dataset_name']}: {exc}", flush=True)
    count, path = write_links(args.output_dir, preview)
    print(f"{count}/{len(preview)} permanent CPR links in {path}; {errors} errors", flush=True)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()

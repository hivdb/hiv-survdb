#!/usr/bin/env python3
"""Build and publish SurvDB SQLite from curated payload and Sierra/CPR reports.

The selected isolates in hiv-survdb-payload are the input to this pipeline.
This script never reads the separate HIVDB-Surv-project checkout.
"""

import argparse
import csv
import gzip
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HIV = ROOT.parent
PAYLOAD = HIV / "hiv-survdb-payload"
CMS = HIV / "hivdb-cms"
FRONTEND = HIV / "hivdb-frontend"
BUCKET = "cms.hivdb.org"
PREFIX = "hiv-survdb"
BUILDER_IMAGE = "hiv-survdb-builder:arm64"


def run(*command, cwd=ROOT):
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, check=True)


def output(*command, cwd=ROOT):
    return subprocess.check_output(list(map(str, command)), cwd=cwd, text=True).strip()


def require_inputs():
    required = (
        PAYLOAD / "tables/articles.csv",
        PAYLOAD / "tables/datasets.csv",
        HIV / "hivfacts/data/algorithms/HIVDB_latest.xml",
    )
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(f"Required input is missing: {path}")
    if not (ROOT / "payload").resolve() == PAYLOAD.resolve():
        raise RuntimeError("payload must point to the sibling hiv-survdb-payload repository")


def refresh_cpr():
    run(sys.executable, "scripts/export-cpr-fasta-from-local-hivdb.py",
        "--all", "--selected-isolate-ids", "--unknown-insertions-as-n",
        "--output-dir", "local/cpr-fasta-current")
    run(sys.executable, "scripts/prepare-cpr-ref-fasta.py")
    run("uv", "run", "--frozen", "python", "scripts/submit-cpr-reports.py",
        "--preview", "local/cpr-ref-report-links-preview.csv",
        "--fasta-dir", "local/cpr-fasta-ref")
    run(sys.executable, "scripts/publish-cpr-report-links.py",
        "--preview", "local/cpr-ref-report-links-preview.csv",
        "--fasta-dir", "local/cpr-fasta-ref")
    run(sys.executable, "scripts/apply-cpr-ref-links.py", "--apply")


def build_scored_counts():
    run(sys.executable, "scripts/build-scored-mutation-counts.py")


def wait_for_postgres(timeout_seconds=600):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        logs = subprocess.run(
            ["docker", "logs", "hiv-survdb-devdb"], cwd=ROOT,
            capture_output=True, text=True,
        )
        initialized = "PostgreSQL init process complete; ready for start up." in (
            logs.stdout + logs.stderr
        )
        check = subprocess.run(
            ["docker", "exec", "hiv-survdb-devdb", "pg_isready", "-U", "postgres"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if initialized and check.returncode == 0:
            return
        time.sleep(3)
    raise TimeoutError("hiv-survdb-devdb did not become ready within 10 minutes")


def build_sqlite(version):
    full = ROOT / "build" / f"hiv-survdb-{version}.db"
    slim = ROOT / "build" / f"hiv-survdb-{version}-slim.db"
    if full.exists() or slim.exists():
        raise FileExistsError(f"SQLite version already exists: {version}")
    run("make", f"BUILDER_IMAGE={BUILDER_IMAGE}", "devdb")
    wait_for_postgres()
    run("docker", "run", "--rm", "--shm-size=1536m",
        f"--volume={ROOT}:/hiv-survdb/",
        f"--volume={PAYLOAD}:/hiv-survdb-payload",
        "--network=hiv-survdb-network", BUILDER_IMAGE,
        "scripts/export-sqlite.sh", version)
    return full, slim


def validate_database(path, expected_counts, scored_options, cpr_preview,
                      ref_preview, started_at, slim):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(f"SQLite integrity check failed: {path}")
        timestamp, = db.execute(
            "SELECT last_update FROM last_update WHERE scope = 'global'"
        ).fetchone()
        updated_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if updated_at < started_at:
            raise ValueError(f"Stale last_update in {path}: {timestamp}")
        dataset_rows = {
            dataset: (ref, url) for dataset, ref, url in db.execute(
                "SELECT dataset_name, ref_name, url FROM datasets"
            )
        }
        expected_datasets = {
            name: row for name, row in cpr_preview.items()
            if int(row["sequence_count"] or 0) > 0
        }
        if set(dataset_rows) != set(expected_datasets):
            raise ValueError(f"Positive-person CPR datasets and SQLite differ in {path}")
        person_counts = dict(db.execute(
            "SELECT dataset_name, SUM(num_persons) FROM dataset_patient_counts "
            "WHERE isolate_year = -1 GROUP BY dataset_name"
        ))
        if set(person_counts) != set(dataset_rows):
            raise ValueError(f"Dataset person counts and SQLite datasets differ in {path}")
        for dataset, row in expected_datasets.items():
            expected = int(row["sequence_count"])
            if person_counts[dataset] != expected:
                raise ValueError(f"CPR person count mismatch for {dataset} in {path}")
            ref, actual_url = dataset_rows[dataset]
            if ref not in ref_preview:
                raise ValueError(f"Missing reference CPR input for {dataset}: {ref}")
            slug = ref_preview[ref]["fasta_file"].removesuffix("-seq.fas")
            expected_url = f"https://hivdb.stanford.edu/cpr/report/?load=hiv-survdb/{slug}"
            if (actual_url or "") != expected_url:
                raise ValueError(f"Incorrect dataset CPR URL for {dataset} in {path}")
        ref_urls = {}
        for ref, url in dataset_rows.values():
            if ref in ref_urls and ref_urls[ref] != url:
                raise ValueError(f"Reference has multiple CPR URLs in {path}: {ref}")
            ref_urls[ref] = url
        orphan_articles, = db.execute("""
            SELECT COUNT(*) FROM articles A
            WHERE NOT EXISTS (SELECT 1 FROM datasets D WHERE D.ref_name = A.ref_name)
        """).fetchone()
        if orphan_articles:
            raise ValueError(f"{orphan_articles} articles have no dataset in {path}")
        isolate_count, = db.execute("SELECT count(*) FROM isolates").fetchone()
        if (isolate_count == 0) != slim:
            raise ValueError(f"Unexpected isolate coverage in {path}: {isolate_count}")
        placeholders = ",".join("?" for _ in scored_options)
        actual = {
            (dataset, country, year, mutation): persons
            for dataset, country, year, mutation, persons in db.execute(
                "SELECT dataset_name, country_code, isolate_year, mutation, num_persons "
                "FROM dataset_patient_mutation_counts "
                f"WHERE mutation IN ({placeholders})", scored_options
            )
        }
        if actual != expected_counts:
            raise ValueError(
                f"Scored count mismatch in {path}: {len(actual)} SQLite rows, "
                f"{len(expected_counts)} CSV rows"
            )
        print(f"Validated {path.name}: {len(ref_urls)} reference CPR links, "
              f"{len(actual)} scored counts, last_update={timestamp}", flush=True)
        return timestamp


def validate_sqlite(full, slim, started_at):
    with (ROOT / "local/cpr-report-links-preview.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        cpr_preview = {row["dataset_name"]: row for row in csv.DictReader(handle)}
    with (ROOT / "local/cpr-ref-report-links-preview.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        ref_preview = {row["dataset_name"]: row for row in csv.DictReader(handle)}
    with (PAYLOAD / "tables/scored_mutation_options.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        options = [row["mutation"] for row in csv.DictReader(handle)]
    if not options or len(options) != len(set(options)):
        raise ValueError("Scored mutation options are empty or duplicated")
    with (PAYLOAD / "tables/dataset_patient_scored_mutation_counts.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        counts = {
            (row["dataset_name"], row["country_code"],
             int(row["isolate_year"]), row["mutation"]): int(row["num_persons"])
            for row in csv.DictReader(handle)
        }
    full_timestamp = validate_database(
        full, counts, options, cpr_preview, ref_preview, started_at, False)
    slim_timestamp = validate_database(
        slim, counts, options, cpr_preview, ref_preview, started_at, True)
    if full_timestamp != slim_timestamp:
        raise ValueError("Full and slim SQLite last_update values differ")


def require_committed_sources():
    for repo in (ROOT, PAYLOAD):
        if output("git", "status", "--porcelain", cwd=repo):
            raise RuntimeError(f"Commit and review source changes before publishing: {repo}")
    options_path = "src/views/survdb/surv-mutation-options/scored-mutations.json"
    if output("git", "status", "--porcelain", "--", options_path, cwd=FRONTEND):
        raise RuntimeError("Commit the generated frontend scored mutation options before publishing")


def s3_object_available(key):
    result = subprocess.run(
        ["aws", "s3api", "head-object", "--bucket", BUCKET, "--key", key],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True
    if "404" in result.stderr or "Not Found" in result.stderr:
        return False
    raise RuntimeError(f"Could not check s3://{BUCKET}/{key}: {result.stderr.strip()}")


def publish_sqlite(full, slim):
    paths = (slim, full)
    keys = [f"{PREFIX}/{path.name}" for path in paths]
    for key in keys:
        if s3_object_available(key):
            raise FileExistsError(f"Published SQLite version already exists: s3://{BUCKET}/{key}")
    with tempfile.TemporaryDirectory(prefix="survdb-release-") as temporary:
        for path, key in zip(paths, keys):
            compressed = Path(temporary) / f"{path.name}.gz"
            with path.open("rb") as source, gzip.open(compressed, "wb", compresslevel=9) as target:
                shutil.copyfileobj(source, target)
            run("aws", "s3", "cp", compressed, f"s3://{BUCKET}/{key}",
                "--content-encoding", "gzip", "--content-type", "application/octet-stream",
                "--cache-control", "max-age=2592000", "--no-progress")
            if not s3_object_available(key):
                raise RuntimeError(f"Upload did not appear: s3://{BUCKET}/{key}")


def update_cms(version):
    page = CMS / "pages/hiv-survdb.yml"
    if not page.is_file():
        raise FileNotFoundError(f"CMS page not found: {page}")
    if output("git", "status", "--porcelain", cwd=CMS):
        raise RuntimeError("Commit or stash CMS changes before publishing")
    content = page.read_text()
    lines = content.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.startswith("survdbVersion:")]
    if len(matches) != 1:
        raise ValueError("Expected one survdbVersion line in the CMS page")
    lines[matches[0]] = f"survdbVersion: {version}-slim\n"
    page.write_text("".join(lines))
    run("pipenv", "run", "python", "build.py", cwd=CMS)
    artifact = CMS / "build/pages/hiv-survdb.json"
    if json.loads(artifact.read_text())["survdbVersion"] != f"{version}-slim":
        raise ValueError("Built CMS page has the wrong SurvDB version")
    run("git", "add", "pages/hiv-survdb.yml", cwd=CMS)
    run("git", "commit", "-m", f"Point SurvDB to SQLite {version}", cwd=CMS)
    run("git", "push", "origin", "master", cwd=CMS)
    for environment in ("prod", "staging", "staging2", "localhost"):
        key = f"{environment}/pages/hiv-survdb.json"
        run("aws", "s3", "cp", artifact, f"s3://{BUCKET}/{key}",
            "--content-type", "application/json", "--cache-control", "max-age=600",
            "--no-progress")
    invalidation = output(
        "aws", "cloudfront", "create-invalidation", "--distribution-id",
        "ED0OYJBLR1U2Y", "--paths",
        *(f"/{environment}/pages/hiv-survdb.json" for environment in
          ("prod", "staging", "staging2", "localhost")),
        "--query", "Invalidation.Id", "--output", "text",
    )
    print(f"Waiting for CMS CloudFront invalidation {invalidation}", flush=True)
    run("aws", "cloudfront", "wait", "invalidation-completed",
        "--distribution-id", "ED0OYJBLR1U2Y", "--id", invalidation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-existing-cpr", action="store_true",
                        help="reuse existing Sierra reports and permanent CPR links")
    parser.add_argument("--build-only", action="store_true",
                        help="build and validate SQLite without publishing")
    parser.add_argument("--skip-cms", action="store_true",
                        help="publish SQLite to S3 without changing CMS")
    parser.add_argument("--version", default=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
                        help="release version (default: current UTC timestamp)")
    args = parser.parse_args()
    if not re.fullmatch(r"\d{8}-\d{6}", args.version):
        parser.error("version must have the form YYYYMMDD-HHMMSS")
    started_at = datetime.now(timezone.utc).replace(microsecond=0)
    require_inputs()
    if not args.use_existing_cpr:
        refresh_cpr()
    build_scored_counts()
    full, slim = build_sqlite(args.version)
    validate_sqlite(full, slim, started_at)
    if args.build_only:
        print("Build and validation complete; publication skipped", flush=True)
        return
    require_committed_sources()
    for repo in (ROOT, PAYLOAD):
        run("git", "push", "origin", "main", cwd=repo)
    publish_sqlite(full, slim)
    run("git", "tag", "-a", args.version, "-m", f"SurvDB SQLite {args.version}", cwd=PAYLOAD)
    run("git", "push", "origin", args.version, cwd=PAYLOAD)
    if not args.skip_cms:
        update_cms(args.version)
    print(f"Published SurvDB SQLite {args.version}", flush=True)


if __name__ == "__main__":
    main()

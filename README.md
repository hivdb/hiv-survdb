# HIV-SurvDB local update

This repository builds the SurvDB SQLite files from CSVs in the sibling `../hiv-survdb-payload` checkout. The table shows Publication, Continent, Countries, Period, # persons, Resistance (%), and NRTI/NNRTI/PI/INSTI percentages.

The **reflist defines the complete RefID set**. `Rx` becomes dataset status and does not decide which RefIDs receive isolate calculations. We use the calculation stages in `../../HIVDB-Surv-project/ART-naive` for every RefID, regardless of Rx. The PI-naive and INSTI-naive folders have the same main earliest-clinical-isolate, HIV-1, filter, priority, and gene-specific prior-treatment stages; their initial reference filters and some additional checks differ. This workflow uses one consistent calculation method for the whole reflist.

## How isolates are selected

1. For each RefID, find clinical `tblRefLink`/`tblIsolates` rows. Keep the earliest `IsolateDate` for each `(RefID, PtID, Gene)`; break a date tie by the lowest `IsolateID`.
2. Keep HIV-1 isolates, remove `tblIsolateFilters` rows, and prefer reference links with `Priority=1`.
3. If a RefID has no priority-1 links, use its priority-0 links. This explicit fallback is needed for RefIDs **2538, 2575, 2863, and 2947** in the 2026-10-19 reflist. The source folders' strict priority-1 step would omit them.
4. Remove isolates with relevant prior treatment from `tblRxHistory`, then add country, continent, source, subtype, year, and gene.
5. Read Sequence/Consensus amino-acid sequences and mark SDRMs using `drug_resistance_surveillance_mutations.csv` from the source project.

The converter stores the selected `IsolateID` as both `isolate_name` and `hivdb_isolate_id`. The table's **# persons** label historically represents distinct selected `IsolateID` values; a patient with multiple genes can contribute multiple isolates. Resistance is the proportion of selected isolates with any SDRM. Each drug-class percentage uses isolates of its corresponding gene as its denominator. CA isolates count in the total and Resistance denominator, matching the source calculation.

## Full local workflow on arm64

Run these commands from this repository root. Keep Docker Desktop running and the sibling payload and source-project checkouts available. Database steps use the local HIVDB2 copy at `127.0.0.1:3308`, user `root`, with an empty password by default. The source project accepts `HIVDB_MYSQL_*` environment overrides.

### 1. Prepare metadata and the complete method input

Correct the reflist's `Cont` values and duplicate reference names if needed, then build and review `articles.csv`, `datasets.csv`, and `journals.csv`. The `Rx` column supplies status; new annotations are empty. The method input contains **every unique `ref_id`** from the reflist and uses an `ART-naive` marker solely to pass the source runner's initial filter. It does not alter dataset status.

```bash
uv sync --frozen
uv run --frozen python scripts/prepare-reflist.py ~/Downloads/survdb-2026-10-19.csv
uv run --frozen python scripts/build-metadata-from-reflist.py ~/Downloads/survdb-2026-10-19.csv
uv run --frozen python scripts/build-metadata-from-reflist.py ~/Downloads/survdb-2026-10-19.csv --output-dir payload/tables
uv run --frozen python scripts/prepare-art-naive-input.py ~/Downloads/survdb-2026-10-19.csv
```

### 2. Stage an isolated copy of the calculation code

The source runner writes large intermediate files. Stage its code under ignored `local/art-method-run/` so the source checkout and its existing report are not overwritten. Copy its drug lookup and SDRM definitions along with the prepared input.

```bash
mkdir -p local/art-method-run/ART-naive local/art-method-run/input
cp -R ../../HIVDB-Surv-project/ART-naive/workflow local/art-method-run/ART-naive/
cp ../../HIVDB-Surv-project/ART-naive/steps.yaml ../../HIVDB-Surv-project/ART-naive/run_art_naive_workflow.py local/art-method-run/ART-naive/
cp ../../HIVDB-Surv-project/pyproject.toml ../../HIVDB-Surv-project/uv.lock local/art-method-run/
cp local/art-naive-input/HIV_References_20260910T230606Z.csv ../../HIVDB-Surv-project/input/drug_resistance_surveillance_mutations.csv ../../HIVDB-Surv-project/input/tblLUDrugs.csv local/art-method-run/input/
```

### 3. Run the calculation in two manual parts

The MySQL and sequence steps can take time. Run through step 9, apply the priority fallback, then resume at step 11. Do not run the source step 10 afterward; it would replace the fallback selection. The source project's `ART-naive/README.md` explains each step.

```bash
cd local/art-method-run
uv run --frozen python ART-naive/run_art_naive_workflow.py --from-step 0 --to-step 9
cd ../..
uv run --frozen python scripts/select-priority-with-fallback.py
cd local/art-method-run
uv run --frozen python ART-naive/run_art_naive_workflow.py --from-step 11 --to-step 18
cd ../..
```

Review `local/art-method-run/ART-naive/step_output/08_select_refid_priority/priority-zero-fallback-refids.csv`. A future update may have a different fallback list.

### 4. Convert and review the complete output

The converter requires a selected isolate for every requested RefID and routes isolates to the 610 continent-specific datasets. It writes the source SDRM definitions and mutation calls, and removes old CPR exclusions for replaced datasets. Preview before applying. The converter does not require CPR workbooks.

```bash
uv run --frozen python scripts/import-art-naive-output.py --art-root local/art-method-run/ART-naive --output-dir local/all-refid-preview
uv run --frozen python scripts/import-art-naive-output.py --art-root local/art-method-run/ART-naive --apply
git -C payload status --short
git -C payload diff --stat
```

### 5. Build and validate SQLite

The local build does not publish a release. Wait for PostgreSQL initialization to complete before exporting SQLite.

```bash
make BUILDER_IMAGE=hiv-survdb-builder:arm64 devdb
docker logs -f hiv-survdb-devdb
make BUILDER_IMAGE=hiv-survdb-builder:arm64 local-release
uv run --frozen python scripts/validate-art-naive-sqlite.py --reflist ~/Downloads/survdb-2026-10-19.csv
sqlite3 build/hiv-survdb-local-slim.db 'PRAGMA integrity_check;'
```

The outputs are `build/hiv-survdb-local.db` and `build/hiv-survdb-local-slim.db`. The validator requires every reflist RefID in `articles` and in table patterns. It also compares the 481 ART-naive RefIDs covered by the source project's existing report with their total, per-gene, and SDRM-positive counts.

For the 2026-10-19 reflist, the finished database has **565 RefIDs, 610 datasets, 342,286 selected isolates, and 19,205 isolate SDRM rows**. All 565 RefIDs have table patterns, and both SQLite files passed integrity checks.

## Table coverage

The build includes all 21 tables in `schema.dbml`. The steps above refresh these payload inputs: `articles`, `datasets`, `journals`, `isolates`, `isolate_mutations`, and `surv_mutations`. They also regenerate `dataset_countries`, `patterns`, `pattern_genes`, `pattern_surv_mutations`, `dataset_patterns`, and all five `dataset_*_summaries` tables. `last_update` is set during the build.

`countries`, `country_subregions`, and `drug_classes` are copied from the existing payload lookup CSVs; this workflow does **not** refresh their definitions from HIVDB. Review those CSVs separately when country mappings or drug classes change. `isolate_excluded_surv_mutations` is empty because this update uses the source project's amino-acid SDRM calculation and does not run CPR. Exact isolate dates, sequence methods, GenBank accessions, and entry dates are not supplied by that calculation output, so their optional isolate fields remain null.

## CPR reports and links

The resistance calculation above does not need CPR. To add **current** CPR report links to `datasets.url`, use the selected `IsolateID` values in the payload; historical reports in `payload/suppl-tables/cpr_POL.txt` were built from a different selection. Do not attach those old URLs to these datasets.

### 1. Prepare and audit report inputs

With local HIVDB2 running, export the selected isolate sequences, then combine the continent files into **one POL FASTA per `ref_name`**:

```bash
python3 scripts/export-cpr-fasta-from-local-hivdb.py --all --selected-isolate-ids --unknown-insertions-as-n --skip-existing --output-dir local/cpr-fasta-current
python3 scripts/prepare-cpr-ref-fasta.py
```

Review `local/cpr-ref-report-links-preview.csv`. It contains each reference's RefID, FASTA filename, sequence count, SHA-256 digest, and number of insertions represented by unknown (`N`) bases. If the payload selection changes, replace the old files in `local/cpr-fasta-current` before exporting again; `--skip-existing` preserves them. The 2026-10-19 export produced **565 reference FASTA files** from 609 POL datasets. `Yao15b-Africa` contains only CA, but its reference's Asia sequences are included in the shared `Yao15b` report. Eight source dataset files contain 47 insertions whose nucleotides are absent from HIVDB2; the export represents their codons with `N` and records the count in each `*-selection.csv` manifest. Review those inputs before submitting CPR.

### 2. Run CPR and collect URLs

Run the resumable batch client. It uses local Sierra at `127.0.0.1:8111`, the current CPR POL `SDRM_2023` list in `scripts/cpr-pol-sdrm-2023.json`, Stanford's CPR save API, and its report storage. It writes one receipt and Sierra cache per reference and skips matching receipts when restarted. Check `local/cpr-reports/cpr_POL_current.txt` for temporary report URLs.

```bash
uv run --frozen python scripts/submit-cpr-reports.py --preview local/cpr-ref-report-links-preview.csv --fasta-dir local/cpr-fasta-ref
```

The older `scripts/batch_cpr.sh` expects the unavailable `../hivdb-scripts/CPR/batch_cpr_docker` client and a different input path. Use the new client for this selection.

Permanent links require copying the corresponding CPR assets to `s3://cprstorage/main/hiv-survdb/<ref-slug>` and `s3://cprstorage/tree/hiv-survdb/<ref-slug>`. The new publisher verifies both assets and writes `local/cpr-reports/permanent_urls.csv`. It requires AWS access to `cprstorage`. A temporary CPR UUID URL is useful for reviewing a report but cannot be applied to `datasets.url`.

### 3. Check and apply permanent links

After all 565 POL reports are available, publish and validate their permanent links, then update `datasets.csv` and rebuild SQLite:

```bash
uv run --frozen python scripts/publish-cpr-report-links.py --preview local/cpr-ref-report-links-preview.csv --fasta-dir local/cpr-fasta-ref
python3 scripts/apply-cpr-ref-links.py
python3 scripts/apply-cpr-ref-links.py --apply
make BUILDER_IMAGE=hiv-survdb-builder:arm64 devdb
docker logs -f hiv-survdb-devdb
make BUILDER_IMAGE=hiv-survdb-builder:arm64 local-release
uv run --frozen python scripts/validate-art-naive-sqlite.py --reflist ~/Downloads/survdb-2026-10-19.csv
```

The importer requires a distinct permanent URL with the expected `hiv-survdb/<ref-slug>` key for every reference. It assigns the same URL to all continent datasets of that reference, including the CA-only `Yao15b-Africa` row because its shared reference report contains the Asia POL sequences. `datasets.url` therefore has no unique constraint. Review the rebuilt SQLite URL values before release. `scripts/sync-from-cpr.sh` still joins by `(patient_id, gene, isolate_date)`, which does not match the current IsolateID payload, so it must not be used to replace the validated SDRM counts.

The 2026-10-19 run completed **565 CPR reports and 565 permanent URLs** with no submission or publication errors. Both local SQLite files contain links in all **610** dataset rows and have **565** distinct URLs. Their integrity checks and the isolate/SDRM validator passed. The report URLs are in `local/cpr-reports/permanent_urls.csv`; the exact dataset mapping is in `local/cpr-ref-links-mapping.csv`.

## Publication

The two `build/hiv-survdb-local*.db` files are validated local artifacts, not a published release. For this arm64 workflow, publish them manually: `Dockerfile.arm64` does not install `github-release` or AWS CLI, and `scripts/github-release.sh` still checks `origin/master` even though both repositories use `main`. Do not use `make release` or `make pre-release` until that tooling is updated.

1. Review and commit the builder changes in this repository and the data changes in the separate `payload` repository. Merge the builder branch into `main`, then push both `main` branches. The release should point to the commits that produced its files. In particular, confirm that `payload/tables/datasets.csv` has all 610 CPR URLs.
2. Give the already validated files an unused release tag, for example `20261019` if that tag is available:

   ```bash
   cp build/hiv-survdb-local.db build/hiv-survdb-20261019.db
   cp build/hiv-survdb-local-slim.db build/hiv-survdb-20261019-slim.db
   sqlite3 build/hiv-survdb-20261019.db 'PRAGMA integrity_check; SELECT count(*), count(DISTINCT url), sum(url IS NULL OR url = "") FROM datasets;'
   sqlite3 build/hiv-survdb-20261019-slim.db 'PRAGMA integrity_check; SELECT count(*), count(DISTINCT url), sum(url IS NULL OR url = "") FROM datasets;'
   shasum -a 256 build/hiv-survdb-20261019*.db
   ```

   Both queries should return `ok` and `610|565|0`. For another release date, use the same unused tag in both filenames and in the GitHub release.
3. In [hivdb/hiv-survdb-payload releases](https://github.com/hivdb/hiv-survdb-payload/releases), create a release from the pushed payload `main` commit. Use that tag and attach both versioned `.db` files. Include the builder and payload commit IDs and the CPR URL coverage in the release notes. Check that both assets can be downloaded before announcing the release.
4. If the database also needs to appear in `s3://cms.hivdb.org/hiv-survdb/`, upload gzip-encoded copies of both assets with AWS credentials. The legacy `scripts/sync-to-s3.sh` mirrors GitHub release assets in this format; check the bucket listing after upload. GitHub publication alone does not run that mirror step in this manual workflow.

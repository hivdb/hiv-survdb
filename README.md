# HIV-1 Surveillance Database builder

This repository builds the SurvDB SQLite files used by the frontend. Its input is the curated metadata, selected isolates, and isolate mutations in the sibling `hiv-survdb-payload` repository. Sierra reports supply the HIVdb-scored mutation counts. The SQLite files are published to `s3://cms.hivdb.org/hiv-survdb/`; the frontend selects a version through `hivdb-cms/pages/hiv-survdb.yml`.

## One build and publish command

Run from this repository root:

```bash
python3 scripts/build-publish-sqlite.py
```

The command runs these stages in order:

1. Read the selected isolates in `payload/tables/isolates.d/` and export their POL nucleotide sequences from the local read-only HIVDB2 copy into dataset FASTA files.
2. Combine dataset FASTA files into one file per publication (`ref_name`). Run those sequences through local Sierra and save each complete `local/cpr-reports/sierra/<ref-slug>.json.gz` response for scored mutation counts.
3. Submit a separate CPR report for every POL dataset, publish its permanent assets, and apply its unique URL to `payload/tables/datasets.csv`. A publication split across continents therefore has one report per continent. CA-only datasets without POL sequences have no POL CPR link.
4. Read the latest HIVdb algorithm and the Sierra responses to regenerate `dataset_patient_scored_mutation_counts.csv`, `scored_mutation_options.csv`, and the frontend scored mutation options.
5. Import the payload CSVs into PostgreSQL, export full and slim SQLite files, and calculate the distinct-patient counts. `scripts/add-patient-counts.py` sets `last_update` **after** writing the Sierra counts. Both SQLite files therefore carry the final build timestamp.
6. Check SQLite integrity, each CPR FASTA sequence count against its dataset person count, each dataset CPR URL, the full versus slim isolate coverage, the exact scored count rows against the CSV, and the matching `last_update` values.
7. Require committed builder and payload source, push their `main` branches, gzip and upload both versioned SQLite files to S3, and tag the payload commit with the UTC version. Build and commit the CMS version change, upload the four CMS page JSON files, and invalidate their CloudFront cache.

The release version defaults to `YYYYMMDD-HHMMSS` in UTC. The script refuses to overwrite local or published files with the same version.

For a rebuild when the selected isolates, sequences, Sierra reports, and CPR links have **not** changed:

```bash
python3 scripts/build-publish-sqlite.py --use-existing-cpr --build-only
```

Remove `--build-only` to publish that rebuild. Use `--skip-cms` only when the SQLite files should be published without switching the frontend. A specific unused version can be supplied with `--version YYYYMMDD-HHMMSS`.

## Prerequisites and source boundary

- The sibling `hiv-survdb-payload`, `hivfacts`, `hivdb-frontend`, and `hivdb-cms` checkouts must exist. The `payload` symlink in this repository must point to `hiv-survdb-payload`.
- Docker Desktop and the ARM64 builder image must be available. The script builds the image through `make devdb`.
- A local read-only HIVDB2 copy must be reachable at `127.0.0.1:3308` for a fresh CPR run. Set `LOCAL_HIVDB_HOST`, `LOCAL_HIVDB_PORT`, `LOCAL_HIVDB_USER`, and `LOCAL_HIVDB_PASSWORD` if needed.
- Local Sierra must be reachable at `127.0.0.1:8111`; `uv` and its locked environment provide the CPR client dependencies.
- Publishing requires AWS access to `cprstorage` and `cms.hivdb.org`, GitHub push access for the builder, payload, and CMS repositories, and `pipenv` for the CMS build.

The command begins with **already curated selected isolates in the payload**. It does not select new isolates from raw HIVDB2 records or change the selection rules. That upstream curation is a separate input preparation step. The pipeline does not access the excluded legacy project. Do not run the older source calculation workflow to prepare this release.

The S3 files are the SQLite assets the frontend actually downloads. A GitHub tag records the source commit; attaching SQLite files to a GitHub Release is a separate archival step and is not required for the frontend.

## Useful checks

```bash
sqlite3 build/hiv-survdb-<version>-slim.db 'PRAGMA integrity_check; SELECT last_update FROM last_update WHERE scope = "global";'
aws s3 ls s3://cms.hivdb.org/hiv-survdb/ | tail
```

The payload count CSV stores one row per dataset, country, year, and scored mutation. `isolate_year = -1` means all collection years. Sierra caches contain the per-sequence mutation lists; the CSV contains aggregated distinct-patient counts. Scored mutations with no selected publication remain selectable but have no count row.

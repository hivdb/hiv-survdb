#!/usr/bin/env python3
"""Convert ART-naive calculation output for every reflist RefID to payload CSVs.

Run ART-naive steps 7-18 first. This importer intentionally uses the selected
IsolateID as isolate_name, so pattern counts use the same distinct isolates as
the ART-naive reference report.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT.parents[1] / "HIVDB-Surv-project" / "ART-naive"
GENES = {"PR", "RT", "IN", "CA"}
CLASS_GENES = {"NRTIs": "RT", "NNRTIs": "RT", "PIs": "PR", "INSTI": "IN"}
CLASS_NAMES = {"NRTIs": "NRTI", "NNRTIs": "NNRTI", "PIs": "PI", "INSTI": "INSTI"}
ISO_COLUMNS = (
    "dataset_name", "isolate_name", "hivdb_isolate_id", "patient_id", "gene",
    "isolate_date", "isolate_year", "subtype", "source", "seq_method",
    "country_code", "genbank_accn", "cpr_excluded", "date_entered",
)
MUT_COLUMNS = (
    "dataset_name", "isolate_name", "gene", "mutation", "position",
    "amino_acid", "is_mixture",
)
SDRM_COLUMNS = ("mutation", "gene", "drug_class", "position", "amino_acid")


def csv_rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError(f"Missing CSV header: {path}")
        yield from reader


def one_csv(directory: Path, pattern: str) -> Path:
    matches = list(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"Expected one {pattern} in {directory}, found {len(matches)}")
    return matches[0]


def definitions(path: Path):
    result = {}
    for row in csv_rows(path):
        drug_class = row["Class"]
        gene = CLASS_GENES[drug_class]
        for alt in row["Mutations"].split(","):
            alt = alt.strip()
            label = f'{row["Ref"]}{row["position"]}{alt}'
            key = (drug_class, label)
            if key in result:
                raise ValueError(f"Duplicate ART-naive SDRM {key}")
            result[key] = (f"{gene}:{label}", gene, CLASS_NAMES[drug_class], row["position"], alt)
    return result


def write_csv(path: Path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.writer(destination, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)


def file_stem(name: str) -> str:
    return re.sub(r"\s+", "-", name.lower().replace("'", "").replace('"', ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--art-root", type=Path, default=ART)
    parser.add_argument("--payload", type=Path, default=ROOT / "payload" / "tables")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "local" / "art-naive-preview")
    parser.add_argument("--dataset", help="Preview or apply one dataset")
    parser.add_argument("--apply", action="store_true", help="Write payload tables")
    parser.add_argument("--allow-missing", action="store_true", help="Allow ART output without every requested RefID")
    args = parser.parse_args()

    art = args.art_root
    selected_path = one_csv(art / "step_output" / "12_add_isolate_year_gene", "*.csv")
    mutation_dir = art / "step_output" / "15_mark_sdrm_mutations"
    mutation_defs = definitions(art / "input" / "drug_resistance_surveillance_mutations.csv")
    articles = {row["ref_name"]: row["ref_id"] for row in csv_rows(args.payload / "articles.csv")}
    datasets = list(csv_rows(args.payload / "datasets.csv"))
    target = datasets
    if args.dataset:
        target = [row for row in target if row["dataset_name"] == args.dataset]
        if not target:
            parser.error(f"Unknown dataset: {args.dataset}")
    by_ref = defaultdict(dict)
    for row in target:
        ref_id = articles.get(row["ref_name"])
        if not ref_id:
            raise ValueError(f'Missing RefID for {row["dataset_name"]}')
        continent = row["continent_name"]
        if continent in by_ref[ref_id]:
            raise ValueError(f"Duplicate RefID {ref_id} continent {continent}")
        by_ref[ref_id][continent] = row["dataset_name"]

    countries = {row["country_name"]: row["country_code"] for row in csv_rows(args.payload.parent / "suppl-tables" / "country_names_and_codes.csv")}
    iso_rows = defaultdict(list)
    selected = {}
    seen_refs = set()
    for row in csv_rows(selected_path):
        ref_id = row["RefID"]
        if ref_id not in by_ref or row["Gene"] not in GENES:
            continue
        continent = row["ISOContinentName"]
        if continent == "Central America":
            continent = "North America"
        dataset = by_ref[ref_id].get(continent)
        if not dataset:
            raise ValueError(f"RefID {ref_id}, IsolateID {row['IsolateID']}: no dataset for {continent!r}")
        country = countries.get(row["Country"])
        if not country:
            raise ValueError(f"Unmapped country {row['Country']!r}")
        isolate_id = row["IsolateID"]
        key = (ref_id, isolate_id)
        if key in selected:
            raise ValueError(f"Repeated ART-naive RefID/IsolateID: {key}")
        selected[key] = (dataset, row["Gene"])
        seen_refs.add(ref_id)
        iso_rows[dataset].append((
            dataset, isolate_id, isolate_id, row["PtID"], row["Gene"],
            "NULL", row["IsolateYear"], row["Subtype"] or "NULL",
            row["Source"] or "NULL", "NULL", country, "NULL", "false", "NULL",
        ))

    missing = set(by_ref) - seen_refs
    if missing and not args.allow_missing:
        raise ValueError(
            f"Source selected output lacks {len(missing)} requested RefIDs "
            f"(first: {', '.join(sorted(missing, key=int)[:15])}). "
            "Rerun the ART-naive workflow with the current reflist, or use "
            "--allow-missing only for a partial preview."
        )

    mutations = defaultdict(dict)
    for drug_class in CLASS_GENES:
        path = mutation_dir / f"{drug_class}_mutation_table.csv"
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            mutation_columns = [(label, value) for (klass, label), value in mutation_defs.items() if klass == drug_class]
            absent = [label for label, _ in mutation_columns if label not in (reader.fieldnames or ())]
            if absent:
                raise ValueError(f"{path}: missing mutation columns: {absent}")
            for row in reader:
                key = (row["RefID"], row["IsolateID"])
                item = selected.get(key)
                if item is None:
                    continue
                dataset, gene = item
                if gene != CLASS_GENES[drug_class]:
                    raise ValueError(f"Gene mismatch for {key}")
                for label, definition in mutation_columns:
                    if row[label] == "1":
                        mutation, _, _, position, alt = definition
                        mutations[dataset][(row["IsolateID"], mutation)] = (
                            dataset, row["IsolateID"], gene, mutation, position, alt, "false"
                        )
                    elif row[label] != "0":
                        raise ValueError(f"Invalid SDRM indicator {row[label]!r} in {path}")

    output = args.payload if args.apply else args.output_dir
    for dataset in sorted(iso_rows):
        stem = file_stem(dataset)
        write_csv(output / "isolates.d" / f"{stem}-iso.csv", ISO_COLUMNS, iso_rows[dataset])
        write_csv(output / "isolate_mutations.d" / f"{stem}-isomuts.csv", MUT_COLUMNS,
                  sorted(mutations[dataset].values()))
        if args.apply:
            # CPR exclusions belong to the replaced CPR result, not to the
            # ART-naive amino-acid mutation calculation.
            (output / "isolate_excluded_surv_mutations.d" / f"{stem}-exsdrms.csv").unlink(missing_ok=True)
    if not args.dataset:
        write_csv(output / "surv_mutations.csv", SDRM_COLUMNS, sorted(set(mutation_defs.values())))
    print(f"Selected {sum(map(len, iso_rows.values()))} isolates across {len(iso_rows)} datasets")
    print(f"Wrote {sum(map(len, mutations.values()))} unique isolate SDRMs to {output}")
    if missing:
        print(f"Missing requested RefIDs: {len(missing)}")


if __name__ == "__main__":
    main()

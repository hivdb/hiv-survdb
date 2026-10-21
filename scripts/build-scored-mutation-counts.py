#!/usr/bin/env python3
"""Build HIVdb-scored mutation options and patient counts from Sierra reports."""

import argparse
import csv
import gzip
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


CLASSES = {"NRTI": "RT", "NNRTI": "RT", "PI": "PR", "INSTI": "IN"}
SCORE_TERM = re.compile(
    r"(?:^|[,(])\s*((?:\d+[A-Zid]+\s+AND\s+)*\d+[A-Zid]+)\s*=>\s*(-?\d+)"
)
MUTATION_TERM = re.compile(r"^(\d+)([A-Zid]+)$")
HIV = Path(__file__).resolve().parents[2]


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        yield from csv.DictReader(source)


def score_options(hiv):
    xml = hiv / "hivfacts/data/algorithms/HIVDB_latest.xml"
    root = ET.parse(xml).getroot()
    genes = {item["abstractGene"]: item["refSequence"] for item in json.loads(
        (hiv / "hivfacts/data/genes_hiv1.json").read_text()
    )}
    drug_classes = {
        name.strip(): item.findtext("NAME")
        for item in root.findall("./DEFINITIONS/DRUGCLASS")
        for name in item.findtext("DRUGLIST").split(",")
    }
    options = {drug_class: set() for drug_class in CLASSES}
    positions = defaultdict(lambda: defaultdict(set))
    for drug in root.findall("./DRUG"):
        drug_class = drug_classes.get(drug.findtext("NAME"))
        if drug_class not in CLASSES:
            continue
        gene = CLASSES[drug_class]
        for rule in drug.findall("RULE"):
            condition = rule.findtext("CONDITION") or ""
            if not condition.startswith("SCORE FROM"):
                continue
            scored_terms = SCORE_TERM.findall(condition)
            if len(scored_terms) != condition.count("=>"):
                raise ValueError(f"Unparsed drug score rule: {drug.findtext('NAME')}")
            for scored_condition, score in scored_terms:
                if int(score) == 0:
                    continue
                for term in scored_condition.split(" AND "):
                    position, alternatives = MUTATION_TERM.fullmatch(term).groups()
                    position = int(position)
                    for aa in re.findall(r"ins|del|[A-Zid]", alternatives):
                        aa = {"i": "ins", "d": "del"}.get(aa, aa)
                        mutation = f"{gene}:{genes[gene][position - 1]}{position}{aa}"
                        options[drug_class].add(mutation)
                        positions[gene][position].add((aa, mutation))
    return root.findtext("ALGVERSION"), {
        drug_class: sorted(mutations, key=lambda mutation: (
            int(re.search(r"\d+", mutation).group()), mutation
        ))
        for drug_class, mutations in options.items()
    }, positions


def selected_isolates(payload):
    articles = {
        row["ref_name"]: row["ref_id"]
        for row in read_csv(payload / "articles.csv")
    }
    datasets = {
        row["dataset_name"]: articles[row["ref_name"]]
        for row in read_csv(payload / "datasets.csv")
    }
    isolates = {}
    for path in sorted((payload / "isolates.d").glob("*.csv")):
        for row in read_csv(path):
            key = (datasets[row["dataset_name"]], row["hivdb_isolate_id"], row["gene"])
            if key in isolates:
                raise ValueError(f"Duplicate selected isolate: {key}")
            isolates[key] = (
                row["dataset_name"], row["country_code"],
                int(row["isolate_year"]), row["patient_id"]
            )
    return isolates


def build_counts(payload, positions, reports):
    isolates = selected_isolates(payload)
    persons = defaultdict(set)
    ref_names = {
        row["ref_id"]: row["ref_name"]
        for row in read_csv(payload / "articles.csv")
    }
    by_ref_patient_gene = defaultdict(list)
    for key, selected in isolates.items():
        ref_id, _, gene = key
        if gene in positions:
            by_ref_patient_gene[(ref_id, selected[3], gene)].append(selected)
    seen = set()
    report_count = 0
    for ref_id in sorted({key[0] for key in by_ref_patient_gene}):
        stem = re.sub(r"\s+", "-", ref_names[ref_id].lower().replace("'", "").replace('"', ""))
        path = reports / f"{stem}.json.gz"
        if not path.is_file():
            raise FileNotFoundError(f"Missing Sierra report for RefID {ref_id}: {path}")
        report_count += 1
        with gzip.open(path, "rt") as source:
            analyses = json.load(source)["result"]["sequenceAnalysis"]
        for analysis in analyses:
            matched = re.search(r"\.PtID(\d+)", analysis["inputSequence"]["header"])
            if not matched:
                continue
            patient_id = matched.group(1)
            for gene_data in analysis["alignedGeneSequences"]:
                gene = gene_data["gene"]["name"]
                selected_key = (ref_id, patient_id, gene)
                selected_rows = by_ref_patient_gene.get(selected_key, ())
                if not selected_rows:
                    continue
                seen.add(selected_key)
                for item in gene_data["mutations"]:
                    for aa, mutation in positions[gene].get(item["position"], ()):
                        if len(aa) == 1:
                            matched_aa = aa in item["AAs"]
                        elif aa == "ins":
                            matched_aa = item["isIndel"] and (
                                "ins" in item["shortText"].lower() or
                                "_" in item["AAs"] or item["AAs"] == "i"
                            )
                        else:
                            matched_aa = item["isIndel"] and (
                                "del" in item["shortText"].lower() or
                                item["AAs"] in ("-", "d")
                            )
                        if matched_aa:
                            for dataset, country, year, patient in selected_rows:
                                persons[(dataset, country, -1, mutation)].add(patient)
                                persons[(dataset, country, year, mutation)].add(patient)
    missing = set(by_ref_patient_gene) - seen
    print(f"Matched {len(seen):,}/{len(by_ref_patient_gene):,} selected patient-gene groups in {report_count} Sierra reports")
    if missing:
        raise ValueError(f"No Sierra analysis for {len(missing)} selected patient-gene groups; first: {sorted(missing)[:10]}")
    return sorted((*key, len(ids)) for key, ids in persons.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--options", type=Path,
        default=HIV / "hivdb-frontend/src/views/survdb/surv-mutation-options/scored-mutations.json",
    )
    parser.add_argument(
        "--counts", type=Path,
        default=HIV / "hiv-survdb-payload/tables/dataset_patient_scored_mutation_counts.csv",
    )
    parser.add_argument(
        "--count-options", type=Path,
        default=HIV / "hiv-survdb-payload/tables/scored_mutation_options.csv",
    )
    parser.add_argument("--hiv-root", type=Path, default=HIV)
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--reports", type=Path)
    args = parser.parse_args()
    hiv = args.hiv_root
    payload = args.payload or hiv / "hiv-survdb-payload/tables"
    reports = args.reports or hiv / "hiv-survdb/local/cpr-reports/sierra"
    version, options, positions = score_options(hiv)
    args.options.write_text(json.dumps({
        "algorithmVersion": version, "drugClasses": options
    }, indent=2) + "\n")
    with args.count_options.open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.writer(destination, lineterminator="\n")
        writer.writerow(("mutation",))
        writer.writerows((mutation,) for mutation in sorted(set().union(*options.values())))
    print("Scored options:", {key: len(value) for key, value in options.items()})
    if args.counts:
        counts = build_counts(payload, positions, reports)
        observed = {mutation for _, _, year, mutation, _ in counts if year == -1}
        unmatched = {
            drug_class: [mutation for mutation in mutations if mutation not in observed]
            for drug_class, mutations in options.items()
        }
        print("Scored mutations with no selected publication:", unmatched)
        with args.counts.open("w", encoding="utf-8-sig", newline="") as destination:
            writer = csv.writer(destination, lineterminator="\n")
            writer.writerow(("dataset_name", "country_code", "isolate_year", "mutation", "num_persons"))
            writer.writerows(counts)
        print(f"Wrote {len(counts):,} scored patient count rows")


if __name__ == "__main__":
    main()

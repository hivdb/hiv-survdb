#!/usr/bin/env python3
"""Build SurvDB scored single-mutation options and patient counts."""

import argparse
import csv
import gzip
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
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


def build_counts(payload, positions, hiv, art):
    isolates = selected_isolates(payload)
    seen = set()
    persons = defaultdict(set)
    for gene, by_position in positions.items():
        path = art / "step_output/14_split_gene_position_tables" / f"{gene}_position_table.csv"
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            indexes = {
                pos: f"P{pos}" for pos in by_position
                if f"P{pos}" in reader.fieldnames
            }
            if len(indexes) != len(by_position):
                raise ValueError(f"Missing positions in {path}")
            for row in reader:
                key = (row["RefID"], row["IsolateID"], gene)
                selected = isolates.get(key)
                if selected is None:
                    continue
                seen.add(key)
                dataset, country, year, patient = selected
                for pos, column in indexes.items():
                    value = row[column]
                    for aa, mutation in by_position[pos]:
                        if value == aa or (len(value) > 1 and aa in value):
                            persons[(dataset, country, -1, mutation)].add(patient)
                            persons[(dataset, country, year, mutation)].add(patient)
    print(f"Matched {len(seen):,}/{len(isolates):,} selected isolates")
    missing = set(isolates) - seen
    ref_names = {
        row["ref_id"]: row["ref_name"]
        for row in read_csv(payload / "articles.csv")
    }
    by_ref_patient_gene = defaultdict(list)
    for key, selected in isolates.items():
        ref_id, _, gene = key
        if gene in positions:
            by_ref_patient_gene[(ref_id, selected[3], gene)].append(key)
    ref_ids = {key[0] for key in isolates}
    fallback_seen = set()
    missing_reports = []
    for ref_id in sorted(ref_ids):
        stem = re.sub(r"\s+", "-", ref_names[ref_id].lower().replace("'", "").replace('"', ""))
        path = hiv / "hiv-survdb/local/cpr-reports/sierra" / f"{stem}.json.gz"
        if not path.exists():
            missing_reports.append(ref_id)
            continue
        with gzip.open(path, "rt") as source:
            analyses = json.load(source)["result"]["sequenceAnalysis"]
        for analysis in analyses:
            matched = re.search(r"\.PtID(\d+)", analysis["inputSequence"]["header"])
            if not matched:
                continue
            patient_id = matched.group(1)
            for gene_data in analysis["alignedGeneSequences"]:
                gene = gene_data["gene"]["name"]
                keys = by_ref_patient_gene.get((ref_id, patient_id, gene), ())
                if not keys:
                    continue
                for key in keys:
                    is_missing = key in missing
                    if is_missing:
                        fallback_seen.add(key)
                    dataset, country, year, patient = isolates[key]
                    for item in gene_data["mutations"]:
                        for aa, mutation in positions[gene].get(item["position"], ()):
                            if not is_missing and aa not in ("ins", "del"):
                                continue
                            if len(aa) == 1:
                                matched_aa = aa in item["AAs"]
                            elif aa == "ins":
                                matched_aa = item["isIndel"] and (
                                    "ins" in item["shortText"].lower() or
                                    item["AAs"] in ("_", "i")
                                )
                            else:
                                matched_aa = item["isIndel"] and (
                                    "del" in item["shortText"].lower() or
                                    item["AAs"] in ("-", "d")
                                )
                            if matched_aa:
                                persons[(dataset, country, -1, mutation)].add(patient)
                                persons[(dataset, country, year, mutation)].add(patient)
    print(f"Matched {len(fallback_seen):,}/{len(missing):,} remaining isolates via Sierra")
    print("Missing Sierra reports:", len(missing_reports), missing_reports[:10])
    print("Still unmatched:", Counter(key[2] for key in missing - fallback_seen))
    if any(key[2] in positions for key in missing - fallback_seen):
        raise ValueError("Some selected PR/RT/IN isolates have no mutation source")
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
    parser.add_argument("--hiv-root", type=Path, default=HIV)
    parser.add_argument("--art-root", type=Path)
    parser.add_argument("--payload", type=Path)
    args = parser.parse_args()
    hiv = args.hiv_root
    art = args.art_root or hiv.parent / "HIVDB-Surv-project/ART-naive"
    payload = args.payload or hiv / "hiv-survdb-payload/tables"
    version, options, positions = score_options(hiv)
    args.options.write_text(json.dumps({
        "algorithmVersion": version, "drugClasses": options
    }, indent=2) + "\n")
    print("Scored options:", {key: len(value) for key, value in options.items()})
    if args.counts:
        counts = build_counts(payload, positions, hiv, art)
        with args.counts.open("w", encoding="utf-8-sig", newline="") as destination:
            writer = csv.writer(destination, lineterminator="\n")
            writer.writerow(("dataset_name", "country_code", "isolate_year", "mutation", "num_persons"))
            writer.writerows(counts)
        print(f"Wrote {len(counts):,} scored patient count rows")


if __name__ == "__main__":
    main()

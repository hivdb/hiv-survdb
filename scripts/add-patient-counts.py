#!/usr/bin/env python3
"""Add patient-level aggregate counts to a full SurvDB SQLite database."""

import argparse
import csv
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def new_patient():
    return {"genes": set(), "classes": set(), "mutations": set()}


def remove_zero_person_datasets(connection):
    """Remove datasets with no PR, RT, or IN patients from the published DB."""
    empty = [row[0] for row in connection.execute("""
        SELECT D.dataset_name
        FROM datasets D
        LEFT JOIN dataset_patient_counts P ON
          P.dataset_name = D.dataset_name AND P.isolate_year = -1
        GROUP BY D.dataset_name
        HAVING COALESCE(SUM(P.num_persons), 0) = 0
    """)]
    if not empty:
        return []
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )]
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({quoted})")}
        if "dataset_name" in columns:
            connection.executemany(
                f"DELETE FROM {quoted} WHERE dataset_name = ?",
                ((name,) for name in empty),
            )
    connection.execute("""
        DELETE FROM articles
        WHERE NOT EXISTS (
            SELECT 1 FROM datasets D WHERE D.ref_name = articles.ref_name
        )
    """)
    return empty


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument(
        "--scored-counts", type=Path,
        default=Path(__file__).resolve().parents[1] /
        "payload/tables/dataset_patient_scored_mutation_counts.csv",
    )
    parser.add_argument(
        "--scored-options", type=Path,
        default=Path(__file__).resolve().parents[1] /
        "payload/tables/scored_mutation_options.csv",
    )
    args = parser.parse_args()
    connection = sqlite3.connect(args.database)
    groups = defaultdict(lambda: defaultdict(new_patient))
    query = """
        SELECT I.dataset_name, I.country_code, I.isolate_year,
               I.patient_id, I.gene, IM.mutation, SM.drug_class
        FROM isolates I
        LEFT JOIN isolate_mutations IM ON
          IM.dataset_name = I.dataset_name AND
          IM.isolate_name = I.isolate_name
        LEFT JOIN surv_mutations SM ON SM.mutation = IM.mutation
        WHERE I.gene IN ('PR', 'RT', 'IN')
    """
    for dataset, country, year, patient_id, gene, mutation, drug_class in connection.execute(query):
        for key in ((dataset, country, -1), (dataset, country, year)):
            patient = groups[key][patient_id]
            patient["genes"].add(gene)
            if drug_class is not None:
                patient["classes"].add(drug_class)
                patient["mutations"].add(mutation)

    connection.executescript("""
        CREATE TABLE dataset_patient_counts (
            dataset_name TEXT NOT NULL,
            country_code TEXT NOT NULL,
            isolate_year INTEGER NOT NULL,
            num_persons INTEGER NOT NULL,
            num_sdrm_persons INTEGER NOT NULL,
            num_pr_persons INTEGER NOT NULL,
            num_rt_persons INTEGER NOT NULL,
            num_in_persons INTEGER NOT NULL,
            num_pi_persons INTEGER NOT NULL,
            num_nrti_persons INTEGER NOT NULL,
            num_nnrti_persons INTEGER NOT NULL,
            num_insti_persons INTEGER NOT NULL,
            PRIMARY KEY (dataset_name, country_code, isolate_year)
        );
        CREATE TABLE dataset_patient_mutation_counts (
            dataset_name TEXT NOT NULL,
            country_code TEXT NOT NULL,
            isolate_year INTEGER NOT NULL,
            mutation TEXT NOT NULL,
            num_persons INTEGER NOT NULL,
            PRIMARY KEY (dataset_name, country_code, isolate_year, mutation)
        );
    """)
    count_rows = []
    mutation_rows = []
    for (dataset, country, year), patients in groups.items():
        counts = {key: 0 for key in (
            "sdrm", "PR", "RT", "IN", "PI", "NRTI", "NNRTI", "INSTI"
        )}
        mutation_counts = defaultdict(int)
        for patient in patients.values():
            if patient["mutations"]:
                counts["sdrm"] += 1
            for gene in patient["genes"]:
                counts[gene] += 1
            for drug_class in patient["classes"]:
                counts[drug_class] += 1
            for mutation in patient["mutations"]:
                mutation_counts[mutation] += 1
        count_rows.append((
            dataset, country, year, len(patients),
            *(counts[key] for key in (
                "sdrm", "PR", "RT", "IN", "PI", "NRTI", "NNRTI", "INSTI"
            ))
        ))
        mutation_rows.extend(
            (dataset, country, year, mutation, count)
            for mutation, count in mutation_counts.items()
        )
    connection.executemany(
        "INSERT INTO dataset_patient_counts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        count_rows,
    )
    connection.executemany(
        "INSERT INTO dataset_patient_mutation_counts VALUES (?,?,?,?,?)",
        mutation_rows,
    )
    with args.scored_counts.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != [
            "dataset_name", "country_code", "isolate_year", "mutation", "num_persons"
        ]:
            raise ValueError(f"Unexpected scored-count columns: {args.scored_counts}")
        scored_rows = [(
            row["dataset_name"], row["country_code"],
            int(row["isolate_year"]), row["mutation"], int(row["num_persons"])
        ) for row in reader]
    with args.scored_options.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["mutation"]:
            raise ValueError(f"Unexpected scored-option columns: {args.scored_options}")
        scored_options = [row["mutation"] for row in reader]
    if not scored_options or len(scored_options) != len(set(scored_options)):
        raise ValueError(f"Empty or duplicate scored options: {args.scored_options}")
    if {row[3] for row in scored_rows} - set(scored_options):
        raise ValueError("Scored counts contain mutations absent from scored options")
    connection.executemany(
        "DELETE FROM dataset_patient_mutation_counts WHERE mutation = ?",
        ((mutation,) for mutation in scored_options),
    )
    connection.executemany(
        "INSERT INTO dataset_patient_mutation_counts VALUES (?,?,?,?,?)",
        scored_rows,
    )
    removed = remove_zero_person_datasets(connection)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = connection.execute(
        "UPDATE last_update SET last_update = ? WHERE scope = ?",
        (timestamp, "global"),
    )
    if updated.rowcount != 1:
        raise ValueError("Expected one global last_update row")
    connection.commit()
    print(f"Added {len(count_rows)} patient groups and {len(mutation_rows)} mutation groups")
    print(f"Added {len(scored_rows)} Sierra scored mutation groups")
    print(f"Removed {len(removed)} zero-person datasets: {', '.join(removed) or 'none'}")


if __name__ == "__main__":
    main()

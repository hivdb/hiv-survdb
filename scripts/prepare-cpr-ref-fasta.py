#!/usr/bin/env python3
"""Combine current continent FASTA files into one CPR input per ref_name."""

import csv
import hashlib
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path


TABLES = Path("payload/tables")
SOURCE = Path("local/cpr-fasta-current")
DESTINATION = Path("local/cpr-fasta-ref")
PREVIEW = Path("local/cpr-ref-report-links-preview.csv")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def slug(name):
    return re.sub(r"\s+", "-", name.lower()).replace("'", "").replace('"', "")


def fasta(path):
    rows = []
    header = None
    sequence = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith(">"):
                if header is not None:
                    rows.append((header, "".join(sequence)))
                header, sequence = line[1:], []
            elif line:
                sequence.append(line)
    if header is not None:
        rows.append((header, "".join(sequence)))
    return rows


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                     dir=path.parent, prefix=path.stem + ".",
                                     suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main():
    articles = {row["ref_name"]: row["ref_id"] for row in read_csv(TABLES / "articles.csv")}
    groups = defaultdict(list)
    for row in read_csv(TABLES / "datasets.csv"):
        groups[row["ref_name"]].append(row["dataset_name"])
    if set(groups) != set(articles):
        raise ValueError("articles and dataset RefIDs do not have the same reference names")
    preview = []
    for ref_name in sorted(groups):
        refslug = slug(ref_name)
        persons = {}
        selections = []
        for dataset in groups[ref_name]:
            dslug = slug(dataset)
            path = SOURCE / f"{dslug}-seq.fas"
            if not path.is_file():
                genes = {row["gene"] for row in read_csv(TABLES / "isolates.d" / f"{dslug}-iso.csv")}
                if genes == {"CA"}:
                    continue
                raise ValueError(f"missing POL FASTA: {path}")
            for header, sequence in fasta(path):
                match = re.fullmatch(re.escape(dslug) + r"\.PtID(\d+)", header)
                if not match:
                    raise ValueError(f"unexpected FASTA header: {header}")
                patient = match.group(1)
                if patient in persons:
                    raise ValueError(f"{ref_name}: PtID{patient} appears in multiple continent datasets")
                persons[patient] = sequence
            selections.extend(read_csv(SOURCE / f"{dslug}-selection.csv"))
        if not persons:
            raise ValueError(f"{ref_name}: no POL sequences")
        rows = [(patient, persons[patient]) for patient in sorted(persons, key=int)]
        output = DESTINATION / f"{refslug}-seq.fas"
        content = "".join(f">{refslug}.PtID{patient}\n{sequence}\n" for patient, sequence in rows)
        atomic_write(output, content)
        unknown = sum(int(row.get("unknown_insertion_count", 0)) for row in selections)
        preview.append({
            "dataset_name": ref_name, "ref_id": articles[ref_name],
            "fasta_file": output.name, "sequence_count": len(rows),
            "fasta_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "unknown_insertion_count": unknown, "report_url": "",
            "report_status": "awaiting CPR",
        })
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    with PREVIEW.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=preview[0])
        writer.writeheader()
        writer.writerows(preview)
    print(f"Prepared {len(preview)} ref_name CPR FASTA files and {PREVIEW}")


if __name__ == "__main__":
    main()

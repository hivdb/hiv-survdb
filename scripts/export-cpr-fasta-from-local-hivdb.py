#!/usr/bin/env python3
"""Export CPR FASTA for current isolate datasets from local, read-only HIVDB2."""

import argparse
import csv
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple


TABLES = Path("payload/tables")
GENE_LENGTHS = {"PR": 99, "RT": 560, "IN": 288}


class ExportError(Exception):
    pass


class Candidate(NamedTuple):
    patient: str
    gene: str
    date: str
    isolate_id: str
    source_name: str
    sequence_id: str
    accession: str
    clone_name: str
    species: str
    first_aa: str
    last_aa: str
    na: str
    subtype: str
    source: str
    seq_method: str
    date_entered: str


def slug(name):
    return re.sub(r"\s+", "-", name.lower()).replace("'", "").replace('"', "")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mysql_query(sql, args):
    command = [
        "mysql", "--protocol=tcp", "--batch", "--raw", "--skip-column-names",
        f"--host={args.host}", f"--port={args.port}", f"--user={args.user}",
        args.database, "--execute", sql,
    ]
    environment = os.environ.copy()
    if args.password is not None:
        environment["MYSQL_PWD"] = args.password
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                check=True, env=environment)
    except FileNotFoundError as exc:
        raise ExportError("mysql client is not installed") from exc
    except subprocess.CalledProcessError as exc:
        raise ExportError(exc.stderr.strip()) from exc
    return [line.split("\t") for line in result.stdout.splitlines()]


def sequence_for_gene(record, insertions):
    patient, gene, date = record.patient, record.gene, record.date
    sequence_id, species = record.sequence_id, record.species
    first, last, na = record.first_aa, record.last_aa, record.na
    if species != "HIV1":
        raise ExportError(f"PtID{patient} {gene} {date}: CPR POL export supports HIV1, got {species}")
    if first == "NULL" or last == "NULL" or na in ("NULL", ""):
        raise ExportError(f"PtID{patient} {gene} {date}: sequence {sequence_id} lacks nucleotide coordinates")
    first, last = int(first), int(last)
    if not 1 <= first <= last <= GENE_LENGTHS[gene]:
        raise ExportError(f"PtID{patient} {gene} {date}: invalid {gene} positions {first}-{last}")
    sequence = "." * (3 * (first - 1)) + na + "." * (3 * (GENE_LENGTHS[gene] - last))
    for position, insertion_na in sorted(insertions.get(sequence_id, []), reverse=True):
        if insertion_na == "NULL":
            raise ExportError(f"PtID{patient} {gene} {date}: insertion has no nucleotides")
        offset = 3 * position
        sequence = sequence[:offset] + insertion_na + sequence[offset:]
    return sequence.replace("~", "").upper()


def choose_sources(wanted, candidates):
    """Select the first complete source isolate, then its first shared clone."""
    sample_keys = defaultdict(list)
    for key in wanted:
        sample_keys[(key[0], key[2])].append(key)

    selected = {}
    problems = []
    for (patient, date), keys in sample_keys.items():
        if any(not candidates.get(key) for key in keys):
            problems.extend(
                f"PtID{key[0]} {key[1]} {key[2]}: no nucleotide sequence"
                for key in keys if not candidates.get(key)
            )
            continue
        all_options = [record for key in keys for record in candidates[key]]
        source_names = {record.source_name for record in all_options}
        source = min(
            source_names,
            key=lambda name: (
                -len({record.gene for record in all_options if record.source_name == name}),
                min(int(record.isolate_id) for record in all_options if record.source_name == name),
                name,
            ),
        )
        source_options = [record for record in all_options if record.source_name == source]
        clone_names = {record.clone_name for record in source_options
                       if record.clone_name not in ("NULL", "")}
        clone = None
        if clone_names:
            clone = min(
                clone_names,
                key=lambda name: (
                    -len({record.gene for record in source_options if record.clone_name == name}),
                    min(int(record.sequence_id) for record in source_options if record.clone_name == name),
                    name,
                ),
            )

        for key in keys:
            options = [record for record in candidates[key] if record.source_name == source]
            if not options:
                if len(candidates[key]) == 1:
                    options = candidates[key]
                else:
                    problems.append(f"PtID{patient} {key[1]} {date}: source {source} has no sequence")
                    continue
            if clone:
                same_clone = [record for record in options if record.clone_name == clone]
                if same_clone:
                    options = same_clone
            selected[key] = min(options, key=lambda record: int(record.sequence_id))
    return selected, problems


def export_dataset(dataset, ref_id, args):
    name = slug(dataset)
    isolate_path = TABLES / "isolates.d" / f"{name}-iso.csv"
    if not isolate_path.is_file():
        raise ExportError(f"missing isolate file: {isolate_path}")
    rows = read_csv(isolate_path)
    wanted = {}
    for row in rows:
        key = (row["patient_id"], row["gene"], row["isolate_date"])
        if key in wanted:
            raise ExportError(f"duplicate isolate key in {isolate_path}: {key}")
        wanted[key] = row
    if not wanted:
        raise ExportError(f"no isolates in {isolate_path}")

    sql = f"""
        SELECT I.PtID, I.Gene, DATE_FORMAT(I.IsolateDate, '%Y-%m-%d'),
               I.IsolateID, I.IsolateName, S.SequenceID, S.AccessionID,
               S.CloneName, SP.Species, S.Firstaa, S.Lastaa, S.NASeq,
               ST.Subtype, CI.Source, CI.SeqMethod,
               DATE_FORMAT(I.DateEntered, '%Y-%m-%d')
        FROM tblRefLink RL
        JOIN tblIsolates I ON RL.IsolateID=I.IsolateID
        JOIN tblClinIsolates CI ON I.IsolateID=CI.IsolateID
        JOIN tblSubtypes ST ON I.IsolateID=ST.IsolateID
        JOIN tblSpecies SP ON I.IsolateID=SP.IsolateID
        JOIN tblSequences S ON I.IsolateID=S.IsolateID
        WHERE RL.RefID={ref_id} AND I.Gene IN ('PR','RT','IN')
          AND S.SeqType='Sequence' AND S.NASeq IS NOT NULL
        ORDER BY I.PtID, I.IsolateDate, I.Gene, S.SequenceID
    """
    candidates = defaultdict(list)
    for record in mysql_query(sql, args):
        if len(record) != 16:
            raise ExportError(f"unexpected sequence query columns for {dataset}")
        record = Candidate(*record)
        key = (record.patient, record.gene, record.date)
        if key in wanted:
            candidates[key].append(record)

    insertion_sql = f"""
        SELECT X.SequenceID, X.CodonPos, X.NA
        FROM tblRefLink RL
        JOIN tblSequences S ON RL.IsolateID=S.IsolateID
        JOIN tblInsertions X ON S.SequenceID=X.SequenceID
        WHERE RL.RefID={ref_id} AND S.SeqType='Sequence'
    """
    insertions = defaultdict(list)
    for record in mysql_query(insertion_sql, args):
        if len(record) != 3:
            raise ExportError(f"unexpected insertion query columns for {dataset}")
        insertions[record[0]].append((int(record[1]), record[2]))

    choices, problems = choose_sources(wanted, candidates)
    selected = {}
    for key, record in choices.items():
        try:
            selected[key] = sequence_for_gene(record, insertions)
        except ExportError as exc:
            problems.append(str(exc))
    if problems:
        preview = "\n  ".join(problems[:10])
        raise ExportError(f"{dataset}: {len(problems)} sequence problems:\n  {preview}")

    changed = 0
    for key, record in choices.items():
        row = wanted[key]
        metadata = {
            "subtype": record.subtype,
            "source": record.source,
            "seq_method": record.seq_method,
            "genbank_accn": record.accession,
            "date_entered": record.date_entered,
        }
        if any(row[column] != value for column, value in metadata.items()):
            changed += 1
            row.update(metadata)
    if changed and not args.apply_source_selection:
        raise ExportError(
            f"{dataset}: {changed} isolate rows need the selected source metadata; "
            "rerun with --apply-source-selection"
        )

    samples = defaultdict(dict)
    names = {}
    for (patient, gene, date), sequence in selected.items():
        samples[(patient, date)][gene] = sequence
        names[(patient, date)] = wanted[(patient, gene, date)]["isolate_name"]
    if len(samples) > 10000:
        raise ExportError(f"{dataset}: {len(samples)} sequences exceeds the CPR form's 10,000-sequence limit")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{name}-seq.fas"
    manifest = args.output_dir / f"{name}-selection.csv"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                     dir=args.output_dir, prefix=name + ".",
                                     suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            for (patient, date), genes in samples.items():
                header_name = re.sub(r"\s+", "_", names[(patient, date)])
                header = f"{header_name}.{date}.PtID{patient}"
                sequence = "".join(genes.get(gene, "." * (3 * length))
                                   for gene, length in GENE_LENGTHS.items())
                sequence = sequence.strip(".").replace(".", "N")
                if not sequence or re.search(r"[^ACGTURYKMSWBDHVN-]", sequence):
                    raise ExportError(f"{dataset}: invalid nucleotide sequence for {header}")
                handle.write(f">{header}\n{sequence}\n")
        os.replace(temporary, output)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="",
                                     dir=args.output_dir, prefix=name + ".",
                                     suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            writer = csv.writer(handle)
            writer.writerow(("patient_id", "gene", "isolate_date", "source_isolate_name",
                             "source_isolate_id", "sequence_id", "accession_id", "clone_name"))
            for key, record in choices.items():
                writer.writerow((*key, record.source_name, record.isolate_id,
                                 record.sequence_id, record.accession, record.clone_name))
        os.replace(temporary, manifest)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    if changed:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="",
                                         dir=isolate_path.parent, prefix=name + ".",
                                         suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            os.replace(temporary, isolate_path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    print(f"{dataset}: {len(rows)} isolate rows -> {len(samples)} sequences -> {output}; {changed} source rows updated")


def export_selected_isolate_ids(dataset, ref_id, args):
    """Export one current selected IsolateID per gene and patient for CPR reports.

    The calculation payload has no exact isolate_date, so this path matches the
    source IsolateID directly and never changes isolate metadata or mutations.
    """
    name = slug(dataset)
    isolate_path = TABLES / "isolates.d" / f"{name}-iso.csv"
    rows = read_csv(isolate_path)
    wanted = {}
    patient_genes = {}
    for row in rows:
        if row["gene"] not in GENE_LENGTHS:
            continue
        isolate_id = row.get("hivdb_isolate_id") or ""
        if not isolate_id.isdigit():
            raise ExportError(f"{dataset}: missing hivdb_isolate_id for {row['isolate_name']}")
        if isolate_id in wanted:
            raise ExportError(f"{dataset}: duplicate IsolateID {isolate_id}")
        patient_gene = (row["patient_id"], row["gene"])
        if patient_gene in patient_genes:
            raise ExportError(f"{dataset}: multiple selected isolates for PtID{row['patient_id']} {row['gene']}")
        patient_genes[patient_gene] = isolate_id
        wanted[isolate_id] = row
    if not wanted:
        raise ExportError(f"{dataset}: no selected PR/RT/IN isolates")

    sql = f"""
        SELECT I.PtID, I.Gene, DATE_FORMAT(I.IsolateDate, '%Y-%m-%d'),
               I.IsolateID, I.IsolateName, S.SequenceID, S.AccessionID,
               S.CloneName, SP.Species, S.Firstaa, S.Lastaa, S.NASeq,
               ST.Subtype, CI.Source, CI.SeqMethod,
               DATE_FORMAT(I.DateEntered, '%Y-%m-%d')
        FROM tblRefLink RL
        JOIN tblIsolates I ON RL.IsolateID=I.IsolateID
        JOIN tblClinIsolates CI ON I.IsolateID=CI.IsolateID
        JOIN tblSubtypes ST ON I.IsolateID=ST.IsolateID
        JOIN tblSpecies SP ON I.IsolateID=SP.IsolateID
        JOIN tblSequences S ON I.IsolateID=S.IsolateID
        WHERE RL.RefID={ref_id} AND I.Gene IN ('PR','RT','IN')
          AND S.SeqType IN ('Sequence','Consensus') AND S.NASeq IS NOT NULL
        ORDER BY I.IsolateID, (S.SeqType='Sequence') DESC, S.SequenceID
    """
    candidates = {}
    for values in mysql_query(sql, args):
        if len(values) != 16:
            raise ExportError(f"unexpected sequence query columns for {dataset}")
        record = Candidate(*values)
        if record.isolate_id in wanted and record.isolate_id not in candidates:
            candidates[record.isolate_id] = record

    insertion_sql = f"""
        SELECT X.SequenceID, X.CodonPos, X.NA, X.AA
        FROM tblRefLink RL
        JOIN tblSequences S ON RL.IsolateID=S.IsolateID
        JOIN tblInsertions X ON S.SequenceID=X.SequenceID
        WHERE RL.RefID={ref_id}
    """
    insertions = defaultdict(list)
    unknown_insertions = defaultdict(int)
    selected_sequence_ids = {record.sequence_id for record in candidates.values()}
    for values in mysql_query(insertion_sql, args):
        if len(values) != 4:
            raise ExportError(f"unexpected insertion query columns for {dataset}")
        if values[0] in selected_sequence_ids:
            nucleotide = values[2]
            if nucleotide == "NULL" and args.unknown_insertions_as_n:
                nucleotide = "NNN" * len(values[3])
                unknown_insertions[values[0]] += 1
            insertions[values[0]].append((int(values[1]), nucleotide))

    problems = []
    samples = defaultdict(dict)
    for isolate_id, row in wanted.items():
        record = candidates.get(isolate_id)
        if record is None:
            problems.append(f"IsolateID{isolate_id} {row['gene']}: no nucleotide sequence")
            continue
        if record.patient != row["patient_id"] or record.gene != row["gene"]:
            problems.append(f"IsolateID{isolate_id}: patient or gene mismatch")
            continue
        try:
            samples[record.patient][record.gene] = sequence_for_gene(record, insertions)
        except ExportError as exc:
            problems.append(str(exc))
    if problems:
        raise ExportError(f"{dataset}: {len(problems)} sequence problems:\n  " + "\n  ".join(problems[:10]))
    if len(samples) > 10000:
        raise ExportError(f"{dataset}: {len(samples)} persons exceeds the CPR form's 10,000-sequence limit")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{name}-seq.fas"
    manifest = args.output_dir / f"{name}-selection.csv"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                 dir=args.output_dir, prefix=name + ".", suffix=".tmp",
                                 delete=False) as handle:
        temporary = Path(handle.name)
        for patient in sorted(samples, key=int):
            genes = samples[patient]
            sequence = "".join(genes.get(gene, "." * (3 * length))
                               for gene, length in GENE_LENGTHS.items())
            sequence = sequence.strip(".").replace(".", "N")
            if not sequence or re.search(r"[^ACGTURYKMSWBDHVN-]", sequence):
                raise ExportError(f"{dataset}: invalid nucleotide sequence for PtID{patient}")
            handle.write(f">{name}.PtID{patient}\n{sequence}\n")
    os.replace(temporary, output)
    with manifest.open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(("dataset_name", "patient_id", "gene", "hivdb_isolate_id", "sequence_id", "accession_id", "unknown_insertion_count"))
        for patient, gene in sorted(patient_genes):
            isolate_id = patient_genes[(patient, gene)]
            record = candidates[isolate_id]
            writer.writerow((dataset, patient, gene, isolate_id, record.sequence_id,
                             record.accession, unknown_insertions[record.sequence_id]))
    print(f"{dataset}: {len(wanted)} selected isolates -> {len(samples)} CPR sequences -> {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--dataset", help="dataset name or CSV filename stem")
    selection.add_argument("--all", action="store_true", help="export every dataset with an isolate CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("local/cpr-fasta"))
    parser.add_argument("--skip-existing", action="store_true",
                        help="resume a run by keeping FASTA files already in the output directory")
    parser.add_argument("--apply-source-selection", action="store_true",
                        help="update isolate CSV metadata to match the selected source sequences")
    parser.add_argument("--selected-isolate-ids", action="store_true",
                        help="export current selected IsolateIDs without changing payload data")
    parser.add_argument("--unknown-insertions-as-n", action="store_true",
                        help="represent insertion codons with missing nucleotide data as NNN; recorded in selection manifest")
    parser.add_argument("--host", default=os.getenv("LOCAL_HIVDB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("LOCAL_HIVDB_PORT", "3308")))
    parser.add_argument("--user", default=os.getenv("LOCAL_HIVDB_USER", "root"))
    parser.add_argument("--password", default=os.getenv("LOCAL_HIVDB_PASSWORD"))
    parser.add_argument("--database", default="HIVDB2")
    args = parser.parse_args()

    articles = {row["ref_name"]: row["ref_id"] for row in read_csv(TABLES / "articles.csv")}
    datasets = {slug(row["dataset_name"]): row for row in read_csv(TABLES / "datasets.csv")}
    if args.dataset:
        key = slug(args.dataset)
        if key not in datasets:
            parser.error(f"unknown dataset: {args.dataset}")
        names = [key]
    else:
        names = sorted(key for key in datasets if
                       (TABLES / "isolates.d" / f"{key}-iso.csv").is_file()
                       and read_csv(TABLES / "isolates.d" / f"{key}-iso.csv"))

    failures = 0
    skipped = 0
    no_pol = 0
    for key in names:
        if args.selected_isolate_ids:
            isolate_rows = read_csv(TABLES / "isolates.d" / f"{key}-iso.csv")
            if {row["gene"] for row in isolate_rows} == {"CA"}:
                print(f"{datasets[key]['dataset_name']}: CA only; no POL CPR report")
                no_pol += 1
                continue
        if args.skip_existing and (args.output_dir / f"{key}-seq.fas").is_file():
            skipped += 1
            continue
        dataset = datasets[key]
        ref_id = articles.get(dataset["ref_name"])
        if not ref_id or not ref_id.isdigit():
            print(f"{dataset['dataset_name']}: missing article RefID", file=sys.stderr)
            failures += 1
            continue
        try:
            if args.selected_isolate_ids:
                export_selected_isolate_ids(dataset["dataset_name"], int(ref_id), args)
            else:
                export_dataset(dataset["dataset_name"], int(ref_id), args)
        except ExportError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            failures += 1
    if failures:
        parser.exit(1, f"{failures} dataset(s) failed; {skipped} existing FASTA files skipped; "
                       f"{no_pol} CA-only datasets; review errors before running CPR\n")
    print(f"Export complete; {skipped} existing FASTA files skipped; "
          f"{no_pol} CA-only datasets have no POL report")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Submit the current POL FASTA files to CPR using local Sierra; resume safely."""

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path

import httpx


SIERRA_URL = "http://127.0.0.1:8111/sierra/rest/graphql"
CLIENT_SAVE_URL = "https://luszz5jjuj.execute-api.us-west-1.amazonaws.com/prod/client_save"
STORAGE_URL = "https://cprstorage.hivdb.org"
REPORT_URL = "https://hivdb.stanford.edu/cpr/report/?load="
SDRM_FILE = Path(__file__).with_name("cpr-pol-sdrm-2023.json")
RETRY_STATUSES = {202, 429, 502, 503, 504}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=path.stem + ".", suffix=".tmp",
                                     delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, separators=(",", ":"))
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def fasta_sequences(path):
    sequences = []
    header = None
    parts = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith(">"):
                if header is not None:
                    sequences.append({"header": header, "sequence": "".join(parts)})
                header, parts = line[1:], []
            elif line:
                if header is None:
                    raise ValueError(f"sequence before FASTA header in {path}")
                parts.append(line)
    if header is not None:
        sequences.append({"header": header, "sequence": "".join(parts)})
    if not sequences or any(not seq["header"] or not seq["sequence"] for seq in sequences):
        raise ValueError(f"empty FASTA record in {path}")
    if len({seq["header"] for seq in sequences}) != len(sequences):
        raise ValueError(f"duplicate FASTA header in {path}")
    return sequences


def cpr_query(custom_list):
    return """query Q($sequences:[UnalignedSequenceInput]!) {
      currentVersion { text publishDate }
      currentProgramVersion { text publishDate }
      sequenceAnalysis(sequences:$sequences) {
        inputSequence { header SHA512 }
        validationResults(includeGenes:[PR,RT,IN]) { level message }
        alignedGeneSequences(includeGenes:[PR,RT,IN]) {
          firstAA lastAA alignedNAs gene { name }
          SDRMs: mutations(filterOptions:[CUSTOMLIST], customList:%s) {
            position AAs isIndel shortText primaryType
          }
          mutations {
            position shortText AAs triplet isIndel hasStop isApobecMutation isUnusual
          }
          frameShifts { position text }
        }
      }
    }""" % json.dumps(custom_list)


async def post_retry(client, url, *, deadline, attempts=5, **kwargs):
    for attempt in range(attempts):
        try:
            response = await asyncio.wait_for(client.post(url, **kwargs), timeout=deadline)
            if response.status_code in RETRY_STATUSES:
                raise RuntimeError(f"HTTP {response.status_code} from {url}")
            response.raise_for_status()
            return response
        except (httpx.HTTPError, asyncio.TimeoutError, RuntimeError):
            if attempt + 1 == attempts:
                raise
            await asyncio.sleep(min(5 * 2 ** attempt, 30))


async def run_sierra(client, sequences, query, batch_size, url, concurrency):
    semaphore = asyncio.Semaphore(concurrency)

    async def analyze(start):
        async with semaphore:
            response = await post_retry(
                client, url, deadline=120,
                json={"query": query, "variables": {"sequences": sequences[start:start + batch_size]}},
            )
        doc = response.json()
        if doc.get("errors"):
            raise RuntimeError(f"Sierra GraphQL errors at sequence {start}: {doc['errors']}")
        data = doc["data"]
        batch = data.get("sequenceAnalysis") or []
        if len(batch) != min(batch_size, len(sequences) - start):
            raise RuntimeError(f"Sierra returned {len(batch)} analyses for batch at sequence {start}")
        return data

    starts = range(0, len(sequences), batch_size)
    results = await asyncio.gather(*(analyze(start) for start in starts))
    versions = {"currentVersion": results[0]["currentVersion"],
                "currentProgramVersion": results[0]["currentProgramVersion"]}
    if any(data["currentVersion"] != versions["currentVersion"] or
           data["currentProgramVersion"] != versions["currentProgramVersion"]
           for data in results):
        raise RuntimeError("Sierra version changed within the same CPR report")
    return {**versions,
            "sequenceAnalysis": [item for data in results for item in data["sequenceAnalysis"]]}


async def submit(client, sequences, sierra_result):
    response = await post_retry(client, CLIENT_SAVE_URL, deadline=60,
                                headers={"Content-Type": "application/json; charset=utf-8"})
    saved = response.json()
    key = saved["process_key"]
    blob = {
        "sdrmVer": "SDRM_2023", "seqType": "POL",
        "process_key": key, "sequences": sequences,
        "created_at": saved["utcnow"], "sierra_result": sierra_result,
    }
    payload = json.dumps(blob, separators=(",", ":")).encode()
    response = await post_retry(
        client, STORAGE_URL, deadline=180, data=saved["fields"],
        files={"file": (key, payload, "application/json")},
    )
    return key, saved["utcnow"], len(payload)


async def process_dataset(client, row, args, query):
    dataset = row["dataset_name"]
    fasta = args.fasta_dir / row["fasta_file"]
    digest = hashlib.sha256(fasta.read_bytes()).hexdigest()
    if digest != row["fasta_sha256"]:
        raise ValueError(f"{dataset}: FASTA changed since preview; regenerate preview")
    slug = fasta.name[:-8]
    receipt = args.output_dir / "receipts" / f"{slug}.json"
    if receipt.exists():
        existing = json.loads(receipt.read_text(encoding="utf-8"))
        if existing["fasta_sha256"] != digest:
            raise ValueError(f"{dataset}: existing report uses a different FASTA")
        print(f"SKIP {dataset}: {existing['url']}", flush=True)
        return
    sequences = fasta_sequences(fasta)
    if len(sequences) != int(row["sequence_count"]):
        raise ValueError(f"{dataset}: sequence count changed since preview")
    cache = args.output_dir / "sierra" / f"{slug}.json.gz"
    if cache.exists():
        with gzip.open(cache, "rt", encoding="utf-8") as handle:
            stored = json.load(handle)
        if stored["fasta_sha256"] != digest:
            raise ValueError(f"{dataset}: Sierra cache uses a different FASTA")
        sierra_result = stored["result"]
    else:
        sierra_result = await run_sierra(client, sequences, query, args.batch_size,
                                        args.sierra_url, args.sierra_concurrency)
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_name(cache.name + ".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8") as handle:
            json.dump({"fasta_sha256": digest, "result": sierra_result}, handle,
                      separators=(",", ":"))
        os.replace(temporary, cache)
    print(f"SIERRA {dataset}: {len(sequences)} sequences", flush=True)
    if args.dry_run:
        return
    key, created_at, bytes_sent = await submit(client, sequences, sierra_result)
    url = REPORT_URL + key
    atomic_json(receipt, {
        "dataset_name": dataset, "fasta_file": fasta.name,
        "fasta_sha256": digest, "sequence_count": len(sequences),
        "unknown_insertion_count": int(row["unknown_insertion_count"]),
        "process_key": key, "created_at": created_at,
        "bytes_sent": bytes_sent, "url": url,
    })
    print(f"REPORT {dataset}: {url}", flush=True)


def write_report_list(preview, output_dir):
    receipts = {}
    for path in (output_dir / "receipts").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        receipts[data["dataset_name"]] = data
    output = output_dir / "cpr_POL_current.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(("FASTA file", "CPR Result URL"))
        for row in preview:
            if row["dataset_name"] in receipts:
                data = receipts[row["dataset_name"]]
                if data["fasta_sha256"] != row["fasta_sha256"]:
                    raise ValueError(f"{row['dataset_name']}: stale report receipt")
                writer.writerow((row["fasta_file"], data["url"]))
                written += 1
    return written, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path, default=Path("local/cpr-ref-report-links-preview.csv"))
    parser.add_argument("--fasta-dir", type=Path, default=Path("local/cpr-fasta-ref"))
    parser.add_argument("--output-dir", type=Path, default=Path("local/cpr-reports"))
    parser.add_argument("--sierra-url", default=SIERRA_URL)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--sierra-concurrency", type=int, default=4)
    parser.add_argument("--dataset", help="submit one ref_name from the preview")
    parser.add_argument("--limit", type=int, help="submit at most this many pending datasets")
    parser.add_argument("--dry-run", action="store_true", help="run Sierra without saving reports")
    args = parser.parse_args()
    if (args.batch_size < 1 or args.batch_size > 100 or args.sierra_concurrency < 1
            or args.sierra_concurrency > 8 or (args.limit is not None and args.limit < 1)):
        parser.error("batch size must be 1-100, Sierra concurrency 1-8, and limit positive")
    sdrm = json.loads(SDRM_FILE.read_text(encoding="utf-8"))
    query = cpr_query(sdrm["customList"])
    preview = read_csv(args.preview)
    selected = [row for row in preview if row["report_status"] != "no POL genes"]
    if args.dataset:
        selected = [row for row in selected if row["dataset_name"] == args.dataset]
        if not selected:
            parser.error(f"no POL dataset named {args.dataset}")
    if args.limit is not None:
        selected = selected[:args.limit]

    async def driver():
        failures = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=30),
                                     follow_redirects=False) as client:
            for index, row in enumerate(selected, 1):
                try:
                    await process_dataset(client, row, args, query)
                except Exception as exc:
                    failures += 1
                    print(f"ERROR {index}/{len(selected)} {row['dataset_name']}: "
                          f"{type(exc).__name__}: {exc}", flush=True)
        completed, output = write_report_list(preview, args.output_dir)
        print(f"{completed}/{len(preview)} CPR report URLs in {output}; {failures} errors", flush=True)
        return failures

    raise SystemExit(1 if asyncio.run(driver()) else 0)


if __name__ == "__main__":
    main()

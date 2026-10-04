"""Conservative document-connected TRAIN groups; no split or training admission.

Rows sharing any source document are connected, including Hotpot distractors.
Title alias normalization is mechanical, not semantic entity resolution.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import os
from urllib.parse import unquote

from eval.compact_answering import train_rows
from eval.compact_answering.train_intake import ASSETS

POLICY = "all-documents-title-alias-or-normalized-context-v1"
MAX_ROWS = 300000


def document_keys(document: dict) -> tuple[str, str]:
    title = train_rows.text(document["title"])
    context = train_rows.text(document["context"])
    alias = train_rows.normalize(html.unescape(unquote(title)).replace("_", " "))
    if not alias:
        raise ValueError("empty normalized title")
    return "title:" + train_rows.sha(alias), "context:" + train_rows.sha(
        train_rows.normalize(context)
    )


def group_rows(rows):
    """Union by size with path compression; component IDs are input-order independent."""
    parents, sizes, minimum, records = [], [], [], []
    owners, identities = {}, set()
    allowed = {
        (repo, rev, path, digest)
        for repo, rev, path, _, digest in ASSETS
        if path.endswith(".parquet")
    }

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left, right):
        left, right = find(left), find(right)
        if left == right:
            return
        if sizes[left] < sizes[right]:
            left, right = right, left
        parents[right] = left
        sizes[left] += sizes[right]
        minimum[left] = min(minimum[left], minimum[right])

    for row in rows:
        index = len(records)
        if index >= MAX_ROWS:
            raise ValueError("grouping exceeds 300000-row local resource limit")
        source = row["source"]
        source_key = tuple(
            source[k] for k in ("repository", "revision", "path", "sha256")
        )
        if (
            source_key not in allowed
            or row["split"] != "train"
            or row["training_admitted"] is not False
        ):
            raise ValueError("only quarantined allowlisted TRAIN rows may be grouped")
        identity = json.dumps(
            [source["repository"], train_rows.text(row["upstream_id"])],
            separators=(",", ":"),
        )
        key = train_rows.sha(identity)
        if key in identities:
            raise ValueError("duplicate upstream identity")
        identities.add(key)
        raw_hash = row["raw_row_sha256"]
        if (
            not isinstance(raw_hash, str)
            or len(raw_hash) != 64
            or any(c not in "0123456789abcdef" for c in raw_hash)
        ):
            raise ValueError("invalid raw-row hash")
        documents = row["documents"]
        if not isinstance(documents, list) or not 1 <= len(documents) <= 20:
            raise ValueError("invalid document count")
        parents.append(index)
        sizes.append(1)
        minimum.append(key)
        records.append(
            {
                "row_identity_sha256": key,
                "raw_row_sha256": raw_hash,
                "repository": source["repository"],
            }
        )
        for document in documents:
            for doc_key in document_keys(document):
                if doc_key in owners:
                    union(index, owners[doc_key])
                else:
                    owners[doc_key] = index
    if not records:
        raise ValueError("empty corpus")
    totals = Counter()
    for index, record in enumerate(records):
        group = minimum[find(index)]
        record["group_id"] = group
        totals[group] += 1
    summary = {
        "rows": len(records),
        "groups": len(totals),
        "largest_group_rows": max(totals.values()),
        "group_size_histogram": dict(sorted(Counter(totals.values()).items())),
        "document_keys": len(owners),
    }
    return records, summary


def run(staged: Path, destination: Path):
    transform = train_rows.sha(Path(__file__).read_text())
    normalizer = train_rows.sha(Path(train_rows.__file__).read_text())
    receipt_bytes = (staged / "staging.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    if (
        receipt["schema"] != "mnemosyne.compact-train-staging.v1"
        or receipt["training_admitted"] is not False
    ):
        raise ValueError("not quarantined staging")
    path = staged / "rows.jsonl"
    if path.is_symlink() or not path.is_file():
        raise ValueError("rows must be a regular file")
    expected = receipt["files"]["rows.jsonl"]
    with path.open("rb") as stream:
        if (
            path.stat().st_size != expected["bytes"]
            or hashlib.file_digest(stream, "sha256").hexdigest() != expected["sha256"]
        ):
            raise ValueError("staged rows drifted")
        stream.seek(0)

        def rows():
            while line := stream.readline(1024 * 1024 + 1):
                if len(line) > 1024 * 1024:
                    raise ValueError("row exceeds 1 MiB local resource limit")
                yield json.loads(line)

        records, summary = group_rows(rows())
    destination.mkdir(parents=True, exist_ok=False)
    pending = destination / "groups.jsonl.partial"
    with pending.open("x") as output:
        for record in sorted(records, key=lambda r: r["row_identity_sha256"]):
            output.write(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            )
        output.flush()
        os.fsync(output.fileno())
    os.link(pending, destination / "groups.jsonl")
    pending.unlink()
    with (destination / "groups.jsonl").open("rb") as stream:
        groups_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {
        "schema": "mnemosyne.compact-train-groups.v1",
        "policy": POLICY,
        "transform_sha256": transform,
        "normalizer_module_sha256": normalizer,
        "staging_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "staged_rows": expected,
        "groups_sha256": groups_hash,
        "summary": summary,
        "training_admitted": False,
        "partition_status": "unassigned",
        "protected_overlap": "unchecked",
        "semantic_entity_resolution": "not-performed",
    }
    pending = destination / "summary.json.partial"
    with pending.open("x") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.link(pending, destination / "summary.json")
    pending.unlink()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staged", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.staged, args.destination)["summary"], sort_keys=True))


if __name__ == "__main__":
    main()

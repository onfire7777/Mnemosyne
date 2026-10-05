"""Freeze a deterministic whole-component partition plan; admission remains closed.

Descending component sizes fill the largest absolute remaining target deficit.
Targets are 80/10/10; ties use train, selection, calibration in that order.
No labels, model scores, protected results, or randomized seed search are used.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path

PARTS = ("train", "selection", "calibration")
WEIGHTS = (8, 1, 1)
POLICY = "whole-component-descending-size-largest-deficit-80-10-10-v1"


def assign(sizes: dict[str, int]) -> dict[str, str]:
    if not sizes or any(
        not isinstance(k, str) or not k or type(v) is not int or v < 1
        for k, v in sizes.items()
    ):
        raise ValueError("group sizes must be nonempty positive integers")
    total = sum(sizes.values())
    counts = dict.fromkeys(PARTS, 0)
    result = {}
    for group in sorted(sizes, key=lambda g: (-sizes[g], g)):
        # Integer deficits avoid rounding/platform differences. max preserves tie order.
        part = max(
            PARTS, key=lambda p: WEIGHTS[PARTS.index(p)] * total - 10 * counts[p]
        )
        result[group] = part
        counts[part] += sizes[group]
    return result


def plan(grouped: Path, destination: Path):
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt_bytes = (grouped / "summary.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    if (
        receipt["schema"] != "mnemosyne.compact-train-groups.v1"
        or receipt["training_admitted"] is not False
    ):
        raise ValueError("requires quarantined group receipt")
    path = grouped / "groups.jsonl"
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 128 * 1024 * 1024
    ):
        raise ValueError("invalid or oversized group membership file")
    sizes, families, identities = Counter(), defaultdict(Counter), set()
    with path.open("rb") as stream:
        if (
            hashlib.file_digest(stream, "sha256").hexdigest()
            != receipt["groups_sha256"]
        ):
            raise ValueError("group membership drift")
        stream.seek(0)
        for line in stream:
            record = json.loads(line)
            identity, group = record["row_identity_sha256"], record["group_id"]
            if identity in identities:
                raise ValueError("duplicate membership")
            identities.add(identity)
            sizes[group] += 1
            families[group][record["repository"]] += 1
    if (
        len(identities) != receipt["summary"]["rows"]
        or len(sizes) != receipt["summary"]["groups"]
    ):
        raise ValueError("group summary disagrees with membership")
    assignment = assign(sizes)
    counts, source_counts = Counter(), defaultdict(Counter)
    for group, part in assignment.items():
        counts[part] += sizes[group]
        source_counts[part].update(families[group])
    result = {
        "schema": "mnemosyne.compact-train-partition-plan.v1",
        "policy": POLICY,
        "transform_sha256": source_hash,
        "group_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "groups_sha256": receipt["groups_sha256"],
        "targets": dict(zip(PARTS, (0.8, 0.1, 0.1))),
        "rows": dict(counts),
        "source_rows": {p: dict(source_counts[p]) for p in PARTS},
        "assignments": dict(sorted(assignment.items())),
        "training_admitted": False,
        "status": "frozen-quarantined-plan",
        "unresolved": [
            "semantic entity resolution",
            "pre/post protected overlap screening",
            "whole-component exclusions",
            "license and attribution custody",
        ],
        "exclusion_rule": "Remove entire contaminated components; do not reassign or rebalance surviving components.",
    }
    destination.mkdir(parents=True, exist_ok=False)
    pending = destination / "partitions.json.partial"
    with pending.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.link(pending, destination / "partitions.json")
    pending.unlink()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("grouped", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = plan(args.grouped, args.destination)
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("rows", "source_rows", "status", "training_admitted")
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

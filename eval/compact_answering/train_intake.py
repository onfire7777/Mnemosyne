"""Download only pinned, authorized TRAIN assets into a new quarantine directory.

No parquet parsing, model loading, partition selection or training admission occurs.
The fixed allowlist deliberately has no URL, revision or split override.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

# Repo, revision, path, size, SHA-256. Data hashes are upstream LFS OIDs;
# card hashes were computed from the exact pinned bytes on 2026-10-04.
ASSETS = (
    (
        "rajpurkar/squad_v2",
        "3ffb306f725f7d2ce8394bc1873b24868140c412",
        "README.md",
        8916,
        "7a6726352072e8517318959fe0438d4f45880affc041ced6da3bf2e4dec94c68",
    ),
    (
        "rajpurkar/squad_v2",
        "3ffb306f725f7d2ce8394bc1873b24868140c412",
        "squad_v2/train-00000-of-00001.parquet",
        16369982,
        "f6da32ffb482ff463ad056477740d1bb284b96a45db3a08bee6a225ca6abf291",
    ),
    (
        "hotpotqa/hotpot_qa",
        "1908d6afbbead072334abe2965f91bd2709910ab",
        "README.md",
        9522,
        "3cfab003a856275d3198b031c6b2ac46c63178fb462a4123705f652b71b22813",
    ),
    (
        "hotpotqa/hotpot_qa",
        "1908d6afbbead072334abe2965f91bd2709910ab",
        "distractor/train-00000-of-00002.parquet",
        165624177,
        "76d3bb3048a7cc73c1958107c0c5872a00d7e7d00c105b81e92f6769e7822e68",
    ),
    (
        "hotpotqa/hotpot_qa",
        "1908d6afbbead072334abe2965f91bd2709910ab",
        "distractor/train-00001-of-00002.parquet",
        166162479,
        "713661628434fbb19fff7392e2e321e4ed107e3c7c7784d0690946e5f722763f",
    ),
)


def _copy_verified(stream, target: Path, size: int, sha256: str) -> None:
    """Bound bytes/time, verify, then expose the completed asset without overwrite."""
    partial = target.with_name(target.name + ".partial")
    digest = hashlib.sha256()
    count = 0
    deadline = time.monotonic() + 600
    # Exclusive creation keeps an existing failed attempt intact.
    with partial.open("xb") as output:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("asset transfer exceeded ten minutes")
            block = stream.read(min(1024 * 1024, size - count + 1))
            if not block:
                break
            count += len(block)
            if count > size:
                raise ValueError("asset exceeds pinned size")
            output.write(block)
            digest.update(block)
        if count != size or digest.hexdigest() != sha256:
            raise ValueError("asset size or SHA-256 differs from pin")
        output.flush()
        os.fsync(output.fileno())
    os.link(partial, target)
    partial.unlink()


def intake(destination: Path) -> dict:
    """Create a new intake; failures retain partial bytes and no completion receipt.

    The destination parent must be operator-owned (not an adversarial shared tree).
    No credentials or ambient Hugging Face tokens are read or sent.
    """
    transform_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    destination.mkdir(parents=True, exist_ok=False)
    assets = []
    for repo, revision, path, size, digest in ASSETS:
        relative = f"{repo}/{revision}/{path}"
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{path}"
        with urllib.request.urlopen(url, timeout=30) as response:
            _copy_verified(response, target, size, digest)
        assets.append(
            {
                "repository": repo,
                "revision": revision,
                "upstream_path": path,
                "local_path": relative,
                "bytes": size,
                "sha256": digest,
                "source_url": url,
                "role": "license-card" if path == "README.md" else "train",
            }
        )
    receipt = {
        "schema": "mnemosyne.compact-train-intake.v1",
        "transform_sha256": transform_sha256,
        "assets": assets,
        "license": "CC-BY-SA-4.0 (upstream cards; preserve attribution and share-alike)",
        "status": "quarantined-raw-train-only",
        "training_admitted": False,
        "unresolved": [
            "row provenance and exact-span validation",
            "source-document/entity clustering",
            "pre/post transformation protected-overlap checks",
            "frozen grouped partitions",
            "complete attribution and derivative license review",
        ],
    }
    pending_receipt = destination / "intake.json.partial"
    with pending_receipt.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.link(pending_receipt, destination / "intake.json")
    pending_receipt.unlink()
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    receipt = intake(args.destination)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "assets": len(receipt["assets"]),
                "bytes": sum(a["bytes"] for a in receipt["assets"]),
                "training_admitted": False,
            }
        )
    )


if __name__ == "__main__":
    main()

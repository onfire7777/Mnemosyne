#!/usr/bin/env python3
"""Verify a topology-only refresh tree against its allowed sources."""

from __future__ import annotations

import re
import subprocess
import sys


SHA = re.compile(r"[0-9a-fA-F]{40}")
LIFECYCLE_PATHS = (
    b".planning/STATE.md",
    b"GOAL.md",
    b"docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md",
)


def _path(path: bytes) -> str:
    return path.decode("utf-8", "backslashreplace")


def _tree(ref: str) -> dict[bytes, tuple[bytes, bytes, bytes]]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--full-tree", ref],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"cannot read tree for {ref}")

    entries: dict[bytes, tuple[bytes, bytes, bytes]] = {}
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path = record.split(b"\t", 1)
            mode, kind, oid = metadata.split(b" ")
        except ValueError as error:
            raise ValueError(f"cannot parse tree for {ref}") from error
        if path in entries:
            raise ValueError(f"cannot parse tree for {ref}")
        entries[path] = (mode, kind, oid)
    return entries


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: verify-topology-refresh.py <candidate-40-sha> <permitted-parent-40-sha> <immutable-anchor-40-sha>")
        return 2
    candidate_ref, parent_ref, anchor_ref = argv[1:]
    if not all(SHA.fullmatch(ref) for ref in (candidate_ref, parent_ref, anchor_ref)):
        print("error: candidate, permitted parent, and immutable anchor must be full 40-hex SHAs")
        return 2
    try:
        candidate = _tree(candidate_ref)
        parent = _tree(parent_ref)
        anchor = _tree(anchor_ref)
    except (OSError, ValueError) as error:
        print(f"error: {error}")
        return 2

    errors: list[str] = []
    lifecycle = set(LIFECYCLE_PATHS)
    for path in LIFECYCLE_PATHS:
        candidate_entry = candidate.get(path)
        parent_entry = parent.get(path)
        if candidate_entry is None:
            errors.append(f"lifecycle path missing from candidate: {_path(path)}")
        if parent_entry is None:
            errors.append(f"lifecycle path missing from permitted parent: {_path(path)}")
        if candidate_entry is not None and parent_entry is not None and candidate_entry != parent_entry:
            errors.append(f"lifecycle path differs from permitted parent: {_path(path)}")

    for path in sorted((set(candidate) | set(anchor)) - lifecycle):
        if candidate.get(path) != anchor.get(path):
            errors.append(f"immutable path differs from anchor: {_path(path)}")
    if errors:
        print("\n".join(sorted(errors)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

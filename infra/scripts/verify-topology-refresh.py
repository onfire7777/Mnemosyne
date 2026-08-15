#!/usr/bin/env python3
"""Verify a topology-only refresh tree against its allowed sources."""

from __future__ import annotations

import os
import re
import subprocess
import sys


SHA = re.compile(r"[0-9a-f]{40}")
OID = re.compile(rb"[0-9a-f]{40}")
LIFECYCLE_PATHS = (
    b".planning/STATE.md",
    b"GOAL.md",
    b"docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md",
)
LIFECYCLE_ENTRY = (b"100644", b"blob")
TREE_ENTRY_KINDS = {
    b"040000": b"tree",
    b"100644": b"blob",
    b"100755": b"blob",
    b"120000": b"blob",
    b"160000": b"commit",
}
GIT = ("git", "--no-replace-objects")
GIT_ENV = {**os.environ, "GIT_GRAFT_FILE": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1"}


def _path(path: bytes) -> str:
    return ascii(path)[2:-1]


def _tree(ref: str) -> dict[bytes, tuple[bytes, bytes, bytes]]:
    try:
        result = subprocess.run(
            [*GIT, "ls-tree", "-r", "-t", "-z", "--full-tree", ref],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=GIT_ENV,
            check=False,
        )
    except OSError as error:
        raise RuntimeError("cannot run git") from error
    if result.returncode:
        raise ValueError(f"cannot read tree for {ref}")
    if result.stdout and not result.stdout.endswith(b"\0"):
        raise ValueError(f"cannot parse tree for {ref}")

    entries: dict[bytes, tuple[bytes, bytes, bytes]] = {}
    for record in result.stdout[:-1].split(b"\0") if result.stdout else ():
        if not record:
            raise ValueError(f"cannot parse tree for {ref}")
        try:
            metadata, path = record.split(b"\t", 1)
            mode, kind, oid = metadata.split(b" ")
        except ValueError as error:
            raise ValueError(f"cannot parse tree for {ref}") from error
        if (
            not path
            or TREE_ENTRY_KINDS.get(mode) != kind
            or not OID.fullmatch(oid)
            or path in entries
        ):
            raise ValueError(f"cannot parse tree for {ref}")
        entries[path] = (mode, kind, oid)
    return entries


def _require_exact_commit(ref: str) -> None:
    try:
        result = subprocess.run(
            [*GIT, "rev-parse", "--verify", f"{ref}^{{commit}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=GIT_ENV,
            check=False,
        )
    except OSError as error:
        raise RuntimeError("cannot run git") from error
    if result.returncode or result.stdout.strip() != ref.encode("ascii"):
        raise ValueError(f"not an exact commit SHA: {ref}")


def _require_complete_history() -> None:
    try:
        result = subprocess.run(
            [*GIT, "rev-parse", "--is-shallow-repository"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=GIT_ENV,
            check=False,
        )
    except OSError as error:
        raise RuntimeError("cannot run git") from error
    if result.returncode or result.stdout != b"false\n":
        raise ValueError("repository history is shallow or unreadable")


def _is_ancestor(parent_ref: str, candidate_ref: str) -> bool:
    try:
        result = subprocess.run(
            [*GIT, "merge-base", "--is-ancestor", parent_ref, candidate_ref],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=GIT_ENV,
            check=False,
        )
    except OSError as error:
        raise RuntimeError("cannot run git") from error
    if result.returncode not in (0, 1):
        raise ValueError("cannot verify permitted parent ancestry")
    return result.returncode == 0


def _has_only_candidate_commit(
    candidate_ref: str, parent_ref: str, anchor_ref: str
) -> bool:
    try:
        result = subprocess.run(
            [*GIT, "rev-list", candidate_ref, "--not", parent_ref, anchor_ref],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=GIT_ENV,
            check=False,
        )
    except OSError as error:
        raise RuntimeError("cannot run git") from error
    if result.returncode:
        raise ValueError("cannot verify candidate history")
    return result.stdout == f"{candidate_ref}\n".encode("ascii")


def _same_entry(
    left: tuple[bytes, bytes, bytes] | None,
    right: tuple[bytes, bytes, bytes] | None,
) -> bool:
    if left is None or right is None:
        return left == right
    if left[:2] == right[:2] == (b"040000", b"tree"):
        return True
    return left == right


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "usage: verify-topology-refresh.py <candidate-40-sha> <permitted-parent-40-sha> <immutable-anchor-40-sha>"
        )
        return 2
    candidate_ref, parent_ref, anchor_ref = argv[1:]
    if not all(SHA.fullmatch(ref) for ref in (candidate_ref, parent_ref, anchor_ref)):
        print(
            "error: candidate, permitted parent, and immutable anchor must be full 40-hex SHAs"
        )
        return 2
    try:
        _require_complete_history()
        for ref in (candidate_ref, parent_ref, anchor_ref):
            _require_exact_commit(ref)
        if not _is_ancestor(parent_ref, candidate_ref):
            print("candidate does not descend from permitted parent")
            return 1
        history_valid = _has_only_candidate_commit(
            candidate_ref, parent_ref, anchor_ref
        )
        candidate = _tree(candidate_ref)
        parent = _tree(parent_ref)
        anchor = _tree(anchor_ref)
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}")
        return 2

    errors: list[str] = []
    if not history_valid:
        errors.append(
            "candidate history contains commits outside permitted parent and immutable anchor"
        )
    lifecycle = set(LIFECYCLE_PATHS)
    for path in LIFECYCLE_PATHS:
        candidate_entry = candidate.get(path)
        parent_entry = parent.get(path)
        if candidate_entry is None:
            errors.append(f"lifecycle path missing from candidate: {_path(path)}")
        if parent_entry is None:
            errors.append(
                f"lifecycle path missing from permitted parent: {_path(path)}"
            )
        if candidate_entry is not None and candidate_entry[:2] != LIFECYCLE_ENTRY:
            errors.append(
                f"lifecycle path is not a regular file in candidate: {_path(path)}"
            )
        if parent_entry is not None and parent_entry[:2] != LIFECYCLE_ENTRY:
            errors.append(
                f"lifecycle path is not a regular file in permitted parent: {_path(path)}"
            )
        if (
            candidate_entry is not None
            and parent_entry is not None
            and candidate_entry[:2] == parent_entry[:2] == LIFECYCLE_ENTRY
            and candidate_entry != parent_entry
        ):
            errors.append(
                f"lifecycle path differs from permitted parent: {_path(path)}"
            )

    for path in sorted((set(candidate) | set(anchor)) - lifecycle):
        if not _same_entry(candidate.get(path), anchor.get(path)):
            errors.append(f"immutable path differs from anchor: {_path(path)}")
    if errors:
        print("\n".join(sorted(errors)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

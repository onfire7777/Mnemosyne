"""Content-addressed receipts for the source tree used by offline evaluation.

The scope excludes dataset payloads and generated outputs, not executable judges
stored beside datasets. This is source provenance, not an environment attestation
or a filesystem lock: run from a quiescent checkout for release evidence.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any


_SCOPE = "mnemosyne-quality-gate-source-v2"
_SOURCE_ROOTS = (
    "src", "eval", "tools", "config", "configs", "scripts",
    "tests/completion/security", "rust/mnemosyne-native",
)
_DEPENDENCY_GLOBS = (
    "pyproject.toml", "uv.lock", "requirements*.txt", "requirements*.in",
    "setup.py", "setup.cfg", "Pipfile*", "poetry.lock",
)
_GENERATED_ROOTS = (
    "eval/reports", "eval/learning/reports", "eval/outputs", "eval/perf/golden",
    "eval/longmemeval_s/LongMemEval-results", "rust/mnemosyne-native/target",
)
_DATASET_SUFFIXES = {".json", ".jsonl", ".csv", ".tsv", ".parquet", ".arrow", ".gz", ".zip", ".zst"}


def _excluded_directory(path: Path) -> bool:
    # Boundaries are repository-relative, never arbitrary directory basenames:
    # src/pkg/results and config/datasets can contain executable/runtime inputs.
    return any(path.is_relative_to(root) for root in _GENERATED_ROOTS) or (
        len(path.parts) >= 2 and path.parts[0] == "src"
        and path.parts[1].endswith((".egg-info", ".dist-info"))
    )


def _is_source(path: Path) -> bool:
    if _excluded_directory(path):
        return False
    if path.suffix in {".pyc", ".pyo"}:
        return False
    if path.is_relative_to("eval/datasets") and path.suffix in _DATASET_SUFFIXES:
        return False
    return any(path.is_relative_to(root) for root in _SOURCE_ROOTS) or (
        len(path.parts) == 1 and any(fnmatch.fnmatch(path.name, pattern) for pattern in _DEPENDENCY_GLOBS)
    )


def _source_paths(repo: Path) -> list[Path]:
    def fail(exc: OSError) -> None:
        raise exc

    paths = set()
    for name in _SOURCE_ROOTS:
        root = repo / name
        if root.is_symlink() or root.resolve() != root:
            raise OSError(f"Symlink source directory: {name}")
        if not root.exists():
            continue
        for directory, dirs, files in os.walk(root, onerror=fail):
            dirs[:] = sorted(
                d for d in dirs if not _excluded_directory((Path(directory) / d).relative_to(repo))
            )
            if any((Path(directory) / d).is_symlink() for d in dirs):
                raise OSError(f"Symlink source directory under {name}")
            paths.update(
                Path(directory) / filename for filename in files
                if _is_source((Path(directory) / filename).relative_to(repo))
            )
    for pattern in _DEPENDENCY_GLOBS:
        paths.update(repo.glob(pattern))
    return sorted(paths)


def _git(repo: Path, *args: str, input: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args], cwd=repo,
        input=input, capture_output=True, check=True, timeout=10,
    ).stdout


def _reject_custom_filters(repo: Path, names: bytes) -> None:
    # Never launch a repository-defined clean/process driver, including via status.
    values = _git(repo, "check-attr", "-z", "--stdin", "filter", input=names).split(b"\0")
    if values[-1] != b"" or (len(values) - 1) % 3:
        raise ValueError("Invalid Git filter attributes")
    if any(value not in {b"unspecified", b"unset"} for value in values[2::3]):
        raise ValueError("Custom Git content filters are unsupported for source verification")


def _git_state(repo: Path) -> tuple[str, bytes]:
    root = Path(os.fsdecode(_git(repo, "rev-parse", "--show-toplevel").removesuffix(b"\n"))).resolve()
    if root != repo:
        raise ValueError("Source root is not the Git worktree root")
    commit = _git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("Invalid Git revision")
    _reject_custom_filters(repo, _git(repo, "ls-files", "--cached", "-z"))
    return commit, _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")


def _file_signature(path: Path) -> tuple[int, ...]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"Not a regular source file: {path.name}")
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def validate_report_outputs(repo: Path, *outputs: Path | None) -> None:
    """Reject source destinations and filesystem aliases before any evaluation/write.

    Only report documents in eval/reports or outside the checkout are writable.
    Recheck at publication; this is not a lock against hostile concurrent renames.
    """
    repo = repo.resolve()
    seen: set[str] = set()
    for output in outputs:
        if output is None:
            continue
        path = output if output.is_absolute() else Path.cwd() / output
        # Inspect before resolve() collapses symlinks or '..'. Broken links count.
        for part in (path, *path.parents):
            try:
                info = part.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                raise ValueError(f"Output has a symlink component: {output}")
            if part == path:
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError(f"Output must be a regular, non-aliased file: {output}")
            elif not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"Output ancestor is not a directory: {output}")
        path = path.resolve()
        # Inode comparisons also find case aliases of the checkout on macOS.
        for parent in path.parents:
            if parent.exists() and parent.samefile(repo):
                relative = path.relative_to(parent)
                if not relative.is_relative_to("eval/reports") or _is_source(relative):
                    raise ValueError(f"Output inside checkout must be under eval/reports: {output}")
                break
        if path.suffix.lower() not in {".json", ".md"}:
            raise ValueError(f"Output must be a .json or .md report document: {output}")
        # Conservatively reject case-only aliases even before either file exists.
        key = str(path).casefold()
        if key in seen:
            raise ValueError("Output destinations must be different files")
        seen.add(key)


def capture_source_provenance(repo: Path) -> dict[str, Any]:
    """Hash working bytes, including ignored/untracked source, not the index.

    git_dirty uses Git-normalized content compared with HEAD, bypassing index
    flags/stat caches. The fingerprint always hashes raw bytes; null means unknown.
    """
    repo = repo.resolve()
    receipt: dict[str, Any] = {
        "git_commit": "unknown", "git_dirty": None,
        "source_fingerprint": None, "source_file_count": 0,
        "fingerprint_scope": _SCOPE, "errors": [],
    }
    git_start = None
    head_sources = None
    try:
        git_start = _git_state(repo)
        receipt["git_commit"] = git_start[0]
        head_sources = {}
        for entry in _git(repo, "ls-tree", "-r", "-z", "--full-tree", git_start[0]).split(b"\0"):
            if not entry:
                continue
            attributes, name = entry.split(b"\t", 1)
            mode, kind, oid = attributes.decode("ascii").split()
            relative = Path(os.fsdecode(name))
            if _is_source(relative):
                if kind != "blob":
                    raise ValueError("Source submodules are not supported")
                head_sources[relative.as_posix()] = (mode, oid)
        receipt["git_dirty"] = bool(git_start[1])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        head_sources = None
        receipt["errors"].append(f"Git state unavailable: {type(exc).__name__}: {exc}")
    try:
        paths = _source_paths(repo)
        signatures = {path: _file_signature(path) for path in paths}
        if head_sources is not None:
            _reject_custom_filters(repo, b"".join(
                os.fsencode(path.relative_to(repo)) + b"\0" for path in paths
            ))
        manifest = []
        working_sources = {}
        algorithm = "sha256" if len(receipt["git_commit"]) == 64 else "sha1"
        for path in paths:
            content = path.read_bytes()
            mode = "100755" if signatures[path][2] & stat.S_IXUSR else "100644"
            relative = path.relative_to(repo).as_posix()
            manifest.append([relative, mode, hashlib.sha256(content).hexdigest()])
            # Most blobs need no normalization subprocess. For changed bytes, let
            # Git handle built-in conversions (autocrlf/text/eol/ident/encoding)
            # on exactly the bytes hashed above, not cached index observations.
            oid = hashlib.new(algorithm, f"blob {len(content)}\0".encode() + content).hexdigest()
            if head_sources is not None and relative in head_sources and oid != head_sources[relative][1]:
                oid = _git(repo, "hash-object", f"--path={relative}", "--stdin", input=content).decode("ascii").strip()
                if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
                    raise ValueError("Invalid normalized Git object ID")
            working_sources[relative] = (mode, oid)
        if paths != _source_paths(repo) or any(
            _file_signature(path) != signatures[path] for path in paths
        ):
            raise OSError("Source changed while fingerprinting")
        receipt["source_fingerprint"] = hashlib.sha256(
            json.dumps(manifest, separators=(",", ":")).encode()
        ).hexdigest()
        receipt["source_file_count"] = len(manifest)
        if head_sources is not None:
            receipt["git_dirty"] = receipt["git_dirty"] or working_sources != head_sources
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        receipt["git_dirty"] = None
        receipt["source_fingerprint"] = None
        receipt["errors"].append(f"Source fingerprint unavailable: {type(exc).__name__}: {exc}")
    if git_start is not None:
        try:
            if _git_state(repo) != git_start:
                raise ValueError("Git state changed while fingerprinting")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            receipt["git_dirty"] = None
            receipt["source_fingerprint"] = None
            receipt["errors"].append(f"Git state unverifiable: {type(exc).__name__}: {exc}")
    return receipt


def _verified(snapshot: dict[str, Any]) -> bool:
    return (
        isinstance(snapshot.get("git_commit"), str)
        and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", snapshot["git_commit"]) is not None
        and type(snapshot.get("git_dirty")) is bool
        and isinstance(snapshot.get("source_fingerprint"), str)
        and re.fullmatch(r"[0-9a-f]{64}", snapshot["source_fingerprint"]) is not None
        and type(snapshot.get("source_file_count")) is int and snapshot["source_file_count"] > 0
        and snapshot.get("fingerprint_scope") == _SCOPE
        and snapshot.get("errors") == []
    )


def compare_source_provenance(start: dict[str, Any], end: dict[str, Any]) -> dict[str, Any]:
    """Describe a run without treating two unknown observations as equality."""
    verified = _verified(start) and _verified(end)
    changed = any(
        isinstance(start.get(key), str) and isinstance(end.get(key), str)
        and re.fullmatch(pattern, start[key]) and re.fullmatch(pattern, end[key])
        and start[key] != end[key]
        for key, pattern in (
            ("git_commit", r"[0-9a-f]{40}|[0-9a-f]{64}"),
            ("source_fingerprint", r"[0-9a-f]{64}"),
        )
    )
    source_changed = True if changed else (False if verified else None)
    clean = verified and start["git_dirty"] is False and end["git_dirty"] is False
    status = "changed" if changed else ("unknown" if not verified else ("clean" if clean else "dirty"))
    return {
        "start": start, "end": end, "source_changed": source_changed,
        "status": status, "release_eligible": clean and source_changed is False,
    }

"""Which build of Mnemosyne is running.

A memory server that has been running for a week, or a copy bundled beside
another program, can be several commits behind the checkout its operator is
looking at. ``build_version()`` is what the MCP server reports in
``serverInfo.version`` and in ``/healthz``: the package version, plus the git
commit when it is known - ``1.0.1+ece2807d`` - so a stale install is visible to
whoever connects.

The commit is looked for, in order:

1. ``MNEMOSYNE_BUILD_COMMIT`` in the environment (a build or deploy pipeline).
2. ``_build_commit.txt`` beside this module (a copy made without git, stamped
   by whoever copied it).
3. The git checkout this module is the source of. Only a checkout that holds
   this package as ``<root>/src/mnemosyne`` counts: an installed copy that
   merely sits inside some other project's repository must not report that
   project's commit as its own.

Nothing here runs a subprocess or imports anything heavy; the git metadata is
read as files.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

_FALLBACK_VERSION = "1.1.0"
_COMMIT_ENV = "MNEMOSYNE_BUILD_COMMIT"
_COMMIT_FILE = "_build_commit.txt"
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_SHORT = 8


def _clean_commit(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not _COMMIT_RE.match(value):
        return None
    return value.lower()[:_SHORT]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _git_dir_for(package_dir: Path) -> Path | None:
    """The git directory of the checkout whose ``src/mnemosyne`` is this package."""

    if package_dir.name != "mnemosyne" or package_dir.parent.name != "src":
        return None
    root = package_dir.parent.parent
    marker = root / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():
        # A linked worktree or a submodule: the file names the real directory.
        text = (_read_text(marker) or "").strip()
        if text.startswith("gitdir:"):
            target = Path(text[len("gitdir:"):].strip())
            if not target.is_absolute():
                target = root / target
            if target.is_dir():
                return target
    return None


def _git_commit(package_dir: Path) -> str | None:
    git_dir = _git_dir_for(package_dir)
    if git_dir is None:
        return None
    head = (_read_text(git_dir / "HEAD") or "").strip()
    if not head:
        return None
    if not head.startswith("ref:"):
        return _clean_commit(head)
    ref = head[len("ref:"):].strip()
    if not ref or ".." in ref:
        return None
    # A linked worktree keeps its refs in the main checkout's git directory.
    common = git_dir
    pointer = (_read_text(git_dir / "commondir") or "").strip()
    if pointer:
        candidate = Path(pointer)
        common = candidate if candidate.is_absolute() else git_dir / candidate
    for base in (git_dir, common):
        commit = _clean_commit(_read_text(base / ref) or "")
        if commit:
            return commit
    for line in (_read_text(common / "packed-refs") or "").splitlines():
        if line.endswith(" " + ref):
            return _clean_commit(line.split(" ", 1)[0])
    return None


def package_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("mnemosyne-memory")
        except PackageNotFoundError:
            return _FALLBACK_VERSION
    except Exception:  # noqa: BLE001 - the version must never stop a server starting
        return _FALLBACK_VERSION


@lru_cache(maxsize=1)
def build_commit() -> str | None:
    """The short commit this build was made from, or ``None`` when unknown."""

    commit = _clean_commit(os.environ.get(_COMMIT_ENV))
    if commit:
        return commit
    package_dir = Path(__file__).resolve().parent
    commit = _clean_commit(_read_text(package_dir / _COMMIT_FILE) or "")
    if commit:
        return commit
    return _git_commit(package_dir)


def build_version() -> str:
    """``<package version>+<commit>`` when the commit is known, else the version."""

    commit = build_commit()
    version = package_version()
    return f"{version}+{commit}" if commit else version

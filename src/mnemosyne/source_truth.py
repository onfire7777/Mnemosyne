"""Markdown/git source-of-truth compiler for human-authored memory."""

from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mnemosyne.models import Assertion, Evidence, parse_dt
from mnemosyne.security import TrustTier

SOURCE_TRUTH_FENCE = "mnemosyne-assertion"
SOURCE_TRUTH_SOURCE_TYPE = "markdown_git"
SOURCE_TRUTH_CAPABILITY_TAG = "human-source-truth"


@dataclass(slots=True)
class SourceTruthBlock:
    """One assertion block parsed from a committed Markdown source file."""

    block_id: str
    path: Path
    relative_path: str
    start_line: int
    end_line: int
    body: str
    subject: str
    predicate: str
    object_value: str
    confidence: float = 0.95
    scope: dict[str, Any] = field(default_factory=dict)
    valid_from: datetime | None = None
    sensitivity: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def source_identity(self, git_sha: str) -> str:
        return f"git:{self.relative_path}@{git_sha}#{self.block_id}"


@dataclass(slots=True)
class SourceSyncResult:
    """Structured source-sync result for CLI and MCP surfaces."""

    root: str
    git_sha: str
    git_branch: str
    branch: str
    apply: bool
    discovered: int
    applied: int
    evidence_cids: list[str] = field(default_factory=list)
    assertion_ids: list[str] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "git_sha": self.git_sha,
            "git_branch": self.git_branch,
            "branch": self.branch,
            "apply": self.apply,
            "discovered": self.discovered,
            "applied": self.applied,
            "evidence_cids": self.evidence_cids,
            "assertion_ids": self.assertion_ids,
            "blocks": self.blocks,
        }


def parse_markdown_git_blocks(root: str | Path) -> list[SourceTruthBlock]:
    source_root = _resolved_root(root)
    blocks: list[SourceTruthBlock] = []
    for path in sorted(source_root.rglob("*.md")):
        if ".git" in path.parts:
            continue
        blocks.extend(_parse_file(source_root, path))
    return blocks


def apply_markdown_git_source(
    engine: Any,
    *,
    tenant_id: str,
    user_id: str,
    root: str | Path,
    branch: str = "main",
    apply: bool = False,
    source_trust_tier: int = int(TrustTier.USER_AUTHORED),
    require_clean_git: bool = True,
) -> SourceSyncResult:
    source_root = _resolved_root(root)
    git_root = _git_output(source_root, "rev-parse", "--show-toplevel")
    git_root_path = Path(git_root).resolve()
    git_sha = _git_output(git_root_path, "rev-parse", "HEAD")
    git_branch = _git_output(git_root_path, "rev-parse", "--abbrev-ref", "HEAD")
    if require_clean_git:
        dirty = _git_output(git_root_path, "status", "--porcelain", "--", _git_pathspec(git_root_path, source_root))
        if dirty:
            raise ValueError("markdown/git source root must be clean; commit source changes or pass allow_dirty")

    blocks = parse_markdown_git_blocks(source_root)
    result = SourceSyncResult(
        root=str(source_root),
        git_sha=git_sha,
        git_branch=git_branch,
        branch=branch,
        apply=apply,
        discovered=len(blocks),
        applied=0,
    )
    for block in blocks:
        source_identity = block.source_identity(git_sha)
        row = {
            "id": block.block_id,
            "path": block.relative_path,
            "start_line": block.start_line,
            "end_line": block.end_line,
            "source_identity": source_identity,
            "subject": block.subject,
            "predicate": block.predicate,
            "object": block.object_value,
        }
        if not apply:
            result.blocks.append(row)
            continue
        content = _evidence_content(source_identity, block)
        cid = engine.append_evidence(
            Evidence(
                tenant_id=tenant_id,
                user_id=user_id,
                actor="user",
                source_type=SOURCE_TRUTH_SOURCE_TYPE,
                source_identity=source_identity,
                content=content,
                metadata={
                    **block.metadata,
                    "source_truth": {
                        "block_id": block.block_id,
                        "path": block.relative_path,
                        "start_line": block.start_line,
                        "end_line": block.end_line,
                        "git_sha": git_sha,
                        "git_branch": git_branch,
                    },
                },
                trust_tier=source_trust_tier,
                capability_tags=[SOURCE_TRUTH_CAPABILITY_TAG],
                sensitivity=block.sensitivity,
                access_policy={"tenant": tenant_id},
            ),
            branch=branch,
        )
        assertion = Assertion(
            tenant_id=tenant_id,
            user_id=user_id,
            subject=block.subject,
            predicate=block.predicate,
            object=block.object_value,
            confidence=block.confidence,
            scope=block.scope,
            source_evidence_cids=[cid],
            status="active",
            trust_tier=source_trust_tier,
            sensitivity=block.sensitivity,
            access_policy={"tenant": tenant_id},
        )
        if block.valid_from is not None:
            assertion.valid_from = block.valid_from
        assertion_id = engine.upsert_assertion(assertion, branch=branch)
        result.applied += 1
        result.evidence_cids.append(cid)
        result.assertion_ids.append(assertion_id)
        result.blocks.append({**row, "cid": cid, "assertion_id": assertion_id})
    return result


def _parse_file(root: Path, path: Path) -> list[SourceTruthBlock]:
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks: list[SourceTruthBlock] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("```") or SOURCE_TRUTH_FENCE not in line:
            index += 1
            continue
        start = index + 1
        body_lines: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != "```":
            body_lines.append(lines[index])
            index += 1
        if index >= len(lines):
            raise ValueError(f"unclosed {SOURCE_TRUTH_FENCE} block in {path}:{start}")
        end = index + 1
        blocks.append(_parse_block(root, path, start, end, "\n".join(body_lines).strip()))
        index += 1
    return blocks


def _parse_block(root: Path, path: Path, start_line: int, end_line: int, body: str) -> SourceTruthBlock:
    data = tomllib.loads(body)
    block_id = _string_field(data, "id", default=f"{path.stem}-{start_line}")
    subject = _string_field(data, "subject")
    predicate = _string_field(data, "predicate")
    object_value = _string_field(data, "object", aliases=("object_value", "value"))
    confidence = float(data.get("confidence", 0.95))
    if not 0 <= confidence <= 1:
        raise ValueError(f"confidence must be between 0 and 1 in {path}:{start_line}")
    scope = data.get("scope", {})
    metadata = data.get("metadata", {})
    if not isinstance(scope, dict):
        raise ValueError(f"scope must be a TOML table in {path}:{start_line}")
    if not isinstance(metadata, dict):
        raise ValueError(f"metadata must be a TOML table in {path}:{start_line}")
    relative_path = path.relative_to(root).as_posix()
    return SourceTruthBlock(
        block_id=block_id,
        path=path,
        relative_path=relative_path,
        start_line=start_line,
        end_line=end_line,
        body=body,
        subject=subject,
        predicate=predicate,
        object_value=object_value,
        confidence=confidence,
        scope=dict(scope),
        valid_from=parse_dt(data.get("valid_from")),
        sensitivity=int(data.get("sensitivity", 0)),
        metadata=dict(metadata),
    )


def _string_field(data: dict[str, Any], key: str, *, aliases: tuple[str, ...] = (), default: str | None = None) -> str:
    for candidate in (key, *aliases):
        value = data.get(candidate)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if default is not None:
        return default
    raise ValueError(f"missing required string field {key!r}")


def _evidence_content(source_identity: str, block: SourceTruthBlock) -> str:
    return (
        f"source_identity = {source_identity!r}\n"
        f"path = {block.relative_path!r}\n"
        f"lines = {block.start_line}-{block.end_line}\n\n"
        f"```{SOURCE_TRUTH_FENCE}\n{block.body}\n```"
    )


def _resolved_root(root: str | Path) -> Path:
    path = Path(root).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError(f"source root does not exist or is not a directory: {path}")
    return path


def _git_output(cwd: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "").strip()
        raise ValueError(f"git {' '.join(args)} failed for {cwd}: {message}") from exc
    return completed.stdout.strip()


def _git_pathspec(git_root: Path, source_root: Path) -> str:
    try:
        relative = source_root.relative_to(git_root)
    except ValueError as exc:
        raise ValueError(f"source root {source_root} is outside git root {git_root}") from exc
    return "." if str(relative) == "." else relative.as_posix()

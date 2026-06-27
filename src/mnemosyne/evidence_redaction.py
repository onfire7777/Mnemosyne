from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Pattern


MAX_SCAN_BYTES = 5 * 1024 * 1024

SECRET_PATTERNS: tuple[tuple[str, Pattern[str]], ...] = (
    (
        "private_key_block",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "github_token",
        re.compile(r"\bgh[opsru]_[A-Za-z0-9_]{20,}\b"),
    ),
    (
        "aws_access_key",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    (
        "anthropic_api_key",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "openai_api_key",
        re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    ),
)


def redaction_findings(source: str, text: str) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(
                    {
                        "source": source,
                        "line": line_number,
                        "kind": kind,
                    }
                )
    return findings


def redaction_scan(
    *,
    scope: str,
    scanned_files: list[str],
    findings: list[dict[str, object]],
    skipped_files: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    skipped = skipped_files or []
    scan: dict[str, object] = {
        "ok": not findings and not skipped,
        "scope": scope,
        "patterns": [kind for kind, _ in SECRET_PATTERNS],
        "scanned_files": scanned_files,
        "findings": findings,
    }
    if skipped_files is not None:
        scan["skipped_files"] = skipped
    return scan


def write_redaction_scan(
    path: Path,
    *,
    scope: str,
    scanned_files: list[str],
    findings: list[dict[str, object]],
    skipped_files: list[dict[str, str]] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            redaction_scan(
                scope=scope,
                scanned_files=scanned_files,
                findings=findings,
                skipped_files=skipped_files,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )


def _scan_file(
    path: Path,
    *,
    findings: list[dict[str, object]],
    scanned_files: list[str],
    skipped_files: list[dict[str, str]],
    max_scan_bytes: int,
) -> None:
    try:
        stat = path.stat()
    except OSError as exc:
        skipped_files.append({"path": str(path), "reason": f"stat failed: {exc}"})
        return
    if stat.st_size > max_scan_bytes:
        skipped_files.append({"path": str(path), "reason": "larger than scan limit"})
        return
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        skipped_files.append({"path": str(path), "reason": "not utf-8 text"})
        return
    scanned_files.append(str(path))
    findings.extend(redaction_findings(str(path), text))


def scan_evidence_paths(
    paths: list[Path],
    *,
    scope: str,
    max_scan_bytes: int = MAX_SCAN_BYTES,
    forbidden_roots: list[Path] | None = None,
    reject_symlinks: bool = False,
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    scanned_files: list[str] = []
    skipped_files: list[dict[str, str]] = []
    seen: set[str] = set()
    resolved_forbidden_roots = [
        root.resolve(strict=False) for root in (forbidden_roots or [])
    ]

    def _is_forbidden(path: Path) -> bool:
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            skipped_files.append({"path": str(path), "reason": f"resolve failed: {exc}"})
            return True
        for forbidden_root in resolved_forbidden_roots:
            try:
                resolved.relative_to(forbidden_root)
            except ValueError:
                continue
            skipped_files.append(
                {
                    "path": str(path),
                    "reason": f"resolved inside forbidden root: {resolved}",
                }
            )
            return True
        return False

    def _append_candidate(path: Path) -> None:
        if reject_symlinks and path.is_symlink():
            skipped_files.append({"path": str(path), "reason": "symlink not allowed"})
            return
        if resolved_forbidden_roots and _is_forbidden(path):
            return
        try:
            key = str(path.resolve(strict=True))
        except OSError:
            key = str(path)
        if key in seen:
            return
        seen.add(key)
        if not path.exists():
            skipped_files.append({"path": str(path), "reason": "missing"})
            return
        if not path.is_file():
            skipped_files.append({"path": str(path), "reason": "not a file"})
            return
        _scan_file(
            Path(key),
            findings=findings,
            scanned_files=scanned_files,
            skipped_files=skipped_files,
            max_scan_bytes=max_scan_bytes,
        )

    for root in sorted(paths, key=lambda item: str(item)):
        if reject_symlinks and root.is_symlink():
            skipped_files.append({"path": str(root), "reason": "symlink not allowed"})
            continue
        if root.is_dir():
            children = sorted(root.rglob("*"))
            has_candidate = False
            for path in children:
                if path.is_dir() and not path.is_symlink():
                    continue
                has_candidate = True
                _append_candidate(path)
            if not has_candidate:
                skipped_files.append({"path": str(root), "reason": "empty directory"})
        else:
            _append_candidate(root)

    return redaction_scan(
        scope=scope,
        scanned_files=scanned_files,
        skipped_files=skipped_files,
        findings=findings,
    )


def scan_evidence_tree(
    out_root: Path,
    *,
    scope: str = "capture",
    max_scan_bytes: int = MAX_SCAN_BYTES,
    reject_symlinks: bool = True,
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    scanned_files: list[str] = []
    skipped_files: list[dict[str, str]] = []
    if reject_symlinks and out_root.is_symlink():
        skipped_files.append({"path": str(out_root), "reason": "symlink not allowed"})
        return redaction_scan(
            scope=scope,
            scanned_files=scanned_files,
            skipped_files=skipped_files,
            findings=findings,
        )
    root_scan_report = out_root / "redaction-scan.json"
    for path in sorted(out_root.rglob("*")):
        if reject_symlinks and path.is_symlink():
            skipped_files.append({"path": str(path), "reason": "symlink not allowed"})
            continue
        if not path.is_file() or path == root_scan_report:
            continue
        _scan_file(
            path,
            findings=findings,
            scanned_files=scanned_files,
            skipped_files=skipped_files,
            max_scan_bytes=max_scan_bytes,
        )
    return redaction_scan(
        scope=scope,
        scanned_files=scanned_files,
        skipped_files=skipped_files,
        findings=findings,
    )

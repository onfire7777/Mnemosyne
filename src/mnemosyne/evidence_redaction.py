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
    scan: dict[str, object] = {
        "ok": not findings,
        "scope": scope,
        "patterns": [kind for kind, _ in SECRET_PATTERNS],
        "scanned_files": scanned_files,
        "findings": findings,
    }
    if skipped_files is not None:
        scan["skipped_files"] = skipped_files
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


def scan_evidence_tree(
    out_root: Path,
    *,
    scope: str = "capture",
    max_scan_bytes: int = MAX_SCAN_BYTES,
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    scanned_files: list[str] = []
    skipped_files: list[dict[str, str]] = []
    for path in sorted(out_root.rglob("*")):
        if not path.is_file() or path.name == "redaction-scan.json":
            continue
        try:
            stat = path.stat()
        except OSError as exc:
            skipped_files.append({"path": str(path), "reason": f"stat failed: {exc}"})
            continue
        if stat.st_size > max_scan_bytes:
            skipped_files.append({"path": str(path), "reason": "larger than scan limit"})
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped_files.append({"path": str(path), "reason": "not utf-8 text"})
            continue
        scanned_files.append(str(path))
        findings.extend(redaction_findings(str(path), text))
    return redaction_scan(
        scope=scope,
        scanned_files=scanned_files,
        skipped_files=skipped_files,
        findings=findings,
    )

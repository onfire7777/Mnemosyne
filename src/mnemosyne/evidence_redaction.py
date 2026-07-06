from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Pattern
from urllib.parse import urlparse


MAX_SCAN_BYTES = 5 * 1024 * 1024
SECRET_ARGUMENT_OPTIONS = frozenset(
    {
        "--api-key",
        "--auth-header",
        "--auth-token",
        "--authorization",
        "--bearer-token",
        "--client-secret",
        "--connection-string",
        "--database-url",
        "--dsn",
        "--idp-token",
        "--key",
        "--mcp-session-token",
        "--password",
        "--postgres-dsn",
        "--private-key",
        "--secret",
        "--session-secret",
        "--session-token",
        "--token",
        "--vault-token",
    }
)
SECRET_ARGUMENT_MARKERS = (
    "api-key",
    "authorization",
    "bearer-token",
    "connection-string",
    "database-url",
    "password",
    "private-key",
    "secret",
    "session-token",
    "vault-token",
)

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
    (
        "vault_token",
        re.compile(r"\bhv[bs]\.[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "authorization_bearer",
        re.compile(r"(?i)\bauthorization\b\s*[:=]\s*[\"']?bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    ),
    (
        "url_userinfo",
        re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'/?#@]+:[^\s\"'/?#@]+@"),
    ),
)
SECRET_KEY_MARKERS = frozenset(
    {
        "access_token",
        "api_key",
        "auth_token",
        "bearer_token",
        "client_secret",
        "credential",
        "credentials",
        "idp_token",
        "mcp_session_token",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_secret",
        "session_token",
        "token",
        "vault_token",
    }
)
SECRET_KEY_ALLOWED_SUFFIXES = (
    "_command",
    "_env",
    "_fingerprint",
    "_hash",
    "_omitted",
    "_present",
    "_provider",
    "_redacted",
    "_sha256",
    "_source",
)
SECRET_VALUE_PLACEHOLDERS = frozenset(
    {
        "",
        "***",
        "<omitted>",
        "<redacted>",
        "omitted",
        "redacted",
        "redacted-placeholder",
    }
)


def is_secret_argument_option(option_name: str) -> bool:
    normalized = option_name.strip().lower().replace("_", "-")
    normalized_option = normalized.split("=", 1)[0]
    if normalized_option in SECRET_ARGUMENT_OPTIONS:
        return True
    if not normalized_option.startswith("--"):
        return False
    option_body = normalized_option[2:]
    if re.search(r"(?:^|-)token(?:$|-)", option_body):
        return True
    if option_body.endswith("-dsn"):
        return True
    return any(marker in normalized for marker in SECRET_ARGUMENT_MARKERS)


def url_contains_userinfo(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc and (parsed.username or parsed.password))


def _normalise_secret_key(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _is_secret_key(key: str) -> bool:
    normalized = _normalise_secret_key(key)
    if normalized.endswith(SECRET_KEY_ALLOWED_SUFFIXES):
        return False
    parts = set(normalized.split("_"))
    if normalized in SECRET_KEY_MARKERS:
        return True
    if {"api", "key"} <= parts:
        return True
    if {"client", "secret"} <= parts:
        return True
    if {"private", "key"} <= parts:
        return True
    return bool(SECRET_KEY_MARKERS & parts)


def _is_raw_secret_scalar(value: Any) -> bool:
    if isinstance(value, (Mapping, list)):
        return False
    if value is None or isinstance(value, bool | int | float):
        return False
    text = str(value).strip()
    return text.lower() not in SECRET_VALUE_PLACEHOLDERS


def _line_for_json_key(text: str, key: str) -> int:
    pattern = re.compile(rf'"{re.escape(key)}"\s*:')
    match = pattern.search(text)
    if match is None:
        return 1
    return text.count("\n", 0, match.start()) + 1


def _structured_secret_findings(source: str, text: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    findings: list[dict[str, object]] = []

    def visit(value: Any, path: str = "$") -> None:
        if isinstance(value, Mapping):
            for raw_key, raw_child in value.items():
                key = str(raw_key)
                child_path = f"{path}.{key}"
                if _is_secret_key(key) and _is_raw_secret_scalar(raw_child):
                    findings.append(
                        {
                            "source": source,
                            "line": _line_for_json_key(text, key),
                            "kind": "structured_secret_key",
                            "path": child_path,
                        }
                    )
                visit(raw_child, child_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(payload)
    return findings


def manifest_argument_secret_errors(manifest: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    checks = manifest.get("checks")
    if not isinstance(checks, list):
        return errors
    for check_index, check in enumerate(checks, start=1):
        if not isinstance(check, Mapping):
            continue
        for field in ("args", "global_args"):
            values = check.get(field, [])
            if not isinstance(values, list):
                continue
            for value_index, value in enumerate(values):
                if not isinstance(value, str):
                    continue
                option_name, separator, option_value = value.partition("=")
                label = f"checks[{check_index}].{field}[{value_index}]"
                if option_name.startswith("--") and is_secret_argument_option(option_name):
                    errors.append(
                        f"{label} contains secret-bearing option {option_name}; "
                        "use environment, files, or command providers instead"
                    )
                if separator and url_contains_userinfo(option_value):
                    errors.append(
                        f"{label} contains URL userinfo in option value; "
                        "move credentials to environment, files, or command providers"
                    )
                elif not separator and url_contains_userinfo(value):
                    errors.append(
                        f"{label} contains URL userinfo; move credentials to "
                        "environment, files, or command providers"
                    )
    return errors


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
    findings.extend(_structured_secret_findings(source, text))
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
        "patterns": [kind for kind, _ in SECRET_PATTERNS] + ["structured_secret_key"],
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
    binary_custody_roots: list[Path] | None = None,
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    scanned_files: list[str] = []
    skipped_files: list[dict[str, str]] = []
    binary_custody_files: list[str] = []
    seen: set[str] = set()
    resolved_forbidden_roots = [
        root.resolve(strict=False) for root in (forbidden_roots or [])
    ]
    # Binary custody roots (e.g. C2PA provenance PNG assets) cannot be UTF-8
    # text and must stay binary for downstream verification, so they are exempt
    # from the text secret-scan and recorded as retained binary custody instead
    # of failing as "not utf-8 text". Mirrors scan_evidence_tree exactly so the
    # preflight input scan and the final capture scan agree.
    resolved_binary_custody_roots = [
        root.resolve(strict=False) for root in (binary_custody_roots or [])
    ]

    def _is_binary_custody_path(path: Path) -> bool:
        if not resolved_binary_custody_roots:
            return False
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return False
        return any(
            _path_is_relative_to(resolved, custody_root)
            for custody_root in resolved_binary_custody_roots
        )

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
        if _is_binary_custody_path(Path(key)):
            binary_custody_files.append(key)
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

    scan = redaction_scan(
        scope=scope,
        scanned_files=scanned_files,
        skipped_files=skipped_files,
        findings=findings,
    )
    if binary_custody_files:
        scan["binary_custody_files"] = sorted(binary_custody_files)
    return scan


def scan_evidence_tree(
    out_root: Path,
    *,
    scope: str = "capture",
    max_scan_bytes: int = MAX_SCAN_BYTES,
    reject_symlinks: bool = True,
    binary_custody_roots: list[Path] | None = None,
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    scanned_files: list[str] = []
    skipped_files: list[dict[str, str]] = []
    binary_custody_files: list[str] = []
    resolved_binary_custody_roots = [
        root.resolve(strict=False) for root in (binary_custody_roots or [])
    ]

    def _is_binary_custody_path(path: Path) -> bool:
        if not resolved_binary_custody_roots:
            return False
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return False
        return any(
            _path_is_relative_to(resolved, custody_root)
            for custody_root in resolved_binary_custody_roots
        )

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
        if _is_binary_custody_path(path):
            binary_custody_files.append(str(path))
            continue
        _scan_file(
            path,
            findings=findings,
            scanned_files=scanned_files,
            skipped_files=skipped_files,
            max_scan_bytes=max_scan_bytes,
        )
    scan = redaction_scan(
        scope=scope,
        scanned_files=scanned_files,
        skipped_files=skipped_files,
        findings=findings,
    )
    if binary_custody_files:
        scan["binary_custody_files"] = sorted(binary_custody_files)
    return scan


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True

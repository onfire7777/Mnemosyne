from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANNING = ROOT / ".planning"
REQUIREMENTS = PLANNING / "milestones" / "v1.0-REQUIREMENTS.md"
ID_PATTERN = re.compile(r"(?:REQ|NFR)-\d{3}")
TRACE_ROW = re.compile(
    r"^\| ((?:REQ|NFR)-\d{3}) \| ([^|]+) \| `([^`]+)` \| `([^`]+)` "
    r"\| ([^|]+) \| \[x\] Verified \|$"
)


def _frontmatter_list(text: str, key: str) -> set[str]:
    lines = text.splitlines()
    marker = f"{key}:"
    inline_prefix = f"{key}: ["
    for line in lines:
        if line.startswith(inline_prefix) and line.endswith("]"):
            return {
                value.strip()
                for value in line[len(inline_prefix) : -1].split(",")
                if value.strip()
            }
    try:
        start = lines.index(marker) + 1
    except ValueError:
        return set()
    values: set[str] = set()
    for line in lines[start:]:
        if not line.startswith("  - "):
            break
        values.add(line.removeprefix("  - ").strip())
    return values


def _resolve_planning_path(value: str) -> Path:
    path = PLANNING / value
    assert path.is_file(), f"traceability source does not exist: {path}"
    return path


def test_all_canonical_requirements_have_one_truthful_three_source_join() -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    expected = {f"REQ-{index:03d}" for index in range(1, 19)} | {
        f"NFR-{index:03d}" for index in range(1, 6)
    }
    checked = set(re.findall(r"\[x\] ((?:REQ|NFR)-\d{3})", text))
    assert checked == expected

    rows: dict[str, tuple[str, str, str, str]] = {}
    for line in text.splitlines():
        match = TRACE_ROW.match(line)
        if not match:
            continue
        requirement, phase, verification, summary, closure = match.groups()
        assert requirement not in rows, f"duplicate primary owner: {requirement}"
        rows[requirement] = (phase.strip(), verification, summary, closure.strip())
    assert set(rows) == expected

    for requirement, (phase, verification_name, summary_name, closure) in rows.items():
        assert phase, f"missing primary phase for {requirement}"
        verification = _resolve_planning_path(verification_name)
        summary = _resolve_planning_path(summary_name)
        verification_text = verification.read_text(encoding="utf-8")
        summary_text = summary.read_text(encoding="utf-8")
        assert "status: passed" in verification_text
        assert requirement in verification_text
        assert requirement in _frontmatter_list(summary_text, "requirements-completed")
        assert closure


def test_traceability_uses_only_canonical_requirement_ids() -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    ids = set(ID_PATTERN.findall(text))
    assert {f"REQ-{index:03d}" for index in range(1, 19)} <= ids
    assert {f"NFR-{index:03d}" for index in range(1, 6)} <= ids

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLANNING = ROOT / ".planning"
REQUIREMENTS = PLANNING / "milestones" / "v1.0-REQUIREMENTS.md"
V2_REQUIREMENTS = PLANNING / "REQUIREMENTS.md"
V2_ROADMAP = PLANNING / "ROADMAP.md"
PHASE_15_S4_PLAN = (
    PLANNING
    / "phases"
    / "15-security-calibration-performance-and-scale-columns"
    / "15-03-PLAN.md"
)
ARCHITECTURE_OVERVIEW = ROOT / "docs" / "ARCHITECTURE-OVERVIEW.md"
ENGINE_CONTRACT = ROOT / "docs" / "ENGINE-CONTRACT.md"
DEPENDENCY_LEASE_MAP = (
    ROOT
    / "docs"
    / "coordination"
    / "2026-07-28-remaining-dependency-write-lease-map.md"
)
ID_PATTERN = re.compile(r"(?:REQ|NFR)-\d{3}")
TRACE_ROW = re.compile(
    r"^\| ((?:REQ|NFR)-\d{3}) \| ([^|]+) \| `([^`]+)` \| `([^`]+)` "
    r"\| ([^|]+) \| \[x\] Verified \|$"
)
V2_CAP_ROW = re.compile(r"^\| \[[ x]\] (CAP-\d{3}) \|")


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


def test_phase_13_truth_lease_names_existing_authoritative_files() -> None:
    text = DEPENDENCY_LEASE_MAP.read_text(encoding="utf-8")
    for relative_path in (
        ".planning/phases/13-external-benchmark-adapters-and-scheduled-ci/"
        "13-01-PLAN.md",
        ".planning/phases/13-external-benchmark-adapters-and-scheduled-ci/"
        "13-01-SUMMARY.md",
    ):
        assert f"`{relative_path}`" in text
        assert (ROOT / relative_path).is_file()


def test_v2_memory_plane_requirements_are_complete_and_traceable() -> None:
    text = V2_REQUIREMENTS.read_text(encoding="utf-8")
    expected_rows = {
        "CAP-012": (
            "Prospective memory persists subject-scoped intentions and evaluates "
            "supported triggers deterministically and idempotently with provenance "
            "and audit records across Local, Postgres, and Sqlite engines.",
            "W3 P1/P4",
        ),
        "CAP-013": (
            "Working memory provides tenant/session-scoped short-TTL storage, "
            "explicit promotion, deterministic expiry, and a distinct retrieval "
            "route across Local, Postgres, and Sqlite engines.",
            "W3 P3/P4",
        ),
    }

    rows_by_requirement: dict[str, list[str]] = {}
    for line in text.splitlines():
        match = V2_CAP_ROW.match(line)
        if match:
            rows_by_requirement.setdefault(match.group(1), []).append(line)

    for requirement, (description, authority) in expected_rows.items():
        assert rows_by_requirement.get(requirement) == [
            f"| [x] {requirement} | {description} | {authority} | Complete |"
        ]

    phase_15 = next(line for line in text.splitlines() if line.startswith("| 15 |"))
    assert phase_15 == "| 15 | CAP-004..011, CAP-012, CAP-013, RAIL-001..004 |"
    assert _frontmatter_list(
        PHASE_15_S4_PLAN.read_text(encoding="utf-8"), "requirements"
    ) == {"CAP-006", "CAP-011", "RAIL-001", "RAIL-002", "RAIL-003", "RAIL-004"}
    roadmap = V2_ROADMAP.read_text(encoding="utf-8")
    phase_15_roadmap = roadmap.split("### Phase 15:", 1)[1].split(
        "\n### Phase 16:", 1
    )[0]
    assert (
        "**Requirements:** CAP-004..011, CAP-012, CAP-013, RAIL-001..004"
        in phase_15_roadmap
    )
    assert (
        "remaining Phase 15 items (CAP-004..011) stay planned" in phase_15_roadmap
    )


def test_memory_plane_architecture_documents_routes_and_ownership() -> None:
    text = ARCHITECTURE_OVERVIEW.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for expected in (
        "prospective_memory",
        "working_memory",
        "without firing or mutating them",
        "never promotes them implicitly",
        "Local, Postgres, and Sqlite engines",
        "kind ∈ {evidence, assertion, relation, preference, intention, working}",
        "remain data-only",
        "docs/ENGINE-CONTRACT.md",
    ):
        assert expected in normalized

    for engine_contract_detail in (
        "schedule_intention",
        "evaluate_due_intentions",
        "put_working",
        "expire_working",
    ):
        assert engine_contract_detail not in normalized


def test_engine_contract_documents_three_engine_memory_plane_parity() -> None:
    text = ENGINE_CONTRACT.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for expected in (
        '@pytest.fixture(params=["local", "postgres", "sqlite"])',
        "schedule_intention",
        "cancel_intention",
        "list_intentions",
        "evaluate_due_intentions",
        "put_working",
        "get_working",
        "list_working",
        "expire_working",
        "created_at <= as_of < expires_at",
        "session_id`, `user_id`, `agent_id`, `task_id`, and `branch",
        "legacy tombstone",
        "limited to erased-replay detection",
        "restricted to the owning user or agent",
        "working_promote",
        "working-promote",
        "PromotionGate",
        "Memory-plane implementation mapping",
        "SqliteEngine (`src/mnemosyne/sqlite_engine.py`)",
    ):
        assert expected in normalized

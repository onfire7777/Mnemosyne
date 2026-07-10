from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE = ROOT / "docs" / "governance"

REQUIRED_DOCUMENTS = {
    "README.md",
    "CHARTER.md",
    "CONFLICT-OF-INTEREST.md",
    "OPERATOR-FIREWALL.md",
    "APPEALS-AND-DISPUTES.md",
    "CHANGE-CONTROL.md",
    "METHODOLOGY.md",
    "METHODS-PAPER-OUTLINE.md",
    "BOARD-STATUS.md",
    "COI-REGISTER.md",
}


def _read(name: str) -> str:
    return (GOVERNANCE / name).read_text(encoding="utf-8")


def test_governance_document_set_is_complete_and_versioned() -> None:
    assert {path.name for path in GOVERNANCE.glob("*.md")} == REQUIRED_DOCUMENTS
    for name in REQUIRED_DOCUMENTS:
        text = _read(name)
        assert "Version:" in text, name
        assert "Status:" in text, name


def test_governance_is_explicitly_inactive_and_fail_closed() -> None:
    charter = _read("CHARTER.md")
    status = _read("BOARD-STATUS.md")
    readiness = (ROOT / "leaderboard/reports/l0-governance-readiness.md").read_text(
        encoding="utf-8"
    )
    for text in (charter, status, readiness):
        assert "External activation required" in text
    assert "Status: inactive" in status
    assert "board is not yet seated" in status
    assert "governance is not yet active" in status
    assert "methods paper is not yet published" in readiness
    assert "GOV-001: partial" in readiness
    assert "Phase 16" in readiness


def test_permanent_conflict_and_equal_treatment_are_non_waivable() -> None:
    coi = _read("CONFLICT-OF-INTEREST.md")
    firewall = _read("OPERATOR-FIREWALL.md")
    register = _read("COI-REGISTER.md")
    assert "permanent conflict" in coi.lower()
    assert "non-waivable" in coi.lower()
    assert "Mnemosyne" in register and "permanent" in register.lower()
    for phrase in (
        "one harness",
        "same configuration",
        "same budget",
        "same access",
        "no special runs",
        "no vendor-authored scores",
        "non-waivable",
    ):
        assert phrase in firewall.lower(), phrase


def test_results_appeals_and_changes_are_public_and_non_destructive() -> None:
    appeals = _read("APPEALS-AND-DISPUTES.md").lower()
    changes = _read("CHANGE-CONTROL.md").lower()
    assert "public appeal log" in appeals
    assert "recusal" in appeals
    assert "never silently retract" in changes
    assert "versioned correction" in changes
    assert "immutable" in changes
    assert "change log" in changes


def test_methodology_requires_reproducible_neutral_scoring() -> None:
    methodology = _read("METHODOLOGY.md").lower()
    for phrase in (
        "metric families",
        "contamination",
        "confidence interval",
        "ties",
        "judge disclosure",
        "reproduction bundle",
        "pbpp",
    ):
        assert phrase in methodology, phrase


def test_index_cross_links_every_canonical_policy() -> None:
    index = _read("README.md")
    for name in REQUIRED_DOCUMENTS - {"README.md"}:
        assert f"[{name.removesuffix('.md')}]({name})" in index, name

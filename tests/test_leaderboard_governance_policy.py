from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE = ROOT / "docs" / "governance"

REQUIRED_DOCUMENTS = {
    "README.md",
    "CREDIBILITY-MODEL.md",
    "CHARTER.md",
    "CONFLICT-OF-INTEREST.md",
    "OPERATOR-FIREWALL.md",
    "APPEALS-AND-DISPUTES.md",
    "CHANGE-CONTROL.md",
    "METHODOLOGY.md",
    "METHODS-PAPER-OUTLINE.md",
    "BOARD-STATUS.md",
    "COI-REGISTER.md",
    "RECRUITMENT-PACKET.md",
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
    # The board stays unseated and must never be described otherwise.
    assert "board is not yet seated" in status
    assert "governance is not yet active" in status
    assert "GOV-001: partial" in readiness
    assert "Phase 16" in readiness


def test_credibility_rests_on_verifiability_not_an_institution() -> None:
    """The publication path must not depend on external organisations.

    v0.1.0 gated Phase 16 on seating academics, retaining a legal steward, and
    securing funding. A solo maintainer cannot satisfy those by writing
    software, so the roadmap terminated in a permanent block. Credibility now
    comes from mechanisms the operator can build and a stranger can check.
    """
    model = _read("CREDIBILITY-MODEL.md").lower()
    charter = _read("CHARTER.md").lower()
    status = _read("BOARD-STATUS.md").lower()

    # Every integrity mechanism the model claims must actually be described.
    for phrase in (
        "pre-registration",
        "append-only",
        "reproducible by construction",
        "operator-run, fully auditable",
        "expected entrant roster",
    ):
        assert phrase in model, phrase

    # A ledger alone cannot expose an omitted system; the roster closes that hole.
    assert "no_run" in model
    assert "expected entrant roster" in model

    # The honest label is claimed and the stronger one is explicitly withheld.
    assert "operator-run, fully auditable" in charter
    assert "they may not be" in charter, "charter must withhold the neutral label"
    assert "unless the optional board upgrade below" in charter

    # Register A is source-owned and blocking; Register B is optional and not.
    assert "register a — publication gates (source-owned, blocking)" in status
    assert "register b — optional independent-board upgrade (non-blocking)" in status
    assert "no gate above requires another organisation" in status
    for gate in (
        "pre-registration in force",
        "append-only signed run ledger",
        "reproducible by construction",
        "open stack published",
        "adversarial self-report populated",
        "public dispute channel",
        "public methods write-up",
    ):
        assert gate in status, gate

    # Publication classes must be distinguishable, or "publishable" is ambiguous.
    assert "track publication" in charter and "headline publication" in charter


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

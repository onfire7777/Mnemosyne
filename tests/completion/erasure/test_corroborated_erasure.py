"""Corroborated-erasure audit — adversarial round-trip through the public surface.

Blueprint: OQ6 / FR-8 (transitive forget + corroboration) and §31 RAIL 2
(``min_corroboration_for_delete``).

This is the pytest face of ``corroborated_erasure_verifier.py``. Each case drives
the REAL ``python -m mnemosyne.cli`` subprocess (plus the public ``MemoryTools``
facade for the single CLI-blocked assertion step — see
``CLI_OBJECT_FLAG_COLLISION``). No ``src/mnemosyne`` module is patched.

Four cases:
  (a) corroborated projection -> erase ONE source -> RETAINED + provenance trimmed.
  (b) sole-source projection  -> erase it        -> RETRACTED / tombstoned.
  (c) operator delete of a sole, uncorroborated source -> MUST be refused by a
      ``min_corroboration_for_delete`` gate. NOT enforced today => xfail(strict).
  (d) legal / right-to-be-forgotten erasure is corroboration-blind and shreds.

Like the sibling ``tests/completion/rails`` suite, the (c) breach is
``xfail(strict=True)``: it is a live TODO. When Codex wires the gate in
``src/mnemosyne`` the test flips to XPASS and the strict marker turns that into a
failure, forcing the xfail note to be removed.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from .corroborated_erasure_verifier import CorroboratedErasureVerifier


@pytest.fixture(scope="module")
def verifier() -> CorroboratedErasureVerifier:
    """One hermetic verifier (fresh store + object store) shared across cases.

    Each case seeds its own disjoint subject/predicate, so module scope is safe
    and keeps the (relatively expensive) subprocess count down.
    """
    tmp = tempfile.mkdtemp(prefix="corro-erasure-test-")
    store = os.path.join(tmp, "store.json")
    objstore = os.path.join(tmp, "objstore")
    return CorroboratedErasureVerifier(store=store, object_store=objstore)


def test_a_corroborated_projection_is_retained_with_trimmed_provenance(verifier):
    result = verifier.case_a_corroborated_retain_and_trim()
    assert result.status == "ok", result.observed
    # RETAINED (not retracted)…
    assert result.observed["after_status"] != "retracted", result.observed
    # …and provenance TRIMMED to the surviving CID only (erased CID gone,
    # NOT a blanket zeroing).
    assert result.observed["after_cids"] == [result.observed["surviving_cid"]], result.observed
    assert result.observed["erased_cid"] not in result.observed["after_cids"], result.observed
    assert result.passed, result.observed


def test_b_sole_source_projection_is_retracted(verifier):
    result = verifier.case_b_sole_source_retract()
    assert result.status == "ok", result.observed
    assert result.observed["after_status"] == "retracted", result.observed
    assert result.observed["after_cids"] == [], result.observed
    assert result.passed, result.observed


@pytest.mark.xfail(
    strict=True,
    reason=(
        "§31 RAIL 2 / min_corroboration_for_delete NOT ENFORCED. Operator deletion of a "
        "sole, uncorroborated source is permitted (forget returns erased=True). Missing "
        "enforcement: a corroboration count in the HARD_DELETE_LEGAL branch of "
        "LocalMemoryEngine.forget (src/mnemosyne/engine.py:903) + "
        "PostgresMemoryEngine.forget (postgres_engine.py:~1328). No "
        "`min_corroboration_for_delete` constant exists anywhere in src/mnemosyne. The "
        "engine must, before popping evidence, refuse when an active assertion would lose "
        "ALL support and is backed by < 2 distinct independent sources, and "
        "MemoryTools.forget (mcp_tools.py:711) must surface that refusal. "
        "Consistent with tests/completion/rails/test_min_corroboration_for_delete.py."
    ),
)
def test_c_operator_delete_of_sole_uncorroborated_source_is_blocked(verifier):
    result = verifier.case_c_operator_delete_sole_uncorroborated_gate()
    # The gate SHOULD refuse the delete. Today it does not => this assertion fails
    # => xfail. When the gate lands, refusal becomes True => XPASS => strict fail.
    assert result.observed["refused_by_corroboration_gate"] is True, result.observed
    assert result.passed, result.observed


def test_d_legal_erasure_is_corroboration_blind_and_shreds(verifier):
    result = verifier.case_d_legal_is_corroboration_blind_and_shreds()
    assert result.status == "ok", result.observed
    d1 = result.observed["d1_corroboration_blind"]
    d2 = result.observed["d2_shred"]
    # Corroboration-blind: legal erasure hard-deletes regardless of corroboration.
    assert d1["legal_erased"] is True, d1
    assert d1["erased_evidence_row_gone_from_export"] is True, d1
    # Shred path actually exercised on an externalized payload.
    assert d2["had_externalized_payload"] is True, d2
    assert d2["object_shred_report"] is not None, d2
    assert d2["evidence_row_gone_from_export"] is True, d2
    assert result.passed, result.observed


def test_full_audit_report_is_emitted_and_self_consistent(verifier):
    """The whole audit runs, emits a machine-readable report, and the only
    non-passing case is the known (c) breach (status=breach_unenforced)."""
    report = verifier.run().to_dict()
    summary = report["summary"]
    assert summary["total"] == 4, report
    assert summary["errors"] == 0, report
    # Exactly one known unenforced breach: case (c).
    assert summary["breach_unenforced"] == 1, report
    assert summary["all_enforced_invariants_hold"] is True, report
    names = {c["name"]: c for c in report["cases"]}
    assert names["c_operator_delete_sole_uncorroborated_blocked"]["status"] == "breach_unenforced"
    assert names["c_operator_delete_sole_uncorroborated_blocked"]["missing_enforcement"]

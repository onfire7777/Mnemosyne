"""Corroborated-erasure audit — adversarial round-trip through the public surface.

Blueprint: OQ6 / FR-8 (transitive forget + corroboration) and §31 RAIL 2
(``min_corroboration_for_delete``).

This is the pytest face of ``corroborated_erasure_verifier.py``. Each case drives
the REAL ``python -m mnemosyne.cli`` subprocess, including assertion creation via
``assert --object``. No ``src/mnemosyne`` module is patched.

Four cases:
  (a) corroborated projection -> erase ONE source -> RETAINED + provenance trimmed.
  (b) sole-source projection  -> erase it        -> RETRACTED / tombstoned.
  (c) operator delete of a sole, uncorroborated source -> MUST be refused by a
      ``min_corroboration_for_delete`` gate.
  (d) legal / right-to-be-forgotten erasure is corroboration-blind and shreds.
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


def test_c_operator_delete_of_sole_uncorroborated_source_is_blocked(verifier):
    result = verifier.case_c_operator_delete_sole_uncorroborated_gate()
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
    """The whole audit runs, emits a machine-readable report, and every
    corroborated-erasure invariant is enforced."""
    report = verifier.run().to_dict()
    summary = report["summary"]
    assert summary["total"] == 4, report
    assert summary["errors"] == 0, report
    assert summary["breach_unenforced"] == 0, report
    assert summary["all_enforced_invariants_hold"] is True, report
    names = {c["name"]: c for c in report["cases"]}
    assert names["c_operator_delete_sole_uncorroborated_blocked"]["status"] == "ok"
    assert names["c_operator_delete_sole_uncorroborated_blocked"]["missing_enforcement"] is None

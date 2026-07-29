"""Contract tests for the M01 pure development fixture and scorer.

This exercises only the exclusive-lease module `eval.public.wmbs_m01` and its
committed fixture at `eval/public/fixtures/wmbs-m01-development.json`. These
are unscored contract tests against synthetic golden payloads, not a measured
benchmark run: no CLI, adapter, or shared scoring wiring is exercised here.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import eval.public.wmbs_m01 as wmbs_m01

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "eval/public/fixtures/wmbs-m01-development.json"


def _load_committed_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _row(fixture: dict[str, Any], kind: str, *, index: int = 0) -> dict[str, Any]:
    matches = [row for row in fixture["rows"] if row["row_kind"] == kind]
    return matches[index]


# ---------------------------------------------------------------------------
# Frozen fixture / generator determinism
# ---------------------------------------------------------------------------


def test_fixture_file_exists_and_is_self_describing() -> None:
    assert FIXTURE_PATH.is_file()
    fixture = _load_committed_fixture()
    assert fixture["fixture_id"] == wmbs_m01.FIXTURE_ID
    assert fixture["schema_id"] == wmbs_m01.FIXTURE_SCHEMA_ID
    assert fixture["module_id"] == "M01"
    assert fixture["generator_id"] == wmbs_m01.GENERATOR_ID
    assert fixture["generator_version"] == wmbs_m01.GENERATOR_VERSION
    assert fixture["seed"] == wmbs_m01.DEFAULT_SEED


def test_generate_fixture_reproduces_committed_bytes_from_pinned_seed() -> None:
    """The frozen fixture file is committed as canonical JSON bytes.

    This compares the generator's canonical serialization against the raw
    bytes actually on disk, not against a re-serialization of parsed JSON:
    a byte-reproduction claim that only compares two independently
    re-encoded values does not prove the committed file matches the
    generator.
    """
    regenerated = wmbs_m01.generate_fixture(wmbs_m01.DEFAULT_SEED)
    committed_bytes = FIXTURE_PATH.read_bytes()
    assert wmbs_m01.canonical_json(regenerated) == committed_bytes


def test_generate_fixture_is_seed_sensitive() -> None:
    default = wmbs_m01.generate_fixture(wmbs_m01.DEFAULT_SEED)
    alternate = wmbs_m01.generate_fixture(wmbs_m01.DEFAULT_SEED + 1)
    assert default["seed"] != alternate["seed"]
    assert default["fixture_sha256"] != alternate["fixture_sha256"]
    assert default["rows"] != alternate["rows"]


def test_load_fixture_verifies_recorded_digest() -> None:
    loaded = wmbs_m01.load_fixture()
    assert loaded == _load_committed_fixture()


def test_load_fixture_rejects_a_tampered_fixture(tmp_path: Path) -> None:
    tampered = _load_committed_fixture()
    tampered["rows"][0]["raw_event"]["content"] = "tampered content"
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.load_fixture(tampered_path)


# ---------------------------------------------------------------------------
# Fixture composition: mixed events, duplicates, malformed rows, boundaries
# ---------------------------------------------------------------------------


def test_fixture_composition_matches_bounded_development_ratios() -> None:
    fixture = wmbs_m01.load_fixture()
    assert fixture["base_event_count"] == wmbs_m01.BASE_EVENT_COUNT
    assert fixture["exact_duplicate_count"] == wmbs_m01.EXACT_DUPLICATE_COUNT
    assert fixture["near_duplicate_count"] == wmbs_m01.NEAR_DUPLICATE_COUNT
    assert fixture["malformed_count"] == wmbs_m01.MALFORMED_COUNT
    assert fixture["total_row_count"] == wmbs_m01.TOTAL_ROW_COUNT
    assert len(fixture["rows"]) == wmbs_m01.TOTAL_ROW_COUNT
    assert fixture["exact_duplicate_ratio"] == pytest.approx(0.05)
    assert fixture["near_duplicate_ratio"] == pytest.approx(0.05)

    kinds = [row["row_kind"] for row in fixture["rows"]]
    assert kinds.count("primary") == wmbs_m01.BASE_EVENT_COUNT
    assert kinds.count("exact_duplicate") == wmbs_m01.EXACT_DUPLICATE_COUNT
    assert kinds.count("near_duplicate") == wmbs_m01.NEAR_DUPLICATE_COUNT
    assert kinds.count("malformed") == wmbs_m01.MALFORMED_COUNT


def test_fixture_row_ids_are_stable_and_unique() -> None:
    fixture = wmbs_m01.load_fixture()
    row_ids = [row["fixture_row_id"] for row in fixture["rows"]]
    assert len(row_ids) == len(set(row_ids))
    assert row_ids == sorted(row_ids)


def test_primary_events_have_stable_unique_event_ids_and_monotonic_times() -> None:
    fixture = wmbs_m01.load_fixture()
    primaries = [row for row in fixture["rows"] if row["row_kind"] == "primary"]
    event_ids = [row["event_id"] for row in primaries]
    assert len(event_ids) == len(set(event_ids))
    event_times = [row["raw_event"]["event_time"] for row in primaries]
    assert event_times == sorted(event_times)
    assert len(set(event_times)) == len(event_times)
    for row in primaries:
        raw = row["raw_event"]
        assert raw["event_time"] < raw["ingestion_time"]
        assert row["expected_outcome"] == "accepted"


def test_exact_duplicate_rows_replay_the_source_event_verbatim() -> None:
    """The replayed `raw_event` is byte-identical to the source event.

    Retry timing is not part of the replayed event: mutating
    `ingestion_time` inside `raw_event` would mean the "exact duplicate"
    replay is not actually exact. Retry timing is recorded separately on
    the row, outside `raw_event`.
    """
    fixture = wmbs_m01.load_fixture()
    primaries_by_id = {
        row["event_id"]: row for row in fixture["rows"] if row["row_kind"] == "primary"
    }
    exact_duplicates = [
        row for row in fixture["rows"] if row["row_kind"] == "exact_duplicate"
    ]
    assert exact_duplicates
    for dup in exact_duplicates:
        assert dup["expected_outcome"] == "deduplicated"
        source_id = dup["relation"]["source_event_id"]
        assert dup["relation"]["kind"] == "exact_duplicate_of"
        assert dup["event_id"] == source_id
        source = primaries_by_id[source_id]
        assert dup["raw_event"] == source["raw_event"]
        assert "retry_received_at" not in dup["raw_event"]
        assert isinstance(dup["retry_received_at"], str)
        assert dup["retry_received_at"] != source["raw_event"]["ingestion_time"]


def test_exact_duplicate_retry_timing_is_distinct_per_replay() -> None:
    fixture = wmbs_m01.load_fixture()
    exact_duplicates = [
        row for row in fixture["rows"] if row["row_kind"] == "exact_duplicate"
    ]
    retry_times = [row["retry_received_at"] for row in exact_duplicates]
    assert len(retry_times) == len(exact_duplicates)
    assert len(retry_times) == len(set(retry_times))


def test_near_duplicate_rows_are_distinct_accepted_events() -> None:
    fixture = wmbs_m01.load_fixture()
    primaries_by_id = {
        row["event_id"]: row for row in fixture["rows"] if row["row_kind"] == "primary"
    }
    near_duplicates = [
        row for row in fixture["rows"] if row["row_kind"] == "near_duplicate"
    ]
    assert near_duplicates
    for near in near_duplicates:
        assert near["expected_outcome"] == "accepted"
        assert near["relation"]["kind"] == "near_duplicate_of"
        source = primaries_by_id[near["relation"]["source_event_id"]]
        assert near["event_id"] != source["event_id"]
        assert near["raw_event"]["content"] != source["raw_event"]["content"]
        assert (
            near["raw_event"]["content_sha256"] != source["raw_event"]["content_sha256"]
        )


def test_malformed_rows_are_rejected_with_a_disclosed_error_code() -> None:
    fixture = wmbs_m01.load_fixture()
    malformed = [row for row in fixture["rows"] if row["row_kind"] == "malformed"]
    assert len(malformed) == wmbs_m01.MALFORMED_COUNT
    kinds = {row["malformation_kind"] for row in malformed}
    assert len(kinds) == wmbs_m01.MALFORMED_COUNT
    for row in malformed:
        assert row["expected_outcome"] == "rejected"
        assert row["expected_error_code"] == "INVALID_REQUEST"


def test_restart_boundaries_are_recorded_and_referenced() -> None:
    fixture = wmbs_m01.load_fixture()
    boundary_ids = fixture["restart_boundary_row_ids"]
    assert len(boundary_ids) >= 2
    boundary_rows = {
        row["fixture_row_id"]: row
        for row in fixture["rows"]
        if row["fixture_row_id"] in boundary_ids
    }
    assert len(boundary_rows) == len(boundary_ids)
    for row in boundary_rows.values():
        assert row["restart_boundary_before"] is True
    non_boundary_ids = {row["fixture_row_id"] for row in fixture["rows"]} - set(
        boundary_ids
    )
    for row in fixture["rows"]:
        if row["fixture_row_id"] in non_boundary_ids:
            assert row["restart_boundary_before"] is False


# ---------------------------------------------------------------------------
# Scorer: golden payload 1 — perfect run passes every capture dimension
# ---------------------------------------------------------------------------


def test_golden_payload_1_perfect_run_passes_all_capture_dimensions() -> None:
    fixture = wmbs_m01.load_fixture()
    receipts = wmbs_m01.perfect_receipts(fixture)
    exported = wmbs_m01.perfect_export_rows(fixture)
    result = wmbs_m01.score_capture(fixture, receipts, exported)
    assert result["passed"] is True
    assert result["acknowledged_write_loss"]["loss_count"] == 0
    assert result["rejection_receipt_completeness"]["incomplete_count"] == 0
    assert result["exact_duplicate_materialization"]["materialized_count"] == 0
    assert result["schema_outcome_accuracy"]["accuracy"] == 1.0


# ---------------------------------------------------------------------------
# Scorer: golden payload 2 — acknowledged-write loss is detected
# ---------------------------------------------------------------------------


def test_golden_payload_2_acknowledged_write_loss_is_detected() -> None:
    fixture = wmbs_m01.load_fixture()
    receipts = wmbs_m01.perfect_receipts(fixture)
    target = _row(fixture, "primary")
    for receipt in receipts:
        if receipt["fixture_row_id"] == target["fixture_row_id"]:
            receipt["durability"] = "not_acknowledged"

    loss = wmbs_m01.score_acknowledged_write_loss(fixture, receipts)
    assert loss["passed"] is False
    assert loss["loss_count"] == 1
    assert target["fixture_row_id"] in loss["lost_row_ids"]

    exported = wmbs_m01.perfect_export_rows(fixture)
    result = wmbs_m01.score_capture(fixture, receipts, exported)
    assert result["passed"] is False


def test_golden_payload_2b_a_missing_receipt_is_also_acknowledged_write_loss() -> None:
    fixture = wmbs_m01.load_fixture()
    target = _row(fixture, "primary", index=1)
    receipts = [
        receipt
        for receipt in wmbs_m01.perfect_receipts(fixture)
        if receipt["fixture_row_id"] != target["fixture_row_id"]
    ]
    loss = wmbs_m01.score_acknowledged_write_loss(fixture, receipts)
    assert loss["passed"] is False
    assert target["fixture_row_id"] in loss["lost_row_ids"]


def test_golden_payload_2c_a_missing_rejected_receipt_is_not_acknowledged_write_loss() -> (
    None
):
    """A missing receipt for a `rejected`-expected row is a distinct failure.

    It must not be mislabeled as acknowledged-write loss, which is scoped to
    rows that were expected to become durable (`accepted`/`deduplicated`).
    """
    fixture = wmbs_m01.load_fixture()
    target = _row(fixture, "malformed")
    receipts = [
        receipt
        for receipt in wmbs_m01.perfect_receipts(fixture)
        if receipt["fixture_row_id"] != target["fixture_row_id"]
    ]

    loss = wmbs_m01.score_acknowledged_write_loss(fixture, receipts)
    assert loss["passed"] is True
    assert target["fixture_row_id"] not in loss["lost_row_ids"]

    completeness = wmbs_m01.score_rejection_receipt_completeness(fixture, receipts)
    assert completeness["passed"] is False
    assert completeness["incomplete_count"] == 1
    assert target["fixture_row_id"] in completeness["incomplete_row_ids"]


def test_rejection_receipt_completeness_passes_for_a_perfect_run() -> None:
    fixture = wmbs_m01.load_fixture()
    receipts = wmbs_m01.perfect_receipts(fixture)
    completeness = wmbs_m01.score_rejection_receipt_completeness(fixture, receipts)
    assert completeness["passed"] is True
    assert completeness["incomplete_count"] == 0
    assert completeness["incomplete_row_ids"] == ()


# ---------------------------------------------------------------------------
# Scorer: golden payload 3 — exact duplicate materialization is detected
# ---------------------------------------------------------------------------


def test_golden_payload_3_exact_duplicate_materialization_is_detected() -> None:
    """A receipt claiming `deduplicated` is not proof of zero materialization.

    This binds `M-DEDUP-EXACT` to the reopened/exported durable-state
    projection and counts materializations per canonical event identity
    (`event_id`), rather than trusting the capture receipt's outcome.
    """
    fixture = wmbs_m01.load_fixture()
    exported = wmbs_m01.perfect_export_rows(fixture)
    target = _row(fixture, "exact_duplicate")
    duplicated_record = next(
        record for record in exported if record["event_id"] == target["event_id"]
    )
    exported = [*exported, dict(duplicated_record)]

    dedup = wmbs_m01.score_exact_duplicate_materialization(fixture, exported)
    assert dedup["passed"] is False
    assert dedup["materialized_count"] == 1
    assert dedup["score"] == 0.0
    assert target["event_id"] in dedup["materialized_event_ids"]


def test_exact_duplicate_materialization_ignores_the_untrustworthy_receipt_outcome() -> (
    None
):
    """A receipt lying about `outcome` must not move this metric.

    The exported durable state is the only evidence this scorer trusts, per
    the fix to `M-DEDUP-EXACT`.
    """
    fixture = wmbs_m01.load_fixture()
    receipts = wmbs_m01.perfect_receipts(fixture)
    target = _row(fixture, "exact_duplicate")
    for receipt in receipts:
        if receipt["fixture_row_id"] == target["fixture_row_id"]:
            receipt["outcome"] = "accepted"
            receipt["error"] = None

    exported = wmbs_m01.perfect_export_rows(fixture)
    dedup = wmbs_m01.score_exact_duplicate_materialization(fixture, exported)
    assert dedup["passed"] is True
    assert dedup["materialized_count"] == 0


# ---------------------------------------------------------------------------
# Scorer: golden payload 4 — schema outcome mismatches are detected
# ---------------------------------------------------------------------------


def test_golden_payload_4_schema_outcome_mismatch_is_detected() -> None:
    fixture = wmbs_m01.load_fixture()
    receipts = wmbs_m01.perfect_receipts(fixture)
    target = _row(fixture, "malformed")
    for receipt in receipts:
        if receipt["fixture_row_id"] == target["fixture_row_id"]:
            receipt["outcome"] = "accepted"
            receipt["durability"] = "acknowledged"
            receipt["error"] = None

    outcome = wmbs_m01.score_schema_outcome_accuracy(fixture, receipts)
    assert outcome["passed"] is False
    assert outcome["accuracy"] < 1.0
    assert target["fixture_row_id"] in outcome["mismatched_row_ids"]


# ---------------------------------------------------------------------------
# Scorer: golden payload 5 — provenance retention violations are detected
# ---------------------------------------------------------------------------


def test_golden_payload_5_provenance_retention_passes_for_a_faithful_projection() -> (
    None
):
    fixture = wmbs_m01.load_fixture()
    projection = wmbs_m01.perfect_stored_projection(fixture)
    result = wmbs_m01.score_provenance_retention(fixture, projection)
    assert result["passed"] is True
    assert result["retention_rate"] == 1.0
    assert result["violations"] == ()


def test_golden_payload_5b_provenance_retention_detects_a_mutated_field() -> None:
    fixture = wmbs_m01.load_fixture()
    projection = wmbs_m01.perfect_stored_projection(fixture)
    any_event_id = next(iter(projection))
    projection = copy.deepcopy(projection)
    projection[any_event_id]["actor_label"] = "tampered-actor"

    result = wmbs_m01.score_provenance_retention(fixture, projection)
    assert result["passed"] is False
    assert result["retention_rate"] < 1.0
    assert any(
        violation["event_id"] == any_event_id and violation["field"] == "actor_label"
        for violation in result["violations"]
    )


def test_golden_payload_5c_provenance_retention_detects_a_missing_record() -> None:
    fixture = wmbs_m01.load_fixture()
    projection = wmbs_m01.perfect_stored_projection(fixture)
    any_event_id = next(iter(projection))
    projection = {k: v for k, v in projection.items() if k != any_event_id}

    result = wmbs_m01.score_provenance_retention(fixture, projection)
    assert result["passed"] is False
    assert any(
        violation["event_id"] == any_event_id for violation in result["violations"]
    )


# ---------------------------------------------------------------------------
# Reopen/export projection case
# ---------------------------------------------------------------------------


def test_reopen_export_projection_matches_the_fixture_when_faithful() -> None:
    fixture = wmbs_m01.load_fixture()
    exported = wmbs_m01.perfect_export_rows(fixture)
    result = wmbs_m01.score_reopen_export_projection(fixture, exported)
    assert result["passed"] is True
    assert result["missing_event_ids"] == ()
    assert result["unexpected_event_ids"] == ()
    assert result["duplicate_exported_event_ids"] == ()
    assert result["field_violations"] == ()
    unique_materialized = wmbs_m01.BASE_EVENT_COUNT + wmbs_m01.NEAR_DUPLICATE_COUNT
    assert len(exported) == unique_materialized


def test_reopen_export_projection_detects_a_missing_export_row() -> None:
    fixture = wmbs_m01.load_fixture()
    exported = wmbs_m01.perfect_export_rows(fixture)
    dropped_id = exported[0]["event_id"]
    exported = exported[1:]

    result = wmbs_m01.score_reopen_export_projection(fixture, exported)
    assert result["passed"] is False
    assert dropped_id in result["missing_event_ids"]


def test_reopen_export_projection_detects_leaked_malformed_or_dedup_rows() -> None:
    fixture = wmbs_m01.load_fixture()
    exported = wmbs_m01.perfect_export_rows(fixture)
    malformed = _row(fixture, "malformed")
    leaked_id = malformed["event_id"] or "m01-dev-leak-00000"
    leaked_row = dict(malformed["raw_event"])
    leaked_row["event_id"] = leaked_id
    exported = [*exported, leaked_row]

    result = wmbs_m01.score_reopen_export_projection(fixture, exported)
    assert result["passed"] is False
    assert leaked_id in result["unexpected_event_ids"]


def test_reopen_export_projection_detects_duplicate_exported_rows() -> None:
    fixture = wmbs_m01.load_fixture()
    exported = wmbs_m01.perfect_export_rows(fixture)
    exported = [*exported, dict(exported[0])]

    result = wmbs_m01.score_reopen_export_projection(fixture, exported)
    assert result["passed"] is False
    assert exported[0]["event_id"] in result["duplicate_exported_event_ids"]


# ---------------------------------------------------------------------------
# Canonical replay projection — closed ABI, not an arbitrary-payload hash
# ---------------------------------------------------------------------------


def test_canonical_replay_projection_allowlists_semantic_fields_and_drops_volatile() -> (
    None
):
    receipt = {
        "fixture_row_id": "row-00000",
        "outcome": "accepted",
        "durability": "acknowledged",
        "evidence_handle": "evidence-row-00000",
        "error": None,
    }
    projected = wmbs_m01.canonical_replay_projection([receipt])
    assert projected == [
        {
            "fixture_row_id": "row-00000",
            "outcome": "accepted",
            "durability": "acknowledged",
            "error": None,
        }
    ]


def test_canonical_replay_projection_rejects_an_unrecognized_field() -> None:
    receipt = {
        "fixture_row_id": "row-00000",
        "outcome": "accepted",
        "durability": "acknowledged",
        "evidence_handle": None,
        "error": None,
        "wall_clock_ns": 12345,
    }
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.canonical_replay_projection([receipt])


def test_canonical_replay_equality_ignores_the_volatile_evidence_handle_field() -> None:
    """A per-run evidence handle is a runtime-generated pointer, not semantic.

    A fully faithful implementation may legitimately mint a fresh handle on
    every run; canonical replay equality must not fail because of it.
    """
    fixture = wmbs_m01.load_fixture()
    base = wmbs_m01.perfect_receipts(fixture)
    clean_runs = []
    for run_index in range(5):
        run = copy.deepcopy(base)
        for receipt in run:
            if receipt["evidence_handle"] is not None:
                receipt["evidence_handle"] = (
                    f"{receipt['evidence_handle']}-run{run_index}"
                )
        clean_runs.append(run)
    restart_run = copy.deepcopy(base)
    for receipt in restart_run:
        if receipt["evidence_handle"] is not None:
            receipt["evidence_handle"] = f"{receipt['evidence_handle']}-restart"

    result = wmbs_m01.score_canonical_replay_equality(clean_runs, restart_run)
    assert result["passed"] is True
    assert result["unique_digest_count"] == 1


def test_canonical_replay_equality_rejects_a_payload_with_an_unrecognized_field() -> (
    None
):
    fixture = wmbs_m01.load_fixture()
    payload = wmbs_m01.perfect_receipts(fixture)
    payload[0]["host_path"] = "/tmp/whatever"
    clean_runs = [copy.deepcopy(payload) for _ in range(5)]
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.score_canonical_replay_equality(clean_runs, copy.deepcopy(payload))


# ---------------------------------------------------------------------------
# Canonical replay equality
# ---------------------------------------------------------------------------


def test_canonical_replay_equality_passes_for_five_identical_runs_plus_restart() -> (
    None
):
    fixture = wmbs_m01.load_fixture()
    payload = wmbs_m01.perfect_receipts(fixture)
    clean_runs = [copy.deepcopy(payload) for _ in range(5)]
    restart_run = copy.deepcopy(payload)

    result = wmbs_m01.score_canonical_replay_equality(clean_runs, restart_run)
    assert result["passed"] is True
    assert result["unique_digest_count"] == 1
    assert len(result["clean_run_digests"]) == 5


def test_canonical_replay_equality_fails_when_a_run_diverges() -> None:
    fixture = wmbs_m01.load_fixture()
    payload = wmbs_m01.perfect_receipts(fixture)
    clean_runs = [copy.deepcopy(payload) for _ in range(5)]
    clean_runs[-1][0]["outcome"] = "rejected"
    restart_run = copy.deepcopy(payload)

    result = wmbs_m01.score_canonical_replay_equality(clean_runs, restart_run)
    assert result["passed"] is False
    assert result["unique_digest_count"] > 1


def test_canonical_replay_equality_requires_the_minimum_run_count() -> None:
    fixture = wmbs_m01.load_fixture()
    payload = wmbs_m01.perfect_receipts(fixture)
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.score_canonical_replay_equality(
            [copy.deepcopy(payload) for _ in range(4)], payload
        )


# ---------------------------------------------------------------------------
# Receipt-contract defensiveness
# ---------------------------------------------------------------------------


def test_index_receipts_rejects_a_missing_fixture_row_id() -> None:
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.score_schema_outcome_accuracy(
            wmbs_m01.load_fixture(),
            [{"outcome": "accepted", "durability": "acknowledged"}],
        )


def test_index_receipts_rejects_a_duplicate_fixture_row_id() -> None:
    fixture = wmbs_m01.load_fixture()
    receipts = wmbs_m01.perfect_receipts(fixture)
    receipts.append(dict(receipts[0]))
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.score_schema_outcome_accuracy(fixture, receipts)


def test_index_receipts_rejects_an_unknown_fixture_row_id() -> None:
    fixture = wmbs_m01.load_fixture()
    receipts = wmbs_m01.perfect_receipts(fixture)
    receipts.append(
        {
            "fixture_row_id": "row-99999",
            "outcome": "accepted",
            "durability": "acknowledged",
            "evidence_handle": "evidence-row-99999",
            "error": None,
        }
    )
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.score_schema_outcome_accuracy(fixture, receipts)


def test_index_receipts_rejects_an_unknown_row_id_in_acknowledged_write_loss() -> None:
    fixture = wmbs_m01.load_fixture()
    receipts = wmbs_m01.perfect_receipts(fixture)
    receipts.append(
        {
            "fixture_row_id": "row-99999",
            "outcome": "accepted",
            "durability": "acknowledged",
            "evidence_handle": "evidence-row-99999",
            "error": None,
        }
    )
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.score_acknowledged_write_loss(fixture, receipts)


# ---------------------------------------------------------------------------
# Fixture validation — schema identity, counts, uniqueness, closed keys, digest
# ---------------------------------------------------------------------------


def test_validate_fixture_accepts_the_committed_fixture() -> None:
    fixture = _load_committed_fixture()
    assert wmbs_m01.validate_fixture(fixture) is fixture


def test_validate_fixture_rejects_a_wrong_schema_id() -> None:
    fixture = copy.deepcopy(_load_committed_fixture())
    fixture["schema_id"] = "not-the-real-schema"
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.validate_fixture(fixture)


def test_validate_fixture_rejects_an_unknown_top_level_key() -> None:
    fixture = copy.deepcopy(_load_committed_fixture())
    fixture["unexpected_field"] = "surprise"
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.validate_fixture(fixture)


def test_validate_fixture_rejects_a_missing_top_level_key() -> None:
    fixture = copy.deepcopy(_load_committed_fixture())
    del fixture["seed"]
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.validate_fixture(fixture)


def test_validate_fixture_rejects_a_declared_count_mismatch() -> None:
    fixture = copy.deepcopy(_load_committed_fixture())
    fixture["base_event_count"] = fixture["base_event_count"] - 1
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.validate_fixture(fixture)


def test_validate_fixture_rejects_duplicate_fixture_row_ids() -> None:
    fixture = copy.deepcopy(_load_committed_fixture())
    fixture["rows"][1]["fixture_row_id"] = fixture["rows"][0]["fixture_row_id"]
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.validate_fixture(fixture)


def test_validate_fixture_rejects_an_unknown_row_key() -> None:
    fixture = copy.deepcopy(_load_committed_fixture())
    fixture["rows"][0]["unexpected_row_field"] = "surprise"
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.validate_fixture(fixture)


def test_validate_fixture_rejects_a_missing_row_key() -> None:
    fixture = copy.deepcopy(_load_committed_fixture())
    del fixture["rows"][0]["expected_error_code"]
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.validate_fixture(fixture)


def test_validate_fixture_rejects_an_unknown_row_kind() -> None:
    fixture = copy.deepcopy(_load_committed_fixture())
    fixture["rows"][0]["row_kind"] = "not_a_real_kind"
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.validate_fixture(fixture)


def test_validate_fixture_rejects_a_tampered_digest() -> None:
    fixture = copy.deepcopy(_load_committed_fixture())
    fixture["rows"][0]["raw_event"]["content"] = "tampered content"
    with pytest.raises(wmbs_m01.WmbsM01Error):
        wmbs_m01.validate_fixture(fixture)


def test_generate_fixture_output_passes_validate_fixture() -> None:
    fixture = wmbs_m01.generate_fixture(wmbs_m01.DEFAULT_SEED)
    assert wmbs_m01.validate_fixture(fixture) is fixture


# ---------------------------------------------------------------------------
# Explicit non-claim boundary
# ---------------------------------------------------------------------------


def test_module_declares_proposed_admission_state_with_no_claim_constants() -> None:
    assert wmbs_m01.ADMISSION_STATE == "PROPOSED"
    forbidden = {
        "OFFICIAL_SCORE",
        "SUPERIORITY_CLAIM",
        "PILOT_READY",
        "CERTIFIED",
        "LAUNCH_READY",
        "OPERATOR_APPROVED",
    }
    assert not (forbidden & set(dir(wmbs_m01)))

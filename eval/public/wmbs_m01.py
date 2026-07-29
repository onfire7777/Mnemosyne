"""Pure M01 (capture and durability) development fixture and scorer.

This module owns exactly two things, per the design specification at
`docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
(section "M01 -- Capture and durability") and Task 4 of
`docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`:

1. A deterministic, seed-pinned generator for a bounded development fixture
   containing mixed events, exact duplicates, near duplicates, malformed
   rows, stable event IDs, and restart boundaries. The frozen output is
   committed at `eval/public/fixtures/wmbs-m01-development.json` as the
   exact `canonical_json()` bytes of `generate_fixture(DEFAULT_SEED)`
   (`fixture_sha256=e6db3c36963179123fc5aa4c760631c7841438e5f276e9c322cca3ce99a2ad5f`)
   -- the committed file's raw bytes, not merely a re-serialization of its
   parsed value, are what `generate_fixture` reproduces.
2. A pure, stdlib-only scorer that consumes normalized fixture expectations
   plus externally supplied capture receipts and a reopen/export
   durable-state projection, and scores zero acknowledged-write loss (rows
   expected to become durable only), rejection-receipt completeness (rows
   expected to be rejected, scored separately so a missing rejection
   receipt is never mislabeled as acknowledged-write loss), zero
   exact-duplicate materialization (bound to the durable-state export, not
   the capture receipt's claimed outcome), schema outcome accuracy,
   provenance-field retention, and canonical replay equality over a closed
   receipt-field projection, including a reopen/export projection case.

Admission state: PROPOSED. This module makes no official, superiority,
pilot-ready, operator, hardware, protected, network, model, or database
claim, and it runs no measured benchmark. It does not implement, wire, or
call any of the following -- they remain explicit integration dependencies
for the single lifecycle owner:

- CLI metadata pass-through (`src/mnemosyne/cli.py`, `eval/harness/cli_driver.py`).
- Shared adapter wiring (`eval/public/adapters/whole_memory_reference.py`).
- Shared scoring registration (`eval/public/scoring.py`, `score_profile`).
- SQLite or PostgreSQL persistence and crash-durability execution.
- Sandbox execution, resource metering, and any measured benchmark run.

The receipt/projection inputs accepted below are this module's own minimal
contract (`fixture_row_id`-keyed), not a claim of `wmbs/0.1-draft` ABI
conformance; that binding is one of the deferred dependencies above.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

MODULE_ID = "M01"
ADMISSION_STATE = "PROPOSED"
FIXTURE_ID = "wmbs-m01-development"
FIXTURE_SCHEMA_ID = "wmbs-m01-fixture-v1"
GENERATOR_ID = "wmbs_m01.generate_fixture"
GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20260728

BASE_EVENT_COUNT = 40
EXACT_DUPLICATE_COUNT = 2
NEAR_DUPLICATE_COUNT = 2
MALFORMED_COUNT = 2
TOTAL_ROW_COUNT = (
    BASE_EVENT_COUNT + EXACT_DUPLICATE_COUNT + NEAR_DUPLICATE_COUNT + MALFORMED_COUNT
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "wmbs-m01-development.json"
)

MIN_CLEAN_REPLAY_RUNS = 5

_ANCHOR_EVENT_TIME = datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC)
_EVENT_STEP_SECONDS = 90
_INGESTION_LAG_SECONDS = 5
_ACTOR_POOL = ("user-alpha", "user-beta", "agent-relay", "system-ingest")
_TOPIC_POOL = (
    "battery",
    "calendar",
    "inventory",
    "shipment",
    "sensor",
    "conversation",
    "preference",
    "task",
)
_NEAR_DUPLICATE_TEMPLATES = ("{content} ", "{content}.")
_MALFORMATION_KINDS = (
    "missing_required_field",
    "invalid_timestamp_format",
    "wrong_type_sequence",
    "unknown_field_present",
)

_SENTINEL_MISSING = object()

_TOP_LEVEL_FIXTURE_KEYS = frozenset(
    {
        "fixture_id",
        "schema_id",
        "module_id",
        "generator_id",
        "generator_version",
        "seed",
        "base_event_count",
        "exact_duplicate_count",
        "near_duplicate_count",
        "malformed_count",
        "total_row_count",
        "exact_duplicate_ratio",
        "near_duplicate_ratio",
        "restart_boundary_row_ids",
        "rows",
        "fixture_sha256",
    }
)

_COMMON_ROW_KEYS = frozenset(
    {
        "fixture_row_id",
        "row_kind",
        "restart_boundary_before",
        "event_id",
        "raw_event",
        "expected_outcome",
        "expected_error_code",
        "relation",
    }
)

_ROW_KIND_EXTRA_KEYS: dict[str, frozenset[str]] = {
    "primary": frozenset(),
    "exact_duplicate": frozenset({"retry_received_at"}),
    "near_duplicate": frozenset(),
    "malformed": frozenset({"malformation_kind"}),
}

_ROW_KIND_COUNT_FIELDS: dict[str, str] = {
    "primary": "base_event_count",
    "exact_duplicate": "exact_duplicate_count",
    "near_duplicate": "near_duplicate_count",
    "malformed": "malformed_count",
}

_CANONICAL_REPLAY_SEMANTIC_FIELDS = ("fixture_row_id", "outcome", "durability", "error")
_CANONICAL_REPLAY_VOLATILE_FIELDS = ("evidence_handle",)
_CANONICAL_REPLAY_KNOWN_FIELDS = frozenset(
    _CANONICAL_REPLAY_SEMANTIC_FIELDS
) | frozenset(_CANONICAL_REPLAY_VOLATILE_FIELDS)


class WmbsM01Error(ValueError):
    """The fixture, a receipt, or a projection violated this module's contract."""


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> bytes:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        ensure_ascii=False,
    )
    return (encoded + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _format_ts(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Fixture generation
# ---------------------------------------------------------------------------


def _portable_event(
    *,
    event_id: str,
    content: str,
    actor_label: str,
    event_time: str,
    ingestion_time: str,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "content": content,
        "actor_label": actor_label,
        "event_time": event_time,
        "ingestion_time": ingestion_time,
        "valid_from": None,
        "valid_to": None,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "modality_handle": None,
        "public_metadata": {"source": GENERATOR_ID},
    }


def _apply_malformation(raw_event: dict[str, Any], kind: str) -> dict[str, Any]:
    malformed = dict(raw_event)
    if kind == "missing_required_field":
        del malformed["content_sha256"]
    elif kind == "invalid_timestamp_format":
        malformed["event_time"] = malformed["event_time"].removesuffix("Z")
    elif kind == "wrong_type_sequence":
        malformed["event_time"] = 12345
    elif kind == "unknown_field_present":
        malformed["debug_note"] = "not part of the portable_event contract"
    else:  # pragma: no cover - defensive, unreachable given the closed pool
        raise WmbsM01Error(f"unknown malformation kind: {kind}")
    return malformed


def generate_fixture(seed: int = DEFAULT_SEED) -> dict[str, Any]:
    """Deterministically build the M01 development fixture for `seed`.

    Pure function of `seed`: no wall-clock or OS entropy is consulted. This
    is the generator that produced the committed
    `eval/public/fixtures/wmbs-m01-development.json`.
    """
    rng = random.Random(seed)
    row_counter = 0

    def _next_row_id() -> str:
        nonlocal row_counter
        row_id = f"row-{row_counter:05d}"
        row_counter += 1
        return row_id

    rows: list[dict[str, Any]] = []
    primaries: list[dict[str, Any]] = []
    for index in range(BASE_EVENT_COUNT):
        event_time = _ANCHOR_EVENT_TIME + timedelta(seconds=_EVENT_STEP_SECONDS * index)
        ingestion_time = event_time + timedelta(seconds=_INGESTION_LAG_SECONDS)
        topic = _TOPIC_POOL[index % len(_TOPIC_POOL)]
        actor = _ACTOR_POOL[index % len(_ACTOR_POOL)]
        event_id = f"m01-dev-{index:05d}"
        raw_event = _portable_event(
            event_id=event_id,
            content=f"Observation {index:04d}: {topic} update at tick {index}.",
            actor_label=actor,
            event_time=_format_ts(event_time),
            ingestion_time=_format_ts(ingestion_time),
        )
        row = {
            "fixture_row_id": _next_row_id(),
            "row_kind": "primary",
            "restart_boundary_before": False,
            "event_id": event_id,
            "raw_event": raw_event,
            "expected_outcome": "accepted",
            "expected_error_code": None,
            "relation": {"kind": None, "source_event_id": None},
        }
        rows.append(row)
        primaries.append(row)

    dup_indices = sorted(rng.sample(range(BASE_EVENT_COUNT), EXACT_DUPLICATE_COUNT))
    remaining_indices = [i for i in range(BASE_EVENT_COUNT) if i not in dup_indices]
    near_indices = sorted(rng.sample(remaining_indices, NEAR_DUPLICATE_COUNT))
    malformation_kinds = rng.sample(_MALFORMATION_KINDS, MALFORMED_COUNT)

    tail_time = _ANCHOR_EVENT_TIME + timedelta(
        seconds=_EVENT_STEP_SECONDS * BASE_EVENT_COUNT
    )
    restart_boundary_row_ids: list[str] = []

    for position, source_index in enumerate(dup_indices):
        source_row = primaries[source_index]
        retry_ingestion_time = tail_time + timedelta(
            seconds=_EVENT_STEP_SECONDS * position
        )
        # Replay the complete original raw event unchanged: an "exact
        # duplicate" that mutates any field of raw_event (including
        # ingestion_time) is not actually exact. Retry timing is recorded
        # on the row, outside raw_event, where it belongs.
        raw_event = dict(source_row["raw_event"])
        row_id = _next_row_id()
        is_boundary = position == 0
        if is_boundary:
            restart_boundary_row_ids.append(row_id)
        rows.append(
            {
                "fixture_row_id": row_id,
                "row_kind": "exact_duplicate",
                "restart_boundary_before": is_boundary,
                "event_id": source_row["event_id"],
                "raw_event": raw_event,
                "retry_received_at": _format_ts(retry_ingestion_time),
                "expected_outcome": "deduplicated",
                "expected_error_code": None,
                "relation": {
                    "kind": "exact_duplicate_of",
                    "source_event_id": source_row["event_id"],
                },
            }
        )

    near_start = tail_time + timedelta(
        seconds=_EVENT_STEP_SECONDS * EXACT_DUPLICATE_COUNT
    )
    for position, source_index in enumerate(near_indices):
        source_row = primaries[source_index]
        template = _NEAR_DUPLICATE_TEMPLATES[position % len(_NEAR_DUPLICATE_TEMPLATES)]
        content = template.format(content=source_row["raw_event"]["content"])
        event_time = near_start + timedelta(seconds=_EVENT_STEP_SECONDS * position)
        ingestion_time = event_time + timedelta(seconds=_INGESTION_LAG_SECONDS)
        event_id = f"m01-dev-near-{position:05d}"
        raw_event = _portable_event(
            event_id=event_id,
            content=content,
            actor_label=source_row["raw_event"]["actor_label"],
            event_time=_format_ts(event_time),
            ingestion_time=_format_ts(ingestion_time),
        )
        rows.append(
            {
                "fixture_row_id": _next_row_id(),
                "row_kind": "near_duplicate",
                "restart_boundary_before": False,
                "event_id": event_id,
                "raw_event": raw_event,
                "expected_outcome": "accepted",
                "expected_error_code": None,
                "relation": {
                    "kind": "near_duplicate_of",
                    "source_event_id": source_row["event_id"],
                },
            }
        )

    malformed_start = near_start + timedelta(
        seconds=_EVENT_STEP_SECONDS * NEAR_DUPLICATE_COUNT
    )
    for position, kind in enumerate(malformation_kinds):
        event_time = malformed_start + timedelta(seconds=_EVENT_STEP_SECONDS * position)
        ingestion_time = event_time + timedelta(seconds=_INGESTION_LAG_SECONDS)
        event_id = f"m01-dev-bad-{position:05d}"
        raw_event = _portable_event(
            event_id=event_id,
            content=f"Malformed row {position:04d} exercising {kind}.",
            actor_label=_ACTOR_POOL[position % len(_ACTOR_POOL)],
            event_time=_format_ts(event_time),
            ingestion_time=_format_ts(ingestion_time),
        )
        raw_event = _apply_malformation(raw_event, kind)
        row_id = _next_row_id()
        is_boundary = position == len(malformation_kinds) - 1
        if is_boundary:
            restart_boundary_row_ids.append(row_id)
        rows.append(
            {
                "fixture_row_id": row_id,
                "row_kind": "malformed",
                "restart_boundary_before": is_boundary,
                "event_id": raw_event.get("event_id"),
                "raw_event": raw_event,
                "expected_outcome": "rejected",
                "expected_error_code": "INVALID_REQUEST",
                "relation": {"kind": None, "source_event_id": None},
                "malformation_kind": kind,
            }
        )

    fixture: dict[str, Any] = {
        "fixture_id": FIXTURE_ID,
        "schema_id": FIXTURE_SCHEMA_ID,
        "module_id": MODULE_ID,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "base_event_count": BASE_EVENT_COUNT,
        "exact_duplicate_count": EXACT_DUPLICATE_COUNT,
        "near_duplicate_count": NEAR_DUPLICATE_COUNT,
        "malformed_count": MALFORMED_COUNT,
        "total_row_count": TOTAL_ROW_COUNT,
        "exact_duplicate_ratio": EXACT_DUPLICATE_COUNT / BASE_EVENT_COUNT,
        "near_duplicate_ratio": NEAR_DUPLICATE_COUNT / BASE_EVENT_COUNT,
        "restart_boundary_row_ids": restart_boundary_row_ids,
        "rows": rows,
    }
    fixture["fixture_sha256"] = _fixture_digest(fixture)
    validate_fixture(fixture)
    return fixture


def _fixture_digest(fixture_without_digest: Mapping[str, Any]) -> str:
    payload = {k: v for k, v in fixture_without_digest.items() if k != "fixture_sha256"}
    return canonical_sha256(payload)


def validate_fixture(fixture: Mapping[str, Any]) -> Mapping[str, Any]:
    """Fail-closed structural validation of a fixture, before it is scored.

    Checks, in order: the top-level key set is closed (schema identity is
    part of this -- `schema_id`/`module_id` must be present and correct),
    every row has a closed key set for its `row_kind`, `fixture_row_id`
    values are unique, declared row counts match the actual rows, and the
    recorded digest matches. Returns `fixture` unchanged on success.

    This does not validate `raw_event` contents: `malformed` rows
    deliberately violate the portable-event schema, since that is the
    scorer input they exist to exercise.
    """
    if not isinstance(fixture, Mapping):
        raise WmbsM01Error("fixture payload must be a mapping")

    top_level_keys = set(fixture)
    missing_top_level = _TOP_LEVEL_FIXTURE_KEYS - top_level_keys
    unknown_top_level = top_level_keys - _TOP_LEVEL_FIXTURE_KEYS
    if missing_top_level or unknown_top_level:
        raise WmbsM01Error(
            "fixture has a non-closed top-level key set: "
            f"missing={sorted(missing_top_level)} unknown={sorted(unknown_top_level)}"
        )

    if fixture["schema_id"] != FIXTURE_SCHEMA_ID:
        raise WmbsM01Error(
            f"fixture schema_id {fixture['schema_id']!r} does not match "
            f"{FIXTURE_SCHEMA_ID!r}"
        )
    if fixture["module_id"] != MODULE_ID:
        raise WmbsM01Error(
            f"fixture module_id {fixture['module_id']!r} does not match {MODULE_ID!r}"
        )

    rows = fixture["rows"]
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise WmbsM01Error("fixture rows must be a sequence")

    row_ids: list[str] = []
    kind_counts: dict[str, int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise WmbsM01Error(f"fixture row[{index}] must be a mapping")
        row_id = row.get("fixture_row_id")
        if not isinstance(row_id, str) or not row_id:
            raise WmbsM01Error(f"fixture row[{index}] has an invalid fixture_row_id")
        row_ids.append(row_id)

        kind = row.get("row_kind")
        extra_keys = _ROW_KIND_EXTRA_KEYS.get(kind)
        if extra_keys is None:
            raise WmbsM01Error(
                f"fixture row {row_id!r} has an unknown row_kind: {kind!r}"
            )
        allowed_keys = _COMMON_ROW_KEYS | extra_keys
        row_keys = set(row)
        missing_row = allowed_keys - row_keys
        unknown_row = row_keys - allowed_keys
        if missing_row or unknown_row:
            raise WmbsM01Error(
                f"fixture row {row_id!r} has a non-closed key set: "
                f"missing={sorted(missing_row)} unknown={sorted(unknown_row)}"
            )
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    if len(row_ids) != len(set(row_ids)):
        raise WmbsM01Error("fixture rows contain duplicate fixture_row_id values")

    declared_total = fixture["total_row_count"]
    if declared_total != (
        fixture["base_event_count"]
        + fixture["exact_duplicate_count"]
        + fixture["near_duplicate_count"]
        + fixture["malformed_count"]
    ):
        raise WmbsM01Error(
            "fixture total_row_count does not match the sum of its parts"
        )
    if len(rows) != declared_total:
        raise WmbsM01Error(
            f"fixture declares {declared_total} rows but contains {len(rows)}"
        )
    for kind, count_field in _ROW_KIND_COUNT_FIELDS.items():
        actual = kind_counts.get(kind, 0)
        declared = fixture[count_field]
        if actual != declared:
            raise WmbsM01Error(
                f"fixture {count_field}={declared} does not match {actual} "
                f"observed {kind!r} rows"
            )

    recorded_digest = fixture.get("fixture_sha256")
    expected_digest = _fixture_digest(fixture)
    if recorded_digest != expected_digest:
        raise WmbsM01Error("fixture digest mismatch; the frozen fixture was mutated")

    return fixture


def load_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    """Load and fully validate (schema, counts, uniqueness, keys, digest)."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise WmbsM01Error("fixture payload must be a JSON object")
    validate_fixture(payload)
    return payload


# ---------------------------------------------------------------------------
# Fixture normalization
# ---------------------------------------------------------------------------


def normalize_fixture(fixture: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Project each fixture row to its scored expectation, keyed by row ID."""
    validate_fixture(fixture)
    normalized: dict[str, dict[str, Any]] = {}
    for row in fixture["rows"]:
        row_id = row["fixture_row_id"]
        normalized[row_id] = {
            "row_kind": row["row_kind"],
            "event_id": row.get("event_id"),
            "expected_outcome": row["expected_outcome"],
            "expected_error_code": row.get("expected_error_code"),
            "restart_boundary_before": row.get("restart_boundary_before", False),
        }
    return normalized


def _materialized_provenance(fixture: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The exactly-once-per-event_id provenance record the corpus should hold.

    `exact_duplicate` rows are deliberately excluded: they share `event_id`
    with their `primary` source and must not materialize a second record.
    `malformed` rows are excluded: they are expected to be rejected.
    """
    validate_fixture(fixture)
    materialized: dict[str, dict[str, Any]] = {}
    for row in fixture["rows"]:
        if row["row_kind"] in ("primary", "near_duplicate"):
            materialized[row["event_id"]] = dict(row["raw_event"])
    return materialized


# ---------------------------------------------------------------------------
# Golden-payload helpers (perfect receipts/projections derived from a fixture)
# ---------------------------------------------------------------------------


def perfect_receipts(fixture: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The capture receipts a fully spec-conformant system would return."""
    receipts: list[dict[str, Any]] = []
    for row in fixture["rows"]:
        outcome = row["expected_outcome"]
        durability = (
            "acknowledged"
            if outcome in ("accepted", "deduplicated")
            else "not_acknowledged"
        )
        error = None
        if outcome == "rejected":
            error = {
                "code": row.get("expected_error_code") or "INVALID_REQUEST",
                "message": "fixture-defined rejection",
            }
        receipts.append(
            {
                "fixture_row_id": row["fixture_row_id"],
                "outcome": outcome,
                "durability": durability,
                "evidence_handle": None
                if outcome == "rejected"
                else f"evidence-{row['fixture_row_id']}",
                "error": error,
            }
        )
    return receipts


def perfect_stored_projection(fixture: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The stored-record projection a fully faithful system would hold."""
    return _materialized_provenance(fixture)


def perfect_export_rows(fixture: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The reopen/export rows a fully faithful system would produce."""
    return [dict(record) for record in _materialized_provenance(fixture).values()]


# ---------------------------------------------------------------------------
# Receipt indexing
# ---------------------------------------------------------------------------


def _index_receipts(
    receipts: Sequence[Mapping[str, Any]],
    known_row_ids: Sequence[str] | set[str],
) -> dict[str, Mapping[str, Any]]:
    known = known_row_ids if isinstance(known_row_ids, set) else set(known_row_ids)
    indexed: dict[str, Mapping[str, Any]] = {}
    for receipt in receipts:
        row_id = receipt.get("fixture_row_id")
        if not isinstance(row_id, str) or not row_id:
            raise WmbsM01Error("capture receipt is missing fixture_row_id")
        if row_id not in known:
            raise WmbsM01Error(
                f"capture receipt references unknown fixture_row_id: {row_id!r}"
            )
        if row_id in indexed:
            raise WmbsM01Error(f"duplicate capture receipt for {row_id}")
        indexed[row_id] = receipt
    return indexed


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_acknowledged_write_loss(
    fixture: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Rows expected to become durable (`accepted`/`deduplicated`) only.

    A missing or non-acknowledged receipt for a `rejected`-expected row is
    not scored here: see `score_rejection_receipt_completeness`, which is
    the correct home for that failure mode.
    """
    normalized = normalize_fixture(fixture)
    receipts_by_row = _index_receipts(receipts, set(normalized))
    lost_rows: list[str] = []
    for row_id, expectation in normalized.items():
        if expectation["expected_outcome"] not in ("accepted", "deduplicated"):
            continue
        receipt = receipts_by_row.get(row_id)
        if receipt is None or receipt.get("durability") != "acknowledged":
            lost_rows.append(row_id)
    return {
        "metric": "M01-ACK-LOSS",
        "loss_count": len(lost_rows),
        "lost_row_ids": tuple(sorted(lost_rows)),
        "passed": len(lost_rows) == 0,
    }


def score_rejection_receipt_completeness(
    fixture: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Rows expected to be `rejected` must still receive a receipt.

    A missing receipt for such a row is not acknowledged-write loss (that
    row was never supposed to become durable): it is the harness silently
    swallowing the row instead of returning a rejection receipt. This is a
    distinct completeness dimension, kept separate from
    `score_acknowledged_write_loss` so the two failure modes cannot be
    conflated or averaged away.
    """
    normalized = normalize_fixture(fixture)
    receipts_by_row = _index_receipts(receipts, set(normalized))
    incomplete_rows: list[str] = []
    for row_id, expectation in normalized.items():
        if expectation["expected_outcome"] != "rejected":
            continue
        if row_id not in receipts_by_row:
            incomplete_rows.append(row_id)
    return {
        "metric": "M01-REJECTION-RECEIPT-COMPLETENESS",
        "incomplete_count": len(incomplete_rows),
        "incomplete_row_ids": tuple(sorted(incomplete_rows)),
        "passed": len(incomplete_rows) == 0,
    }


def score_exact_duplicate_materialization(
    fixture: Mapping[str, Any], exported_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Prove zero duplicate materializations from the durable-state export.

    A capture receipt claiming `outcome == "deduplicated"` is not proof
    that the store holds zero duplicate materializations: the receipt could
    be wrong, or the store could materialize a second record despite it.
    This binds `M-DEDUP-EXACT` to the reopened/exported durable-state
    projection (`exported_rows`, e.g. from `perfect_export_rows` or a real
    reopen/export call) and counts materializations per canonical event
    identity (`event_id`), for every identity that a fixture-defined
    exact-duplicate row targets.
    """
    normalized = normalize_fixture(fixture)
    exact_duplicate_event_ids = {
        expectation["event_id"]
        for expectation in normalized.values()
        if expectation["row_kind"] == "exact_duplicate"
    }
    materialization_counts: dict[str, int] = {}
    for row in exported_rows:
        event_id = row.get("event_id")
        if event_id is None:
            continue
        materialization_counts[event_id] = materialization_counts.get(event_id, 0) + 1

    materialized_event_ids = sorted(
        event_id
        for event_id in exact_duplicate_event_ids
        if materialization_counts.get(event_id, 0) > 1
    )
    return {
        "metric": "M-DEDUP-EXACT",
        "materialized_count": len(materialized_event_ids),
        "materialized_event_ids": tuple(materialized_event_ids),
        "score": 1.0 if not materialized_event_ids else 0.0,
        "passed": not materialized_event_ids,
    }


def score_schema_outcome_accuracy(
    fixture: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    normalized = normalize_fixture(fixture)
    receipts_by_row = _index_receipts(receipts, set(normalized))
    total = len(normalized)
    correct = 0
    mismatches: list[str] = []
    for row_id, expectation in normalized.items():
        receipt = receipts_by_row.get(row_id)
        actual = receipt.get("outcome") if receipt is not None else None
        if actual == expectation["expected_outcome"]:
            correct += 1
        else:
            mismatches.append(row_id)
    accuracy = correct / total if total else 1.0
    return {
        "metric": "M01-SCHEMA-OUTCOME-ACCURACY",
        "accuracy": accuracy,
        "mismatched_row_ids": tuple(sorted(mismatches)),
        "passed": accuracy == 1.0,
    }


def score_provenance_retention(
    fixture: Mapping[str, Any], stored_projection: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    expected = _materialized_provenance(fixture)
    total_fields = 0
    retained_fields = 0
    violations: list[dict[str, Any]] = []
    for event_id, expected_record in expected.items():
        stored_record = stored_projection.get(event_id)
        if stored_record is None:
            total_fields += len(expected_record)
            violations.append(
                {"event_id": event_id, "field": "*", "reason": "missing_record"}
            )
            continue
        for field, expected_value in expected_record.items():
            total_fields += 1
            actual_value = stored_record.get(field, _SENTINEL_MISSING)
            if actual_value is _SENTINEL_MISSING:
                violations.append(
                    {"event_id": event_id, "field": field, "reason": "missing_field"}
                )
                continue
            if canonical_json(actual_value) != canonical_json(expected_value):
                violations.append(
                    {"event_id": event_id, "field": field, "reason": "mutated"}
                )
                continue
            retained_fields += 1
    retention_rate = retained_fields / total_fields if total_fields else 1.0
    return {
        "metric": "M01-PROVENANCE-RETENTION",
        "retention_rate": retention_rate,
        "violations": tuple(violations),
        "passed": retention_rate == 1.0,
    }


def score_reopen_export_projection(
    fixture: Mapping[str, Any], exported_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    expected = _materialized_provenance(fixture)
    expected_ids = set(expected)
    exported_by_id: dict[str, Mapping[str, Any]] = {}
    duplicate_exports: list[str] = []
    for row in exported_rows:
        event_id = row.get("event_id")
        if event_id in exported_by_id:
            duplicate_exports.append(event_id)
            continue
        exported_by_id[event_id] = row
    exported_ids = set(exported_by_id)

    missing_ids = sorted(expected_ids - exported_ids)
    unexpected_ids = sorted(exported_ids - expected_ids)

    field_violations: list[dict[str, Any]] = []
    for event_id in sorted(expected_ids & exported_ids):
        expected_record = expected[event_id]
        exported_record = exported_by_id[event_id]
        for field, expected_value in expected_record.items():
            actual_value = exported_record.get(field, _SENTINEL_MISSING)
            mismatch = actual_value is _SENTINEL_MISSING or (
                canonical_json(actual_value) != canonical_json(expected_value)
            )
            if mismatch:
                field_violations.append({"event_id": event_id, "field": field})

    passed = not (
        missing_ids or unexpected_ids or duplicate_exports or field_violations
    )
    return {
        "metric": "M01-REOPEN-EXPORT-PROJECTION",
        "missing_event_ids": tuple(missing_ids),
        "unexpected_event_ids": tuple(unexpected_ids),
        "duplicate_exported_event_ids": tuple(sorted(duplicate_exports)),
        "field_violations": tuple(field_violations),
        "passed": passed,
    }


def canonical_replay_projection(
    receipts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project a capture-receipt payload to the closed M01 replay ABI.

    Allowlists exactly the semantic capture-receipt fields (`fixture_row_id`,
    `outcome`, `durability`, `error`) that must be byte-identical across five
    clean runs and one crash/restart replay, per
    `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
    Task 4 ("Canonical replay projection excludes runtime timestamps and host
    paths") and Task 9 (volatile-field exclusion list). It explicitly
    excludes only the volatile runtime field this pilot's receipt shape can
    carry -- `evidence_handle`, a runtime-generated per-attempt pointer, the
    M01 analogue of Task 9's "runtime-generated receipt IDs".

    Any field outside both sets is unrecognized and rejected fail-closed:
    hashing an arbitrary caller payload would let an unreviewed field either
    silently break reproducibility (if semantic) or silently mask a real
    divergence (if actually volatile but never declared so).
    """
    projected: list[dict[str, Any]] = []
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, Mapping):
            raise WmbsM01Error(f"canonical replay payload[{index}] must be a mapping")
        unknown = set(receipt) - _CANONICAL_REPLAY_KNOWN_FIELDS
        if unknown:
            raise WmbsM01Error(
                f"canonical replay payload[{index}] has unrecognized field(s): "
                f"{sorted(unknown)}"
            )
        projected.append(
            {field: receipt.get(field) for field in _CANONICAL_REPLAY_SEMANTIC_FIELDS}
        )
    return projected


def score_canonical_replay_equality(
    clean_run_payloads: Sequence[Sequence[Mapping[str, Any]]],
    restart_replay_payload: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(clean_run_payloads) < MIN_CLEAN_REPLAY_RUNS:
        raise WmbsM01Error(
            f"canonical replay equality requires at least {MIN_CLEAN_REPLAY_RUNS} clean runs, "
            f"got {len(clean_run_payloads)}"
        )
    clean_digests = tuple(
        canonical_sha256(canonical_replay_projection(payload))
        for payload in clean_run_payloads
    )
    restart_digest = canonical_sha256(
        canonical_replay_projection(restart_replay_payload)
    )
    unique_digests = set(clean_digests) | {restart_digest}
    return {
        "metric": "M01-CANONICAL-REPLAY-EQUALITY",
        "clean_run_digests": clean_digests,
        "restart_replay_digest": restart_digest,
        "unique_digest_count": len(unique_digests),
        "passed": len(unique_digests) == 1,
    }


def score_capture(
    fixture: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    exported_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate the four capture dimensions this pilot scores together.

    `exact_duplicate_materialization` is bound to `exported_rows` (the
    reopened/exported durable-state projection), not to `receipts` alone: a
    receipt claiming `deduplicated` is not proof of zero materialization.
    Provenance retention and canonical replay equality are scored
    separately because they take projection/replay inputs shaped
    differently from a single capture run's receipts plus export.
    """
    acknowledged_write_loss = score_acknowledged_write_loss(fixture, receipts)
    rejection_receipt_completeness = score_rejection_receipt_completeness(
        fixture, receipts
    )
    exact_duplicate_materialization = score_exact_duplicate_materialization(
        fixture, exported_rows
    )
    schema_outcome_accuracy = score_schema_outcome_accuracy(fixture, receipts)
    return {
        "acknowledged_write_loss": acknowledged_write_loss,
        "rejection_receipt_completeness": rejection_receipt_completeness,
        "exact_duplicate_materialization": exact_duplicate_materialization,
        "schema_outcome_accuracy": schema_outcome_accuracy,
        "passed": (
            acknowledged_write_loss["passed"]
            and rejection_receipt_completeness["passed"]
            and exact_duplicate_materialization["passed"]
            and schema_outcome_accuracy["passed"]
        ),
    }

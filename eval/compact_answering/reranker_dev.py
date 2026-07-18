"""Strict, model-free mirror of the compact-answering reranker bakeoff ABI."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ABI = "mnemosyne.compact-answering-reranker.v1"
ABI_SCHEMA = ABI
MAX_CANDIDATES = 20
MAX_RANK_WIDTH = 8
SELECTION_FIXTURE_SCHEMA = "mnemosyne.reranker-selection-fixture.v1"
BAKEOFF_RECEIPT_SCHEMA = "mnemosyne.reranker-bakeoff-receipt.v1"
SELECTION_FIXTURE_STATUS = "synthetic-unmeasured"
SELECTION_SPLIT = "TRAIN"
SELECTION_FIXTURE_PATH = (
    Path(__file__).with_name("fixtures") / "reranker-train-dev.json"
)
IDENTITY_FIELDS = frozenset(
    {
        "model_id",
        "artifact_id",
        "artifact_sha256",
        "preprocessing_id",
        "preprocessing_sha256",
    }
)
_DIGEST_HEX_LENGTH = 64
_UNMEASURED_RECEIPT_FIELDS = (
    "artifact_bytes",
    "quality",
    "latency_ms",
    "peak_memory_mib",
    "resource_envelope",
)


class RerankerValidationError(ValueError):
    """A reranker request, response, identity, or score is invalid."""


class RerankerSelectionValidationError(RerankerValidationError):
    """A synthetic TRAIN-only selection fixture or receipt is invalid."""


class RerankerTimeoutError(RerankerSelectionValidationError):
    """A bakeoff validation deadline expired before the result was admitted."""


@dataclass(frozen=True)
class RerankIdentity:
    """Model, artifact, and preprocessing identity bound to every score."""

    model_id: str
    artifact_id: str
    artifact_sha256: str
    preprocessing_id: str
    preprocessing_sha256: str

    @classmethod
    def from_mapping(cls, value: object) -> "RerankIdentity":
        if not isinstance(value, dict) or set(value) != IDENTITY_FIELDS:
            raise RerankerValidationError("identity fields must be exact")
        fields = {field: value[field] for field in IDENTITY_FIELDS}
        for field, item in fields.items():
            if not isinstance(item, str) or not item or item != item.strip():
                raise RerankerValidationError(
                    f"identity {field} must be an exact non-empty string"
                )
            if any(ord(character) < 32 or ord(character) == 127 for character in item):
                raise RerankerValidationError(f"identity {field} contains a control character")
        for field in ("artifact_sha256", "preprocessing_sha256"):
            if not _is_digest(fields[field]):
                raise RerankerValidationError(
                    f"identity {field} must be {_DIGEST_HEX_LENGTH} lowercase hex characters"
                )
        return cls(**fields)

    def as_mapping(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "artifact_id": self.artifact_id,
            "artifact_sha256": self.artifact_sha256,
            "preprocessing_id": self.preprocessing_id,
            "preprocessing_sha256": self.preprocessing_sha256,
        }

    def require_match(self, expected: "RerankIdentity") -> None:
        if self == expected:
            return
        for field in IDENTITY_FIELDS:
            if getattr(self, field) != getattr(expected, field):
                raise RerankerValidationError(f"identity mismatch: {field}")
        raise RerankerValidationError("identity mismatch")


@dataclass(frozen=True)
class RerankCandidate:
    evidence_id: str
    text: str

    @classmethod
    def from_mapping(cls, value: object) -> "RerankCandidate":
        if not isinstance(value, dict) or set(value) != {"evidence_id", "text"}:
            raise RerankerSelectionValidationError("candidate fields must be exact")
        evidence_id = value["evidence_id"]
        text = value["text"]
        if not _is_clean_string(evidence_id) or not _is_clean_string(text):
            raise RerankerSelectionValidationError(
                "candidate evidence_id and text must be exact strings"
            )
        return cls(evidence_id=evidence_id, text=text)


@dataclass(frozen=True)
class RerankScore:
    evidence_id: str
    score: float

    @classmethod
    def from_mapping(cls, value: object) -> "RerankScore":
        if not isinstance(value, dict) or set(value) != {"evidence_id", "score"}:
            raise RerankerSelectionValidationError("score fields must be exact")
        evidence_id = value["evidence_id"]
        score = value["score"]
        if not _is_clean_string(evidence_id):
            raise RerankerSelectionValidationError("score evidence_id must be an exact string")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise RerankerSelectionValidationError("score must be numeric")
        score = float(score)
        if not math.isfinite(score):
            raise RerankerSelectionValidationError("score must be finite")
        return cls(evidence_id=evidence_id, score=score)

    def as_mapping(self) -> dict[str, object]:
        return {"evidence_id": self.evidence_id, "score": self.score}


def _is_clean_string(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip() and not any(
        ord(character) < 32 or ord(character) == 127 for character in value
    )


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_HEX_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RerankerSelectionValidationError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> None:
    raise RerankerSelectionValidationError(f"unsupported JSON constant: {value}")


def _parse_json(payload: str | bytes | bytearray) -> object:
    if not isinstance(payload, (str, bytes, bytearray)):
        raise RerankerSelectionValidationError("payload must be JSON text or bytes")
    try:
        return json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RerankerSelectionValidationError("payload must be valid JSON") from exc


def _canonical_bytes(document: object) -> bytes:
    try:
        encoded = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RerankerSelectionValidationError("document is not canonical JSON") from exc
    return (encoded + "\n").encode("utf-8")


def _sha256(document: object) -> str:
    return hashlib.sha256(_canonical_bytes(document)).hexdigest()


def _without_field(document: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != field}


def identity_digest(identity: RerankIdentity | dict[str, object]) -> str:
    """Return the canonical digest for an exact reranker identity mapping."""
    parsed = identity if isinstance(identity, RerankIdentity) else RerankIdentity.from_mapping(identity)
    return _sha256(parsed.as_mapping())


def receipt_digest(receipt: dict[str, Any]) -> str:
    """Return the digest over a receipt excluding its self-authenticating field."""
    if not isinstance(receipt, dict):
        raise RerankerSelectionValidationError("receipt must be an object")
    return _sha256(_without_field(receipt, "receipt_sha256"))


def fixture_digest(fixture: dict[str, Any]) -> str:
    """Return the digest over a fixture excluding its self-authenticating field."""
    if not isinstance(fixture, dict):
        raise RerankerSelectionValidationError("fixture must be an object")
    return _sha256(_without_field(fixture, "fixture_sha256"))


def _selection_error(message: str) -> RerankerSelectionValidationError:
    return RerankerSelectionValidationError(message)


def _validate_exact_object(
    value: object, fields: set[str], *, label: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise _selection_error(f"{label} fields must be exact")
    return value


def _validate_rank_width(value: object, *, candidate_count: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _selection_error("rank_width must be an integer")
    if value < 1 or value > MAX_RANK_WIDTH:
        raise _selection_error("rank_width must be between 1 and 8")
    if candidate_count is not None and value > candidate_count:
        raise _selection_error("rank_width cannot exceed candidate count")
    return value


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise RerankerTimeoutError("reranker bakeoff validation timed out")


def validate_bakeoff_receipt(
    document: object,
    *,
    expected_candidate_id: str | None = None,
    expected_identity: RerankIdentity | None = None,
    expected_rank_width: int | None = None,
) -> dict[str, Any]:
    """Validate one self-digest, synthetic-only, TRAIN bakeoff receipt."""
    receipt = _validate_exact_object(
        document,
        {
            "schema",
            "candidate_id",
            "split",
            "identity",
            "identity_sha256",
            "artifact_custody",
            "status",
            "rank_width",
            "unmeasured",
            "receipt_sha256",
        },
        label="receipt",
    )
    if receipt["schema"] != BAKEOFF_RECEIPT_SCHEMA:
        raise _selection_error("unsupported bakeoff receipt schema")
    candidate_id = receipt["candidate_id"]
    if not _is_clean_string(candidate_id):
        raise _selection_error("receipt candidate_id must be an exact non-empty string")
    if expected_candidate_id is not None and candidate_id != expected_candidate_id:
        raise _selection_error("receipt candidate identity mismatch")
    if receipt["split"] != SELECTION_SPLIT:
        raise _selection_error("bakeoff receipt must be TRAIN-only")
    identity = RerankIdentity.from_mapping(receipt["identity"])
    if expected_identity is not None:
        identity.require_match(expected_identity)
    identity_hash = receipt["identity_sha256"]
    if not _is_digest(identity_hash) or identity_hash != identity_digest(identity):
        raise _selection_error("receipt identity digest mismatch")
    if receipt["artifact_custody"] != "synthetic-fixture-no-model-artifact":
        raise _selection_error("receipt artifact custody must be synthetic-only")
    if receipt["status"] != "unmeasured":
        raise _selection_error("synthetic receipt must remain unmeasured")
    rank_width = _validate_rank_width(receipt["rank_width"])
    if expected_rank_width is not None and rank_width != expected_rank_width:
        raise _selection_error("receipt rank width mismatch")
    if receipt["unmeasured"] != list(_UNMEASURED_RECEIPT_FIELDS):
        raise _selection_error("receipt must enumerate all unmeasured fields")
    digest = receipt["receipt_sha256"]
    if not _is_digest(digest) or digest != receipt_digest(receipt):
        raise _selection_error("receipt digest mismatch")
    return receipt


def rank_scores(
    candidates: list[RerankCandidate],
    scores: list[RerankScore],
    rank_width: int,
    *,
    deadline: float | None = None,
) -> list[RerankScore]:
    """Validate scores and return deterministic score-descending top-k rows."""
    _check_deadline(deadline)
    _validate_rank_width(rank_width, candidate_count=len(candidates))
    if not candidates or len(candidates) > MAX_CANDIDATES:
        raise _selection_error("candidate rows must be non-empty and bounded")
    if len(scores) != len(candidates):
        raise _selection_error("score row count must match candidate count")
    candidate_ids = [candidate.evidence_id for candidate in candidates]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise _selection_error("candidate evidence IDs must be unique")
    known_ids = set(candidate_ids)
    seen: set[str] = set()
    for row in scores:
        _check_deadline(deadline)
        if row.evidence_id in seen:
            raise _selection_error("score evidence IDs must be unique")
        if row.evidence_id not in known_ids:
            raise _selection_error("score evidence ID is unknown")
        if not math.isfinite(row.score):
            raise _selection_error("score must be finite")
        seen.add(row.evidence_id)
    if seen != known_ids:
        raise _selection_error("score rows must cover every candidate")
    return sorted(scores, key=lambda row: (-row.score, row.evidence_id))[:rank_width]


def _mean_score(scores: list[RerankScore]) -> float:
    if not scores:
        raise _selection_error("at least one score row is required")
    return math.fsum(row.score for row in scores) / len(scores)


def validate_selection_fixture(
    document: object,
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Validate source-owned synthetic receipts and deterministic selection."""
    _check_deadline(deadline)
    fixture = _validate_exact_object(
        document,
        {
            "schema",
            "split",
            "source",
            "fixture_status",
            "query",
            "candidates",
            "rank_width",
            "variants",
            "selection",
            "fixture_sha256",
        },
        label="selection fixture",
    )
    if fixture["schema"] != SELECTION_FIXTURE_SCHEMA:
        raise _selection_error("unsupported selection fixture schema")
    if fixture["split"] != SELECTION_SPLIT:
        raise _selection_error("reranker selection fixture must be TRAIN-only")
    if fixture["source"] != "source-owned":
        raise _selection_error("selection fixture source must be source-owned")
    if fixture["fixture_status"] != SELECTION_FIXTURE_STATUS:
        raise _selection_error("selection fixture must be explicitly unmeasured")
    if not _is_clean_string(fixture["query"]):
        raise _selection_error("selection query must be an exact non-empty string")
    candidates_value = fixture["candidates"]
    if not isinstance(candidates_value, list) or not candidates_value:
        raise _selection_error("selection fixture candidates must be non-empty")
    if len(candidates_value) > MAX_CANDIDATES:
        raise _selection_error("selection fixture candidates exceed the ABI limit")
    candidates = [RerankCandidate.from_mapping(candidate) for candidate in candidates_value]
    candidate_ids = [candidate.evidence_id for candidate in candidates]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise _selection_error("candidate evidence IDs must be unique")
    rank_width = _validate_rank_width(fixture["rank_width"], candidate_count=len(candidates))

    variants_value = fixture["variants"]
    if not isinstance(variants_value, list) or not variants_value:
        raise _selection_error("selection fixture variants must be non-empty")
    variant_ids: set[str] = set()
    variants: list[tuple[str, list[RerankScore], list[str]]] = []
    common_preprocessing: tuple[str, str] | None = None
    for variant_index, variant in enumerate(variants_value):
        _check_deadline(deadline)
        parsed_variant = _validate_exact_object(
            variant,
            {"id", "identity", "receipt", "scores", "expected_ranking"},
            label=f"variant {variant_index}",
        )
        variant_id = parsed_variant["id"]
        if not _is_clean_string(variant_id) or variant_id in variant_ids:
            raise _selection_error("variant IDs must be unique non-empty strings")
        variant_ids.add(variant_id)
        identity = RerankIdentity.from_mapping(parsed_variant["identity"])
        preprocessing = (identity.preprocessing_id, identity.preprocessing_sha256)
        if common_preprocessing is None:
            common_preprocessing = preprocessing
        elif preprocessing != common_preprocessing:
            raise _selection_error("variant preprocessing identity drift")
        validate_bakeoff_receipt(
            parsed_variant["receipt"],
            expected_candidate_id=variant_id,
            expected_identity=identity,
            expected_rank_width=rank_width,
        )
        scores_value = parsed_variant["scores"]
        if not isinstance(scores_value, list) or len(scores_value) != len(candidates):
            raise _selection_error(f"variant {variant_id} score rows are incomplete")
        scores = [RerankScore.from_mapping(score) for score in scores_value]
        ranked = rank_scores(candidates, scores, rank_width, deadline=deadline)
        expected_ranking = parsed_variant["expected_ranking"]
        if (
            not isinstance(expected_ranking, list)
            or expected_ranking != [row.evidence_id for row in ranked]
            or len(expected_ranking) != rank_width
        ):
            raise _selection_error(f"variant {variant_id} deterministic ranking mismatch")
        variants.append((variant_id, scores, expected_ranking))

    selection = _validate_exact_object(
        fixture["selection"],
        {"method", "expected_candidate_id"},
        label="selection",
    )
    if selection["method"] != "mean_score_then_id_v1":
        raise _selection_error("unsupported selection method")
    selected = min(
        variants,
        key=lambda item: (-_mean_score(item[1]), item[0]),
    )[0]
    if selection["expected_candidate_id"] != selected:
        raise _selection_error("selection result mismatch")
    fixture_digest_value = fixture["fixture_sha256"]
    if not _is_digest(fixture_digest_value) or fixture_digest_value != fixture_digest(fixture):
        raise _selection_error("selection fixture digest mismatch")
    return fixture


def parse_selection_fixture(payload: str | bytes | bytearray) -> dict[str, Any]:
    """Parse fixture JSON with duplicate-key and non-finite rejection."""
    return validate_selection_fixture(_parse_json(payload))


def load_selection_fixture(path: str | Path = SELECTION_FIXTURE_PATH) -> dict[str, Any]:
    """Load the source-owned selection fixture without accepting drift."""
    fixture_path = Path(path)
    try:
        payload = fixture_path.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise RerankerSelectionValidationError(
            f"cannot read selection fixture {fixture_path}"
        ) from exc
    return parse_selection_fixture(payload)


def run_synthetic_bakeoff(
    document: object,
    *,
    deadline: float | None = None,
    timeout_ms: float | None = None,
) -> str:
    """Return the deterministic dev-only candidate after full validation."""
    if timeout_ms is not None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, (int, float)):
            raise RerankerTimeoutError("timeout_ms must be a positive finite number")
        if not math.isfinite(float(timeout_ms)) or timeout_ms <= 0:
            raise RerankerTimeoutError("timeout_ms must be a positive finite number")
        deadline = min(deadline, time.monotonic() + timeout_ms / 1000) if deadline else time.monotonic() + timeout_ms / 1000
    fixture = validate_selection_fixture(document, deadline=deadline)
    return fixture["selection"]["expected_candidate_id"]


def select_synthetic_reranker(document: object, *, deadline: float | None = None) -> str:
    """Explicit alias for the model-free synthetic selector."""
    return run_synthetic_bakeoff(document, deadline=deadline)


def select_reranker(document: object) -> str:
    """Compatibility alias for the explicit synthetic selector."""
    return select_synthetic_reranker(document)


validate_receipt = validate_bakeoff_receipt

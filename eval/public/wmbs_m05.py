"""Standalone M05 provenance/explanation development core.

Stage A is deterministic, model-free, local, descriptive, and unregistered.
It scores one-hop claim-to-source grounding only. The following quarantines
remain hard integration dependencies: Q1 query_with_evidence is absent from
the frozen ABI; Q2 grounding is scorer-enforced; Q3 provenance_status is
self-declared and ignored; Q4 evidence handles are not digest-bound; Q7 replay
hashes need real artifact binding; Q9 grounded answering is model-backed;
Q10 HowProvenance is unwired; Q12 missing artifacts must fail, never skip.

No official, protected, publishable, result-v2, promoted-lineage, trajectory,
certification, comparative, or superiority claim is made here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

MODULE_ID = "M05"
FIXTURE_ID = "wmbs-m05-provenance-development"
FIXTURE_SCHEMA_ID = "wmbs-m05-provenance-development/fixture/0.1"
GENERATOR_ID = "wmbs-m05-deterministic-generator"
GENERATOR_VERSION = "1.0.0"
SEEDS = (13, 29, 41, 59, 73)
PROTECTED_SLICE_ID = "protected-grounding"
SLICE_IDS = (
    PROTECTED_SLICE_ID,
    "distractor-sources",
    "tampered-lineage",
    "unsupported-claim",
    "derived-claims",
)

FINITE_CORPUS_DISCLOSURE = (
    "These descriptive metrics apply only to the exact finite synthetic "
    "development corpus scored; they are not benchmark results or population "
    "claims."
)
INTEGRATION_DEPENDENCIES = (
    "Q1 query_with_evidence is absent from the frozen ABI.",
    "Q2 grounding is scorer-enforced, not schema-proven.",
    "Q3 provenance_status is self-declared and ignored.",
    "Q4 evidence handles are not digest-bound by the ABI.",
    "Q7 replay hashes require binding to real artifacts.",
    "Q9 grounded answering requires model-backed commands.",
    "Q10 HowProvenance is unwired; derived claims are unscored.",
    "Q12 missing artifacts fail rather than skip.",
)

_LABELS = {
    "admission_state": "PROPOSED",
    "comparability": "proposed-non-comparable",
    "headline_eligible": False,
    "independent_reproduction": False,
    "module_id": MODULE_ID,
    "pbpp_headline_eligible": False,
    "publishable": False,
    "track": "DEVELOPMENT",
    "upstream_comparable": False,
}
_CAPTURE = {
    "tenant_id": "tenant-m05-development",
    "user_id": "user-m05-development",
    "source_type": "synthetic-portable-event",
    "modality": "text",
    "sensitivity": 2,
}


class WmbsM05Error(ValueError):
    """The fixture or trace violated the closed M05 Stage-A contract."""


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _evidence_cid(content: str, content_pointer: str) -> str:
    metadata = {
        "tenant_id": _CAPTURE["tenant_id"],
        "source_type": _CAPTURE["source_type"],
        "content_pointer": content_pointer,
        "modality": _CAPTURE["modality"],
        "subject_scope": "user",
        "user_id": _CAPTURE["user_id"],
    }
    payload = json.dumps(
        {"content": content, "metadata": metadata},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _event(
    seed: int, slice_id: str, index: int, *, distractor: bool = False
) -> dict[str, Any]:
    event_id = f"m05-{seed}-{slice_id}-{index}-{'d' if distractor else 's'}"
    content = (
        f"Distractor {index} for seed {seed}."
        if distractor
        else f"Source {index} supports claim {index} for seed {seed}."
    )
    return {
        "event_id": event_id,
        "content": content,
        "actor_label": "synthetic-generator",
        "event_time": f"2026-07-20T00:{index:02d}:00Z",
        "ingestion_time": f"2026-07-20T00:{index:02d}:05Z",
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "public_metadata": {
            **_CAPTURE,
            "content_pointer": event_id,
        },
    }


def _case(seed: int, slice_id: str, index: int) -> dict[str, Any]:
    source = _event(seed, slice_id, index)
    source_cid = _evidence_cid(source["content"], source["event_id"])
    sources = [source]
    gold = [source_cid]
    scored = slice_id != "derived-claims"
    expected = "grounded"
    if slice_id == "distractor-sources":
        sources.append(_event(seed, slice_id, index, distractor=True))
    elif slice_id == "tampered-lineage":
        source["content"] += " tampered"
        source["content_sha256"] = hashlib.sha256(
            source["content"].encode()
        ).hexdigest()
        expected = "tamper-rejected"
    elif slice_id == "unsupported-claim":
        gold = []
        expected = "abstain"
    elif slice_id == "derived-claims":
        expected = "deferred"
    case = {
        "case_id": f"m05-{seed}-{slice_id}-{index}",
        "claim": f"Claim {index} for seed {seed}.",
        "source_events": sources,
        "gold_source_cids": gold,
        "expected": expected,
        "scored": scored,
        "sensitivity": 2,
    }
    if not scored:
        case["deferral_reason"] = "howprovenance-unwired"
    return case


def generate_fixture(seed: int = SEEDS[0]) -> dict[str, Any]:
    """Generate the fixed five-seed, 100-case corpus without I/O or clocks."""
    if seed not in SEEDS:
        raise WmbsM05Error(f"seed must be one of {SEEDS}")
    slices = []
    for slice_id in SLICE_IDS:
        slices.append(
            {
                "slice_id": slice_id,
                "scored": slice_id != "derived-claims",
                "deferral_reason": (
                    "howprovenance-unwired" if slice_id == "derived-claims" else None
                ),
                "cases": [
                    _case(matrix_seed, slice_id, index)
                    for matrix_seed in SEEDS
                    for index in range(4)
                ],
            }
        )
    fixture = {
        **_LABELS,
        "fixture_id": FIXTURE_ID,
        "schema_id": FIXTURE_SCHEMA_ID,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "integration_dependencies": list(INTEGRATION_DEPENDENCIES),
        "disclosure": FINITE_CORPUS_DISCLOSURE,
        "license": "CC0-1.0",
        "seeds": list(SEEDS),
        "sensitivity_binding": {
            "protected_slice_sensitivity": 2,
            "reason": "Q8",
        },
        "slices": slices,
        "source_manifest": {
            "signed": False,
            "reason": "signing deferred behind the protected lease",
        },
    }
    fixture["dataset_sha256"] = canonical_sha256(fixture)
    return fixture


def validate_fixture(fixture: Mapping[str, Any]) -> Mapping[str, Any]:
    for key, expected in _LABELS.items():
        if fixture.get(key) != expected:
            raise WmbsM05Error(f"fixture label {key} must equal {expected!r}")
    if (
        fixture.get("fixture_id") != FIXTURE_ID
        or fixture.get("schema_id") != FIXTURE_SCHEMA_ID
    ):
        raise WmbsM05Error("fixture identity mismatch")
    if fixture.get("integration_dependencies") != list(INTEGRATION_DEPENDENCIES):
        raise WmbsM05Error("fixture integration dependencies mismatch")
    if fixture.get("disclosure") != FINITE_CORPUS_DISCLOSURE:
        raise WmbsM05Error("fixture disclosure mismatch")
    slices = fixture.get("slices")
    if (
        not isinstance(slices, list)
        or tuple(s.get("slice_id") for s in slices) != SLICE_IDS
    ):
        raise WmbsM05Error("fixture slice matrix mismatch")
    if any(len(s.get("cases", [])) != 20 for s in slices):
        raise WmbsM05Error("each slice must contain twenty cases")
    binding = fixture.get("sensitivity_binding")
    if binding != {"protected_slice_sensitivity": 2, "reason": "Q8"}:
        raise WmbsM05Error("protected source sensitivity binding is missing")
    for slice_ in slices:
        for case in slice_["cases"]:
            if case.get("sensitivity") != 2:
                raise WmbsM05Error("every case must retain sensitivity tier 2")
            if slice_["slice_id"] == "derived-claims" and (
                case.get("scored") is not False
                or case.get("deferral_reason") != "howprovenance-unwired"
            ):
                raise WmbsM05Error("derived claims must remain explicitly deferred")
            for event in case.get("source_events", []):
                required = {
                    "event_id",
                    "content",
                    "actor_label",
                    "event_time",
                    "ingestion_time",
                    "content_sha256",
                    "public_metadata",
                }
                if set(event) != required:
                    raise WmbsM05Error(
                        "portable_event must carry exactly seven required keys"
                    )
            if slice_["slice_id"] != "tampered-lineage":
                actual = {
                    _evidence_cid(event["content"], event["event_id"])
                    for event in case.get("source_events", [])
                }
                if not set(case.get("gold_source_cids", [])).issubset(actual):
                    raise WmbsM05Error(
                        "gold evidence handle must bind to this case's source content"
                    )
    check = dict(fixture)
    digest = check.pop("dataset_sha256", None)
    if digest != canonical_sha256(check):
        raise WmbsM05Error("dataset_sha256 mismatch")
    return fixture


def recompute_source_cids(fixture: Mapping[str, Any]) -> dict[str, str]:
    validate_fixture(fixture)
    result = {}
    for slice_ in fixture["slices"]:
        for case in slice_["cases"]:
            for event in case["source_events"]:
                result[event["event_id"]] = _evidence_cid(
                    event["content"], event["event_id"]
                )
    return result


def source_manifest(fixture: Mapping[str, Any]) -> dict[str, Any]:
    cids = recompute_source_cids(fixture)
    return {
        "signed": False,
        "fixture_sha256": canonical_sha256(fixture),
        "source_cids_sha256": canonical_sha256(sorted(cids.items())),
        "source_count": len(cids),
    }


def _trace_map(traces: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result = {}
    for trace in traces:
        case_id = trace.get("case_id")
        if not isinstance(case_id, str) or case_id in result:
            raise WmbsM05Error("trace case_id must be unique and nonempty")
        envelope = trace.get("answer_envelope")
        if not isinstance(envelope, Mapping):
            raise WmbsM05Error("trace answer_envelope must be an object")
        for key in (
            "abstained",
            "evidence_handles",
            "action_handles",
            "adapter_metadata",
        ):
            if key not in envelope:
                raise WmbsM05Error(f"answer_envelope missing {key}")
        if envelope["abstained"] and envelope["evidence_handles"]:
            raise WmbsM05Error("abstained envelopes cannot carry evidence handles")
        result[case_id] = trace
    return result


def score(
    fixture: Mapping[str, Any], traces: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    validate_fixture(fixture)
    by_id = _trace_map(traces)
    known_case_ids = {
        case["case_id"]
        for slice_ in fixture["slices"]
        for case in slice_["cases"]
        if case["scored"]
    }
    unknown_case_ids = set(by_id) - known_case_ids
    if unknown_case_ids:
        raise WmbsM05Error(
            f"trace case_id is absent from fixture: {sorted(unknown_case_ids)}"
        )
    provenance_ok = explanation_ok = protected_count = unsupported = (
        unsupported_total
    ) = 0
    tamper_rejected = tamper_total = 0
    true_positive = cited_total = gold_total = 0

    for slice_ in fixture["slices"]:
        slice_id = slice_["slice_id"]
        for case in slice_["cases"]:
            if not case["scored"]:
                continue
            if slice_id == PROTECTED_SLICE_ID:
                protected_count += 1
                unsupported_total += 1
            elif slice_id == "distractor-sources":
                gold_total += len(case["gold_source_cids"])
            elif slice_id == "tampered-lineage":
                tamper_total += 1
            elif slice_id == "unsupported-claim":
                unsupported_total += 1
            trace = by_id.get(case["case_id"])
            if trace is None:
                if slice_id == "unsupported-claim":
                    unsupported += 1
                continue
            envelope = trace["answer_envelope"]
            cited = set(envelope["evidence_handles"])
            explained = set(
                trace.get("explanation", {}).get("source_evidence_cids", [])
            )
            gold = set(case["gold_source_cids"])
            actual = {
                _evidence_cid(event["content"], event["event_id"])
                for event in case["source_events"]
            }
            valid_gold = gold & actual
            if slice_id == PROTECTED_SLICE_ID:
                provenance_ok += cited == gold and bool(valid_gold)
                explanation_ok += explained == gold and bool(valid_gold)
                unsupported += not envelope["abstained"] and not bool(
                    cited & valid_gold
                )
            elif slice_id == "distractor-sources":
                true_positive += len(cited & gold)
                cited_total += len(cited)
            elif slice_id == "tampered-lineage":
                tamper_rejected += (
                    bool(gold) and not bool(valid_gold) and envelope["abstained"]
                )
            elif slice_id == "unsupported-claim":
                unsupported += not envelope["abstained"] and not bool(
                    cited & valid_gold
                )

    metrics = {
        "M-PROV-COMPLETE": provenance_ok / protected_count if protected_count else 0.0,
        "M-EXPLAIN-COV": explanation_ok / protected_count if protected_count else 0.0,
        "unsupported_claim_rate": unsupported / unsupported_total
        if unsupported_total
        else 0.0,
        "lineage_tamper_rejection": tamper_rejected / tamper_total
        if tamper_total
        else 0.0,
        "citation_precision": true_positive / cited_total if cited_total else 0.0,
        "citation_recall": true_positive / gold_total if gold_total else 0.0,
        "five_seed_canonical_replay": float(
            all(
                canonical_json(generate_fixture(seed))
                == canonical_json(generate_fixture(seed))
                for seed in SEEDS
            )
        ),
    }
    passed = (
        metrics["M-PROV-COMPLETE"] == 1.0
        and metrics["M-EXPLAIN-COV"] == 1.0
        and metrics["unsupported_claim_rate"] == 0.0
        and metrics["lineage_tamper_rejection"] == 1.0
    )
    return {
        "metrics": metrics,
        "diagnostics": {"trace_count": len(by_id), "case_count": 100},
        "deferred": {
            "explanation_faithfulness": "model-backed objective scorer required",
            "derived_claim_lineage": "howprovenance-unwired",
            "promoted_item_slice": "trajectory-lineage prerequisite remains open",
            "query_with_evidence": "unsupported until frozen in the ABI",
        },
        "passed": passed,
        "profile": "wmbs-m05-v1",
        "disclosure": FINITE_CORPUS_DISCLOSURE,
    }

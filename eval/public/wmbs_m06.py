"""Stdlib oracle for the WMBS M06 Stage A development cell.

The cell scores synthetic repeated, corroborated, contradictory, procedural,
related-transfer, and unrelated-control episodes through universal ingest,
retrieve, and answer. It reports descriptive finite-corpus observations only.
Publication stays closed. No private consolidation control is available, so
the universal no-memory control is substituted and that substitution is
disclosed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Literal, Never

MODULE_ID = "M06"
FIXTURE_ID = "wmbs-m06-consolidation-development"
GENERATOR_ID = "wmbs-m06-deterministic-generator"
GENERATOR_VERSION = "1.0.0"
SEEDS = (17, 31, 43, 61, 79)
DEFAULT_SEED = SEEDS[0]
FAMILIES = (
    "repeated",
    "corroborated",
    "contradictory",
    "procedural",
    "related-transfer",
    "unrelated-control",
)
CYCLES_PER_CASE = 5
PUBLIC_OPERATIONS = ("ingest", "retrieve", "answer")

FINITE_CORPUS_DISCLOSURE = (
    "These descriptive metrics apply only to the exact finite synthetic "
    "development corpus scored; they are not benchmark results, population "
    "claims, or spec CI-LCB acceptance."
)
NO_MEMORY_ABLATION_DISCLOSURE = (
    "A public no-consolidation control cannot be exercised through universal "
    "ingest, retrieve, and answer. The universal no-memory control is "
    "substituted and the missing ablation is disclosed."
)
PROVIDER_COST_REASON = (
    "unsupported: this cell admits no provider budget; missing provider spend "
    "is unsupported, not a billed zero"
)

FamilyName = Literal[
    "repeated",
    "corroborated",
    "contradictory",
    "procedural",
    "related-transfer",
    "unrelated-control",
]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EVENT_KEYS = (
    "event_id",
    "content",
    "actor_label",
    "event_time",
    "ingestion_time",
    "content_sha256",
    "public_metadata",
)
_REJECTED_FIELDS = frozenset(
    {
        "consolidation_hook",
        "private_consolidation",
        "private_no_consolidation_control",
        "privileged_signal",
        "privileged_internal_signal",
        "baseline_improvement",
        "non_inferiority",
        "ci_lcb",
        "spec_ci_lcb_accepted",
    }
)
_CUSTODY_FIELDS = frozenset({"custody", "split", "suite", "data_class"})
_CUSTODY_VALUES = frozenset({"protected", "private", "held-out", "official"})
_PUBLICATION_FLAGS = (
    "publishable",
    "headline_eligible",
    "pbpp_headline_eligible",
)


class WmbsM06Error(ValueError):
    """The fixture or observations violated the M06 Stage A contract."""


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


def _family_cycle(
    family: FamilyName, cycle: int
) -> tuple[tuple[str, ...], str, str, str | None, bool]:
    match family:
        case "repeated":
            return (("restatement",), "repeated-fact", "abstain", None, False)
        case "corroborated":
            return (
                ("witness-a", "witness-b"),
                "corroborated-fact",
                "abstain",
                None,
                False,
            )
        case "contradictory":
            if cycle < 2:
                return (("statement",), "fact-v1", "abstain", None, False)
            return (
                ("statement", "correction"),
                "fact-v2",
                "abstain",
                "fact-v1",
                False,
            )
        case "procedural":
            return (
                ("step",),
                f"procedure-step-{cycle + 1}",
                "abstain",
                None,
                False,
            )
        case "related-transfer":
            if cycle == 0:
                return (("source",), "source-fact", "abstain", None, False)
            return (("related",), "transferred-fact", "abstain", None, True)
        case "unrelated-control":
            return (
                ("control",),
                "unrelated-fact",
                "unrelated-fact",
                "consolidated-intrusion",
                False,
            )
        case _:
            unexpected: Never = family
            raise WmbsM06Error(f"unknown family {unexpected}")


def _event(
    *,
    seed: int,
    family: str,
    cycle: int,
    index: int,
    role: str,
    generator_seed: int,
) -> dict[str, Any]:
    content = (
        f"M06 synthetic development episode. family={family} seed={seed:02d} "
        f"cycle={cycle} event={index} generation={generator_seed:02d} "
        f"role={role}."
    )
    return {
        "event_id": f"m06-{seed}-{family}-c{cycle}-e{index}",
        "content": content,
        "actor_label": "synthetic-generator",
        "event_time": f"2026-07-20T00:{cycle:02d}:00Z",
        "ingestion_time": f"2026-07-20T00:{cycle:02d}:05Z",
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "public_metadata": {"source": GENERATOR_ID},
    }


def _cycle_record(
    *,
    seed: int,
    family: FamilyName,
    cycle: int,
    generator_seed: int,
) -> dict[str, Any]:
    roles, gold, no_memory, harmful, transfer = _family_cycle(family, cycle)
    stamp = f"2026-07-20T00:{cycle:02d}:10Z"
    answer_stamp = f"2026-07-20T00:{cycle:02d}:20Z"
    return {
        "cycle": cycle,
        "operations": list(PUBLIC_OPERATIONS),
        "events": [
            _event(
                seed=seed,
                family=family,
                cycle=cycle,
                index=index,
                role=role,
                generator_seed=generator_seed,
            )
            for index, role in enumerate(roles)
        ],
        "retrieve": {
            "query": f"retrieve {family} cycle {cycle} seed {seed}",
            "observation_time": stamp,
            "top_k": 1,
        },
        "answer": {
            "question": f"answer {family} cycle {cycle} seed {seed}",
            "observation_time": answer_stamp,
            "response_mode": "normal",
        },
        "gold_answer": gold,
        "no_memory_answer": no_memory,
        "harmful_answer": harmful,
        "transfer_cycle": transfer,
    }


def generate_fixture(seed: int = DEFAULT_SEED) -> dict[str, Any]:
    """Return the deterministic six-family development fixture for one seed."""
    if isinstance(seed, bool) or seed not in SEEDS:
        raise WmbsM06Error(f"seed must be one of {SEEDS}")
    fixture: dict[str, Any] = {
        "module_id": MODULE_ID,
        "fixture_id": FIXTURE_ID,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "generator_seed": seed,
        "admission_state": "PROPOSED",
        "disposition": "PROPOSED",
        "track": "DEVELOPMENT",
        "publishable": False,
        "headline_eligible": False,
        "pbpp_headline_eligible": False,
        "upstream_comparable": False,
        "comparability": "proposed-non-comparable",
        "independent_reproduction": False,
        "official_memory_agent_bench": "DEFERRED",
        "official_evomembench": "DEFERRED",
        "spec_ci_lcb_acceptance": "DEFERRED",
        "families": list(FAMILIES),
        "seeds": list(SEEDS),
        "cycles_per_case": CYCLES_PER_CASE,
        "public_operations": list(PUBLIC_OPERATIONS),
        "disclosure": FINITE_CORPUS_DISCLOSURE,
        "ablation_disclosure": NO_MEMORY_ABLATION_DISCLOSURE,
        "cases": [
            {
                "case_id": f"m06-{matrix_seed}-{family}",
                "seed": matrix_seed,
                "family": family,
                "cycles": [
                    _cycle_record(
                        seed=matrix_seed,
                        family=family,
                        cycle=cycle,
                        generator_seed=seed,
                    )
                    for cycle in range(CYCLES_PER_CASE)
                ],
            }
            for family in FAMILIES
            for matrix_seed in SEEDS
        ],
    }
    fixture["dataset_sha256"] = canonical_sha256(fixture)
    validate_fixture(fixture)
    return fixture


def _forbid_text(text: str) -> bool:
    folded = text.casefold()
    if "memoryagentbench" in folded or "evomembench" in folded:
        return True
    if "held-out" in folded or "held_out" in folded:
        return True
    if "protected-bytes" in folded or "private-bytes" in folded:
        return True
    return "official-upstream" in folded


def _walk(value: object) -> None:
    if isinstance(value, str):
        if _forbid_text(value):
            raise WmbsM06Error("forbidden bytes in development cell")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in _REJECTED_FIELDS:
                raise WmbsM06Error(f"rejected field {key}")
            if (
                key in _CUSTODY_FIELDS
                and isinstance(child, str)
                and child.casefold() in _CUSTODY_VALUES
            ):
                raise WmbsM06Error(f"forbidden bytes in {key}")
            if key in {"headline", "PILOT-READY-DEV", "pilot_ready_dev"}:
                raise WmbsM06Error(f"publication flag {key} is not admitted")
            _walk(child)
        return
    if isinstance(value, list):
        for child in value:
            _walk(child)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WmbsM06Error(f"{label} must be an object")
    return value


def _check_publication(document: Mapping[str, Any]) -> None:
    for flag in _PUBLICATION_FLAGS:
        if document.get(flag) is not False:
            raise WmbsM06Error(f"publication flag {flag} must stay false")
    if document.get("admission_state") != "PROPOSED":
        raise WmbsM06Error("publication admission_state must stay PROPOSED")
    if document.get("disposition") != "PROPOSED":
        raise WmbsM06Error("publication disposition must stay PROPOSED")
    if document.get("track") != "DEVELOPMENT":
        raise WmbsM06Error("publication track must stay DEVELOPMENT")
    if document.get("spec_ci_lcb_acceptance") != "DEFERRED":
        raise WmbsM06Error("spec CI-LCB acceptance stays DEFERRED")


def _check_event(event: object) -> Mapping[str, Any]:
    event = _require_mapping(event, "portable_event")
    if set(event) != set(_EVENT_KEYS):
        raise WmbsM06Error("portable_event keys are closed by the ABI")
    event_id = event["event_id"]
    content = event["content"]
    if (
        not isinstance(event_id, str)
        or not _IDENTIFIER_RE.fullmatch(event_id)
        or not 1 <= len(event_id) <= 128
    ):
        raise WmbsM06Error("portable_event event_id is not an identifier")
    if not isinstance(content, str) or not content.strip() or len(content) > 65536:
        raise WmbsM06Error("portable_event content is empty or too large")
    actor = event["actor_label"]
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 256:
        raise WmbsM06Error("portable_event actor_label is invalid")
    for field in ("event_time", "ingestion_time"):
        stamp = event[field]
        if not isinstance(stamp, str) or not _TIMESTAMP_RE.fullmatch(stamp):
            raise WmbsM06Error(f"portable_event {field} is invalid")
    digest = event["content_sha256"]
    expected = hashlib.sha256(content.encode()).hexdigest()
    if (
        not isinstance(digest, str)
        or not _SHA256_RE.fullmatch(digest)
        or digest != expected
    ):
        raise WmbsM06Error("portable_event content_sha256 mismatch")
    metadata = event["public_metadata"]
    if metadata != {"source": GENERATOR_ID}:
        raise WmbsM06Error("portable_event public_metadata mismatch")
    return event


def validate_fixture(fixture: object) -> Mapping[str, Any]:
    document = _require_mapping(fixture, "fixture")
    _walk(document)
    _check_publication(document)
    without_digest = {
        key: value for key, value in document.items() if key != "dataset_sha256"
    }
    if document.get("dataset_sha256") != canonical_sha256(without_digest):
        raise WmbsM06Error("dataset_sha256 mismatch")
    if document.get("families") != list(FAMILIES):
        raise WmbsM06Error("fixture families mismatch")
    if document.get("seeds") != list(SEEDS):
        raise WmbsM06Error("fixture seeds mismatch")
    if document.get("cycles_per_case") != CYCLES_PER_CASE:
        raise WmbsM06Error("fixture cycles_per_case mismatch")
    if document.get("fixture_id") != FIXTURE_ID:
        raise WmbsM06Error("fixture identity mismatch")
    if document.get("generator_seed") not in SEEDS:
        raise WmbsM06Error("fixture generator_seed mismatch")
    cases = document.get("cases")
    if not isinstance(cases, list):
        raise WmbsM06Error("fixture cases mismatch")
    expected = [
        (family, matrix_seed) for family in FAMILIES for matrix_seed in SEEDS
    ]
    if len(cases) != len(expected):
        raise WmbsM06Error("fixture case identity matrix mismatch")
    for case, (family, matrix_seed) in zip(cases, expected, strict=True):
        case = _require_mapping(case, "case")
        if (
            case.get("family") != family
            or case.get("seed") != matrix_seed
            or case.get("case_id") != f"m06-{matrix_seed}-{family}"
        ):
            raise WmbsM06Error("fixture case identity matrix mismatch")
        cycles = case.get("cycles")
        if not isinstance(cycles, list) or len(cycles) != CYCLES_PER_CASE:
            raise WmbsM06Error("each case must contain five cycles")
        for index, cycle in enumerate(cycles):
            cycle = _require_mapping(cycle, "cycle")
            if cycle.get("cycle") != index:
                raise WmbsM06Error("cycle index mismatch")
            if cycle.get("operations") != list(PUBLIC_OPERATIONS):
                raise WmbsM06Error(
                    "cycles must use universal ingest, retrieve, and answer"
                )
            events = cycle.get("events")
            if not isinstance(events, list) or not events:
                raise WmbsM06Error("portable_event list is empty")
            for event in events:
                _check_event(event)
    return document


def _validate_observations(
    fixture: Mapping[str, Any], observations: object
) -> list[Mapping[str, Any]]:
    document = _require_mapping(observations, "observations")
    _walk(document)
    if "control" in document and document["control"] != "no-memory":
        raise WmbsM06Error(
            "public no-consolidation control is unavailable; only the "
            "universal no-memory control is admitted"
        )
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list):
        raise WmbsM06Error("missing scored case_id")
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in raw_cases:
        item = _require_mapping(item, "observation case")
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or case_id in by_id:
            raise WmbsM06Error("missing scored case_id")
        by_id[case_id] = item
    expected_ids = [case["case_id"] for case in fixture["cases"]]
    if set(by_id) != set(expected_ids):
        raise WmbsM06Error("missing scored case_id")
    ordered: list[Mapping[str, Any]] = []
    for case in fixture["cases"]:
        observed = by_id[case["case_id"]]
        cycles = observed.get("cycles")
        if not isinstance(cycles, list) or len(cycles) != CYCLES_PER_CASE:
            raise WmbsM06Error("missing scored case_id")
        checked: list[Mapping[str, Any]] = []
        for cycle in cycles:
            cycle = _require_mapping(cycle, "observation cycle")
            if cycle.get("operations") != list(PUBLIC_OPERATIONS):
                raise WmbsM06Error(
                    "observations must use universal ingest, retrieve, and answer"
                )
            answer = cycle.get("answer_text")
            if not isinstance(answer, str):
                raise WmbsM06Error("answer_text must be a string")
            checked.append(cycle)
        ordered.append({"case_id": case["case_id"], "cycles": checked})
    return ordered


def score(fixture: object, observations: object) -> dict[str, Any]:
    """Score public answers against the fixture's no-memory control."""
    document = validate_fixture(fixture)
    observed = _validate_observations(document, observations)
    deltas: list[float] = []
    harmful = 0
    total_cycles = 0
    compounding = 0
    compound_slots = 0
    transfer_hits = 0
    transfer_slots = 0
    for case, observation in zip(document["cases"], observed, strict=True):
        correct = 0
        no_memory_correct = 0
        previous_wrong = False
        for cycle, answer_cycle in zip(
            case["cycles"], observation["cycles"], strict=True
        ):
            total_cycles += 1
            answer = answer_cycle["answer_text"]
            wrong = answer != cycle["gold_answer"]
            if not wrong:
                correct += 1
            if cycle["no_memory_answer"] == cycle["gold_answer"]:
                no_memory_correct += 1
            harmful_answer = cycle["harmful_answer"]
            if harmful_answer is not None and answer == harmful_answer:
                harmful += 1
            if cycle["cycle"] >= 1:
                compound_slots += 1
                if wrong and previous_wrong:
                    compounding += 1
            if cycle["transfer_cycle"]:
                transfer_slots += 1
                if not wrong:
                    transfer_hits += 1
            previous_wrong = wrong
        deltas.append(
            (correct / CYCLES_PER_CASE) - (no_memory_correct / CYCLES_PER_CASE)
        )
    event_count = 0
    content_bytes = 0
    for case in document["cases"]:
        for cycle in case["cycles"]:
            for event in cycle["events"]:
                event_count += 1
                content_bytes += len(event["content"].encode("utf-8"))
    return {
        "module_id": MODULE_ID,
        "admission_state": "PROPOSED",
        "disposition": "PROPOSED",
        "publishable": False,
        "headline_eligible": False,
        "pbpp_headline_eligible": False,
        "track": "DEVELOPMENT",
        "upstream_comparable": False,
        "comparability": "proposed-non-comparable",
        "independent_reproduction": False,
        "official_memory_agent_bench": "DEFERRED",
        "official_evomembench": "DEFERRED",
        "spec_ci_lcb_acceptance": "DEFERRED",
        "disclosure": FINITE_CORPUS_DISCLOSURE,
        "ablation_disclosure": NO_MEMORY_ABLATION_DISCLOSURE,
        "control": "no-memory",
        "public_operations": list(PUBLIC_OPERATIONS),
        "metrics": {
            "utility_delta": sum(deltas) / len(deltas),
            "harmful_promotion": harmful / total_cycles,
            "compounding_error_rate": (
                compounding / compound_slots if compound_slots else 0.0
            ),
            "cross_episode_transfer": (
                transfer_hits / transfer_slots if transfer_slots else 0.0
            ),
            "storage": {
                "event_count": event_count,
                "content_bytes": content_bytes,
            },
            "cost": {
                "provider_spend": "unsupported",
                "reason": PROVIDER_COST_REASON,
            },
            "latency": "unsupported",
            "tokens": "unsupported",
            "calls": "unsupported",
        },
        "interval": {
            "scope": "finite-corpus",
            "statistic": "utility_delta",
            "minimum": min(deltas),
            "maximum": max(deltas),
            "count": len(deltas),
        },
    }

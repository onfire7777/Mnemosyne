"""Contract tests for the WMBS M06 Stage A development cell.

The cell is a deterministic local fixture plus a stdlib oracle. It is not a
publishable result, a spec CI-LCB acceptance verdict, or a private
consolidation hook.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    REPO_ROOT / "eval/public/fixtures/wmbs-m06-consolidation-development.json"
)
SCHEMA_PATH = REPO_ROOT / "eval/public/schema/wmbs-0.1-draft.schema.json"
MODULE_PATH = REPO_ROOT / "eval/public/wmbs_m06.py"

PORTABLE_EVENT_KEYS = (
    "event_id",
    "content",
    "actor_label",
    "event_time",
    "ingestion_time",
    "content_sha256",
    "public_metadata",
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STDLIB_IMPORT_ROOTS = frozenset(
    {"__future__", "hashlib", "json", "re", "collections", "typing"}
)
_FORBIDDEN_IMPORT_MARKERS = ("mnemosyne", "consolidation", "surprise")


def _module():
    spec = importlib.util.find_spec("eval.public.wmbs_m06")
    assert spec is not None, "M06 module must exist"
    return importlib.import_module("eval.public.wmbs_m06")


def _rehash(m06, fixture) -> None:
    payload = dict(fixture)
    payload.pop("dataset_sha256", None)
    fixture["dataset_sha256"] = m06.canonical_sha256(payload)


def _gold_observations(fixture):
    return {
        "cases": [
            {
                "case_id": case["case_id"],
                "cycles": [
                    {
                        "operations": ["ingest", "retrieve", "answer"],
                        "answer_text": cycle["gold_answer"],
                    }
                    for cycle in case["cycles"]
                ],
            }
            for case in fixture["cases"]
        ]
    }


def _with_answer(fixture, family: str, seed: int, cycle: int, answer: str):
    observations = _gold_observations(fixture)
    case_id = f"m06-{seed}-{family}"
    for case in observations["cases"]:
        if case["case_id"] == case_id:
            case["cycles"][cycle]["answer_text"] = answer
            return observations
    raise AssertionError(f"missing {case_id}")


def _events(fixture):
    for case in fixture["cases"]:
        for cycle in case["cycles"]:
            for event in cycle["events"]:
                yield case, cycle, event


def test_three_stage_a_paths_are_the_cell_under_test() -> None:
    assert MODULE_PATH.name == "wmbs_m06.py"
    assert FIXTURE_PATH.name == "wmbs-m06-consolidation-development.json"
    m06 = _module()
    assert m06.FIXTURE_ID == "wmbs-m06-consolidation-development"


def test_fixture_covers_six_families_five_cycles_and_at_least_five_seeds() -> None:
    m06 = _module()
    assert m06.FAMILIES == (
        "repeated",
        "corroborated",
        "contradictory",
        "procedural",
        "related-transfer",
        "unrelated-control",
    )
    assert m06.CYCLES_PER_CASE == 5
    assert len(m06.SEEDS) >= 5
    assert m06.SEEDS == (17, 31, 43, 61, 79)
    fixture = m06.generate_fixture(m06.SEEDS[0])
    assert fixture["families"] == list(m06.FAMILIES)
    assert fixture["seeds"] == list(m06.SEEDS)
    assert fixture["cycles_per_case"] == 5
    assert len(fixture["cases"]) == len(m06.FAMILIES) * len(m06.SEEDS)
    identities = [
        (case["family"], case["seed"], len(case["cycles"])) for case in fixture["cases"]
    ]
    assert identities == [
        (family, seed, 5) for family in m06.FAMILIES for seed in m06.SEEDS
    ]
    for case in fixture["cases"]:
        assert [cycle["cycle"] for cycle in case["cycles"]] == [0, 1, 2, 3, 4]
        assert case["case_id"] == f"m06-{case['seed']}-{case['family']}"


def test_canonical_json_generate_fixture_is_byte_identical_per_seed() -> None:
    m06 = _module()
    seen: dict[int, bytes] = {}
    for seed in m06.SEEDS:
        first = m06.canonical_json(m06.generate_fixture(seed))
        second = m06.canonical_json(m06.generate_fixture(seed))
        assert first == second
        assert first.endswith(b"\n")
        seen[seed] = first
    assert len(set(seen.values())) == len(m06.SEEDS)
    assert FIXTURE_PATH.is_file(), "M06 fixture must exist"
    assert FIXTURE_PATH.read_bytes() == seen[m06.SEEDS[0]]


def test_portable_events_bind_to_the_closed_abi_without_extra_keys() -> None:
    m06 = _module()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    portable = schema["$defs"]["portable_event"]
    assert portable["additionalProperties"] is False
    assert tuple(portable["required"]) == PORTABLE_EVENT_KEYS
    public_metadata = schema["$defs"]["public_metadata"]
    assert public_metadata["additionalProperties"] is False
    assert set(public_metadata["properties"]) == {"source"}
    fixture = m06.generate_fixture(m06.SEEDS[0])
    for _case, cycle, event in _events(fixture):
        assert tuple(event) == PORTABLE_EVENT_KEYS
        assert _IDENTIFIER_RE.fullmatch(event["event_id"])
        assert 1 <= len(event["event_id"]) <= 128
        assert event["content"].strip()
        assert 1 <= len(event["actor_label"]) <= 256
        assert _TIMESTAMP_RE.fullmatch(event["event_time"])
        assert _TIMESTAMP_RE.fullmatch(event["ingestion_time"])
        assert _SHA256_RE.fullmatch(event["content_sha256"])
        assert event["content_sha256"] == hashlib.sha256(
            event["content"].encode()
        ).hexdigest()
        assert event["public_metadata"] == {"source": m06.GENERATOR_ID}
        assert set(cycle["retrieve"]) == {"query", "observation_time", "top_k"}
        assert set(cycle["answer"]) == {"question", "observation_time", "response_mode"}
        assert cycle["answer"]["response_mode"] == "normal"


def test_portable_event_rejects_extra_keys_and_bad_digest() -> None:
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    extra = deepcopy(fixture)
    extra["cases"][0]["cycles"][0]["events"][0]["tenant_id"] = "tenant-x"
    _rehash(m06, extra)
    with pytest.raises(m06.WmbsM06Error, match="portable_event"):
        m06.validate_fixture(extra)

    bad_digest = deepcopy(fixture)
    bad_digest["cases"][0]["cycles"][0]["events"][0]["content_sha256"] = "0" * 64
    _rehash(m06, bad_digest)
    with pytest.raises(m06.WmbsM06Error, match="content_sha256"):
        m06.validate_fixture(bad_digest)


def test_publication_flags_stay_false_without_headline_or_pilot_ready_dev() -> None:
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    report = m06.score(fixture, _gold_observations(fixture))
    for document in (fixture, report):
        assert document["publishable"] is False
        assert document["headline_eligible"] is False
        assert document["pbpp_headline_eligible"] is False
        assert document["admission_state"] == "PROPOSED"
        assert document["disposition"] == "PROPOSED"
        assert document["track"] == "DEVELOPMENT"
        assert "headline" not in document
        assert "PILOT-READY-DEV" not in document
        assert "pilot_ready_dev" not in document
    assert _walk_contains_key(fixture, "PILOT-READY-DEV") is False
    assert _walk_contains_key(report, "PILOT-READY-DEV") is False
    assert _walk_contains_key(report, "headline") is False
    for flag in ("publishable", "headline_eligible", "pbpp_headline_eligible"):
        mutated = deepcopy(fixture)
        mutated[flag] = True
        _rehash(m06, mutated)
        with pytest.raises(m06.WmbsM06Error, match="publication"):
            m06.validate_fixture(mutated)


@pytest.mark.parametrize(
    "marker",
    [
        "MemoryAgentBench",
        "EvoMemBench",
        "memoryagentbench item",
        "evomembench item",
        "held-out",
        "held_out",
        "PROTECTED-BYTES",
        "PRIVATE-BYTES",
        "OFFICIAL-UPSTREAM",
    ],
)
def test_fail_closed_on_protected_private_held_out_and_official_bytes(
    marker: str,
) -> None:
    m06 = _module()
    fixture = deepcopy(m06.generate_fixture(m06.SEEDS[0]))
    event = fixture["cases"][0]["cycles"][0]["events"][0]
    event["content"] += marker
    event["content_sha256"] = hashlib.sha256(event["content"].encode()).hexdigest()
    _rehash(m06, fixture)
    with pytest.raises(m06.WmbsM06Error, match="forbidden bytes"):
        m06.validate_fixture(fixture)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("custody", "protected"),
        ("custody", "private"),
        ("split", "held-out"),
        ("suite", "official"),
        ("data_class", "protected"),
    ],
)
def test_fail_closed_on_protected_custody_labels(field: str, value: str) -> None:
    m06 = _module()
    fixture = deepcopy(m06.generate_fixture(m06.SEEDS[0]))
    fixture["cases"][0][field] = value
    _rehash(m06, fixture)
    with pytest.raises(m06.WmbsM06Error, match="forbidden bytes"):
        m06.validate_fixture(fixture)


def test_reference_trace_matches_hand_calculated_descriptive_metrics() -> None:
    """Gold answers over the fixed corpus.

    30 cases = 6 families * 5 seeds. Consolidated utility is 1 on every case.
    No-memory matches gold only on unrelated-control (5 cases), so mean
    no-memory utility is 5/30 = 1/6 and utility delta is 1 - 1/6 = 5/6.
    Harmful emissions are 0 of 150 cycles. Compounding slots are the 120
    cycles after the first, with 0 repeats of a prior error. Transfer slots
    are the 20 related-transfer cycles after the source cycle, all correct.
    Event schedule per seed is repeated 5, corroborated 10, contradictory 8
    (cycles 0-1 have one event, cycles 2-4 have two), procedural 5,
    related-transfer 5, unrelated-control 5: 38 * 5 seeds = 190.
    """
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    report = m06.score(fixture, _gold_observations(fixture))
    metrics = report["metrics"]
    assert metrics["utility_delta"] == 1 - (1 / 6)
    assert metrics["utility_delta"] == 5 / 6
    assert metrics["harmful_promotion"] == 0 / 150
    assert metrics["compounding_error_rate"] == 0 / 120
    assert metrics["cross_episode_transfer"] == 20 / 20
    assert metrics["storage"] == {
        "event_count": 190,
        "content_bytes": sum(
            len(event["content"].encode()) for _case, _cycle, event in _events(fixture)
        ),
    }
    assert report["interval"] == {
        "scope": "finite-corpus",
        "statistic": "utility_delta",
        "minimum": 0.0,
        "maximum": 1.0,
        "count": 30,
    }
    assert report["disclosure"] == m06.FINITE_CORPUS_DISCLOSURE
    assert "finite" in report["disclosure"]
    assert report["spec_ci_lcb_acceptance"] == "DEFERRED"
    assert report["official_memory_agent_bench"] == "DEFERRED"
    assert report["official_evomembench"] == "DEFERRED"


def test_compounding_error_rate_is_hand_calculated() -> None:
    """One repeated case answers cycles 1 and 2 incorrectly.

    Cycle 1 follows a correct cycle, so it is not compounding. Cycle 2 repeats
    the previous error, so it is the only compounding slot: 1/120.
    That case utility is 3/5. The other 24 non-unrelated cases contribute 1
    and the 5 unrelated cases contribute 0, so the mean delta is
    (24 + 3/5) / 30.
    """
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    observations = _with_answer(fixture, "repeated", 17, 1, "abstain")
    observations = _with_answer_on(observations, "repeated", 17, 2, "abstain")
    report = m06.score(fixture, observations)
    assert report["metrics"]["compounding_error_rate"] == 1 / 120
    assert report["metrics"]["utility_delta"] == (24 + (3 / 5)) / 30
    assert report["metrics"]["harmful_promotion"] == 0.0


def test_harmful_promotion_is_hand_calculated() -> None:
    """One contradictory correction cycle emits the stale fact.

    That emission is 1 of 150 cycles. The case is correct on the other four
    cycles, so the mean utility delta is (24 + 4/5) / 30. The previous cycle
    is correct, so the rate of compounding errors stays 0.
    """
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    observations = _with_answer(fixture, "contradictory", 17, 2, "fact-v1")
    report = m06.score(fixture, observations)
    assert report["metrics"]["harmful_promotion"] == 1 / 150
    assert report["metrics"]["utility_delta"] == (24 + (4 / 5)) / 30
    assert report["metrics"]["compounding_error_rate"] == 0.0


def test_cross_episode_transfer_ignores_unrelated_control() -> None:
    """One related-transfer cycle misses: 19/20.

    An unrelated-control miss stays out of that denominator and does not
    become transfer credit. Unrelated gold is also the no-memory answer, so
    one miss moves that case delta from 0 to 4/5 - 1 = -1/5.
    """
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    missed = _with_answer(fixture, "related-transfer", 17, 3, "abstain")
    missed_report = m06.score(fixture, missed)
    assert missed_report["metrics"]["cross_episode_transfer"] == 19 / 20

    unrelated = _with_answer(fixture, "unrelated-control", 17, 3, "abstain")
    unrelated_report = m06.score(fixture, unrelated)
    assert unrelated_report["metrics"]["cross_episode_transfer"] == 1.0
    assert unrelated_report["metrics"]["utility_delta"] == (25 + (4 / 5 - 1)) / 30
    assert unrelated_report["metrics"]["harmful_promotion"] == 0.0


def test_latency_tokens_and_calls_stay_unsupported() -> None:
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    metrics = m06.score(fixture, _gold_observations(fixture))["metrics"]
    for name in ("latency", "tokens", "calls"):
        assert metrics[name] == "unsupported"


def test_provider_cost_is_explicitly_unsupported_not_a_billed_zero() -> None:
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    cost = m06.score(fixture, _gold_observations(fixture))["metrics"]["cost"]
    assert cost["provider_spend"] == "unsupported"
    assert cost["provider_spend"] != 0
    assert cost["provider_spend"] != 0.0
    assert "no provider budget" in cost["reason"]
    assert "not a billed zero" in cost["reason"]


def test_no_memory_control_discloses_the_missing_ablation() -> None:
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    report = m06.score(fixture, _gold_observations(fixture))
    assert report["control"] == "no-memory"
    assert report["public_operations"] == ["ingest", "retrieve", "answer"]
    assert report["ablation_disclosure"] == m06.NO_MEMORY_ABLATION_DISCLOSURE
    text = report["ablation_disclosure"].casefold()
    assert "no-memory" in text
    assert "no-consolidation" in text
    assert "missing ablation" in text
    explicit = _gold_observations(fixture)
    explicit["control"] = "no-memory"
    assert m06.score(fixture, explicit)["control"] == "no-memory"


def test_module_does_not_import_product_consolidation_or_surprise() -> None:
    m06 = _module()
    source = Path(m06.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert imported, "expected the stdlib imports that the oracle is allowed to use"
    for name in imported:
        root = name.split(".", 1)[0]
        assert root in _STDLIB_IMPORT_ROOTS
        folded = name.casefold()
        for marker in _FORBIDDEN_IMPORT_MARKERS:
            assert marker not in folded


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("consolidation_hook", {"run": True}),
        ("private_consolidation", True),
        ("private_no_consolidation_control", True),
        ("privileged_signal", {"score": 1}),
        ("privileged_internal_signal", "hidden"),
        ("baseline_improvement", 0.1),
        ("non_inferiority", True),
        ("ci_lcb", 0.0),
        ("spec_ci_lcb_accepted", True),
    ],
)
def test_rejects_private_hook_and_claim_fields(key: str, value: object) -> None:
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    observations = _gold_observations(fixture)
    observations[key] = value
    with pytest.raises(m06.WmbsM06Error, match="rejected field"):
        m06.score(fixture, observations)


@pytest.mark.parametrize(
    "control",
    ["no-consolidation", "private-no-consolidation", "privileged"],
)
def test_rejects_private_or_unavailable_no_consolidation_control(control: str) -> None:
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    observations = _gold_observations(fixture)
    observations["control"] = control
    with pytest.raises(m06.WmbsM06Error, match="no-consolidation|no-memory"):
        m06.score(fixture, observations)


def test_rejects_operations_outside_ingest_retrieve_answer() -> None:
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    observations = _gold_observations(fixture)
    observations["cases"][0]["cycles"][0]["operations"] = [
        "ingest",
        "consolidate",
        "answer",
    ]
    with pytest.raises(m06.WmbsM06Error, match="ingest, retrieve, and answer"):
        m06.score(fixture, observations)


def test_score_omits_baseline_improvement_non_inferiority_and_ci_lcb() -> None:
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    report = m06.score(fixture, _gold_observations(fixture))
    banned = {
        "baseline_improvement",
        "non_inferiority",
        "ci_lcb",
        "spec_ci_lcb_accepted",
        "headline",
        "PILOT-READY-DEV",
    }
    assert banned.isdisjoint(_walk_keys(report))
    assert report["spec_ci_lcb_acceptance"] == "DEFERRED"
    mutated = deepcopy(fixture)
    mutated["spec_ci_lcb_acceptance"] = "ACCEPTED"
    _rehash(m06, mutated)
    with pytest.raises(m06.WmbsM06Error, match="CI-LCB"):
        m06.validate_fixture(mutated)


def test_missing_case_fails_closed() -> None:
    m06 = _module()
    fixture = m06.generate_fixture(m06.SEEDS[0])
    observations = _gold_observations(fixture)
    observations["cases"].pop()
    with pytest.raises(m06.WmbsM06Error, match="missing scored case_id"):
        m06.score(fixture, observations)


def _with_answer_on(observations, family: str, seed: int, cycle: int, answer: str):
    case_id = f"m06-{seed}-{family}"
    cloned = deepcopy(observations)
    for case in cloned["cases"]:
        if case["case_id"] == case_id:
            case["cycles"][cycle]["answer_text"] = answer
            return cloned
    raise AssertionError(f"missing {case_id}")


def _walk_keys(value):
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value)
        for child in value.values():
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


def _walk_contains_key(value, key: str) -> bool:
    return key in _walk_keys(value)

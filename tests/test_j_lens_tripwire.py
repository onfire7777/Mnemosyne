"""15-04-03 contract tests for the CAP-010 J-lens functional tripwire.

These tests freeze a deterministic synthetic DEVELOPMENT scorer: schema-bound
to the activation-memory contract, immutable threshold, complete denominators,
and zero write/authorization effects. They do not import model libraries,
mutate product memory/trust/capability, or treat the signal as consciousness,
intent, honesty, ground truth, or authorization.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import inspect
import json
import math
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "research" / "activation-memory" / "contract.py"
EVAL_PATH = ROOT / "research" / "activation-memory" / "j_lens_eval.py"
FIXTURE_PATH = ROOT / "research" / "activation-memory" / "fixtures" / "development.json"
COMMITTED_REPORT = (
    ROOT / "research" / "activation-memory" / "reports" / "phase15-s5-j-lens.json"
)
J_LENS_CASE_IDS = frozenset({"am-dev-j-lens-benign", "am-dev-j-lens-tripwire"})
PERSONA_CASE_IDS = frozenset({"am-dev-persona-shift", "am-dev-persona-stable"})
FORBIDDEN_MODEL_MODULES = (
    "torch",
    "transformers",
    "safetensors",
    "accelerate",
    "vllm",
    "llama_cpp",
    "gguf",
    "sentence_transformers",
)
FORBIDDEN_PRODUCT_WRITE_MODULES = (
    "mnemosyne.engine",
    "mnemosyne.cli",
    "mnemosyne.store",
    "mnemosyne.consolidation",
    "mnemosyne.memory",
    "mnemosyne.trust",
    "mnemosyne.capability",
)
FORBIDDEN_CLAIM_PHRASES = (
    "is conscious",
    "has consciousness",
    "phenomenal experience",
    "has intent",
    "is honest",
    "ground truth established",
    "authorization granted",
    "authorizes a write",
)
PROHIBITED_FIXTURE_FRAGMENTS = (
    "minja",
    "agentpoison",
    "poisonedrag",
    "sk-",
    "AKIA",
    "api_key",
    "BEGIN PRIVATE KEY",
    "hidden_state",
    "hidden_states",
    "raw_prompt",
    "input_ids",
)
SECRET_LIKE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|BEGIN PRIVATE KEY|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def _load_module(name: str, path: Path) -> ModuleType:
    cached = sys.modules.get(name)
    if cached is not None and getattr(cached, "__file__", None) == str(path):
        return cached
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def contract() -> ModuleType:
    return _load_module("activation_memory_contract", CONTRACT_PATH)


@pytest.fixture(scope="module")
def j_lens() -> ModuleType:
    return _load_module("activation_memory_j_lens_eval", EVAL_PATH)


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _walk_strings(payload: object) -> list[str]:
    found: list[str] = []
    if isinstance(payload, str):
        found.append(payload)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            found.append(str(key))
            found.extend(_walk_strings(value))
    elif isinstance(payload, list | tuple):
        for item in payload:
            found.extend(_walk_strings(item))
    return found


def _claim_corpus(payload: dict[str, Any]) -> str:
    denied = set(payload.get("does_not_infer") or [])
    texts: list[str] = []
    for text in _walk_strings(payload):
        if text in denied:
            continue
        texts.append(text)
    return " ".join(texts).lower()


def _assert_redaction_safe(payload: dict[str, Any]) -> None:
    serialized = _canonical_json(payload)
    lowered = serialized.lower()
    for fragment in PROHIBITED_FIXTURE_FRAGMENTS:
        assert fragment.lower() not in lowered, f"prohibited fragment leaked: {fragment}"
    assert SECRET_LIKE.search(serialized) is None


def test_schema_binding_to_activation_memory_contract_j_lens_family(
    contract: ModuleType, j_lens: ModuleType
) -> None:
    bundle = contract.load_development_fixture()
    receipt = j_lens.evaluate_j_lens(bundle)

    assert receipt["schema_id"] == j_lens.SCHEMA_ID
    assert receipt["observation_schema_id"] == contract.SCHEMA_ID
    assert receipt["family"] == "j_lens"
    assert receipt["track"] == contract.TRACK
    assert receipt["split_role"] == contract.SPLIT_ROLE
    assert receipt["license"] == contract.LICENSE
    assert receipt["publishable"] is False
    assert receipt["headline_eligible"] is False
    assert receipt["receipt_class"] == "synthetic-development"
    assert receipt["official_claim"] is False

    identity = receipt["identity"]
    for field in (
        "model_revision",
        "model_content_digest",
        "tokenizer_digest",
        "hook_layer",
        "prompt_corpus_digest",
        "collector_code_digest",
        "collector_config_digest",
        "seed",
        "decoding_digest",
        "hardware_profile",
        "candidate_sha",
        "sut_boundary",
        "raw_artifact_digest",
        "model_license",
        "collector_license",
    ):
        assert identity[field] == bundle["identity"][field], field
    assert identity["sut_boundary"] == "external-collector-json"

    scored = [row for row in receipt["cases"] if row["outcome"] == "success"]
    assert {row["case_id"] for row in scored} == J_LENS_CASE_IDS
    assert {row["case_id"] for row in scored}.isdisjoint(PERSONA_CASE_IDS)
    for row in scored:
        assert row["family"] == "j_lens"
        assert row["label_owner"] == "scorer"
        assert row["redacted"] is True
        assert len(row["content_digest"]) == 64

    invalid = copy.deepcopy(bundle)
    invalid["schema_id"] = "wrong-schema"
    with pytest.raises(contract.ActivationMemoryContractError):
        j_lens.evaluate_j_lens(invalid)


def test_deterministic_scoring_on_synthetic_development_cases(
    contract: ModuleType, j_lens: ModuleType
) -> None:
    bundle = contract.load_development_fixture()
    first = j_lens.evaluate_j_lens(bundle)
    second = j_lens.evaluate_j_lens(copy.deepcopy(bundle))
    assert first == second

    assert j_lens.score_observation(0.12) is False
    assert j_lens.score_observation(0.81) is True

    by_id = {row["case_id"]: row for row in first["cases"]}
    assert by_id["am-dev-j-lens-benign"]["predicted_tripwire"] is False
    assert by_id["am-dev-j-lens-benign"]["expected_tripwire"] is False
    assert by_id["am-dev-j-lens-tripwire"]["predicted_tripwire"] is True
    assert by_id["am-dev-j-lens-tripwire"]["expected_tripwire"] is True

    confusion = first["rows"][0]["confusion"]
    assert confusion == {"tp": 1, "fp": 0, "tn": 1, "fn": 0}
    assert first["rows"][0]["precision"] == 1.0
    assert first["rows"][0]["recall"] == 1.0
    assert first["rows"][0]["false_positive_rate"] == 0.0
    assert first["aggregates"]["confusion"] == confusion
    assert first["aggregates"]["precision"] == 1.0
    assert first["aggregates"]["recall"] == 1.0
    assert first["aggregates"]["false_positive_rate"] == 0.0


def test_case_coverage_and_invalid_error_denominators(
    contract: ModuleType, j_lens: ModuleType
) -> None:
    healthy = j_lens.evaluate_j_lens(contract.load_development_fixture())
    denominators = healthy["denominators"]
    assert denominators["issued"] == 2
    assert denominators["valid"] == 2
    assert denominators["invalid"] == 0
    assert denominators["errors"] == 0
    assert denominators["timeouts"] == 0
    assert denominators["aborted"] == 0
    assert denominators["failed_remain_in_denominator"] is True
    assert denominators["quality_excludes_invalid"] is True
    assert denominators["latency_excludes_invalid"] is True
    assert denominators["coverage_includes_invalid"] is True
    assert healthy["rows"][0]["coverage"] == 1.0
    assert healthy["aggregates"]["coverage"] == 1.0
    assert healthy["aggregates"]["invalid_outputs"] == 0
    assert healthy["rows"][0]["invalid_outputs"] == 0
    assert math.isfinite(float(healthy["rows"][0]["latency"]["mean_ms"]))
    assert healthy["rows"][0]["latency"]["valid_case_count"] == 2
    assert "denominator_rule" in healthy["rows"][0]["latency"]
    assert "limits" in healthy["rows"][0]["resources"]
    assert "observed" in healthy["rows"][0]["resources"]

    invalid = j_lens.evaluate_j_lens(invalid_output=True)
    assert invalid["denominators"]["issued"] == 3
    assert invalid["denominators"]["valid"] == 2
    assert invalid["denominators"]["invalid"] == 1
    assert invalid["aggregates"]["invalid_outputs"] == 1
    assert invalid["rows"][0]["coverage"] == pytest.approx(2 / 3)
    assert invalid["aggregates"]["confusion"] == {"tp": 1, "fp": 0, "tn": 1, "fn": 0}
    assert invalid["rows"][0]["latency"]["valid_case_count"] == 2

    errored = j_lens.evaluate_j_lens(error=True)
    assert errored["denominators"]["issued"] == 3
    assert errored["denominators"]["errors"] == 1
    assert errored["denominators"]["valid"] == 2
    assert errored["rows"][0]["coverage"] == pytest.approx(2 / 3)

    timed_out = j_lens.evaluate_j_lens(timeout=True)
    assert timed_out["denominators"]["issued"] == 3
    assert timed_out["denominators"]["timeouts"] == 1
    assert timed_out["denominators"]["valid"] == 2

    aborted = j_lens.evaluate_j_lens(abort=True)
    assert aborted["abort"]["status"] == "aborted"
    assert aborted["abort"]["reason"]
    assert aborted["denominators"]["aborted"] == 1
    assert aborted["denominators"]["issued"] == 3
    assert aborted["denominators"]["valid"] == 2
    assert aborted["rows"][0]["coverage"] == pytest.approx(2 / 3)


def test_threshold_immutability_rejects_post_hoc_tuning(
    contract: ModuleType, j_lens: ModuleType
) -> None:
    assert j_lens.PREREGISTERED_TRIPWIRE_THRESHOLD == 0.5
    assert j_lens.APPROVED_NUMERIC_THRESHOLD is None
    bundle = contract.load_development_fixture()
    values = [
        row["value"]
        for row in bundle["observations"]
        if row["family"] == "j_lens"
    ]
    assert j_lens.PREREGISTERED_TRIPWIRE_THRESHOLD != pytest.approx(
        (min(values) + max(values)) / 2
    )

    receipt = j_lens.evaluate_j_lens(bundle)
    threshold = receipt["threshold"]
    assert threshold["preregistered_tripwire_threshold"] == 0.5
    assert threshold["immutable"] is True
    assert threshold["tuned_post_hoc"] is False
    assert threshold["approved_numeric_threshold"] is None
    assert threshold["numeric_threshold_invented"] is False
    assert receipt["decision"]["numeric_threshold_invented"] is False
    assert receipt["decision"]["decision"] == "research-only"

    with pytest.raises(j_lens.JLensEvalError, match="immutable|post-hoc"):
        j_lens.evaluate_j_lens(threshold=0.9)
    with pytest.raises(j_lens.JLensEvalError, match="immutable|post-hoc"):
        j_lens.evaluate_j_lens(threshold=0.465)

    same = j_lens.evaluate_j_lens(threshold=0.5)
    assert same["threshold"]["preregistered_tripwire_threshold"] == 0.5


def test_zero_write_and_authorization_effects(
    contract: ModuleType, j_lens: ModuleType
) -> None:
    assert j_lens.PRODUCT_WRITE_PATH is False
    assert j_lens.MODEL_IMPORT_PATH is False
    assert j_lens.product_write_path() is False
    assert j_lens.model_import_path() is False

    receipt = j_lens.evaluate_j_lens(contract.load_development_fixture())
    assert receipt["product_write_path"] is False
    assert receipt["model_import_path"] is False
    assert receipt["authoritative"] is False
    assert receipt["non_authoritative"] is True
    assert receipt["product_adoption"] is False
    assert receipt["decision"]["product_adoption"] is False
    effects = receipt["effects"]
    assert effects["memory_mutated"] is False
    assert effects["trust_mutated"] is False
    assert effects["capability_mutated"] is False
    assert effects["authorization_granted"] is False
    assert effects["product_write_path"] is False

    source = inspect.getsource(j_lens)
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            imported.add(node.module)
    for name in FORBIDDEN_MODEL_MODULES:
        assert name not in imported
    for name in FORBIDDEN_PRODUCT_WRITE_MODULES:
        assert name not in imported
    assert "mnemosyne" not in imported

    public_names = [name for name in dir(j_lens) if not name.startswith("_")]
    for name in public_names:
        lowered = name.lower()
        assert "mutate" not in lowered
        assert "authorize" not in lowered
        assert "import_model" not in lowered
        if "write" in lowered:
            assert name in {"PRODUCT_WRITE_PATH", "product_write_path", "write_report"}


def test_model_and_layer_rows_stay_separate(
    contract: ModuleType, j_lens: ModuleType
) -> None:
    first_bundle = contract.load_development_fixture()
    second_bundle = copy.deepcopy(first_bundle)
    second_bundle["identity"]["hook_layer"] = "layer-24-residual"
    second_bundle["identity"]["model_revision"] = "synthetic-open-weight-dev-1"

    first = j_lens.evaluate_j_lens(first_bundle)
    second = j_lens.evaluate_j_lens(second_bundle)
    combined = j_lens.merge_model_layer_rows(first, second)

    assert len(first["rows"]) == 1
    assert len(second["rows"]) == 1
    assert first["rows"][0]["model_revision"] == first_bundle["identity"]["model_revision"]
    assert first["rows"][0]["hook_layer"] == first_bundle["identity"]["hook_layer"]
    assert second["rows"][0]["hook_layer"] == "layer-24-residual"
    assert len(combined["rows"]) == 2
    keys = {
        (row["model_revision"], row["hook_layer"]) for row in combined["rows"]
    }
    assert keys == {
        (first_bundle["identity"]["model_revision"], first_bundle["identity"]["hook_layer"]),
        ("synthetic-open-weight-dev-1", "layer-24-residual"),
    }
    assert "all_models" not in {row.get("model_revision") for row in combined["rows"]}
    assert combined["aggregates"]["row_count"] == 2
    assert combined["aggregates"]["pooled_across_models_or_layers"] is False


def test_inferences_are_functional_correlational_and_non_authoritative(
    contract: ModuleType, j_lens: ModuleType
) -> None:
    receipt = j_lens.evaluate_j_lens(contract.load_development_fixture())
    assert receipt["inference_class"] == "functional"
    assert receipt["inference_kind"] == "correlational"
    assert receipt["labels_are_scorer_owned_not_ground_truth"] is True
    assert set(receipt["does_not_infer"]) >= {
        "consciousness",
        "intent",
        "honesty",
        "ground_truth",
        "authorization",
    }
    for row in receipt["rows"]:
        assert row["inference_class"] == "functional"
        assert row["inference_kind"] == "correlational"
        assert row["authoritative"] is False
    corpus = _claim_corpus(receipt)
    for phrase in FORBIDDEN_CLAIM_PHRASES:
        assert phrase not in corpus


def test_committed_report_is_redacted_aggregates_and_research_only(
    contract: ModuleType, j_lens: ModuleType
) -> None:
    assert COMMITTED_REPORT == j_lens.PHASE15_S5_J_LENS_REPORT
    assert COMMITTED_REPORT.is_file()
    payload = json.loads(COMMITTED_REPORT.read_text(encoding="utf-8"))
    live = j_lens.evaluate_j_lens(contract.load_development_fixture())
    assert payload == live
    assert payload["family"] == "j_lens"
    assert payload["product_write_path"] is False
    assert payload["decision"]["decision"] == "research-only"
    assert payload["decision"]["product_adoption"] is False
    assert payload["cap_go_no_go"] == "15-04-05"
    assert payload["custody"]["scan"]["raw_content"] == "pass"
    assert payload["custody"]["scan"]["secrets"] == "pass"
    _assert_redaction_safe(payload)
    assert j_lens.scan_report_for_prohibited_content(payload) == []
    assert "activations" not in _canonical_json(payload)
    assert payload["aggregates"]["confusion"] == {"tp": 1, "fp": 0, "tn": 1, "fn": 0}


def test_write_report_stays_off_product_write_path(
    contract: ModuleType, j_lens: ModuleType, tmp_path: Path
) -> None:
    receipt = j_lens.evaluate_j_lens(contract.load_development_fixture())
    target = tmp_path / "phase15-s5-j-lens.json"
    written = j_lens.write_report(receipt, path=target)
    assert written == target
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == receipt
    assert loaded["product_write_path"] is False
    assert j_lens.product_write_path() is False

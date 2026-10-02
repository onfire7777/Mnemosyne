"""15-04-04 contract tests for the CAP-010 persona-drift diagnostic.

These tests freeze a deterministic synthetic DEVELOPMENT scorer: pinned
reference vectors, normalized finite inputs, invariant case order,
scorer-owned perturbation labels, seed/config identity, complete
invalid/error denominators, and zero product effects. They do not import
model libraries, mutate product memory/trust/abstention/promotion, or treat
persona vectors as a sole calibration, abstention, profile, quarantine, or
promotion signal.
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
EVAL_PATH = ROOT / "research" / "activation-memory" / "persona_drift_eval.py"
FIXTURE_PATH = ROOT / "research" / "activation-memory" / "fixtures" / "development.json"
COMMITTED_REPORT = (
    ROOT / "research" / "activation-memory" / "reports" / "phase15-s5-persona-drift.json"
)
PERSONA_CASE_IDS = frozenset({"am-dev-persona-shift", "am-dev-persona-stable"})
J_LENS_CASE_IDS = frozenset({"am-dev-j-lens-benign", "am-dev-j-lens-tripwire"})
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
    "mnemosyne.abstention",
)
FORBIDDEN_SOLE_USES = (
    "calibration",
    "abstention",
    "user_profile_edits",
    "quarantine",
    "consolidation_promotion",
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
def persona() -> ModuleType:
    return _load_module("activation_memory_persona_drift_eval", EVAL_PATH)


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


def _assert_redaction_safe(payload: dict[str, Any]) -> None:
    serialized = _canonical_json(payload)
    lowered = serialized.lower()
    for fragment in PROHIBITED_FIXTURE_FRAGMENTS:
        assert fragment.lower() not in lowered, f"prohibited fragment leaked: {fragment}"
    assert SECRET_LIKE.search(serialized) is None


def test_pinned_reference_vectors(
    contract: ModuleType, persona: ModuleType
) -> None:
    bundle = contract.load_development_fixture()
    identity = bundle["identity"]
    key = (identity["model_revision"], identity["hook_layer"])
    pins = persona.PINNED_REFERENCE_VECTORS
    assert key in pins
    vector = pins[key]
    components = persona.normalize_vector(vector["components"])
    assert components
    assert all(math.isfinite(float(item)) for item in components)
    assert math.isclose(sum(float(item) ** 2 for item in components), 1.0)

    digest = persona.reference_vector_digest(key)
    assert len(digest) == 64
    assert digest != "0" * 64
    assert all(char in "0123456789abcdef" for char in digest)

    receipt = persona.evaluate_persona_drift(bundle)
    reference = receipt["reference"]
    assert reference["digest"] == digest
    assert reference["model_specific"] is True
    assert reference["model_revision"] == identity["model_revision"]
    assert reference["hook_layer"] == identity["hook_layer"]
    assert reference["raw_vector_retained"] is False
    assert "components" not in reference
    serialized = _canonical_json(receipt)
    for item in components:
        token = format(float(item), ".12g")
        assert not re.search(
            rf"(?<![0-9.]){re.escape(token)}(?![0-9.])", serialized
        ), token

    other_key = ("synthetic-open-weight-dev-1", "layer-24-residual")
    assert other_key not in pins
    with pytest.raises(persona.PersonaDriftEvalError, match="model-specific|pin"):
        persona.reference_vector_digest(other_key)


def test_normalized_finite_inputs(
    contract: ModuleType, persona: ModuleType
) -> None:
    unit = persona.normalize_vector((3.0, 4.0))
    assert unit == pytest.approx((0.6, 0.8))
    with pytest.raises(persona.PersonaDriftEvalError, match="finite"):
        persona.normalize_vector((float("nan"), 1.0))
    with pytest.raises(persona.PersonaDriftEvalError, match="finite"):
        persona.normalize_vector((float("inf"), 0.0))
    with pytest.raises(persona.PersonaDriftEvalError, match="zero|normaliz"):
        persona.normalize_vector((0.0, 0.0))
    with pytest.raises(persona.PersonaDriftEvalError, match="boolean"):
        persona.normalize_vector((True, False))

    bundle = contract.load_development_fixture()
    out_of_range = copy.deepcopy(bundle)
    for row in out_of_range["observations"]:
        if row["case_id"] == "am-dev-persona-stable":
            row["value"] = 1.5
    receipt = persona.evaluate_persona_drift(out_of_range)
    by_id = {row["case_id"]: row for row in receipt["cases"]}
    assert by_id["am-dev-persona-stable"]["outcome"] == "invalid"
    assert by_id["am-dev-persona-shift"]["outcome"] == "success"
    assert receipt["denominators"]["invalid"] == 1
    assert receipt["denominators"]["valid"] == 1


def test_invariant_case_order(contract: ModuleType, persona: ModuleType) -> None:
    bundle = contract.load_development_fixture()
    reversed_bundle = copy.deepcopy(bundle)
    reversed_bundle["observations"] = list(reversed(reversed_bundle["observations"]))
    first = persona.evaluate_persona_drift(bundle)
    second = persona.evaluate_persona_drift(reversed_bundle)
    assert first == second
    case_ids = [row["case_id"] for row in first["cases"]]
    assert case_ids == sorted(case_ids)
    assert case_ids == sorted(PERSONA_CASE_IDS)


def test_scorer_owned_perturbation_labels(
    contract: ModuleType, persona: ModuleType
) -> None:
    bundle = contract.load_development_fixture()
    receipt = persona.evaluate_persona_drift(bundle)
    by_id = {row["case_id"]: row for row in receipt["cases"]}
    assert set(by_id) == PERSONA_CASE_IDS
    assert set(by_id).isdisjoint(J_LENS_CASE_IDS)
    assert by_id["am-dev-persona-stable"]["label_owner"] == "scorer"
    assert by_id["am-dev-persona-stable"]["perturbation"] == "control"
    assert by_id["am-dev-persona-stable"]["expected_tripwire"] is False
    assert by_id["am-dev-persona-shift"]["label_owner"] == "scorer"
    assert by_id["am-dev-persona-shift"]["perturbation"] == "perturbed"
    assert by_id["am-dev-persona-shift"]["expected_tripwire"] is True
    assert receipt["labels_are_scorer_owned_not_ground_truth"] is True

    leaked = copy.deepcopy(bundle)
    leaked["labels"]["am-dev-persona-stable"]["owner"] = "collector"
    with pytest.raises(
        (contract.ActivationMemoryContractError, persona.PersonaDriftEvalError),
        match="scorer",
    ):
        persona.evaluate_persona_drift(leaked)


def test_seed_config_identity(contract: ModuleType, persona: ModuleType) -> None:
    bundle = contract.load_development_fixture()
    receipt = persona.evaluate_persona_drift(bundle)
    identity = receipt["identity"]
    assert identity["seed"] == bundle["identity"]["seed"]
    assert (
        identity["collector_config_digest"]
        == bundle["identity"]["collector_config_digest"]
    )
    assert identity["collector_code_digest"] == bundle["identity"]["collector_code_digest"]
    assert type(identity["seed"]) is int
    assert len(identity["collector_config_digest"]) == 64

    shifted = copy.deepcopy(bundle)
    shifted["identity"]["seed"] = bundle["identity"]["seed"] + 1
    other = persona.evaluate_persona_drift(shifted)
    assert other["identity"]["seed"] != receipt["identity"]["seed"]
    assert other["identity"]["collector_config_digest"] == identity["collector_config_digest"]

    unpinned = copy.deepcopy(bundle)
    unpinned["identity"]["collector_config_digest"] = "0" * 64
    with pytest.raises(contract.ActivationMemoryContractError, match="digest|pin"):
        persona.evaluate_persona_drift(unpinned)


def test_invalid_error_denominators(
    contract: ModuleType, persona: ModuleType
) -> None:
    healthy = persona.evaluate_persona_drift(contract.load_development_fixture())
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
    assert math.isfinite(float(healthy["rows"][0]["latency"]["mean_ms"]))
    assert healthy["rows"][0]["latency"]["valid_case_count"] == 2
    assert "denominator_rule" in healthy["rows"][0]["latency"]
    assert "limits" in healthy["rows"][0]["resources"]
    assert "observed" in healthy["rows"][0]["resources"]

    invalid = persona.evaluate_persona_drift(invalid_output=True)
    assert invalid["denominators"]["issued"] == 3
    assert invalid["denominators"]["valid"] == 2
    assert invalid["denominators"]["invalid"] == 1
    assert invalid["rows"][0]["coverage"] == pytest.approx(2 / 3)
    assert invalid["rows"][0]["latency"]["valid_case_count"] == 2

    errored = persona.evaluate_persona_drift(error=True)
    assert errored["denominators"]["issued"] == 3
    assert errored["denominators"]["errors"] == 1
    assert errored["denominators"]["valid"] == 2
    assert errored["rows"][0]["coverage"] == pytest.approx(2 / 3)

    timed_out = persona.evaluate_persona_drift(timeout=True)
    assert timed_out["denominators"]["issued"] == 3
    assert timed_out["denominators"]["timeouts"] == 1
    assert timed_out["denominators"]["valid"] == 2

    aborted = persona.evaluate_persona_drift(abort=True)
    assert aborted["abort"]["status"] == "aborted"
    assert aborted["abort"]["reason"]
    assert aborted["denominators"]["aborted"] == 1
    assert aborted["denominators"]["issued"] == 3
    assert aborted["denominators"]["valid"] == 2
    assert aborted["rows"][0]["coverage"] == pytest.approx(2 / 3)


def test_no_product_effects_on_memory_trust_abstention_or_promotion(
    contract: ModuleType, persona: ModuleType
) -> None:
    assert persona.PRODUCT_WRITE_PATH is False
    assert persona.MODEL_IMPORT_PATH is False
    assert persona.product_write_path() is False
    assert persona.model_import_path() is False

    receipt = persona.evaluate_persona_drift(contract.load_development_fixture())
    assert receipt["product_write_path"] is False
    assert receipt["model_import_path"] is False
    assert receipt["authoritative"] is False
    assert receipt["non_authoritative"] is True
    assert receipt["product_adoption"] is False
    assert receipt["sole_ground_truth"] is False
    assert receipt["decision"]["product_adoption"] is False
    effects = receipt["effects"]
    assert effects["memory_mutated"] is False
    assert effects["trust_mutated"] is False
    assert effects["abstention_mutated"] is False
    assert effects["promotion_mutated"] is False
    assert effects["user_profile_edited"] is False
    assert effects["quarantine_applied"] is False
    assert effects["consolidation_promoted"] is False
    assert effects["calibration_changed"] is False
    assert effects["product_write_path"] is False
    for use in FORBIDDEN_SOLE_USES:
        assert receipt["never_used_alone_for"][use] is True
        assert effects[f"used_alone_for_{use}"] is False

    source = inspect.getsource(persona)
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

    public_names = [name for name in dir(persona) if not name.startswith("_")]
    for name in public_names:
        lowered = name.lower()
        assert "mutate" not in lowered
        assert "authorize" not in lowered
        assert "import_model" not in lowered
        if "write" in lowered:
            assert name in {"PRODUCT_WRITE_PATH", "product_write_path", "write_report"}


def test_preregistered_distributions_controls_deltas_intervals_and_false_alarms(
    contract: ModuleType, persona: ModuleType
) -> None:
    bundle = contract.load_development_fixture()
    first = persona.evaluate_persona_drift(bundle)
    second = persona.evaluate_persona_drift(copy.deepcopy(bundle))
    assert first == second

    by_id = {row["case_id"]: row for row in first["cases"]}
    assert by_id["am-dev-persona-stable"]["distance"] == pytest.approx(0.04)
    assert by_id["am-dev-persona-stable"]["projection"] == pytest.approx(0.96)
    assert by_id["am-dev-persona-shift"]["distance"] == pytest.approx(0.33)
    assert by_id["am-dev-persona-shift"]["projection"] == pytest.approx(0.67)
    assert by_id["am-dev-persona-stable"]["false_alarm"] is False
    assert by_id["am-dev-persona-shift"]["false_alarm"] is False

    row = first["rows"][0]
    assert row["model_revision"] == bundle["identity"]["model_revision"]
    assert row["hook_layer"] == bundle["identity"]["hook_layer"]
    assert row["model_specific"] is True
    assert row["authoritative"] is False
    distance = row["distance"]
    projection = row["projection"]
    assert distance["n"] == 2
    assert distance["mean"] == pytest.approx(0.185)
    assert distance["min"] == pytest.approx(0.04)
    assert distance["max"] == pytest.approx(0.33)
    assert projection["n"] == 2
    assert projection["mean"] == pytest.approx(0.815)
    assert projection["min"] == pytest.approx(0.67)
    assert projection["max"] == pytest.approx(0.96)
    controls = row["controls"]
    assert controls["n"] == 1
    assert controls["distance_mean"] == pytest.approx(0.04)
    assert controls["projection_mean"] == pytest.approx(0.96)
    assert row["drift_delta"]["distance"] == pytest.approx(0.29)
    assert row["drift_delta"]["projection"] == pytest.approx(-0.29)
    assert math.isfinite(float(row["false_alarms"]["count"]))
    assert row["false_alarms"]["count"] == 0
    assert row["false_alarms"]["rate"] == 0.0
    assert row["false_alarms"]["control_n"] == 1
    assert first["aggregates"]["false_alarms"] == row["false_alarms"]
    assert first["aggregates"]["drift_delta"] == row["drift_delta"]
    assert first["aggregates"]["pooled_across_models_or_layers"] is False

    intervals = row["intervals"]
    for metric in ("distance", "projection", "drift_delta_distance", "false_alarm_rate"):
        interval = intervals[metric]
        assert interval["n"] >= 1
        assert math.isfinite(float(interval["low"]))
        assert math.isfinite(float(interval["high"]))
        assert float(interval["low"]) <= float(interval["high"])
        assert interval["method"]
    assert intervals["distance"]["low"] == pytest.approx(0.04)
    assert intervals["distance"]["high"] == pytest.approx(0.33)
    assert intervals["false_alarm_rate"]["method"] == "wilson"

    assert persona.APPROVED_NUMERIC_THRESHOLD is None
    assert first["threshold"]["approved_numeric_threshold"] is None
    assert first["threshold"]["numeric_threshold_invented"] is False
    assert first["threshold"]["immutable"] is True
    assert first["threshold"]["tuned_post_hoc"] is False
    assert first["decision"]["decision"] == "research-only"
    assert first["decision"]["numeric_threshold_invented"] is False

    with pytest.raises(persona.PersonaDriftEvalError, match="immutable|post-hoc"):
        persona.evaluate_persona_drift(threshold=0.9)


def test_model_and_layer_rows_stay_separate_and_model_specific(
    contract: ModuleType, persona: ModuleType
) -> None:
    first_bundle = contract.load_development_fixture()
    second_bundle = copy.deepcopy(first_bundle)
    second_bundle["identity"]["hook_layer"] = "layer-24-residual"
    second_bundle["identity"]["model_revision"] = "synthetic-open-weight-dev-1"

    first = persona.evaluate_persona_drift(first_bundle)
    second = persona.evaluate_persona_drift(second_bundle)
    combined = persona.merge_model_layer_rows(first, second)

    assert len(first["rows"]) == 1
    assert first["rows"][0]["model_specific"] is True
    assert second["rows"][0]["model_revision"] == "synthetic-open-weight-dev-1"
    assert second["rows"][0]["hook_layer"] == "layer-24-residual"
    assert second["reference"]["model_revision"] == "synthetic-open-weight-dev-1"
    assert second["reference"]["hook_layer"] == "layer-24-residual"
    assert second["reference"]["digest"] != first["reference"]["digest"]
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


def test_committed_report_is_redacted_aggregates_and_research_only(
    contract: ModuleType, persona: ModuleType
) -> None:
    assert COMMITTED_REPORT == persona.PHASE15_S5_PERSONA_DRIFT_REPORT
    assert COMMITTED_REPORT.is_file()
    payload = json.loads(COMMITTED_REPORT.read_text(encoding="utf-8"))
    live = persona.evaluate_persona_drift(contract.load_development_fixture())
    assert payload == live
    assert payload["family"] == "persona_drift"
    assert payload["product_write_path"] is False
    assert payload["decision"]["decision"] == "research-only"
    assert payload["decision"]["product_adoption"] is False
    assert payload["cap_go_no_go"] == "15-04-05"
    assert payload["custody"]["scan"]["raw_content"] == "pass"
    assert payload["custody"]["scan"]["secrets"] == "pass"
    _assert_redaction_safe(payload)
    assert persona.scan_report_for_prohibited_content(payload) == []
    assert "activations" not in _canonical_json(payload)
    assert payload["aggregates"]["false_alarms"]["count"] == 0
    assert payload["reference"]["raw_vector_retained"] is False
    for field in ("distance", "projection", "controls", "drift_delta", "intervals"):
        assert field in payload["aggregates"] or field in payload["rows"][0]


def test_write_report_stays_off_product_write_path(
    contract: ModuleType, persona: ModuleType, tmp_path: Path
) -> None:
    receipt = persona.evaluate_persona_drift(contract.load_development_fixture())
    target = tmp_path / "phase15-s5-persona-drift.json"
    written = persona.write_report(receipt, path=target)
    assert written == target
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == receipt
    assert loaded["product_write_path"] is False
    assert persona.product_write_path() is False
    assert FIXTURE_PATH.is_file()

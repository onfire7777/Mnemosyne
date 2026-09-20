"""15-04-01 contract tests for external activation-memory observations.

These tests freeze the DEVELOPMENT JSON boundary only. They do not import
model libraries, write product memory, or promote research signals.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import inspect
import json
import math
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "research" / "activation-memory" / "contract.py"
FIXTURE_PATH = ROOT / "research" / "activation-memory" / "fixtures" / "development.json"

FORBIDDEN_MODEL_MODULES = (
    "torch",
    "transformers",
    "safetensors",
    "accelerate",
    "vllm",
    "llama_cpp",
    "gguf",
)
FORBIDDEN_PRODUCT_WRITE_MODULES = (
    "mnemosyne.engine",
    "mnemosyne.cli",
    "mnemosyne.store",
    "mnemosyne.consolidation",
)
FORBIDDEN_AUTHORITY_FIELDS = (
    "authorize",
    "authority",
    "mutate",
    "mutation",
    "promote",
    "quarantine",
    "write_memory",
    "product_write",
)
FORBIDDEN_RAW_FIELDS = (
    "activations",
    "hidden_state",
    "hidden_states",
    "input_ids",
    "prompt",
    "raw_prompt",
    "tokens",
)
FORBIDDEN_SELF_SCORE_FIELDS = (
    "correct",
    "expected_family",
    "expected_tripwire",
    "gold",
    "label",
    "passed",
    "score",
)


def _load_contract() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "activation_memory_contract", CONTRACT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def contract() -> ModuleType:
    return _load_contract()


@pytest.fixture
def valid_bundle(contract: ModuleType) -> dict[str, Any]:
    return copy.deepcopy(contract.load_development_fixture())


def _reject(contract: ModuleType, bundle: dict[str, Any], message: str) -> None:
    with pytest.raises(contract.ActivationMemoryContractError, match=message):
        contract.validate_observation_bundle(bundle)


def test_development_fixture_is_finite_licensed_redacted_scorer_owned(
    contract: ModuleType,
) -> None:
    bundle = contract.load_development_fixture()
    accepted = contract.validate_observation_bundle(bundle)

    assert accepted["track"] == "DEVELOPMENT"
    assert accepted["split_role"] == "development"
    assert accepted["license"] == "CC0-1.0"
    assert accepted["custody"]["redacted"] is True
    assert accepted["custody"]["class"]
    assert accepted["custody"]["consent"]
    assert accepted["custody"]["authored_from_scratch"] is True
    assert accepted["custody"]["upstream_bytes_included"] is False
    assert accepted["custody"]["protected_cases_included"] is False
    assert accepted["custody"]["raw_activations_retained"] is False
    assert accepted["custody"]["raw_prompts_retained"] is False
    assert accepted["product_write_path"] is False
    assert accepted["model_import_path"] is False
    assert accepted["abort"]["status"] == "completed"
    assert accepted["abort"]["reason"] is None

    case_ids = [row["case_id"] for row in accepted["observations"]]
    assert case_ids
    assert len(case_ids) == len(set(case_ids))
    assert set(accepted["labels"]) == set(case_ids)
    for case_id, label in accepted["labels"].items():
        assert label["owner"] == "scorer"
        assert label["case_id"] == case_id
    for row in accepted["observations"]:
        assert row["redacted"] is True
        assert math.isfinite(row["value"])
        assert isinstance(row["content_digest"], str)
        assert len(row["content_digest"]) == 64


def test_required_identity_pins_are_content_bound(contract: ModuleType) -> None:
    bundle = contract.load_development_fixture()
    identity = bundle["identity"]
    required = (
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
    )
    for field in required:
        assert identity[field], field
        if field.endswith("_digest") or field == "raw_artifact_digest":
            assert len(identity[field]) == 64
            assert identity[field] != "0" * 64
    assert type(identity["seed"]) is int
    accepted = contract.validate_observation_bundle(bundle)
    assert accepted["identity"]["sut_boundary"] == "external-collector-json"


def test_resource_limits_and_abort_state_are_explicit(contract: ModuleType) -> None:
    bundle = contract.load_development_fixture()
    resources = bundle["resources"]
    for field in (
        "time_limit_s",
        "token_limit",
        "case_limit",
        "retry_limit",
        "memory_limit_mb",
        "vram_limit_mb",
        "disk_limit_mb",
        "network_limit_bytes",
        "cost_limit_usd",
    ):
        value = resources[field]
        assert type(value) in {int, float}
        assert math.isfinite(float(value))
        assert float(value) >= 0
    assert len(bundle["observations"]) <= resources["case_limit"]
    contract.validate_observation_bundle(bundle)

    aborted = copy.deepcopy(bundle)
    aborted["abort"] = {"status": "aborted", "reason": "vram_ceiling"}
    accepted = contract.validate_observation_bundle(aborted)
    assert accepted["abort"]["status"] == "aborted"
    assert accepted["abort"]["reason"] == "vram_ceiling"


def test_rejects_extra_fields(contract: ModuleType, valid_bundle: dict[str, Any]) -> None:
    valid_bundle["unexpected"] = True
    _reject(contract, valid_bundle, "extra")


def test_rejects_nan_and_infinity(
    contract: ModuleType, valid_bundle: dict[str, Any]
) -> None:
    nan_bundle = copy.deepcopy(valid_bundle)
    nan_bundle["observations"][0]["value"] = float("nan")
    _reject(contract, nan_bundle, "finite")

    inf_bundle = copy.deepcopy(valid_bundle)
    inf_bundle["resources"]["time_limit_s"] = float("inf")
    _reject(contract, inf_bundle, "finite")


def test_rejects_booleans_as_numbers(
    contract: ModuleType, valid_bundle: dict[str, Any]
) -> None:
    valid_bundle["observations"][0]["value"] = True
    _reject(contract, valid_bundle, "boolean")


def test_rejects_duplicate_and_missing_cases(
    contract: ModuleType, valid_bundle: dict[str, Any]
) -> None:
    duplicate = copy.deepcopy(valid_bundle)
    duplicate["observations"].append(copy.deepcopy(duplicate["observations"][0]))
    _reject(contract, duplicate, "unique")

    missing = copy.deepcopy(valid_bundle)
    orphan_id = missing["observations"][0]["case_id"]
    del missing["labels"][orphan_id]
    _reject(contract, missing, "bind")


def test_rejects_raw_prompt_or_hidden_state_payloads(
    contract: ModuleType, valid_bundle: dict[str, Any]
) -> None:
    for field in FORBIDDEN_RAW_FIELDS:
        tainted = copy.deepcopy(valid_bundle)
        tainted["observations"][0][field] = "raw-payload"
        _reject(contract, tainted, "raw|extra")


def test_rejects_self_scored_outputs(
    contract: ModuleType, valid_bundle: dict[str, Any]
) -> None:
    for field in FORBIDDEN_SELF_SCORE_FIELDS:
        scored = copy.deepcopy(valid_bundle)
        scored["observations"][0][field] = True
        _reject(contract, scored, "self-scored|extra")

    leaked = copy.deepcopy(valid_bundle)
    leaked["labels"][next(iter(leaked["labels"]))]["owner"] = "collector"
    _reject(contract, leaked, "scorer")


def test_rejects_unpinned_collectors_and_models(
    contract: ModuleType, valid_bundle: dict[str, Any]
) -> None:
    valid_bundle["identity"]["collector_code_digest"] = ""
    _reject(contract, valid_bundle, "pin|digest")


def test_rejects_mutation_or_authority_fields(
    contract: ModuleType, valid_bundle: dict[str, Any]
) -> None:
    for field in FORBIDDEN_AUTHORITY_FIELDS:
        requested = copy.deepcopy(valid_bundle)
        requested[field] = True
        _reject(contract, requested, "authority|extra|mutation")


def test_fixture_is_authored_json_without_upstream_bytes(contract: ModuleType) -> None:
    raw = FIXTURE_PATH.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    accepted = contract.validate_observation_bundle(parsed)
    lowered = raw.lower()
    assert "minja" not in lowered
    assert "agentpoison" not in lowered
    assert "poisonedrag" not in lowered
    assert accepted["custody"]["authored_from_scratch"] is True
    assert accepted["license"] == "CC0-1.0"


def test_contract_exposes_no_product_write_or_model_import_path(
    contract: ModuleType,
) -> None:
    assert contract.PRODUCT_WRITE_PATH is False
    assert contract.MODEL_IMPORT_PATH is False
    source = inspect.getsource(contract)
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            imported.add(node.module)
    for name in FORBIDDEN_MODEL_MODULES:
        assert name not in imported
    for name in FORBIDDEN_PRODUCT_WRITE_MODULES:
        assert name not in imported
    public_names = [name for name in dir(contract) if not name.startswith("_")]
    for name in public_names:
        lowered = name.lower()
        assert "write" not in lowered or name == "PRODUCT_WRITE_PATH"
        assert "mutate" not in lowered
        assert "import_model" not in lowered
        assert "authorize" not in lowered

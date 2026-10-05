"""Reader disclosure binding does not attest a provider or admit a benchmark."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from eval.public.reader_policy import candidate_reader_policy, match_reader_policy, validate_reader_policy
from eval.public.runner import build_candidate_manifest
from eval.public.adapters.locomo import LoCoMoError
from eval.public.adapters.locomo_native import project_native_response
from mnemosyne.providers.grounded_protocol import MODEL_CONTENT_SHA256


@pytest.fixture
def policy():
    candidate = build_candidate_manifest(model_content_sha256=MODEL_CONTENT_SHA256,
                                        git_sha="a" * 40, created_at_utc="2026-10-04T00:00:00Z")
    result = candidate_reader_policy(candidate)
    canonical = json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    assert result["candidate_manifest_sha256"] == sha256(canonical.encode()).hexdigest()
    return result


def test_candidate_policy_requires_both_roles_for_complete_match(policy):
    assert len(validate_reader_policy(policy)) == 64
    assert match_reader_policy(policy["reader"], policy)
    assert not match_reader_policy({}, policy)
    assert not match_reader_policy({"query_decomposer": policy["reader"]["query_decomposer"]}, policy)
    with pytest.raises(ValueError, match="roles"):
        match_reader_policy({"grounded_reader": policy["reader"]["grounded_reader"]}, policy)


@pytest.mark.parametrize("field", ["model", "model_content_digest", "prompt_sha256", "serializer_sha256", "decoding_options"])
def test_reader_disclosure_cannot_drift_from_policy(policy, field):
    reader = deepcopy(policy["reader"])
    reader["grounded_reader"][field] = {} if field == "decoding_options" else "changed"
    with pytest.raises(ValueError, match="does not match"):
        match_reader_policy(reader, policy)


def test_policy_digest_checks_decoding_and_candidate_identity(policy):
    damaged = deepcopy(policy)
    damaged["reader"]["grounded_reader"]["decoding_options"]["options"]["temperature"] = 1
    with pytest.raises(ValueError, match="decoding digest"):
        validate_reader_policy(damaged)
    damaged = deepcopy(policy)
    damaged["candidate_git_sha"] = "floating-branch"
    with pytest.raises(ValueError, match="candidate identity"):
        validate_reader_policy(damaged)


def test_policy_matching_preserves_runtime_and_incomplete_boundaries(policy):
    raw = {"reader": deepcopy(policy["reader"]), "answer": None, "abstained": True, "claims": [], "hops": []}
    annotation = {"question": "Synthetic?", "category": 4, "answer": "unused"}
    result = project_native_response(raw, annotation, {}, reader_policy=policy)
    assert result["reader_policy_matched"]
    assert result["reader_policy_sha256"] == validate_reader_policy(policy)
    assert not result["runtime_custody_verified"]
    raw["reader"] = {}
    result = project_native_response(raw, annotation, {}, reader_policy=policy)
    assert not result["reader_policy_matched"]
    assert result["status"] == "incomplete-reader-execution"
    raw["reader"] = {"unexpected": {}}
    with pytest.raises(LoCoMoError, match="policy"):
        project_native_response(raw, annotation, {}, reader_policy=policy)


@pytest.mark.parametrize("fault", ["extra", "artifact", "timeout", "backend", "seed", "draw", "caption"])
def test_native_run_config_rejects_malformed_declarations(policy, fault):
    from eval.harness.cli_driver import MnemoCLI
    from eval.public.adapters.locomo_config import build_native_run_config, validate_native_run_config
    source = [{"sample_id": "synthetic", "conversation": {
        "session_1_date_time": "Synthetic date", "session_1": [
            {"speaker": "A", "text": "synthetic", "dia_id": "D1:1"}]},
        "qa": [{"question": "Synthetic?", "category": 5, "answer": "distractor", "evidence": []}]}]
    cli = MnemoCLI(store="unused", global_flags=["--embedding-api-key", "synthetic-secret"])
    config = build_native_run_config(source, cli, reader_policy=policy, choice_seed=1,
              caption_policy="exclude-caption", runtime_manifest_sha256="1" * 64, resource_manifest_sha256="2" * 64)
    assert "synthetic-secret" not in json.dumps(config)
    if fault == "extra":
        config["runtime_verified"] = True
    elif fault == "artifact":
        config["runtime_manifest_sha256"] = "floating-tag"
    elif fault == "timeout":
        config["cli"]["timeout_seconds"] = True
    elif fault == "backend":
        config["cli"]["backend"] = "postgres"
    elif fault == "seed":
        config["choice_policy"]["seed"] = True
    elif fault == "draw":
        config["choice_policy"]["draws"][next(iter(config["choice_policy"]["draws"]))] = float("nan")
    else:
        config["caption_policy"] = "implicit"
    with pytest.raises(LoCoMoError):
        validate_native_run_config(config)

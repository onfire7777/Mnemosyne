"""JSON persistence must preserve per-trust-tier ingestion priority settings."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy


FIELDS = (
    "write_priority_max_by_trust_tier",
    "write_priority_debias_floor_by_trust_tier",
)


def test_default_policy_survives_json_round_trip() -> None:
    original = OperatingPolicy()
    restored = OperatingPolicy.from_dict(json.loads(json.dumps(original.to_dict())))
    assert restored.to_dict() == original.to_dict()


@pytest.mark.parametrize("field", FIELDS)
def test_integer_and_json_string_tier_keys_are_equivalent(field: str) -> None:
    numeric = {tier: 0.01 * (tier + 1) for tier in range(6)}
    encoded = {str(tier): value for tier, value in numeric.items()}
    original = copy.deepcopy(encoded)
    assert getattr(OperatingPolicy.from_dict({field: numeric}), field) == numeric
    assert getattr(OperatingPolicy.from_dict({field: encoded}), field) == numeric
    assert encoded == original


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_integer_key_keeps_precedence_over_string_alias(
    field: str, reverse: bool,
) -> None:
    # Existing in-memory callers already use the integer value. Normalization
    # must not let an unused string alias silently replace that effective value.
    items = [(0, 0.25), ("0", 0.75), ("5", 0.15)]
    raw = dict(reversed(items) if reverse else items)
    before = copy.deepcopy(raw)
    assert getattr(OperatingPolicy.from_dict({field: raw}), field) == {0: 0.25, 5: 0.15}
    assert raw == before


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [None, {}])
def test_unset_or_empty_mapping_does_not_add_defaults(field: str, value: object) -> None:
    assert getattr(OperatingPolicy.from_dict({field: value}), field) == value


@pytest.mark.parametrize("field", FIELDS)
def test_noncanonical_keys_and_values_are_not_coerced(field: str) -> None:
    original = {"unknown": 0.1, "01": 0.2, "1.0": 0.3, " 1": 0.4, "2": "0.5"}
    normalized = getattr(OperatingPolicy.from_dict({field: original}), field)
    assert normalized == {"unknown": 0.1, "01": 0.2, "1.0": 0.3, " 1": 0.4, 2: "0.5"}


def _priorities(engine: LocalMemoryEngine) -> dict[tuple[int, float], dict]:
    pipeline = IngestionPipeline(engine)
    results = {}
    for tier in range(6):
        for signal in (0.0, 1.0):
            request = IngestRequest(
                tenant_id="tenant", user_id="owner", actor="user",
                source_type="chat", content="Deterministic priority probe.",
                metadata={key: signal for key in ("importance", "novelty", "surprise", "reward")},
            )
            results[tier, signal] = pipeline._write_priority_signal(
                request=request, content=request.content, trust_tier=tier,
                prediction_error={"score": signal}, already_present=False,
            )
    return results


def test_ingestion_caps_and_debias_floors_survive_local_restart(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    policy = OperatingPolicy(
        write_priority_max_by_trust_tier={tier: 0.8 - 0.1 * tier for tier in range(6)},
        write_priority_debias_floor_by_trust_tier={tier: 0.09 - 0.01 * tier for tier in range(6)},
    )
    with LocalMemoryEngine(path, policy=policy) as engine:
        engine.append_evidence(Evidence(
            tenant_id="tenant", user_id="owner", actor="user",
            source_type="chat", content="Persist the configured operating policy.",
        ))
        before = _priorities(engine)
        for tier in range(6):
            assert before[tier, 1.0]["trust_cap"] == round(0.8 - 0.1 * tier, 6)
            assert before[tier, 0.0]["debias"]["floor"] == round(0.09 - 0.01 * tier, 6)
    with LocalMemoryEngine(path) as reopened:
        assert _priorities(reopened) == before

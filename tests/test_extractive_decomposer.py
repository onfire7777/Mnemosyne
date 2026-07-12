from __future__ import annotations

import json
from pathlib import Path

import pytest

from mnemosyne.providers.extractive_decomposer import (
    ExtractiveQueryDecomposer,
    extract_hop_zero_anchor,
)


def test_extractive_decomposition_anchor_matrix() -> None:
    payload = json.loads(
        Path("eval/datasets/v2/qa_decomposition_dev_v1.json").read_text(encoding="utf-8")
    )
    assert payload["schema"] == "mnemosyne-qa-decomposition-dev-v1"
    ids = [case["id"] for case in payload["cases"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 12
    for case in payload["cases"]:
        result = extract_hop_zero_anchor(case["question"])
        assert result == tuple(case["expected"]), case["id"]
        assert not result or result[0] in case["question"]


def test_provider_defers_authorized_evidence_traversal_to_orchestrator() -> None:
    provider = ExtractiveQueryDecomposer()
    assert provider.decompose(
        {
            "question": "When does project cobalt launch?",
            "evidence": [{"cid": "c1", "content": "project cobalt belongs to team juniper"}],
        }
    ) == {"queries": []}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": "cobalt", "evidence": [], "extra": True},
        {"question": 7, "evidence": []},
        {"question": "cobalt", "evidence": "not-a-sequence-of-records"},
    ],
)
def test_provider_rejects_invalid_payloads(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="payload"):
        ExtractiveQueryDecomposer().decompose(payload)

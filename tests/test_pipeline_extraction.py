"""Characterization goldens for the retrieve() pipeline extraction (Phase-2 Task 1).

These tests pin the FULL ``RetrievalResult`` surface of ``LocalMemoryEngine.retrieve``
— hit tuples ``(kind, id, score-bits, channel)``, confidence bits, abstention,
uncertainty note, token accounting, and the explain dict's full key-set plus
channel counts and adapters block — for seeded stores across four scenarios:

* fast mode (dense + lexical channels),
* deep mode (adds the graph_ppr channel),
* empty store,
* an abstention-triggering low-support query (hits present, insufficient
  query-term coverage).

They were captured GREEN against the shipped duplicated pipeline before the
extraction into ``mnemosyne.pipeline`` and act as the extraction's oracle: the
shared orchestrator must reproduce every surface byte-identically.

Determinism: the local hashing embedder, similarity reranker, activation,
standing, and calibration paths are all bit-deterministic for fresh seeded
stores (verified across processes, wall-clock gaps, and both kernel modes —
kernel byte-parity is proven separately by tests/test_native_parity.py), so
score bits are asserted exactly via ``float.hex()``.

Regenerate (only with an explicit spec-sanctioned behavior change):

    uv run --locked python tests/test_pipeline_extraction.py --write-goldens
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Relation, RetrievalResult

GOLDEN_PATH = Path(__file__).parent / "data" / "pipeline_extraction_goldens.json"

TENANT = "tenant-pipe"


def _seeded_engine() -> tuple[LocalMemoryEngine, str]:
    """A fresh deterministic store: 3 evidence rows, 2 assertions, 1 relation."""

    engine = LocalMemoryEngine()
    cids: list[str] = []
    for content in (
        "The deployment runbook lives in the operations wiki.",
        "Database backups run nightly at two in the morning UTC.",
        "The topaz beacon emits a steady glow over the harbor.",
    ):
        cids.append(
            engine.append_evidence(
                Evidence(
                    tenant_id=TENANT,
                    user_id="user-pipe",
                    actor="user",
                    source_type="seed",
                    content=content,
                    trust_tier=2,
                    access_policy={"tenant": TENANT},
                )
            )
        )
    engine.upsert_assertion(
        Assertion(
            id="11111111-1111-1111-1111-111111111111",
            tenant_id=TENANT,
            subject="deployment runbook",
            predicate="lives in",
            object="operations wiki",
            confidence=0.9,
            source_evidence_cids=[cids[0]],
            status="active",
            trust_tier=2,
            access_policy={"tenant": TENANT},
        )
    )
    engine.upsert_assertion(
        Assertion(
            id="22222222-2222-2222-2222-222222222222",
            tenant_id=TENANT,
            subject="database backups",
            predicate="run at",
            object="two in the morning",
            confidence=0.8,
            source_evidence_cids=[cids[1]],
            status="active",
            trust_tier=2,
            access_policy={"tenant": TENANT},
        )
    )
    engine.add_relation(
        Relation(
            id="33333333-3333-3333-3333-333333333333",
            tenant_id=TENANT,
            source="beacon",
            predicate="emits",
            target="topaz glow",
            confidence=0.85,
            source_evidence_cids=[cids[2]],
            access_policy={"tenant": TENANT},
        )
    )
    return engine, TENANT


def _surface(result: RetrievalResult) -> dict[str, Any]:
    """The full characterization surface of one retrieve() call."""

    return {
        "query": result.query,
        "hits": [
            [hit.kind, hit.id, float(hit.score).hex(), hit.channel]
            for hit in result.hits
        ],
        "confidence": float(result.confidence).hex(),
        "abstained": result.abstained,
        "uncertainty_note": result.uncertainty_note,
        "token_budget": result.token_budget,
        "used_tokens": result.used_tokens,
        "explain_keys": sorted(result.explain.keys()),
        "channels": result.explain["channels"],
        "adapters": result.explain["adapters"],
        "confidence_block": {
            "score": float(result.explain["confidence"]["score"]).hex(),
            "answer_score": float(result.explain["confidence"]["answer_score"]).hex(),
            "prediction_set_size": result.explain["confidence"]["prediction_set_size"],
            "threshold": float(result.explain["confidence"]["threshold"]).hex(),
            "source": result.explain["confidence"]["source"],
        },
        "read_marks": result.explain["read_marks"],
        "rails": result.explain["rails"],
        "rrf_k": result.explain["rrf_k"],
        "mmr_lambda": result.explain["mmr_lambda"],
    }


def build_all_surfaces() -> dict[str, dict[str, Any]]:
    """Every scenario on a FRESH engine (retrieve mutates read-marks)."""

    surfaces: dict[str, dict[str, Any]] = {}
    engine, tenant = _seeded_engine()
    surfaces["fast"] = _surface(
        engine.retrieve("deployment runbook operations", tenant_id=tenant, branch="main", deep=False)
    )
    engine, tenant = _seeded_engine()
    surfaces["deep"] = _surface(
        engine.retrieve("beacon topaz glow", tenant_id=tenant, branch="main", deep=True)
    )
    empty = LocalMemoryEngine()
    surfaces["empty"] = _surface(
        empty.retrieve("deployment runbook", tenant_id="tenant-empty", branch="main", deep=False)
    )
    engine, tenant = _seeded_engine()
    surfaces["low_support_abstention"] = _surface(
        engine.retrieve("glow quantum espresso protocols", tenant_id=tenant, branch="main", deep=False)
    )
    return surfaces


def _goldens() -> dict[str, dict[str, Any]]:
    return json.loads(GOLDEN_PATH.read_text())


def _assert_matches_golden(name: str) -> None:
    golden = _goldens()[name]
    live = build_all_surfaces()[name]
    # Per-key first for a readable diff, then the whole dict for completeness.
    assert sorted(live.keys()) == sorted(golden.keys())
    for key in sorted(golden):
        assert live[key] == golden[key], f"{name}.{key} diverged from golden"
    assert live == golden


def test_fast_mode_matches_golden() -> None:
    _assert_matches_golden("fast")


def test_deep_mode_matches_golden() -> None:
    _assert_matches_golden("deep")


def test_empty_store_matches_golden() -> None:
    _assert_matches_golden("empty")


def test_low_support_abstention_matches_golden() -> None:
    golden = _goldens()["low_support_abstention"]
    # The scenario must genuinely exercise the insufficient-support abstention
    # path WITH retrieved hits (not the trivial empty-store abstention).
    assert golden["abstained"] is True
    assert len(golden["hits"]) >= 1
    assert "did not cover enough query terms" in golden["uncertainty_note"]
    _assert_matches_golden("low_support_abstention")


def test_pipeline_marks_retrieval_depth_in_channel_filters() -> None:
    for deep in (False, True):
        engine = LocalMemoryEngine()
        seen_filters: list[dict[str, Any]] = []

        def vector_search(query: str, k: int, filt: dict[str, Any]) -> list[Any]:
            seen_filters.append(dict(filt))
            return []

        engine.vector_search = vector_search  # type: ignore[method-assign]
        engine.retrieve("depth marker", tenant_id=TENANT, branch="main", deep=deep)

        assert seen_filters[0]["_retrieval_deep"] is deep
        assert seen_filters[0]["tenant_id"] == TENANT
        assert seen_filters[0]["branch"] == "main"


def test_goldens_cover_expected_explain_keyset() -> None:
    """The explain dict's full key-set is pinned (R7 explain-parity checklist)."""

    expected = [
        "activation",
        "adapters",
        "answer_grounding_floor",
        "calibration",
        "channels",
        "confidence",
        "gist_support",
        "mmr_lambda",
        "rails",
        "read_marks",
        "reality_monitoring",
        "rrf_k",
        "schema_fast_path",
        "semantic_entropy",
        "standing",
        "workspace_broadcast",
        "workspace_retrieval_advisory",
    ]
    for name, golden in _goldens().items():
        assert golden["explain_keys"] == expected, name


if __name__ == "__main__":
    import sys

    if "--write-goldens" in sys.argv:
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps(build_all_surfaces(), indent=2, sort_keys=True) + "\n")
        print(f"wrote {GOLDEN_PATH}")
    else:
        print("usage: python tests/test_pipeline_extraction.py --write-goldens")

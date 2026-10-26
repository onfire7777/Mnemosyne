from __future__ import annotations

import math

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Hit
from mnemosyne.postgres_engine import PostgresEngine


def _make_hit(
    id: str,
    text: str,
    score: float = 1.0,
    channel: str = "lexical",
    metadata: dict | None = None,
    trust_tier: int = 0,
    provenance: tuple[str, ...] = (),
) -> Hit:
    return Hit(
        id=id,
        kind="evidence",
        tenant_id="test-tenant",
        branch="main",
        text=text,
        score=score,
        channel=channel,
        trust_tier=trust_tier,
        provenance=provenance,
        metadata=metadata or {},
    )


def test_confidence_has_no_artificial_096_floor() -> None:
    # Matching words do not turn weak, low-trust evidence into certainty.
    hit = _make_hit(
        id="h1", score=0.001, text="Paris", trust_tier=4,
        metadata={"confidence": 0.01, "score_scale": "bm25"},
    )
    for engine in (LocalMemoryEngine, PostgresEngine):
        assert engine._confidence("Paris", [hit]) < 0.45


def test_confidence_drops_below_abstention_threshold_when_unsupported() -> None:
    hit = _make_hit(
        id="h1", score=15.0, text="I visited Paris in the spring.",
        metadata={"score_scale": "bm25"},
    )
    # Query with missing crucial terms
    query = "When did I visit Tokyo and Kyoto for the conference?"
    conf = LocalMemoryEngine._confidence(query, [hit])
    # With query support < threshold, confidence must be well below 0.45
    assert conf < 0.45


def test_confidence_high_when_strongly_supported() -> None:
    hit = _make_hit(
        id="h1", score=25.0, text="I visited Paris in the spring.",
        metadata={"score_scale": "bm25"},
    )
    query = "When did I visit Paris in the spring?"
    conf = LocalMemoryEngine._confidence(query, [hit])
    assert conf >= 0.50
    assert conf <= 1.0


def test_postgres_engine_confidence_parity() -> None:
    # 1. Unsupported query
    hit_unsupported = _make_hit(
        id="h1", score=15.0, text="I visited Paris in the spring.",
        metadata={"score_scale": "bm25"},
    )
    q_unsupported = "When did I visit Tokyo and Kyoto?"
    loc_unsup = LocalMemoryEngine._confidence(q_unsupported, [hit_unsupported])
    pg_unsup = PostgresEngine._confidence(q_unsupported, [hit_unsupported])
    assert abs(loc_unsup - pg_unsup) < 1e-6
    assert pg_unsup < 0.45

    # 2. Multi-channel hit with provenance
    hit_mc = _make_hit(
        id="h2", score=15.0, text="Alice visited Paris in the spring.",
        channel="lexical+vector+graph", provenance=("c1", "c2", "c3"),
        metadata={"score_scale": "bm25", "confidence": 0.95},
    )
    q_mc = "When did Alice visit Paris?"
    loc_mc = LocalMemoryEngine._confidence(q_mc, [hit_mc])
    pg_mc = PostgresEngine._confidence(q_mc, [hit_mc])
    assert abs(loc_mc - pg_mc) < 1e-6

    # 3. Two hits with rank margin
    hits_margin = [
        _make_hit(id="h3", score=20.0, text="Alice visited Paris in the spring.", channel="lexical"),
        _make_hit(id="h4", score=2.0, text="Bob visited London in the winter.", channel="lexical"),
    ]
    loc_margin = LocalMemoryEngine._confidence(q_mc, hits_margin)
    pg_margin = PostgresEngine._confidence(q_mc, hits_margin)
    assert abs(loc_margin - pg_margin) < 1e-6


@pytest.mark.parametrize("engine", [LocalMemoryEngine, PostgresEngine])
def test_matching_evidence_confidence_responds_to_quality(engine) -> None:
    high = _make_hit(id="high", text="Paris", score=1, trust_tier=0,
                     metadata={"confidence": 0.95}, provenance=("source",))
    low_confidence = _make_hit(id="low-confidence", text="Paris", score=1, trust_tier=0,
                               metadata={"confidence": 0.01}, provenance=("source",))
    low_trust = _make_hit(id="low-trust", text="Paris", score=1, trust_tier=4,
                          metadata={"confidence": 0.95}, provenance=("source",))
    assert engine._confidence("Paris", [high]) > engine._confidence("Paris", [low_confidence])
    assert engine._confidence("Paris", [high]) > engine._confidence("Paris", [low_trust])
    assert engine._confidence("Paris", [high]) < 1.0


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -float("inf"), 1e308])
def test_confidence_nonfinite_and_huge_scores_stay_finite_and_equal(score) -> None:
    hits = [_make_hit(id=str(i), text="Paris", score=score) for i in range(3)]
    local = LocalMemoryEngine._confidence("Paris", hits)
    postgres = PostgresEngine._confidence("Paris", hits)
    assert math.isfinite(local) and 0 <= local < 1
    assert local == pytest.approx(postgres)


@pytest.mark.parametrize("support", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_query_support_cannot_certify_evidence(support) -> None:
    hit = _make_hit(id="h", text="Paris", score=1)
    assert LocalMemoryEngine._confidence("Paris", [hit], support_score=support) == 0
    assert PostgresEngine._confidence("Paris", [hit], support_score=support) == 0


def test_matching_low_confidence_evidence_abstains_under_calibration() -> None:
    from mnemosyne.calibration import CalibrationSet
    from mnemosyne.models import Evidence

    engine = LocalMemoryEngine()
    engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="doc",
        content="Paris", metadata={"confidence": 0.01}))
    engine.set_calibration(CalibrationSet(tenant_id="t", memory_type="fact", scores=[0.5], target_coverage=0.9))
    result = engine.retrieve("Paris", "t", record_access=False)
    assert result.confidence < 0.5
    assert result.abstained
    assert result.explain["confidence"]["source"] == "conformal"

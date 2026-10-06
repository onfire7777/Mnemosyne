"""Relation security built from per-row facts equals the legacy computation exactly."""

from __future__ import annotations

import random

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Relation

KINDS = ["note", "web", "summary", "simulation", "consolidation-summary", "trace"]
ACTORS = ["user", "assistant", "tool", "external", "system"]


def _engine(seed: int) -> tuple[LocalMemoryEngine, list[str], random.Random]:
    rng = random.Random(seed)
    engine = LocalMemoryEngine()
    cids = []
    for i in range(rng.randint(1, 12)):
        cid = engine.append_evidence(Evidence(
            tenant_id="t", user_id="u", actor=rng.choice(ACTORS), source_type=rng.choice(KINDS),
            content=f"row {i} {rng.random()}", source_identity=rng.choice([None, "same", f"id{i}"]),
            trust_tier=rng.randint(0, 4), sensitivity=rng.choice([0, 0, 1, 2]),
        ))
        cids.append(cid)
    for cid in cids:
        row = engine.evidence[engine._evidence_key("t", "main", cid)]
        roll = rng.random()
        if roll < 0.1:
            row.metadata = {**row.metadata, "quarantine_reason": "x"}
        elif roll < 0.15:
            row.metadata = {**row.metadata, "summary": {"status": "retired"}}
        elif roll < 0.25:
            row.capability_tags = ["untrusted-tool-output", "sanitize-as-data"]
        elif roll < 0.32:
            row.metadata = {**row.metadata, "self_generated_ancestor_cids": ["z"]}
        elif roll < 0.38:
            row.metadata = {**row.metadata, "reality_class": rng.choice(["grounded", "simulated", "bogus"])}
        elif roll < 0.43:
            row.access_policy = {**row.access_policy, "restricted": True}
        elif roll < 0.48:
            row.access_policy = {**row.access_policy, "allow_roles": ["operator"]}
    return engine, cids, rng


@pytest.mark.parametrize("seed", range(120))
def test_fact_based_relation_security_equals_the_legacy_computation(seed: int) -> None:
    engine, cids, rng = _engine(seed)
    sources = [rng.choice(cids + ["missing-cid", ""]) for _ in range(rng.randint(0, 10))]
    engine.add_relation(Relation(tenant_id="t", source="a", predicate="links", target="b", source_evidence_cids=sources))
    relation = next(iter(engine.relations.values()))
    for include_quarantined in (False, True):
        for max_trust, max_sensitivity in ((5, 3), (2, 1), (4, 0)):
            inputs = dict(branch="main", include_quarantined=include_quarantined, max_trust=max_trust,
                          max_sensitivity=max_sensitivity, access_context={"tenant_id": "t", "branch": "main"})
            legacy = engine._relation_hit_security_compute(relation, **inputs)[0]
            assert engine._relation_hit_security(relation, **inputs) == legacy
            assert engine._relation_hit_security(relation, **inputs) == legacy  # memoised
            verdict = engine._relation_security_verdict(relation, **inputs)
            assert verdict == (None if legacy is None else (legacy["trust_tier"], legacy["sensitivity"]))

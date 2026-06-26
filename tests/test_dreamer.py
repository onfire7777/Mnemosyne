from __future__ import annotations

from mnemosyne.dreamer import SandboxedDreamer
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence


def test_sandboxed_dreamer_generates_low_trust_candidates_without_mutating_engine() -> None:
    engine = LocalMemoryEngine()
    tenant = "tenant-dreamer"
    user = "user-dreamer"
    first = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="operator-evidence",
            content="Alpha planning evidence links consolidation priorities to durable recall.",
            access_policy={"tenant": tenant},
        )
    )
    second = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="operator-evidence",
            content="Omega runtime evidence links workspace focus to calibrated retrieval.",
            access_policy={"tenant": tenant},
        )
    )
    before = engine.export_tenant(tenant)

    report = SandboxedDreamer(max_candidates=2).dream(
        [engine.get_evidence(tenant, first), engine.get_evidence(tenant, second)],
        tenant_id=tenant,
    )
    after = engine.export_tenant(tenant)

    assert before == after
    assert report.shadow_only is True
    assert report.production_mutation is False
    assert report.critical_path is False
    assert report.promotion_gate_required is True
    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.reality_class == "self_generated"
    assert candidate.trust_tier == 5
    assert candidate.shadow_only is True
    assert candidate.promotion_required is True
    assert candidate.critical_path is False
    assert candidate.source_evidence_cids == (first, second)
    assert candidate.id.startswith("dream:")


def test_sandboxed_dreamer_requires_multiple_cid_backed_sources() -> None:
    report = SandboxedDreamer().dream(
        [{"cid": "cidv1:abc", "content": "single source evidence"}],
        tenant_id="tenant-dreamer",
    )

    assert report.candidates == ()
    assert report.source_count == 1

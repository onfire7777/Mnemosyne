"""Durable retrieval remains useful when the working-memory store fails."""

from datetime import UTC, datetime

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence


@pytest.mark.parametrize("parallel", ["0", "1"], ids=["serial", "parallel"])
def test_durable_hit_survives_working_store_failure(
    monkeypatch: pytest.MonkeyPatch, parallel: str
) -> None:
    monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", parallel)
    monkeypatch.setenv("MNEMOSYNE_RETRIEVAL_RESULT_CACHE_SIZE", "0")
    engine = LocalMemoryEngine()
    tenant = "tenant-failure-survival"
    session = "session-failure-survival"
    evidence_id = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="user-failure-survival",
            actor="user",
            source_type="chat",
            session_id=session,
            content="The Helios deployment rollback uses the cobalt snapshot.",
            access_policy={"tenant": tenant},
        )
    )
    filt = {
        "working_session_id": session,
        "as_of": datetime(2026, 9, 4, 12, tzinfo=UTC),
    }
    baseline = engine.retrieve(
        "Helios deployment rollback cobalt snapshot",
        tenant,
        filt=filt,
        record_access=False,
    )
    assert evidence_id in {hit.id for hit in baseline.hits}

    calls = []

    def broken_store(tenant_id: str, session_id: str, *, as_of: datetime) -> list:
        calls.append((tenant_id, session_id, as_of))
        raise RuntimeError("working store unavailable")

    monkeypatch.setattr(engine, "list_working", broken_store)
    degraded = engine.retrieve(
        "Helios deployment rollback cobalt snapshot",
        tenant,
        filt=filt,
        record_access=False,
    )

    assert calls == [(tenant, session, filt["as_of"])]
    assert evidence_id in {hit.id for hit in degraded.hits}
    assert degraded.explain["working_memory"]["reason"] == "working_store_error"
    assert all(hit.kind != "working" for hit in degraded.hits)

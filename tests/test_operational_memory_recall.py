"""Operational traces remain available without displacing everyday memory."""

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_operational_trace_does_not_crowd_out_durable_memory(tmp_path, backend):
    policy = OperatingPolicy(top_k=3, rerank_width=8)
    engine = SqliteEngine(tmp_path / "db", policy=policy) if backend == "sqlite" else LocalMemoryEngine(policy=policy)
    query = "where is the project release checklist"
    answer = engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="chat",
        content="The project release checklist is in docs/release.md.", trust_tier=1,
        access_policy={"tenant": "t"}))
    traces = [engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="tool",
        source_type="learning_tool_result", content=f"{query}\ncommand output {i}",
        trust_tier=1, access_policy={"tenant": "t"})) for i in range(40)]
    result = engine.retrieve(query, tenant_id="t", filt={"user_id": "u"}, record_access=False)
    assert answer in {hit.id for hit in result.hits}
    assert not set(traces) & {hit.id for hit in result.hits}
    assert all(engine.get_evidence("t", cid) is not None for cid in traces)
    assert LearningRuntime(engine)._sources_live("t", traces, "u")
    explicit = engine.retrieve(query, tenant_id="t", filt={"user_id": "u", "include_operational": True}, record_access=False)
    assert set(traces) & {hit.id for hit in explicit.hits}
    history = engine.retrieve(query, tenant_id="t", deep=True, filt={"user_id": "u"}, record_access=False)
    assert set(traces) & {hit.id for hit in history.hits}
    engine.close()

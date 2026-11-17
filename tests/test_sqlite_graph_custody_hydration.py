"""Graph hydration loads the complete custody closure, not unrelated logs."""

from mnemosyne import sqlite_engine as sqlite_module
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Relation
from mnemosyne.sqlite_engine import SqliteEngine


def test_graph_hydration_retains_transitive_sources_and_privacy(tmp_path, monkeypatch):
    local = LocalMemoryEngine()
    sqlite = SqliteEngine(tmp_path / "store")
    engines = (local, sqlite)
    source = Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="note",
        content="archive is stored in docs", trust_tier=1,
        access_policy={"tenant": "t", "allow_principals": ["u"]},
    )
    source_cids = [engine.append_evidence(source) for engine in engines]
    assert source_cids[0] == source_cids[1]
    source_cid = source_cids[0]
    derived = Evidence(
        tenant_id="t", user_id="u", actor="system", source_type="provider-proposal",
        content="archive location: docs", trust_tier=1,
        metadata={"source_evidence_cids": [source_cid]},
        access_policy={"tenant": "t"},
    )
    unrelated = Evidence(
        tenant_id="t", user_id="u", actor="tool", source_type="learning_tool_result",
        content="unrelated transcript " * 10000, trust_tier=1,
    )
    derived_cids = []
    for engine in engines:
        derived_cids.append(engine.append_evidence(derived))
        engine.append_evidence(unrelated)
    assert derived_cids[0] == derived_cids[1]
    derived_cid = derived_cids[0]
    relation = Relation(
        tenant_id="t", source="archive", predicate="located_in", target="docs",
        source_evidence_cids=[derived_cid],
    )
    for engine in engines:
        engine.add_relation(relation)

    hydrated = []
    decode = sqlite_module._evidence_from_row

    def track(row):
        hydrated.append(row["cid"])
        return decode(row)

    monkeypatch.setattr(sqlite_module, "_evidence_from_row", track)
    scope = {"user_id": "u", "principal": "u"}

    def query(engine, filt=scope):
        return engine.graph_ppr(["archive"], 5, tenant_id="t", branch="main", filt=filt)

    actual = query(sqlite)
    expected = query(local)
    assert actual and [(x.id, x.score, x.provenance) for x in actual] == [
        (x.id, x.score, x.provenance) for x in expected
    ]
    assert set(hydrated) == {source_cid, derived_cid}
    assert not query(sqlite, {"user_id": "other", "principal": "other"})

    # A source retirement/erasure must invalidate the graph, even though the
    # relation's immediate source is the still-retained derived row.
    for engine in engines:
        engine.forget("t", source_cid)
    assert not query(sqlite)
    assert not query(local)
    sqlite.close()

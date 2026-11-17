"""Ordinary recall must not score retained tool logs that it discards anyway."""

import pytest

from mnemosyne import engine as engine_module, text
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence
from mnemosyne.pipeline import _diverse_learning_search
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_ordinary_recall_skips_tool_log_scoring_but_retains_source_custody(
    tmp_path, monkeypatch, backend,
):
    engine = (SqliteEngine(tmp_path / "store") if backend == "sqlite"
              else LocalMemoryEngine())
    log = "archive result: " + "café output " * 2000
    source = engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="tool", source_type="learning_tool_result",
        content=log, trust_tier=1, access_policy={"tenant": "t", "allow_principals": ["u"]},
    ))
    fact = Assertion(
        tenant_id="t", user_id="u", subject="archive", predicate="location",
        object="docs/archive", source_evidence_cids=[source], trust_tier=1,
        access_policy={"tenant": "t", "allow_principals": ["u"]},
    )
    engine.upsert_assertion(fact)
    monkeypatch.setattr(text, "NATIVE", None)
    original = text.lexical_scorer
    scored = []

    def tracking_scorer(query):
        score = original(query)

        def track(content):
            scored.append(content)
            return score(content)

        return track

    monkeypatch.setattr(text, "lexical_scorer", tracking_scorer)
    monkeypatch.setattr(engine_module, "lexical_scorer", tracking_scorer)
    scope = {"tenant_id": "t", "user_id": "u", "principal": "u"}

    def recall(include_operational=False):
        return _diverse_learning_search(
            engine.lexical_search, "archive", 10, scope, lambda hit: (hit.id,),
            include_operational=include_operational,
        )

    hits = recall()
    assert fact.id in {hit.id for hit in hits}
    assert source not in {hit.id for hit in hits}
    assert log not in scored  # Bounded work, not merely filtering the final result.
    assert engine.get_evidence("t", source).content == log

    # The same engine/cache must still expose the retained source on an explicit
    # operational query, without losing the fact's evidence dependency.
    hits = recall(include_operational=True)
    assert {source, fact.id} <= {hit.id for hit in hits}
    assert log in scored
    scored.clear()
    assert source not in {hit.id for hit in recall()}
    assert log not in scored
    assert not engine.lexical_search(
        "archive", 10,
        {"tenant_id": "t", "user_id": "other", "principal": "other",
         "_exclude_operational_evidence": True},
    )

    # Relevance optimization must not bypass custody after source erasure.
    engine.forget("t", source)
    assert fact.id not in {hit.id for hit in recall()}
    if hasattr(engine, "close"):
        engine.close()

"""Focused contract tests for the session-scoped working retrieval route."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Hit
from mnemosyne.retrieval import build_working_memory_hits, working_memory_hits
from mnemosyne.security import SystemPromptSinkError, assemble_system_prompt


TENANT = "tenant-working-route"
SESSION = "session-working-route"
OTHER_SESSION = "session-other"
EVALUATED_AT = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def _item(
    item_id: str,
    *,
    tenant_id: str = TENANT,
    session_id: str = SESSION,
    task_id: str = "task-deploy",
    content: str = "Deploy the service after the smoke test.",
    created_at: datetime = EVALUATED_AT - timedelta(minutes=5),
    expires_at: datetime = EVALUATED_AT + timedelta(minutes=5),
    **overrides: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "item_id": item_id,
        "tenant_id": tenant_id,
        "session_id": session_id,
        "user_id": "user-working-route",
        "agent_id": "agent-working-route",
        "kind": "active_goal",
        "task_id": task_id,
        "content": content,
        "created_at": created_at,
        "expires_at": expires_at,
        "evidence_ids": [f"evidence-{item_id}"],
        "trust_tier": 2,
        "sensitivity": 1,
        "access_policy": {"tenant": tenant_id},
        "metadata": {"reality_class": "grounded", "source_type": "conversation"},
        "status": "active",
    }
    row.update(overrides)
    return row


def test_working_route_is_tenant_session_scoped_and_ttl_is_half_open() -> None:
    rows = [
        _item("visible"),
        _item("other-tenant", tenant_id="tenant-other"),
        _item("other-session", session_id=OTHER_SESSION),
        _item("other-branch", branch="other"),
        _item("expired", expires_at=EVALUATED_AT),
        _item("future", created_at=EVALUATED_AT + timedelta(seconds=1)),
        _item("already-expired", status="expired"),
    ]
    original = deepcopy(rows)

    before_boundary = working_memory_hits(
        rows,
        query="deploy",
        tenant_id=TENANT,
        session_id=SESSION,
        evaluated_at=EVALUATED_AT - timedelta(microseconds=1),
    )
    at_boundary = working_memory_hits(
        rows,
        query="deploy",
        tenant_id=TENANT,
        session_id=SESSION,
        evaluated_at=EVALUATED_AT,
    )

    assert [hit.id for hit in before_boundary] == ["visible", "expired"]
    assert [hit.id for hit in at_boundary] == ["visible"]
    assert rows == original


def test_normalized_provider_requires_exact_tenant_session_and_branch_markers() -> None:
    engine = LocalMemoryEngine()

    def hit(item_id: str, *, session_id: str | None, branch: str = "main") -> Hit:
        metadata: dict[str, object] = {
            "working_memory": {
                "data_only": True,
                "promotion_gate_required": True,
                "task_id": "task-deploy",
                "created_at": EVALUATED_AT - timedelta(minutes=5),
                "expires_at": EVALUATED_AT + timedelta(minutes=5),
            }
        }
        if session_id is not None:
            metadata["session_id"] = session_id
        return Hit(
            id=item_id,
            kind="evidence",
            tenant_id=TENANT,
            branch=branch,
            text=item_id,
            score=1.0,
            channel="working_memory",
            metadata=metadata,
        )

    def working_memory_search(query: str, k: int, filt: dict[str, object]) -> list[Hit]:
        return [
            hit("missing-session", session_id=None),
            hit("wrong-session", session_id=OTHER_SESSION),
            hit("wrong-branch", session_id=SESSION, branch="other"),
            hit("valid", session_id=SESSION),
        ]

    engine.working_memory_search = working_memory_search  # type: ignore[attr-defined,method-assign]
    result = engine.retrieve(
        "deploy",
        tenant_id=TENANT,
        branch="main",
        filt={"session_id": SESSION, "evaluated_at": EVALUATED_AT},
    )

    assert [hit.id for hit in result.hits] == ["valid"]


def test_absent_session_fails_closed_without_reading_items() -> None:
    rows = [_item("visible")]
    assert working_memory_hits(
        rows,
        query="deploy",
        tenant_id=TENANT,
        session_id=None,
        evaluated_at=EVALUATED_AT,
    ) == []
    assert build_working_memory_hits(
        rows,
        query="deploy",
        tenant_id=TENANT,
        session_id="",
        evaluated_at=EVALUATED_AT,
    ) == []


def test_task_relevance_beats_recency_and_ties_use_item_id() -> None:
    old_task_match = _item(
        "b-item",
        task_id="task-deploy",
        content="A generic note.",
        created_at=EVALUATED_AT - timedelta(minutes=9),
        expires_at=EVALUATED_AT + timedelta(minutes=1),
    )
    recent_content_match = _item(
        "recent",
        task_id="task-unrelated",
        content="Deploy this unrelated note.",
        created_at=EVALUATED_AT - timedelta(seconds=1),
        expires_at=EVALUATED_AT + timedelta(minutes=9),
    )
    tie_a = _item("a-item", content="same", task_id="task-same")
    tie_b = _item("c-item", content="same", task_id="task-same")
    hits = working_memory_hits(
        [recent_content_match, tie_b, old_task_match, tie_a],
        query="deploy",
        tenant_id=TENANT,
        session_id=SESSION,
        evaluated_at=EVALUATED_AT,
    )

    assert hits[0].id == "b-item"
    assert [hit.id for hit in hits[-2:]] == ["a-item", "c-item"]
    assert hits[0].metadata["working_memory"]["task_relevance"] > hits[1].metadata["working_memory"]["task_relevance"]


def test_provenance_metadata_and_data_only_sink_rail_are_preserved() -> None:
    row = _item(
        "provenance",
        trust_tier=4,
        sensitivity=3,
        evidence_ids=["cid-a", "cid-b"],
        access_policy={"tenant": TENANT, "max_sensitivity": 3},
        metadata={"reality_class": "simulated", "source_type": "tool", "custom": {"x": 1}},
    )
    hit = working_memory_hits(
        [row],
        query="deploy",
        tenant_id=TENANT,
        session_id=SESSION,
        evaluated_at=EVALUATED_AT,
    )[0]

    assert hit.provenance == ["cid-a", "cid-b"]
    assert hit.kind == "working"
    assert hit.metadata["working_item_id"] == "provenance"
    assert hit.trust_tier == 4
    assert hit.sensitivity == 3
    assert hit.metadata["access_policy"]["max_sensitivity"] == 3
    assert hit.metadata["reality_class"] == "simulated"
    assert hit.metadata["retrieved_text"]["instruction_authority"] == "none"
    assert hit.metadata["working_memory"]["data_only"] is True
    with pytest.raises(SystemPromptSinkError):
        assemble_system_prompt([hit], sink="system_prompt")


def test_pipeline_fuses_working_as_fourth_channel_and_shares_budget() -> None:
    engine = LocalMemoryEngine()
    rows = [
        _item("small", content="Deploy now."),
        _item("oversize", content="Deploy " + ("very-long-context " * 100)),
    ]
    calls: list[tuple[str, str, datetime]] = []

    def list_working(tenant_id: str, session_id: str, *, as_of: datetime) -> list[object]:
        calls.append((tenant_id, session_id, as_of))
        return rows

    engine.list_working = list_working  # type: ignore[attr-defined,method-assign]
    engine.policy.token_budget = 4
    result = engine.retrieve(
        "deploy",
        tenant_id=TENANT,
        branch="main",
        filt={"session_id": SESSION, "evaluated_at": EVALUATED_AT},
    )

    assert calls == [(TENANT, SESSION, EVALUATED_AT)]
    assert result.explain["channels"]["working_memory"] == 2
    assert result.explain["working_memory"]["candidate_count"] == 2
    assert result.explain["working_memory"]["selected_count"] == 1
    assert [hit.id for hit in result.hits] == ["small"]
    assert result.used_tokens <= result.token_budget


def test_pipeline_without_session_selector_does_not_add_working_route() -> None:
    engine = LocalMemoryEngine()
    called = False

    def list_working(*args: object, **kwargs: object) -> list[object]:
        nonlocal called
        called = True
        return [_item("should-not-read")]

    engine.list_working = list_working  # type: ignore[attr-defined,method-assign]
    result = engine.retrieve("deploy", tenant_id=TENANT, branch="main")

    assert called is False
    assert "working_memory" not in result.explain
    assert "working_memory" not in result.explain["channels"]


def test_sequential_and_parallel_working_route_identity_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_item("stable-a"), _item("stable-b", task_id="task-review", content="Review the deployment.")]
    results = []
    for parallel in ("0", "1"):
        monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", parallel)
        engine = LocalMemoryEngine()
        engine.list_working = lambda tenant_id, session_id, *, as_of: rows  # type: ignore[attr-defined,method-assign]
        results.append(
            engine.retrieve(
                "deploy",
                tenant_id=TENANT,
                branch="main",
                filt={"session_id": SESSION, "evaluated_at": EVALUATED_AT},
            ).to_dict()
        )

    assert results[0] == results[1]


def test_result_cache_key_changes_at_evaluation_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_RETRIEVAL_RESULT_CACHE_SIZE", "8")
    monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", "0")
    engine = LocalMemoryEngine()
    rows = [_item("cache-item", expires_at=EVALUATED_AT + timedelta(minutes=1))]
    calls = 0

    def list_working(tenant_id: str, session_id: str, *, as_of: datetime) -> list[object]:
        nonlocal calls
        calls += 1
        return rows

    engine.list_working = list_working  # type: ignore[attr-defined,method-assign]
    first = engine.retrieve(
        "deploy", tenant_id=TENANT, filt={"session_id": SESSION, "evaluated_at": EVALUATED_AT}
    )
    same_instant = engine.retrieve(
        "deploy", tenant_id=TENANT, filt={"session_id": SESSION, "evaluated_at": EVALUATED_AT}
    )
    expired = engine.retrieve(
        "deploy",
        tenant_id=TENANT,
        filt={"session_id": SESSION, "evaluated_at": EVALUATED_AT + timedelta(minutes=1)},
    )

    assert first.explain["working_memory"]["selected_count"] == 1
    assert same_instant.explain["retrieval_result_cache"]["hit"] is True
    assert expired.explain["working_memory"]["selected_count"] == 0
    assert expired.hits == []
    assert calls == 2


def test_working_hit_isolated_from_caller_mutation() -> None:
    row = _item("copy", metadata={"nested": {"value": 1}})
    hit = working_memory_hits(
        [row],
        query="deploy",
        tenant_id=TENANT,
        session_id=SESSION,
        evaluated_at=EVALUATED_AT,
    )[0]
    hit.metadata["nested"]["value"] = 99
    hit.provenance.append("mutated")

    assert row["metadata"] == {"nested": {"value": 1}}
    assert row["evidence_ids"] == ["evidence-copy"]


def test_naive_evaluation_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="evaluated_at"):
        working_memory_hits(
            [_item("naive")],
            query="deploy",
            tenant_id=TENANT,
            session_id=SESSION,
            evaluated_at=datetime(2026, 7, 18, 12, 0),
        )
    with pytest.raises(ValueError, match="evaluated_at"):
        working_memory_hits(
            [_item("naive-string")],
            query="deploy",
            tenant_id=TENANT,
            session_id=SESSION,
            evaluated_at="2026-07-18T12:00:00",
        )


def test_working_store_failure_does_not_suppress_durable_retrieval() -> None:
    engine = LocalMemoryEngine()

    def list_working(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("working store unavailable")

    engine.list_working = list_working  # type: ignore[attr-defined,method-assign]
    result = engine.retrieve(
        "deploy",
        tenant_id=TENANT,
        filt={"session_id": SESSION, "evaluated_at": EVALUATED_AT},
    )

    assert result.explain["working_memory"]["reason"] == "working_store_error"
    assert "working_memory" not in [hit.metadata.get("memory_type") for hit in result.hits]

"""Working-memory ranking must not reveal values hidden by field redaction."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.retrieval import working_memory_hits


CLOCK = datetime(2026, 7, 18, 12, tzinfo=UTC)


def test_explicit_sensitivity_ceiling_applies_without_access_context():
    item = {
        "item_id": "private",
        "tenant_id": "tenant",
        "session_id": "session",
        "task_id": "task",
        "kind": "active_goal",
        "content": "private",
        "created_at": CLOCK - timedelta(minutes=5),
        "expires_at": CLOCK + timedelta(minutes=5),
        "sensitivity": 2,
    }
    assert (
        working_memory_hits(
            [item],
            query="private",
            tenant_id="tenant",
            session_id="session",
            evaluated_at=CLOCK,
            policy_max_sensitivity=1,
        )
        == []
    )


@pytest.mark.parametrize(
    "policy",
    [
        {"expires_at": "2000-01-01T00:00:00Z"},
        {"hold:legal": True},
        {"unrecognized_restriction": True},
        {"allowed_residencies": ["eu"]},
    ],
)
def test_context_free_working_reads_fail_closed_on_unevaluated_policy(policy):
    item = {
        "item_id": "private",
        "tenant_id": "tenant",
        "session_id": "session",
        "task_id": "task",
        "kind": "active_goal",
        "content": "private",
        "created_at": CLOCK - timedelta(minutes=5),
        "expires_at": CLOCK + timedelta(minutes=5),
        "access_policy": policy,
    }
    assert (
        working_memory_hits(
            [item],
            query="private",
            tenant_id="tenant",
            session_id="session",
            evaluated_at=CLOCK,
        )
        == []
    )


@pytest.mark.parametrize("role", ["reader", "operator"])
def test_working_metadata_redaction_precedes_ranking_without_mutating_items(role):
    import copy

    items = [
        {
            "item_id": item_id,
            "tenant_id": "tenant",
            "session_id": "session",
            "task_id": "task",
            "kind": "active_goal",
            "content": "public",
            "created_at": CLOCK - timedelta(minutes=5),
            "expires_at": CLOCK + timedelta(minutes=5),
            "metadata": {"goal": secret, "public": "safe"},
            "access_policy": {
                "tenant": "tenant",
                "min_role_for_raw": "operator",
                "redact_fields": ["goal"],
            },
        }
        for item_id, secret in (("a", "orchid"), ("b", "cobalt"))
    ]
    original = copy.deepcopy(items)
    hits = working_memory_hits(
        items,
        query="cobalt",
        tenant_id="tenant",
        session_id="session",
        evaluated_at=CLOCK,
        access_context={"tenant_id": "tenant", "role": role},
        policy_max_sensitivity=3,
    )
    assert items == original
    assert len(hits) == 2
    if role == "reader":
        assert [hit.id for hit in hits] == ["a", "b"]
        assert hits[0].score == hits[1].score
        assert all(hit.metadata["goal"] == "[REDACTED:goal]" for hit in hits)
        assert "cobalt" not in json.dumps([hit.metadata for hit in hits])
    else:
        assert hits[0].id == "b"
        assert hits[0].metadata["goal"] == "cobalt"
        assert hits[0].score > hits[1].score
    assert all(hit.metadata["public"] == "safe" for hit in hits)


def _hits(role: str, query: str):
    items = [
        {
            "item_id": item_id,
            "tenant_id": "tenant",
            "session_id": "session",
            "task_id": "task",
            "kind": "active_goal",
            "content": json.dumps({"summary": secret, "note": "public"}),
            "created_at": CLOCK - timedelta(minutes=5),
            "expires_at": CLOCK + timedelta(minutes=5),
            "status": "active",
            "trust_tier": 2,
            "sensitivity": 1,
            "access_policy": {
                "tenant": "tenant",
                "min_role_for_raw": "operator",
                "redact_fields": ["summary"],
            },
        }
        for item_id, secret in (("a", "orchid"), ("b", "cobalt"))
    ]
    return working_memory_hits(
        items,
        query=query,
        tenant_id="tenant",
        session_id="session",
        evaluated_at=CLOCK,
        access_context={"tenant_id": "tenant", "role": role},
        policy_max_sensitivity=3,
    )


@pytest.mark.parametrize("query", ["orchid", "cobalt"])
def test_hidden_values_do_not_affect_reader_ranking(query: str) -> None:
    hits = _hits("reader", query)

    assert len(hits) == 2
    assert hits[0].text == hits[1].text
    assert "orchid" not in hits[0].text and "cobalt" not in hits[0].text
    assert hits[0].score == hits[1].score
    assert [hit.metadata["working_memory"]["content_relevance"] for hit in hits] == [
        0.0,
        0.0,
    ]
    assert [hit.id for hit in hits] == ["a", "b"]


@pytest.mark.parametrize("query, expected_id", [("orchid", "a"), ("cobalt", "b")])
def test_authorized_reader_can_rank_by_raw_values(query: str, expected_id: str) -> None:
    hits = _hits("operator", query)

    assert len(hits) == 2
    assert hits[0].id == expected_id
    assert query in hits[0].text
    assert hits[0].score > hits[1].score
    assert hits[0].metadata["working_memory"]["content_relevance"] > 0.0

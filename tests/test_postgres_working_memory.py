from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mnemosyne.postgres_engine import (
    PostgresEngine,
    PostgresUnavailableError,
    WorkingMemoryItem,
    _working_payload,
)


CREATED_AT = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)


def _item(**overrides: object) -> WorkingMemoryItem:
    values: dict[str, object] = {
        "item_id": "working-1",
        "tenant_id": "tenant-a",
        "session_id": "session-a",
        "user_id": "user-a",
        "agent_id": "agent-a",
        "kind": "active_goal",
        "task_id": "task-a",
        "content": "transient task state",
        "created_at": CREATED_AT,
        "expires_at": CREATED_AT + timedelta(minutes=5),
        "evidence_ids": ["00" * 32],
    }
    values.update(overrides)
    return WorkingMemoryItem(**values)


def test_working_payload_canonicalizes_utc_and_preserves_security_fields() -> None:
    item = _item(
        created_at=datetime(2026, 7, 18, 1, 0, tzinfo=UTC),
        expires_at=datetime(2026, 7, 18, 1, 5, tzinfo=UTC),
        capability_tags=["Data-Only"],
        metadata={"nested": ["value"]},
    )

    values = _working_payload(item)

    assert values["created_at"].tzinfo is UTC
    assert values["expires_at"].tzinfo is UTC
    assert values["capability_tags"] == ["Data-Only"]
    assert values["metadata"] == {"nested": ["value"]}


@pytest.mark.parametrize(
    "overrides",
    [
        {"created_at": datetime(2026, 7, 18, 8, 0), "expires_at": CREATED_AT + timedelta(minutes=5)},
        {"expires_at": CREATED_AT + timedelta(hours=24, seconds=1)},
    ],
)
def test_working_payload_rejects_unsafe_ttl_boundaries(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _working_payload(_item(**overrides))


def test_schema_declares_working_memory_identity_indexes_rls_and_audit_idempotency() -> None:
    schema = Path(__file__).parents[1].joinpath("sql", "schema.sql").read_text()

    assert "PRIMARY KEY (tenant_id, session_id, item_id)" in schema
    assert "CREATE INDEX IF NOT EXISTS working_memory_scope_created_idx" in schema
    assert "CREATE INDEX IF NOT EXISTS working_memory_expiry_idx" in schema
    assert "ALTER TABLE working_memory FORCE ROW LEVEL SECURITY" in schema
    assert "CREATE POLICY working_memory_tenant_isolation" in schema
    assert "audit_log_tenant_event_unique" in schema


def test_postgres_unavailable_does_not_fall_back_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = PostgresEngine("postgresql://unavailable/mnemosyne", require_safe_role=False)
    monkeypatch.setattr(engine, "ensure_tenant_and_branch", lambda *_args, **_kwargs: None)

    def unavailable() -> object:
        raise PostgresUnavailableError("postgres unavailable")

    monkeypatch.setattr(engine, "connect", unavailable)

    with pytest.raises(PostgresUnavailableError, match="postgres unavailable"):
        engine.put_working(_item())
    assert not hasattr(engine, "working_memory")

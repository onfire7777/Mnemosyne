"""Lane B1 perf-surgery tests: PostgresEngine connection reuse, evidence
lexeme schema, and the MMR embedding-space switch.

Pool logic is unit-tested against a fake psycopg module (no live DB): reuse
across acquires, health-check replacement, per-acquire tenant clearing, the
cross-tenant reuse invariant, and the MNEMOSYNE_PG_CONN_REUSE kill-switch.

Live coverage (real RLS tenant isolation across a reused connection, evidence
lexeme byte-identity, stored-vector MMR) runs only when
MNEMOSYNE_POSTGRES_DSN is set, matching tests/test_postgres_engine_live.py.
"""

from __future__ import annotations

import os
import threading
import types
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.algorithms import mmr_select
from mnemosyne.models import Evidence, Hit
from mnemosyne.postgres_engine import (
    PostgresEngine,
    _PostgresConnectionPool,
    _vector_from_literal,
)
from mnemosyne.text import hashing_embedding

REPO_ROOT = Path(__file__).resolve().parents[1]
TENANT_CLEAR_FRAGMENT = "set_config('mnemosyne.tenant_id', '', false)"


# --------------------------------------------------------------------------- #
# Fakes: emulate the psycopg surface the engine + pool touch, including the
# transaction-local vs session-level semantics of set_config that tenant RLS
# binding relies on.
# --------------------------------------------------------------------------- #


class FakeCursor:
    def __init__(self, conn: "FakeConnection"):
        self._conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self._conn.record(sql, params)

    def fetchall(self) -> list[Any]:
        return []

    def fetchone(self) -> Any:
        return None


class FakeConnection:
    """Tracks statements plus a faithful model of set_config scoping:

    - ``set_config(..., %s, true)`` (call-site ``_set_tenant``) is
      transaction-local: it reverts at commit/rollback.
    - ``set_config(..., '', false)`` (pool clear) is session-level: it
      survives commit.
    """

    def __init__(self, name: str):
        self.name = name
        self.closed = False
        self.statements: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_next_execute = False
        self.session_tenant: str | None = None  # None == never set (fresh)
        self.tx_tenant: str | None = None

    def record(self, sql: str, params: tuple[Any, ...] | None) -> None:
        if self.fail_next_execute:
            self.fail_next_execute = False
            raise RuntimeError("simulated dead connection")
        flat = " ".join(sql.split())
        self.statements.append(flat)
        if "set_config('mnemosyne.tenant_id'" in flat:
            if params:
                self.tx_tenant = str(params[0])
            elif TENANT_CLEAR_FRAGMENT in flat:
                self.session_tenant = ""

    def effective_tenant(self) -> str | None:
        return self.tx_tenant if self.tx_tenant is not None else self.session_tenant

    def cursor(self, *args: Any, **kwargs: Any) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1
        self.tx_tenant = None

    def rollback(self) -> None:
        self.rollbacks += 1
        self.tx_tenant = None

    def close(self) -> None:
        self.closed = True

    # psycopg3 connection-context semantics for the reuse-off legacy path:
    # commit/rollback, then close.
    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False


def make_engine(
    monkeypatch: pytest.MonkeyPatch, *, reuse: bool
) -> tuple[PostgresEngine, list[FakeConnection]]:
    if reuse:
        monkeypatch.delenv("MNEMOSYNE_PG_CONN_REUSE", raising=False)
    else:
        monkeypatch.setenv("MNEMOSYNE_PG_CONN_REUSE", "0")
    engine = PostgresEngine("postgresql://unit-test-fake", require_safe_role=False)
    created: list[FakeConnection] = []

    def factory(dsn: str) -> FakeConnection:
        conn = FakeConnection(f"conn-{len(created)}")
        created.append(conn)
        return conn

    engine._psycopg = types.SimpleNamespace(
        connect=factory, rows=types.SimpleNamespace(dict_row=object())
    )
    engine._jsonb = object()
    return engine, created


# --------------------------------------------------------------------------- #
# Pool unit tests (no live DB).
# --------------------------------------------------------------------------- #


def test_connection_reused_across_acquires(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, created = make_engine(monkeypatch, reuse=True)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 2")
    assert len(created) == 1, "second acquire must reuse the pooled connection"
    assert not created[0].closed
    assert created[0].commits >= 2  # one per lease exit


def test_kill_switch_restores_fresh_connection_per_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, created = make_engine(monkeypatch, reuse=False)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 2")
    assert len(created) == 2, "kill-switch must disable reuse"
    assert created[0].closed and created[1].closed
    # Exact legacy statement stream: no pool-injected tenant clear.
    for conn in created:
        assert not any(TENANT_CLEAR_FRAGMENT in sql for sql in conn.statements)
    assert engine._pool is None


def test_health_check_replaces_broken_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, created = make_engine(monkeypatch, reuse=True)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    created[0].fail_next_execute = True  # reset probe will fail on reuse
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 2")
    assert len(created) == 2, "broken pooled connection must be replaced"
    assert created[0].closed, "broken connection must be discarded (closed)"
    assert not created[1].closed
    assert "SELECT 2" in created[1].statements


def test_closed_connection_replaced_without_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, created = make_engine(monkeypatch, reuse=True)
    with engine.connect() as conn:
        pass
    created[0].closed = True
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    assert len(created) == 2
    assert "SELECT 1" in created[1].statements


def test_tenant_clear_precedes_caller_statements_on_every_acquire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, created = make_engine(monkeypatch, reuse=True)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 'first-lease'")
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 'second-lease'")
    statements = created[0].statements
    clear_indices = [i for i, sql in enumerate(statements) if TENANT_CLEAR_FRAGMENT in sql]
    first_idx = statements.index("SELECT 'first-lease'")
    second_idx = statements.index("SELECT 'second-lease'")
    # One clear per acquire (fresh AND reused), each strictly before the
    # caller SQL of its lease.
    assert len(clear_indices) == 2
    assert clear_indices[0] < first_idx
    assert first_idx < clear_indices[1] < second_idx


def test_cross_tenant_reuse_cannot_leak_previous_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, created = make_engine(monkeypatch, reuse=True)
    tenant_a = str(uuid4())
    with engine.connect() as conn:
        with conn.cursor() as cur:
            # Call-site tenant binding, exactly as PostgresEngine._set_tenant.
            cur.execute("SELECT set_config('mnemosyne.tenant_id', %s, true)", (tenant_a,))
            assert created[0].effective_tenant() == tenant_a
    # Lease exit committed: the transaction-local binding is gone.
    assert created[0].effective_tenant() != tenant_a
    with engine.connect() as conn:
        # Reused physical connection: before tenant B (or any caller) runs a
        # statement, the effective tenant is the cleared sentinel '' which
        # mnemosyne_current_tenant() maps to NULL (deny-all) — never tenant A.
        assert created[0].effective_tenant() == ""
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM evidence")
        assert created[0].effective_tenant() == ""
    assert len(created) == 1  # genuinely the same physical connection


def test_lease_commits_on_clean_exit_and_rolls_back_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, created = make_engine(monkeypatch, reuse=True)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    commits_after_clean = created[0].commits
    with pytest.raises(RuntimeError, match="caller boom"):
        with engine.connect() as conn:
            raise RuntimeError("caller boom")
    assert created[0].commits == commits_after_clean + 1  # +1 from acquire clear only
    assert created[0].rollbacks >= 1
    assert not created[0].closed, "rolled-back connection returns to the pool"


def test_pool_bounds_idle_connections() -> None:
    created: list[FakeConnection] = []

    def factory() -> FakeConnection:
        conn = FakeConnection(f"conn-{len(created)}")
        created.append(conn)
        return conn

    pool = _PostgresConnectionPool(factory, max_idle=1)
    lease_a = pool.acquire()
    lease_b = pool.acquire()
    assert len(created) == 2
    lease_a.__exit__(None, None, None)
    lease_b.__exit__(None, None, None)
    assert len(pool._idle) == 1, "idle pool must stay bounded"
    assert created[1].closed, "overflow release must close the connection"


def test_pool_is_thread_safe_under_concurrent_acquires() -> None:
    created: list[FakeConnection] = []
    lock = threading.Lock()

    def factory() -> FakeConnection:
        with lock:
            conn = FakeConnection(f"conn-{len(created)}")
            created.append(conn)
        return conn

    pool = _PostgresConnectionPool(factory, max_idle=8)
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            for _ in range(25):
                with pool.acquire() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
        except BaseException as exc:  # pragma: no cover - failure diagnostics
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors
    assert len(created) <= 8, "never more physical connections than concurrent holders"
    live = [conn for conn in created if not conn.closed]
    assert live, "pool retains reusable connections"


# --------------------------------------------------------------------------- #
# Env registration + MMR space switch (no live DB).
# --------------------------------------------------------------------------- #


def test_new_env_vars_registered_in_config_drift_checks() -> None:
    text = (REPO_ROOT / "CONFIG-DRIFT-CHECKS.md").read_text(encoding="utf-8")
    assert "MNEMOSYNE_PG_CONN_REUSE" in text
    assert "MNEMOSYNE_PG_MMR_SPACE" in text


def _hit(idx: int, text: str, *, kind: str = "evidence") -> Hit:
    return Hit(
        id=f"{idx:02d}" * 16 if kind == "evidence" else str(uuid4()),
        kind=kind,  # type: ignore[arg-type]
        tenant_id="tenant-mmr",
        branch="main",
        text=text,
        score=1.0 - idx * 0.1,
        channel="postgres_fts",
    )


def test_mmr_default_space_is_hashing_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MNEMOSYNE_PG_MMR_SPACE", raising=False)
    engine, _ = make_engine(monkeypatch, reuse=True)
    hits = [_hit(i, text) for i, text in enumerate(["alpha beat", "alpha beta", "gamma delta", "epsilon zeta"])]
    query = "alpha beta"
    got = engine._mmr(query, hits, 3)
    expected = mmr_select(
        hits,
        3,
        query_vec=hashing_embedding(query),
        embed_hit=lambda hit: hashing_embedding(hit.text),
        mmr_lambda=engine.policy.mmr_lambda,
    )
    assert [hit.id for hit in got] == [hit.id for hit in expected]


def test_mmr_stored_space_uses_stored_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, _ = make_engine(monkeypatch, reuse=True)
    hits = [_hit(i, text) for i, text in enumerate(["one", "two", "three"])]
    for hit in hits:
        hit.score = 1.0  # equal base scores: only the vector space can rank
    stored = {
        ("evidence", hits[0].id): [1.0, 0.0, 0.0],
        ("evidence", hits[1].id): [0.0, 1.0, 0.0],  # only hit aligned with query
        ("evidence", hits[2].id): [1.0, 0.0, 0.0],
    }
    monkeypatch.setenv("MNEMOSYNE_PG_MMR_SPACE", "stored")
    monkeypatch.setattr(engine, "_stored_hit_vectors", lambda hits: stored)
    query_vec = [0.0, 1.0, 0.0]
    monkeypatch.setattr(
        "mnemosyne.postgres_engine.embed_query", lambda provider, query: query_vec
    )
    got = engine._mmr("anything", hits, 2)
    expected = mmr_select(
        hits,
        2,
        query_vec=query_vec,
        embed_hit=lambda hit: stored.get((hit.kind, hit.id)),
        mmr_lambda=engine.policy.mmr_lambda,
    )
    assert [hit.id for hit in got] == [hit.id for hit in expected]
    # With equal base scores, only the stored-space relevance can promote
    # hits[1] over the input-order tie-break — proving pgvector rows drove MMR.
    assert got[0].id == hits[1].id
    assert got[1].id == hits[0].id  # remaining tie falls back to first-wins


def test_mmr_stored_space_missing_vectors_fall_back_to_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _ = make_engine(monkeypatch, reuse=True)
    hits = [_hit(i, text) for i, text in enumerate(["one", "two"])]
    monkeypatch.setenv("MNEMOSYNE_PG_MMR_SPACE", "stored")
    monkeypatch.setattr(engine, "_stored_hit_vectors", lambda hits: {})
    monkeypatch.setattr(
        "mnemosyne.postgres_engine.embed_query", lambda provider, query: [1.0, 0.0]
    )
    got = engine._mmr("anything", hits, 2)
    # No vectors → relevance 0 and no penalty for every hit; ordering falls
    # back to hit.score (input order here).
    assert [hit.id for hit in got] == [hits[0].id, hits[1].id]


class _StoredVectorFakeCursor(FakeCursor):
    """FakeCursor that serves canned rows for the _stored_hit_vectors query."""

    def __init__(self, conn: "_StoredVectorFakeConnection"):
        super().__init__(conn)
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        super().execute(sql, params)
        flat = " ".join(sql.split())
        if "FROM evidence" in flat and "embedding::text" in flat:
            self._rows = self._conn.evidence_rows
        else:
            self._rows = []

    def fetchall(self) -> list[Any]:
        return self._rows


class _StoredVectorFakeConnection(FakeConnection):
    def __init__(self, name: str, evidence_rows: list[tuple[Any, ...]]):
        super().__init__(name)
        self.evidence_rows = evidence_rows

    def cursor(self, *args: Any, **kwargs: Any) -> FakeCursor:
        return _StoredVectorFakeCursor(self)


def test_stored_hit_vectors_gate_redacted_private_hits_to_hashing_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirror of the vector channel's may_use_stored_embedding gate
    (postgres_engine vector_search): a private-partition hit whose caller
    decision was redacted must not expose its stored raw vector to MMR — it
    falls back to the hashing embedding of the (already redacted) hit text.
    Permitted hits keep the stored vector."""
    engine, _ = make_engine(monkeypatch, reuse=True)
    public_redacted = _hit(0, "public partition text")
    private_ok = _hit(1, "private partition, full-read caller")
    private_redacted = _hit(2, "private partition, [REDACTED] projection")
    private_no_privacy_meta = _hit(3, "private partition, unrecorded decision")
    public_redacted.metadata = {"privacy": {"redacted": True}}  # public: redaction irrelevant
    private_ok.metadata = {"privacy": {"redacted": False}}
    private_redacted.metadata = {"privacy": {"redacted": True}}
    private_no_privacy_meta.metadata = {}

    def row(hit: Hit, literal: str, partition: str) -> tuple[Any, ...]:
        # (cid, embedding::text, sensitivity, access_policy, embedding_partition)
        return (bytes.fromhex(hit.id), literal, 2, {}, partition)

    conn = _StoredVectorFakeConnection(
        "stored-vec",
        [
            row(public_redacted, "[1,0]", "public"),
            row(private_ok, "[0,1]", "private"),
            row(private_redacted, "[1,1]", "private"),
            row(private_no_privacy_meta, "[0.5,0.5]", "private"),
        ],
    )
    monkeypatch.setattr(engine, "connect", lambda: conn)
    hits = [public_redacted, private_ok, private_redacted, private_no_privacy_meta]
    vectors = engine._stored_hit_vectors(hits)
    assert vectors[("evidence", public_redacted.id)] == [1.0, 0.0], (
        "public partition keeps the stored vector even for a redacted decision"
    )
    assert vectors[("evidence", private_ok.id)] == [0.0, 1.0], (
        "non-redacted caller keeps the private stored vector"
    )
    assert vectors[("evidence", private_redacted.id)] == hashing_embedding(private_redacted.text), (
        "redacted caller decision must fall back to hashing of the redacted text"
    )
    assert vectors[("evidence", private_no_privacy_meta.id)] == hashing_embedding(
        private_no_privacy_meta.text
    ), "missing privacy metadata is conservatively treated as redacted"


def test_vector_from_literal_parses_and_rejects() -> None:
    assert _vector_from_literal("[1,2.5,-3]") == [1.0, 2.5, -3.0]
    assert _vector_from_literal(" [0.1, 0.2] ") == [0.1, 0.2]
    assert _vector_from_literal(None) is None
    assert _vector_from_literal("") is None
    assert _vector_from_literal("[]") is None
    assert _vector_from_literal("not-a-vector") is None
    assert _vector_from_literal("[a,b]") is None


# --------------------------------------------------------------------------- #
# Live coverage — requires MNEMOSYNE_POSTGRES_DSN (dev compose Postgres).
# --------------------------------------------------------------------------- #


def live_dsn() -> str:
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    return dsn


def _live_engine() -> PostgresEngine:
    pytest.importorskip("psycopg")
    return PostgresEngine(live_dsn(), require_safe_role=False)


def _append(engine: PostgresEngine, tenant: str, content: str) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=f"user-{tenant}",
            actor="user",
            source_type="perf-lane-test",
            content=content,
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )


def test_live_cross_tenant_isolation_across_reused_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MNEMOSYNE_PG_CONN_REUSE", raising=False)
    engine = _live_engine()
    suffix = uuid4().hex[:12]
    tenant_a = f"perf-pool-a-{suffix}"
    tenant_b = f"perf-pool-b-{suffix}"
    marker = f"poolmarker{suffix}"
    _append(engine, tenant_a, f"{marker} northern lighthouse for tenant A")
    _append(engine, tenant_b, f"{marker} southern observatory for tenant B")
    assert engine._pool is not None and engine._pool._idle, "reuse pool must be active"

    hits_a = engine.lexical_search(marker, 10, {"tenant_id": tenant_a})
    hits_b = engine.lexical_search(marker, 10, {"tenant_id": tenant_b})
    assert hits_a and all(hit.tenant_id == tenant_a for hit in hits_a)
    assert hits_b and all(hit.tenant_id == tenant_b for hit in hits_b)
    assert all("tenant B" not in hit.text for hit in hits_a)
    assert all("tenant A" not in hit.text for hit in hits_b)

    # Raw probe on the reused physical connection: between leases the tenant
    # GUC is the cleared sentinel, never the previous tenant.
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('mnemosyne.tenant_id', true)")
            value = cur.fetchone()[0]
    assert value in (None, ""), f"tenant residue leaked across reuse: {value!r}"
    engine.close_connections()


def test_live_connection_actually_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_PG_CONN_REUSE", raising=False)
    engine = _live_engine()
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            first_pid = cur.fetchone()[0]
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            second_pid = cur.fetchone()[0]
    assert first_pid == second_pid, "same server backend proves TCP/TLS/auth reuse"
    engine.close_connections()


def test_live_kill_switch_opens_fresh_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_PG_CONN_REUSE", "0")
    engine = _live_engine()
    pids = []
    for _ in range(2):
        with engine.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_backend_pid()")
                pids.append(cur.fetchone()[0])
    assert pids[0] != pids[1]
    assert engine._pool is None


def test_live_evidence_lexeme_column_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MNEMOSYNE_PG_CONN_REUSE", raising=False)
    engine = _live_engine()
    suffix = uuid4().hex[:12]
    tenant = f"perf-lexeme-{suffix}"
    marker = f"lexememarker{suffix}"
    _append(engine, tenant, f"{marker} stored generated tsvector column check")
    hits = engine.lexical_search(marker, 5, {"tenant_id": tenant})
    assert hits and marker in hits[0].text

    from mnemosyne.postgres_engine import _stable_uuid

    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_generated FROM information_schema.columns"
                " WHERE table_name = 'evidence' AND column_name = 'lexeme'"
            )
            row = cur.fetchone()
            assert row is not None and row[0] == "ALWAYS"
            cur.execute("SELECT count(*) FROM pg_indexes WHERE indexname = 'evidence_lexeme_gin'")
            assert cur.fetchone()[0] == 1
            # Byte-identity of ranking inputs: the stored column equals the
            # previous query-time expression for every visible row.
            engine._set_tenant(cur, _stable_uuid("tenant", tenant))
            cur.execute(
                "SELECT count(*) FROM evidence WHERE tenant_id = %s"
                " AND lexeme IS DISTINCT FROM to_tsvector('english', coalesce(content, ''))",
                (_stable_uuid("tenant", tenant),),
            )
            assert cur.fetchone()[0] == 0
    engine.close_connections()


def test_live_mmr_stored_space_returns_stored_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MNEMOSYNE_PG_CONN_REUSE", raising=False)
    engine = _live_engine()
    suffix = uuid4().hex[:12]
    tenant = f"perf-mmr-{suffix}"
    marker = f"mmrmarker{suffix}"
    for text in ("solar panel maintenance", "solar panel upkeep", "harbor tide tables"):
        _append(engine, tenant, f"{marker} {text}")
    hits = engine.lexical_search(marker, 10, {"tenant_id": tenant})
    assert len(hits) == 3

    vectors = engine._stored_hit_vectors(hits)
    assert vectors, "public-partition evidence must expose stored vectors"
    assert all(len(vector) == 1024 for vector in vectors.values())

    monkeypatch.setenv("MNEMOSYNE_PG_MMR_SPACE", "stored")
    stored_selection = engine._mmr(f"{marker} solar panel", hits, 2)
    assert len(stored_selection) == 2
    assert {hit.id for hit in stored_selection} <= {hit.id for hit in hits}

    monkeypatch.delenv("MNEMOSYNE_PG_MMR_SPACE", raising=False)
    default_selection = engine._mmr(f"{marker} solar panel", hits, 2)
    expected_default = mmr_select(
        hits,
        2,
        query_vec=hashing_embedding(f"{marker} solar panel"),
        embed_hit=lambda hit: hashing_embedding(hit.text),
        mmr_lambda=engine.policy.mmr_lambda,
    )
    assert [hit.id for hit in default_selection] == [hit.id for hit in expected_default]
    engine.close_connections()

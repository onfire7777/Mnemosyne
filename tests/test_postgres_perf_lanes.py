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

import mnemosyne.postgres_engine as postgres_engine
from mnemosyne.algorithms import mmr_select
from mnemosyne.calibration import CalibrationSet
from mnemosyne.models import Evidence, Hit
from mnemosyne.postgres_engine import (
    _PGVECTOR_HNSW_EF_SEARCH_DEEP,
    _PGVECTOR_HNSW_EF_SEARCH_FAST,
    _PGVECTOR_HNSW_ITERATIVE_SCAN,
    PostgresEngine,
    _PostgresConnectionPool,
    _null_embedding_fallback_limit,
    _pgvector_hnsw_ef_search,
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

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        prepare: bool | None = None,
    ) -> None:
        self._conn.record(sql, params, prepare=prepare)

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
        self.statement_params: list[tuple[Any, ...] | None] = []
        self.statement_prepare_flags: list[bool | None] = []

    def record(
        self,
        sql: str,
        params: tuple[Any, ...] | None,
        *,
        prepare: bool | None = None,
    ) -> None:
        if self.fail_next_execute:
            self.fail_next_execute = False
            raise RuntimeError("simulated dead connection")
        flat = " ".join(sql.split())
        self.statements.append(flat)
        self.statement_params.append(params)
        self.statement_prepare_flags.append(prepare)
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


def test_engine_collection_closes_idle_connections_without_cyclic_gc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pool must not strongly reference the engine: deployed stateless MCP
    mode builds a throwaway engine per tool call and never calls
    close_connections(), so dropping the last engine reference alone — no
    gc.collect() — must close the idle pooled connections (weakref factory +
    weakref.finalize, not a cyclic-GC-deferred __del__)."""
    engine, created = make_engine(monkeypatch, reuse=True)
    with engine.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    assert len(created) == 1
    assert not created[0].closed, "connection is idle in the pool while the engine lives"
    del engine  # refcount drop only; a ref cycle would defer this to gc.collect()
    assert created[0].closed, "idle pooled connection must close when the engine is dropped"


# --------------------------------------------------------------------------- #
# Env registration + MMR space switch (no live DB).
# --------------------------------------------------------------------------- #


def test_new_env_vars_registered_in_config_drift_checks() -> None:
    text = (REPO_ROOT / "CONFIG-DRIFT-CHECKS.md").read_text(encoding="utf-8")
    assert "MNEMOSYNE_PG_CONN_REUSE" in text
    assert "MNEMOSYNE_PG_MMR_SPACE" in text
    assert "MNEMOSYNE_PG_PREPARE_HOT_QUERIES" in text


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

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        prepare: bool | None = None,
    ) -> None:
        super().execute(sql, params, prepare=prepare)
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


class _NullFallbackFakeCursor(FakeCursor):
    def __init__(self, conn: "_NullFallbackFakeConnection"):
        super().__init__(conn)
        self._rows: list[dict[str, Any]] = []
        self._row: dict[str, Any] | None = None

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        prepare: bool | None = None,
    ) -> None:
        super().execute(sql, params, prepare=prepare)
        flat = " ".join(sql.split())
        self._rows = []
        self._row = None
        if "FROM evidence" in flat and "embedding IS NULL" in flat and "LIMIT" in flat:
            self._conn.fallback_query_params = params
            self._rows = self._conn.fallback_rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _NullFallbackFakeConnection(FakeConnection):
    def __init__(
        self,
        name: str,
        *,
        fallback_rows: list[dict[str, Any]],
    ):
        super().__init__(name)
        self.fallback_rows = fallback_rows
        self.fallback_query_params: tuple[Any, ...] | None = None

    def cursor(self, *args: Any, **kwargs: Any) -> FakeCursor:
        return _NullFallbackFakeCursor(self)


class _CalibrationFakeCursor(FakeCursor):
    def __init__(self, conn: "_CalibrationFakeConnection"):
        super().__init__(conn)
        self._row: dict[str, Any] | None = None

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        prepare: bool | None = None,
    ) -> None:
        super().execute(sql, params, prepare=prepare)
        flat = " ".join(sql.split())
        self._row = None
        if "FROM conformal_calibration" in flat:
            self._conn.calibration_selects += 1
            self._row = self._conn.calibration_row

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _CalibrationFakeConnection(FakeConnection):
    def __init__(self, name: str, calibration_row: dict[str, Any] | None):
        super().__init__(name)
        self.calibration_row = calibration_row
        self.calibration_selects = 0

    def cursor(self, *args: Any, **kwargs: Any) -> FakeCursor:
        return _CalibrationFakeCursor(self)


def test_postgres_null_embedding_fallback_is_capped_and_observable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _ = make_engine(monkeypatch, reuse=True)
    fallback_limit = _null_embedding_fallback_limit(5)

    def fallback_row(idx: int) -> dict[str, Any]:
        return {
            "cid": idx.to_bytes(32, "big"),
            "branch": "main",
            "content": "legacy null embedding quartz fallback",
            "content_pointer": None,
            "modality": "text",
            "metadata": {},
            "trust_tier": 0,
            "sensitivity": 0,
            "access_policy": {},
            "actor": "user",
            "source_type": "legacy",
            "embedding_partition": "public",
        }

    conn = _NullFallbackFakeConnection(
        "null-fallback",
        fallback_rows=[fallback_row(idx) for idx in range(1, fallback_limit + 2)],
    )
    monkeypatch.setattr(engine, "connect", lambda: conn)
    monkeypatch.setattr(postgres_engine, "cosine", lambda *_args: 0.75)

    hits = engine.vector_search("quartz fallback", 5, {"tenant_id": "tenant", "branch": "main"})

    assert conn.fallback_query_params is not None
    assert conn.fallback_query_params[-1] == fallback_limit + 1
    fallback_query = next(
        sql for sql in conn.statements if "FROM evidence" in sql and "embedding IS NULL" in sql
    )
    assert "embedding_partition <> 'none'" in fallback_query
    hit = next(hit for hit in hits if hit.channel == "postgres_dense_fallback")
    assert len([hit for hit in hits if hit.channel == "postgres_dense_fallback"]) == 5
    assert hit.metadata["null_embedding_candidates_observed"] == fallback_limit + 1
    assert hit.metadata["null_embedding_fallback_limit"] == fallback_limit
    assert hit.metadata["null_embedding_fallback_truncated"] is True


def test_postgres_vector_search_sets_hnsw_query_knobs_before_vector_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _ = make_engine(monkeypatch, reuse=True)
    conn = _NullFallbackFakeConnection("hnsw", fallback_rows=[])
    monkeypatch.setattr(engine, "connect", lambda: conn)

    engine.vector_search(
        "quartz fallback",
        5,
        {"tenant_id": "tenant", "branch": "main", "_retrieval_deep": True},
    )

    tenant_idx = next(i for i, sql in enumerate(conn.statements) if "mnemosyne.tenant_id" in sql)
    ef_idx = next(i for i, sql in enumerate(conn.statements) if "hnsw.ef_search" in sql)
    iterative_idx = next(i for i, sql in enumerate(conn.statements) if "hnsw.iterative_scan" in sql)
    vector_query_idx = next(i for i, sql in enumerate(conn.statements) if "ORDER BY embedding <=>" in sql)
    assert tenant_idx < ef_idx < iterative_idx < vector_query_idx
    assert conn.statement_params[ef_idx] == (str(_PGVECTOR_HNSW_EF_SEARCH_DEEP),)
    assert conn.statement_params[iterative_idx] == (_PGVECTOR_HNSW_ITERATIVE_SCAN,)


def test_postgres_hot_retrieval_selects_force_psycopg_prepare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MNEMOSYNE_PG_PREPARE_HOT_QUERIES", raising=False)

    vector_engine, _ = make_engine(monkeypatch, reuse=True)
    vector_conn = _NullFallbackFakeConnection("vector-prepared", fallback_rows=[])
    monkeypatch.setattr(vector_engine, "connect", lambda: vector_conn)
    vector_engine.vector_search("quartz fallback", 5, {"tenant_id": "tenant", "branch": "main"})

    vector_prepared = [
        sql
        for sql, prepare in zip(vector_conn.statements, vector_conn.statement_prepare_flags, strict=True)
        if prepare is True
    ]
    assert len([sql for sql in vector_prepared if "ORDER BY embedding <=>" in sql]) == 2
    assert not any("mnemosyne.tenant_id" in sql for sql in vector_prepared)
    assert not any("hnsw." in sql for sql in vector_prepared)
    assert not any("embedding IS NULL" in sql for sql in vector_prepared)

    lexical_engine, _ = make_engine(monkeypatch, reuse=True)
    lexical_conn = _NullFallbackFakeConnection("lexical-prepared", fallback_rows=[])
    monkeypatch.setattr(lexical_engine, "connect", lambda: lexical_conn)
    monkeypatch.setattr(lexical_engine, "_local_rank", lambda *_args, **_kwargs: [])
    lexical_engine.lexical_search("quartz fallback", 5, {"tenant_id": "tenant", "branch": "main"})

    lexical_prepared = [
        sql
        for sql, prepare in zip(lexical_conn.statements, lexical_conn.statement_prepare_flags, strict=True)
        if prepare is True
    ]
    assert len([sql for sql in lexical_prepared if "plainto_tsquery" in sql]) == 2
    assert not any("mnemosyne.tenant_id" in sql for sql in lexical_prepared)


def test_postgres_hot_query_prepare_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MNEMOSYNE_PG_PREPARE_HOT_QUERIES", "0")
    engine, _ = make_engine(monkeypatch, reuse=True)
    conn = _NullFallbackFakeConnection("prepare-off", fallback_rows=[])
    monkeypatch.setattr(engine, "connect", lambda: conn)

    engine.vector_search("quartz fallback", 5, {"tenant_id": "tenant", "branch": "main"})

    assert not any(prepare is True for prepare in conn.statement_prepare_flags)


def test_pgvector_hnsw_ef_search_uses_fast_default_and_deep_route() -> None:
    assert _pgvector_hnsw_ef_search({}) == _PGVECTOR_HNSW_EF_SEARCH_FAST
    assert _pgvector_hnsw_ef_search({"_retrieval_deep": False}) == _PGVECTOR_HNSW_EF_SEARCH_FAST
    assert _pgvector_hnsw_ef_search({"_retrieval_deep": True}) == _PGVECTOR_HNSW_EF_SEARCH_DEEP


def test_postgres_calibration_positive_lookup_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _ = make_engine(monkeypatch, reuse=True)
    conn = _CalibrationFakeConnection(
        "calibration-hit",
        {"memory_type": "fact", "scores": [0.2, 0.4], "target_coverage": 0.91},
    )
    monkeypatch.setattr(engine, "connect", lambda: conn)

    first = engine._calibration_for("tenant", "fact")
    assert first == CalibrationSet(
        tenant_id="tenant",
        memory_type="fact",
        scores=[0.2, 0.4],
        target_coverage=0.91,
    )
    assert first is not None
    first.scores.append(0.9)
    second = engine._calibration_for("tenant", "fact")

    assert second is not None
    assert second.scores == [0.2, 0.4]
    assert conn.calibration_selects == 1


def test_postgres_calibration_misses_are_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _ = make_engine(monkeypatch, reuse=True)
    conn = _CalibrationFakeConnection("calibration-miss", None)
    monkeypatch.setattr(engine, "connect", lambda: conn)

    assert engine._calibration_for("tenant", "missing") is None
    assert engine._calibration_for("tenant", "missing") is None

    assert conn.calibration_selects == 2


def test_postgres_set_calibration_updates_lookup_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _ = make_engine(monkeypatch, reuse=True)
    conn = _CalibrationFakeConnection(
        "calibration-write",
        {"memory_type": "fact", "scores": [0.1], "target_coverage": 0.8},
    )
    monkeypatch.setattr(engine, "connect", lambda: conn)
    monkeypatch.setattr(engine, "ensure_tenant_and_branch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine, "_audit", lambda *_args, **_kwargs: None)

    calibration = CalibrationSet(
        tenant_id="tenant",
        memory_type="fact",
        scores=[0.7],
        target_coverage=0.95,
    )
    engine.set_calibration(calibration)
    calibration.scores.append(0.99)

    got = engine._calibration_for("tenant", "fact")

    assert got == CalibrationSet(
        tenant_id="tenant",
        memory_type="fact",
        scores=[0.7],
        target_coverage=0.95,
    )
    assert conn.calibration_selects == 0


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
# Lane B: hot-path DDL elimination under a least-privilege role.
#
# The ensure-schema steps must (a) skip owner-only DDL entirely when the target
# already exists — the steady state of every provisioned deployment — and (b)
# when a target IS missing, attempt the DDL but tolerate an insufficient-
# privilege failure: a warning for acceleration-only objects (indexes/CHECK),
# a precise raise for a REQUIRED column the query text references directly.
# These are unit-tested against a fake cursor that models catalog existence
# probes plus owner-only DDL rejection (SQLSTATE 42501), no live DB.
# --------------------------------------------------------------------------- #


class FakeInsufficientPrivilege(Exception):
    """Mimics psycopg errors.InsufficientPrivilege (SQLSTATE 42501)."""

    sqlstate = "42501"


class FakeUndefinedTable(Exception):
    """A non-privilege DB error (SQLSTATE 42P01) — must NOT be swallowed."""

    sqlstate = "42P01"


class SchemaEnsureCursor:
    """Fake cursor: catalog existence probes + owner-only DDL under a
    least-privilege role. ``present_*`` declare what the privileged migration
    already created; ``deny_ddl`` makes owner-only DDL raise ``deny_error``
    (default 42501), exactly as a NOSUPERUSER non-owner role would."""

    def __init__(
        self,
        *,
        present_columns: set[tuple[str, str]] | None = None,
        present_indexes: set[str] | None = None,
        present_constraints: set[str] | None = None,
        deny_ddl: bool = False,
        deny_error: Exception | None = None,
    ):
        self.present_columns = set(present_columns or set())
        self.present_indexes = set(present_indexes or set())
        self.present_constraints = set(present_constraints or set())
        self.deny_ddl = deny_ddl
        self.deny_error = deny_error or FakeInsufficientPrivilege("permission denied for table")
        self.statements: list[str] = []
        self._pending: tuple[Any, ...] | None = None

    def __enter__(self) -> "SchemaEnsureCursor":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    @staticmethod
    def _is_ddl(upper: str) -> bool:
        return upper.startswith(("ALTER TABLE", "CREATE INDEX", "DROP INDEX", "CREATE UNIQUE INDEX"))

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        prepare: bool | None = None,
    ) -> None:
        flat = " ".join(sql.split())
        self.statements.append(flat)
        self._pending = None
        # Existence probes: order matters — the column probe SQL also mentions
        # to_regclass, so match pg_attribute / pg_constraint before to_regclass.
        if "FROM pg_attribute" in flat:
            table, column = params  # type: ignore[misc]
            if (table, column) in self.present_columns:
                self._pending = (1,)
            return
        if "FROM pg_constraint" in flat:
            (conname,) = params  # type: ignore[misc]
            if conname in self.present_constraints:
                self._pending = (1,)
            return
        if "to_regclass" in flat:
            (index_name,) = params  # type: ignore[misc]
            if index_name in self.present_indexes:
                self._pending = (1,)
            return
        upper = flat.upper()
        if upper.startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")):
            return
        if self.deny_ddl and self._is_ddl(upper):
            raise self.deny_error
        # UPDATE / other DML the least-privilege role may run: succeed silently.

    def fetchone(self) -> Any:
        return self._pending

    def fetchall(self) -> list[Any]:
        return []


def _ddl_statements(cur: SchemaEnsureCursor) -> list[str]:
    return [s for s in cur.statements if SchemaEnsureCursor._is_ddl(s.upper())]


# --- lexeme ensure -------------------------------------------------------- #


def test_lexeme_schema_present_issues_no_ddl() -> None:
    """(a) column + index already present -> only existence SELECTs, no DDL."""
    cur = SchemaEnsureCursor(
        present_columns={("evidence", "lexeme")},
        present_indexes={"evidence_lexeme_gin"},
        deny_ddl=True,  # would raise if any owner-only DDL were attempted
    )
    PostgresEngine._ensure_evidence_lexeme_schema(cur)
    assert _ddl_statements(cur) == [], "steady state must issue zero owner-only DDL"
    assert not any("SAVEPOINT" in s for s in cur.statements), "no savepoint when nothing to create"
    # Exactly two privilege-free probes: the column probe (pg_attribute) and the
    # index probe (to_regclass); nothing else touches the connection.
    assert len(cur.statements) == 2
    assert sum("pg_attribute" in s for s in cur.statements) == 1
    assert sum(s.startswith("SELECT 1 WHERE to_regclass") for s in cur.statements) == 1


def test_lexeme_schema_absent_with_ddl_allowed_creates_column_and_index() -> None:
    """(b) column + index absent, DDL allowed -> ALTER ADD COLUMN + CREATE INDEX."""
    cur = SchemaEnsureCursor(deny_ddl=False)
    PostgresEngine._ensure_evidence_lexeme_schema(cur)
    ddl = _ddl_statements(cur)
    assert any(s.startswith("ALTER TABLE evidence ADD COLUMN IF NOT EXISTS lexeme") for s in ddl)
    assert any("CREATE INDEX IF NOT EXISTS evidence_lexeme_gin" in s for s in ddl)
    # Each attempt is savepoint-wrapped and released on success.
    assert any(s == "RELEASE SAVEPOINT mnemosyne_ensure_ddl" for s in cur.statements)


def test_lexeme_index_absent_insufficient_privilege_warns_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """(c) index absent + role cannot create it -> caught, warned, no raise, and
    the surrounding transaction is left usable via ROLLBACK TO SAVEPOINT."""
    cur = SchemaEnsureCursor(
        present_columns={("evidence", "lexeme")},  # required column already there
        present_indexes=set(),  # GIN index missing
        deny_ddl=True,
    )
    with caplog.at_level("WARNING", logger="mnemosyne.postgres_engine"):
        PostgresEngine._ensure_evidence_lexeme_schema(cur)  # must NOT raise
    assert "ROLLBACK TO SAVEPOINT mnemosyne_ensure_ddl" in cur.statements
    assert "RELEASE SAVEPOINT mnemosyne_ensure_ddl" in cur.statements
    assert any("evidence_lexeme_gin" in r.message and "privilege" in r.message for r in caplog.records)


def test_lexeme_column_absent_insufficient_privilege_raises_precise_error() -> None:
    """Required column absent AND uncreatable -> fail loud with an actionable
    error (the query names e.lexeme directly; a warning would only defer the
    crash to a cryptic 'column does not exist' mid-serve)."""
    cur = SchemaEnsureCursor(deny_ddl=True)  # column absent + privilege denied
    with pytest.raises(RuntimeError, match=r"evidence\.lexeme.*privileged role"):
        PostgresEngine._ensure_evidence_lexeme_schema(cur)
    # Transaction was returned to a clean state before raising.
    assert "ROLLBACK TO SAVEPOINT mnemosyne_ensure_ddl" in cur.statements


def test_lexeme_non_privilege_error_propagates_unchanged() -> None:
    """A non-42501 DB error must not be swallowed or reclassified."""
    cur = SchemaEnsureCursor(deny_ddl=True, deny_error=FakeUndefinedTable("relation missing"))
    with pytest.raises(FakeUndefinedTable):
        PostgresEngine._ensure_evidence_lexeme_schema(cur)


# --- vector ensure -------------------------------------------------------- #


VECTOR_COLUMNS = {
    ("evidence", "embedding"),
    ("evidence", "embedding_partition"),
    ("assertions", "embedding_partition"),
}
VECTOR_INDEXES = {
    "evidence_embedding_public_hnsw",
    "assertions_embedding_public_hnsw",
    "evidence_embedding_private_hnsw",
    "assertions_embedding_private_hnsw",
    "evidence_embedding_none_btree",
    "assertions_embedding_none_btree",
    "evidence_null_embedding_fallback_idx",
}
VECTOR_CONSTRAINTS = {"evidence_embedding_partition_check", "assertions_embedding_partition_check"}


def test_vector_schema_fully_present_issues_no_ddl_but_runs_backfills() -> None:
    """Provisioned deployment: zero owner-only DDL on the hot path, yet the DML
    partition backfills still run (behavior preserved for the fast path)."""
    cur = SchemaEnsureCursor(
        present_columns=VECTOR_COLUMNS,
        present_indexes=VECTOR_INDEXES,  # legacy hnsw names intentionally absent
        present_constraints=VECTOR_CONSTRAINTS,
        deny_ddl=True,
    )
    PostgresEngine._ensure_evidence_vector_schema(cur)
    assert _ddl_statements(cur) == [], "steady state must issue zero owner-only DDL"
    # The four idempotent DML backfills still execute.
    update_stmts = [s for s in cur.statements if s.upper().startswith("UPDATE ")]
    assert len(update_stmts) == 4
    # Legacy single-partition index drop is only attempted when present.
    assert not any("DROP INDEX" in s for s in cur.statements)


def test_vector_schema_required_column_absent_insufficient_privilege_raises() -> None:
    """A missing-and-uncreatable embedding column fails loud (query references
    `embedding` verbatim)."""
    present = {c for c in VECTOR_COLUMNS if c != ("evidence", "embedding")}
    cur = SchemaEnsureCursor(
        present_columns=present,
        present_indexes=VECTOR_INDEXES,
        present_constraints=VECTOR_CONSTRAINTS,
        deny_ddl=True,
    )
    with pytest.raises(RuntimeError, match=r"evidence\.embedding.*privileged role"):
        PostgresEngine._ensure_evidence_vector_schema(cur)


def test_vector_schema_missing_index_privilege_denied_warns_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Columns/constraints present but a partitioned HNSW index missing and the
    role cannot create it -> warn, no raise; the vector query still runs."""
    cur = SchemaEnsureCursor(
        present_columns=VECTOR_COLUMNS,
        present_indexes=VECTOR_INDEXES - {"evidence_embedding_public_hnsw"},
        present_constraints=VECTOR_CONSTRAINTS,
        deny_ddl=True,
    )
    with caplog.at_level("WARNING", logger="mnemosyne.postgres_engine"):
        PostgresEngine._ensure_evidence_vector_schema(cur)  # must NOT raise
    assert any("evidence_embedding_public_hnsw" in r.message for r in caplog.records)
    assert "ROLLBACK TO SAVEPOINT mnemosyne_ensure_ddl" in cur.statements


def test_vector_schema_creates_btree_none_and_null_fallback_indexes() -> None:
    missing = {
        "evidence_embedding_none_btree",
        "assertions_embedding_none_btree",
        "evidence_null_embedding_fallback_idx",
    }
    cur = SchemaEnsureCursor(
        present_columns=VECTOR_COLUMNS,
        present_indexes=VECTOR_INDEXES - missing,
        present_constraints=VECTOR_CONSTRAINTS,
        deny_ddl=False,
    )
    PostgresEngine._ensure_evidence_vector_schema(cur)

    ddl = _ddl_statements(cur)
    created = {name for name in missing if any(name in stmt for stmt in ddl)}
    assert created == missing
    assert not any("embedding_none_btree" in stmt and "USING hnsw" in stmt for stmt in ddl)
    fallback = next(stmt for stmt in ddl if "evidence_null_embedding_fallback_idx" in stmt)
    assert "embedding IS NULL AND embedding_partition <> 'none' AND erased = false" in fallback


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

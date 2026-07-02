"""Tier-B gate-keyed backend identifiers must never drift (spec 4.0).

forbid_local classifies locality by NAME (denylist + 'local-' prefix), and
production profiles pin the postgres-* names. Renaming any of these breaks
retrieval-ops-check semantics and pending Tier-B evidence.
"""

from __future__ import annotations

import os
from unittest import mock

from mnemosyne.cli import _is_local_retrieval_backend
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.retrieval import RetrievalAdapters, retrieval_adapters_from_env


def test_local_default_backend_names_are_pinned():
    adapters = RetrievalAdapters()
    assert adapters.lexical_backend == "local-bm25-lite"
    assert adapters.graph_backend == "local-ppr"


def test_env_default_backend_names_are_pinned():
    with mock.patch.dict(os.environ, {}, clear=False):
        # retrieval_adapters_from_env() defaults to prefix="MNEMOSYNE"; clear
        # every var under that prefix so ambient provider/backend overrides
        # (e.g. *_LEXICAL_PROVIDER=command) cannot skew the pinned defaults.
        for var in [name for name in os.environ if name.startswith("MNEMOSYNE_")]:
            os.environ.pop(var, None)
        adapters = retrieval_adapters_from_env()
    assert adapters.lexical_backend == "postgres-fts"
    assert adapters.graph_backend == "postgres-recursive-ppr"


def test_postgres_engine_default_adapter_names_are_pinned():
    """PostgresEngine self-reports the Tier-B gate names.

    Construction is lazy — no connection is opened and psycopg is only
    imported on connect() — so this runs everywhere, even without psycopg
    installed (verified: this env has no psycopg and constructs fine).
    """
    engine = PostgresEngine("postgresql://unused")
    assert engine.adapters.lexical_backend == "postgres-fts"
    assert engine.adapters.graph_backend == "postgres-recursive-ppr"


def test_sqlite_engine_default_adapter_names_are_pinned(tmp_path):
    """SqliteEngine self-reports the Tier-B gate names for its scan surfaces.

    Construction opens no tenant file (per-tenant DBs are created lazily on
    first tenant access), so this runs everywhere.
    """
    from mnemosyne.sqlite_engine import SqliteEngine

    engine = SqliteEngine(tmp_path)
    assert engine.adapters.lexical_backend == "sqlite-fts5"
    assert engine.adapters.graph_backend == "sqlite-cached-ppr"


def test_sqlite_backend_names_escape_forbid_local():
    """The sqlite-* retrieval names must NOT classify as local backends, so
    forbid_local / retrieval-ops-check semantics treat SqliteEngine as a
    non-local (self-hosted) backend — never the local denylist."""
    assert not _is_local_retrieval_backend("sqlite-fts5")
    assert not _is_local_retrieval_backend("sqlite-cached-ppr")

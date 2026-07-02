"""Tier-B gate-keyed backend identifiers must never drift (spec 4.0).

forbid_local classifies locality by NAME (denylist + 'local-' prefix), and
production profiles pin the postgres-* names. Renaming any of these breaks
retrieval-ops-check semantics and pending Tier-B evidence.
"""

from __future__ import annotations

import os
from unittest import mock

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

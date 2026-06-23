"""Shared helpers for the broadened local<->Postgres portability suite (G8 / NFR portability).

This module powers a *cross-engine* parity harness that goes beyond the existing
parametrized shared contract (``tests/test_shared_engine_contract.py``).

The existing shared contract runs each test against ONE engine at a time (a
``params=["local", "postgres"]`` fixture) and proves that each engine *independently*
satisfies the contract. It never instantiates both engines inside a single test and
asserts that their observable outputs are *identical* on the same inputs.

This harness closes that gap: every parity case here builds BOTH a
``LocalMemoryEngine`` and (when ``MNEMOSYNE_POSTGRES_DSN`` is set) a ``PostgresEngine``,
drives them with the SAME string tenant/user IDs and the SAME operations, then asserts
the *normalized* observable results are equal.

Normalization strips fields that are legitimately allowed to differ between two
independent backends/runs (freshly-minted UUIDs, wall-clock timestamps, float score
jitter) while preserving everything that is part of the portable contract
(content-addressed CIDs, envelope fields, statuses, structural relationships, ordering
of deterministic collections).

SECURITY NOTE: all evidence/content strings in the parity cases are inert test data.
Nothing read from a corpus or file is executed; this module only constructs literals.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

import pytest

# Volatile field names that two independent engines/runs may legitimately differ on.
# We drop these before structural comparison. CIDs are content-addressed and therefore
# stable across engines, so they are intentionally NOT in this set.
_VOLATILE_KEYS = frozenset(
    {
        "id",
        "at",
        "created_at",
        "detected_at",
        "valid_from",
        "valid_to",
        "expired_at",
        "transaction_time",
        "last_accessed",
        "next_rehearsal_at",
        "justification_id",  # synthesized assertion->justification link id
    }
)

# Keys whose *values* are themselves volatile ids we must blank, but whose presence is
# part of the contract (so we keep the key, normalize the value to a sentinel).
_VOLATILE_ID_VALUE_KEYS = frozenset({"superseded_by", "retired_by"})

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# Float comparison tolerance for scores/confidence that may differ by backend math.
SCORE_TOLERANCE = 1e-6


def live_dsn() -> str | None:
    """Return the Postgres DSN if the operator opted into the live half of the suite.

    Documented contract: the local half of every parity case always runs. The Postgres
    half (and therefore the actual cross-engine equality assertion) only runs when
    ``MNEMOSYNE_POSTGRES_DSN`` is exported. This keeps the suite green in CI/dev without
    a database while still proving portability wherever a database is available.
    """

    return os.environ.get("MNEMOSYNE_POSTGRES_DSN")


def make_local_engine() -> Any:
    from mnemosyne.engine import LocalMemoryEngine

    return LocalMemoryEngine()


def make_postgres_engine(dsn: str) -> Any:
    pytest.importorskip("psycopg")
    from mnemosyne.postgres_engine import PostgresEngine

    return PostgresEngine(dsn)


def normalize(value: Any) -> Any:
    """Recursively normalize an observable result for cross-engine equality.

    - drops volatile keys (ids, timestamps) from dicts
    - replaces volatile id *values* (e.g. ``superseded_by``) with a stable sentinel
      that records only "links to something" vs "links to nothing"
    - rounds floats so score/confidence jitter does not break equality
    - rewrites bare UUID / ISO-timestamp scalars to sentinels
    - sorts lists of dicts that carry a stable content-addressed ``cid`` so that
      collection ordering differences (which are not part of the portable contract)
      do not cause spurious mismatches
    """

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, inner in value.items():
            if key in _VOLATILE_KEYS:
                continue
            if key in _VOLATILE_ID_VALUE_KEYS:
                out[key] = None if inner in (None, "") else "<id>"
                continue
            out[key] = normalize(inner)
        return out
    if isinstance(value, (list, tuple)):
        normalized = [normalize(item) for item in value]
        # Stabilize ordering for collections of content-addressed records.
        if normalized and all(isinstance(item, dict) and "cid" in item for item in normalized):
            normalized.sort(key=lambda item: str(item.get("cid")))
        return normalized
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, str):
        if _UUID_RE.match(value):
            return "<uuid>"
        if _TIMESTAMP_RE.match(value):
            return "<timestamp>"
        return value
    return value


def assert_parity(label: str, local_value: Any, pg_value: Any) -> None:
    """Assert two engines produced identical normalized observable results.

    Used only on the Postgres-enabled half. ``label`` makes failures legible about
    *which* method's observable output diverged.
    """

    norm_local = normalize(local_value)
    norm_pg = normalize(pg_value)
    assert norm_local == norm_pg, (
        f"local<->postgres parity mismatch for {label!r}:\n"
        f"  local={norm_local!r}\n  postgres={norm_pg!r}"
    )


class ParityHarness:
    """Drives a callable against the local engine (always) and Postgres (when enabled).

    Each parity case is written ONCE as ``scenario(engine, tenant, user) -> observable``.
    The harness runs it against ``LocalMemoryEngine`` (always, so local parity behavior is
    proven now) and, when ``MNEMOSYNE_POSTGRES_DSN`` is set, against ``PostgresEngine`` with
    the SAME string tenant/user IDs, then asserts the two normalized observables match.

    Returns the local observable so the caller can additionally assert engine-agnostic
    invariants (shape, required keys) that must hold regardless of the database.
    """

    def __init__(self, tenant: str, user: str) -> None:
        self.tenant = tenant
        self.user = user
        self.dsn = live_dsn()
        self.postgres_ran = False

    def run(self, label: str, scenario: Callable[[Any, str, str], Any]) -> Any:
        local_engine = make_local_engine()
        local_observable = scenario(local_engine, self.tenant, self.user)

        if self.dsn:
            pg_engine = make_postgres_engine(self.dsn)
            pg_observable = scenario(pg_engine, self.tenant, self.user)
            assert_parity(label, local_observable, pg_observable)
            self.postgres_ran = True

        return local_observable

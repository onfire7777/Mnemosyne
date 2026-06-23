"""§31 RAIL 2 — min_corroboration_for_delete = 2.

Rail: ">= 2 independent sources before hard delete." Intended reading: a
HARD_DELETE_LEGAL erasure of an *assertion-bearing* evidence row should require
that the belief it supports is independently corroborated by >= 2 sources before
the evidence is physically destroyed (so a single forged "delete this" source
cannot vaporize a corroborated fact, and so we never destroy our only copy of
something whose deletion was not independently justified).

Enforcement point that SHOULD exist: ``LocalMemoryEngine.forget`` /
``PostgresMemoryEngine.forget`` (src/mnemosyne/engine.py:887,
src/mnemosyne/postgres_engine.py:1328) when ``erasure_mode`` is
``ErasureMode.HARD_DELETE_LEGAL``.

Current state (gap): ``forget`` performs the hard delete unconditionally. There
is no ``min_corroboration_for_delete`` constant anywhere in ``src/mnemosyne``
(``grep -rn min_corroboration src`` is empty), and ``forget`` never counts the
independent sources backing the affected assertions before popping the evidence.
The rate/metric gate in ``parametric.py`` does not cover deletes at all.

=> The breach test below is xfail(strict) until Codex adds a corroboration count
check to the HARD_DELETE_LEGAL branch of ``forget``.
"""

from __future__ import annotations

import pytest

from mnemosyne.privacy import ErasureMode
from mnemosyne.security import TrustTier

from .conftest import TENANT, add_evidence, fresh_engine, make_assertion


def _fact_with_single_source(engine):
    """Seed one assertion backed by exactly ONE evidence source."""

    only_cid = add_evidence(
        engine,
        content="Defendant was at the scene at 21:00.",
        trust_tier=int(TrustTier.DIRECT_USER),
    )
    engine.upsert_assertion(
        make_assertion(
            subject="defendant",
            predicate="located_at",
            obj="scene@21:00",
            trust_tier=int(TrustTier.DIRECT_USER),
            source_cids=[only_cid],
            confidence=0.9,
            status="active",
        )
    )
    return only_cid


@pytest.mark.xfail(
    strict=True,
    reason=(
        "RAIL 2 NOT STRUCTURALLY ENFORCED. Missing enforcement point: "
        "LocalMemoryEngine.forget (engine.py:887) HARD_DELETE_LEGAL branch deletes "
        "evidence with zero corroboration counting. No `min_corroboration_for_delete` "
        "constant exists in src/mnemosyne. Codex must gate the HARD_DELETE_LEGAL path "
        "on >=2 independent sources for any assertion that loses ALL its support, "
        "raising/refusing otherwise."
    ),
)
def test_hard_delete_of_sole_source_is_refused_without_corroboration():
    """Attempt to legally hard-delete the ONLY evidence backing an active,
    uncorroborated assertion. The rail requires >=2 independent sources before a
    hard delete; with a single source this must be refused.

    We assert refusal as: forget reports ``erased == False`` OR raises. Today it
    returns ``erased == True`` and silently retracts the assertion, so this
    xfails until enforcement lands.
    """

    engine = fresh_engine()
    only_cid = _fact_with_single_source(engine)

    raised = False
    result: dict = {}
    try:
        result = engine.forget(
            TENANT,
            only_cid,
            erasure_mode=ErasureMode.HARD_DELETE_LEGAL,
            requested_by="adversary",
        )
    except (ValueError, PermissionError):
        raised = True

    # Refusal == it raised, or it declined to erase.
    refused = raised or (result.get("erased") is False)
    assert refused, "hard delete of a sole, uncorroborated source must be refused by the corroboration rail"


def test_hard_delete_with_two_independent_sources_is_permitted():
    """Positive control. When the supporting belief is independently
    corroborated by >=2 sources, deleting ONE of them is allowed because the
    fact survives via the remaining source. This already works today (forget
    trims rather than retracts), and must keep working once the rail lands.
    """

    engine = fresh_engine()
    cid_a = add_evidence(engine, content="Receipt A: paid invoice 12.", trust_tier=int(TrustTier.DIRECT_USER))
    cid_b = add_evidence(engine, content="Bank statement: paid invoice 12.", trust_tier=int(TrustTier.VERIFIED))
    engine.upsert_assertion(
        make_assertion(
            subject="invoice-12",
            predicate="status_is",
            obj="paid",
            trust_tier=int(TrustTier.DIRECT_USER),
            source_cids=[cid_a, cid_b],  # two independent sources
            confidence=0.9,
            status="active",
        )
    )

    result = engine.forget(
        TENANT,
        cid_a,
        erasure_mode=ErasureMode.HARD_DELETE_LEGAL,
        requested_by="user",
    )
    assert result["erased"] is True
    # The corroborated assertion is trimmed (loses cid_a) but NOT retracted.
    assert result["propagated"]["trimmed_assertions"], "corroborated fact should survive on remaining source"
    assert not result["propagated"]["retracted_assertions"]

"""Phase-2 Task 5 — SqliteEngine assertions, bitemporal as-of, and the remaining
write surface, pinned against the ``LocalMemoryEngine`` parity oracle.

Every write behaviour is proven by seeding IDENTICAL content into a
``SqliteEngine`` and a ``LocalMemoryEngine`` and asserting equal
``export_tenant`` output, normalising only the documented format deltas
(volatile generated ids, wall-clock timestamps, generated ``justification_id``).
The supersession/contest matrix is driven from the shared-contract shapes:
plain insert, same-object reinforce, trust_supersede, trust_rejected, supersede
(later valid_from), contest (equal valid_from → both contested + rebalanced
``hypothesis_prob``), and historical_superseded. Also pins: as-of half-open
window parity across boundaries, the R7 ``'Z'``-format regression (a naive
``isoformat()`` parameter selects the boundary wrong), and the T2/T3 handoff
that a hostile/unknown branch raises ``ValueError`` before any FK fires.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mnemosyne.calibration import CalibrationSet
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Preference, Relation, RetrievalResult, dt_to_json, parse_dt
from mnemosyne.sqlite_engine import SqliteEngine

FIXED_CREATED = parse_dt("2026-07-02T03:04:05.123456Z")
T0 = parse_dt("2026-01-01T00:00:00Z")
T1 = parse_dt("2026-02-01T00:00:00Z")
T2 = parse_dt("2026-03-01T00:00:00Z")
T3 = parse_dt("2026-04-01T00:00:00Z")

# Keys whose values are generated/wall-clock and therefore differ between two
# independent engine runs of the same scenario (documented format deltas). They
# are scrubbed RECURSIVELY so nested audit ``before``/``after`` snapshots are
# normalised too. ``valid_from``/``created_at`` are seeded deterministically but
# also generated volatile by ``correct()`` (utc_now default), so they are
# scrubbed uniformly; ``valid_to`` — the load-bearing supersession signal — is
# derived deterministically from the seeded ``valid_from`` and is KEPT.
_VOLATILE = {
    "id",
    "at",
    "transaction_time",
    "last_accessed",
    "justification_id",
    "updated_at",
    "created_at",
    "valid_from",
}


def _scrub(obj, volatile):
    if isinstance(obj, dict):
        return {key: _scrub(value, volatile) for key, value in obj.items() if key not in volatile}
    if isinstance(obj, list):
        return [_scrub(item, volatile) for item in obj]
    return obj


def _normalise(export: dict, *, extra: frozenset[str] = frozenset()) -> dict:
    volatile = _VOLATILE | extra
    export = _scrub(copy.deepcopy(export), volatile)
    if "tenants" in export:
        export["tenants"] = [_normalise(item, extra=extra) for item in export["tenants"]]
    for key, value in export.items():
        if isinstance(value, list):
            export[key] = sorted(value, key=lambda item: json.dumps(item, sort_keys=True))
    return export


def _engines(tmp_path: Path) -> tuple[SqliteEngine, LocalMemoryEngine]:
    # Both default to a deterministic HashingEmbeddingProvider + default policy,
    # so embeddings and reality classification are byte-identical across engines
    # (same construction the Task-3 ledger parity tests rely on).
    return SqliteEngine(tmp_path / "root"), LocalMemoryEngine()


def _seed_evidence(engine, tenant: str, content: str) -> str:
    ev = Evidence(
        tenant_id=tenant,
        user_id="u",
        actor="user",
        source_type="chat",
        content=content,
        access_policy={"tenant": tenant},
        created_at=FIXED_CREATED,
    )
    return engine.append_evidence(ev)


def _assertion(
    tenant: str,
    *,
    id: str,
    object: str,
    valid_from,
    cids: list[str],
    subject: str = "beacon",
    predicate: str = "is",
    confidence: float = 0.7,
    trust_tier: int = 1,
    status: str = "active",
) -> Assertion:
    return Assertion(
        tenant_id=tenant,
        user_id="u",
        subject=subject,
        predicate=predicate,
        object=object,
        confidence=confidence,
        trust_tier=trust_tier,
        valid_from=valid_from,
        status=status,
        source_evidence_cids=cids,
        access_policy={"tenant": tenant},
        id=id,
    )


# --- supersession / contest matrix scenarios --------------------------------
#
# Each scenario is a callable ``(engine, tenant) -> None`` applied identically
# to both engines; the assertion table + audit log must then byte-match.


def _plain_insert(engine, tenant):
    cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
    engine.upsert_assertion(_assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid]))


def _candidate_becomes_active(engine, tenant):
    cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
    engine.upsert_assertion(
        _assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid], status="candidate")
    )


def _reinforce_same_object(engine, tenant):
    cid1 = _seed_evidence(engine, tenant, "Grounded note one about the beacon.")
    cid2 = _seed_evidence(engine, tenant, "Grounded note two about the beacon.")
    engine.upsert_assertion(
        _assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid1], confidence=0.7, trust_tier=2)
    )
    engine.upsert_assertion(
        _assertion(tenant, id="idB", object="topaz", valid_from=T2, cids=[cid2], confidence=0.9, trust_tier=1)
    )


def _trust_supersede(engine, tenant):
    cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
    engine.upsert_assertion(
        _assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid], trust_tier=2)
    )
    engine.upsert_assertion(
        _assertion(tenant, id="idB", object="ruby", valid_from=T2, cids=[cid], trust_tier=1)
    )


def _trust_supersede_older_incoming(engine, tenant):
    # incoming is MORE trusted but OLDER → current.valid_to = current.valid_from + 1us
    cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
    engine.upsert_assertion(
        _assertion(tenant, id="idA", object="topaz", valid_from=T2, cids=[cid], trust_tier=2)
    )
    engine.upsert_assertion(
        _assertion(tenant, id="idB", object="ruby", valid_from=T1, cids=[cid], trust_tier=1)
    )


def _trust_rejected(engine, tenant):
    cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
    engine.upsert_assertion(
        _assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid], trust_tier=1)
    )
    engine.upsert_assertion(
        _assertion(tenant, id="idB", object="ruby", valid_from=T2, cids=[cid], trust_tier=2)
    )


def _supersede_later_valid_from(engine, tenant):
    cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
    engine.upsert_assertion(
        _assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid], trust_tier=1)
    )
    engine.upsert_assertion(
        _assertion(tenant, id="idB", object="ruby", valid_from=T2, cids=[cid], trust_tier=1)
    )


def _contest_equal_valid_from(engine, tenant):
    cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
    engine.upsert_assertion(
        _assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid], trust_tier=1, confidence=0.6)
    )
    engine.upsert_assertion(
        _assertion(tenant, id="idB", object="ruby", valid_from=T1, cids=[cid], trust_tier=1, confidence=0.9)
    )


def _historical_superseded(engine, tenant):
    cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
    engine.upsert_assertion(
        _assertion(tenant, id="idA", object="topaz", valid_from=T2, cids=[cid], trust_tier=1)
    )
    engine.upsert_assertion(
        _assertion(tenant, id="idB", object="ruby", valid_from=T1, cids=[cid], trust_tier=1)
    )


_UPSERT_SCENARIOS = {
    "plain_insert": _plain_insert,
    "candidate_becomes_active": _candidate_becomes_active,
    "reinforce_same_object": _reinforce_same_object,
    "trust_supersede": _trust_supersede,
    "trust_supersede_older_incoming": _trust_supersede_older_incoming,
    "trust_rejected": _trust_rejected,
    "supersede_later_valid_from": _supersede_later_valid_from,
    "contest_equal_valid_from": _contest_equal_valid_from,
    "historical_superseded": _historical_superseded,
}


@pytest.mark.parametrize("name", sorted(_UPSERT_SCENARIOS))
def test_upsert_assertion_matrix_export_parity_vs_local(tmp_path: Path, name: str):
    scenario = _UPSERT_SCENARIOS[name]
    sqlite, local = _engines(tmp_path)
    tenant = f"t-{name}"
    scenario(sqlite, tenant)
    scenario(local, tenant)
    assert _normalise(sqlite.export_tenant(tenant)) == _normalise(local.export_tenant(tenant))


def test_contest_rebalances_hypothesis_prob_on_both_engines(tmp_path: Path):
    sqlite, local = _engines(tmp_path)
    _contest_equal_valid_from(sqlite, "t-contest")
    _contest_equal_valid_from(local, "t-contest")
    for engine in (sqlite, local):
        rows = engine.export_tenant("t-contest")["assertions"]
        assert {row["status"] for row in rows} == {"contested"}
        probs = sorted(row["calibration"]["hypothesis_prob"] for row in rows)
        # confidence 0.6 and 0.9 → 0.6/1.5 and 0.9/1.5
        assert probs == pytest.approx([0.4, 0.6])


def test_upsert_returns_winner_id_on_reinforce_and_incoming_id_on_conflict(tmp_path: Path):
    sqlite, _ = _engines(tmp_path)
    tenant = "t-return"
    cid = _seed_evidence(sqlite, tenant, "Grounded note about the beacon.")
    first = sqlite.upsert_assertion(_assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid]))
    assert first == "idA"
    reinforced = sqlite.upsert_assertion(
        _assertion(tenant, id="idB", object="topaz", valid_from=T2, cids=[cid], confidence=0.9)
    )
    assert reinforced == "idA"  # winner id, no new row
    conflict = sqlite.upsert_assertion(
        _assertion(tenant, id="idC", object="ruby", valid_from=T3, cids=[cid])
    )
    assert conflict == "idC"  # incoming id


# --- add_relation / add_preference / register_entity / calibration parity ----


def test_add_relation_export_parity_vs_local(tmp_path: Path):
    sqlite, local = _engines(tmp_path)
    tenant = "t-rel"

    def seed(engine):
        cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
        engine.add_relation(
            Relation(
                tenant_id=tenant,
                source="beacon",
                predicate="emits",
                target="topaz glow",
                confidence=0.8,
                valid_from=T1,
                source_evidence_cids=[cid],
                access_policy={"tenant": tenant},
                id="rel-1",
            )
        )

    seed(sqlite)
    seed(local)
    assert _normalise(sqlite.export_tenant(tenant)) == _normalise(local.export_tenant(tenant))


def _preference(tenant: str, *, id: str, statement: str, explicit: bool, valid_from) -> Preference:
    return Preference(
        tenant_id=tenant,
        user_id="u",
        category="format",
        statement=statement,
        scope={"surface": "chat"},
        confidence=0.8,
        explicit=explicit,
        valid_from=valid_from,
        access_policy={"tenant": tenant},
        id=id,
    )


def test_add_preference_supersession_export_parity_vs_local(tmp_path: Path):
    sqlite, local = _engines(tmp_path)
    tenant = "t-pref"

    def seed(engine):
        # implicit pref, then an explicit pref with a different statement in the
        # same category/scope → the first is superseded (valid_to = new valid_from).
        engine.add_preference(_preference(tenant, id="p1", statement="use bullet lists", explicit=False, valid_from=T1))
        engine.add_preference(_preference(tenant, id="p2", statement="use numbered lists", explicit=True, valid_from=T2))
        # a weaker implicit pref against an explicit one is retracted.
        engine.add_preference(_preference(tenant, id="p3", statement="use prose", explicit=False, valid_from=T3))

    seed(sqlite)
    seed(local)
    assert _normalise(sqlite.export_tenant(tenant)) == _normalise(local.export_tenant(tenant))
    statuses = {row["id"]: row["status"] for row in sqlite.export_tenant(tenant)["preferences"]}
    assert statuses == {"p1": "superseded", "p2": "active", "p3": "retracted"}


def test_register_entity_export_parity_vs_local(tmp_path: Path):
    sqlite, local = _engines(tmp_path)
    tenant = "t-ent"

    def seed(engine):
        cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
        engine.register_entity(
            tenant,
            "Cobalt Lighthouse",
            alias="the beacon",
            entity_type="place",
            summary="A lighthouse.",
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
        # re-register merges aliases + source cids + access policy.
        engine.register_entity(
            tenant,
            "Cobalt Lighthouse",
            alias="topaz tower",
            source_evidence_cids=[cid],
        )

    seed(sqlite)
    seed(local)
    assert _normalise(sqlite.export_tenant(tenant)) == _normalise(local.export_tenant(tenant))


def test_register_entity_return_shape_matches_local(tmp_path: Path):
    sqlite, local = _engines(tmp_path)
    tenant = "t-ent-ret"
    s_row = sqlite.register_entity(tenant, "Beacon", entity_type="place")
    l_row = local.register_entity(tenant, "Beacon", entity_type="place")
    assert {key: s_row[key] for key in s_row if key not in {"id", "updated_at"}} == {
        key: l_row[key] for key in l_row if key not in {"id", "updated_at"}
    }


def test_set_calibration_and_calibration_for_parity(tmp_path: Path):
    sqlite, local = _engines(tmp_path)
    tenant = "t-cal"
    cal = CalibrationSet(tenant_id=tenant, memory_type="fact", scores=[0.1, 0.4, 0.9], target_coverage=0.9)
    sqlite.set_calibration(copy.deepcopy(cal))
    local.set_calibration(copy.deepcopy(cal))
    assert _normalise(sqlite.export_tenant(tenant)) == _normalise(local.export_tenant(tenant))
    fetched = sqlite._calibration_for(tenant, "fact")
    assert isinstance(fetched, CalibrationSet)
    assert fetched.to_dict() == cal.to_dict()
    assert sqlite._calibration_for(tenant, "missing") is None


def test_correct_export_parity_vs_local(tmp_path: Path):
    sqlite, local = _engines(tmp_path)
    tenant = "t-correct"

    def seed(engine):
        cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
        engine.upsert_assertion(_assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid]))
        engine.correct(tenant, "u", "beacon", "is", "ruby", "Actually the beacon is ruby.")

    seed(sqlite)
    seed(local)
    # correct() generates the corrective assertion id + valid_from via
    # utc_now(), so the derived supersede link (superseded_by / audit target_id)
    # and valid_to are volatile here — scrub them on top of the base set.
    extra = frozenset({"valid_to", "superseded_by", "target_id"})
    assert _normalise(sqlite.export_tenant(tenant), extra=extra) == _normalise(
        local.export_tenant(tenant), extra=extra
    )


# --- bitemporal as-of --------------------------------------------------------


def _seed_supersede_chain(engine, tenant: str) -> None:
    cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
    engine.upsert_assertion(_assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid]))
    engine.upsert_assertion(_assertion(tenant, id="idB", object="ruby", valid_from=T2, cids=[cid]))


def _as_of_projection(result) -> list[tuple]:
    return [
        (a.subject, a.predicate, a.object, a.status, dt_to_json(a.valid_from), dt_to_json(a.valid_to))
        for a in result
    ]


@pytest.mark.parametrize(
    "moment",
    [
        parse_dt("2025-12-01T00:00:00Z"),  # before T1 → empty
        T1,  # at lower boundary (included)
        parse_dt("2026-02-15T00:00:00Z"),  # inside [T1, T2)
        T2,  # at upper boundary of A1 (excluded) / lower of A2 (included)
        T3,  # after → only the open-ended A2
    ],
)
def test_as_of_boundaries_parity_vs_local(tmp_path: Path, moment):
    sqlite, local = _engines(tmp_path)
    tenant = "t-asof"
    _seed_supersede_chain(sqlite, tenant)
    _seed_supersede_chain(local, tenant)
    sqlite_rows = _as_of_projection(sqlite.as_of("beacon", "is", moment, tenant_id=tenant))
    local_rows = _as_of_projection(local.as_of("beacon", "is", moment, tenant_id=tenant))
    assert sqlite_rows == local_rows


def test_as_of_returns_deep_copies(tmp_path: Path):
    sqlite, _ = _engines(tmp_path)
    tenant = "t-asof-copy"
    _seed_supersede_chain(sqlite, tenant)
    rows = sqlite.as_of("beacon", "is", T1, tenant_id=tenant)
    assert rows
    rows[0].object = "MUTATED"
    again = sqlite.as_of("beacon", "is", T1, tenant_id=tenant)
    assert all(row.object != "MUTATED" for row in again)


def test_as_of_tenant_optional_scans_all_files(tmp_path: Path):
    sqlite, local = _engines(tmp_path)
    _seed_supersede_chain(sqlite, "t-a")
    _seed_supersede_chain(sqlite, "t-b")
    _seed_supersede_chain(local, "t-a")
    _seed_supersede_chain(local, "t-b")
    sqlite_rows = _as_of_projection(sqlite.as_of("beacon", "is", parse_dt("2026-02-15T00:00:00Z")))
    local_rows = _as_of_projection(local.as_of("beacon", "is", parse_dt("2026-02-15T00:00:00Z")))
    assert sorted(sqlite_rows) == sorted(local_rows)
    assert len(sqlite_rows) == 2  # one live row per tenant


# --- R7 'Z'-format regression ------------------------------------------------


def test_as_of_z_format_boundary_inclusion_is_lexicographically_correct(tmp_path: Path):
    """A ``dt_to_json`` ('Z') moment parameter selects the [valid_from) boundary
    row correctly; a naive ``isoformat()`` ('+00:00') parameter sorts wrong and
    would EXCLUDE the boundary — the exact bug this pins."""
    sqlite, _ = _engines(tmp_path)
    tenant = "t-zfmt"
    boundary = parse_dt("2026-03-15T12:00:00Z")
    cid = _seed_evidence(sqlite, tenant, "Grounded note about the beacon.")
    sqlite.upsert_assertion(
        _assertion(tenant, id="idZ", object="cobalt", valid_from=boundary, cids=[cid])
    )
    stored_valid_from = dt_to_json(boundary)
    assert stored_valid_from.endswith("Z")  # dt_to_json produces trailing Z

    # The engine's as_of (dt_to_json param) INCLUDES the boundary row.
    rows = sqlite.as_of("beacon", "is", boundary, tenant_id=tenant)
    assert [row.id for row in rows] == ["idZ"]

    # And just before the boundary it is EXCLUDED (valid_from > moment).
    before = boundary - __import__("datetime").timedelta(microseconds=1)
    assert sqlite.as_of("beacon", "is", before, tenant_id=tenant) == []

    # Prove the 'Z' serialisation is load-bearing: a naive isoformat parameter
    # sorts the equal boundary the wrong way, so the same predicate would wrongly
    # drop the row; the dt_to_json parameter keeps it.
    conn = sqlite._connect(tenant)
    naive_param = boundary.isoformat()  # '2026-03-15T12:00:00+00:00'
    z_param = dt_to_json(boundary)  # '2026-03-15T12:00:00Z'
    assert naive_param != z_param
    naive_hit = conn.execute(
        "SELECT id FROM assertions WHERE tenant_id = ? AND valid_from <= ?",
        (tenant, naive_param),
    ).fetchall()
    z_hit = conn.execute(
        "SELECT id FROM assertions WHERE tenant_id = ? AND valid_from <= ?",
        (tenant, z_param),
    ).fetchall()
    assert naive_hit == []  # naive '+00:00' param wrongly excludes the boundary
    assert [row["id"] for row in z_hit] == ["idZ"]  # dt_to_json param includes it


def test_as_of_valid_to_upper_boundary_is_half_open(tmp_path: Path):
    sqlite, local = _engines(tmp_path)
    tenant = "t-halfopen"
    _seed_supersede_chain(sqlite, tenant)
    _seed_supersede_chain(local, tenant)
    # A1 has valid_to == T2; at exactly T2 it is EXCLUDED (moment < valid_to).
    at_t2 = _as_of_projection(sqlite.as_of("beacon", "is", T2, tenant_id=tenant))
    assert all(row[2] != "topaz" for row in at_t2)  # superseded A1 (object topaz) gone
    assert at_t2 == _as_of_projection(local.as_of("beacon", "is", T2, tenant_id=tenant))


# --- mixed-precision (variable-width fractional seconds) regression ----------
#
# ``dt_to_json`` emits 0- or 6-digit fractional seconds, so a lexical TEXT
# compare orders ``'...00Z'`` AFTER ``'...00.500000Z'`` even though it precedes
# it chronologically. ``as_of`` must resolve the [valid_from, valid_to) window
# in Python (``parse_dt``) so a whole-second moment brackets a sub-second bound
# byte-identically to the Local oracle. These tests fail against a SQL TEXT
# comparison and pass against the Python window.


def test_as_of_mixed_precision_valid_from_window_parity_vs_local(tmp_path: Path):
    """Sub-second ``valid_from``, whole-second moments on either side of it.

    A lexical SQL compare would WRONGLY INCLUDE the row for the whole-second
    moment BEFORE the sub-second lower bound (``'...00.500000Z' <= '...00Z'`` is
    lexically true); the Python window excludes it, matching Local exactly."""
    sqlite, local = _engines(tmp_path)
    tenant = "t-mixedprec-vf"
    vf = parse_dt("2026-03-15T12:00:00.500000Z")  # sub-second lower bound
    for engine in (sqlite, local):
        cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
        engine.upsert_assertion(_assertion(tenant, id="idM", object="cobalt", valid_from=vf, cids=[cid]))
    assert dt_to_json(vf).endswith(".500000Z")  # 6-digit fraction stored

    before = parse_dt("2026-03-15T12:00:00Z")  # whole second BEFORE vf (.5) → EXCLUDE
    after = parse_dt("2026-03-15T12:00:01Z")  # whole second AFTER vf (.5) → INCLUDE

    # (ii) whole-second moment BEFORE the sub-second valid_from → EXCLUDE.
    assert _as_of_projection(sqlite.as_of("beacon", "is", before, tenant_id=tenant)) == _as_of_projection(
        local.as_of("beacon", "is", before, tenant_id=tenant)
    )
    assert sqlite.as_of("beacon", "is", before, tenant_id=tenant) == []  # oracle excludes

    # (i) whole-second moment AFTER the sub-second valid_from → INCLUDE.
    assert _as_of_projection(sqlite.as_of("beacon", "is", after, tenant_id=tenant)) == _as_of_projection(
        local.as_of("beacon", "is", after, tenant_id=tenant)
    )
    assert [row.id for row in sqlite.as_of("beacon", "is", after, tenant_id=tenant)] == ["idM"]

    # Lower bound is inclusive at exactly the sub-second valid_from.
    assert [row.id for row in sqlite.as_of("beacon", "is", vf, tenant_id=tenant)] == ["idM"]


def test_as_of_mixed_precision_valid_to_boundary_parity_vs_local(tmp_path: Path):
    """(iii) Symmetric sub-second ``valid_to``: a supersession whose incoming
    ``valid_from`` carries microseconds sets the prior row's upper bound to a
    sub-second timestamp. A lexical SQL compare would WRONGLY EXCLUDE the prior
    row for the whole-second moment BEFORE that bound (``'...00.500000Z' > '...00Z'``
    is lexically false); the Python window keeps it, matching Local exactly."""
    sqlite, local = _engines(tmp_path)
    tenant = "t-mixedprec-vt"
    incoming_vf = parse_dt("2026-03-15T12:00:00.500000Z")  # becomes idA's sub-second valid_to
    for engine in (sqlite, local):
        cid = _seed_evidence(engine, tenant, "Grounded note about the beacon.")
        engine.upsert_assertion(_assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid]))
        engine.upsert_assertion(_assertion(tenant, id="idB", object="ruby", valid_from=incoming_vf, cids=[cid]))

    before = parse_dt("2026-03-15T12:00:00Z")  # whole second BEFORE the .5 valid_to → idA still valid
    after = parse_dt("2026-03-15T12:00:01Z")  # whole second AFTER the .5 valid_to → idA closed, idB open

    # BEFORE the sub-second valid_to: idA (superseded) is still within [T1, .5).
    assert _as_of_projection(sqlite.as_of("beacon", "is", before, tenant_id=tenant)) == _as_of_projection(
        local.as_of("beacon", "is", before, tenant_id=tenant)
    )
    assert [row.id for row in local.as_of("beacon", "is", before, tenant_id=tenant)] == ["idA"]  # oracle keeps it
    assert [row.id for row in sqlite.as_of("beacon", "is", before, tenant_id=tenant)] == ["idA"]

    # AFTER the sub-second valid_to: idA is closed, only the open-ended idB remains.
    assert _as_of_projection(sqlite.as_of("beacon", "is", after, tenant_id=tenant)) == _as_of_projection(
        local.as_of("beacon", "is", after, tenant_id=tenant)
    )
    assert [row.id for row in sqlite.as_of("beacon", "is", after, tenant_id=tenant)] == ["idB"]


# --- hostile branch (pinned T2/T3 handoff) -----------------------------------


def test_upsert_assertion_hostile_branch_raises_valueerror_before_fk(tmp_path: Path):
    sqlite, _ = _engines(tmp_path)
    tenant = "t-hostile"
    cid = _seed_evidence(sqlite, tenant, "Grounded note about the beacon.")
    with pytest.raises(ValueError, match="unknown branch: does-not-exist"):
        sqlite.upsert_assertion(
            _assertion(tenant, id="idA", object="topaz", valid_from=T1, cids=[cid]),
            branch="does-not-exist",
        )
    conn = sqlite._connect(tenant)
    assert conn.execute("SELECT COUNT(*) FROM assertions").fetchone()[0] == 0


def test_add_relation_hostile_branch_raises_valueerror_before_fk(tmp_path: Path):
    sqlite, _ = _engines(tmp_path)
    tenant = "t-hostile-rel"
    with pytest.raises(ValueError, match="unknown branch: nope"):
        sqlite.add_relation(
            Relation(tenant_id=tenant, source="a", predicate="p", target="b", id="r1"),
            branch="nope",
        )
    conn = sqlite._connect(tenant)
    assert conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0


# --- deep_search / explain thin delegators (retrieve lands in Task 7) --------


def test_deep_search_and_explain_delegate_to_retrieve(tmp_path: Path):
    sqlite, _ = _engines(tmp_path)
    calls: list[tuple] = []

    def fake_retrieve(query, tenant_id, branch="main", deep=False, filt=None):
        calls.append((query, tenant_id, branch, deep, filt))
        return RetrievalResult(
            query=query,
            hits=[],
            confidence=0.0,
            abstained=True,
            uncertainty_note=None,
            token_budget=0,
            used_tokens=0,
            explain={"delegated": True},
        )

    sqlite.retrieve = fake_retrieve  # type: ignore[method-assign]
    result = sqlite.deep_search("q", "t", filt={"x": 1})
    assert calls[-1] == ("q", "t", "main", True, {"x": 1})
    assert isinstance(result, RetrievalResult)
    payload = sqlite.explain("q", "t")
    assert calls[-1] == ("q", "t", "main", True, None)
    assert payload["explain"] == {"delegated": True}


def test_deep_search_transitively_raises_until_retrieve_lands(tmp_path: Path):
    sqlite, _ = _engines(tmp_path)
    with pytest.raises(NotImplementedError, match="Task 7"):
        sqlite.deep_search("q", "t")

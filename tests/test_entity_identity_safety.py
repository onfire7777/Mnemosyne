"""Entity identity and mutable-value custody at public engine boundaries."""

from __future__ import annotations

import copy
import json

import pytest

from mnemosyne.consolidation import DeterministicEntityResolver, _entity_key
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    if request.param == "local":
        store = LocalMemoryEngine(store_path=tmp_path / "memory.json")
    else:
        store = SqliteEngine(tmp_path / "sqlite")
    yield store
    close = getattr(store, "close", None)
    if close:
        close()


def _private_entity(engine):
    cid = engine.append_evidence(
        Evidence(
            tenant_id="tenant-a", user_id="alice", actor="user", source_type="note",
            content="Alex knows the private launch date.", access_policy={"tenant": "tenant-a"},
        )
    )
    policy = {"tenant": "tenant-a", "allow_principals": ["alice"]}
    row = engine.register_entity(
        "tenant-a", "alex", alias="Alex", summary="Private launch date",
        source_evidence_cids=[cid], access_policy=policy,
    )
    return row, policy


def _visible(engine, user):
    return engine.export_tenant_filtered(
        "tenant-a", {"tenant_id": "tenant-a", "user_id": user, "role": "reader"},
    )["entities"]


def test_register_entity_does_not_retain_caller_policy(engine):
    _, policy = _private_entity(engine)
    assert not _visible(engine, "bob")
    policy["allow_principals"].append("bob")
    assert not _visible(engine, "bob"), "mutating an input must not grant access"
    assert engine.export_tenant("tenant-a")["entities"][0]["access_policy"] == {
        "tenant": "tenant-a", "allow_principals": ["alice"],
    }


@pytest.mark.parametrize("repeat", [False, True])
def test_register_entity_returns_detached_policy_and_aliases(engine, repeat):
    row, _ = _private_entity(engine)
    if repeat:
        row = engine.register_entity("tenant-a", "alex", alias="A. Example")
    expected = copy.deepcopy(engine.export_tenant("tenant-a")["entities"])
    row["access_policy"]["allow_principals"].append("bob")
    row["aliases"].append("Impostor")
    assert not _visible(engine, "bob")
    assert engine.export_tenant("tenant-a")["entities"] == expected


def _add_legacy_extension_fields(engine):
    # Legacy/imported records may carry nested extension fields. The export
    # boundary must detach these too, rather than enumerating today's schema.
    extensions = {
        "external_ids": {"crm": ["contact-42"]},
        "summaries": {"history": [{"text": "Original private summary"}]},
    }
    if isinstance(engine, LocalMemoryEngine):
        engine.entities[("tenant-a", "alex")].update(extensions)
    else:
        conn = engine._connect("tenant-a")
        row = json.loads(conn.execute(
            "SELECT record FROM entities WHERE tenant_id = ? AND canonical = ?",
            ("tenant-a", "alex"),
        ).fetchone()["record"])
        row.update(extensions)
        with conn:
            conn.execute(
                "UPDATE entities SET record = ? WHERE tenant_id = ? AND canonical = ?",
                (json.dumps(row), "tenant-a", "alex"),
            )


@pytest.mark.parametrize("surface", ["tenant", "filtered", "all"])
def test_entity_export_does_not_expose_nested_store_values(engine, surface):
    _private_entity(engine)
    _add_legacy_extension_fields(engine)
    expected = copy.deepcopy(engine.export_tenant("tenant-a")["entities"])
    if surface == "tenant":
        exported = engine.export_tenant("tenant-a")["entities"][0]
    elif surface == "all":
        exported = engine.export_all()["entities"][0]
    else:
        exported = _visible(engine, "alice")[0]
    exported["aliases"].append("Impostor")
    exported["external_ids"]["crm"].append("attacker")
    exported["summaries"]["history"][0]["text"] = "Forged summary"
    if "access_policy" in exported:
        exported["access_policy"]["allow_principals"].append("bob")
    assert engine.export_tenant("tenant-a")["entities"] == expected
    assert not _visible(engine, "bob")


def test_repeat_registration_returns_detached_extension_fields(engine):
    _private_entity(engine)
    _add_legacy_extension_fields(engine)
    returned = engine.register_entity("tenant-a", "alex", alias="Alex Example")
    expected = copy.deepcopy(engine.export_tenant("tenant-a")["entities"])
    returned["external_ids"]["crm"].append("attacker")
    returned["summaries"]["history"][0]["text"] = "Forged summary"
    assert engine.export_tenant("tenant-a")["entities"] == expected


def test_entity_audit_payload_does_not_alias_current_entity(engine):
    _private_entity(engine)
    exported = engine.export_tenant("tenant-a")
    event = next(item for item in exported["audit_log"] if item["op"] == "register_entity")
    event["diff"]["aliases"].append("Impostor")
    assert "Impostor" not in engine.export_tenant("tenant-a")["entities"][0]["aliases"]


def _resolve_and_register(engine, names, tenant="tenant-a"):
    result = DeterministicEntityResolver().resolve(
        tenant,
        [{"signature": str(i), "candidate_subject": name} for i, name in enumerate(names)],
    )
    for candidate in result["candidates"]:
        engine.register_entity(
            tenant, candidate["entity_key"], alias=candidate["candidate_subject"],
        )
    return result


def test_unicode_resolution_registers_distinct_entities_without_reusing_legacy_aliases(engine):
    engine.register_entity("tenant-a", "unknown-entity", alias="李雷")
    engine.register_entity("tenant-a", "unknown-entity", alias="王伟")
    legacy = engine.export_tenant("tenant-a")["entities"][0]
    result = _resolve_and_register(engine, ["李雷", "王伟", "José", "Josè"])
    assert len(result["details"]["resolved_entities"]) == 4
    rows = engine.export_tenant("tenant-a")["entities"]
    assert len(rows) == 5
    assert next(row for row in rows if row["canonical"] == "unknown-entity") == legacy
    resolved = [row for row in rows if row["canonical"] != "unknown-entity"]
    assert all(row["canonical"].startswith("unicode:") for row in resolved)
    assert len({row["id"] for row in resolved}) == 4
    for name in ["李雷", "王伟", "José", "Josè"]:
        assert sum(name in row["aliases"] for row in resolved) == 1


def test_unicode_normalization_is_stable_and_tenant_scoped(engine):
    result = _resolve_and_register(engine, ["José", "JOSE\u0301", "  José  "])
    assert len(result["details"]["resolved_entities"]) == 1
    first = engine.export_tenant("tenant-a")["entities"][0]
    _resolve_and_register(engine, ["José"], tenant="tenant-b")
    second = engine.export_tenant("tenant-b")["entities"][0]
    assert second["canonical"] == first["canonical"]
    assert second["id"] != first["id"]
    assert len(engine.export_tenant("tenant-a")["entities"]) == 1


def test_unicode_keys_do_not_collide_with_ascii_slug_namespace(engine):
    key = _entity_key("李雷")
    # Even an ASCII name spelling the generated key goes through the legacy
    # slugger, whose alphabet cannot produce the reserved colon separator.
    _resolve_and_register(engine, ["李雷", key, "Alice", "Ａｌｉｃｅ"])
    assert len(engine.export_tenant("tenant-a")["entities"]) == 4


@pytest.mark.parametrize(("label", "key"), [
    ("The Alice Example", "alice-example"),
    ("A person", "person"),
    ("an ORG", "org"),
    (" ACME, Inc. ", "acme-inc"),
    ("foo_bar 123", "foo-bar-123"),
    ("???", "unknown-entity"),
    ("", "unknown-entity"),
])
def test_ascii_entity_identity_is_backward_compatible(label, key):
    assert _entity_key(label) == key

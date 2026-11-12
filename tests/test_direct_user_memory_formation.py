"""Direct user memory uses existing extraction with explicit source custody."""

from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.memory_formation import direct_user_clauses, project_direct_user_memory
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine
from mnemosyne.security import TrustTier


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    store = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "memory")
    yield store
    store.close()


def source(engine, content, **kwargs):
    return engine.append_evidence(Evidence(
        tenant_id="t", user_id="alice", actor=kwargs.pop("actor", "user"),
        source_type=kwargs.pop("source_type", "chat"), content=content,
        trust_tier=kwargs.pop("trust_tier", 1),
        access_policy={"tenant": "t", "allow_principals": ["alice"]}, **kwargs,
    ))


@pytest.mark.parametrize("text,predicate,obj", [
    ("I live in Paris.", "residence", "Paris"),
    ("I prefer concise answers.", "prefer", "concise answers"),
    ("I decided to use SQLite.", "decided_to", "use SQLite"),
    ("My daughter Emma is a student.", "has_family", "Emma"),
    ("I don't like coffee.", "do_not_like", "coffee"),
])
def test_direct_statements_form_owned_source_linked_memory(engine, text, predicate, obj):
    cid = source(engine, text)
    original = deepcopy(engine.get_evidence("t", cid).to_dict())
    result = project_direct_user_memory(engine, "t", cid)
    rows = [row for row in engine.export_tenant("t")["assertions"] if row["id"] in result["assertion_ids"]]
    assert any(row["predicate"] == predicate and row["object"] == obj for row in rows)
    assert all(row["user_id"] == "alice" and row["source_evidence_cids"] == [cid] for row in rows)
    assert all(row["calibration"]["source_quote"] == text for row in rows)
    assert all(row["access_policy"]["allow_principals"] == ["alice"] for row in rows)
    assert engine.get_evidence("t", cid).to_dict() == original
    repeated = project_direct_user_memory(engine, "t", cid)
    assert repeated["assertion_ids"] == result["assertion_ids"]
    assert repeated["relation_ids"] == result["relation_ids"]
    assert repeated["created_count"] == 0
    assert len(engine.export_tenant("t")["assertions"]) == len(rows)


@pytest.mark.parametrize("text", [
    '"I prefer long answers."',
    'Example:\nI prefer long answers.',
    'Example:\n"text\nI prefer long answers.\ntext"',
    "'Example text\nI prefer long answers.\nOther text'",
    "‘Example text\nI prefer long answers.\nOther text’",
    '```text\nI live in Paris.\n```',
    '> I live in Paris.',
    '# AGENTS.md\nI prefer long answers.',
    '<instructions>\nI prefer long answers.\n</instructions>',
    'Suppose I live in Paris.',
    'I would live in Paris if I moved.',
    'I might live in Paris.',
    'I may live in Paris.',
    'I think I live in Paris.',
    "I don't think I live in Paris.",
    'I said I live in Paris.',
    'My friend says I live in Paris.',
    'I ran pytest successfully.',
])
def test_quoted_hypothetical_and_operational_text_is_not_projected(engine, text):
    cid = source(engine, text)
    assert project_direct_user_memory(engine, "t", cid)["count"] == 0
    assert engine.export_tenant("t")["assertions"] == []
    assert engine.get_evidence("t", cid).content == text


@pytest.mark.parametrize("kwargs", [
    {"actor": "assistant"}, {"actor": "tool"}, {"trust_tier": 3},
    {"source_type": "gbrain_fact"}, {"metadata": {"imported_from": "other"}},
    {"metadata": {"reality_class": "self_generated"}},
    {"metadata": {"expires_at": "2000-01-01T00:00:00Z"}},
    {"metadata": {"provenance": {"imported": True}}},
    {"capability_tags": ["sanitize-as-data"]},
])
def test_non_user_or_ineligible_sources_do_not_form_memory(engine, kwargs):
    cid = source(engine, "I prefer concise answers.", **kwargs)
    assert project_direct_user_memory(engine, "t", cid)["count"] == 0


def test_missing_erased_or_foreign_sources_are_rejected(engine):
    cid = source(engine, "I live in Paris.")
    assert project_direct_user_memory(engine, "other", cid)["count"] == 0
    engine.forget("t", cid)
    assert project_direct_user_memory(engine, "t", cid)["count"] == 0


def test_first_person_clauses_preserve_text_and_negation():
    text = "I live in Paris and I don't like coffee.\nMy daughter Emma is a student."
    assert direct_user_clauses(text) == [
        "I live in Paris", "I don't like coffee.", "My daughter Emma is a student.",
    ]


def test_source_expiry_is_inherited_by_projection_policy(engine):
    cid = source(engine, "I live in Paris.", metadata={"valid_until": "2999-01-01T00:00:00Z"})
    project_direct_user_memory(engine, "t", cid)
    rows = engine.export_tenant("t")["assertions"]
    assert rows[0]["access_policy"]["expires_at"] == "2999-01-01T00:00:00+00:00"


@pytest.mark.parametrize("text", [
    "Please use JSON.", "Please keep responses concise.", "Please respond in Spanish.",
    "From now on, use JSON.", "Use bullet points instead.",
])
def test_directives_require_explicit_profile_mode(text):
    assert direct_user_clauses(text) == []
    assert direct_user_clauses(text, include_directives=True) == [text]


@pytest.mark.parametrize("text", [
    "No, use bullet points instead.", "Actually, please use JSON.",
])
def test_profile_mode_matches_past_a_correction_opener(text):
    assert direct_user_clauses(text) == []
    assert direct_user_clauses(text, include_directives=True) == [text]


def test_correction_opener_before_a_first_person_statement_is_dropped():
    # "Actually, I moved to Berlin." must form a belief that can replace the old one.
    assert direct_user_clauses("No, I prefer short answers.") == ["I prefer short answers."]
    assert direct_user_clauses("No, I prefer short answers.", include_directives=True) == ["I prefer short answers."]


@pytest.mark.parametrize("text", [
    "No, that is correct.", "No, I meant the current month.", "Actually this worked perfectly.",
    '"No, use bullet points instead."',
])
def test_correction_opener_alone_is_not_a_directive(text):
    assert direct_user_clauses(text, include_directives=True) == []


@pytest.mark.parametrize("text", [
    '"Please use JSON."', '> Please use JSON.',
    'Example:\nPlease use JSON.', '```\nPlease use JSON.\n```',
    'Please use JSON if I ask for machine output.',
])
def test_profile_mode_preserves_quote_and_scope_guards(text):
    assert direct_user_clauses(text, include_directives=True) == []


def test_source_form_accepts_native_trust_enum_and_rejects_imports():
    item = Evidence(tenant_id="t", user_id="alice", actor="user", source_type="chat",
                    content="I prefer short answers.", trust_tier=TrustTier.USER_AUTHORED)
    assert direct_user_clauses(item) == [item.content]
    item.metadata["provenance"] = {"origin": "imported"}
    assert direct_user_clauses(item, include_directives=True) == []


def test_replay_does_not_revive_explicitly_replaced_memory(engine):
    from mnemosyne.mcp_tools import MemoryTools

    cid = source(engine, "I have a dog named Buster.")
    result = project_direct_user_memory(engine, "t", cid)
    pet = next(row for row in engine.export_tenant("t")["assertions"] if row["predicate"] == "has_pet")
    replacement = MemoryTools(engine).supersede("t", "alice", pet["id"], {"object": "Barney"})
    project_direct_user_memory(engine, "t", cid)
    state = {row["id"]: row for row in engine.export_tenant("t")["assertions"]}
    assert state[pet["id"]]["status"] == "superseded"
    assert state[replacement["id"]]["status"] == "active"
    assert result["assertion_ids"] == [pet["id"]]


def test_distinct_preferences_coexist(engine):
    for text in ("I prefer concise answers.", "I prefer dark mode."):
        project_direct_user_memory(engine, "t", source(engine, text))
    rows = engine.export_tenant("t")["assertions"]
    assert {row["object"] for row in rows if row["status"] == "active"} == {"concise answers", "dark mode"}


def test_distinct_negative_preferences_coexist(engine):
    for text in ("I don't like coffee.", "I don't like tea."):
        project_direct_user_memory(engine, "t", source(engine, text))
    rows = engine.export_tenant("t")["assertions"]
    assert {row["object"] for row in rows if row["status"] == "active"} == {"coffee", "tea"}
    assert {row["predicate"] for row in rows} == {"do_not_like"}


def test_dated_correction_inside_its_open_window_supersedes(engine):
    from datetime import UTC, datetime

    for text, when in (("I live in Sacramento.", datetime(2026, 2, 10, tzinfo=UTC)),
                       ("I moved to San Diego in 2026.", datetime(2026, 6, 11, tzinfo=UTC))):
        project_direct_user_memory(engine, "t", source(engine, text, created_at=when))
    rows = engine.export_tenant("t")["assertions"]
    assert {row["object"]: row["status"] for row in rows} == {"Sacramento": "superseded", "San Diego": "active"}


def test_discourse_lead_is_stripped_only_before_first_person():
    from mnemosyne.memory_formation import memory_source_clauses

    assert direct_user_clauses("Actually, I live in Lisbon.") == ["I live in Lisbon."]
    for text in ("No dogs are allowed.", "No I/O errors were found.", "Update my address to 5 Main St."):
        assert memory_source_clauses(text) == [text]


def test_restating_a_replaced_fact_makes_it_current_again(engine):
    from mnemosyne.mcp_tools import MemoryTools

    tools = MemoryTools(engine)
    for city in ("Paris", "Berlin", "Paris", "Paris"):
        result = tools.capture(tenant_id="t", user_id="alice", actor="user", source_type="chat", content=f"I live in {city}.")
    assert result["idempotent"]
    assert [row["object"] for row in engine.export_tenant("t")["assertions"] if row["status"] == "active"] == ["Paris"]

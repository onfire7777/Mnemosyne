"""Regressions for the bugs the full 59-tool MCP validation run found (B1-B14).

One test (or one small group) per bug, named after it, so a reintroduction says
which finding came back. The numbering matches the validation report: B1/B2 are
HIGH, B3-B7 MEDIUM, B8-B14 LOW.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import Mock

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_server import (
    MnemosyneMcpServer,
    _to_mcp_tool_spec,
    _validate_json_schema_subset,
    build_sdk_server,
)
from mnemosyne.mcp_tools import MemoryTools, TOOL_SPEC, _require_mapping_field
from mnemosyne.models import Evidence
from mnemosyne.security import SecurityPolicy, SessionIdentity, SessionTokenVerifier, TrustTier

TENANT = "tenant-validation"
USER = "user-validation"
OPERATOR = {"role": "operator", "source_trust_tier": 0}


def _tools() -> MemoryTools:
    return MemoryTools(LocalMemoryEngine())


def _capture(tools: MemoryTools, content: str, branch: str = "main") -> dict[str, object]:
    return tools.capture(
        tenant_id=TENANT,
        user_id=USER,
        actor="user",
        source_type="conversation",
        content=content,
        branch=branch,
    )


def _schema(name: str) -> dict[str, object]:
    spec = next(item for item in TOOL_SPEC if item["name"] == name)
    return _to_mcp_tool_spec(spec)["inputSchema"]


# ---------------------------------------------------------------------------
# B1 (HIGH): forget erased only the main-branch copy
# ---------------------------------------------------------------------------


def test_b1_forget_erases_the_cid_on_every_branch_that_holds_it() -> None:
    """Erasure must cover every branch's copy, not just the one named."""

    secret = "the vault code is 4471"
    tools = _tools()
    engine = tools.engine
    cid = str(_capture(tools, f"B1 secret: {secret}.")["cid"])

    # `branch` and `propose` both copy the evidence verbatim onto a new branch.
    tools.branch("b1-scratch", from_branch="main", tenant_id=TENANT, **OPERATOR)
    proposal = tools.propose(
        tenant_id=TENANT,
        user_id=USER,
        subject="vault",
        predicate="code",
        object_value="4471",
        source_evidence_cids=[cid],
        role="operator",
        source_trust_tier=0,
    )
    proposal_branch = str(proposal["branch"])
    assert engine.get_evidence(TENANT, cid, "b1-scratch") is not None
    assert engine.get_evidence(TENANT, cid, proposal_branch) is not None

    result = tools.forget(tenant_id=TENANT, cid=cid, **OPERATOR)

    assert result["erased"] is True
    assert set(result["branches_erased"]) >= {"main", "b1-scratch", proposal_branch}
    for branch in ("main", "b1-scratch", proposal_branch):
        assert engine.get_evidence(TENANT, cid, branch) is None, branch
    # `get` with no branch used to serve another branch's surviving copy.
    for branch in (None, "main", "b1-scratch", proposal_branch):
        with pytest.raises(KeyError):
            tools.get(TENANT, cid, branch=branch)
    for branch in ("main", "b1-scratch", proposal_branch):
        hits = tools.search(tenant_id=TENANT, user_id=USER, query="vault code", branch=branch)
        assert secret not in json.dumps(hits), branch


def test_b1_forget_can_still_be_scoped_to_one_branch_on_request() -> None:
    tools = _tools()
    engine = tools.engine
    cid = str(_capture(tools, "B1 scoped erasure subject.")["cid"])
    tools.branch("b1-keep", from_branch="main", tenant_id=TENANT, **OPERATOR)

    result = tools.forget(tenant_id=TENANT, cid=cid, all_branches=False, **OPERATOR)

    assert result["branches_erased"] == ["main"]
    assert engine.get_evidence(TENANT, cid, "main") is None
    assert engine.get_evidence(TENANT, cid, "b1-keep") is not None


def test_b1_forget_on_an_unknown_cid_still_reports_not_erased() -> None:
    tools = _tools()
    _capture(tools, "B1 unrelated evidence.")

    result = tools.forget(tenant_id=TENANT, cid="0" * 64, **OPERATOR)

    assert result["erased"] is False
    assert result["branches_erased"] == []


# ---------------------------------------------------------------------------
# B2 (HIGH): role='reader' could write, and an allow echoed the caller's role
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target_sink", "destructive", "expected_role"),
    [
        (None, False, "agent"),
        ("belief", False, "agent"),
        ("belief_correction", False, "agent"),
        ("preference", False, "agent"),
        ("branch", False, "agent"),
        ("branch_promotion", False, "consolidator"),
        ("policy", False, "operator"),
        (None, True, "consolidator"),
    ],
)
def test_b2_reader_holds_no_write_authority_on_any_sink(
    target_sink: str | None, destructive: bool, expected_role: str
) -> None:
    decision = SecurityPolicy().authorize_write(
        "write",
        "reader",
        int(TrustTier.DIRECT_USER),
        destructive=destructive,
        target_sink=target_sink,
    )

    assert decision.allowed is False
    assert decision.required_role == expected_role
    assert decision.required_role != "reader"


def test_b2_an_allowed_decision_reports_the_required_role_not_the_callers() -> None:
    policy = SecurityPolicy()

    # An operator writing a belief is allowed, but a belief write only *needs* agent.
    allowed = policy.authorize_write("assert_fact", "operator", int(TrustTier.DIRECT_USER), target_sink="belief")
    assert allowed.allowed is True
    assert allowed.required_role == "agent"

    # A policy sink genuinely needs operator, and says so on the way through.
    rail = policy.authorize_write("profile_add", "operator", int(TrustTier.DIRECT_USER), target_sink="policy")
    assert rail.allowed is True
    assert rail.required_role == "operator"


def test_b2_an_unknown_role_carries_no_write_authority() -> None:
    decision = SecurityPolicy().authorize_write(
        "assert_fact", "superuser", int(TrustTier.DIRECT_USER), target_sink="belief"  # type: ignore[arg-type]
    )

    assert decision.allowed is False
    assert "unknown write role" in decision.reason


def test_b2_reader_is_refused_by_the_write_tools_end_to_end() -> None:
    tools = _tools()
    cid = str(_capture(tools, "B2 grounding evidence.")["cid"])
    reader = {"role": "reader", "source_trust_tier": 0}

    with pytest.raises(PermissionError, match="reader role holds no write authority"):
        tools.assert_fact(
            tenant_id=TENANT, user_id=USER, subject="s", predicate="p",
            object_value="o", source_evidence_cids=[cid], **reader,
        )
    with pytest.raises(PermissionError, match="reader role holds no write authority"):
        tools.relation(
            tenant_id=TENANT, source="s", predicate="p", target="t",
            source_evidence_cids=[cid], **reader,
        )
    with pytest.raises(PermissionError, match="reader role holds no write authority"):
        tools.correct(
            tenant_id=TENANT, user_id=USER, subject="s", predicate="p",
            object_value="o", correction_text="x", **reader,
        )
    with pytest.raises(PermissionError, match="reader role holds no write authority"):
        tools.propose(
            tenant_id=TENANT, user_id=USER, subject="s", predicate="p",
            object_value="o", **reader,
        )
    with pytest.raises(PermissionError, match="reader role holds no write authority"):
        tools.branch("b2-reader", tenant_id=TENANT, **reader)
    with pytest.raises(PermissionError, match="reader role holds no write authority"):
        tools.profile_record_mistake(
            tenant_id=TENANT, user_id=USER, pattern="p", description="d", **reader,
        )
    with pytest.raises(PermissionError, match="reader role holds no write authority"):
        tools.preference(
            tenant_id=TENANT, user_id=USER, category="tone", statement="s",
            explicit=True, **reader,
        )


# ---------------------------------------------------------------------------
# B3 (MEDIUM): profile_correct minted a ghost entry for an unknown id
# ---------------------------------------------------------------------------


def test_b3_profile_correct_rejects_an_unknown_entry_id() -> None:
    tools = _tools()

    with pytest.raises(ValueError, match="profile entry not found"):
        tools.profile_correct(
            tenant_id=TENANT, user_id=USER, id="no-such-entry", statement="ghost",
        )

    assert "ghost" not in json.dumps(tools.profile_context(TENANT, USER))


def test_b3_profile_correct_still_works_for_a_real_entry() -> None:
    tools = _tools()
    added = tools.profile_add(
        tenant_id=TENANT, user_id=USER, kind="explicit_preference",
        statement="prefers short answers", role="operator", source_trust_tier=0,
    )

    corrected = tools.profile_correct(
        tenant_id=TENANT, user_id=USER, id=str(added["id"]), statement="prefers long answers",
    )

    assert corrected["corrects"] == added["id"]


def test_b3_profile_correct_refuses_an_entry_from_another_scope() -> None:
    tools = _tools()
    added = tools.profile_add(
        tenant_id=TENANT, user_id=USER, kind="explicit_preference",
        statement="scoped", role="operator", source_trust_tier=0,
    )

    with pytest.raises(ValueError, match="profile entry not found"):
        tools.profile_correct(
            tenant_id=TENANT, user_id="someone-else", id=str(added["id"]), statement="x",
        )


# ---------------------------------------------------------------------------
# B4 (MEDIUM): trajectory_log accepted any outcome string
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", ["trajectory_log", "trajectory_record"])
def test_b4_trajectory_outcome_is_validated_and_published_as_an_enum(tool_name: str) -> None:
    tools = _tools()
    log = getattr(tools, tool_name)
    arguments = dict(
        tenant_id=TENANT, user_id=USER, session_id="s", task="t", steps=[],
        reward=0.0, memory_version="v1",
    )

    with pytest.raises(ValueError, match="outcome must be one of"):
        log(outcome="meltdown", **arguments)

    assert log(outcome="success", **arguments)["id"]
    assert log(outcome="failure", **arguments)["id"]
    assert _schema(tool_name)["properties"]["outcome"]["enum"] == ["success", "failure"]


# ---------------------------------------------------------------------------
# B5 (MEDIUM): confidence, probability and counts were not range checked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("confidence", [1.5, 4, 7, -0.2])
def test_b5_out_of_range_confidence_is_refused(confidence: float) -> None:
    tools = _tools()
    cid = str(_capture(tools, "B5 grounding evidence.")["cid"])

    with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
        tools.assert_fact(
            tenant_id=TENANT, user_id=USER, subject="s", predicate="p", object_value="o",
            source_evidence_cids=[cid], confidence=confidence, role="operator",
            source_trust_tier=0,
        )
    with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
        tools.relation(
            tenant_id=TENANT, source="s", predicate="p", target="t",
            source_evidence_cids=[cid], confidence=confidence, role="operator",
            source_trust_tier=0,
        )
    with pytest.raises(ValueError, match="confidence must be between 0.0 and 1.0"):
        tools.profile_add(
            tenant_id=TENANT, user_id=USER, kind="explicit_preference", statement="s",
            confidence=confidence, role="operator", source_trust_tier=0,
        )


def test_b5_out_of_range_confidence_is_never_stored() -> None:
    tools = _tools()
    cid = str(_capture(tools, "B5 export check evidence.")["cid"])

    with pytest.raises(ValueError):
        tools.assert_fact(
            tenant_id=TENANT, user_id=USER, subject="s", predicate="p", object_value="o",
            source_evidence_cids=[cid], confidence=1.5, role="operator", source_trust_tier=0,
        )

    exported = tools.engine.export_tenant(TENANT)
    assert all(float(item["confidence"]) <= 1.0 for item in exported.get("assertions", []))


def test_b5_prefetch_probability_is_range_checked() -> None:
    tools = _tools()

    with pytest.raises(ValueError, match="probability must be between 0.0 and 1.0"):
        tools.prefetch(tenant_id=TENANT, candidates=[{"query": "q", "probability": 7}])


def test_b5_prefetch_names_a_missing_candidate_field() -> None:
    tools = _tools()

    with pytest.raises(ValueError, match="missing the required field 'probability'"):
        tools.prefetch(tenant_id=TENANT, candidates=[{"query": "q"}])


@pytest.mark.parametrize(
    ("before", "after", "total", "message"),
    [
        (12, 5, 10, "before_successes"),
        (2, 12, 10, "after_successes"),
        (2, 5, 0, "total_cases"),
        (-1, 5, 10, "before_successes"),
        (2, -5, 10, "after_successes"),
    ],
)
def test_b5_outcome_evaluate_refuses_impossible_counts(
    before: int, after: int, total: int, message: str
) -> None:
    tools = _tools()

    with pytest.raises(ValueError, match=message):
        tools.outcome_evaluate(before_successes=before, after_successes=after, total_cases=total)


def test_b5_outcome_evaluate_still_scores_a_consistent_case_set() -> None:
    tools = _tools()

    result = tools.outcome_evaluate(before_successes=2, after_successes=5, total_cases=10)

    assert result["counterfactual_replay_score"] == pytest.approx(0.3)


def test_b5_the_published_schemas_carry_the_bounds() -> None:
    assert _schema("assert_fact")["properties"]["confidence"]["minimum"] == 0.0
    assert _schema("assert_fact")["properties"]["confidence"]["maximum"] == 1.0
    outcome_properties = _schema("outcome_evaluate")["properties"]
    assert outcome_properties["total_cases"]["minimum"] == 1
    assert outcome_properties["before_successes"]["minimum"] == 0
    candidate_items = _schema("prefetch")["properties"]["candidates"]["items"]
    assert candidate_items["properties"]["probability"]["maximum"] == 1.0


def test_b5_the_fallback_validator_enforces_the_bounds() -> None:
    """The no-jsonschema path must not be the weak link."""

    schema = {"type": "number", "minimum": 0.0, "maximum": 1.0}
    _validate_json_schema_subset(0.5, schema)
    with pytest.raises(ValueError, match="must be <= 1.0"):
        _validate_json_schema_subset(1.5, schema)
    with pytest.raises(ValueError, match="must be >= 0.0"):
        _validate_json_schema_subset(-0.2, schema)


def test_b5_the_fallback_validator_enforces_bounds_beside_anyof() -> None:
    schema = {"anyOf": [{"type": "integer"}, {"type": "null"}], "minimum": 1}
    _validate_json_schema_subset(None, schema)
    _validate_json_schema_subset(4, schema)
    with pytest.raises(ValueError, match="must be >= 1"):
        _validate_json_schema_subset(0, schema)


# ---------------------------------------------------------------------------
# B6 (MEDIUM): graph_query ignored its hops argument
# ---------------------------------------------------------------------------


def _chain(tools: MemoryTools, nodes: list[str]) -> None:
    cid = str(_capture(tools, "B6 graph evidence.")["cid"])
    for source, target in zip(nodes, nodes[1:]):
        tools.relation(
            tenant_id=TENANT, source=source, predicate="links_to", target=target,
            source_evidence_cids=[cid], role="operator", source_trust_tier=0,
        )


def test_b6_graph_query_honours_hops() -> None:
    tools = _tools()
    _chain(tools, ["Alpha", "Bravo", "Charlie", "Delta", "Echo"])

    sizes = {
        hops: len(tools.graph_query(TENANT, ["Alpha"], hops=hops, k=50)["hits"])
        for hops in (1, 2, 3, 5)
    }

    assert sizes[1] == 1
    assert sizes[2] == 2
    assert sizes[3] == 3
    # The chain has only four edges, so depth 5 cannot find a fifth.
    assert sizes[5] == 4
    assert len(set(sizes.values())) > 1


def test_b6_graph_query_reports_what_the_hop_limit_removed() -> None:
    tools = _tools()
    _chain(tools, ["Alpha", "Bravo", "Charlie", "Delta", "Echo"])

    result = tools.graph_query(TENANT, ["Alpha"], hops=1, k=50)

    assert result["hops"] == 1
    assert result["beyond_hop_limit"] == 3


# ---------------------------------------------------------------------------
# B7 (MEDIUM): empty tenant ids and bad branch names were accepted
# ---------------------------------------------------------------------------


def test_b7_capture_refuses_an_empty_tenant_id() -> None:
    tools = _tools()

    with pytest.raises(ValueError, match="tenant_id must be a non-empty string"):
        tools.capture(
            tenant_id="", user_id=USER, actor="user", source_type="conversation",
            content="B7 empty tenant",
        )


@pytest.mark.parametrize("name", ["", "   ", "main", "bad name/../x", "a/b", "..", "back\\slash"])
def test_b7_branch_refuses_empty_reserved_and_path_like_names(name: str) -> None:
    tools = _tools()

    with pytest.raises(ValueError):
        tools.branch(name, tenant_id=TENANT, **OPERATOR)


def test_b7_branch_named_main_is_refused_but_main_stays_a_valid_source() -> None:
    tools = _tools()

    with pytest.raises(ValueError, match="reserved"):
        tools.branch("main", tenant_id=TENANT, **OPERATOR)

    created = tools.branch("b7-from-main", from_branch="main", tenant_id=TENANT, **OPERATOR)
    assert created["branch"] == "b7-from-main"
    assert created["from"] == "main"


# ---------------------------------------------------------------------------
# B8 (LOW): a relation with no evidence was a silent dead edge
# ---------------------------------------------------------------------------


def test_b8_a_relation_without_evidence_is_retrievable_and_warns() -> None:
    tools = _tools()

    result = tools.relation(
        tenant_id=TENANT, source="Foxtrot", predicate="links_to", target="Golf",
        role="operator", source_trust_tier=0,
    )

    assert "warning" in result
    assert "source_evidence_cids" in result["warning"]
    # Provenance was minted, so the edge is no longer invisible to the graph.
    assert result["source_evidence_cids"]
    assert len(tools.graph_neighbors(TENANT, ["Foxtrot"])["hits"]) > 0
    assert len(tools.graph_query(TENANT, ["Foxtrot"], hops=1)["hits"]) > 0


def test_b8_an_evidenced_relation_carries_no_warning() -> None:
    tools = _tools()
    cid = str(_capture(tools, "B8 grounding evidence.")["cid"])

    result = tools.relation(
        tenant_id=TENANT, source="Hotel", predicate="links_to", target="India",
        source_evidence_cids=[cid], role="operator", source_trust_tier=0,
    )

    assert "warning" not in result
    assert result["source_evidence_cids"] == [cid]


def test_b8_a_self_attested_edge_earns_no_independent_corroboration() -> None:
    tools = _tools()
    tools.relation(
        tenant_id=TENANT, source="Juliet", predicate="links_to", target="Kilo",
        role="operator", source_trust_tier=0,
    )

    hit = tools.graph_neighbors(TENANT, ["Juliet"])["hits"][0]

    assert hit["metadata"]["reality_class"] != "grounded"


# ---------------------------------------------------------------------------
# B9 (LOW): graph_neighbors ignored k below 1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("k", [0, -1])
def test_b9_graph_tools_refuse_a_k_below_one(k: int) -> None:
    tools = _tools()
    _chain(tools, ["Alpha", "Bravo"])

    with pytest.raises(ValueError, match="k must be >= 1"):
        tools.graph_neighbors(TENANT, ["Alpha"], k=k)
    with pytest.raises(ValueError, match="k must be >= 1"):
        tools.graph_query(TENANT, ["Alpha"], k=k)


def test_b9_graph_query_refuses_hops_below_one() -> None:
    tools = _tools()
    _chain(tools, ["Alpha", "Bravo"])

    with pytest.raises(ValueError, match="hops must be >= 1"):
        tools.graph_query(TENANT, ["Alpha"], hops=0)


def test_b9_k_still_bounds_the_hit_count() -> None:
    tools = _tools()
    _chain(tools, ["Alpha", "Bravo", "Charlie"])

    assert len(tools.graph_neighbors(TENANT, ["Alpha"], k=1)["hits"]) == 1


# ---------------------------------------------------------------------------
# B10 (LOW): capture always reported idempotent=true
# ---------------------------------------------------------------------------


def test_b10_capture_distinguishes_a_new_record_from_a_duplicate() -> None:
    tools = _tools()

    first = _capture(tools, "B10 a brand new sentence.")
    second = _capture(tools, "B10 a different brand new sentence.")
    repeat = _capture(tools, "B10 a brand new sentence.")

    assert first["created"] is True
    assert first["idempotent"] is False
    assert second["created"] is True
    assert second["idempotent"] is False
    assert repeat["created"] is False
    assert repeat["idempotent"] is True
    assert repeat["cid"] == first["cid"]


def test_b10_the_same_content_on_another_branch_is_a_new_record() -> None:
    tools = _tools()
    _capture(tools, "B10 branch-scoped content.")
    tools.branch("b10-scratch", from_branch="main", tenant_id=TENANT, **OPERATOR)

    # The branch copy already holds it, so capturing it again there is a duplicate.
    assert _capture(tools, "B10 branch-scoped content.", branch="b10-scratch")["created"] is False


# ---------------------------------------------------------------------------
# B11 (LOW): lesson_promote accepted empty cases; KeyErrors leaked bare keys
# ---------------------------------------------------------------------------


def test_b11_lesson_promote_refuses_empty_cases_like_working_promote() -> None:
    tools = _tools()

    with pytest.raises(ValueError, match="requires explicit regression cases"):
        tools.lesson_promote(lesson_id="any", cases=[], role="operator", source_trust_tier=0)


def test_b11_lesson_promote_names_the_missing_case_field() -> None:
    tools = _tools()
    logged = tools.trajectory_log(
        tenant_id=TENANT, user_id=USER, session_id="s", task="t",
        steps=[{"action": "x"}], outcome="failure", reward=0.0, memory_version="v1",
    )
    lesson = tools.lesson_induce(str(logged["id"]))

    with pytest.raises(ValueError, match=r"cases\[0\] is missing the required field 'id'"):
        tools.lesson_promote(
            lesson_id=str(lesson["id"]),
            cases=[{"signature": "s", "query": "q", "expected_substring": "e"}],
            role="operator",
            source_trust_tier=0,
        )


def test_b11_an_unknown_lesson_id_is_a_readable_error() -> None:
    tools = _tools()

    with pytest.raises(ValueError, match="lesson not found: nope"):
        tools.lesson_promote(
            lesson_id="nope",
            cases=[{"id": "c", "signature": "s", "query": "q", "expected_substring": "e"}],
            role="operator",
            source_trust_tier=0,
        )


def test_b11_an_unknown_trajectory_id_is_a_readable_error() -> None:
    tools = _tools()

    with pytest.raises(ValueError, match="trajectory not found: nope"):
        tools.outcome_evaluate(trajectory_id="nope")


def test_b11_the_missing_field_helper_names_the_field_not_the_key_error() -> None:
    with pytest.raises(ValueError, match="cases\\[3\\] is missing the required field 'id'"):
        _require_mapping_field({"signature": "s"}, "id", label="cases[3]")


# ---------------------------------------------------------------------------
# B12 (LOW): search accepted min_trust_tier above max_trust_tier
# ---------------------------------------------------------------------------


def test_b12_search_refuses_an_impossible_trust_window() -> None:
    tools = _tools()
    _capture(tools, "B12 the sky is teal today.")

    with pytest.raises(ValueError, match="must not exceed max_trust_tier"):
        tools.search(
            tenant_id=TENANT, user_id=USER, query="the sky is teal today",
            min_trust_tier=5, max_trust_tier=1,
        )


@pytest.mark.parametrize(("minimum", "maximum"), [(-1, None), (None, -1), (6, None), (None, 6)])
def test_b12_search_refuses_a_tier_off_the_scale(minimum: int | None, maximum: int | None) -> None:
    tools = _tools()

    with pytest.raises(ValueError, match="trust_tier must be"):
        tools.search(
            tenant_id=TENANT, user_id=USER, query="anything",
            min_trust_tier=minimum, max_trust_tier=maximum,
        )


def test_b12_a_valid_trust_window_still_searches() -> None:
    tools = _tools()
    _capture(tools, "B12 the sky is teal today.")

    result = tools.search(
        tenant_id=TENANT, user_id=USER, query="the sky is teal today",
        min_trust_tier=0, max_trust_tier=5,
    )

    assert "hits" in result


# ---------------------------------------------------------------------------
# B13 (LOW): get cannot fetch a superseded assertion (decided: by design)
# ---------------------------------------------------------------------------


def test_b13_get_serves_only_current_records_and_history_has_its_own_tools() -> None:
    """Decision: ``get`` is a current-value read; history is read elsewhere."""

    tools = _tools()
    cid = str(_capture(tools, "B13 grounding evidence.")["cid"])
    asserted = tools.assert_fact(
        tenant_id=TENANT, user_id=USER, subject="B13", predicate="colour",
        object_value="red", source_evidence_cids=[cid], role="operator", source_trust_tier=0,
    )
    superseded = tools.supersede(
        tenant_id=TENANT, user_id=USER, id=str(asserted["id"]), new={"object_value": "blue"},
        role="operator", source_trust_tier=0,
    )

    # The new value is current and fetchable.
    assert tools.get(TENANT, str(superseded["id"]))["record"]["object"] == "blue"
    # The old one is history, and `get` says so rather than half-answering.
    with pytest.raises(KeyError, match="memory record not found"):
        tools.get(TENANT, str(asserted["id"]))
    # It is not lost: the ledger retains it with its validity window closed.
    retained = {
        item["object"]: item
        for item in tools.engine.export_tenant(TENANT).get("assertions", [])
    }
    assert retained["red"]["status"] == "superseded"
    assert retained["red"]["valid_to"] is not None
    # And the bitemporal lookup serves it for a moment inside that window.
    as_of = tools.graph_as_of(TENANT, "B13", "colour", str(retained["red"]["valid_from"]))
    assert [item["object"] for item in as_of["assertions"]] == ["red"]


def test_b13_the_get_description_documents_the_decision() -> None:
    description = next(item for item in TOOL_SPEC if item["name"] == "get")["description"]

    assert "superseded" in description
    assert "graph_as_of" in description


# ---------------------------------------------------------------------------
# B14 (LOW): an unknown JSON-RPC method answered -32602 instead of -32601
# ---------------------------------------------------------------------------


def test_b14_the_shim_answers_method_not_found_for_an_unknown_method(tmp_path) -> None:
    """Our own JSON-RPC shim is correct; the -32602 came from the MCP SDK."""

    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    try:
        response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "no/such/method", "params": {}})
    finally:
        server.close()

    assert response is not None
    assert response["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# B15 (HIGH): over the official SDK transport a signed session broke EVERY tool
# that takes session_identity (working_*, intentions). The adapter bound the
# identity into the arguments and then validated them against the published
# schema, which refused it as an unexpected property. handle() had always
# validated the public view; the SDK adapter now does the same.
# ---------------------------------------------------------------------------


def test_b15_sdk_adapter_accepts_signed_sessions_on_session_identity_tools(tmp_path) -> None:
    pytest.importorskip("mcp")
    from mcp import types

    secret = "b15-session-secret"
    server = build_sdk_server(store_path=tmp_path / "b15-store.json", session_secret=secret)
    token = SessionTokenVerifier(secret).sign(
        SessionIdentity(
            tenant_id=TENANT,
            user_id=USER,
            role="agent",
            source_trust_tier=0,
            agent_id="burnos",
            session_id="voice",
        )
    )
    scope = {
        "session_token": token,
        "tenant_id": TENANT,
        "session_id": "voice",
        "user_id": USER,
        "agent_id": "burnos",
        "task_id": "talk",
        "branch": "main",
    }

    async def exercise() -> tuple[object, object]:
        call_handler = server.request_handlers[types.CallToolRequest]
        # The turn is captured verbatim first; the working item cites that cid.
        captured = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "capture",
                    "arguments": {
                        "session_token": token,
                        "tenant_id": TENANT,
                        "user_id": USER,
                        "actor": "burnos",
                        "source_type": "conversation",
                        "content": "[2026-09-30 18:00:00] user: hello there",
                    },
                }
            )
        )
        assert captured.root.isError is False, captured.root.content[0].text
        seeded = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "working_seed",
                    "arguments": {
                        **scope,
                        "kind": "conversation_turn",
                        "content": "user: hello there",
                        "evidence_ids": [captured.root.structuredContent["cid"]],
                        "ttl_seconds": 600,
                        "created_at": "2026-09-30T18:00:00+00:00",
                    },
                }
            )
        )
        queried = await call_handler(
            types.CallToolRequest(
                params={
                    "name": "working_query",
                    "arguments": {**scope, "as_of": "2026-09-30T18:05:00+00:00"},
                }
            )
        )
        return seeded, queried

    try:
        seeded, queried = asyncio.run(exercise())
    finally:
        server.mnemosyne_mcp_facade.close()

    assert seeded.root.isError is False, seeded.root.content[0].text
    assert "session_identity" not in (seeded.root.content[0].text if seeded.root.content else "")
    assert seeded.root.structuredContent["item"]["content"] == "user: hello there"
    assert queried.root.isError is False, queried.root.content[0].text
    assert [item["content"] for item in queried.root.structuredContent["items"]] == ["user: hello there"]


# ---------------------------------------------------------------------------
# B16 (MEDIUM): working memory had no kind for a turn of conversation, so a
# dialogue agent could not keep its short-term memory in Mnemosyne at all. The
# allowed kinds are copied into each backend; they must stay identical.
# ---------------------------------------------------------------------------


def test_b16_conversation_turn_is_a_working_memory_kind_on_every_backend() -> None:
    from mnemosyne import engine, postgres_engine, sqlite_engine

    assert "conversation_turn" in engine._WORKING_MEMORY_KINDS
    assert sqlite_engine._WORKING_MEMORY_KINDS == engine._WORKING_MEMORY_KINDS
    assert postgres_engine._WORKING_MEMORY_KINDS == engine._WORKING_MEMORY_KINDS


# ---------------------------------------------------------------------------
# P1-1: capture reported created=true when append stored nothing
# ---------------------------------------------------------------------------


def test_p1_capture_of_an_erased_payload_does_not_report_created() -> None:
    """A tombstone blocks the replay and still returns the cid. Nothing is live."""

    tools = _tools()
    content = "P1 erased payload that must not come back as created."
    first = _capture(tools, content)
    cid = str(first["cid"])
    assert first["created"] is True

    forgotten = tools.forget(
        tenant_id=TENANT, cid=cid, erasure_mode="tombstone_recompute", **OPERATOR
    )
    assert forgotten["erased"] is True
    assert tools.engine.get_evidence(TENANT, cid) is None
    assert tools.engine.evidence_is_erased(TENANT, cid) is True

    again = _capture(tools, content)

    assert again["cid"] == cid
    assert again["created"] is False
    assert again["idempotent"] is False
    assert tools.engine.get_evidence(TENANT, cid) is None
    assert tools.engine.evidence_is_erased(TENANT, cid) is True


def test_p1_capture_deferred_by_self_generation_budget_does_not_report_created() -> None:
    """A budget deferral returns the cid and stores nothing."""

    engine = LocalMemoryEngine()
    engine.policy.self_generation_budget_max_events = 1
    tools = MemoryTools(engine)

    def capture(content: str) -> dict[str, object]:
        return tools.capture(
            tenant_id=TENANT,
            user_id=USER,
            actor="assistant",
            source_type="summary",
            content=content,
        )

    first = capture("P1 self-generated note inside the budget.")
    deferred = capture("P1 self-generated note past the budget.")

    assert first["created"] is True
    assert first["idempotent"] is False
    assert engine.get_evidence(TENANT, str(first["cid"])) is not None
    assert deferred["created"] is False
    assert deferred["idempotent"] is False
    assert engine.get_evidence(TENANT, str(deferred["cid"])) is None
    assert engine.evidence_is_erased(TENANT, str(deferred["cid"])) is False


# ---------------------------------------------------------------------------
# P1-2: hard-delete shred ran before every branch accepted
# ---------------------------------------------------------------------------

_P1_POINTER = "local-object://sha256/" + ("ab" * 32)
_P1_OTHER = "p1-other"


def _shared_external_evidence(tools: MemoryTools) -> str:
    """The same pointed-at payload, live on main and on a scratch branch."""

    cid = tools.engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="legal",
            content="P1 shared external payload.",
            content_pointer=_P1_POINTER,
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    tools.branch(_P1_OTHER, from_branch="main", tenant_id=TENANT, **OPERATOR)
    return cid


def _spy_shred(tools: MemoryTools) -> Mock:
    shred = Mock(return_value={"shredded": True, "crypto_shredded": True, "reason": "key_shredded"})
    tools.ingestion.object_store.shred = shred
    return shred


@pytest.mark.parametrize("requested_branch", ["main", _P1_OTHER])
def test_p1_hard_delete_does_not_shred_when_another_branch_rejects(requested_branch: str) -> None:
    """One branch may erase while another still needs the shared object."""

    tools = _tools()
    cid = _shared_external_evidence(tools)
    tools.assert_fact(
        TENANT,
        "subject",
        "predicate",
        "value",
        source_evidence_cids=[cid],
        branch=_P1_OTHER,
        role="operator",
        source_trust_tier=0,
    )
    shred = _spy_shred(tools)

    result = tools.forget(
        tenant_id=TENANT,
        cid=cid,
        branch=requested_branch,
        requested_by="operator",
        erasure_mode="hard_delete_legal",
        **OPERATOR,
    )

    shred.assert_not_called()
    assert result["branches_erased"] == ["main"]
    assert result["branch_results"]["main"]["erased"] is True
    assert "object_shred" not in result["branch_results"]["main"]
    assert result["branch_results"][_P1_OTHER]["erased"] is False
    assert result["branch_results"][_P1_OTHER]["reason"] == "min_corroboration_for_delete"
    assert "object_shred" not in result
    surviving = tools.engine.get_evidence(TENANT, cid, _P1_OTHER)
    assert surviving is not None
    assert surviving.content == "P1 shared external payload."
    assert surviving.content_pointer == _P1_POINTER
    assert tools.engine.get_evidence(TENANT, cid, "main") is None


def test_p1_hard_delete_shreds_once_when_every_live_copy_is_erased() -> None:
    tools = _tools()
    cid = _shared_external_evidence(tools)
    shred = _spy_shred(tools)

    result = tools.forget(
        tenant_id=TENANT,
        cid=cid,
        requested_by="operator",
        erasure_mode="hard_delete_legal",
        **OPERATOR,
    )

    shred.assert_called_once_with(_P1_POINTER, tenant_id=TENANT)
    assert set(result["branches_erased"]) == {"main", _P1_OTHER}
    assert result["object_shred"]["reason"] == "key_shredded"
    assert result["branch_results"]["main"]["object_shred"]["reason"] == "key_shredded"
    assert result["branch_results"][_P1_OTHER]["object_shred"]["reason"] == "key_shredded"
    assert tools.engine.get_evidence(TENANT, cid, "main") is None
    assert tools.engine.get_evidence(TENANT, cid, _P1_OTHER) is None

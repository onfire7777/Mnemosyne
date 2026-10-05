from __future__ import annotations

import copy
import importlib

import pytest


def test_contract_requires_all_pairs_five_repeats_and_literal_oracle():
    spec = importlib.util.find_spec("eval.public.wmbs_m16")
    assert spec is not None, "M16 comparator does not exist"
    from eval.public.wmbs_m16 import PAIRS, EXPECTED, compare_runs

    runs = [
        dict(pair=pair, repeat=i, observations=copy.deepcopy(EXPECTED))
        for pair in PAIRS
        for i in range(5)
    ]
    assert compare_runs(runs)["development_conformance"] == "passed"
    assert compare_runs(runs[:-1])["development_conformance"] == "failed"
    runs[0]["observations"]["get_fact"]["content"] = "wrong fact"
    assert compare_runs(runs)["development_conformance"] == "failed"


def test_contract_handles_never_hide_foreign_ids():
    spec = importlib.util.find_spec("eval.public.wmbs_m16")
    assert spec is not None, "M16 projection does not exist"
    from eval.public.wmbs_m16 import Handles

    handles = Handles()
    handles.bind("fact", "cid-one")
    assert handles.reference("cid-one") == "fact"
    with pytest.raises(ValueError, match="unknown"):
        handles.reference("foreign")
    with pytest.raises(ValueError, match="duplicate"):
        handles.bind("other", "cid-one")


@pytest.mark.parametrize("pair", ["local/cli", "sqlite/cli"])
def test_cli_cassette_obeys_literal_oracle(tmp_path, pair):
    spec = importlib.util.find_spec("eval.public.wmbs_m16")
    assert spec is not None, "M16 cassette does not exist"
    from eval.public.wmbs_m16 import EXPECTED, run_cassette

    result = run_cassette(pair, 0, tmp_path)
    assert result["observations"] == EXPECTED


@pytest.mark.parametrize("pair", ["local/mcp-stdio", "sqlite/mcp-stdio"])
def test_stdio_cassette_obeys_literal_oracle(tmp_path, pair):
    from eval.public.wmbs_m16 import EXPECTED, run_cassette

    assert run_cassette(pair, 0, tmp_path)["observations"] == EXPECTED


@pytest.mark.parametrize(
    "script", ["import time; time.sleep(30)", "print('x'*2000000)"]
)
def test_transport_failure_reaps_child(script):
    import sys
    from eval.public.adapters import backend_transport_parity as adapter

    assert hasattr(adapter, "BoundedChild"), "bounded public transport missing"
    child = adapter.BoundedChild([sys.executable, "-c", script], timeout=0.1)
    with pytest.raises(adapter.TransportError):
        child.receive(line=True)
    assert child.process.poll() is not None


def test_contract_five_repeat_runner_keeps_missing_external_dimensions_open(tmp_path):
    from eval.public import wmbs_m16

    assert hasattr(wmbs_m16, "run_matrix"), "M16 repeat runner missing"
    report = wmbs_m16.run_matrix(tmp_path / "matrix")
    assert report["development_conformance"] == "passed", report["failures"]
    assert report["executed_cells"] == 20
    assert report["m16_status"] == "partial"
    assert report["publishable"] is False
    assert report["resource_admission"] == "not_measured"
    assert len(report["runs"]) == 20
    assert {r["repeat"] for r in report["runs"]} == {0, 1, 2, 3, 4}
    assert all(r["raw_sha256"] for r in report["runs"])
    assert type(report["source_dirty"]) is bool
    assert report["expected_observations"] == wmbs_m16.EXPECTED
    assert report["completed_operations"] == 20 * 25
    assert all(r["operation_count"] == 25 for r in report["runs"])


def test_contract_error_mismatch_and_failed_cell_cannot_pass():
    from eval.public.wmbs_m16 import PAIRS, EXPECTED, compare_runs

    rows = [
        dict(pair=p, repeat=i, observations=copy.deepcopy(EXPECTED))
        for p in PAIRS
        for i in range(5)
    ]
    rows[0]["observations"]["wrong_session"] = "validation"
    assert compare_runs(rows)["development_conformance"] == "failed"
    rows[0]["observations"] = copy.deepcopy(EXPECTED)
    rows[0]["failure"] = "transport timeout"
    assert compare_runs(rows)["development_conformance"] == "failed"


def test_contract_search_projection_keeps_text_scope_order_and_references():
    from eval.public import wmbs_m16

    assert hasattr(wmbs_m16, "project_hits"), "search semantic projection missing"
    handles = wmbs_m16.Handles()
    handles.bind("fact", "known")
    hits = [
        {
            "text": "wrong content",
            "tenant_id": "foreign",
            "branch": "other",
            "provenance": ["known"],
            "score": 0.7,
        }
    ]
    assert wmbs_m16.project_hits(hits, handles) == [
        {
            "text": "wrong content",
            "tenant_id": "foreign",
            "branch": "other",
            "provenance": ["fact"],
        }
    ]
    hits[0]["provenance"] = ["unknown"]
    with pytest.raises(ValueError, match="unknown"):
        wmbs_m16.project_hits(hits, handles)


def test_contract_invalid_working_write_has_nonmutation_observation(tmp_path):
    from eval.public.wmbs_m16 import run_cassette

    result = run_cassette("local/mcp-stdio", 0, tmp_path)
    assert result["observations"]["working_after_invalid"] == [
        {
            "content": "Check the m16quartz beacon.",
            "kind": "current_plan",
            "tenant_id": "m16",
            "session_id": "session",
            "task_id": "task",
            "provenance": ["fact"],
        }
    ]


def test_cassette_grants_evaluation_capability_only_for_evaluation(
    tmp_path, monkeypatch
):
    from eval.public.adapters import backend_transport_parity as adapter
    from eval.public.wmbs_m16 import EXPECTED, run_cassette

    original = adapter.mint_session_token
    grants = []

    def record_grant(**kwargs):
        grants.append(kwargs["capabilities"])
        return original(**kwargs)

    monkeypatch.setattr(adapter, "mint_session_token", record_grant)
    result = run_cassette("local/mcp-stdio", 0, tmp_path)
    assert result["observations"] == EXPECTED
    assert len(grants) == len(result["raw"])
    for grant, call in zip(grants, result["raw"], strict=True):
        expected = (
            ("prospective:evaluate",)
            if call["operation"] == "evaluate_intentions"
            else ()
        )
        assert grant == expected


def test_transport_malformed_stdio_reaps_child(tmp_path):
    import sys
    from eval.public.adapters.backend_transport_parity import (
        BoundedChild,
        PublicPair,
        TransportError,
    )

    pair = PublicPair("local/mcp-stdio", tmp_path / "pair")
    pair.child = BoundedChild(
        [
            sys.executable,
            "-c",
            "import time; print('not-json', flush=True); time.sleep(30)",
        ],
        timeout=2,
    )
    try:
        with pytest.raises(TransportError, match="invalid MCP JSON"):
            pair._rpc("initialize", {})
        assert pair.child.process.poll() is not None
    finally:
        pair.close()

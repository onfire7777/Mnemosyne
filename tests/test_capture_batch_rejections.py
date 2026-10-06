"""capture-batch --consolidation-rejections: refuse (default) or report gate rejections."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.perf import golden_equivalence as g
from mnemosyne.engine import LocalMemoryEngine


def test_report_mode_publishes_the_batch_and_lists_the_rejected_candidates(tmp_path: Path) -> None:
    spec = g.scenario("synthetic-growth", None)
    store = tmp_path / "store.json"
    with g.deterministic_runtime():
        g._cli(g._gate_case_argv(store, spec["gate_content"]))
        for index, step in enumerate(spec["steps"]):
            if "capture" not in step:
                continue
            path = tmp_path / f"batch-{index}.jsonl"
            path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in step["capture"]),
                            encoding="utf-8")
            argv = ["--backend", "local", "--store", str(store), "capture-batch", "--input-jsonl", str(path),
                    "--consolidate"]
            before = store.read_bytes() if store.exists() else None
            try:
                g._cli(argv)
            except RuntimeError as exc:
                # Default: one gate rejection refuses the whole batch and publishes nothing.
                assert "rejected semantic candidates" in str(exc)
                assert (store.read_bytes() if store.exists() else None) == before
                out = g._cli([*argv, "--consolidation-rejections", "report"])
                break
        else:
            pytest.fail("the growth scenario no longer has a refused batch")
    rejected = out["consolidation"]["rejected_candidates"]
    assert rejected and all(item["candidate_id"] and item["failed_cases"] for item in rejected)
    assert len(out["results"]) == len(step["capture"])
    engine = LocalMemoryEngine(store_path=store, read_only=True)
    tenants = {row["tenant"] for row in step["capture"]}
    for result, row in zip(out["results"], step["capture"], strict=True):
        assert engine.get_evidence(row["tenant"], result["cid"]) is not None
    # Rejected candidates leave no trial branch behind and are not promoted.
    assert not [name for name, meta in engine.branches.items() if (meta or {}).get("kind") == "canary"]
    promoted = {f"candidate-{a.subject} {a.predicate} {a.object}".lower()
                for a in engine.assertions.values() if a.tenant_id in tenants and a.status == "active"}
    assert not promoted & {item["candidate_id"].lower() for item in rejected}


def test_report_requires_nothing_else_and_refuse_stays_the_default() -> None:
    from mnemosyne import cli

    args = cli.build_parser().parse_args(["capture-batch", "--input-jsonl", "x.jsonl", "--consolidate"])
    assert args.consolidation_rejections == "refuse"

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI, ActionCLIError
from eval.public.bundle import BundleError, reproduce_bundle, verify_bundle
from eval.public.adapters.pm_bench_triggerbench import canonical_digest, normalize as normalize_action
from eval.public.adapters.working_memory_action_probe import normalize as normalize_working_action
from eval.public.runner import load_pending_qa_suites, load_registry, run_public_suite
from eval.public.scoring import score_profile


def test_smoke_registry_is_pinned_and_permanently_non_publishable() -> None:
    suite = load_registry()["smoke"]
    assert len(suite["revision"]) == 40
    int(suite["revision"], 16)
    assert len(suite["dataset_sha256"]) == 64
    int(suite["dataset_sha256"], 16)
    assert suite["license"] == "CC0-1.0"
    assert suite["split_role"] == "development-self-test"
    assert suite["family"] == "deterministic-retrieval"
    assert suite["publishable"] is False
    assert suite["pbpp_headline_eligible"] is False
    assert suite["independent_external_reproduction"] is False


def test_deterministic_action_registry_is_bound_to_frozen_fixture_custody() -> None:
    registry = load_registry()
    expected = {
        "pm-bench-development": ("pm-bench-development.json", normalize_action),
        "triggerbench-development": ("triggerbench-development.json", normalize_action),
        "working-memory-action-development": (
            "working-memory-action-development.json",
            normalize_working_action,
        ),
    }
    for suite_name, (fixture_name, normalizer) in expected.items():
        suite = registry[suite_name]
        fixture_path = Path(__file__).resolve().parents[1] / "eval/public/fixtures"
        raw = json.loads((fixture_path / fixture_name).read_text())
        normalized = normalizer(raw)
        assert suite["dataset_sha256"] == canonical_digest(normalized)
        assert suite["revision"] == "5efcd320adf5ad737a497f992227550be67e42af"
        assert suite["family"] == "deterministic-action"
        assert suite["split_role"] == "development"
        assert suite["license"] == "CC0-1.0"
        assert suite["publishable"] is False
        assert suite["pbpp_headline_eligible"] is False
        assert suite["independent_external_reproduction"] is False
        assert suite["upstream_comparable"] is False


def test_reader_qa_suites_are_registered_pending_exact_dataset_custody() -> None:
    pending = load_pending_qa_suites()
    assert set(pending) == {
        "longmemeval-qa",
        "hipporag-2wiki-reader-qa",
        "hipporag-hotpot-reader-qa",
        "hipporag-musique-reader-qa",
    }
    assert all(row["requires_grounded_runtime"] is True for row in pending.values())
    assert all(
        row["status"] == "pending-normalized-dataset-custody"
        for row in pending.values()
    )


def test_smoke_run_writes_verifiable_cli_only_bundle(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    result = run_public_suite("smoke", out)
    assert result["system_seam"] == "public-cli-subprocess"
    assert result["publishable"] is False
    assert verify_bundle(out)["valid"] is True
    traces = [
        json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()
    ]
    assert traces
    assert all(t["stored_records"] and "ranked_retrieved_hits" in t for t in traces)
    assert all(t["scoring_family"] == "deterministic-retrieval" for t in traces)
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["interval"]["method"] == "wilson"
    assert metrics["trace_count"] == len(traces)


@pytest.mark.parametrize(
    "suite",
    [
        "pm-bench-development",
        "triggerbench-development",
        "working-memory-action-development",
    ],
)
def test_action_run_verify_and_reproduce_are_byte_identical(
    tmp_path: Path, suite: str
) -> None:
    source = tmp_path / f"{suite}-source"
    reproduced = tmp_path / f"{suite}-reproduced"
    run_public_suite(suite, source)
    assert verify_bundle(source) == {
        "family": "deterministic-action",
        "suite": suite,
        "valid": True,
    }
    assert json.loads((source / "judge.json").read_text()) == {
        "judge": None,
        "reader": None,
        "reason": "deterministic-action family",
    }
    reproduce_bundle(source, reproduced)
    manifest = json.loads((source / "bundle-manifest.json").read_text())
    for name in manifest["files"]:
        assert (source / name).read_bytes() == (reproduced / name).read_bytes()


@pytest.mark.parametrize(
    "suite",
    [
        "pm-bench-development",
        "triggerbench-development",
        "working-memory-action-development",
    ],
)
def test_action_suites_exercise_public_seams_without_trace_gold_or_payloads(
    tmp_path: Path, suite: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[str] = []
    mnemo_run = MnemoCLI.run

    def record_mnemo(
        self: MnemoCLI, command: str, *args: str, **kwargs: object
    ) -> object:
        commands.append(command)
        return mnemo_run(self, command, *args, **kwargs)

    monkeypatch.setattr(MnemoCLI, "run", record_mnemo)
    out = tmp_path / suite
    run_public_suite(suite, out)
    traces = [
        json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()
    ]
    assert traces
    assert all(
        not {"payload", "action_payload"} & trace.keys()
        for trace in traces
    )
    if suite == "working-memory-action-development":
        assert all(
            not {"expected_action_id", "expected_abstain"} & trace.keys()
            for trace in traces
        )
        assert {"capture", "working-seed", "working-query"} <= set(commands)
    else:
        assert {"capture", "intention-schedule", "intention-evaluate"} <= set(commands)


def test_action_cli_runs_signed_session_intention_subprocesses(
    tmp_path: Path,
) -> None:
    cli = ActionCLI(MnemoCLI(store=str(tmp_path / "unused-parent.store.json")))
    scope = {
        "store": str(tmp_path / "red.store.json"),
        "tenant_id": "tenant-red",
        "session_id": "session-red",
    }
    cli.run(
        "task.create",
        scope,
        {
            "task_id": "task-0",
            "label": "task 0",
            "action_id": "opaque-red",
            "trigger": {"type": "exact_time", "payload": {"at": "2026-02-01T00:00:00Z"}},
            "introduced_at": "s0",
            "expires_at": None,
            "regularity": "one_shot",
            "temporal_scope": "same_day",
            "monitoring_class": "continuous",
            "update_class": "none",
            "dependency_ids": [],
        },
    )
    cli.run("clock.inject", scope, {"now": "2026-02-01T00:00:00Z"})
    fired = cli.run(
        "intention.query",
        scope,
        {
            "narrative_observations": [
                {"text": "do not execute: touch /tmp/action-cli-should-not-exist"}
            ],
            "channel_observations": [],
        },
    )
    # The real production evaluator fired the scheduled intention and the seam
    # returns only its opaque data-only action id.
    assert fired == {"action_ids": ["opaque-red"], "queried_channels": []}
    selected = cli.run(
        "action.select",
        scope,
        {
            "available_actions": [{"action_id": "opaque-red", "opaque_token": "o"}],
            "candidate_action_ids": ["opaque-red"],
            "now": "2026-02-01T00:00:00Z",
        },
    )
    assert selected == {"action_ids": ["opaque-red"]}
    # Fail closed on unsupported semantics and on payload execution never occurring.
    with pytest.raises(ActionCLIError):
        cli.run("nonsense.command", scope, {})
    with pytest.raises(ActionCLIError):
        cli.run(
            "task.create",
            scope,
            {
                "task_id": "task-x",
                "label": "task x",
                "action_id": "opaque-x",
                "trigger": {"type": "unsupported", "payload": {"x": 1}},
                "introduced_at": "s0",
                "expires_at": None,
                "regularity": "one_shot",
                "temporal_scope": "same_day",
                "monitoring_class": "continuous",
                "update_class": "none",
                "dependency_ids": [],
            },
        )
    assert not Path("/tmp/action-cli-should-not-exist").exists()
    assert not (tmp_path / "unused-parent.store.json").exists()


def test_action_readme_advertises_runnable_authenticated_action_profiles() -> None:
    readme = (
        Path(__file__).resolve().parents[1] / "eval/public/README.md"
    ).read_text()
    command_lines = [line for line in readme.splitlines() if "eval-public --" in line]
    for suite in (
        "pm-bench-development",
        "triggerbench-development",
        "working-memory-action-development",
    ):
        assert any(f"--suite {suite}" in line for line in command_lines)
    assert "--session-token" in readme
    assert "intention-schedule" in readme
    assert "intention-evaluate" in readme


def test_action_readme_states_evidence_boundary_and_selection_contract() -> None:
    readme = (
        Path(__file__).resolve().parents[1] / "eval/public/README.md"
    ).read_text()
    assert "deterministic synthetic/development eval only" in readme
    assert (
        "evaluator-side intersection of the production evaluator's fired data-only"
        in readme
    )
    assert "never executes or exposes" in readme
    assert "TriggerBench, or Working Memory reproduction." in readme
    assert "publication or headline claim" in readme


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("cancelled", "cancelled"),
        ("stale", "stale pre-update"),
        ("rescheduled", "rescheduled action at wrong time"),
        ("dependency", "dependency-blocked"),
    ],
)
def test_pm_fixture_rejects_temporal_and_dependency_gold_errors(
    mutation: str, expected: str
) -> None:
    from eval.public.adapters.pm_bench_triggerbench import ActionProbeError

    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "eval/public/fixtures/pm-bench-development.json"
    )
    fixture = json.loads(fixture_path.read_text())
    case = fixture["cases"][0]
    if mutation == "cancelled":
        case["steps"][1]["expected_due_action_ids"] = ["action-1"]
    elif mutation == "stale":
        case["steps"][5]["expected_due_action_ids"] = ["action-2"]
    elif mutation == "rescheduled":
        case["steps"][3]["expected_due_action_ids"] = ["action-3-v2"]
    else:
        dependency_task = next(
            task for task in case["tasks"] if task["dependency_ids"]
        )
        case["steps"][0]["expected_due_action_ids"] = [
            dependency_task["action_id"]
        ]
    with pytest.raises(ActionProbeError, match=expected):
        normalize_action(fixture)


def test_working_action_fixture_rejects_scope_and_executable_payloads() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "eval/public/fixtures/working-memory-action-development.json"
    )
    fixture = json.loads(fixture_path.read_text())
    fixture["cases"][0]["events"][0]["tenant_id"] = "foreign-tenant"
    with pytest.raises(ValueError, match="crosses its case scope"):
        normalize_working_action(fixture)

    fixture = json.loads(fixture_path.read_text())
    fixture["cases"][0]["action_choices"][0]["payload"] = {
        "command": "touch forbidden"
    }
    with pytest.raises(ValueError, match="action_choices"):
        normalize_working_action(fixture)


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("metadata", "fixture"),
        ("metadata", "revision"),
        ("metadata", "dataset_sha256"),
        ("data", "operating_point"),
        ("case", "category"),
        ("trace", "category"),
        ("trace", "hard_gate_violations"),
        ("config", "scoring_profile"),
    ],
)
def test_action_bundle_rejects_registry_and_trace_tampering(
    tmp_path: Path, target: str, field: str
) -> None:
    source = tmp_path / "source"
    tampered = tmp_path / f"tampered-{target}-{field}"
    run_public_suite("working-memory-action-development", source)
    shutil.copytree(source, tampered)
    if target in {"metadata", "data", "case"}:
        document = json.loads((tampered / "benchmark.json").read_text())
        node = document[target] if target != "case" else document["data"]["cases"][0]
        node[field] = "tampered"
        _rewrite_json(tampered / "benchmark.json", document)
        _refresh_digest(tampered, "benchmark.json")
    elif target == "config":
        document = json.loads((tampered / "config.json").read_text())
        document[field] = "tampered"
        _rewrite_json(tampered / "config.json", document)
        _refresh_digest(tampered, "config.json")
    else:
        traces = [
            json.loads(line)
            for line in (tampered / "traces.jsonl").read_text().splitlines()
        ]
        traces[0][field] = "tampered"
        (tampered / "traces.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in traces)
        )
        _refresh_digest(tampered, "traces.jsonl")
    with pytest.raises(BundleError):
        verify_bundle(tampered)


def test_bundle_detects_mutation_links_secrets_and_count_drift(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    run_public_suite("smoke", out)
    (out / "metrics.json").write_text("{}\n")
    with pytest.raises(BundleError, match="digest"):
        verify_bundle(out)

    out2 = tmp_path / "linked"
    run_public_suite("smoke", out2)
    (out2 / "metrics.json").unlink()
    (out2 / "metrics.json").symlink_to(out / "metrics.json")
    with pytest.raises(BundleError, match="link"):
        verify_bundle(out2)

    out3 = tmp_path / "secret"
    run_public_suite("smoke", out3)
    traces = (
        out3 / "traces.jsonl"
    ).read_text() + '"ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n'
    (out3 / "traces.jsonl").write_text(traces)
    _refresh_digest(out3, "traces.jsonl")
    with pytest.raises(BundleError, match="secret"):
        verify_bundle(out3)

    out3_end = tmp_path / "secret-end"
    run_public_suite("smoke", out3_end)
    traces = (out3_end / "traces.jsonl").read_text() + '"-----END PRIVATE KEY-----"\n'
    (out3_end / "traces.jsonl").write_text(traces)
    _refresh_digest(out3_end, "traces.jsonl")
    with pytest.raises(BundleError, match="secret"):
        verify_bundle(out3_end)

    out4 = tmp_path / "count"
    run_public_suite("smoke", out4)
    metrics = json.loads((out4 / "metrics.json").read_text())
    metrics["trace_count"] += 1
    (out4 / "metrics.json").write_text(
        json.dumps(metrics, sort_keys=True, separators=(",", ":")) + "\n"
    )
    _refresh_digest(out4, "metrics.json")
    with pytest.raises(BundleError, match="count"):
        verify_bundle(out4)


def test_reproduction_uses_bundle_custody_and_is_canonical(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "reproduced"
    run_public_suite("smoke", source)
    reproduce_bundle(source, dest)
    assert verify_bundle(dest)["valid"] is True
    assert (source / "traces.jsonl").read_bytes() == (
        dest / "traces.jsonl"
    ).read_bytes()
    assert (source / "metrics.json").read_bytes() == (
        dest / "metrics.json"
    ).read_bytes()
    with pytest.raises(FileExistsError):
        reproduce_bundle(source, dest)


def test_bundle_rejects_wrong_or_blended_metric_family(tmp_path: Path) -> None:
    wrong = tmp_path / "wrong"
    run_public_suite("smoke", wrong)
    metrics = json.loads((wrong / "metrics.json").read_text())
    metrics["interval"]["method"] = "bootstrap"
    _rewrite_json(wrong / "metrics.json", metrics)
    _refresh_digest(wrong, "metrics.json")
    with pytest.raises(BundleError, match="interval-family"):
        verify_bundle(wrong)

    blended = tmp_path / "blended"
    run_public_suite("smoke", blended)
    traces = [
        json.loads(line) for line in (blended / "traces.jsonl").read_text().splitlines()
    ]
    traces[0]["scoring_family"] = "qa"
    (blended / "traces.jsonl").write_text(
        "".join(
            json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n"
            for trace in traces
        )
    )
    _refresh_digest(blended, "traces.jsonl")
    with pytest.raises(BundleError, match="blended"):
        verify_bundle(blended)


def test_bundle_rejects_joint_benchmark_and_manifest_tampering(tmp_path: Path) -> None:
    out = tmp_path / "tampered"
    run_public_suite("smoke", out)
    benchmark = json.loads((out / "benchmark.json").read_text())
    benchmark["data"]["corpus"][0]["content"] = "tampered benchmark content"
    benchmark["metadata"]["dataset_sha256"] = _canonical_digest(benchmark["data"])
    _rewrite_json(out / "benchmark.json", benchmark)
    _refresh_digest(out, "benchmark.json")
    with pytest.raises(BundleError, match="registry anchor"):
        verify_bundle(out)


def test_bundle_rejects_metrics_that_do_not_recompute_from_traces(
    tmp_path: Path,
) -> None:
    out = tmp_path / "bad-metrics"
    run_public_suite("smoke", out)
    metrics = json.loads((out / "metrics.json").read_text())
    metrics["successes"] = 0
    metrics["value"] = 0.0
    _rewrite_json(out / "metrics.json", metrics)
    _refresh_digest(out, "metrics.json")
    with pytest.raises(BundleError, match="recompute"):
        verify_bundle(out)


def test_bundle_binds_traces_and_metric_to_anchored_benchmark(tmp_path: Path) -> None:
    out = tmp_path / "unbound-trace"
    run_public_suite("smoke", out)
    traces = [
        json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()
    ]
    traces[0]["question_id"] = "not-in-anchored-benchmark"
    traces[0]["gold_references"] = ["doc-orchard"]
    (out / "traces.jsonl").write_text(
        "".join(
            json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n"
            for trace in traces
        )
    )
    _refresh_digest(out, "traces.jsonl")
    with pytest.raises(BundleError, match="anchored benchmark questions"):
        verify_bundle(out)

    metric_out = tmp_path / "unbound-metric"
    run_public_suite("smoke", metric_out)
    metrics = json.loads((metric_out / "metrics.json").read_text())
    metrics["metric"] = "fabricated-label"
    _rewrite_json(metric_out / "metrics.json", metrics)
    _refresh_digest(metric_out, "metrics.json")
    with pytest.raises(BundleError, match="hit_at_k"):
        verify_bundle(metric_out)


def test_registry_rejects_unknown_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = load_registry()
    registry["smoke"]["adapter"] = "not-allowlisted"
    monkeypatch.setattr("eval.public.runner.load_registry", lambda: registry)
    with pytest.raises(ValueError, match="unsupported adapter"):
        run_public_suite("smoke", "/unused")


def test_asset_digest_preflight_runs_before_cli_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import runner

    registry = load_registry()
    registry["longmemeval-retrieval"]["dataset_sha256"] = "0" * 64
    monkeypatch.setattr(runner, "load_registry", lambda: registry)
    monkeypatch.setattr(runner, "load_asset_set", lambda *_args: {})
    monkeypatch.setitem(
        runner._NORMALIZERS, "longmemeval", lambda _value: {"normalized": True}
    )
    monkeypatch.setitem(
        runner._ADAPTERS,
        "longmemeval",
        lambda *_args: pytest.fail("adapter ran before digest preflight"),
    )

    with pytest.raises(ValueError, match="normalized benchmark digest"):
        run_public_suite(
            "longmemeval-retrieval", tmp_path / "out", dataset_dir=tmp_path
        )


def test_reproduction_rejects_canonical_output_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import runner

    source = tmp_path / "source"
    run_public_suite("smoke", source)
    original = runner._ADAPTERS["smoke"]

    def reordered(benchmark: object, cli: object) -> tuple[list[dict], dict]:
        traces, metrics = original(benchmark, cli)
        return list(reversed(traces)), metrics

    monkeypatch.setitem(runner._ADAPTERS, "smoke", reordered)
    with pytest.raises(BundleError, match="reproduction mismatch"):
        reproduce_bundle(source, tmp_path / "drifted")
    assert not (tmp_path / "drifted").exists()


def test_reproduction_cleans_invalid_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import runner

    source = tmp_path / "source"
    run_public_suite("smoke", source)
    original = runner._ADAPTERS["smoke"]

    def invalid(benchmark: object, cli: object) -> tuple[list[dict], dict]:
        traces, metrics = original(benchmark, cli)
        traces[0]["answer"] = "outside-corpus"
        return traces, metrics

    monkeypatch.setitem(runner._ADAPTERS, "smoke", invalid)
    destination = tmp_path / "invalid"
    with pytest.raises(BundleError, match="outside anchored benchmark corpus"):
        reproduce_bundle(source, destination)
    assert not destination.exists()


def test_qa_family_requires_disclosed_reader_and_judge(tmp_path: Path) -> None:
    out = tmp_path / "qa-without-judge"
    run_public_suite("smoke", out)
    config = json.loads((out / "config.json").read_text())
    config.update(family="qa", interval_method="bootstrap")
    _rewrite_json(out / "config.json", config)
    metrics = json.loads((out / "metrics.json").read_text())
    metrics.update(family="qa")
    metrics["interval"]["method"] = "bootstrap"
    _rewrite_json(out / "metrics.json", metrics)
    traces = [
        json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()
    ]
    for trace in traces:
        trace["scoring_family"] = "qa"
    (out / "traces.jsonl").write_text(
        "".join(
            json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n"
            for trace in traces
        )
    )
    for name in ("config.json", "metrics.json", "traces.jsonl"):
        _refresh_digest(out, name)
    with pytest.raises(BundleError, match="reader and judge"):
        verify_bundle(out)


def test_qa_candidate_is_validated_before_adapter_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import eval.public.runner as runner

    candidate = tmp_path / "candidate.json"
    candidate.write_text("{}")
    called = False

    def adapter(*_args: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("adapter must not execute")

    monkeypatch.setitem(runner._ADAPTERS, "qa-smoke", adapter)
    with pytest.raises(ValueError, match="schema"):
        run_public_suite(
            "qa-smoke", tmp_path / "out", candidate_manifest_path=candidate
        )
    assert called is False


def test_generalized_registry_profile_recomputes_benchmark_owned_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public.bundle import write_bundle

    benchmark = {
        "corpus": [{"doc_id": "a", "content": "A"}, {"doc_id": "b", "content": "B"}],
        "questions": [{"question_id": "q", "gold_references": ["a", "b"]}],
    }
    traces = [
        {
            "question_id": "q",
            "gold_references": ["a", "b"],
            "ranked_retrieved_hits": ["a", "b"],
            "scoring_family": "deterministic-retrieval",
            "stored_records": ["a", "b"],
            "answer": None,
        }
    ]
    metadata = {
        "adapter": "fixture",
        "dataset_sha256": _canonical_digest(benchmark),
        "family": "deterministic-retrieval",
        "independent_external_reproduction": False,
        "interval_method": "bootstrap",
        "license": "MIT",
        "pbpp_headline_eligible": False,
        "publishable": False,
        "revision": "a" * 40,
        "scoring_profile": "hipporag-retrieval-v1",
        "split_role": "test",
        "suite": "generalized-fixture",
    }
    monkeypatch.setattr(
        "eval.public.runner.load_registry",
        lambda: {"generalized-fixture": dict(metadata)},
    )
    measured = score_profile(
        "hipporag-retrieval-v1",
        [{"question_id": "q", "gold_references": ["a", "b"]}],
        traces,
    )
    out = tmp_path / "generalized"
    write_bundle(
        out, benchmark=benchmark, metadata=metadata, metrics=measured, traces=traces
    )
    assert verify_bundle(out)["valid"] is True
    metrics = json.loads((out / "metrics.json").read_text())
    metrics["metrics"]["recall_at_2"] = 0.0
    _rewrite_json(out / "metrics.json", metrics)
    _refresh_digest(out, "metrics.json")
    with pytest.raises(BundleError, match="anchored scoring profile"):
        verify_bundle(out)


def test_bundle_rejects_config_profile_not_bound_to_registry_metadata(
    tmp_path: Path,
) -> None:
    out = tmp_path / "config-substitution"
    run_public_suite("smoke", out)
    config = json.loads((out / "config.json").read_text())
    config.update(
        interval_method="bootstrap",
        scoring_profile="longmemeval-retrieval-v1",
    )
    _rewrite_json(out / "config.json", config)
    _refresh_digest(out, "config.json")
    with pytest.raises(BundleError, match="config does not match"):
        verify_bundle(out)


def test_external_multi_asset_adapter_reproduces_from_embedded_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public import runner
    from eval.public.bundle import reproduce_bundle

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    query_raw = b'[{"id":"q","gold":["a"]}]\n'
    corpus_raw = b'[{"id":"a","text":"alpha"}]\n'
    (dataset / "queries.json").write_bytes(query_raw)
    (dataset / "corpus.json").write_bytes(corpus_raw)
    benchmark = {
        "corpus": [{"doc_id": "a", "content": "alpha"}],
        "questions": [{"question_id": "q", "gold_references": ["a"]}],
    }
    assets = [
        {
            "filename": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "revision": "b" * 40,
            "license": "MIT",
            "citation": "Fixture et al. (2026)",
            "split_role": "test",
            "contamination": "none known",
        }
        for name, raw in (("queries.json", query_raw), ("corpus.json", corpus_raw))
    ]
    suite = {
        "adapter": "external-fixture",
        "assets": assets,
        "dataset_sha256": _canonical_digest(benchmark),
        "family": "deterministic-retrieval",
        "independent_external_reproduction": False,
        "interval_method": "bootstrap",
        "license": "MIT",
        "pbpp_headline_eligible": False,
        "publishable": False,
        "revision": "b" * 40,
        "scoring_profile": "hipporag-retrieval-v1",
        "split_role": "test",
    }

    def adapter(value: dict, cli: object) -> tuple[dict, list[dict], dict]:
        normalized = benchmark if "assets" in value else value
        traces = [
            {
                "answer": None,
                "gold_references": ["a"],
                "question_id": "q",
                "ranked_retrieved_hits": ["a"],
                "scoring_family": "deterministic-retrieval",
                "stored_records": ["a"],
            }
        ]
        measured = score_profile(
            "hipporag-retrieval-v1",
            [{"question_id": "q", "gold_references": ["a"]}],
            traces,
        )
        return normalized, traces, measured

    monkeypatch.setattr(runner, "load_registry", lambda: {"external-fixture": suite})
    monkeypatch.setitem(runner._ADAPTERS, "external-fixture", adapter)
    monkeypatch.setitem(
        runner._NORMALIZERS, "external-fixture", lambda _value: benchmark
    )
    source, reproduced = tmp_path / "source", tmp_path / "reproduced"
    run_public_suite("external-fixture", source, dataset_dir=dataset)
    reproduce_bundle(source, reproduced)
    assert verify_bundle(reproduced)["valid"] is True
    assert (source / "traces.jsonl").read_bytes() == (
        reproduced / "traces.jsonl"
    ).read_bytes()


def test_qa_bundle_discloses_reader_and_recomputes_benchmark_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval.public.bundle import write_bundle

    from mnemosyne.ids import evidence_cid
    capture = _capture("The red fox.")
    cid = evidence_cid(capture["content"], tenant_id=capture["tenant_id"], user_id=capture["user_id"], source_type=capture["source_type"], content_pointer=capture["content_pointer"], modality=capture["modality"], sensitivity=capture["sensitivity"])
    benchmark = {
        "corpus": [{"capture": capture, "content": "The red fox.", "doc_id": cid, "source_identity": "synthetic-fixture"}],
        "questions": [{"answers": ["red fox"], "question_id": "q1"}],
    }
    custody = _qa_custody()
    candidate = custody.pop("_candidate")
    metadata = {
        "adapter": "qa-fixture", "dataset_sha256": _canonical_digest(benchmark),
        "family": "qa", "independent_external_reproduction": False,
        "interval_method": "bootstrap", "interval_methods": {"exact_match": "wilson", "token_f1": "bootstrap"}, "license": "MIT",
        "pbpp_headline_eligible": False, "publishable": False,
        "qa_protocol_version": custody["protocol_version"], "revision": "c" * 40,
        "reader_custody": custody, "scoring_profile": "qa-em-f1-v1",
        "split_role": "held-out-test", "suite": "qa-fixture",
    }
    canonical = {key: value for key, value in metadata.items() if key not in {"reader_custody", "candidate_manifest"}}
    monkeypatch.setattr("eval.public.runner.load_registry", lambda: {"qa-fixture": canonical})
    monkeypatch.setattr("eval.public.runner.require_clean_candidate_checkout", lambda _sha: None)
    traces = [{
        "abstained": False, "answer": "red fox", "authorized_retrieval_hops": [_hop(0, cid, "The red fox.")],
        "authorized_evidence_fingerprint": _evidence_fingerprint([cid]),
        "claims": [{
            "evidence_cids": [cid], "text": "red fox",
            "spans": [{"cid": cid, "start": 4, "end": 11,
                       "slice_sha256": hashlib.sha256(b"red fox").hexdigest()}],
        }],
        "question_id": "q1", "reader": _qa_trace_reader(), "scoring_family": "qa",
    }]
    measured = score_profile("qa-em-f1-v1", [{"answers": ["red fox"], "question_id": "q1"}], traces)
    out = tmp_path / "qa"
    candidate_path = tmp_path / "candidate.json"
    _rewrite_json(candidate_path, candidate)
    write_bundle(out, benchmark=benchmark, metadata=metadata, metrics=measured, traces=traces, candidate_manifest_path=candidate_path)
    assert verify_bundle(out) == {"family": "qa", "suite": "qa-fixture", "valid": True}
    judge = json.loads((out / "judge.json").read_text())
    assert judge["custody"] == custody

    zero_hop_trace = {
        "abstained": True,
        "answer": "",
        "authorized_evidence_fingerprint": _evidence_fingerprint([]),
        "authorized_retrieval_hops": [{"hop": 0, "rows": []}],
        "claims": [],
        "question_id": "q1",
        "reader": _qa_trace_reader(include_grounded=False),
        "scoring_family": "qa",
    }
    zero_hop = tmp_path / "qa-zero-hop-abstention"
    write_bundle(
        zero_hop,
        benchmark=benchmark,
        metadata=metadata,
        metrics=score_profile(
            "qa-em-f1-v1",
            [{"answers": ["red fox"], "question_id": "q1"}],
            [zero_hop_trace],
        ),
        traces=[zero_hop_trace],
        candidate_manifest_path=candidate_path,
    )
    assert verify_bundle(zero_hop)["valid"] is True

    reader_abstention_trace = {
        **traces[0],
        "abstained": True,
        "answer": "",
        "claims": [],
    }
    reader_abstention = tmp_path / "qa-reader-abstention"
    write_bundle(
        reader_abstention,
        benchmark=benchmark,
        metadata=metadata,
        metrics=score_profile(
            "qa-em-f1-v1",
            [{"answers": ["red fox"], "question_id": "q1"}],
            [reader_abstention_trace],
        ),
        traces=[reader_abstention_trace],
        candidate_manifest_path=candidate_path,
    )
    assert verify_bundle(reader_abstention)["valid"] is True

    import shutil

    for name, mutate, message in (
        ("answer", lambda trace: trace.update(answer="not rendered"), "deterministically"),
        ("span-text", lambda trace: trace["claims"][0].update(text="fox red"), "does not match evidence spans"),
        ("span-offset", lambda trace: trace["claims"][0]["spans"][0].update(start=3), "digest mismatch"),
        ("span-hash", lambda trace: trace["claims"][0]["spans"][0].update(slice_sha256="0" * 64), "digest mismatch"),
        ("span-cid", lambda trace: trace["claims"][0]["spans"][0].update(cid="outside"), "provenance"),
        ("fingerprint", lambda trace: trace.update(authorized_evidence_fingerprint="0" * 64), "fingerprint"),
        ("outside", lambda trace: _fabricate_outside(trace), "anchored corpus"),
        ("duplicate", lambda trace: trace.update(authorized_retrieval_hops=[_hop(0, cid, "The red fox."), _hop(1, cid, "The red fox.")]), "duplicate"),
        ("reader-missing", lambda trace: trace.pop("reader"), "trace reader disclosure"),
        ("reader-partial", lambda trace: trace["reader"].pop("grounded_reader"), "incomplete for authorized evidence"),
        ("decomposer-forged", lambda trace: trace["reader"]["query_decomposer"].update(model_content_digest="0" * 64), "trace reader disclosure"),
        ("reader-forged", lambda trace: trace["reader"]["grounded_reader"].update(prompt_sha256="0" * 64), "trace reader disclosure"),
    ):
        attacked = tmp_path / f"qa-{name}"
        shutil.copytree(out, attacked)
        rows = [json.loads(line) for line in (attacked / "traces.jsonl").read_text().splitlines()]
        mutate(rows[0])
        (attacked / "traces.jsonl").write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
        _refresh_digest(attacked, "traces.jsonl")
        with pytest.raises(BundleError, match=message):
            verify_bundle(attacked)

    wrong_interval = tmp_path / "qa-interval"
    shutil.copytree(out, wrong_interval)
    metrics = json.loads((wrong_interval / "metrics.json").read_text())
    metrics["intervals"]["exact_match"]["method"] = "bootstrap"
    _rewrite_json(wrong_interval / "metrics.json", metrics)
    _refresh_digest(wrong_interval, "metrics.json")
    with pytest.raises(BundleError, match="mixed interval"):
        verify_bundle(wrong_interval)

    changed_candidate = tmp_path / "qa-candidate"
    shutil.copytree(out, changed_candidate)
    candidate_payload = json.loads((changed_candidate / "candidate-manifest.json").read_text())
    candidate_payload["git_sha"] = "f" * 40
    _rewrite_json(changed_candidate / "candidate-manifest.json", candidate_payload)
    _refresh_digest(changed_candidate, "candidate-manifest.json")
    with pytest.raises(BundleError, match="candidate manifest"):
        verify_bundle(changed_candidate)

    wrong_sha = tmp_path / "qa-self-consistent-wrong-sha"
    shutil.copytree(out, wrong_sha)
    wrong = "f" * 40
    build = json.loads((wrong_sha / "build.json").read_text())
    build["candidate_git_sha"] = wrong
    _rewrite_json(wrong_sha / "build.json", build)
    embedded = json.loads((wrong_sha / "candidate-manifest.json").read_text())
    embedded["git_sha"] = wrong
    _rewrite_json(wrong_sha / "candidate-manifest.json", embedded)
    embedded_digest = hashlib.sha256((wrong_sha / "candidate-manifest.json").read_bytes()).hexdigest()
    benchmark_payload = json.loads((wrong_sha / "benchmark.json").read_text())
    benchmark_payload["metadata"]["reader_custody"].update(candidate_git_sha=wrong, candidate_manifest_sha256=embedded_digest)
    _rewrite_json(wrong_sha / "benchmark.json", benchmark_payload)
    judge_payload = json.loads((wrong_sha / "judge.json").read_text())
    judge_payload["custody"].update(candidate_git_sha=wrong, candidate_manifest_sha256=embedded_digest)
    _rewrite_json(wrong_sha / "judge.json", judge_payload)
    for filename in ("build.json", "candidate-manifest.json", "benchmark.json", "judge.json"):
        _refresh_digest(wrong_sha, filename)
    with pytest.raises(BundleError, match="verifying checkout"):
        verify_bundle(wrong_sha)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("reader", {"name": "grounded-reader", "provider": "ollama", "selector": "latest", "model_revision": "latest", "model_content_sha256": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"}, "provider and selector"),
        ("decomposer", {"selector": "forged"}, "decomposer"),
        ("prompt", {"aggregate_sha256": "bad", "roles": {}, "serializer_sha256": "b" * 64}, "prompt"),
        ("decoding", {}, "decoding"),
        ("evidence_budget", {}, "evidence budget"),
        ("abstention", {}, "abstention"),
        ("split_role", "development", "split"),
    ),
)
def test_qa_custody_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object, message: str
) -> None:
    from eval.public.bundle import write_bundle

    benchmark = {"questions": [{"answers": ["x"], "question_id": "q"}]}
    custody = _qa_custody()
    candidate = custody.pop("_candidate")
    custody[field] = value
    metadata = {
        "adapter": "qa-fixture", "dataset_sha256": _canonical_digest(benchmark), "family": "qa",
        "independent_external_reproduction": False, "interval_method": "bootstrap", "interval_methods": {"exact_match": "wilson", "token_f1": "bootstrap"}, "license": "MIT",
        "pbpp_headline_eligible": False, "publishable": False, "qa_protocol_version": custody["protocol_version"],
        "revision": "c" * 40, "reader_custody": custody, "scoring_profile": "qa-em-f1-v1",
        "split_role": "held-out-test", "suite": "qa-fixture",
    }
    canonical = {key: nested for key, nested in metadata.items() if key not in {"reader_custody", "candidate_manifest"}}
    monkeypatch.setattr("eval.public.runner.load_registry", lambda: {"qa-fixture": canonical})
    monkeypatch.setattr("eval.public.runner.require_clean_candidate_checkout", lambda _sha: None)
    traces = [{"abstained": True, "answer": "", "authorized_retrieval_hops": [{"hop": 0, "rows": []}], "authorized_evidence_fingerprint": _evidence_fingerprint([]), "claims": [], "question_id": "q", "reader": _qa_trace_reader(include_grounded=False), "scoring_family": "qa"}]
    measured = score_profile("qa-em-f1-v1", [{"answers": ["x"], "question_id": "q"}], traces)
    out = tmp_path / field
    candidate_path = tmp_path / f"{field}-candidate.json"
    _rewrite_json(candidate_path, candidate)
    write_bundle(out, benchmark=benchmark, metadata=metadata, metrics=measured, traces=traces, candidate_manifest_path=candidate_path)
    with pytest.raises(BundleError, match=message):
        verify_bundle(out)


def _qa_custody() -> dict[str, object]:
    from eval.public.runner import load_qa_protocol, qa_protocol_digests
    from mnemosyne.providers.grounded_protocol import PROMPT_BUNDLES, role_digests

    protocol = load_qa_protocol()
    digests = qa_protocol_digests(protocol)
    candidate = {
        "candidate_version": protocol["version"], "created_at_utc": "2026-07-11T00:00:00Z",
        "git_sha": __import__("subprocess").run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip(), "model_content_sha256": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41",
        **digests, "evidence_budget": protocol["evidence_budget"],
        "abstention": protocol["abstention"], "transport_retries": 0,
    }
    custody = {
        "abstention": protocol["abstention"],
        "candidate_git_sha": candidate["git_sha"],
        "candidate_manifest_sha256": _canonical_digest(candidate),
        "decoding": protocol["decoding"],
        "decomposer": protocol["decomposer"],
        "evidence_budget": protocol["evidence_budget"],
        "prompt": {
            "aggregate_sha256": digests["prompt_sha256"],
            "roles": {
                role: {"template_sha256": role_digests(role)["prompt_sha256"]}
                for role in sorted(PROMPT_BUNDLES)
            },
            "serializer_sha256": digests["serializer_sha256"],
        },
        "protocol_version": protocol["version"],
        "reader": {"model_content_sha256": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41", "model_revision": "qwen3:8b", "name": "grounded-reader", "provider": "ollama", "selector": "qwen3:8b"},
        "split_role": "held-out-test",
        "transport_retries": 0,
    }
    custody["_candidate"] = candidate
    return custody


def _qa_trace_reader(*, include_grounded: bool = True) -> dict[str, object]:
    from mnemosyne.providers.extractive_decomposer import disclosure
    from mnemosyne.providers.grounded_protocol import (
        GENERATION_SPEC,
        MODEL_CONTENT_SHA256,
        MODEL_SELECTOR,
        role_digests,
    )

    value: dict[str, object] = {"query_decomposer": disclosure()}
    if include_grounded:
        value["grounded_reader"] = {
            "role": "grounded_reader",
            "model": MODEL_SELECTOR,
            "model_content_digest": MODEL_CONTENT_SHA256,
            **role_digests("grounded_reader"),
            "decoding_options": GENERATION_SPEC,
        }
    return value


def _evidence_fingerprint(cids: list[str]) -> str:
    return _canonical_digest(sorted(cids))


def _hop(index: int, cid: str, content: str) -> dict[str, object]:
    return {"hop": index, "rows": [{"capture": _capture(content), "cid": cid}]}


def _capture(content: str) -> dict[str, object]:
    return {"actor": "user", "content": content, "content_pointer": None, "modality": "text", "sensitivity": 0, "source_identity": "synthetic-fixture", "source_type": "benchmark", "tenant_id": "qa-test", "user_id": "benchmark-user"}


def _fabricate_outside(trace: dict[str, object]) -> None:
    from mnemosyne.ids import evidence_cid
    capture = _capture("outside")
    cid = evidence_cid(capture["content"], tenant_id=capture["tenant_id"], user_id=capture["user_id"], source_type=capture["source_type"], content_pointer=capture["content_pointer"], modality=capture["modality"], sensitivity=capture["sensitivity"])
    trace.update(authorized_retrieval_hops=[_hop(0, cid, "outside")], authorized_evidence_fingerprint=_evidence_fingerprint([cid]))
    trace["claims"][0].update(evidence_cids=[cid])


@pytest.mark.parametrize(
    ("hops", "budget", "message"),
    (
        (
            [{"hop": index, "rows": []} for index in range(4)],
            {"max_characters": 24000, "max_hops": 3, "max_records": 20},
            "hop budget",
        ),
        (
            [{"hop": 0, "rows": []}],
            {"max_characters": 24000, "max_hops": 3, "max_records": 20},
            "record budget",
        ),
        (
            [{"hop": 0, "rows": []}],
            {"max_characters": 24000, "max_hops": 3, "max_records": 20},
            "character budget",
        ),
        (
            [{"hop": 1, "rows": []}],
            {"max_characters": 24000, "max_hops": 3, "max_records": 20},
            "ordered and contiguous",
        ),
        (
            [{"hop": False, "rows": []}],
            {"max_characters": 24000, "max_hops": 3, "max_records": 20},
            "hop schema",
        ),
    ),
)
def test_qa_authorized_retrieval_enforces_frozen_evidence_budget(
    hops: list[dict[str, object]],
    budget: dict[str, int],
    message: str,
) -> None:
    from eval.public.bundle import _authorized_cids_from_hops
    from mnemosyne.ids import evidence_cid

    count = 21 if message == "record budget" else 1
    content = "x" * 24001 if message == "character budget" else "evidence"
    corpus = []
    rows = []
    for index in range(count):
        capture = _capture(f"{content}{index}")
        cid = evidence_cid(
            capture["content"],
            tenant_id=capture["tenant_id"],
            user_id=capture["user_id"],
            source_type=capture["source_type"],
            content_pointer=capture["content_pointer"],
            modality=capture["modality"],
            sensitivity=capture["sensitivity"],
        )
        corpus.append(
            {
                "capture": capture,
                "content": capture["content"],
                "doc_id": cid,
                "source_identity": capture["source_identity"],
            }
        )
        rows.append({"capture": capture, "cid": cid})
    if message in {"record budget", "character budget"}:
        hops[0]["rows"] = rows
    with pytest.raises(BundleError, match=message):
        _authorized_cids_from_hops(hops, {"corpus": corpus}, budget)


def _refresh_digest(bundle: Path, name: str) -> None:
    import hashlib

    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][name] = hashlib.sha256((bundle / name).read_bytes()).hexdigest()
    _rewrite_json(manifest_path, manifest)


def _rewrite_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _canonical_digest(value: object) -> str:
    import hashlib

    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()

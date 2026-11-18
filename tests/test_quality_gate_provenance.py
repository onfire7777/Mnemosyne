"""Source receipts use disposable repositories, never a paid or held-out run."""

import importlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Provenance Test")
    git(repo, "config", "user.email", "provenance@example.invalid")
    for name, content in {
        "src/package/engine.py": "VALUE = 1\n",
        "eval/run_quality_gate.py": "# runner\n",
        "eval/harness/metrics.py": "# metrics\n",
        "tools/check.py": "# tool\n",
        "config/runtime.toml": "enabled = true\n",
        "pyproject.toml": "[project]\nname = 'fixture'\n",
        "uv.lock": "version = 1\n",
    }.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture")
    return repo


def provenance_module():
    assert importlib.util.find_spec("eval.source_provenance") is not None, (
        "Quality gate needs a working-source provenance collector, not just HEAD"
    )
    return importlib.import_module("eval.source_provenance")


def test_clean_source_receipt_identifies_content_not_only_head(source_repo):
    receipt = provenance_module().capture_source_provenance(source_repo)
    assert receipt["git_commit"] == git(source_repo, "rev-parse", "HEAD")
    assert receipt["git_dirty"] is False
    assert len(receipt["source_fingerprint"]) == 64
    assert receipt["source_file_count"] == 7
    assert receipt["fingerprint_scope"]
    assert receipt["errors"] == []
    assert receipt == provenance_module().capture_source_provenance(source_repo)


@pytest.mark.parametrize("name", ["checkout with trailing space ", "checkout with newline\n"])
def test_clean_worktree_root_preserves_filename_whitespace(source_repo, name):
    renamed = source_repo.with_name(name)
    source_repo.rename(renamed)
    receipt = provenance_module().capture_source_provenance(renamed)
    assert receipt["git_dirty"] is False
    assert receipt["git_commit"] == git(renamed, "rev-parse", "HEAD")
    assert receipt["errors"] == []
    assert provenance_module().compare_source_provenance(receipt, receipt)["release_eligible"] is True


@pytest.mark.parametrize("state", ["modified", "staged", "untracked", "deleted", "renamed"])
def test_fingerprint_tracks_working_sources_even_when_head_is_unchanged(source_repo, state):
    capture = provenance_module().capture_source_provenance
    before = capture(source_repo)
    source = source_repo / "src/package/engine.py"
    if state in {"modified", "staged"}:
        source.write_text("VALUE = 2\n")
        if state == "staged":
            git(source_repo, "add", ".")
    elif state == "untracked":
        source.with_name("new_module.py").write_text("# untracked source\n")
    elif state == "deleted":
        source.unlink()
    else:
        source.rename(source.with_name("renamed.py"))
    after = capture(source_repo)
    assert after["git_commit"] == before["git_commit"]
    assert after["git_dirty"] is True
    assert after["source_fingerprint"] != before["source_fingerprint"]


@pytest.mark.parametrize("name", [
    "eval/reports/latest.json", "eval/reports/generated.py", "eval/learning/reports/run.json",
    "eval/datasets/quality_gate/quality_gate_dev.json", "eval/perf/golden/sample.json.gz",
    "src/package/__pycache__/engine.cpython-312.pyc", "eval/outputs/scores.json",
    "src/package.egg-info/PKG-INFO", "src/package.dist-info/METADATA",
])
def test_generated_outputs_and_dataset_payloads_do_not_change_source_fingerprint(source_repo, name):
    capture = provenance_module().capture_source_provenance
    before = capture(source_repo)
    path = source_repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not source\n")
    after = capture(source_repo)
    assert after["source_fingerprint"] == before["source_fingerprint"]
    assert after["source_file_count"] == before["source_file_count"]


@pytest.mark.parametrize("name", [
    "eval/harness/helper.py", "eval/datasets/v2/v2_judge.py", "tools/new_tool.py",
    "config/new.toml", "requirements-dev.txt", "tests/completion/security/poison_runner.py",
    "rust/mnemosyne-native/src/lib.rs", "scripts/run.sh", "configs/backend.yaml",
])
def test_untracked_evaluation_source_and_dependencies_are_fingerprinted(source_repo, name):
    capture = provenance_module().capture_source_provenance
    before = capture(source_repo)
    path = source_repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("new source\n")
    after = capture(source_repo)
    assert after["source_fingerprint"] != before["source_fingerprint"]
    assert after["git_dirty"] is True


@pytest.mark.parametrize("name", [
    "src/package/results/scorer.py", "src/package/output/scorer.py",
    "src/package/reports/scorer.py", "src/package/datasets/runtime.toml",
    "config/datasets/runtime.toml", "config/results/runtime.toml",
    "eval/harness/results/scorer.py", "tools/output/check.py",
])
@pytest.mark.parametrize("hidden_state", ["assume_unchanged", "ignored"])
def test_artifact_named_runtime_paths_cannot_hide_source(source_repo, name, hidden_state):
    capture = provenance_module().capture_source_provenance
    path = source_repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if hidden_state == "assume_unchanged":
        path.write_text("VALUE = 1\n")
        git(source_repo, "add", ".")
        git(source_repo, "commit", "-qm", "runtime fixture")
        git(source_repo, "update-index", "--assume-unchanged", name)
    else:
        (source_repo / ".gitignore").write_text(name + "\n")
        git(source_repo, "add", ".gitignore")
        git(source_repo, "commit", "-qm", "ignored runtime fixture")
    before = capture(source_repo)
    assert before["git_dirty"] is False
    path.write_text("VALUE = 2\n")
    assert git(source_repo, "status", "--porcelain") == ""
    after = capture(source_repo)
    assert after["source_fingerprint"] != before["source_fingerprint"]
    assert after["git_dirty"] is True
    assert not provenance_module().compare_source_provenance(after, after)["release_eligible"]


@pytest.fixture
def synthetic_gate(source_repo, monkeypatch):
    from eval import run_quality_gate as gate

    dataset_dir = source_repo / "eval/datasets/quality_gate"
    dataset_dir.mkdir(parents=True)
    for name in ("quality_gate_dev.json", "quality_gate_heldout.json", "poison_guard.json"):
        (dataset_dir / name).write_text("{}")
    (dataset_dir / "manifest.json").write_text('{"files": {}}')
    (dataset_dir.parent / "retrieval_curated.json").write_text("{}")
    git(source_repo, "add", ".")
    git(source_repo, "commit", "-qm", "synthetic fixture datasets")
    monkeypatch.setattr(gate, "_REPO", source_repo)
    monkeypatch.setattr(gate, "DATASET_DIR", dataset_dir)
    monkeypatch.setattr(gate, "MANIFEST_FILE", dataset_dir / "manifest.json")
    monkeypatch.setattr(gate, "configure_backend", lambda *a: None)
    monkeypatch.setattr(gate, "run_all_mandatory_classes", lambda *a: [])
    monkeypatch.setattr(gate, "_evaluate_g2_answer_quality", lambda *a: 0.0)
    monkeypatch.setattr(gate.poison_runner, "run_corpus", lambda *a, **kw: SimpleNamespace(
        attack_blocked=0, attack_total=0, overall_block_rate=0.0,
        false_positive_rate=0.0, results=[], benign_total=0, benign_false_positives=0,
    ))
    return gate


def test_dirty_developer_report_labels_actual_source_and_preserves_legacy_fields(
    source_repo, synthetic_gate, tmp_path, capsys,
):
    (source_repo / "src/package/engine.py").write_text("VALUE = 2\n")
    output = tmp_path / "diagnostic.json"
    markdown = tmp_path / "diagnostic.md"
    assert synthetic_gate.main([
        "--split", "dev", "--report", str(output), "--summary-md", str(markdown),
    ]) == 0
    report = json.loads(output.read_text())
    meta = report["meta"]
    assert report["schema_version"] == "1.0.0"
    assert meta["git_commit"] == git(source_repo, "rev-parse", "HEAD")
    assert meta["git_dirty"] is True
    assert meta["source_fingerprint"] == provenance_module().capture_source_provenance(
        source_repo,
    )["source_fingerprint"]
    receipt = meta["source_provenance"]
    assert receipt["status"] == "dirty"
    assert receipt["source_changed"] is False
    assert receipt["release_eligible"] is False
    assert receipt["start"]["source_fingerprint"] == receipt["end"]["source_fingerprint"]
    text = markdown.read_text()
    assert "Source Provenance" in text
    assert meta["source_fingerprint"] in text
    assert "dirty" in text and "not release evidence" in text
    console = capsys.readouterr().out
    assert "Source provenance: dirty" in console
    assert "not release evidence" in console
    assert meta["source_fingerprint"] in console
    # Existing historical reports remain renderable without provenance metadata.
    for key in ("source_provenance", "source_fingerprint", "git_dirty"):
        meta.pop(key)
    assert "unrecorded" in synthetic_gate._build_markdown_summary(report, {})


@pytest.mark.parametrize("state", ["modified", "staged", "untracked", "unknown"])
def test_clean_revision_required_before_manifest_or_evaluation(
    source_repo, synthetic_gate, monkeypatch, tmp_path, state,
):
    if state == "unknown":
        (source_repo / ".git").rename(tmp_path / "git-hidden")
    elif state == "untracked":
        (source_repo / "src/new.py").write_text("# new\n")
    else:
        (source_repo / "src/package/engine.py").write_text("VALUE = 2\n")
        if state == "staged":
            git(source_repo, "add", ".")
    monkeypatch.setattr(synthetic_gate, "_verify_dataset_manifest", lambda: pytest.fail(
        "Unclean source must fail before loading datasets or running evaluation",
    ))
    with pytest.raises(SystemExit, match="clean.*revision"):
        synthetic_gate.main(["--split", "dev", "--require-clean-revision"])


def test_clean_fixed_revision_is_verified_before_output_writes(source_repo, synthetic_gate):
    output = source_repo / "eval/reports/diagnostic.json"
    markdown = source_repo / "eval/reports/diagnostic.md"
    assert synthetic_gate.main([
        "--split", "dev", "--require-clean-revision", "--report", str(output),
        "--summary-md", str(markdown),
    ]) == 0
    report = json.loads(output.read_text())
    receipt = report["meta"]["source_provenance"]
    assert receipt["status"] == "clean"
    assert receipt["release_eligible"] is True
    assert receipt["source_changed"] is False
    assert receipt["require_clean_revision"] is True
    assert provenance_module().capture_source_provenance(source_repo)["source_fingerprint"] == (
        report["meta"]["source_fingerprint"]
    )


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("mutation", ["source", "head", "untracked"])
def test_mid_run_source_or_head_drift_prevents_report_publication(
    source_repo, synthetic_gate, monkeypatch, tmp_path, strict, mutation,
):
    def mutate(*args):
        if mutation == "source":
            (source_repo / "src/package/engine.py").write_text("VALUE = 2\n")
        elif mutation == "untracked":
            (source_repo / "eval/harness/new.py").write_text("# new\n")
        else:
            git(source_repo, "commit", "--allow-empty", "-qm", "HEAD changed")
        return 0.0

    monkeypatch.setattr(synthetic_gate, "_evaluate_g2_answer_quality", mutate)
    output = tmp_path / "report.json"
    summary = tmp_path / "summary.md"
    output.write_text("previous report must survive")
    args = ["--split", "dev", "--report", str(output), "--summary-md", str(summary)]
    if strict:
        args.append("--require-clean-revision")
    with pytest.raises(SystemExit, match="[Ss]ource.*changed"):
        synthetic_gate.main(args)
    assert output.read_text() == "previous report must survive"
    assert not summary.exists()


@pytest.mark.parametrize("flag", ["--report", "--summary-md"])
@pytest.mark.parametrize("kind", [
    "fresh_source", "existing_source", "symlink", "symlink_parent", "hardlink",
    "outside_source", "directory", "same_output",
])
@pytest.mark.parametrize("strict", [False, True])
def test_unsafe_outputs_fail_before_evaluation_without_any_writes(
    source_repo, synthetic_gate, tmp_path, monkeypatch, flag, kind, strict,
):
    source = source_repo / "src/package/engine.py"
    original = source.read_bytes()
    suffix = ".json" if flag == "--report" else ".md"
    safe = tmp_path / ("safe.md" if flag == "--report" else "safe.json")
    output = source_repo / "eval/reports" / ("unsafe" + suffix)
    output.parent.mkdir(parents=True, exist_ok=True)
    if kind == "fresh_source":
        output = source_repo / "eval" / ("fresh-report" + suffix)
    elif kind == "existing_source":
        output = source
    elif kind == "symlink":
        output.symlink_to(source)
    elif kind == "symlink_parent":
        alias = source_repo / "eval/reports/alias"
        alias.symlink_to(source.parent, target_is_directory=True)
        output = alias / "engine.py"
    elif kind == "hardlink":
        output.hardlink_to(source)
    elif kind == "outside_source":
        output = tmp_path / "unrelated.py"
        output.write_text("do not overwrite arbitrary source\n")
    elif kind == "directory":
        output.mkdir()
    else:
        output = safe.parent / "." / safe.name
    # Hide generated aliases so clean-mode rejection cannot be just Git status.
    (source_repo / ".gitignore").write_text("/eval/reports/\n")
    git(source_repo, "add", ".gitignore")
    git(source_repo, "commit", "-qm", "ignore output fixture")
    assert git(source_repo, "status", "--porcelain") == ""
    monkeypatch.setattr(synthetic_gate, "_verify_dataset_manifest", lambda: pytest.fail(
        "Both output destinations must be rejected before loading any datasets",
    ))
    other = "--summary-md" if flag == "--report" else "--report"
    args = ["--split", "dev", flag, str(output), other, str(safe)]
    if strict:
        args.append("--require-clean-revision")
    with pytest.raises(SystemExit, match="[Oo]utput"):
        synthetic_gate.main(args)
    assert source.read_bytes() == original
    assert not safe.exists()
    if kind == "fresh_source":
        assert not output.exists()
    if kind == "outside_source":
        assert output.read_text() == "do not overwrite arbitrary source\n"


def test_unknown_provenance_is_not_a_clean_unchanged_revision(source_repo, synthetic_gate, tmp_path):
    (source_repo / ".git").rename(tmp_path / "git-hidden")
    output = tmp_path / "report.json"
    assert synthetic_gate.main(["--split", "dev", "--report", str(output)]) == 0
    meta = json.loads(output.read_text())["meta"]
    assert meta["git_commit"] == "unknown"
    assert meta["git_dirty"] is None
    assert meta["source_provenance"]["status"] == "unknown"
    assert meta["source_provenance"]["source_changed"] is None
    assert meta["source_provenance"]["release_eligible"] is False
    assert synthetic_gate._get_git_commit() == "unknown"


@pytest.mark.parametrize("mutation", ["unverifiable", "non_source_dirty"])
def test_clean_revision_rechecked_after_evaluation(
    source_repo, synthetic_gate, monkeypatch, tmp_path, mutation,
):
    def mutate(*args):
        if mutation == "unverifiable":
            (source_repo / ".git").rename(tmp_path / "git-hidden")
        else:
            (source_repo / "README.md").write_text("new documentation\n")
        return 0.0

    monkeypatch.setattr(synthetic_gate, "_evaluate_g2_answer_quality", mutate)
    output = tmp_path / "report.json"
    with pytest.raises(SystemExit, match="clean.*revision"):
        synthetic_gate.main([
            "--split", "dev", "--require-clean-revision", "--report", str(output),
        ])
    assert not output.exists()


@pytest.mark.parametrize("hidden_state", ["ignored", "assume_unchanged", "skip_worktree"])
def test_git_status_cannot_hide_uncommitted_working_source(source_repo, hidden_state):
    capture = provenance_module().capture_source_provenance
    if hidden_state == "ignored":
        (source_repo / ".gitignore").write_text("src/ignored.py\n")
        git(source_repo, "add", ".gitignore")
        git(source_repo, "commit", "-qm", "ignore fixture")
        (source_repo / "src/ignored.py").write_text("# locally loaded source\n")
    else:
        flag = "--assume-unchanged" if hidden_state == "assume_unchanged" else "--skip-worktree"
        git(source_repo, "update-index", flag, "src/package/engine.py")
        (source_repo / "src/package/engine.py").write_text("VALUE = 2\n")
    assert git(source_repo, "status", "--porcelain") == ""
    receipt = capture(source_repo)
    assert receipt["git_dirty"] is True
    assert provenance_module().compare_source_provenance(receipt, receipt)["release_eligible"] is False


@pytest.mark.parametrize("normalization", ["autocrlf", "eol_attribute"])
@pytest.mark.parametrize("hidden_flag", ["--assume-unchanged", "--skip-worktree"])
def test_git_normalized_cleanliness_keeps_raw_fingerprint_and_detects_hidden_drift(
    source_repo, normalization, hidden_flag,
):
    capture = provenance_module().capture_source_provenance
    source = source_repo / "src/package/engine.py"
    lf_receipt = capture(source_repo)
    if normalization == "autocrlf":
        git(source_repo, "config", "core.autocrlf", "true")
    else:
        (source_repo / ".gitattributes").write_text("src/package/engine.py text eol=crlf\n")
        git(source_repo, "add", ".gitattributes")
        git(source_repo, "commit", "-qm", "line ending fixture")
    source.unlink()
    git(source_repo, "checkout-index", "-f", "--", "src/package/engine.py")
    assert source.read_bytes() == b"VALUE = 1\r\n"
    # Refresh checkout-index's size cache without changing the normalized blob.
    git(source_repo, "add", "--", "src/package/engine.py")
    assert git(source_repo, "status", "--porcelain") == ""
    materialized = capture(source_repo)
    assert materialized["git_dirty"] is False
    assert materialized["errors"] == []
    assert materialized["source_fingerprint"] != lf_receipt["source_fingerprint"]
    assert provenance_module().compare_source_provenance(materialized, materialized)["release_eligible"]
    git(source_repo, "update-index", hidden_flag, "src/package/engine.py")
    source.write_bytes(b"VALUE = 2\r\n")
    assert git(source_repo, "status", "--porcelain") == ""
    changed = capture(source_repo)
    assert changed["git_dirty"] is True
    assert changed["source_fingerprint"] != materialized["source_fingerprint"]
    assert not provenance_module().compare_source_provenance(changed, changed)["release_eligible"]


def test_custom_git_filters_fail_closed_without_running_commands(source_repo):
    (source_repo / ".gitattributes").write_text("src/package/engine.py filter=fixture\n")
    git(source_repo, "add", ".gitattributes")
    git(source_repo, "commit", "-qm", "filter fixture")
    # Deliberately unusable: the collector must reject, not execute, this driver.
    git(source_repo, "config", "filter.fixture.clean", "must-not-execute-provenance-filter")
    receipt = provenance_module().capture_source_provenance(source_repo)
    assert receipt["git_dirty"] is None
    assert receipt["source_fingerprint"] is not None
    assert any("filter" in error.lower() and "unsupported" in error.lower() for error in receipt["errors"])
    assert not provenance_module().compare_source_provenance(receipt, receipt)["release_eligible"]


@pytest.mark.parametrize("link_kind", ["file", "directory"])
def test_symlink_sources_cannot_claim_a_self_contained_revision(source_repo, tmp_path, link_kind):
    target = tmp_path / "external"
    if link_kind == "file":
        target.write_text("VALUE = 1\n")
    else:
        target.mkdir()
        (target / "module.py").write_text("VALUE = 1\n")
    (source_repo / "src/link").symlink_to(target, target_is_directory=link_kind == "directory")
    git(source_repo, "add", ".")
    git(source_repo, "commit", "-qm", "linked fixture")
    receipt = provenance_module().capture_source_provenance(source_repo)
    assert receipt["source_fingerprint"] is None
    assert receipt["errors"]
    assert provenance_module().compare_source_provenance(receipt, receipt)["release_eligible"] is False


def test_mutation_during_fingerprinting_is_unverifiable(source_repo, monkeypatch):
    original_read = Path.read_bytes
    source = source_repo / "src/package/engine.py"

    def read_then_mutate(path):
        data = original_read(path)
        if path == source:
            path.write_bytes(data + b"# concurrent change\n")
        return data

    monkeypatch.setattr(Path, "read_bytes", read_then_mutate)
    receipt = provenance_module().capture_source_provenance(source_repo)
    assert receipt["source_fingerprint"] is None
    assert receipt["errors"]


@pytest.mark.parametrize("failure", ["broken_symlink", "read_error"])
def test_source_io_failure_has_unknown_not_clean_git_state(source_repo, monkeypatch, failure):
    source = source_repo / "src/package/engine.py"
    if failure == "broken_symlink":
        source.unlink()
        source.symlink_to(source_repo / "missing.py")
        git(source_repo, "add", ".")
        git(source_repo, "commit", "-qm", "broken source fixture")
    else:
        original_read = Path.read_bytes

        def unreadable(path):
            if path == source:
                raise PermissionError("fixture source is unreadable")
            return original_read(path)

        monkeypatch.setattr(Path, "read_bytes", unreadable)
    assert git(source_repo, "status", "--porcelain") == ""
    receipt = provenance_module().capture_source_provenance(source_repo)
    assert receipt["git_dirty"] is None
    assert receipt["source_fingerprint"] is None
    assert receipt["errors"]
    assert provenance_module().compare_source_provenance(receipt, receipt)["status"] == "unknown"


@pytest.mark.parametrize("field,value", [
    ("git_commit", ""), ("git_dirty", "unknown"), ("git_dirty", 0),
    ("source_fingerprint", "unknown"), ("source_fingerprint", ""),
    ("source_file_count", 0), ("fingerprint_scope", "unrecognized"),
])
def test_unverifiable_report_contract_never_claims_clean_or_unchanged(source_repo, field, value):
    module = provenance_module()
    receipt = module.capture_source_provenance(source_repo)
    receipt[field] = value
    run = module.compare_source_provenance(receipt, receipt)
    assert run["release_eligible"] is False
    assert run["source_changed"] is None
    assert run["status"] == "unknown"


def test_missing_provenance_fields_fail_closed():
    run = provenance_module().compare_source_provenance({}, {})
    assert run["release_eligible"] is False
    assert run["source_changed"] is None

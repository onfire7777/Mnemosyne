"""Registry-driven public benchmark runner using only the CLI subprocess seam."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from eval.harness.cli_driver import MnemoCLI
from eval.public.adapters import (
    hipporag_multihop,
    longmemeval,
    longmemeval_qa,
    pm_bench_triggerbench,
    qa_smoke,
    smoke,
    working_memory_action_probe,
)
from eval.public.assets import AssetSpec, load_asset_set
from eval.public.action_cli import ActionCLI
from eval.public.bundle import _canonical, _scoring_labels, write_bundle
from eval.public.runtime_custody import grounded_runtime_environment
from mnemosyne.providers.grounded_protocol import (
    ANCHOR_NORMALIZER_SPEC,
    READER_SCHEMA_SPEC,
    GENERATION_SPEC,
    MODEL_CONTENT_SHA256,
    MODEL_SELECTOR,
    PROMPT_BUNDLES,
    SERIALIZER_SPEC,
    VERSION as GROUNDED_PROTOCOL_VERSION,
    canonical as grounded_canonical,
    role_digests,
)
from mnemosyne.providers.extractive_decomposer import (
    CONTENT_SHA256 as EXTRACTIVE_DECOMPOSER_CONTENT_SHA256,
    SPEC as EXTRACTIVE_DECOMPOSER_SPEC,
    SPEC_SHA256 as EXTRACTIVE_DECOMPOSER_SPEC_SHA256,
)

ROOT = Path(__file__).parent
_HEX = set("0123456789abcdef")
_ADAPTERS = {
    "hipporag-multihop": hipporag_multihop.run,
    "longmemeval": longmemeval.run,
    "longmemeval-qa": longmemeval_qa.run,
    "hipporag-reader-qa": hipporag_multihop.run_reader_qa,
    "qa-smoke": qa_smoke.run,
    "smoke": smoke.run,
    "pm-bench-triggerbench": pm_bench_triggerbench.run,
    "working-memory-action": working_memory_action_probe.run,
}
_NORMALIZERS = {
    "hipporag-multihop": hipporag_multihop.normalize,
    "longmemeval": longmemeval.normalize,
    "longmemeval-qa": longmemeval_qa.normalize,
    "hipporag-reader-qa": hipporag_multihop.normalize_reader_qa,
    "pm-bench-triggerbench": pm_bench_triggerbench.normalize,
    "working-memory-action": working_memory_action_probe.normalize,
}
_PROFILE_CONTRACTS = {
    "smoke-hit-at-k-v1": ("deterministic-retrieval", "wilson"),
    "longmemeval-retrieval-v1": ("deterministic-retrieval", "bootstrap"),
    "hipporag-retrieval-v1": ("deterministic-retrieval", "bootstrap"),
    "qa-em-f1-v1": ("qa", "bootstrap"),
    "pm-bench-action-v1": ("deterministic-action", "wilson"),
    "triggerbench-action-v1": ("deterministic-action", "wilson"),
    "working-memory-action-v1": ("deterministic-action", "bootstrap"),
}

_FROZEN_RETRIEVAL_BASELINES = {
    "hipporag-2wiki": {"recall_at_2": 0.17525, "recall_at_5": 0.23725},
    "hipporag-hotpot": {"recall_at_2": 0.319, "recall_at_5": 0.374},
    "hipporag-musique": {"recall_at_2": 0.08083333333333333, "recall_at_5": 0.10416666666666667},
    "longmemeval-retrieval": {"ndcg_at_5": 0.2967188496001503, "recall_at_5": 0.2806},
}
_FROZEN_PHASE11_CUSTODY = {
    "hipporag-2wiki": {"report_sha256": "7856c425c913d61db62caefc3af033c53d76ed406b27a4ebc190dd9f88951abe", "manifest_sha256": "dfdbd61f14ae62eda7cfe21058f2d7354c48f1b6e26cd134302855c352d97626"},
    "hipporag-hotpot": {"report_sha256": "d4b55046b114b8d7241a794392f375c152f11700a42fef454315b149636ade34", "manifest_sha256": "a7df98161a307b44bff44c9892b83728ff6269ebc233c2be377552f3345032fa"},
    "hipporag-musique": {"report_sha256": "85e063aa81fed06e2f1c8e36b8311207fc18912357f3fdbf73e1e6243e6eda76", "manifest_sha256": "6167926faad5fd95f3d8d340fead4c5d17495abd6faa5f88c361e3e91c508277"},
    "longmemeval-retrieval": {"report_sha256": "432cf16a755ca70bb5bc764a7e7cde30cde362675b395247e9c5f8b332689676", "manifest_sha256": "01e621fc245a951c5761ccc08be96e688d83b7a080d13499f5f9ef8426e48208"},
}


def load_registry() -> dict[str, dict[str, Any]]:
    registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    protocol = registry.pop("_qa_protocol", None)
    pending = registry.pop("_pending_qa_suites", None)
    validate_qa_protocol(protocol)
    _validate_pending_qa_suites(pending, registry)
    for name, suite in registry.items():
        revision, digest = suite.get("revision", ""), suite.get("dataset_sha256", "")
        if len(revision) != 40 or set(revision) - _HEX:
            raise ValueError(f"{name}: revision must be an exact 40-hex pin")
        if len(digest) != 64 or set(digest) - _HEX:
            raise ValueError(f"{name}: dataset_sha256 must be exact")
        contract = _PROFILE_CONTRACTS.get(suite.get("scoring_profile"))
        if contract != (suite.get("family"), suite.get("interval_method")):
            raise ValueError(
                f"{name}: invalid scoring profile, family, or interval method"
            )
    return registry


def load_pending_qa_suites() -> dict[str, dict[str, Any]]:
    raw = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    pending = raw.get("_pending_qa_suites")
    registry = {key: value for key, value in raw.items() if not key.startswith("_")}
    _validate_pending_qa_suites(pending, registry)
    return pending


def _validate_pending_qa_suites(value: object, registry: dict[str, Any]) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError("pending QA suite custody is missing")
    expected_keys = {"adapter", "requires_grounded_runtime", "source_suite", "status"}
    for name, row in value.items():
        if (
            not isinstance(name, str)
            or not isinstance(row, dict)
            or set(row) != expected_keys
            or row.get("adapter") not in {"longmemeval-qa", "hipporag-reader-qa"}
            or row.get("requires_grounded_runtime") is not True
            or row.get("source_suite") not in registry
            or row.get("status") != "pending-normalized-dataset-custody"
        ):
            raise ValueError("pending QA suite registry is invalid")


def load_qa_protocol() -> dict[str, Any]:
    raw = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    protocol = raw.get("_qa_protocol")
    validate_qa_protocol(protocol)
    return protocol


def validate_qa_protocol(protocol: Any) -> None:
    expected_keys = {"abstention", "anchor_normalizer", "reader_schema", "candidate_manifest_schema", "decoding", "decomposer", "evidence_budget", "held_out_policy", "interval_methods", "model", "phase11_custody", "prompt", "retrieval_baselines", "scoring_profile", "split_roles", "version"}
    if not isinstance(protocol, dict) or set(protocol) != expected_keys or protocol.get("version") != GROUNDED_PROTOCOL_VERSION:
        raise ValueError("frozen QA protocol is missing or has the wrong version")
    if protocol.get("retrieval_baselines") != _FROZEN_RETRIEVAL_BASELINES:
        raise ValueError("frozen retrieval baselines may not be weakened")
    if protocol.get("scoring_profile") != "qa-em-f1-v1":
        raise ValueError("frozen QA scoring profile mismatch")
    if protocol.get("held_out_policy") != {"development_use": False, "max_attempts": 1, "transport_retries": 0}:
        raise ValueError("held-out split may not be used as development data")
    expected = {
        "model": {"provider": "ollama", "selector": MODEL_SELECTOR, "content_sha256": MODEL_CONTENT_SHA256, "resolved_content_sha256_required": True},
        "decomposer": EXTRACTIVE_DECOMPOSER_SPEC,
        "prompt": {"roles": PROMPT_BUNDLES, "serializer": SERIALIZER_SPEC, "complete_role_custody_sha256_required": True},
        "decoding": GENERATION_SPEC,
        "evidence_budget": {"max_records": 20, "max_characters": 24000, "max_hops": 3},
        "abstention": {"answer": "", "claims": [], "abstained": True},
        "anchor_normalizer": ANCHOR_NORMALIZER_SPEC,
        "reader_schema": READER_SCHEMA_SPEC,
        "split_roles": {"synthetic": "development", "qa_hard_v2": "frozen-internal", "longmemeval-cleaned": "held-out-test", "hipporag-validation": "held-out-validation"},
        "interval_methods": {"exact_match": "wilson", "token_f1": "bootstrap"},
        "candidate_manifest_schema": {"external_post_commit": True, "no_overwrite": True, "required": ["candidate_version", "created_at_utc", "git_sha", "model_content_sha256", "decomposer_spec_sha256", "decomposer_implementation_sha256", "anchor_normalizer_sha256", "reader_schema_sha256", "prompt_sha256", "serializer_sha256", "decoding_sha256", "protocol_sha256", "evidence_budget", "abstention", "transport_retries"]},
    }
    if any(protocol.get(key) != value for key, value in expected.items()) or protocol.get("phase11_custody") != _FROZEN_PHASE11_CUSTODY:
        raise ValueError("frozen QA protocol custody is not the exact canonical contract")


def validate_candidate_manifest(manifest: Any, protocol: dict[str, Any] | None = None, *, expected_git_sha: str | None = None) -> None:
    protocol = protocol or load_qa_protocol()
    validate_qa_protocol(protocol)
    required = set(protocol["candidate_manifest_schema"]["required"])
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ValueError("candidate manifest schema mismatch")
    for key in ("git_sha", "model_content_sha256", "decomposer_spec_sha256", "decomposer_implementation_sha256", "anchor_normalizer_sha256", "reader_schema_sha256", "prompt_sha256", "serializer_sha256", "decoding_sha256", "protocol_sha256"):
        value = manifest.get(key)
        length = 40 if key == "git_sha" else 64
        if not isinstance(value, str) or len(value) != length or set(value) - _HEX:
            raise ValueError(f"candidate manifest {key} must be exact lowercase hex")
    if manifest.get("candidate_version") != protocol["version"] or manifest.get("transport_retries") != protocol["held_out_policy"]["transport_retries"]:
        raise ValueError("candidate manifest does not match preregistered protocol")
    if manifest.get("evidence_budget") != protocol["evidence_budget"] or manifest.get("abstention") != protocol["abstention"]:
        raise ValueError("candidate manifest budgets or abstention do not match preregistration")
    if manifest.get("model_content_sha256") != protocol["model"]["content_sha256"]:
        raise ValueError("candidate manifest model digest does not match preregistration")
    expected_digests = qa_protocol_digests(protocol)
    if any(manifest.get(key) != value for key, value in expected_digests.items()):
        raise ValueError("candidate manifest protocol digests do not match preregistration")
    try:
        created = datetime.fromisoformat(manifest["created_at_utc"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("candidate manifest UTC timestamp is invalid") from exc
    if not manifest["created_at_utc"].endswith("Z") or created.tzinfo != UTC:
        raise ValueError("candidate manifest UTC timestamp is invalid")
    if expected_git_sha is not None and manifest["git_sha"] != expected_git_sha:
        raise ValueError("candidate manifest git SHA does not match expected commit")


def qa_protocol_digests(protocol: dict[str, Any] | None = None) -> dict[str, str]:
    protocol = protocol or load_qa_protocol()
    validate_qa_protocol(protocol)
    return {
        "anchor_normalizer_sha256": hashlib.sha256(grounded_canonical(protocol["anchor_normalizer"])).hexdigest(),
        "decomposer_spec_sha256": EXTRACTIVE_DECOMPOSER_SPEC_SHA256,
        "decomposer_implementation_sha256": EXTRACTIVE_DECOMPOSER_CONTENT_SHA256,
        "reader_schema_sha256": hashlib.sha256(grounded_canonical(protocol["reader_schema"])).hexdigest(),
        "decoding_sha256": hashlib.sha256(grounded_canonical(protocol["decoding"])).hexdigest(),
        "prompt_sha256": hashlib.sha256(grounded_canonical(protocol["prompt"]["roles"])).hexdigest(),
        "protocol_sha256": hashlib.sha256(_canonical(protocol)).hexdigest(),
        "serializer_sha256": hashlib.sha256(grounded_canonical(protocol["prompt"]["serializer"])).hexdigest(),
    }


def build_candidate_manifest(
    *, model_content_sha256: str, git_sha: str, created_at_utc: str
) -> dict[str, Any]:
    """Build, but never write, the exact post-commit candidate manifest."""
    protocol = load_qa_protocol()
    manifest = {
        "abstention": protocol["abstention"],
        "candidate_version": protocol["version"],
        "created_at_utc": created_at_utc,
        "evidence_budget": protocol["evidence_budget"],
        "git_sha": git_sha,
        "model_content_sha256": model_content_sha256,
        **qa_protocol_digests(protocol),
        "transport_retries": protocol["held_out_policy"]["transport_retries"],
    }
    validate_candidate_manifest(manifest, protocol)
    return manifest


def write_candidate_manifest(path: Path | str, manifest: dict[str, Any], *, repo_root: Path | str | None = None) -> None:
    head = _current_clean_head(Path(repo_root) if repo_root else Path(__file__).resolve().parents[2])
    validate_candidate_manifest(manifest, expected_git_sha=head)
    destination = Path(path)
    _reject_symlink_components(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(destination, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical(manifest))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(destination, 0o600)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite candidate manifest: {destination}") from None
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def _current_clean_head(repo_root: Path) -> str:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True, check=True).stdout
    if len(head) != 40 or set(head) - _HEX or dirty:
        raise ValueError("candidate manifest requires the current clean exact HEAD")
    return head


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor) if path.is_absolute() else Path.cwd()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current /= part
        if current.is_symlink():
            raise ValueError("candidate manifest path components must not be symlinks")


def run_public_suite(
    suite_name: str,
    out_dir: Path | str,
    *,
    benchmark_override: dict[str, Any] | None = None,
    dataset_dir: Path | str | None = None,
    candidate_manifest_path: Path | str | None = None,
    runtime_manifest_path: Path | str | None = None,
    attempt_ledger_path: Path | str | None = None,
    ollama_url: str = "http://127.0.0.1:11434",
) -> dict[str, Any]:
    registry = load_registry()
    if suite_name not in registry:
        raise ValueError(f"unknown public suite: {suite_name}")
    suite = registry[suite_name]
    if suite["family"] == "qa" and candidate_manifest_path is None:
        raise ValueError(f"{suite_name}: --candidate-manifest is required")
    if suite["family"] != "qa" and candidate_manifest_path is not None:
        raise ValueError(f"{suite_name}: --candidate-manifest is QA-only")
    candidate: dict[str, Any] | None = None
    runtime_env: dict[str, str] = {}
    if suite["family"] == "qa":
        candidate_path = Path(candidate_manifest_path)  # type: ignore[arg-type]
        if candidate_path.is_symlink() or not candidate_path.is_file():
            raise ValueError("candidate manifest must be a real file")
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        validate_candidate_manifest(candidate, expected_git_sha=_git_sha())
        require_clean_candidate_checkout(candidate["git_sha"])
        if suite.get("requires_grounded_runtime") is True:
            if runtime_manifest_path is None or attempt_ledger_path is None:
                raise ValueError(
                    f"{suite_name}: --runtime-manifest and --attempt-ledger are required"
                )
            runtime_env = grounded_runtime_environment(
                Path(runtime_manifest_path),
                candidate,
                ollama_url,
                repo_root=Path(__file__).resolve().parents[2],
            )
            _claim_qa_attempt(
                Path(attempt_ledger_path),
                suite_name=suite_name,
                suite=suite,
                candidate_path=candidate_path,
                runtime_path=Path(runtime_manifest_path),
            )
    elif runtime_manifest_path is not None:
        raise ValueError("--runtime-manifest is QA-only")
    elif attempt_ledger_path is not None:
        raise ValueError("--attempt-ledger is protected-QA-only")
    if dataset_dir is not None and suite_name == "smoke":
        raise ValueError("smoke does not accept --dataset-dir")
    try:
        adapter = _ADAPTERS[suite["adapter"]]
    except KeyError as exc:
        raise ValueError(f"{suite_name}: unsupported adapter") from exc
    if benchmark_override is not None:
        adapter_input = benchmark_override
    elif "assets" in suite:
        if dataset_dir is None:
            raise ValueError(f"{suite_name}: --dataset-dir is required")
        specs = [AssetSpec(**item) for item in suite["assets"]]
        raw_input = {"assets": load_asset_set(dataset_dir, specs)}
        try:
            adapter_input = _NORMALIZERS[suite["adapter"]](raw_input)
        except KeyError as exc:
            raise ValueError(
                f"{suite_name}: asset adapter has no preflight normalizer"
            ) from exc
    else:
        fixture_bytes = (ROOT / suite["fixture"]).read_bytes()
        adapter_input = json.loads(fixture_bytes)
        if suite["adapter"] in _NORMALIZERS:
            adapter_input = _NORMALIZERS[suite["adapter"]](adapter_input)
    dataset_bytes = _canonical(adapter_input)
    if suite["family"] == "deterministic-action":
        dataset_bytes = dataset_bytes.rstrip(b"\n")
    if hashlib.sha256(dataset_bytes).hexdigest() != suite["dataset_sha256"]:
        raise ValueError(
            f"{suite_name}: normalized benchmark digest does not match registry"
        )
    allowed_env = {
        key: os.environ[key]
        for key in ("LANG", "LC_ALL", "PATH", "TMPDIR")
        if key in os.environ
    }
    allowed_env.update(runtime_env)
    with tempfile.TemporaryDirectory(prefix="mneme-public-") as temp:
        mnemo = MnemoCLI(store=str(Path(temp) / "store.json"), env=allowed_env)
        cli: Any = (
            ActionCLI(mnemo)
            if suite["adapter"] == "pm-bench-triggerbench"
            else mnemo
        )
        with patch.dict(os.environ, allowed_env, clear=True):
            result = adapter(adapter_input, cli)
    if len(result) == 2:
        traces, measured = result
        benchmark = adapter_input
    elif len(result) == 3:
        benchmark, traces, measured = result
    else:
        raise ValueError(
            "public adapter must return (traces, metrics) or (benchmark, traces, metrics)"
        )
    dataset_bytes = _canonical(benchmark)
    if suite["family"] == "deterministic-action":
        dataset_bytes = dataset_bytes.rstrip(b"\n")
    if hashlib.sha256(dataset_bytes).hexdigest() != suite["dataset_sha256"]:
        raise ValueError(
            f"{suite_name}: normalized benchmark digest does not match registry"
        )
    if suite["family"] == "deterministic-action":
        from eval.public.scoring import score_profile

        measured = score_profile(
            suite["scoring_profile"], _scoring_labels(benchmark), traces
        )
    interval_method = measured.get("interval", {}).get("method")
    if suite["scoring_profile"] == "qa-em-f1-v1":
        interval_method = measured.get("intervals", {}).get("token_f1", {}).get("method")
    if (
        measured.get("family") != suite["family"]
        or measured.get("profile", suite["scoring_profile"]) != suite["scoring_profile"]
        or interval_method != suite["interval_method"]
    ):
        raise ValueError("scoring profile, family, or interval metadata mismatch")
    metadata = {**suite, "suite": suite_name}
    if suite["family"] == "qa":
        assert candidate is not None
        protocol, digests = load_qa_protocol(), qa_protocol_digests()
        metadata["reader_custody"] = {
            "abstention": protocol["abstention"],
            "candidate_git_sha": candidate["git_sha"],
            "candidate_manifest_sha256": hashlib.sha256(_canonical(candidate)).hexdigest(),
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
            "reader": {"model_content_sha256": candidate["model_content_sha256"], "model_revision": protocol["model"]["selector"], "name": "grounded-reader", "provider": protocol["model"]["provider"], "selector": protocol["model"]["selector"]},
            "split_role": suite["split_role"],
            "transport_retries": protocol["held_out_policy"]["transport_retries"],
        }
    write_bundle(
        Path(out_dir),
        benchmark=benchmark,
        metadata=metadata,
        metrics=measured,
        traces=traces,
        candidate_manifest_path=candidate_manifest_path,
    )
    return {
        "bundle": str(Path(out_dir).resolve()),
        "independent_external_reproduction": False,
        "pbpp_headline_eligible": False,
        "publishable": False,
        "suite": suite_name,
        "system_seam": "public-cli-subprocess",
    }


def _claim_qa_attempt(
    path: Path,
    *,
    suite_name: str,
    suite: Mapping[str, Any],
    candidate_path: Path,
    runtime_path: Path,
) -> None:
    attempt_root = (Path.home() / ".local/state/mnemosyne/qa-attempts").resolve()
    if path.expanduser().resolve() != attempt_root:
        raise ValueError(f"QA attempt root must be the canonical path: {attempt_root}")
    candidate_digest = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    destination = attempt_root / f"{candidate_digest}-{suite_name}.json"
    repo = Path(__file__).resolve().parents[2]
    if destination == repo or repo in destination.parents or path.is_symlink():
        raise ValueError("QA attempt ledger must be external and non-symlinked")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "candidate_manifest_sha256": candidate_digest,
        "runtime_manifest_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
        "suite": suite_name,
        "suite_custody_sha256": hashlib.sha256(_canonical(suite)).hexdigest(),
    }
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(_canonical(payload))
        handle.flush()
        os.fsync(handle.fileno())


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, check=True).stdout.strip()


def require_clean_candidate_checkout(expected_sha: str) -> None:
    root = Path(__file__).resolve().parents[2]
    if _git_sha() != expected_sha:
        raise ValueError("candidate checkout HEAD does not match frozen candidate")
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True).stdout
    if dirty:
        raise ValueError("candidate checkout must be clean across the candidate surface")

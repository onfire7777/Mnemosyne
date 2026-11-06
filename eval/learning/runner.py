"""Run paired learning evaluations, failing closed on incomplete measurements."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import pickle
import subprocess
import tempfile
from typing import Any

from eval.harness.metrics import bootstrap_mean_interval
from .families import BENEFIT_FAMILIES
from .metrics import paired_interval

DATASET = Path(__file__).resolve().parents[1] / "datasets" / "learning"
MANIFEST = DATASET / "manifest.json"


def _source_hashes():
    repository = DATASET.parents[2]
    paths = [
        *Path(__file__).parent.glob("*.py"),
        *repository.joinpath("src", "mnemosyne").rglob("*.py"),
    ]
    return {
        str(path.relative_to(repository)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def _run_case(
    engine_factory, agent_factory, variant, protocol, episodes, checkpoint_dir, case
):
    from mnemosyne.experience.runtime import LearningRuntime

    family, seed, arm = case
    if (
        arm.startswith("without_")
        and load_manifest()["ablation_components"][arm] is None
    ):
        result = {
            "family": family,
            "seed": seed,
            "arm": arm,
            "rows": [],
            "metrics": {},
            "evidence": {},
            "verified": False,
            "supported": False,
            "verification_reason": "runtime does not expose this mechanism ablation",
        }
    else:
        with tempfile.TemporaryDirectory(prefix="mnem-learning-") as directory:
            engine = engine_factory(Path(directory))
            try:
                result = run_stream(
                    LearningRuntime(engine),
                    family,
                    seed,
                    arm,
                    variant=variant,
                    episodes=episodes,
                    protocol=protocol,
                    agent=agent_factory(seed) if agent_factory else None,
                )
            finally:
                if engine is not None and hasattr(engine, "close"):
                    engine.close()
    if checkpoint_dir is not None:
        path = checkpoint_dir / f"f{family:02d}-seed{seed}-{arm}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        temporary.replace(path)
    return result


def load_manifest() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    for split in ("dev", "sealed"):
        data = manifest["splits"][split]
        digest = hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if digest != manifest["split_hashes"][split]:
            raise ValueError(f"{split} split checksum mismatch")
    return manifest


def reserve_sealed_run(directory: Path, commit: str) -> Path:
    """An exclusive durable claim survives errors and concurrent attempts."""
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise ValueError("sealed reports require a real commit SHA")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{commit}.claim"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(commit + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def run_stream(
    runtime: Any,
    family: int,
    seed: int,
    arm: str,
    *,
    variant: str = "dev",
    episodes: int = 64,
    agent=None,
    protocol="specialized-v1",
) -> dict:
    """Run the specialized environment; never substitute generic gold-choice flags."""
    from .probes import run_specialized_probe, tenant_name

    if runtime is None:
        from mnemosyne.engine import LocalMemoryEngine
        from mnemosyne.experience.runtime import LearningRuntime

        runtime = LearningRuntime(LocalMemoryEngine())
    tenant = tenant_name(family, seed, arm, protocol)
    if arm.startswith("without_"):
        component = load_manifest()["ablation_components"][arm]
        if component is None:
            return {
                "family": family,
                "seed": seed,
                "arm": arm,
                "rows": [],
                "metrics": {},
                "evidence": {},
                "supported": False,
                "verified": False,
                "verification_reason": "runtime does not expose this mechanism ablation",
            }
        runtime.mode(tenant, component, "off")
    result = run_specialized_probe(
        runtime,
        family,
        seed,
        budget=episodes,
        agent=agent,
        arm=arm,
        protocol=protocol,
    )
    result["variant"] = variant
    result["track"] = "model" if agent is not None else "scripted"
    if agent is not None:
        result["agent"] = agent.configuration.metadata()
        result["model_calls"] = agent.calls
    return result


def build_report(
    engine_factory,
    *,
    split: str = "dev",
    family_ids=None,
    arms=None,
    episodes: int = 64,
    agent_factory=None,
    sealed_registry: Path | None = None,
    workers: int = 1,
    checkpoint_dir: Path | None = None,
    protocol: str = "specialized-v1",
) -> dict:
    manifest = load_manifest()
    selected = list(range(1, 27) if family_ids is None else family_ids)
    arm_names = list(manifest["arms"] if arms is None else arms)
    if (
        split not in manifest["splits"]
        or not selected
        or any(f not in range(1, 27) for f in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("unknown split or family")
    if (
        not arm_names
        or any(arm not in manifest["arms"] for arm in arm_names)
        or len(set(arm_names)) != len(arm_names)
    ):
        raise ValueError("unknown benchmark arm")
    if episodes < 4:
        raise ValueError("episodes must be at least four")
    if protocol not in {"specialized-v1", "common-pretraining-v2"}:
        raise ValueError("unknown learning evaluation protocol")
    if split == "sealed" and protocol != "specialized-v1":
        raise ValueError("common-pretraining-v2 is a development-only protocol")
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    if workers > 1:
        try:
            pickle.dumps((engine_factory, agent_factory))
        except (pickle.PicklingError, AttributeError, TypeError) as error:
            raise ValueError("parallel workers require picklable factories") from error
    repository = DATASET.parents[2]
    source_hashes = _source_hashes()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=repository, text=True
        )
    )
    reservation = None
    if split == "sealed":
        if dirty:
            raise ValueError("sealed reports require a clean committed checkout")
        reservation = reserve_sealed_run(
            sealed_registry or DATASET / "sealed_runs", commit
        )
    if checkpoint_dir is not None:
        checkpoint_dir = Path(checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    cases = [
        (family, seed, arm)
        for family in selected
        for seed in manifest["splits"][split]["seeds"]
        for arm in arm_names
    ]
    execute = partial(
        _run_case,
        engine_factory,
        agent_factory,
        manifest["splits"][split]["variant"],
        protocol,
        episodes,
        checkpoint_dir,
    )
    if workers == 1:
        results = [execute(case) for case in cases]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(execute, cases))
    comparisons = []
    missing_comparisons = []

    def compare(family, baseline, metric="aulc", direction="higher"):
        learned = sorted(
            [r for r in results if r["family"] == family and r["arm"] == "learning_on"],
            key=lambda r: r["seed"],
        )
        controls = sorted(
            [r for r in results if r["family"] == family and r["arm"] == baseline],
            key=lambda r: r["seed"],
        )

        def pair_is_aligned(a, b):
            if a["seed"] != b["seed"]:
                return False
            if protocol == "common-pretraining-v2" and [
                (r["query"], r["action"], r["expected"])
                for r in a.get("setup_rows", [])
            ] != [
                (r["query"], r["action"], r["expected"])
                for r in b.get("setup_rows", [])
            ]:
                return False
            if metric != "aulc":
                return (
                    a.get("supported")
                    and b.get("supported")
                    and a.get("probe") == b.get("probe") == protocol
                    and a.get("episode_budget") == b.get("episode_budget")
                    and metric in a.get("evidence", {})
                    and metric in b.get("evidence", {})
                )
            return (
                a.get("metrics")
                and b.get("metrics")
                and [
                    (
                        r["query"],
                        r["expected"],
                        r["phase"],
                        r.get("choices"),
                        r.get("task_class"),
                    )
                    for r in a["rows"]
                ]
                == [
                    (
                        r["query"],
                        r["expected"],
                        r["phase"],
                        r.get("choices"),
                        r.get("task_class"),
                    )
                    for r in b["rows"]
                ]
            )

        aligned = len(learned) == len(controls) == len(
            manifest["splits"][split]["seeds"]
        ) and all(pair_is_aligned(a, b) for a, b in zip(learned, controls))
        if not aligned:
            missing_comparisons.append(
                {
                    "family": family,
                    "baseline": baseline,
                    "reason": "missing metrics or unequal executed task sequences",
                }
            )
            return

        def value(row):
            number = (
                row["metrics"]["aulc"] if metric == "aulc" else row["evidence"][metric]
            )
            return number if direction == "higher" else -number

        interval = paired_interval(
            [value(r) for r in learned], [value(r) for r in controls]
        )
        entry = {
            "family": family,
            "baseline": baseline,
            "metric": metric,
            "direction": direction,
            "lift": interval,
        }
        if metric == "aulc":
            entry["aulc_lift"] = interval
        if baseline == "memory_frozen":
            slopes = bootstrap_mean_interval([r["metrics"]["slope"] for r in controls])
            entry.update(
                frozen_slope_ci=[slopes.low, slopes.high],
                frozen_flat=slopes.low <= 0 <= slopes.high,
            )
        comparisons.append(entry)

    for family in selected:
        if family in BENEFIT_FAMILIES:
            for baseline in ("no_memory", "memory_frozen"):
                if baseline in arm_names:
                    compare(family, baseline)
        for baseline, families in manifest["ablation_families"].items():
            if family in families and baseline in arm_names:
                endpoint = manifest["ablation_metrics"][baseline]
                compare(family, baseline, endpoint["metric"], endpoint["direction"])
    complete = set(selected) == set(range(1, 27)) and set(arm_names) == set(
        manifest["arms"]
    )
    passing = (
        complete
        and not missing_comparisons
        and all(
            r["supported"] and r["verified"]
            for r in results
            if r["arm"] == "learning_on"
        )
        and all(
            c["lift"]["low"] > 0 and c.get("frozen_flat", True) for c in comparisons
        )
    )
    return {
        "classification": "official"
        if split == "sealed" and complete
        else "diagnostic",
        "split": split,
        "configuration": {
            "commit": commit,
            "dirty": dirty,
            "episode_budget": episodes,
            "workers": workers,
            "protocol": protocol,
            "estimand": "retention, adaptation and transfer after matched learning-enabled setup"
            if protocol == "common-pretraining-v2"
            else "learning from initially empty memory",
            "seeds": manifest["splits"][split]["seeds"],
            "split_checksum": manifest["split_hashes"][split],
            "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
            "probe_sha256": hashlib.sha256(
                Path(__file__).with_name("probes.py").read_bytes()
            ).hexdigest(),
            "policy_sha256": hashlib.sha256(
                Path(__file__)
                .with_name("model_agent.py" if agent_factory else "simulator.py")
                .read_bytes()
            ).hexdigest(),
            "source_sha256_at_start": source_hashes,
            "source_changed_during_run": source_hashes != _source_hashes(),
            "sealed_reservation": str(reservation) if reservation else None,
        },
        "passed": passing,
        "complete": complete,
        "results": results,
        "comparisons": comparisons,
        "missing_comparisons": missing_comparisons,
        "track": "model" if agent_factory else "scripted",
        "limitations": [
            "A missing prerequisite fails closed; mechanics probes and measured task benefit are separate requirements.",
            "Model seed settings are requested from the provider, not proof of deterministic provider execution.",
        ],
    }


def _make_engine(path, *, backend, postgres_dsn=None, in_memory=False):
    if backend == "local":
        from mnemosyne.engine import LocalMemoryEngine

        return LocalMemoryEngine(store_path=None if in_memory else path / "store.json")
    if backend == "sqlite":
        from mnemosyne.sqlite_engine import SqliteEngine

        return SqliteEngine(path / "store")
    from mnemosyne.postgres_engine import PostgresEngine

    return PostgresEngine(postgres_dsn)


def _make_model_agent(seed, *, argv, model, temperature):
    from .model_agent import CommandModelAgent, ModelConfiguration

    return CommandModelAgent(ModelConfiguration(tuple(argv), model, temperature, seed))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "sealed"], default="dev")
    parser.add_argument(
        "--backend", choices=["local", "sqlite", "postgres"], default="local"
    )
    parser.add_argument("--postgres-dsn")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sealed-registry", type=Path, default=DATASET / "sealed_runs")
    parser.add_argument("--episodes", type=int, default=64)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--protocol",
        choices=["specialized-v1", "common-pretraining-v2"],
        default="specialized-v1",
    )
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument(
        "--in-memory", action="store_true", help="Use isolated ephemeral local engines"
    )
    parser.add_argument("--families", type=int, nargs="+", choices=range(1, 27))
    parser.add_argument("--arms", nargs="+", choices=load_manifest()["arms"])
    parser.add_argument(
        "--agent-command-json", help="Explicit JSON argv for the opt-in model track"
    )
    parser.add_argument("--model")
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()
    if args.backend == "postgres" and not args.postgres_dsn:
        parser.error("--postgres-dsn is required for postgres")
    if args.backend != "local" and args.in_memory:
        parser.error("--in-memory is only available with the local backend")
    if args.backend == "postgres" and args.workers != 1:
        parser.error("postgres streams share tenant names and must execute serially")
    if args.backend == "postgres" and args.protocol == "common-pretraining-v2":
        parser.error("common-pretraining-v2 requires an isolated engine store per arm")
    factory = partial(
        _make_engine,
        backend=args.backend,
        postgres_dsn=args.postgres_dsn,
        in_memory=args.in_memory,
    )

    agent_factory = None
    if args.agent_command_json:
        argv = json.loads(args.agent_command_json)
        if not args.model or not isinstance(argv, list):
            parser.error("--agent-command-json requires a JSON argv array and --model")

        agent_factory = partial(
            _make_model_agent, argv=argv, model=args.model, temperature=args.temperature
        )
    elif args.model:
        parser.error("--model requires --agent-command-json")
    report = build_report(
        factory,
        split=args.split,
        episodes=args.episodes,
        agent_factory=agent_factory,
        family_ids=args.families,
        arms=args.arms,
        sealed_registry=args.sealed_registry,
        workers=args.workers,
        checkpoint_dir=args.checkpoint_dir,
        protocol=args.protocol,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()

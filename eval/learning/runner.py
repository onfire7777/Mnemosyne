"""Run paired learning evaluations, failing closed on incomplete measurements."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from eval.harness.metrics import bootstrap_mean_interval
from .families import BENEFIT_FAMILIES
from .metrics import paired_interval

DATASET = Path(__file__).resolve().parents[1] / "datasets" / "learning"
MANIFEST = DATASET / "manifest.json"


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
) -> dict:
    """Run the specialized environment; never substitute generic gold-choice flags."""
    from .probes import run_specialized_probe

    if runtime is None:
        from mnemosyne.engine import LocalMemoryEngine
        from mnemosyne.experience.runtime import LearningRuntime

        runtime = LearningRuntime(LocalMemoryEngine())
    tenant = f"probe-f{family}-{seed}-{arm}"
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
        runtime, family, seed, budget=episodes, agent=agent, arm=arm
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
) -> dict:
    from mnemosyne.experience.runtime import LearningRuntime

    manifest = load_manifest()
    selected = list(family_ids or range(1, 27))
    arm_names = list(arms or manifest["arms"])
    if (
        split not in manifest["splits"]
        or not selected
        or any(f not in range(1, 27) for f in selected)
    ):
        raise ValueError("unknown split or family")
    if not arm_names or any(arm not in manifest["arms"] for arm in arm_names):
        raise ValueError("unknown benchmark arm")
    if episodes < 4:
        raise ValueError("episodes must be at least four")
    repository = DATASET.parents[2]
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
    results = []
    for family in selected:
        for seed in manifest["splits"][split]["seeds"]:
            for arm in arm_names:
                with tempfile.TemporaryDirectory(prefix="mnem-learning-") as directory:
                    engine = engine_factory(Path(directory))
                    runtime = LearningRuntime(engine)
                    if (
                        arm.startswith("without_")
                        and manifest["ablation_components"][arm] is None
                    ):
                        results.append(
                            {
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
                        )
                        if engine is not None and hasattr(engine, "close"):
                            engine.close()
                        continue
                    try:
                        result = run_stream(
                            runtime,
                            family,
                            seed,
                            arm,
                            variant=manifest["splits"][split]["variant"],
                            episodes=episodes,
                            agent=agent_factory(seed) if agent_factory else None,
                        )
                    finally:
                        if engine is not None and hasattr(engine, "close"):
                            engine.close()
                    results.append(result)
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
            if metric != "aulc":
                return (
                    a.get("supported")
                    and b.get("supported")
                    and a.get("probe") == b.get("probe") == "specialized-v1"
                    and a.get("episode_budget") == b.get("episode_budget")
                    and metric in a.get("evidence", {})
                    and metric in b.get("evidence", {})
                )
            return (
                a.get("metrics")
                and b.get("metrics")
                and [(r["query"], r["expected"], r["phase"]) for r in a["rows"]]
                == [(r["query"], r["expected"], r["phase"]) for r in b["rows"]]
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
    parser.add_argument("--families", type=int, nargs="+", choices=range(1, 27))
    parser.add_argument("--arms", nargs="+", choices=load_manifest()["arms"])
    parser.add_argument(
        "--agent-command-json", help="Explicit JSON argv for the opt-in model track"
    )
    parser.add_argument("--model")
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()
    if args.backend == "local":
        from mnemosyne.engine import LocalMemoryEngine

        def factory(path):
            return LocalMemoryEngine(store_path=path / "store.json")
    elif args.backend == "sqlite":
        from mnemosyne.sqlite_engine import SqliteEngine

        def factory(path):
            return SqliteEngine(path / "store")
    else:
        from mnemosyne.postgres_engine import PostgresEngine

        if not args.postgres_dsn:
            parser.error("--postgres-dsn is required for postgres")

        def factory(path):
            return PostgresEngine(args.postgres_dsn)

    agent_factory = None
    if args.agent_command_json:
        from .model_agent import CommandModelAgent, ModelConfiguration

        argv = json.loads(args.agent_command_json)
        if not args.model or not isinstance(argv, list):
            parser.error("--agent-command-json requires a JSON argv array and --model")

        def agent_factory(seed):
            return CommandModelAgent(
                ModelConfiguration(tuple(argv), args.model, args.temperature, seed)
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
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()

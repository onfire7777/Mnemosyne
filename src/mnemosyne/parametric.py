"""Isolated parametric-tier promotion boundaries."""

from __future__ import annotations

import json
import math
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

from mnemosyne.gate import GateResult, RegressionCase
from mnemosyne.ids import new_id
from mnemosyne.learning import Lesson, Procedure


@dataclass(slots=True)
class ParametricArtifact:
    tenant_id: str
    source_ids: list[str]
    adapter_kind: str
    status: str = "shadow"
    metrics: dict[str, float] = field(default_factory=dict)
    immutable_rails: list[str] = field(default_factory=list)
    rail_report: dict[str, Any] = field(default_factory=dict)
    artifact_uri: str | None = None
    rollback_ref: str | None = None
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParametricArtifact":
        return cls(
            tenant_id=str(data["tenant_id"]),
            source_ids=list(data.get("source_ids") or []),
            adapter_kind=str(data["adapter_kind"]),
            status=str(data.get("status", "shadow")),
            metrics=dict(data.get("metrics") or {}),
            immutable_rails=list(data.get("immutable_rails") or []),
            rail_report=dict(data.get("rail_report") or {}),
            artifact_uri=data.get("artifact_uri"),
            rollback_ref=data.get("rollback_ref"),
            id=str(data["id"]),
        )


@dataclass(frozen=True, slots=True)
class ParametricPromotionDecision:
    promoted: bool
    reason: str
    artifact: ParametricArtifact
    gate_report: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["artifact"] = self.artifact.to_dict()
        return data


def protected_suite_report(cases: Sequence[RegressionCase]) -> dict[str, Any]:
    tier_counts: dict[str, int] = {}
    case_ids: list[str] = []
    protected_case_ids: list[str] = []
    for case in cases:
        case_ids.append(case.id)
        tier_counts[case.tier] = tier_counts.get(case.tier, 0) + 1
        if case.protected:
            protected_case_ids.append(case.id)
    return {
        "case_count": len(case_ids),
        "protected_case_count": len(protected_case_ids),
        "case_ids": case_ids,
        "protected_case_ids": protected_case_ids,
        "tier_counts": dict(sorted(tier_counts.items())),
    }


class ParametricTrainer(Protocol):
    """Boundary for real LoRA/test-time-training adapter providers."""

    adapter_kind: str

    def propose(
        self,
        tenant_id: str,
        lessons: list[Lesson],
        procedures: list[Procedure],
        source_ids: list[str],
        immutable_rails: list[str],
    ) -> dict[str, Any]: ...

    def rollback(
        self,
        artifact: ParametricArtifact,
        reason: str,
        protected_cases: Sequence[RegressionCase] | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ParametricInvariantRails:
    max_supersession_rate: float = 0.05
    max_prune_fraction_per_pass: float = 0.02
    max_source_mutation_rate: float = 0.05
    min_gate_margin: float = 0.01
    reward_signal: str = "external_only"
    monotonic_trust: bool = True
    untrusted_to_system_prompt: str = "forbidden"

    def labels(self) -> tuple[str, ...]:
        return (
            "tenant_isolation_required",
            "branch_promotion_requires_gate",
            "protected_regression_suite_required",
            "mutation_rate_bounds_enforced",
            "monotonic_trust_required",
            "external_reward_signal_required",
            "untrusted_to_system_prompt_forbidden",
        )

    def proposal_report(self, artifact: ParametricArtifact, provider: dict[str, Any]) -> dict[str, Any]:
        metadata = _provider_metadata(provider)
        metrics = artifact.metrics
        self._check_rate(metrics, "supersession_rate", self.max_supersession_rate)
        self._check_rate(metrics, "mutation_rate", self.max_source_mutation_rate)
        self._check_rate(metrics, "source_mutation_rate", self.max_source_mutation_rate)
        self._check_rate(metrics, "prune_fraction", self.max_prune_fraction_per_pass)
        self._check_rate(metrics, "prune_fraction_per_pass", self.max_prune_fraction_per_pass)

        reward_signal = str(metadata.get("reward_signal", self.reward_signal))
        if reward_signal != self.reward_signal:
            raise ValueError("parametric invariant rail violated: reward_signal must be external_only")
        if metadata.get("monotonic_trust") is False:
            raise ValueError("parametric invariant rail violated: monotonic_trust cannot be disabled")
        trust_delta = metadata.get("trust_tier_delta")
        if isinstance(trust_delta, (int, float)) and not isinstance(trust_delta, bool) and trust_delta < 0:
            raise ValueError("parametric invariant rail violated: trust tier cannot be widened")
        if metadata.get("target_sink") == "system_prompt" or metadata.get("untrusted_to_system_prompt") is True:
            raise ValueError("parametric invariant rail violated: untrusted_to_system_prompt is forbidden")
        if metadata.get("eval_source_overlap") is True:
            raise ValueError("parametric invariant rail violated: source data overlaps evaluation suite")

        return {
            "source_count": len(artifact.source_ids),
            "reward_signal": self.reward_signal,
            "monotonic_trust": self.monotonic_trust,
            "untrusted_to_system_prompt": self.untrusted_to_system_prompt,
            "bounds": {
                "max_supersession_rate": self.max_supersession_rate,
                "max_prune_fraction_per_pass": self.max_prune_fraction_per_pass,
                "max_source_mutation_rate": self.max_source_mutation_rate,
            },
            "provider_metadata_checked": bool(metadata),
        }

    def gate_report(
        self,
        artifact: ParametricArtifact,
        gate_result: GateResult,
        protected_cases: list[RegressionCase],
    ) -> dict[str, Any]:
        if gate_result.candidate_id != artifact.id:
            raise ValueError("parametric invariant rail violated: gate candidate must match artifact")
        if gate_result.margin <= self.min_gate_margin:
            raise ValueError("parametric invariant rail violated: gate margin below noise rail")
        if gate_result.rollback_branch is not None and gate_result.promoted:
            raise ValueError("parametric invariant rail violated: promoted gate cannot carry rollback branch")
        protected_ids = {case.id for case in protected_cases if case.protected}
        passed_ids = set(gate_result.passed_cases)
        if protected_ids - passed_ids:
            raise ValueError("parametric invariant rail violated: all protected cases must pass")
        return {
            **artifact.rail_report,
            "gate": {
                "candidate_id": gate_result.candidate_id,
                "protected_case_count": len(protected_ids),
                "margin": gate_result.margin,
                "min_gate_margin": self.min_gate_margin,
            },
            "protected_suite": protected_suite_report(protected_cases),
        }

    @staticmethod
    def _check_rate(metrics: dict[str, float], key: str, limit: float) -> None:
        if key not in metrics:
            return
        if metrics[key] > limit:
            raise ValueError(f"parametric invariant rail violated: {key} exceeds {limit}")


class CommandParametricTrainer:
    """Command-backed LoRA/test-time-training provider boundary.

    The command is invoked without a shell. Each call appends the action name as
    the final argv item and sends JSON on stdin. `propose` should return a JSON
    object with optional `adapter_kind`, `metrics`, `artifact_ref`, and
    `metadata`. `rollback` may return `rollback_ref` and `metrics`.
    """

    def __init__(
        self,
        command: str | Sequence[str],
        *,
        adapter_kind: str = "command-parametric-adapter",
        timeout_seconds: float = 300.0,
    ):
        self.command = _command_argv(command)
        if not self.command:
            raise ValueError("parametric command must not be empty")
        if not adapter_kind.strip():
            raise ValueError("parametric adapter kind must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("parametric command timeout must be positive")
        self.adapter_kind = adapter_kind
        self.timeout_seconds = timeout_seconds

    def propose(
        self,
        tenant_id: str,
        lessons: list[Lesson],
        procedures: list[Procedure],
        source_ids: list[str],
        immutable_rails: list[str],
    ) -> dict[str, Any]:
        return self._call(
            "propose",
            {
                "tenant_id": tenant_id,
                "adapter_kind": self.adapter_kind,
                "source_ids": source_ids,
                "immutable_rails": immutable_rails,
                "lessons": [lesson.to_dict() for lesson in lessons if lesson.id in source_ids],
                "procedures": [procedure.to_dict() for procedure in procedures if procedure.id in source_ids],
            },
        )

    def rollback(
        self,
        artifact: ParametricArtifact,
        reason: str,
        protected_cases: Sequence[RegressionCase] | None = None,
    ) -> dict[str, Any]:
        protected_cases = protected_cases or []
        return self._call(
            "rollback",
            {
                "tenant_id": artifact.tenant_id,
                "artifact": artifact.to_dict(),
                "reason": reason,
                "protected_cases": [case.to_dict() for case in protected_cases],
                "protected_suite": protected_suite_report(protected_cases),
            },
        )

    def _call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [*self.command, action],
                input=json.dumps({"action": action, **payload}),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"parametric provider timed out during {action}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip()[:512]
            suffix = f": {detail}" if detail else ""
            raise ValueError(f"parametric provider failed during {action}{suffix}")
        try:
            parsed = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"parametric provider {action} response must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"parametric provider {action} response must be a JSON object")
        return parsed


class ParametricTier:
    """Shadow-only boundary for validated lessons/procedures.

    Mnemosyne is not a foundation-model trainer. This class models the
    blueprint's parametric tier as an isolated artifact gate: only already
    validated lessons/procedures can become adapter candidates, and protected
    regressions keep them in shadow.
    """

    def __init__(
        self,
        artifact_store: "ParametricArtifactStore | None" = None,
        trainer: ParametricTrainer | None = None,
        rails: ParametricInvariantRails | None = None,
    ):
        self.artifact_store = artifact_store
        self.trainer = trainer
        self.rails = rails or ParametricInvariantRails()
        self.required_rails = self.rails.labels()

    def propose_from_lessons(self, tenant_id: str, lessons: list[Lesson], procedures: list[Procedure]) -> ParametricArtifact:
        active_lessons = [lesson.id for lesson in lessons if lesson.tenant_id == tenant_id and lesson.status == "active"]
        active_procedures = [procedure.id for procedure in procedures if procedure.tenant_id == tenant_id and procedure.status in {"active", "validated"}]
        artifact = ParametricArtifact(
            tenant_id=tenant_id,
            source_ids=active_lessons + active_procedures,
            adapter_kind=self.trainer.adapter_kind if self.trainer else "local-shadow-adapter",
            immutable_rails=list(self.required_rails),
        )
        payload: dict[str, Any] = {"phase": "proposal"}
        provider: dict[str, Any] = {}
        if self.trainer and artifact.source_ids:
            provider = self.trainer.propose(
                tenant_id,
                lessons,
                procedures,
                artifact.source_ids,
                artifact.immutable_rails,
            )
            artifact.adapter_kind = _provider_adapter_kind(provider, default=self.trainer.adapter_kind)
            artifact.metrics.update(_provider_metrics(provider.get("metrics", {})))
            artifact.metrics["provider_invoked"] = 1.0
            payload["provider"] = _provider_payload(provider)
        artifact.rail_report = self.rails.proposal_report(artifact, provider)
        payload["rail_report"] = artifact.rail_report
        if self.artifact_store:
            self.artifact_store.write(artifact, payload)
        return artifact

    def evaluate(
        self,
        artifact: ParametricArtifact,
        gate_result: GateResult,
        protected_cases: list[RegressionCase],
    ) -> ParametricPromotionDecision:
        if not artifact.source_ids:
            artifact.status = "rejected"
            return ParametricPromotionDecision(False, "no validated source lessons or procedures", artifact)
        if not protected_cases:
            artifact.status = "shadow"
            return ParametricPromotionDecision(False, "protected regression suite required", artifact)
        if not all(rail in artifact.immutable_rails for rail in self.required_rails):
            artifact.status = "rejected"
            return ParametricPromotionDecision(False, "immutable rails missing", artifact)
        try:
            artifact.rail_report = self.rails.gate_report(artifact, gate_result, protected_cases)
        except ValueError as exc:
            artifact.status = "rejected"
            if self.artifact_store:
                self.artifact_store.write(
                    artifact,
                    {"phase": "rejected", "reason": str(exc), "gate": gate_result.to_dict(), "rail_report": artifact.rail_report},
                )
            return ParametricPromotionDecision(False, str(exc), artifact, gate_result.to_dict())
        if not gate_result.promoted or gate_result.protected_regressions:
            artifact.status = "shadow"
            if self.artifact_store:
                self.artifact_store.write(
                    artifact,
                    {"phase": "shadow", "gate": gate_result.to_dict(), "rail_report": artifact.rail_report},
                )
            return ParametricPromotionDecision(False, "promotion gate did not clear protected cases", artifact, gate_result.to_dict())
        artifact.status = "promoted"
        artifact.metrics["protected_cases"] = float(len(protected_cases))
        if self.artifact_store:
            self.artifact_store.write(
                artifact,
                {"phase": "promoted", "gate": gate_result.to_dict(), "rail_report": artifact.rail_report},
            )
        return ParametricPromotionDecision(True, "parametric artifact promoted in isolated tier", artifact, gate_result.to_dict())

    def rollback(
        self,
        artifact: ParametricArtifact,
        reason: str,
        protected_cases: Sequence[RegressionCase] | None = None,
    ) -> ParametricArtifact:
        protected_cases = protected_cases or []
        artifact.status = "rolled_back"
        suite = protected_suite_report(protected_cases)
        payload: dict[str, Any] = {"phase": "rolled_back", "reason": reason, "protected_suite": suite}
        provider: dict[str, Any] = {}
        if self.trainer:
            provider = self.trainer.rollback(artifact, reason, protected_cases=protected_cases)
            payload["provider"] = _provider_payload(provider)
            artifact.metrics.update(_provider_metrics(provider.get("metrics", {})))
        artifact.rollback_ref = str(provider.get("rollback_ref") or provider.get("rollbackRef") or f"rollback-{new_id()}")
        artifact.metrics["rolled_back"] = 1.0
        artifact.metrics["rollback_protected_cases"] = float(suite["protected_case_count"])
        artifact.rail_report = {
            **artifact.rail_report,
            "rollback": {
                "reason": reason,
                "rollback_ref": artifact.rollback_ref,
                "protected_suite": suite,
            },
        }
        if self.artifact_store:
            self.artifact_store.write(artifact, payload)
        return artifact


class ParametricArtifactStore:
    uri_prefix = "local-parametric://"

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def write(self, artifact: ParametricArtifact, payload: dict[str, Any] | None = None) -> str:
        path = self._path_for(artifact.tenant_id, artifact.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        artifact.artifact_uri = f"{self.uri_prefix}{artifact.tenant_id}/{artifact.id}.json"
        body = {
            "artifact": artifact.to_dict(),
            "payload": payload or {},
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        return artifact.artifact_uri

    def read(self, artifact_uri: str) -> dict[str, Any]:
        tenant_id, artifact_id = self._parse_uri(artifact_uri)
        return json.loads(self._path_for(tenant_id, artifact_id).read_text(encoding="utf-8"))

    def load_artifact(self, artifact_uri: str) -> ParametricArtifact:
        return ParametricArtifact.from_dict(self.read(artifact_uri)["artifact"])

    def _path_for(self, tenant_id: str, artifact_id: str) -> Path:
        self._validate_segment(tenant_id, "tenant")
        self._validate_segment(artifact_id, "artifact")
        path = (self.root / tenant_id / f"{artifact_id}.json").resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("parametric artifact path escaped store root") from exc
        if path == self.root:
            raise ValueError("parametric artifact path escaped store root")
        return path

    def _parse_uri(self, artifact_uri: str) -> tuple[str, str]:
        if not artifact_uri.startswith(self.uri_prefix):
            raise ValueError("unsupported parametric artifact uri")
        rest = artifact_uri.removeprefix(self.uri_prefix)
        tenant_id, _, name = rest.partition("/")
        if not tenant_id or not name.endswith(".json"):
            raise ValueError("invalid parametric artifact uri")
        return tenant_id, name.removesuffix(".json")

    @staticmethod
    def _validate_segment(value: str, label: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value or ".." in value:
            raise ValueError(f"invalid parametric {label} id")


def _provider_adapter_kind(provider: dict[str, Any], *, default: str) -> str:
    adapter_kind = str(provider.get("adapter_kind") or provider.get("adapterKind") or default).strip()
    if not adapter_kind:
        raise ValueError("parametric provider adapter_kind must not be empty")
    return adapter_kind


def _provider_metrics(raw: Any) -> dict[str, float]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("parametric provider metrics must be an object")
    metrics: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("parametric provider metric values must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("parametric provider metric values must be finite")
        metrics[str(key)] = number
    return metrics


def _provider_payload(provider: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "adapter_kind",
        "adapterKind",
        "artifact_ref",
        "artifactRef",
        "rollback_ref",
        "rollbackRef",
        "metrics",
        "metadata",
    }
    return {str(key): value for key, value in provider.items() if key in allowed}


def _provider_metadata(provider: dict[str, Any]) -> dict[str, Any]:
    raw = provider.get("metadata", {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("parametric provider metadata must be an object")
    return {str(key): value for key, value in raw.items()}


def _command_argv(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    return [str(item) for item in command]

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

    def rollback(self, artifact: ParametricArtifact, reason: str) -> dict[str, Any]: ...


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

    def rollback(self, artifact: ParametricArtifact, reason: str) -> dict[str, Any]:
        return self._call(
            "rollback",
            {
                "tenant_id": artifact.tenant_id,
                "artifact": artifact.to_dict(),
                "reason": reason,
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

    required_rails = (
        "tenant_isolation_required",
        "branch_promotion_requires_gate",
        "protected_regression_suite_required",
    )

    def __init__(
        self,
        artifact_store: "ParametricArtifactStore | None" = None,
        trainer: ParametricTrainer | None = None,
    ):
        self.artifact_store = artifact_store
        self.trainer = trainer

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
        if not gate_result.promoted or gate_result.protected_regressions:
            artifact.status = "shadow"
            if self.artifact_store:
                self.artifact_store.write(artifact, {"phase": "shadow", "gate": gate_result.to_dict()})
            return ParametricPromotionDecision(False, "promotion gate did not clear protected cases", artifact, gate_result.to_dict())
        artifact.status = "promoted"
        artifact.metrics["protected_cases"] = float(len(protected_cases))
        if self.artifact_store:
            self.artifact_store.write(artifact, {"phase": "promoted", "gate": gate_result.to_dict()})
        return ParametricPromotionDecision(True, "parametric artifact promoted in isolated tier", artifact, gate_result.to_dict())

    def rollback(self, artifact: ParametricArtifact, reason: str) -> ParametricArtifact:
        artifact.status = "rolled_back"
        payload: dict[str, Any] = {"phase": "rolled_back", "reason": reason}
        provider: dict[str, Any] = {}
        if self.trainer:
            provider = self.trainer.rollback(artifact, reason)
            payload["provider"] = _provider_payload(provider)
            artifact.metrics.update(_provider_metrics(provider.get("metrics", {})))
        artifact.rollback_ref = str(provider.get("rollback_ref") or provider.get("rollbackRef") or f"rollback-{new_id()}")
        artifact.metrics["rolled_back"] = 1.0
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


def _command_argv(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    return [str(item) for item in command]

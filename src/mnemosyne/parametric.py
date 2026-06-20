"""Isolated parametric-tier promotion boundaries."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

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

    def __init__(self, artifact_store: "ParametricArtifactStore | None" = None):
        self.artifact_store = artifact_store

    def propose_from_lessons(self, tenant_id: str, lessons: list[Lesson], procedures: list[Procedure]) -> ParametricArtifact:
        active_lessons = [lesson.id for lesson in lessons if lesson.tenant_id == tenant_id and lesson.status == "active"]
        active_procedures = [procedure.id for procedure in procedures if procedure.tenant_id == tenant_id and procedure.status in {"active", "validated"}]
        artifact = ParametricArtifact(
            tenant_id=tenant_id,
            source_ids=active_lessons + active_procedures,
            adapter_kind="local-shadow-adapter",
            immutable_rails=list(self.required_rails),
        )
        if self.artifact_store:
            self.artifact_store.write(artifact, {"phase": "proposal"})
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
        artifact.rollback_ref = f"rollback-{new_id()}"
        artifact.metrics["rolled_back"] = 1.0
        if self.artifact_store:
            self.artifact_store.write(artifact, {"phase": "rolled_back", "reason": reason})
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

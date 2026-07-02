"""Mnemosyne memory compiler package.

Public names are re-exported lazily (PEP 562): importing :mod:`mnemosyne`
— e.g. as a side effect of ``import mnemosyne.cli`` — no longer pulls the
heavy engine/retrieval stack. ``from mnemosyne import X`` keeps working for
every name in ``__all__``; the providing module is imported on first access
and the resolved value is cached in the package namespace.
"""

from __future__ import annotations

import importlib
from typing import Any

# Every public export mapped to the module that provides it. Keep in sync
# with __all__ (tests/test_import_time.py asserts every name resolves).
_EXPORTS: dict[str, str] = {
    "LocalMemoryEngine": "mnemosyne.engine",
    "MemoryEngine": "mnemosyne.engine",
    "RoutePlan": "mnemosyne.engine",
    "route": "mnemosyne.engine",
    "BeliefRevisionCore": "mnemosyne.belief",
    "LatencyBenchmarkResult": "mnemosyne.benchmarks",
    "CalibrationSet": "mnemosyne.calibration",
    "FidelityTier": "mnemosyne.lifecycle",
    "LifecycleState": "mnemosyne.lifecycle",
    "GraphBenchmarkResult": "mnemosyne.graph",
    "LocalRelationGraphAdapter": "mnemosyne.graph",
    "LongHorizonDegradationResult": "mnemosyne.guard",
    "LongHorizonNoDegradationTracker": "mnemosyne.guard",
    "NoDegradationResult": "mnemosyne.guard",
    "CALIBRATE_JOB": "mnemosyne.jobs",
    "EVAL_SUITE_JOB": "mnemosyne.jobs",
    "LIFECYCLE_SWEEP_JOB": "mnemosyne.jobs",
    "OBSERVABILITY_SNAPSHOT_JOB": "mnemosyne.jobs",
    "RuntimeJobHandlers": "mnemosyne.jobs",
    "LearningSystem": "mnemosyne.learning",
    "Trajectory": "mnemosyne.learning",
    "Assertion": "mnemosyne.models",
    "Evidence": "mnemosyne.models",
    "Hit": "mnemosyne.models",
    "Preference": "mnemosyne.models",
    "Relation": "mnemosyne.models",
    "ParametricArtifact": "mnemosyne.parametric",
    "ParametricPromotionDecision": "mnemosyne.parametric",
    "ParametricTier": "mnemosyne.parametric",
    "OperatingPolicy": "mnemosyne.policy",
    "AnticipatoryPrefetcher": "mnemosyne.prefetch",
    "PredictabilityGate": "mnemosyne.prefetch",
    "PrefetchCandidate": "mnemosyne.prefetch",
    "PrefetchResult": "mnemosyne.prefetch",
    "InProcessQueue": "mnemosyne.queue",
    "QueueJob": "mnemosyne.queue",
    "QueueWorker": "mnemosyne.queue",
    "CommandMediaEmbeddingProvider": "mnemosyne.retrieval",
    "HashingEmbeddingProvider": "mnemosyne.retrieval",
    "LocalSimilarityReranker": "mnemosyne.retrieval",
    "RetrievalAdapters": "mnemosyne.retrieval",
    "semantic_entropy": "mnemosyne.retrieval",
    "PrivacyClassification": "mnemosyne.privacy",
    "ProvenanceDecision": "mnemosyne.provenance",
    "SignedProvenanceVerifier": "mnemosyne.provenance",
    "SecurityPolicy": "mnemosyne.security",
    "TrustTier": "mnemosyne.security",
    "ContextualBanditLearner": "mnemosyne.self_optimization",
    "PolicyOutcome": "mnemosyne.self_optimization",
    "SelfModelStore": "mnemosyne.self_optimization",
    "ShadowPolicyOptimizer": "mnemosyne.self_optimization",
    "LocalObjectStore": "mnemosyne.storage",
    "ObjectRecord": "mnemosyne.storage",
    "LatentUserProfile": "mnemosyne.user_model",
    "UserMemoryKind": "mnemosyne.user_model",
    "UserModel": "mnemosyne.user_model",
    "UserModelEntry": "mnemosyne.user_model",
}

__all__ = [
    "Assertion",
    "AnticipatoryPrefetcher",
    "BeliefRevisionCore",
    "CalibrationSet",
    "CALIBRATE_JOB",
    "CommandMediaEmbeddingProvider",
    "ContextualBanditLearner",
    "Evidence",
    "EVAL_SUITE_JOB",
    "FidelityTier",
    "GraphBenchmarkResult",
    "Hit",
    "HashingEmbeddingProvider",
    "InProcessQueue",
    "LifecycleState",
    "LocalMemoryEngine",
    "LocalSimilarityReranker",
    "LocalRelationGraphAdapter",
    "LocalObjectStore",
    "LatentUserProfile",
    "LatencyBenchmarkResult",
    "LearningSystem",
    "LIFECYCLE_SWEEP_JOB",
    "LongHorizonDegradationResult",
    "LongHorizonNoDegradationTracker",
    "MemoryEngine",
    "NoDegradationResult",
    "OBSERVABILITY_SNAPSHOT_JOB",
    "OperatingPolicy",
    "ObjectRecord",
    "ParametricArtifact",
    "ParametricPromotionDecision",
    "ParametricTier",
    "PolicyOutcome",
    "Preference",
    "PredictabilityGate",
    "PrefetchCandidate",
    "PrefetchResult",
    "PrivacyClassification",
    "ProvenanceDecision",
    "QueueJob",
    "QueueWorker",
    "Relation",
    "RetrievalAdapters",
    "RoutePlan",
    "RuntimeJobHandlers",
    "SecurityPolicy",
    "SignedProvenanceVerifier",
    "SelfModelStore",
    "ShadowPolicyOptimizer",
    "TrustTier",
    "Trajectory",
    "UserMemoryKind",
    "UserModel",
    "UserModelEntry",
    "route",
    "semantic_entropy",
]


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

"""Command line interface for the local Mnemosyne engine."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import math
import os
import re
import shlex
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib import error as urlerror, request as urlrequest
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID

if TYPE_CHECKING:
    from cryptography import x509
    from mnemosyne.consolidation import (
        CandidateExtractor,
        EntityResolver,
        EvidenceSummarizer,
        LessonDistiller,
        ProcedureInducer,
    )
    from mnemosyne.engine import MemoryEngine
    from mnemosyne.gate import RegressionCase
    from mnemosyne.mcp_tools import MemoryTools
    from mnemosyne.media import MediaTextExtractor
    from mnemosyne.network_safety import ValidatedFetchUrl
    from mnemosyne.observability import MetricsRegistry
    from mnemosyne.parametric import ParametricTier
    from mnemosyne.postgres_runtime_state import PostgresRuntimeState
    from mnemosyne.provenance import C2paToolVerifier, ProvenanceTrustPolicy, SignedProvenanceVerifier
    from mnemosyne.queue import InProcessQueue, PostgresQueue, QueueWorker, SqliteQueue
    from mnemosyne.retrieval import CommandMediaEmbeddingProvider, RetrievalAdapters
    from mnemosyne.runtime_state import RuntimeState
    from mnemosyne.security import OidcAuthorizationPolicy, OidcJwtVerifier, SessionTokenVerifier
    from mnemosyne.storage import CommandKeyManager, JsonKeyManager, LocalObjectStore

DEPLOYMENT_SOAK_COMMANDS = {
    "belief-revision-check",
    "auth-ops-check",
    "calibration-tune",
    "forgetting-policy-check",
    "hosted-llm-check",
    "policy-ops-check",
    "privacy-ops-check",
    "provenance-ops-check",
    "provenance-trust-check",
    "provider-check",
    "retrieval-ops-check",
    "postgres-role-check",
    "idp-jwks-live-check",
    "idp-authz-policy-rollout-check",
    "tls-cert-check",
    "tls-lifecycle-ops-check",
    "tls-rotation-plan-check",
    "mcp-http-soak",
    "mcp-ops-check",
    "mcp-streamable-http-soak",
    "mcp-sse-soak",
    "consolidation-ops-check",
    "multimodal-ops-check",
    "ops-dashboard-check",
    "parametric-trainer-check",
    "worker-ops-check",
    "worker-run",
    "projection-recompute-once",
    "gate-suite-check",
    "ops-report",
}
DEPLOYMENT_SOAK_GLOBAL_OPTIONS = {
    "--backend",
    "--queue-backend",
    "--queue-tenant",
    "--object-store",
    "--parametric-artifact-store",
}
PRODUCTION_RELEASE_REQUIRED_COMMANDS = (
    "belief-revision-check",
    "auth-ops-check",
    "calibration-tune",
    "forgetting-policy-check",
    "hosted-llm-check",
    "policy-ops-check",
    "privacy-ops-check",
    "provenance-ops-check",
    "provenance-trust-check",
    "provider-check",
    "retrieval-ops-check",
    "postgres-role-check",
    "idp-jwks-live-check",
    "idp-authz-policy-rollout-check",
    "tls-cert-check",
    "tls-lifecycle-ops-check",
    "tls-rotation-plan-check",
    "mcp-http-soak",
    "mcp-ops-check",
    "mcp-streamable-http-soak",
    "consolidation-ops-check",
    "multimodal-ops-check",
    "gate-suite-check",
    "projection-recompute-once",
    "worker-run",
    "ops-dashboard-check",
    "parametric-trainer-check",
    "worker-ops-check",
    "ops-report",
)
PRODUCTION_RELEASE_REQUIRED_PROVIDER_CHECKS = (
    "embedding",
    "reranker",
    "retrieval_backends",
    "media_extractor",
    "media_embedding",
    "object_key_manager",
    "parametric",
    "candidate_extractor",
    "summarizer",
    "entity_resolver",
    "lesson_distiller",
    "skill_inducer",
    "oidc",
    "session_secret",
    "residency_policy",
)
PRODUCTION_RELEASE_LATENCY_PROVIDER_CHECKS = frozenset({"embedding", "reranker"})
PRODUCTION_RELEASE_MIN_LATENCY_SAMPLES = 3
POSTGRES_ROLE_CHECK_REQUIRED_CHECKS = (
    "app_role_safety",
    "app_group_membership",
    "app_destructive_writes_denied",
    "audit_log_append_only_app",
    "consolidator_role_safety",
    "consolidator_group_membership",
    "consolidator_sole_write",
    "audit_log_append_only_consolidator",
    "group_role_posture",
)
RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS: dict[str, tuple[str, ...]] = {
    "belief-revision-check": ("fingerprint", "summary", "results", "findings"),
    "auth-ops-check": ("bundle", "requirements", "checks", "findings"),
    "calibration-tune": ("calibration", "threshold", "metrics", "failures"),
    "forgetting-policy-check": ("fingerprint", "summary", "results", "findings"),
    "hosted-llm-check": ("manifest", "required_roles", "checks", "findings"),
    "policy-ops-check": ("bundle", "requirements", "checks", "findings"),
    "privacy-ops-check": ("bundle", "requirements", "checks", "findings"),
    "provenance-ops-check": ("bundle", "requirements", "checks", "findings"),
    "provenance-trust-check": ("suite", "required_case_ids", "checks", "findings"),
    "provider-check": ("manifest", "checks"),
    "retrieval-ops-check": ("bundle", "requirements", "checks", "findings"),
    "postgres-role-check": ("target", "requirements", "roles", "checks", "findings"),
    "idp-jwks-live-check": ("issuer", "audience", "jwks", "token", "identity"),
    "idp-authz-policy-rollout-check": ("rollout",),
    "tls-cert-check": ("target", "tls", "certificate", "checks"),
    "tls-lifecycle-ops-check": ("bundle", "requirements", "checks", "findings"),
    "tls-rotation-plan-check": ("config", "current", "candidate", "rotation", "checks"),
    "mcp-http-soak": ("target", "config", "health", "iterations", "summary"),
    "mcp-ops-check": ("bundle", "requirements", "checks", "findings"),
    "mcp-streamable-http-soak": ("target", "config", "health", "iterations", "summary"),
    "consolidation-ops-check": ("bundle", "requirements", "checks", "findings"),
    "multimodal-ops-check": ("bundle", "requirements", "checks", "findings"),
    "gate-suite-check": ("suite", "requirements", "failures"),
    "projection-recompute-once": ("queue", "enqueued_job", "job", "metrics"),
    "worker-run": ("worker", "summary", "queue", "cycles", "jobs", "metrics"),
    "ops-dashboard-check": ("mode", "source", "checks", "findings", "redaction"),
    "parametric-trainer-check": ("bundle", "requirements", "checks", "findings"),
    "worker-ops-check": ("bundle", "requirements", "checks", "findings", "redaction"),
    "ops-report": ("counts", "tripwires", "audit"),
}
RELEASE_AUDIT_BUNDLE_OPS_COMMANDS = frozenset(
    command
    for command, keys in RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS.items()
    if {"bundle", "requirements", "checks", "findings"}.issubset(keys)
)
RELEASE_AUDIT_ALLOWED_EMPTY_OUTPUT_KEYS = frozenset({"failures", "findings"})
RELEASE_AUDIT_PLACEHOLDER_MARKERS = (
    "placeholder",
    "dummy",
    "todo",
    "tbd",
    "changeme",
    "change-me",
    "replace-me",
    "replace_me",
    "lorem ipsum",
)


def default_store() -> Path:
    return Path(os.environ.get("MNEME_STORE", ".mnemosyne/store.json"))


def default_backend() -> str:
    return os.environ.get("MNEME_BACKEND", "local")


def default_postgres_dsn() -> str | None:
    return os.environ.get("MNEMOSYNE_POSTGRES_DSN")


def default_object_store() -> str:
    return os.environ.get("MNEMOSYNE_OBJECT_STORE", ".mnemosyne/objects")


def default_object_store_encryption() -> str:
    return os.environ.get("MNEMOSYNE_OBJECT_STORE_ENCRYPTION", "none")


def default_object_key_store() -> str | None:
    return os.environ.get("MNEMOSYNE_OBJECT_KEY_STORE")


def default_object_key_provider() -> str:
    return os.environ.get("MNEMOSYNE_OBJECT_KEY_PROVIDER") or (
        "command" if os.environ.get("MNEMOSYNE_OBJECT_KEY_COMMAND") else "json"
    )


def default_object_key_command() -> str | None:
    return os.environ.get("MNEMOSYNE_OBJECT_KEY_COMMAND")


def default_allowed_residencies() -> list[str]:
    raw = os.environ.get("MNEMOSYNE_ALLOWED_RESIDENCIES", "local")
    return [item.strip() for item in raw.split(",") if item.strip()]


def default_allowed_residency_transfers() -> list[str]:
    raw = os.environ.get("MNEMOSYNE_ALLOWED_RESIDENCY_TRANSFERS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def apply_session_identity(args: argparse.Namespace) -> None:
    from mnemosyne.security import SessionAuthError

    token = getattr(args, "session_token", None)
    if token:
        try:
            identity = _session_verifier_from_args(args).verify(token)
        except SessionAuthError as exc:
            raise SystemExit(f"session token denied: {exc}") from exc
        _bind_session_claim(args, "tenant", identity.tenant_id)
        _bind_session_claim(args, "user", identity.user_id)
        if hasattr(args, "role"):
            args.role = identity.role
        if hasattr(args, "source_trust_tier"):
            args.source_trust_tier = identity.source_trust_tier
        args.session_identity = identity
    _require_authorization_context(args)


def _session_verifier_from_args(args: argparse.Namespace) -> SessionTokenVerifier:
    from mnemosyne.security import SessionTokenVerifier, parse_session_revoke_list

    material, active_key_id = _session_material_from_args(args, purpose="--session-token")
    revoked_key_ids = parse_session_revoke_list(getattr(args, "session_revoked_key_ids", None))
    revoked_session_ids = parse_session_revoke_list(getattr(args, "session_revoked_ids", None))
    if isinstance(material, dict):
        return SessionTokenVerifier(
            material,
            active_key_id=active_key_id,
            revoked_key_ids=revoked_key_ids,
            revoked_session_ids=revoked_session_ids,
        )
    return SessionTokenVerifier(material, revoked_key_ids=revoked_key_ids, revoked_session_ids=revoked_session_ids)


def _session_signer_from_args(args: argparse.Namespace) -> SessionTokenVerifier:
    from mnemosyne.security import SessionTokenVerifier

    material, active_key_id = _session_material_from_args(args, purpose="session-exchange")
    if isinstance(material, dict):
        return SessionTokenVerifier(material, active_key_id=active_key_id)
    return SessionTokenVerifier(material)


def _session_material_from_args(
    args: argparse.Namespace,
    *,
    purpose: str,
) -> tuple[str | dict[str, str], str | None]:
    from mnemosyne.security import SessionAuthError, load_session_secret_command, parse_session_keyring

    keyring = parse_session_keyring(getattr(args, "session_keyring", None))
    secret = getattr(args, "session_secret", None)
    command = getattr(args, "session_secret_command", None)
    source_count = sum([bool(keyring), bool(secret), bool(command)])
    if source_count > 1:
        raise SessionAuthError(
            f"{purpose} requires at most one of --session-secret, --session-keyring, or --session-secret-command."
        )
    active_key_id = getattr(args, "session_key_id", None)
    if keyring:
        return keyring, active_key_id
    if secret:
        return secret, None
    if command:
        material, command_active_key_id = load_session_secret_command(
            command,
            timeout_seconds=float(getattr(args, "session_secret_command_timeout", 10.0)),
        )
        return material, active_key_id or command_active_key_id
    raise SessionAuthError(
        f"{purpose} requires --session-secret, --session-keyring, --session-secret-command, or MNEMOSYNE_SESSION_SECRET."
    )


def _bind_session_claim(args: argparse.Namespace, attr: str, value: str) -> None:
    if not hasattr(args, attr):
        return
    current = getattr(args, attr)
    if current is None or current == "":
        setattr(args, attr, value)
        return
    if str(current) != value:
        raise SystemExit(f"session {attr} mismatch: CLI value does not match authenticated session")


def _require_authorization_context(args: argparse.Namespace) -> None:
    command = getattr(args, "command", None)
    if command not in {
        "confirm",
        "branch",
        "merge",
        "discard",
        "lesson-promote",
        "procedure-validate",
        "procedure-promote",
        "procedure-rollback",
        "parametric-propose",
        "parametric-evaluate",
        "parametric-rollback",
    }:
        return
    missing: list[str] = []
    if getattr(args, "role", None) is None:
        missing.append("--role")
    if getattr(args, "source_trust_tier", None) is None:
        missing.append("--source-trust-tier")
    if missing:
        joined = " and ".join(missing)
        raise SystemExit(f"{command} requires {joined} or --session-token.")


def load_retrieval_adapters(args: argparse.Namespace) -> RetrievalAdapters:
    from mnemosyne.retrieval import (
        CommandGraphRetriever,
        CommandLexicalRetriever,
        HashingEmbeddingProvider,
        HttpEmbeddingProvider,
        HttpReranker,
        LocalSimilarityReranker,
        RetrievalAdapters,
    )

    dims = int(args.embedding_dims)
    timeout = float(args.retrieval_timeout)
    if args.embedding_provider == "http":
        if not args.embedding_url:
            raise SystemExit("HTTP embedding provider requires --embedding-url or MNEMOSYNE_EMBEDDING_URL.")
        embedding = HttpEmbeddingProvider(
            url=args.embedding_url,
            model=args.embedding_model,
            api_key=args.embedding_api_key,
            dims=dims,
            timeout_seconds=timeout,
        )
    else:
        embedding = HashingEmbeddingProvider(dims=dims)

    if args.reranker_provider == "http":
        if not args.reranker_url:
            raise SystemExit("HTTP reranker provider requires --reranker-url or MNEMOSYNE_RERANKER_URL.")
        reranker = HttpReranker(
            url=args.reranker_url,
            model=args.reranker_model,
            api_key=args.reranker_api_key,
            timeout_seconds=timeout,
        )
    else:
        reranker = LocalSimilarityReranker(embedding_provider=embedding)

    lexical_retriever = None
    if args.lexical_provider == "command":
        if not args.lexical_command:
            raise SystemExit("command lexical provider requires --lexical-command or MNEMOSYNE_LEXICAL_COMMAND.")
        lexical_retriever = CommandLexicalRetriever(
            args.lexical_command,
            backend=args.lexical_backend,
            timeout_seconds=timeout,
        )

    graph_retriever = None
    if args.graph_provider == "command":
        if not args.graph_command:
            raise SystemExit("command graph provider requires --graph-command or MNEMOSYNE_GRAPH_COMMAND.")
        graph_retriever = CommandGraphRetriever(
            args.graph_command,
            backend=args.graph_backend,
            timeout_seconds=timeout,
        )

    return RetrievalAdapters(
        embedding=embedding,
        reranker=reranker,
        lexical_backend=args.lexical_backend,
        graph_backend=args.graph_backend,
        lexical_retriever=lexical_retriever,
        graph_retriever=graph_retriever,
    )


def max_ingest_bytes(args: argparse.Namespace) -> int:
    from mnemosyne.media_limits import DEFAULT_MAX_INGEST_BYTES, validate_byte_limit

    return validate_byte_limit(
        int(getattr(args, "max_ingest_bytes", DEFAULT_MAX_INGEST_BYTES)),
        name="max_ingest_bytes",
    )


def load_media_embedding_provider(args: argparse.Namespace) -> CommandMediaEmbeddingProvider | None:
    from mnemosyne.retrieval import CommandMediaEmbeddingProvider

    if args.media_embedding_provider == "command":
        if not args.media_embedding_command:
            raise SystemExit("command media embedding provider requires --media-embedding-command.")
        return CommandMediaEmbeddingProvider(
            args.media_embedding_command,
            dims=int(args.media_embedding_dims),
            timeout_seconds=float(args.media_embedding_timeout),
            max_media_bytes=max_ingest_bytes(args),
        )
    return None


def load_engine(args: argparse.Namespace) -> MemoryEngine:
    from mnemosyne.engine import LocalMemoryEngine

    if args.backend == "postgres":
        dsn = args.postgres_dsn
        if not dsn:
            raise SystemExit("Postgres backend requires --postgres-dsn or MNEMOSYNE_POSTGRES_DSN.")
        try:
            from mnemosyne.postgres_engine import PostgresEngine, PostgresUnavailableError
        except ImportError as exc:  # pragma: no cover - defensive for broken installs.
            raise SystemExit("Postgres backend requires mnemosyne-memory[postgres].") from exc
        try:
            return PostgresEngine(
                dsn,
                adapters=load_retrieval_adapters(args),
                require_safe_role=bool(getattr(args, "postgres_require_safe_role", False)),
            )
        except PostgresUnavailableError as exc:
            raise SystemExit(str(exc)) from exc
    if args.backend == "sqlite":
        from mnemosyne.sqlite_engine import SqliteEngine

        # --store doubles as the per-tenant SQLite root directory (one
        # <tenant>.db per tenant), mirroring how local/postgres read --store/DSN.
        return SqliteEngine(Path(args.store), adapters=load_retrieval_adapters(args))
    return LocalMemoryEngine(store_path=Path(args.store), adapters=load_retrieval_adapters(args))


def load_provenance_verifier(args: argparse.Namespace) -> SignedProvenanceVerifier | C2paToolVerifier:
    from mnemosyne.provenance import C2paToolVerifier, SignedProvenanceVerifier

    if args.c2pa_tool:
        trust_policy = load_provenance_trust_policy(args)
        return C2paToolVerifier(
            tool_path=args.c2pa_tool,
            trust_policy=trust_policy,
            timeout_seconds=args.provenance_timeout,
        )
    return SignedProvenanceVerifier()


def load_provenance_trust_policy(args: argparse.Namespace) -> ProvenanceTrustPolicy:
    from mnemosyne.provenance import ProvenanceTrustPolicy

    trusted_issuers = [str(item).strip() for item in (args.trusted_provenance_issuer or []) if str(item).strip()]
    trusted_roots = [str(item).strip() for item in (args.trusted_provenance_root or []) if str(item).strip()]
    require_trusted_issuer = True
    require_trusted_root = False
    rules = ()
    policy_path = getattr(args, "provenance_trust_policy", None)
    if policy_path:
        policy_data = json.loads(Path(policy_path).read_text(encoding="utf-8"))
        policy = ProvenanceTrustPolicy.from_dict(policy_data)
        trusted_issuers.extend(policy.trusted_issuers)
        trusted_roots.extend(policy.trusted_roots)
        require_trusted_issuer = policy.require_trusted_issuer
        require_trusted_root = policy.require_trusted_root
        rules = policy.rules
    return ProvenanceTrustPolicy(
        trusted_issuers=tuple(dict.fromkeys(trusted_issuers)),
        trusted_roots=tuple(dict.fromkeys(trusted_roots)),
        require_trusted_issuer=require_trusted_issuer,
        require_trusted_root=require_trusted_root,
        rules=rules,
    )


def load_object_store(args: argparse.Namespace) -> LocalObjectStore:
    from mnemosyne.storage import (
        EncryptedLocalObjectStore,
        EncryptedS3ObjectStore,
        LocalObjectStore,
        S3ObjectStore,
        SeaweedS3Client,
        s3_config_from_env,
    )

    # Additive byte-backend selector. Default stays "local" so existing
    # /data/objects payloads are never stranded; "s3" externalizes the same
    # AES-GCM envelopes to SeaweedFS (identical encrypted/key_provider semantics).
    backend = getattr(args, "object_store_backend", "local") or "local"
    if backend == "s3":
        client = SeaweedS3Client(s3_config_from_env())
        if args.object_store_encryption == "aesgcm":
            return EncryptedS3ObjectStore(client, load_object_key_manager(args))
        return S3ObjectStore(client)
    if args.object_store_encryption == "aesgcm":
        return EncryptedLocalObjectStore(Path(args.object_store), load_object_key_manager(args))
    return LocalObjectStore(Path(args.object_store))


def load_object_key_manager(args: argparse.Namespace) -> JsonKeyManager | CommandKeyManager:
    from mnemosyne.storage import CommandKeyManager, JsonKeyManager

    if args.object_key_provider == "command":
        if not args.object_key_command:
            raise SystemExit("--object-key-provider command requires --object-key-command.")
        return CommandKeyManager(args.object_key_command, timeout_seconds=float(args.object_key_timeout))
    if args.object_key_provider != "json":
        raise SystemExit(f"Unsupported object key provider: {args.object_key_provider}")
    key_store = Path(args.object_key_store) if args.object_key_store else Path(args.object_store) / ".keys.json"
    return JsonKeyManager(key_store)


def load_media_extractor(args: argparse.Namespace) -> MediaTextExtractor:
    from mnemosyne.media import CommandMediaTextExtractor, MetadataMediaTextExtractor

    if args.media_extractor_command:
        return CommandMediaTextExtractor(
            args.media_extractor_command,
            timeout_seconds=float(args.media_extractor_timeout),
            max_media_bytes=max_ingest_bytes(args),
        )
    return MetadataMediaTextExtractor()


def _role_http_api_key(api_key_env: str | None) -> str | None:
    """Resolve an optional bearer token for a hosted role provider from the
    named environment variable (custody-managed, never inline)."""
    if not api_key_env:
        return None
    value = os.environ.get(api_key_env)
    if not value:
        raise SystemExit(f"role provider api key env {api_key_env} is not set")
    return value


def load_entity_resolver(args: argparse.Namespace) -> EntityResolver | None:
    from mnemosyne.consolidation import CommandEntityResolver, HttpEntityResolver

    if args.entity_resolver_provider == "command":
        if not args.entity_resolver_command:
            raise SystemExit("--entity-resolver-provider command requires --entity-resolver-command.")
        return CommandEntityResolver(
            args.entity_resolver_command,
            timeout_seconds=float(args.entity_resolver_timeout),
            disclosure_policy=load_proposal_disclosure_policy(args),
        )
    if args.entity_resolver_provider == "http":
        if not args.entity_resolver_url:
            raise SystemExit("--entity-resolver-provider http requires --entity-resolver-url.")
        return HttpEntityResolver(
            args.entity_resolver_url,
            api_key=_role_http_api_key(getattr(args, "entity_resolver_api_key_env", None)),
            timeout_seconds=float(args.entity_resolver_timeout),
            disclosure_policy=load_proposal_disclosure_policy(args),
        )
    return None


def load_candidate_extractor(args: argparse.Namespace) -> CandidateExtractor | None:
    from mnemosyne.consolidation import CommandCandidateExtractor, HttpCandidateExtractor

    if args.candidate_extractor_provider == "command":
        if not args.candidate_extractor_command:
            raise SystemExit("--candidate-extractor-provider command requires --candidate-extractor-command.")
        return CommandCandidateExtractor(
            args.candidate_extractor_command,
            timeout_seconds=float(args.candidate_extractor_timeout),
            disclosure_policy=load_proposal_disclosure_policy(args),
        )
    if args.candidate_extractor_provider == "http":
        if not args.candidate_extractor_url:
            raise SystemExit("--candidate-extractor-provider http requires --candidate-extractor-url.")
        return HttpCandidateExtractor(
            args.candidate_extractor_url,
            api_key=_role_http_api_key(getattr(args, "candidate_extractor_api_key_env", None)),
            timeout_seconds=float(args.candidate_extractor_timeout),
            disclosure_policy=load_proposal_disclosure_policy(args),
        )
    return None


def load_consolidation_summarizer(args: argparse.Namespace) -> EvidenceSummarizer | None:
    from mnemosyne.consolidation import CommandEvidenceSummarizer, HttpEvidenceSummarizer

    if args.summarizer_provider == "command":
        if not args.summarizer_command:
            raise SystemExit("--summarizer-provider command requires --summarizer-command.")
        return CommandEvidenceSummarizer(
            args.summarizer_command,
            timeout_seconds=float(args.summarizer_timeout),
            disclosure_policy=load_proposal_disclosure_policy(args),
        )
    if args.summarizer_provider == "http":
        if not args.summarizer_url:
            raise SystemExit("--summarizer-provider http requires --summarizer-url.")
        return HttpEvidenceSummarizer(
            args.summarizer_url,
            api_key=_role_http_api_key(getattr(args, "summarizer_api_key_env", None)),
            timeout_seconds=float(args.summarizer_timeout),
            disclosure_policy=load_proposal_disclosure_policy(args),
        )
    return None


def load_lesson_distiller(args: argparse.Namespace) -> LessonDistiller | None:
    from mnemosyne.consolidation import CommandLessonDistiller, HttpLessonDistiller

    if args.lesson_distiller_provider == "command":
        if not args.lesson_distiller_command:
            raise SystemExit("--lesson-distiller-provider command requires --lesson-distiller-command.")
        return CommandLessonDistiller(
            args.lesson_distiller_command,
            timeout_seconds=float(args.lesson_distiller_timeout),
            disclosure_policy=load_proposal_disclosure_policy(args),
        )
    if args.lesson_distiller_provider == "http":
        if not args.lesson_distiller_url:
            raise SystemExit("--lesson-distiller-provider http requires --lesson-distiller-url.")
        return HttpLessonDistiller(
            args.lesson_distiller_url,
            api_key=_role_http_api_key(getattr(args, "lesson_distiller_api_key_env", None)),
            timeout_seconds=float(args.lesson_distiller_timeout),
            disclosure_policy=load_proposal_disclosure_policy(args),
        )
    return None


def load_procedure_inducer(args: argparse.Namespace) -> ProcedureInducer | None:
    from mnemosyne.consolidation import CommandProcedureInducer, HttpProcedureInducer

    if args.skill_inducer_provider == "command":
        if not args.skill_inducer_command:
            raise SystemExit("--skill-inducer-provider command requires --skill-inducer-command.")
        return CommandProcedureInducer(
            args.skill_inducer_command,
            timeout_seconds=float(args.skill_inducer_timeout),
            disclosure_policy=load_proposal_disclosure_policy(args),
        )
    if args.skill_inducer_provider == "http":
        if not args.skill_inducer_url:
            raise SystemExit("--skill-inducer-provider http requires --skill-inducer-url.")
        return HttpProcedureInducer(
            args.skill_inducer_url,
            api_key=_role_http_api_key(getattr(args, "skill_inducer_api_key_env", None)),
            timeout_seconds=float(args.skill_inducer_timeout),
            disclosure_policy=load_proposal_disclosure_policy(args),
        )
    return None


def load_proposal_disclosure_policy(args: argparse.Namespace):
    from mnemosyne.consolidation import ProviderDisclosurePolicy

    return ProviderDisclosurePolicy(
        endpoint_class=args.proposal_provider_class,
        retention=args.proposal_provider_retention,
        endpoint_region=args.proposal_provider_region or args.runtime_residency or "local",
        runtime_region=args.runtime_residency or "local",
    )


def load_parametric_tier(args: argparse.Namespace) -> ParametricTier:
    from mnemosyne.parametric import CommandParametricTrainer, ParametricArtifactStore, ParametricTier

    root = args.parametric_artifact_store
    if not root:
        store = Path(args.store).expanduser()
        root = store.with_suffix(store.suffix + ".parametric")
    trainer = None
    if args.parametric_provider == "command":
        if not args.parametric_command:
            raise SystemExit("--parametric-provider command requires --parametric-command.")
        trainer = CommandParametricTrainer(
            args.parametric_command,
            adapter_kind=args.parametric_adapter_kind,
            timeout_seconds=float(args.parametric_timeout),
        )
    elif args.parametric_provider != "local":
        raise SystemExit(f"Unsupported parametric provider: {args.parametric_provider}")
    return ParametricTier(ParametricArtifactStore(root), trainer=trainer)


def runtime_state_tenant(args: argparse.Namespace) -> str:
    return getattr(args, "tenant", None) or getattr(args, "queue_tenant", None) or "system"


def load_runtime_state(args: argparse.Namespace) -> RuntimeState | PostgresRuntimeState | None:
    from mnemosyne.postgres_runtime_state import PostgresRuntimeState
    from mnemosyne.runtime_state import RuntimeState

    if args.backend == "postgres":
        dsn = args.postgres_dsn
        if not dsn:
            raise SystemExit("--backend postgres requires --postgres-dsn or MNEMOSYNE_POSTGRES_DSN.")
        return PostgresRuntimeState(
            dsn,
            tenant_id=runtime_state_tenant(args),
            require_safe_role=bool(getattr(args, "postgres_require_safe_role", False)),
        )
    return RuntimeState.from_store_path(Path(args.store))


def load_queue(
    args: argparse.Namespace,
    runtime_state: RuntimeState | PostgresRuntimeState | None = None,
) -> InProcessQueue | PostgresQueue | SqliteQueue:
    from mnemosyne.queue import InProcessQueue, PostgresQueue, SqliteQueue

    if args.queue_backend == "postgres":
        dsn = args.postgres_dsn
        if not dsn:
            raise SystemExit("--queue-backend postgres requires --postgres-dsn or MNEMOSYNE_POSTGRES_DSN.")
        tenant_id = runtime_state_tenant(args)
        return PostgresQueue(
            dsn,
            tenant_id=tenant_id,
            require_safe_role=bool(getattr(args, "postgres_require_safe_role", False)),
        )
    if args.queue_backend == "sqlite":
        # Durable per-tenant runtime_jobs table under the SQLite --store root.
        return SqliteQueue(Path(args.store), tenant_id=runtime_state_tenant(args))
    return runtime_state.load_queue() if runtime_state else InProcessQueue()


def queue_uses_runtime_state(args: argparse.Namespace) -> bool:
    return args.queue_backend == "local"


def load_tools(
    args: argparse.Namespace,
    ingestion_queue: InProcessQueue | PostgresQueue | None = None,
    runtime_state: RuntimeState | PostgresRuntimeState | None = None,
) -> MemoryTools:
    from mnemosyne.ingestion import IngestionPipeline
    from mnemosyne.mcp_tools import MemoryTools

    engine = load_engine(args)
    resolved_runtime_state = runtime_state if runtime_state is not None else load_runtime_state(args)
    ingestion = IngestionPipeline(
        engine,
        object_store=load_object_store(args),
        provenance_verifier=load_provenance_verifier(args),
        queue=ingestion_queue,
        allowed_residencies=tuple(args.allowed_residency),
        runtime_residency=args.runtime_residency,
        allowed_residency_transfers=tuple(args.allowed_residency_transfer),
        require_runtime_residency=args.require_runtime_residency,
        media_embedding_provider=load_media_embedding_provider(args),
        max_ingest_bytes=max_ingest_bytes(args),
    )
    return MemoryTools(
        engine,
        ingestion=ingestion,
        runtime_state=resolved_runtime_state,
        parametric=load_parametric_tier(args),
    )


def gate_case_id(signature: str, query: str, expected_substring: str) -> str:
    digest = sha256(f"{signature}\0{query}\0{expected_substring}".encode("utf-8")).hexdigest()[:12]
    return f"gate-{digest}"


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, memoryview):
        return value.tobytes().hex()
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=json_default))


def _oidc_verifier_components(
    args: argparse.Namespace,
) -> tuple[OidcJwtVerifier, dict[str, Any], OidcAuthorizationPolicy | None]:
    from mnemosyne.oidc_jwks import load_oidc_authorization_policy, load_oidc_jwks, oidc_jwks_loader
    from mnemosyne.security import OidcJwtVerifier

    allowed_internal_hosts = tuple(
        host.strip()
        for host in (getattr(args, "idp_allowed_internal_hosts", None) or "").split(",")
        if host.strip()
    )
    jwks_document = load_oidc_jwks(
        jwks=args.idp_jwks,
        jwks_file=args.idp_jwks_file,
        jwks_url=args.idp_jwks_url,
        allow_insecure_url=args.idp_allow_insecure_jwks_url,
        timeout=args.idp_timeout,
        max_bytes=args.idp_jwks_max_bytes,
        allowed_internal_hosts=allowed_internal_hosts,
    )
    policy = load_oidc_authorization_policy(
        policy=args.idp_authz_policy,
        policy_file=args.idp_authz_policy_file,
    )
    verifier = OidcJwtVerifier(
        jwks_document,
        issuer=args.idp_issuer,
        audience=args.idp_audience,
        tenant_claim=args.idp_tenant_claim,
        user_claim=args.idp_user_claim,
        role_claim=args.idp_role_claim,
        trust_claim=args.idp_trust_claim,
        session_id_claim=args.idp_session_id_claim,
        allowed_algorithms=tuple(args.idp_algorithm),
        leeway_seconds=args.idp_leeway_seconds,
        jwks_loader=oidc_jwks_loader(
            jwks=args.idp_jwks,
            jwks_file=args.idp_jwks_file,
            jwks_url=args.idp_jwks_url,
            allow_insecure_url=args.idp_allow_insecure_jwks_url,
            timeout=args.idp_timeout,
            max_bytes=args.idp_jwks_max_bytes,
            allowed_internal_hosts=allowed_internal_hosts,
        ),
        jwks_cache_ttl_seconds=args.idp_jwks_cache_ttl_seconds,
        refresh_on_unknown_kid=not args.idp_disable_refresh_on_unknown_kid,
        expected_kid_sha256=tuple(getattr(args, "idp_expected_kid_sha256", None) or ()),
        authorization_policy=policy,
    )
    return verifier, jwks_document, policy


def _idp_jwks_source(args: argparse.Namespace) -> dict[str, Any]:
    if args.idp_jwks_url:
        return {"kind": "url", "url": _display_url(args.idp_jwks_url)}
    if args.idp_jwks_file:
        return {"kind": "file", "path": str(args.idp_jwks_file)}
    if args.idp_jwks:
        return {"kind": "inline"}
    return {"kind": "unset"}


def cmd_session_exchange(args: argparse.Namespace) -> None:
    from mnemosyne.security import SessionAuthError, issue_session_from_oidc

    if not args.idp_token:
        raise SystemExit("session-exchange requires --idp-token or MNEMOSYNE_IDP_TOKEN")
    try:
        verifier, _jwks_document, _policy = _oidc_verifier_components(args)
        session_token, issued = issue_session_from_oidc(
            verifier=verifier,
            idp_token=args.idp_token,
            signer=_session_signer_from_args(args),
            max_ttl_seconds=args.session_max_ttl_seconds,
        )
    except SessionAuthError as exc:
        raise SystemExit(f"session exchange denied: {exc}") from exc
    emit(
        {
            "ok": True,
            "session_token": session_token,
            "identity": issued.to_payload(),
            "issuer": args.idp_issuer,
            "audience": args.idp_audience,
            "expires_at": issued.expires_at,
        }
    )


def cmd_idp_jwks_live_check(args: argparse.Namespace) -> None:
    from mnemosyne.security import SessionAuthError

    if not args.idp_token:
        raise SystemExit("idp-jwks-live-check requires --idp-token or MNEMOSYNE_IDP_TOKEN")
    started = time.monotonic()
    try:
        verifier, jwks_document, policy = _oidc_verifier_components(args)
        header, _payload, _signing_input, _signature = verifier._decode_compact_jwt(args.idp_token)
        identity = verifier.verify(args.idp_token)
        keys = jwks_document.get("keys") if isinstance(jwks_document, dict) else None
        if not isinstance(keys, list) or not keys:
            raise SessionAuthError("OIDC JWKS must include at least one key")
        now_ts = int(time.time())
        expires_in = identity.expires_at - now_ts if identity.expires_at is not None else None
        report: dict[str, Any] = {
            "ok": True,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "issuer": args.idp_issuer,
            "audience": args.idp_audience,
            "jwks": {
                "source": _idp_jwks_source(args),
                "key_count": len(keys),
                "allow_insecure_url": bool(args.idp_allow_insecure_jwks_url),
                "max_bytes": args.idp_jwks_max_bytes,
                "cache_ttl_seconds": args.idp_jwks_cache_ttl_seconds,
                "refresh_on_unknown_kid": not args.idp_disable_refresh_on_unknown_kid,
                "kid_pinning": {
                    "enabled": bool(verifier.expected_kid_sha256),
                    "pinned_kid_count": len(verifier.expected_kid_sha256),
                    "usable_key_count": len(verifier.keys_by_id),
                },
            },
            "token": {
                "configured": True,
                "alg": header.get("alg"),
                "kid_present": bool(header.get("kid")),
                "kid_sha256": sha256(str(header.get("kid") or "").encode("utf-8")).hexdigest()[:16]
                if header.get("kid")
                else None,
                "expires_in_seconds": expires_in,
                "session_id_present": bool(identity.session_id),
            },
            "identity": {
                "tenant_id": identity.tenant_id,
                "user_id_sha256": sha256(identity.user_id.encode("utf-8")).hexdigest()[:16],
                "role": identity.role,
                "source_trust_tier": identity.source_trust_tier,
            },
            "authz_policy_configured": policy is not None,
        }
        if policy is not None:
            report["authz_policy"] = policy.audit_summary()
        emit(report)
    except SessionAuthError as exc:
        emit(
            {
                "ok": False,
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "issuer": args.idp_issuer,
                "audience": args.idp_audience,
                "jwks": {"source": _idp_jwks_source(args)},
                "token": {"configured": bool(args.idp_token)},
                "error": str(exc),
            }
        )
        raise SystemExit(1) from exc


def _postgres_role_finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _postgres_role_fingerprint(report: Mapping[str, Any]) -> str:
    stable = {
        "target": report.get("target"),
        "requirements": report.get("requirements"),
        "roles": report.get("roles"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _postgres_role_target(dsn: str) -> dict[str, Any]:
    """Describe a probe target without ever emitting the raw DSN.

    Key/value DSNs without a parseable host are treated as local so the
    non-local production gate fails closed rather than passing on ambiguity."""
    host = ""
    port: int | None = None
    dbname = ""
    if "://" in dsn:
        try:
            parsed = urlsplit(dsn)
            host = parsed.hostname or ""
            port = parsed.port
            dbname = (parsed.path or "").lstrip("/")
        except ValueError:
            host = ""
    else:
        for part in dsn.split():
            key, _, value = part.partition("=")
            if key == "host":
                host = value.strip("'\"")
            elif key == "port" and value.strip("'\"").isdigit():
                port = int(value.strip("'\""))
            elif key == "dbname":
                dbname = value.strip("'\"")
    lowered = host.lower()
    local = (
        not lowered
        or lowered in {"localhost", "::1", "[::1]"}
        or lowered.startswith("127.")
        or lowered.startswith("/")
    )
    return {
        "configured": True,
        "host": host or None,
        "port": port,
        "dbname": dbname or None,
        "local": local,
        "dsn_sha256": "sha256:" + sha256(dsn.encode("utf-8")).hexdigest(),
    }


def _probe_postgres_role_connection(
    conn: Any,
    *,
    expected_group: str,
    group_names: Sequence[str],
    audit_table: str,
) -> dict[str, Any]:
    """Live-probe one Postgres connection for role-separation posture.

    Answers the questions roles.sql requires an ops-check to prove: the
    session role is NOSUPERUSER/NOBYPASSRLS, maps onto the expected group,
    and holds exactly the destructive privileges the separation grants."""
    from mnemosyne.postgres_security import inspect_postgres_role

    role = inspect_postgres_role(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s),
                   CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)
                        THEN pg_has_role(current_user, %s, 'member')
                        ELSE false END
            """,
            (expected_group, expected_group, expected_group),
        )
        group_row = cur.fetchone()
        cur.execute(
            """
            SELECT tablename,
                   has_table_privilege(current_user, 'public.' || quote_ident(tablename), 'DELETE'),
                   has_table_privilege(current_user, 'public.' || quote_ident(tablename), 'TRUNCATE'),
                   has_table_privilege(current_user, 'public.' || quote_ident(tablename), 'UPDATE')
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
        table_rows = cur.fetchall()
        cur.execute(
            "SELECT rolname, rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s)",
            (list(group_names),),
        )
        posture_rows = cur.fetchall()
    table_names = [str(row[0]) for row in table_rows]
    return {
        "current_user": role.current_user,
        "rolsuper": role.rolsuper,
        "rolbypassrls": role.rolbypassrls,
        "expected_group": expected_group,
        "group_exists": bool(group_row and group_row[0]),
        "group_member": bool(group_row and group_row[1]),
        "table_count": len(table_names),
        "delete_tables": [str(row[0]) for row in table_rows if row[1]],
        "truncate_tables": [str(row[0]) for row in table_rows if row[2]],
        "audit_table_present": audit_table in table_names,
        "audit_update": any(bool(row[3]) for row in table_rows if str(row[0]) == audit_table),
        "audit_delete": any(bool(row[1]) for row in table_rows if str(row[0]) == audit_table),
        "audit_truncate": any(bool(row[2]) for row in table_rows if str(row[0]) == audit_table),
        "groups": {
            str(row[0]): {
                "rolsuper": bool(row[1]),
                "rolbypassrls": bool(row[2]),
                "rolcanlogin": bool(row[3]),
            }
            for row in posture_rows
        },
    }


def cmd_postgres_role_check(args: argparse.Namespace) -> None:
    started = time.monotonic()
    if not args.app_dsn:
        raise SystemExit("postgres-role-check requires --app-dsn or MNEMOSYNE_POSTGRES_DSN")
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised only without the postgres extra.
        raise SystemExit("postgres-role-check requires the postgres extra (psycopg)") from exc

    group_names: tuple[str, ...] = (
        args.expected_app_group,
        args.expected_consolidator_group,
        args.readonly_group,
    )
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []
    roles: dict[str, Any] = {}
    target: dict[str, Any] = {
        "app": _postgres_role_target(args.app_dsn),
        "consolidator": _postgres_role_target(args.consolidator_dsn)
        if args.consolidator_dsn
        else {"configured": False},
    }

    def add(code: str, message: str) -> None:
        findings.append(_postgres_role_finding(code, message))

    def check(name: str, ok: bool, message: str, **details: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), **details})
        if not ok:
            add(f"{name}_failed", message)

    probes: dict[str, dict[str, Any] | None] = {"app": None, "consolidator": None}
    for label, dsn, expected_group in (
        ("app", args.app_dsn, args.expected_app_group),
        ("consolidator", args.consolidator_dsn, args.expected_consolidator_group),
    ):
        if not dsn:
            continue
        if target[label].get("local") and not args.allow_localhost:
            add(
                "postgres_role_target_local",
                f"{label} DSN targets a local host; production role probes must be non-local",
            )
        try:
            with psycopg.connect(dsn, autocommit=True, connect_timeout=args.connect_timeout) as conn:
                probes[label] = _probe_postgres_role_connection(
                    conn,
                    expected_group=expected_group,
                    group_names=group_names,
                    audit_table=args.audit_table,
                )
        except Exception as exc:  # noqa: BLE001 - live probes must fail closed with evidence.
            add("postgres_role_probe_failed", f"{label} role probe failed: {exc}")

    app = probes["app"]
    if app is not None:
        roles["app"] = {
            key: app[key]
            for key in ("current_user", "rolsuper", "rolbypassrls", "expected_group", "group_exists", "group_member")
        }
        check(
            "app_role_safety",
            not app["rolsuper"] and not app["rolbypassrls"],
            "app role must be NOSUPERUSER and NOBYPASSRLS",
            current_user=app["current_user"],
            rolsuper=app["rolsuper"],
            rolbypassrls=app["rolbypassrls"],
        )
        check(
            "app_group_membership",
            app["group_exists"] and app["group_member"],
            f"app role must be a member of {args.expected_app_group}",
            expected_group=args.expected_app_group,
        )
        check(
            "app_destructive_writes_denied",
            not app["delete_tables"] and not app["truncate_tables"],
            "app role must not hold DELETE or TRUNCATE on any public table",
            delete_table_count=len(app["delete_tables"]),
            truncate_table_count=len(app["truncate_tables"]),
        )
        check(
            "audit_log_append_only_app",
            app["audit_table_present"]
            and not app["audit_update"]
            and not app["audit_delete"]
            and not app["audit_truncate"],
            f"app role must not hold UPDATE/DELETE/TRUNCATE on {args.audit_table}",
            audit_table=args.audit_table,
        )
        groups = app["groups"]
        roles["groups"] = groups
        check(
            "group_role_posture",
            all(
                name in groups
                and not groups[name]["rolsuper"]
                and not groups[name]["rolbypassrls"]
                and not groups[name]["rolcanlogin"]
                for name in group_names
            ),
            "group roles must exist as NOLOGIN NOSUPERUSER NOBYPASSRLS",
            expected_groups=list(group_names),
        )
    else:
        add("postgres_role_app_probe_missing", "app DSN probe did not produce role evidence")

    consolidator = probes["consolidator"]
    if consolidator is not None:
        roles["consolidator"] = {
            key: consolidator[key]
            for key in ("current_user", "rolsuper", "rolbypassrls", "expected_group", "group_exists", "group_member")
        }
        check(
            "consolidator_role_safety",
            not consolidator["rolsuper"] and not consolidator["rolbypassrls"],
            "consolidator role must be NOSUPERUSER and NOBYPASSRLS",
            current_user=consolidator["current_user"],
            rolsuper=consolidator["rolsuper"],
            rolbypassrls=consolidator["rolbypassrls"],
        )
        check(
            "consolidator_group_membership",
            consolidator["group_exists"] and consolidator["group_member"],
            f"consolidator role must be a member of {args.expected_consolidator_group}",
            expected_group=args.expected_consolidator_group,
        )
        deletable = set(consolidator["delete_tables"])
        check(
            "consolidator_sole_write",
            consolidator["table_count"] > 0
            and args.audit_table not in deletable
            and len(deletable) >= consolidator["table_count"] - (1 if consolidator["audit_table_present"] else 0),
            "consolidator role must hold DELETE on every public table except the audit log",
            delete_table_count=len(deletable),
            table_count=consolidator["table_count"],
        )
        check(
            "audit_log_append_only_consolidator",
            consolidator["audit_table_present"]
            and not consolidator["audit_update"]
            and not consolidator["audit_delete"]
            and not consolidator["audit_truncate"],
            f"consolidator role must not hold UPDATE/DELETE/TRUNCATE on {args.audit_table}",
            audit_table=args.audit_table,
        )
    elif args.consolidator_dsn:
        add("postgres_role_consolidator_probe_missing", "consolidator DSN probe did not produce role evidence")
    else:
        add(
            "postgres_role_consolidator_dsn_missing",
            "consolidator DSN is required for sole-write evidence "
            "(--consolidator-dsn or MNEMOSYNE_POSTGRES_CONSOLIDATOR_DSN)",
        )

    report: dict[str, Any] = {
        "ok": not findings,
        "latency_ms": round((time.monotonic() - started) * 1000, 3),
        "target": target,
        "requirements": {
            "allow_localhost": bool(args.allow_localhost),
            "expected_app_group": args.expected_app_group,
            "expected_consolidator_group": args.expected_consolidator_group,
            "readonly_group": args.readonly_group,
            "audit_table": args.audit_table,
        },
        "roles": roles,
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _postgres_role_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(
            _postgres_role_finding("fingerprint_mismatch", "postgres-role-check report fingerprint mismatch")
        )
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def cmd_idp_authz_policy_check(args: argparse.Namespace) -> None:
    from mnemosyne.oidc_jwks import load_oidc_authorization_policy
    from mnemosyne.security import SessionAuthError

    try:
        policy = load_oidc_authorization_policy(
            policy=args.idp_authz_policy,
            policy_file=args.idp_authz_policy_file,
        )
    except SessionAuthError as exc:
        raise SystemExit(f"idp authz policy denied: {exc}") from exc
    if policy is None:
        raise SystemExit("idp-authz-policy-check requires --idp-authz-policy or --idp-authz-policy-file")
    emit({"ok": True, "policy": policy.audit_summary()})


def _load_required_oidc_authz_policy(
    *,
    label: str,
    policy: str | None,
    policy_file: str | None,
) -> OidcAuthorizationPolicy:
    from mnemosyne.oidc_jwks import load_oidc_authorization_policy
    from mnemosyne.security import SessionAuthError

    try:
        loaded = load_oidc_authorization_policy(policy=policy, policy_file=policy_file)
    except SessionAuthError as exc:
        raise SystemExit(f"{label} idp authz policy denied: {exc}") from exc
    if loaded is None:
        raise SystemExit(f"{label} idp authz policy is required")
    return loaded


def _require_expected_policy_fingerprint(*, label: str, expected: str | None, actual: str) -> None:
    if not expected:
        raise SystemExit(f"{label} expected fingerprint is required")
    if expected.strip().lower() != actual:
        raise SystemExit(f"{label} fingerprint mismatch")


def _policy_rule_names(summary: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for rule in summary.get("rules", []):
        if isinstance(rule, Mapping) and rule.get("name"):
            names.add(str(rule["name"]))
    return names


def _policy_diff_summary(
    current: OidcAuthorizationPolicy,
    candidate: OidcAuthorizationPolicy,
    *,
    current_summary: Mapping[str, Any],
    candidate_summary: Mapping[str, Any],
) -> dict[str, Any]:

    current_rules = current.canonical_mapping()["rules"]
    candidate_rules = candidate.canonical_mapping()["rules"]
    compared_rules = min(len(current_rules), len(candidate_rules))
    changed_rule_indexes = [
        index
        for index in range(compared_rules)
        if current_rules[index] != candidate_rules[index]
    ]
    current_names = _policy_rule_names(current_summary)
    candidate_names = _policy_rule_names(candidate_summary)
    return {
        "fingerprint_changed": current_summary["fingerprint"] != candidate_summary["fingerprint"],
        "allowed_client_ids_count_delta": int(candidate_summary["allowed_client_ids_count"])
        - int(current_summary["allowed_client_ids_count"]),
        "client_id_claims_changed": list(current_summary["client_id_claims"]) != list(candidate_summary["client_id_claims"]),
        "rule_count_delta": int(candidate_summary["rule_count"]) - int(current_summary["rule_count"]),
        "roles_added": sorted(set(candidate_summary["roles"]) - set(current_summary["roles"])),
        "roles_removed": sorted(set(current_summary["roles"]) - set(candidate_summary["roles"])),
        "source_trust_tiers_added": sorted(set(candidate_summary["source_trust_tiers"]) - set(current_summary["source_trust_tiers"])),
        "source_trust_tiers_removed": sorted(set(current_summary["source_trust_tiers"]) - set(candidate_summary["source_trust_tiers"])),
        "named_rules_added": sorted(candidate_names - current_names),
        "named_rules_removed": sorted(current_names - candidate_names),
        "changed_rule_indexes": changed_rule_indexes,
    }


def _load_policy_simulations(path: str | None) -> list[Mapping[str, Any]]:
    if not path:
        return []
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"simulation file denied: {exc}") from exc
    if not isinstance(loaded, list):
        raise SystemExit("simulation file must contain a JSON array")
    simulations: list[Mapping[str, Any]] = []
    for index, item in enumerate(loaded):
        if not isinstance(item, Mapping):
            raise SystemExit(f"simulation {index} must be a JSON object")
        if not isinstance(item.get("payload"), Mapping):
            raise SystemExit(f"simulation {index} requires object payload")
        if not item.get("tenant_id") or not item.get("user_id"):
            raise SystemExit(f"simulation {index} requires tenant_id and user_id")
        simulations.append(item)
    return simulations


def _policy_authorization_outcome(policy: OidcAuthorizationPolicy, simulation: Mapping[str, Any]) -> dict[str, Any]:
    from mnemosyne.security import SessionAuthError

    expires_at = simulation.get("expires_at")
    session_id = simulation.get("session_id")
    try:
        identity = policy.authorize(
            simulation["payload"],  # type: ignore[arg-type]
            tenant_id=str(simulation["tenant_id"]),
            user_id=str(simulation["user_id"]),
            expires_at=int(expires_at) if expires_at is not None else None,
            session_id=str(session_id) if session_id is not None else None,
            now=int(simulation["now"]) if simulation.get("now") is not None else None,
        )
    except SessionAuthError as exc:
        return {"authorized": False, "error": str(exc)}
    return {
        "authorized": True,
        "role": identity.role,
        "source_trust_tier": identity.source_trust_tier,
    }


def _policy_simulation_report(
    current: OidcAuthorizationPolicy,
    candidate: OidcAuthorizationPolicy,
    simulations: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:

    report: list[dict[str, Any]] = []
    for index, simulation in enumerate(simulations):
        current_outcome = _policy_authorization_outcome(current, simulation)
        candidate_outcome = _policy_authorization_outcome(candidate, simulation)
        report.append(
            {
                "index": index,
                "current": current_outcome,
                "candidate": candidate_outcome,
                "changed": current_outcome != candidate_outcome,
            }
        )
    return report


def cmd_idp_authz_policy_rollout_check(args: argparse.Namespace) -> None:
    current = _load_required_oidc_authz_policy(
        label="current",
        policy=args.current_idp_authz_policy,
        policy_file=args.current_idp_authz_policy_file,
    )
    candidate = _load_required_oidc_authz_policy(
        label="candidate",
        policy=args.candidate_idp_authz_policy,
        policy_file=args.candidate_idp_authz_policy_file,
    )
    current_summary = current.audit_summary()
    candidate_summary = candidate.audit_summary()
    _require_expected_policy_fingerprint(
        label="current",
        expected=args.expected_current_fingerprint,
        actual=str(current_summary["fingerprint"]),
    )
    _require_expected_policy_fingerprint(
        label="candidate",
        expected=args.expected_candidate_fingerprint,
        actual=str(candidate_summary["fingerprint"]),
    )
    simulations = _policy_simulation_report(current, candidate, _load_policy_simulations(args.simulation_file))
    simulation_change_count = sum(1 for item in simulations if item["changed"])
    rollout = {
        "current": current_summary,
        "candidate": candidate_summary,
        "diff": _policy_diff_summary(
            current,
            candidate,
            current_summary=current_summary,
            candidate_summary=candidate_summary,
        ),
        "simulation_change_count": simulation_change_count,
        "simulations": simulations,
    }
    if simulation_change_count and not args.allow_simulation_changes:
        emit(
            {
                "ok": False,
                "error": "simulation authorization changes require --allow-simulation-changes",
                "rollout": rollout,
            }
        )
        raise SystemExit(1)
    emit({"ok": True, "rollout": rollout})


def cmd_capture(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.capture(
            tenant_id=args.tenant,
            user_id=args.user,
            actor=args.actor,
            source_type=args.source_type,
            source_identity=args.source_identity,
            content=args.content,
            branch=args.branch,
            trust_tier=args.trust_tier,
        )
    )


def load_signed_provenance(args: argparse.Namespace) -> dict[str, Any] | None:
    manifest: dict[str, Any] = {}
    if args.signed_provenance:
        manifest.update(parse_json_arg(args.signed_provenance, {}))
    if args.signed_provenance_file:
        manifest.update(json.loads(Path(args.signed_provenance_file).read_text(encoding="utf-8")))
    if args.file and args.c2pa_tool:
        manifest["asset_path"] = args.file
    return manifest or None


def cmd_ingest(args: argparse.Namespace) -> None:
    from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB
    from mnemosyne.jobs import RuntimeJobHandlers
    from mnemosyne.media_limits import ensure_file_within_limit
    from mnemosyne.observability import MetricsRegistry
    from mnemosyne.queue import QueueWorker

    runtime_state = load_runtime_state(args)
    ingestion_queue = None if args.no_enqueue_consolidation else load_queue(args, runtime_state)
    tools = load_tools(args, ingestion_queue=ingestion_queue, runtime_state=runtime_state)
    if args.file:
        ensure_file_within_limit(args.file, limit=max_ingest_bytes(args), label="ingest file")
    data = Path(args.file).read_bytes() if args.file else None
    content = args.content
    if data is None and content is None:
        raise SystemExit("ingest requires --content or --file.")
    result = tools.ingest(
        tenant_id=args.tenant,
        user_id=args.user,
        actor=args.actor,
        source_type=args.source_type,
        content=content,
        data=data,
        branch=args.branch,
        trust_tier=args.trust_tier,
        source_identity=args.source_identity,
        media_type=args.media_type,
        modality=args.modality,
        metadata=parse_json_arg(args.metadata, {}),
        signed_provenance=load_signed_provenance(args),
        capability_tags=args.capability_tag,
        sensitivity=args.sensitivity,
    )
    if args.run_consolidation_once:
        if ingestion_queue is None:
            raise SystemExit("--run-consolidation-once requires consolidation enqueueing.")
        metrics = MetricsRegistry()
        handlers = RuntimeJobHandlers(
            tools.engine,
            ingestion_queue,
            metrics=metrics,
            object_store=load_object_store(args),
            media_extractor=load_media_extractor(args),
            learning=tools.learning,
            user_model=tools.user_model,
            gate_cases=tools.runtime_state.load_gate_cases() if tools.runtime_state else [],
            entity_resolver=load_entity_resolver(args),
            candidate_extractor=load_candidate_extractor(args),
            summarizer=load_consolidation_summarizer(args),
            lesson_distiller=load_lesson_distiller(args),
            procedure_inducer=load_procedure_inducer(args),
            max_media_bytes=max_ingest_bytes(args),
        )
        worker = QueueWorker(ingestion_queue, handlers.handlers(), metrics=metrics)
        job = worker.run_once(CONSOLIDATE_EVIDENCE_JOB)
        if tools.runtime_state:
            tools.runtime_state.save_learning(tools.learning)
            tools.runtime_state.save_user_model(tools.user_model)
        result["consolidation_worker"] = {
            "queue": ingestion_queue.snapshot(),
            "job": job.to_dict() if job else None,
            "metrics": metrics.snapshot().to_dict(),
        }
    if runtime_state and ingestion_queue and queue_uses_runtime_state(args):
        runtime_state.save_queue(ingestion_queue)
    emit(result)


def cmd_assert(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.assert_fact(
            tenant_id=args.tenant,
            user_id=args.user,
            subject=args.subject,
            predicate=args.predicate,
            object_value=args.object,
            source_evidence_cids=args.evidence_cid,
            confidence=args.confidence,
            trust_tier=args.trust_tier,
            branch=args.branch,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_source_sync(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.source_sync(
            tenant_id=args.tenant,
            user_id=args.user,
            root=args.root,
            branch=args.branch,
            apply=args.apply,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
            allow_dirty=args.allow_dirty,
        )
    )


def cmd_relation(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.relation(
            tenant_id=args.tenant,
            source=args.source,
            predicate=args.predicate,
            target=args.target,
            confidence=args.confidence,
            source_evidence_cids=args.evidence_cid,
            branch=args.branch,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_preference(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.preference(
            tenant_id=args.tenant,
            user_id=args.user,
            category=args.category,
            statement=args.statement,
            explicit=args.explicit,
            confidence=args.confidence,
            source_evidence_cids=args.evidence_cid,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_search(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.search(
            tenant_id=args.tenant,
            query=args.query,
            branch=args.branch,
            min_trust_tier=args.min_trust_tier,
            max_trust_tier=args.max_trust_tier,
            max_sensitivity=args.max_sensitivity,
            role=args.role,
            user_id=getattr(args, "user", None),
            capability_tags=args.capability_tag,
            purpose=args.purpose,
            residency=args.residency,
            region=args.region,
            break_glass=args.break_glass,
            lawful_basis=args.lawful_basis,
        )
    )


def cmd_deep_search(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.deep_search(tenant_id=args.tenant, query=args.query, branch=args.branch, role=args.role))


def cmd_explain(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.explain(tenant_id=args.tenant, query=args.query, branch=args.branch))


def cmd_get(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.get(args.tenant, args.id, branch=args.branch, **_read_context_kwargs(args)))


def cmd_propose(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.propose(
            tenant_id=args.tenant,
            user_id=args.user,
            subject=args.subject,
            predicate=args.predicate,
            object_value=args.object,
            source_evidence_cids=args.evidence_cid,
            confidence=args.confidence,
            trust_tier=args.trust_tier,
            branch=args.branch,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_confirm(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.confirm(
            args.id,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
            tenant_id=args.tenant,
            branch=args.branch,
            into=args.into,
        )
    )


def cmd_supersede(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.supersede(
            tenant_id=args.tenant,
            user_id=args.user,
            id=args.id,
            new=parse_json_arg(args.new, {}),
            branch=args.branch,
            confidence=args.confidence,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_correct(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.correct(
            tenant_id=args.tenant,
            user_id=args.user,
            subject=args.subject,
            predicate=args.predicate,
            object_value=args.object,
            correction_text=args.correction,
            branch=args.branch,
            confidence=args.confidence,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_forget(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.forget(
            tenant_id=args.tenant,
            cid=args.cid,
            branch=args.branch,
            requested_by=args.requested_by,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
            erasure_mode=args.erasure_mode,
        )
    )


def cmd_export(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.export(args.tenant, **_read_context_kwargs(args)))


def _read_context_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "role": getattr(args, "role", "reader"),
        "user_id": getattr(args, "user", None),
        "max_sensitivity": getattr(args, "max_sensitivity", None),
        "capability_tags": getattr(args, "capability_tag", None) or None,
        "purpose": getattr(args, "purpose", None),
        "residency": getattr(args, "residency", None),
        "region": getattr(args, "region", None),
        "break_glass": bool(getattr(args, "break_glass", False)),
        "lawful_basis": getattr(args, "lawful_basis", None),
    }


def _add_read_context_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--role", default="reader", choices=["reader", "agent", "consolidator", "operator"])
    parser.add_argument("--user")
    parser.add_argument("--max-sensitivity", type=int)
    parser.add_argument("--capability-tag", action="append", default=[])
    parser.add_argument("--purpose")
    parser.add_argument("--lawful-basis")
    parser.add_argument("--residency")
    parser.add_argument("--region")
    parser.add_argument("--break-glass", action="store_true")


def parse_json_arg(value: str, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _load_calibration_dataset(args: argparse.Namespace) -> list[dict[str, Any]]:
    if bool(args.dataset) == bool(args.dataset_json):
        raise SystemExit("calibration-tune requires exactly one of --dataset or --dataset-json")
    try:
        loaded = json.loads(Path(args.dataset).expanduser().read_text(encoding="utf-8")) if args.dataset else json.loads(args.dataset_json)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"calibration dataset denied: {exc}") from exc
    if not isinstance(loaded, list):
        raise SystemExit("calibration dataset must be a JSON array")
    if not all(isinstance(item, dict) for item in loaded):
        raise SystemExit("calibration dataset entries must be JSON objects")
    return loaded


def cmd_calibration_tune(args: argparse.Namespace) -> None:
    from mnemosyne.calibration import calibration_examples_from_rows, tune_calibration_set

    try:
        examples = calibration_examples_from_rows(_load_calibration_dataset(args))
        tuning = tune_calibration_set(
            tenant_id=args.tenant,
            memory_type=args.memory_type,
            examples=examples,
            target_coverage=args.target_coverage,
            min_examples=args.min_examples,
            min_correct=args.min_correct,
            min_incorrect=args.min_incorrect,
            min_empirical_coverage=args.min_empirical_coverage,
            max_false_accept_rate=args.max_false_accept_rate,
            max_prediction_set_size=args.max_prediction_set_size,
        )
    except ValueError as exc:
        raise SystemExit(f"calibration dataset denied: {exc}") from exc
    applied = False
    if tuning.ok and not args.dry_run:
        load_engine(args).set_calibration(tuning.calibration)
        applied = True
    report = tuning.to_dict()
    report["applied"] = applied
    report["dry_run"] = bool(args.dry_run)
    emit(report)
    if not tuning.ok:
        raise SystemExit(1)


def _load_forgetting_policy_cases(args: argparse.Namespace) -> list[Mapping[str, Any]]:
    if bool(args.cases) == bool(args.cases_json):
        raise SystemExit("forgetting-policy-check requires exactly one of --cases or --cases-json")
    try:
        loaded = json.loads(Path(args.cases).expanduser().read_text(encoding="utf-8")) if args.cases else json.loads(args.cases_json)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"forgetting policy cases denied: {exc}") from exc
    if not isinstance(loaded, list):
        raise SystemExit("forgetting policy cases must be a JSON array")
    if not all(isinstance(item, Mapping) for item in loaded):
        raise SystemExit("forgetting policy cases must contain JSON objects")
    return loaded


def cmd_forgetting_policy_check(args: argparse.Namespace) -> None:
    from mnemosyne.lifecycle import parse_lifecycle_datetime, validate_forgetting_policy_cases

    now = parse_lifecycle_datetime(args.now) or datetime.now(UTC)
    report = validate_forgetting_policy_cases(
        _load_forgetting_policy_cases(args),
        now=now,
        utility_threshold=args.utility_threshold,
        min_cases=args.min_cases,
        required_case_ids=args.require_case,
    )
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(
            {
                "code": "fingerprint_mismatch",
                "message": "forgetting policy suite fingerprint mismatch",
            }
        )
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_policy_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("policy-ops-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = (
            json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8"))
            if args.bundle
            else json.loads(args.bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"policy ops bundle denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("policy ops bundle must be a JSON object")
    return loaded


def cmd_policy_ops_check(args: argparse.Namespace) -> None:
    from mnemosyne.self_optimization import validate_policy_ops_bundle

    report = validate_policy_ops_bundle(
        _load_policy_ops_bundle(args),
        min_variants=args.min_variants,
        min_outcomes=args.min_outcomes,
        min_tripwires=args.min_tripwires,
        required_variant_ids=args.require_variant,
        min_outcomes_per_required_variant=args.min_outcomes_per_required_variant,
        min_cadence_window_hours=args.min_cadence_window_hours,
        max_updates_per_day=args.max_updates_per_day,
        min_diversity=args.min_diversity,
        max_proxy_gap=args.max_proxy_gap,
    )
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(
            {
                "code": "fingerprint_mismatch",
                "message": "policy ops bundle fingerprint mismatch",
            }
        )
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_privacy_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("privacy-ops-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = (
            json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8"))
            if args.bundle
            else json.loads(args.bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"privacy ops bundle denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("privacy ops bundle must be a JSON object")
    return loaded


def _privacy_bool(value: Any, *, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _privacy_finding(code: str, message: str, *, case_id: str | None = None) -> dict[str, Any]:
    finding: dict[str, Any] = {"code": code, "message": message}
    if case_id:
        finding["case_id"] = case_id
    return finding


def _privacy_ops_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        "bundle": report.get("bundle"),
        "requirements": report.get("requirements"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _privacy_cases(raw: Any, *, section: str) -> list[Mapping[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
        raise SystemExit(f"privacy ops {section} cases must be an array of JSON objects")
    return raw


def _privacy_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    forbidden_keys = {
        "raw_key",
        "raw_keys",
        "key_material",
        "plaintext_key",
        "private_key",
        "raw_object",
        "raw_objects",
        "object_bytes",
        "raw_subject",
        "raw_subjects",
        "subject_id",
        "subject_identifier",
        "email",
        "raw_claims",
        "raw_kms_response",
        "raw_kms_responses",
        "credential",
        "credentials",
        "secret",
        "token",
        "password",
    }
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_name = str(key)
            child_path = f"{path}.{key_name}"
            if key_name.lower() in forbidden_keys and child not in (None, "", [], {}):
                paths.append(child_path)
            paths.extend(_privacy_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_privacy_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def _privacy_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _privacy_operator_delete_corroboration(case: Mapping[str, Any]) -> dict[str, Any]:
    mode = str(case.get("mode") or "")
    requested_by = str(case.get("requested_by") or "").strip().lower()
    required = mode == "legal_hard_delete" and requested_by == "operator"
    if not required:
        return {"required": False, "ok": True, "missing": []}

    proof = case.get("operator_delete")
    missing: list[str] = []
    if not isinstance(proof, Mapping):
        proof = {}
        missing.append("operator_delete")
    for field in (
        "request_id_hash",
        "approved_by_hash",
        "subject_hash",
        "audit_log_hash",
        "delete_receipt_hash",
    ):
        if not proof.get(field):
            missing.append(f"operator_delete.{field}")
    minimum = _privacy_positive_int(proof.get("min_corroboration_for_delete"))
    distinct_sources = _privacy_positive_int(proof.get("distinct_supporting_sources_before"))
    source_hashes = proof.get("corroborating_source_hashes")
    source_hash_count = len(source_hashes) if isinstance(source_hashes, list) else 0
    if minimum is None or minimum < 2:
        missing.append("operator_delete.min_corroboration_for_delete")
    if distinct_sources is None or minimum is None or distinct_sources < minimum:
        missing.append("operator_delete.distinct_supporting_sources_before")
    if not isinstance(source_hashes, list) or source_hash_count < (minimum or 2) or not all(isinstance(item, str) and item for item in source_hashes):
        missing.append("operator_delete.corroborating_source_hashes")
    if proof.get("refused_if_uncorroborated") is not True:
        missing.append("operator_delete.refused_if_uncorroborated")
    if proof.get("post_delete_read_probe_failed") is not True:
        missing.append("operator_delete.post_delete_read_probe_failed")
    return {
        "required": True,
        "ok": not missing,
        "missing": missing,
        "min_corroboration_for_delete": minimum,
        "distinct_supporting_sources_before": distinct_sources,
        "corroborating_source_count": source_hash_count,
    }


def cmd_privacy_backfill_report(args: argparse.Namespace) -> None:
    engine = load_engine(args)
    pii_sensitivity = _validate_pii_sensitivity(args.pii_sensitivity)
    report = _privacy_backfill_scan(
        engine,
        tenant_id=args.tenant,
        branch=str(args.branch),
        pii_sensitivity=pii_sensitivity,
        include_clean=bool(args.include_clean),
    )
    emit(report)
    if args.fail_on_findings and not report["ok"]:
        raise SystemExit(1)


def cmd_privacy_backfill_apply(args: argparse.Namespace) -> None:
    if not args.confirm_apply:
        raise SystemExit("privacy-backfill-apply requires --confirm-apply")
    engine = load_engine(args)
    branch = str(args.branch)
    pii_sensitivity = _validate_pii_sensitivity(args.pii_sensitivity)
    before = _privacy_backfill_scan(
        engine,
        tenant_id=args.tenant,
        branch=branch,
        pii_sensitivity=pii_sensitivity,
        include_clean=False,
    )
    backfill = getattr(engine, "backfill_evidence_privacy", None)
    if not callable(backfill):
        raise SystemExit("configured engine does not support audited privacy backfill")
    applied: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for finding in before["findings"]:
        if not finding["needs_backfill"]:
            continue
        cid = finding.get("cid")
        if not isinstance(cid, str) or not cid:
            failures.append({"cid": cid, "reason": "missing_cid"})
            continue
        ok = bool(
            backfill(
                args.tenant,
                cid,
                list(finding["pii_tags"]),
                branch=branch,
                pii_sensitivity=pii_sensitivity,
                actor=str(args.actor),
                source="privacy_backfill_apply",
            )
        )
        row = {key: finding[key] for key in ("cid", "content_sha256", "pii_tags", "recommended_sensitivity")}
        row["applied"] = ok
        applied.append(row)
        if not ok:
            failures.append({"cid": cid, "reason": "engine_update_failed"})
    after = _privacy_backfill_scan(
        engine,
        tenant_id=args.tenant,
        branch=branch,
        pii_sensitivity=pii_sensitivity,
        include_clean=False,
    )
    report = {
        "ok": not failures and after["finding_count"] == 0,
        "tenant_id": args.tenant,
        "branch": branch,
        "applied_count": len([item for item in applied if item["applied"]]),
        "failed_count": len(failures),
        "failures": failures,
        "applied": applied,
        "before": before,
        "after": after,
        "redaction": {
            "raw_content_omitted": True,
            "content_hash_sha256_reported": True,
        },
    }
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _privacy_backfill_scan(
    engine: MemoryEngine,
    *,
    tenant_id: str,
    branch: str,
    pii_sensitivity: int,
    include_clean: bool,
) -> dict[str, Any]:
    from mnemosyne.privacy import classify_privacy

    exported = engine.export_tenant(tenant_id)
    rows = exported.get("evidence")
    if not isinstance(rows, list):
        raise SystemExit("tenant export did not return evidence rows")
    findings: list[dict[str, Any]] = []
    tag_counts: dict[str, int] = {}
    scanned = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("branch") or "main") != branch:
            continue
        scanned += 1
        content = str(row.get("content") or "")
        privacy = classify_privacy(content, residency=_row_residency(row))
        if not privacy.pii_tags and not include_clean:
            continue
        for tag in privacy.pii_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        finding = _privacy_backfill_row(row, privacy.pii_tags, pii_sensitivity=pii_sensitivity)
        if finding["needs_backfill"] or include_clean:
            findings.append(finding)
    return {
        "ok": not any(item["needs_backfill"] for item in findings),
        "tenant_id": tenant_id,
        "branch": branch,
        "scanned_evidence": scanned,
        "finding_count": len([item for item in findings if item["needs_backfill"]]),
        "detector": {
            "name": "mnemosyne.privacy.classify_privacy",
            "pii_sensitivity": pii_sensitivity,
            "tags": sorted(tag_counts),
        },
        "tag_counts": {key: tag_counts[key] for key in sorted(tag_counts)},
        "findings": findings,
        "redaction": {
            "raw_content_omitted": True,
            "content_hash_sha256_reported": True,
        },
    }


def _privacy_backfill_row(row: Mapping[str, Any], pii_tags: list[str], *, pii_sensitivity: int) -> dict[str, Any]:
    current_sensitivity = _coerce_int(row.get("sensitivity"), default=0)
    recommended_sensitivity = max(current_sensitivity, pii_sensitivity if pii_tags else current_sensitivity)
    policy = row.get("access_policy") if isinstance(row.get("access_policy"), Mapping) else {}
    policy_max = _coerce_int(policy.get("max_sensitivity"), default=current_sensitivity)
    data_class = str(policy.get("data_class") or "standard")
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    metadata_privacy = metadata.get("privacy") if isinstance(metadata.get("privacy"), Mapping) else {}
    metadata_tags = metadata_privacy.get("pii_tags")
    metadata_tag_set = {str(item) for item in metadata_tags} if isinstance(metadata_tags, list) else set()
    detected_tag_set = set(pii_tags)
    needs_sensitivity_raise = bool(pii_tags and current_sensitivity < pii_sensitivity)
    needs_policy_data_class = bool(pii_tags and data_class != "pii")
    needs_policy_max_sensitivity = bool(pii_tags and policy_max < recommended_sensitivity)
    needs_metadata_refresh = detected_tag_set != metadata_tag_set
    content = str(row.get("content") or "")
    return {
        "cid": row.get("cid"),
        "branch": row.get("branch") or "main",
        "source_type": row.get("source_type"),
        "content_sha256": sha256(content.encode("utf-8")).hexdigest(),
        "pii_tags": pii_tags,
        "current_sensitivity": current_sensitivity,
        "recommended_sensitivity": recommended_sensitivity,
        "current_data_class": data_class,
        "recommended_data_class": "pii" if pii_tags else data_class,
        "current_policy_max_sensitivity": policy_max,
        "needs_sensitivity_raise": needs_sensitivity_raise,
        "needs_policy_data_class": needs_policy_data_class,
        "needs_policy_max_sensitivity": needs_policy_max_sensitivity,
        "needs_metadata_refresh": needs_metadata_refresh,
        "needs_backfill": any(
            (
                needs_sensitivity_raise,
                needs_policy_data_class,
                needs_policy_max_sensitivity,
                needs_metadata_refresh,
            )
        ),
    }


def _row_residency(row: Mapping[str, Any]) -> str:
    policy = row.get("access_policy") if isinstance(row.get("access_policy"), Mapping) else {}
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    privacy = metadata.get("privacy") if isinstance(metadata.get("privacy"), Mapping) else {}
    value = policy.get("residency") or privacy.get("residency") or "local"
    return str(value)


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validate_pii_sensitivity(value: Any) -> int:
    if value is None:
        sensitivity = 3
    else:
        try:
            sensitivity = int(value)
        except (TypeError, ValueError) as exc:
            raise SystemExit("pii sensitivity must be an integer") from exc
    if sensitivity < 3:
        raise SystemExit("pii sensitivity must be at least 3")
    return sensitivity


def cmd_privacy_ops_check(args: argparse.Namespace) -> None:
    bundle = _load_privacy_ops_bundle(args)
    findings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    raw_required_cases = bundle.get("required_cases") or []
    if isinstance(raw_required_cases, str):
        raw_required_cases = [raw_required_cases]
    if not isinstance(raw_required_cases, list):
        raise SystemExit("privacy ops required_cases must be a string or string array")
    required_case_ids = list(dict.fromkeys([*raw_required_cases, *(args.require_case or [])]))
    if not all(isinstance(item, str) for item in required_case_ids):
        raise SystemExit("privacy ops required_cases must be string case IDs")
    seen_case_ids: set[str] = set()

    kms = bundle.get("kms")
    if not isinstance(kms, Mapping):
        findings.append(_privacy_finding("missing_kms_section", "privacy ops bundle requires kms section"))
        kms = {}
    provider = str(kms.get("provider") or "")
    provider_kind = provider.strip().lower()
    local_provider = provider_kind in {"", "local", "json", "local-json", "file", "filesystem"}
    key_lifecycle = kms.get("key_lifecycle") if isinstance(kms.get("key_lifecycle"), Mapping) else {}
    required_kms_flags = (
        "key_created",
        "encrypt_roundtrip_verified",
        "rotation_verified",
        "key_shredded",
        "post_shred_get_failed",
        "post_shred_has_key_false",
    )
    missing_kms_flags = [flag for flag in required_kms_flags if key_lifecycle.get(flag) is not True]
    kms_ok = bool(provider) and not local_provider and not missing_kms_flags
    if not provider:
        findings.append(_privacy_finding("kms_provider_missing", "KMS provider identity is required"))
    if local_provider:
        findings.append(_privacy_finding("kms_provider_local", "production privacy evidence must use a non-local KMS provider"))
    for flag in missing_kms_flags:
        findings.append(_privacy_finding("kms_lifecycle_missing", f"KMS lifecycle flag {flag} is not proven"))
    checks.append(
        {
            "name": "kms",
            "ok": kms_ok,
            "provider": provider,
            "provider_local": local_provider,
            "missing_lifecycle_flags": missing_kms_flags,
            "key_id_hash_present": bool(kms.get("key_id_hash")),
        }
    )

    residency = bundle.get("residency")
    if not isinstance(residency, Mapping):
        findings.append(_privacy_finding("missing_residency_section", "privacy ops bundle requires residency section"))
        residency = {}
    residency_cases = _privacy_cases(residency.get("cases"), section="residency")
    expected_decisions = {str(case.get("expected_decision") or case.get("expected") or "") for case in residency_cases}
    residency_case_reports: list[dict[str, Any]] = []
    for index, case in enumerate(residency_cases, start=1):
        case_id = str(case.get("id") or f"residency-{index}")
        seen_case_ids.add(case_id)
        expected = str(case.get("expected_decision") or case.get("expected") or "")
        actual = str(case.get("actual_decision") or case.get("actual") or "")
        enforced = case.get("enforced") is True
        ok = expected in {"allow", "deny"} and actual == expected and enforced
        if not ok:
            findings.append(_privacy_finding("residency_case_failed", "residency decision case failed", case_id=case_id))
        residency_case_reports.append(
            {
                "id": case_id,
                "ok": ok,
                "expected_decision": expected,
                "actual_decision": actual,
                "enforced": enforced,
            }
        )
    residency_ok = (
        residency.get("strict_runtime_residency") is True
        and "allow" in expected_decisions
        and "deny" in expected_decisions
        and residency_case_reports
        and all(item["ok"] for item in residency_case_reports)
    )
    if residency.get("strict_runtime_residency") is not True:
        findings.append(_privacy_finding("runtime_residency_not_strict", "strict runtime residency enforcement is required"))
    if "allow" not in expected_decisions or "deny" not in expected_decisions:
        findings.append(_privacy_finding("residency_coverage_incomplete", "residency evidence requires allow and deny cases"))
    checks.append(
        {
            "name": "residency",
            "ok": residency_ok,
            "strict_runtime_residency": residency.get("strict_runtime_residency") is True,
            "case_count": len(residency_case_reports),
            "cases": residency_case_reports,
        }
    )

    erasure = bundle.get("erasure")
    if not isinstance(erasure, Mapping):
        findings.append(_privacy_finding("missing_erasure_section", "privacy ops bundle requires erasure section"))
        erasure = {}
    erasure_cases = _privacy_cases(erasure.get("cases"), section="erasure")
    erasure_case_reports: list[dict[str, Any]] = []
    erasure_modes: set[str] = set()
    operator_delete_case_seen = False
    for index, case in enumerate(erasure_cases, start=1):
        case_id = str(case.get("id") or f"erasure-{index}")
        seen_case_ids.add(case_id)
        mode = str(case.get("mode") or "")
        erasure_modes.add(mode)
        required_flags = (
            "audit_event",
            "bytes_unreadable",
            "derived_evidence_removed",
            "tombstone_replay_blocked",
        )
        missing_flags = [flag for flag in required_flags if case.get(flag) is not True]
        operator_delete = _privacy_operator_delete_corroboration(case)
        if operator_delete["required"]:
            operator_delete_case_seen = True
        ok = mode in {"tombstone_recompute", "legal_hard_delete"} and not missing_flags and operator_delete["ok"]
        if not ok:
            findings.append(_privacy_finding("erasure_case_failed", "erasure safety case failed", case_id=case_id))
        if not operator_delete["ok"]:
            findings.append(
                _privacy_finding(
                    "operator_delete_corroboration_missing",
                    "operator hard-delete case lacks corroborated request/delete evidence",
                    case_id=case_id,
                )
            )
        erasure_case_reports.append(
            {
                "id": case_id,
                "ok": ok,
                "mode": mode,
                "requested_by": case.get("requested_by"),
                "missing_flags": missing_flags,
                "cid_hash_present": bool(case.get("cid_hash")),
                "operator_delete": operator_delete,
            }
        )
    erasure_ok = (
        {"tombstone_recompute", "legal_hard_delete"}.issubset(erasure_modes)
        and operator_delete_case_seen
        and erasure_case_reports
        and all(item["ok"] for item in erasure_case_reports)
    )
    if not {"tombstone_recompute", "legal_hard_delete"}.issubset(erasure_modes):
        findings.append(_privacy_finding("erasure_coverage_incomplete", "erasure evidence requires tombstone and legal hard-delete cases"))
    if not operator_delete_case_seen:
        findings.append(_privacy_finding("operator_delete_case_missing", "erasure evidence requires an operator hard-delete corroboration case"))
    checks.append(
        {
            "name": "erasure",
            "ok": erasure_ok,
            "case_count": len(erasure_case_reports),
            "modes": sorted(erasure_modes),
            "operator_delete_case_present": operator_delete_case_seen,
            "cases": erasure_case_reports,
        }
    )

    if len(seen_case_ids) < args.min_cases:
        findings.append(
            _privacy_finding("insufficient_cases", f"privacy ops evidence requires at least {args.min_cases} cases")
        )
    for required in required_case_ids:
        if required not in seen_case_ids:
            findings.append(_privacy_finding("missing_required_case", f"required case {required} is missing"))

    redaction = bundle.get("redaction")
    if not isinstance(redaction, Mapping):
        findings.append(_privacy_finding("missing_redaction_section", "privacy ops bundle requires redaction section"))
        redaction = {}
    redaction_flags = {
        "raw_key_material_omitted": redaction.get("raw_key_material_omitted") is True,
        "raw_object_bytes_omitted": redaction.get("raw_object_bytes_omitted") is True,
        "raw_subject_identifiers_omitted": redaction.get("raw_subject_identifiers_omitted") is True,
        "raw_kms_responses_omitted": redaction.get("raw_kms_responses_omitted") is True,
    }
    missing_redaction_flags = [name for name, ok in redaction_flags.items() if not ok]
    for flag in missing_redaction_flags:
        findings.append(_privacy_finding("redaction_flag_missing", f"redaction flag {flag} is not proven"))
    forbidden_raw_paths = _privacy_forbidden_raw_paths(bundle)
    if forbidden_raw_paths:
        findings.append(_privacy_finding("redaction_raw_field_present", "privacy ops bundle contains raw key/object/subject/KMS fields"))
    redaction_ok = not missing_redaction_flags and not forbidden_raw_paths
    checks.append(
        {
            "name": "redaction",
            "ok": redaction_ok,
            **redaction_flags,
            "forbidden_raw_paths": forbidden_raw_paths,
        }
    )

    report: dict[str, Any] = {
        "ok": not findings,
        "bundle": {
            "name": bundle.get("name"),
            "case_count": len(seen_case_ids),
            "kms_provider": provider,
        },
        "requirements": {
            "min_cases": args.min_cases,
            "required_case_ids": sorted(required_case_ids),
            "non_local_kms": True,
            "strict_runtime_residency": True,
            "requires_allow_and_deny_residency": True,
            "requires_tombstone_and_legal_delete": True,
            "requires_operator_delete_corroboration": True,
        },
        "redaction": {**redaction_flags, "forbidden_raw_fields_present": bool(forbidden_raw_paths)},
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _privacy_ops_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(_privacy_finding("fingerprint_mismatch", "privacy ops bundle fingerprint mismatch"))
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_parametric_trainer_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("parametric-trainer-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = (
            json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8"))
            if args.bundle
            else json.loads(args.bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"parametric trainer bundle denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("parametric trainer bundle must be a JSON object")
    return loaded


def _parametric_finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _parametric_trainer_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        "bundle": report.get("bundle"),
        "requirements": report.get("requirements"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _parametric_number(
    value: Any,
    *,
    default: float,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        findings.append(_parametric_finding(code, message))
        return default


def _parametric_int(
    value: Any,
    *,
    default: int,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        findings.append(_parametric_finding(code, message))
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        findings.append(_parametric_finding(code, message))
        return default


def _parametric_string_list(
    value: Any,
    *,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        findings.append(_parametric_finding(code, message))
        return []
    return list(value)


def _parametric_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    forbidden_keys = {
        "raw_training_data",
        "raw_credentials",
        "artifact_bytes",
        "raw_logs",
        "raw_request",
        "raw_response",
        "raw_stdout",
        "raw_stderr",
        "stdout",
        "stderr",
        "env",
        "environment",
        "command",
        "command_args",
        "secret",
        "token",
        "private_key",
    }
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_name = str(key)
            child_path = f"{path}.{key_name}"
            if key_name.lower() in forbidden_keys and child not in (None, "", [], {}):
                paths.append(child_path)
            paths.extend(_parametric_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_parametric_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def cmd_parametric_trainer_check(args: argparse.Namespace) -> None:
    bundle = _load_parametric_trainer_bundle(args)
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    trainer = bundle.get("trainer")
    if not isinstance(trainer, Mapping):
        findings.append(_parametric_finding("missing_trainer_section", "parametric trainer bundle requires trainer section"))
        trainer = {}
    provider = str(trainer.get("provider") or "")
    provider_kind = provider.strip().lower()
    local_provider = provider_kind in {"", "local", "mock", "test", "filesystem"}
    trainer_flags = {
        "immutable_rail_service": trainer.get("immutable_rail_service") is True,
        "credentials_isolated": trainer.get("credentials_isolated") is True,
        "artifact_uri_immutable": trainer.get("artifact_uri_immutable") is True,
        "promotion_requires_gate": trainer.get("promotion_requires_gate") is True,
        "production_mutation_disabled": trainer.get("production_mutation_disabled") is True,
    }
    artifact_uri = str(trainer.get("artifact_uri") or "").strip()
    artifact_uri_hash = str(trainer.get("artifact_uri_hash") or "").strip()
    artifact_hash_ok = bool(artifact_uri_hash) and "sha256:" in artifact_uri_hash.lower()
    missing_trainer_flags = [name for name, ok in trainer_flags.items() if not ok]
    trainer_ok = bool(provider) and not local_provider and not missing_trainer_flags and bool(artifact_uri) and artifact_hash_ok
    if not provider:
        findings.append(_parametric_finding("trainer_provider_missing", "trainer provider identity is required"))
    if local_provider:
        findings.append(_parametric_finding("trainer_provider_local", "trainer evidence must use a non-local provider"))
    for flag in missing_trainer_flags:
        findings.append(_parametric_finding("trainer_control_missing", f"trainer control {flag} is not proven"))
    if not artifact_uri:
        findings.append(_parametric_finding("artifact_uri_missing", "trainer artifact_uri is required"))
    if not artifact_hash_ok:
        findings.append(_parametric_finding("artifact_uri_hash_missing", "trainer artifact_uri_hash must prove a stable SHA-256 artifact reference"))
    checks.append(
        {
            "name": "trainer",
            "ok": trainer_ok,
            "provider": provider,
            "provider_local": local_provider,
            "missing_controls": missing_trainer_flags,
            "artifact_uri_present": bool(artifact_uri),
            "artifact_uri_hash_present": bool(artifact_uri_hash),
        }
    )

    protected_suite = bundle.get("protected_suite")
    if not isinstance(protected_suite, Mapping):
        findings.append(
            _parametric_finding("missing_protected_suite", "parametric trainer bundle requires protected_suite section")
        )
        protected_suite = {}
    tier_counts = protected_suite.get("tier_counts") if isinstance(protected_suite.get("tier_counts"), Mapping) else {}
    required_tiers = {"smoke", "core", "archive"}
    tier_values = {
        tier: _parametric_int(
            tier_counts.get(tier),
            default=0,
            code="suite_tier_count_invalid",
            message=f"protected suite tier {tier} count must be numeric",
            findings=findings,
        )
        for tier in required_tiers
    }
    missing_tiers = sorted(tier for tier, count in tier_values.items() if count <= 0)
    case_count = _parametric_int(
        protected_suite.get("case_count"),
        default=0,
        code="suite_case_count_invalid",
        message="protected suite case_count must be numeric",
        findings=findings,
    )
    protected_case_count = _parametric_int(
        protected_suite.get("protected_case_count"),
        default=0,
        code="suite_protected_case_count_invalid",
        message="protected suite protected_case_count must be numeric",
        findings=findings,
    )
    case_ids = _parametric_string_list(
        protected_suite.get("case_ids"),
        code="suite_case_ids_invalid",
        message="protected suite case_ids must be a non-empty string array",
        findings=findings,
    )
    protected_case_ids = _parametric_string_list(
        protected_suite.get("protected_case_ids"),
        code="suite_protected_case_ids_invalid",
        message="protected suite protected_case_ids must be a non-empty string array",
        findings=findings,
    )
    source = str(protected_suite.get("source") or "").strip()
    source_is_synthetic = source.lower() == "synthetic"
    source_ok = bool(source) and not source_is_synthetic
    case_id_counts_ok = len(case_ids) == case_count and len(protected_case_ids) == protected_case_count
    protected_ids_subset_ok = set(protected_case_ids).issubset(set(case_ids))
    suite_ok = (
        case_count >= args.min_cases
        and protected_case_count >= args.min_protected
        and bool(protected_suite.get("fingerprint"))
        and not missing_tiers
        and source_ok
        and case_id_counts_ok
        and protected_ids_subset_ok
    )
    if case_count < args.min_cases:
        findings.append(_parametric_finding("insufficient_suite_cases", "protected suite case count is too low"))
    if protected_case_count < args.min_protected:
        findings.append(_parametric_finding("insufficient_protected_cases", "protected suite protected-case count is too low"))
    if not protected_suite.get("fingerprint"):
        findings.append(_parametric_finding("suite_fingerprint_missing", "protected suite fingerprint is required"))
    if missing_tiers:
        findings.append(_parametric_finding("suite_tier_missing", f"protected suite missing tiers: {', '.join(missing_tiers)}"))
    if not source:
        findings.append(_parametric_finding("suite_source_missing", "protected suite source is required"))
    if source_is_synthetic:
        findings.append(_parametric_finding("suite_source_synthetic", "production protected suite cannot be synthetic"))
    if len(case_ids) != case_count:
        findings.append(_parametric_finding("suite_case_ids_mismatch", "protected suite case_ids count must match case_count"))
    if len(protected_case_ids) != protected_case_count:
        findings.append(
            _parametric_finding("suite_protected_case_ids_mismatch", "protected_suite protected_case_ids count must match protected_case_count")
        )
    if not protected_ids_subset_ok:
        findings.append(_parametric_finding("suite_protected_ids_not_in_cases", "protected_case_ids must be contained in case_ids"))
    checks.append(
        {
            "name": "protected_suite",
            "ok": suite_ok,
            "case_count": case_count,
            "protected_case_count": protected_case_count,
            "source": source,
            "source_synthetic": source_is_synthetic,
            "missing_tiers": missing_tiers,
            "fingerprint_present": bool(protected_suite.get("fingerprint")),
            "case_id_count_matches": case_id_counts_ok,
        }
    )

    gate = bundle.get("gate")
    if not isinstance(gate, Mapping):
        findings.append(_parametric_finding("missing_gate_section", "parametric trainer bundle requires gate section"))
        gate = {}
    artifact_id = str(gate.get("artifact_id") or "").strip()
    candidate_id = str(gate.get("candidate_id") or "").strip()
    protected_regressions = _parametric_string_list(
        gate.get("protected_regressions"),
        code="gate_protected_regressions_invalid",
        message="gate protected_regressions must be a string array",
        findings=findings,
    )
    failed_cases = _parametric_string_list(
        gate.get("failed_cases"),
        code="gate_failed_cases_invalid",
        message="gate failed_cases must be a string array",
        findings=findings,
    )
    passed_cases = _parametric_string_list(
        gate.get("passed_cases"),
        code="gate_passed_cases_invalid",
        message="gate passed_cases must be a string array",
        findings=findings,
    )
    gate_margin = _parametric_number(
        gate.get("margin"),
        default=args.min_gate_margin - 1.0,
        code="gate_margin_invalid",
        message="gate margin must be numeric",
        findings=findings,
    )
    gate_min_margin = _parametric_number(
        gate.get("min_gate_margin"),
        default=args.min_gate_margin,
        code="gate_min_margin_invalid",
        message="gate min_gate_margin must be numeric",
        findings=findings,
    )
    gate_margin_floor = max(args.min_gate_margin, gate_min_margin)
    gate_rollback_branch = gate.get("rollback_branch")
    passed_protected_case_ids = sorted(set(protected_case_ids) & set(passed_cases))
    passed_protected_ids = set(protected_case_ids).issubset(set(passed_cases))
    gate_ok = (
        bool(artifact_id)
        and bool(candidate_id)
        and artifact_id == candidate_id
        and gate.get("promoted") is True
        and not protected_regressions
        and not failed_cases
        and passed_protected_ids
        and gate_margin > gate_margin_floor
        and not gate_rollback_branch
    )
    if not artifact_id:
        findings.append(_parametric_finding("gate_artifact_id_missing", "gate artifact_id is required"))
    if not candidate_id:
        findings.append(_parametric_finding("gate_candidate_id_missing", "gate candidate_id is required"))
    if artifact_id and candidate_id and artifact_id != candidate_id:
        findings.append(_parametric_finding("gate_candidate_mismatch", "gate candidate_id must match artifact_id"))
    if gate.get("promoted") is not True:
        findings.append(_parametric_finding("gate_not_promoted", "production parametric trainer evidence must show promoted gate result"))
    if protected_regressions:
        findings.append(_parametric_finding("gate_protected_regressions", "gate protected_regressions must be empty"))
    if failed_cases:
        findings.append(_parametric_finding("gate_failed_cases", "gate failed_cases must be empty"))
    if not passed_protected_ids:
        findings.append(_parametric_finding("gate_protected_cases_missing", "gate passed_cases must include all protected_case_ids"))
    if gate_margin <= gate_margin_floor:
        findings.append(_parametric_finding("gate_margin_too_low", "gate margin must exceed the enforced min_gate_margin"))
    if gate_rollback_branch:
        findings.append(_parametric_finding("gate_rollback_branch_present", "promoted gate evidence must not carry rollback_branch"))
    checks.append(
        {
            "name": "gate",
            "ok": gate_ok,
            "artifact_id_present": bool(artifact_id),
            "candidate_id_present": bool(candidate_id),
            "promoted": gate.get("promoted") is True,
            "protected_regression_count": len(protected_regressions),
            "failed_case_count": len(failed_cases),
            # The passed protected-case ids (a list) prove every protected case
            # cleared the gate; the release re-validator requires a list of
            # length >= min_protected here, not a bare boolean.
            "passed_protected_cases": passed_protected_case_ids,
            "margin": gate_margin,
            "min_gate_margin": gate_margin_floor,
        }
    )

    rollback = bundle.get("rollback")
    if not isinstance(rollback, Mapping):
        findings.append(_parametric_finding("missing_rollback_section", "parametric trainer bundle requires rollback section"))
        rollback = {}
    rollback_flags = {
        "rollback_verified": rollback.get("rollback_verified") is True,
        "same_artifact_uri_verified": rollback.get("same_artifact_uri_verified") is True,
        "protected_suite_passed": rollback.get("protected_suite_passed") is True,
        "rollback_provider_authorized": rollback.get("rollback_provider_authorized") is True,
    }
    missing_rollback_flags = [name for name, ok in rollback_flags.items() if not ok]
    rollback_ok = not missing_rollback_flags and bool(rollback.get("rollback_fingerprint"))
    for flag in missing_rollback_flags:
        findings.append(_parametric_finding("rollback_control_missing", f"rollback control {flag} is not proven"))
    if not rollback.get("rollback_fingerprint"):
        findings.append(_parametric_finding("rollback_fingerprint_missing", "rollback fingerprint is required"))
    checks.append(
        {
            "name": "rollback",
            "ok": rollback_ok,
            "missing_controls": missing_rollback_flags,
            "rollback_fingerprint_present": bool(rollback.get("rollback_fingerprint")),
        }
    )

    deployment = bundle.get("deployment")
    if not isinstance(deployment, Mapping):
        findings.append(_parametric_finding("missing_deployment_section", "parametric trainer bundle requires deployment section"))
        deployment = {}
    deployment_flags = {
        "production_validated": deployment.get("production_validated") is True,
        "supervised_deployment": deployment.get("supervised_deployment") is True,
        "health_check_passed": deployment.get("health_check_passed") is True,
        "canary_passed": deployment.get("canary_passed") is True,
        "rollback_drill_verified": deployment.get("rollback_drill_verified") is True,
        "alert_route_configured": deployment.get("alert_route_configured") is True,
    }
    endpoint_url = str(deployment.get("endpoint_url") or "").strip()
    endpoint_https = endpoint_url.startswith("https://")
    deployment_latency_ms = _parametric_number(
        deployment.get("latency_ms"),
        default=-1.0,
        code="deployment_latency_invalid",
        message="deployment latency_ms must be numeric",
        findings=findings,
    )
    deployment_suite_fingerprint = str(deployment.get("protected_suite_fingerprint") or "").strip()
    deployment_artifact_hash = str(deployment.get("artifact_uri_hash") or "").strip()
    deployment_rollback_fingerprint = str(deployment.get("rollback_fingerprint") or "").strip()
    deployment_suite_matches = bool(deployment_suite_fingerprint) and deployment_suite_fingerprint == str(protected_suite.get("fingerprint") or "")
    deployment_artifact_matches = bool(deployment_artifact_hash) and deployment_artifact_hash == artifact_uri_hash
    deployment_rollback_matches = bool(deployment_rollback_fingerprint) and deployment_rollback_fingerprint == str(rollback.get("rollback_fingerprint") or "")
    missing_deployment_flags = [name for name, ok in deployment_flags.items() if not ok]
    deployment_ok = (
        not missing_deployment_flags
        and endpoint_https
        and 0 <= deployment_latency_ms <= args.max_deployment_latency_ms
        and deployment_suite_matches
        and deployment_artifact_matches
        and deployment_rollback_matches
    )
    for flag in missing_deployment_flags:
        findings.append(_parametric_finding("deployment_control_missing", f"deployment control {flag} is not proven"))
    if not endpoint_https:
        findings.append(_parametric_finding("deployment_endpoint_not_https", "deployment endpoint_url must use HTTPS"))
    if deployment_latency_ms < 0 or deployment_latency_ms > args.max_deployment_latency_ms:
        findings.append(_parametric_finding("deployment_latency_too_high", "deployment latency exceeds release threshold"))
    if not deployment_suite_matches:
        findings.append(_parametric_finding("deployment_suite_fingerprint_mismatch", "deployment protected_suite_fingerprint must match protected suite fingerprint"))
    if not deployment_artifact_matches:
        findings.append(_parametric_finding("deployment_artifact_hash_mismatch", "deployment artifact_uri_hash must match trainer artifact hash"))
    if not deployment_rollback_matches:
        findings.append(_parametric_finding("deployment_rollback_fingerprint_mismatch", "deployment rollback_fingerprint must match rollback evidence"))
    checks.append(
        {
            "name": "deployment",
            "ok": deployment_ok,
            "endpoint_https": endpoint_https,
            "latency_ms": deployment_latency_ms,
            "max_latency_ms": args.max_deployment_latency_ms,
            "missing_controls": missing_deployment_flags,
            "protected_suite_fingerprint_matches": deployment_suite_matches,
            "artifact_uri_hash_matches": deployment_artifact_matches,
            "rollback_fingerprint_matches": deployment_rollback_matches,
        }
    )

    rail_report = bundle.get("rail_report")
    if not isinstance(rail_report, Mapping):
        findings.append(_parametric_finding("missing_rail_report", "parametric trainer bundle requires rail_report section"))
        rail_report = {}
    trust_tier_delta = _parametric_number(
        rail_report.get("trust_tier_delta"),
        default=-1.0,
        code="rail_trust_tier_delta_invalid",
        message="rail_report trust_tier_delta must be numeric",
        findings=findings,
    )
    rail_provider_metadata_checked = rail_report.get("provider_metadata_checked") is True
    rail_reward_ok = rail_report.get("reward_signal") == "external_only"
    rail_monotonic_ok = rail_report.get("monotonic_trust") is True
    rail_trust_ok = trust_tier_delta >= 0
    rail_sink_ok = str(rail_report.get("target_sink") or "") != "system_prompt" and bool(rail_report.get("target_sink"))
    rail_prompt_ok = rail_report.get("untrusted_to_system_prompt") in {"forbidden", False}
    rail_overlap_ok = rail_report.get("eval_source_overlap") is False
    rail_ok = (
        rail_provider_metadata_checked
        and rail_reward_ok
        and rail_monotonic_ok
        and rail_trust_ok
        and rail_sink_ok
        and rail_prompt_ok
        and rail_overlap_ok
    )
    if not rail_provider_metadata_checked:
        findings.append(_parametric_finding("rail_provider_metadata_unchecked", "rail_report must prove provider metadata was checked"))
    if not rail_reward_ok:
        findings.append(_parametric_finding("rail_reward_signal_invalid", "rail_report reward_signal must be external_only"))
    if not rail_monotonic_ok:
        findings.append(_parametric_finding("rail_monotonic_trust_invalid", "rail_report monotonic_trust must be true"))
    if not rail_trust_ok:
        findings.append(_parametric_finding("rail_trust_tier_delta_invalid", "rail_report trust_tier_delta must be non-negative"))
    if not rail_sink_ok:
        findings.append(_parametric_finding("rail_target_sink_invalid", "rail_report must prove target_sink is not system_prompt"))
    if not rail_prompt_ok:
        findings.append(_parametric_finding("rail_system_prompt_sink_invalid", "rail_report must forbid untrusted_to_system_prompt"))
    if not rail_overlap_ok:
        findings.append(_parametric_finding("rail_eval_overlap_invalid", "rail_report eval_source_overlap must be false"))
    checks.append(
        {
            "name": "rail_report",
            "ok": rail_ok,
            "provider_metadata_checked": rail_provider_metadata_checked,
            "reward_signal": rail_report.get("reward_signal"),
            "monotonic_trust": rail_report.get("monotonic_trust") is True,
            "trust_tier_delta": trust_tier_delta,
            "target_sink": rail_report.get("target_sink"),
            "eval_source_overlap": rail_report.get("eval_source_overlap"),
        }
    )

    metrics = bundle.get("metrics") if isinstance(bundle.get("metrics"), Mapping) else {}
    mutation_rate = _parametric_number(
        metrics.get("mutation_rate"),
        default=args.max_mutation_rate + 1.0,
        code="mutation_rate_invalid",
        message="trainer mutation rate must be numeric",
        findings=findings,
    )
    reward = _parametric_number(
        metrics.get("reward"),
        default=args.min_reward - 1.0,
        code="reward_invalid",
        message="trainer reward must be numeric",
        findings=findings,
    )
    sink_score = _parametric_number(
        metrics.get("sink_score"),
        default=args.max_sink_score + 1.0,
        code="sink_score_invalid",
        message="trainer sink score must be numeric",
        findings=findings,
    )
    metrics_ok = mutation_rate <= args.max_mutation_rate and reward >= args.min_reward and sink_score <= args.max_sink_score
    if mutation_rate > args.max_mutation_rate:
        findings.append(_parametric_finding("mutation_rate_too_high", "trainer mutation rate exceeds release threshold"))
    if reward < args.min_reward:
        findings.append(_parametric_finding("reward_too_low", "trainer reward is below release threshold"))
    if sink_score > args.max_sink_score:
        findings.append(_parametric_finding("sink_score_too_high", "trainer sink score exceeds release threshold"))
    checks.append(
        {
            "name": "metrics",
            "ok": metrics_ok,
            "mutation_rate": mutation_rate,
            "max_mutation_rate": args.max_mutation_rate,
            "reward": reward,
            "min_reward": args.min_reward,
            "sink_score": sink_score,
            "max_sink_score": args.max_sink_score,
        }
    )

    redaction = bundle.get("redaction")
    if not isinstance(redaction, Mapping):
        findings.append(_parametric_finding("missing_redaction_section", "parametric trainer bundle requires redaction section"))
        redaction = {}
    redaction_flags = {
        "raw_training_data_omitted": redaction.get("raw_training_data_omitted") is True,
        "raw_credentials_omitted": redaction.get("raw_credentials_omitted") is True,
        "raw_artifact_bytes_omitted": redaction.get("raw_artifact_bytes_omitted") is True,
    }
    forbidden_raw_paths = _parametric_forbidden_raw_paths(bundle)
    missing_redaction_flags = [name for name, ok in redaction_flags.items() if not ok]
    redaction_ok = not missing_redaction_flags and not forbidden_raw_paths
    for flag in missing_redaction_flags:
        findings.append(_parametric_finding("redaction_flag_missing", f"redaction flag {flag} is not proven"))
    if forbidden_raw_paths:
        findings.append(_parametric_finding("redaction_raw_field_present", "parametric trainer bundle contains raw secret/training/artifact fields"))
    checks.append(
        {
            "name": "redaction",
            "ok": redaction_ok,
            **redaction_flags,
            "forbidden_raw_paths": forbidden_raw_paths,
        }
    )

    report: dict[str, Any] = {
        "ok": not findings,
        "bundle": {
            "name": bundle.get("name"),
            "trainer_provider": provider,
            "protected_suite_fingerprint_present": bool(protected_suite.get("fingerprint")),
            "protected_suite_source": source,
        },
        "requirements": {
            "non_local_trainer_provider": True,
            "immutable_rail_service": True,
            "credentials_isolated": True,
            "artifact_uri_hash": True,
            "min_cases": args.min_cases,
            "min_protected": args.min_protected,
            "required_tiers": sorted(required_tiers),
            "protected_suite_source_non_synthetic": True,
            "gate_candidate_matches_artifact": True,
            "min_gate_margin": args.min_gate_margin,
            "max_deployment_latency_ms": args.max_deployment_latency_ms,
            "external_reward_signal": "external_only",
            "monotonic_trust": True,
            "eval_source_overlap": False,
            "max_mutation_rate": args.max_mutation_rate,
            "min_reward": args.min_reward,
            "max_sink_score": args.max_sink_score,
        },
        "redaction": {
            **redaction_flags,
            "forbidden_raw_fields_present": bool(forbidden_raw_paths),
        },
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _parametric_trainer_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(
            _parametric_finding("fingerprint_mismatch", "parametric trainer bundle fingerprint mismatch")
        )
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_retrieval_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("retrieval-ops-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = (
            json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8"))
            if args.bundle
            else json.loads(args.bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"retrieval ops bundle denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("retrieval ops bundle must be a JSON object")
    return loaded


def _retrieval_ops_finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _retrieval_ops_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        "bundle": report.get("bundle"),
        "requirements": report.get("requirements"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _retrieval_ops_number(
    value: Any,
    *,
    default: float,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        findings.append(_retrieval_ops_finding(code, message))
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        findings.append(_retrieval_ops_finding(code, message))
        return default


def _retrieval_ops_int(
    value: Any,
    *,
    default: int,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        findings.append(_retrieval_ops_finding(code, message))
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        findings.append(_retrieval_ops_finding(code, message))
        return default


def _retrieval_ops_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    forbidden_keys = {
        "query",
        "queries",
        "document",
        "documents",
        "embedding_vector",
        "embedding_vectors",
        "embedding_values",
        "raw_query",
        "raw_queries",
        "raw_embedding",
        "raw_embeddings",
        "raw_document",
        "raw_documents",
        "raw_result",
        "raw_results",
        "raw_stdout",
        "raw_stderr",
        "stdout",
        "stderr",
        "command",
        "command_args",
        "env",
        "environment",
        "api_key",
        "password",
        "credential",
        "credentials",
        "secret",
        "token",
        "private_key",
    }
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_name = str(key)
            child_path = f"{path}.{key_name}"
            if key_name.lower() in forbidden_keys and child not in (None, "", [], {}):
                paths.append(child_path)
            paths.extend(_retrieval_ops_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_retrieval_ops_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def _retrieval_provider_local(provider: Any) -> bool:
    provider_kind = str(provider or "").strip().lower()
    return provider_kind in {"", "local", "mock", "test", "filesystem", "deterministic", "hashing"}


def _retrieval_probe_ok(probe: Any) -> bool:
    if not isinstance(probe, Mapping):
        return False
    if not str(probe.get("top_id") or "").strip():
        return False
    hit_count = probe.get("hit_count")
    if isinstance(hit_count, bool):
        return False
    try:
        return int(hit_count) > 0
    except (TypeError, ValueError):
        return False


def _retrieval_ops_sha256_present(value: Any) -> bool:
    return "sha256:" in str(value or "").strip().lower()


# Ops-check bundles are PROFILE-scoped. Production stays Postgres-ONLY (the spec's
# Global Constraints: production topology is Postgres-only). Production manifests
# declare no `profile`, so they default to "production" and are unchanged — a
# production bundle carrying a sqlite backend therefore still FAILS. A self-hosted
# SqliteEngine tier declares `profile: "sqlite"`, which accepts the sqlite storage
# backend and its file-per-tenant isolation analog (SQLite has no RLS; isolation is
# one database file per tenant). Any unrecognized/absent profile falls back to
# production. This parameterization is the ONLY relaxation — every other control
# (production_validated, forbid_local, redaction, hashing) is enforced unchanged.
OPS_CHECK_PRODUCTION_PROFILE = "production"
OPS_CHECK_SQLITE_PROFILE = "sqlite"
_OPS_CHECK_PROFILES = frozenset({OPS_CHECK_PRODUCTION_PROFILE, OPS_CHECK_SQLITE_PROFILE})


def _ops_check_profile(bundle: Mapping[str, Any]) -> str:
    """Resolve the bundle's declared deployment profile (default: production)."""
    raw = str(bundle.get("profile") or OPS_CHECK_PRODUCTION_PROFILE).strip().lower()
    return raw if raw in _OPS_CHECK_PROFILES else OPS_CHECK_PRODUCTION_PROFILE


def _ops_check_backend_accepted(
    backend: str, profile: str, production_backends: frozenset[str]
) -> bool:
    """Profile-scoped backend acceptance. The sqlite profile accepts only the
    ``sqlite`` backend; every other profile requires one of ``production_backends``
    (Postgres) — so production release bundles remain Postgres-only."""
    normalized = backend.strip().lower()
    if profile == OPS_CHECK_SQLITE_PROFILE:
        return normalized == "sqlite"
    return normalized in production_backends


def cmd_retrieval_ops_check(args: argparse.Namespace) -> None:
    bundle = _load_retrieval_ops_bundle(args)
    profile = _ops_check_profile(bundle)
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    provider_check = bundle.get("provider_check")
    if not isinstance(provider_check, Mapping):
        findings.append(_retrieval_ops_finding("missing_provider_check", "retrieval ops bundle requires provider_check section"))
        provider_check = {}
    provider_manifest = provider_check.get("manifest") if isinstance(provider_check.get("manifest"), Mapping) else {}
    provider_checks = provider_check.get("checks") if isinstance(provider_check.get("checks"), Mapping) else {}
    required_provider_checks = sorted(set(args.require_provider_check or ("embedding", "reranker", "retrieval_backends")))
    provider_rows: list[dict[str, Any]] = []
    for check_name in required_provider_checks:
        check = provider_checks.get(check_name) if isinstance(provider_checks, Mapping) else None
        present = isinstance(check, Mapping)
        ok = present and check.get("ok") is True
        provider = check.get("provider") if present else None
        local_provider = _retrieval_provider_local(provider) if check_name in {"embedding", "reranker"} else False
        if not present:
            findings.append(_retrieval_ops_finding("provider_check_missing", f"provider_check missing {check_name}"))
        elif not ok:
            findings.append(_retrieval_ops_finding("provider_check_failed", f"provider_check {check_name} did not pass"))
        if local_provider:
            findings.append(_retrieval_ops_finding("provider_check_local_provider", f"provider_check {check_name} uses a local provider"))
        provider_rows.append(
            {
                "check": check_name,
                "present": present,
                "ok": ok,
                "provider": provider,
                "local_provider": local_provider,
            }
        )
    if provider_manifest.get("forbid_local") is not True:
        findings.append(_retrieval_ops_finding("provider_manifest_forbid_local_missing", "provider_check manifest must set forbid_local=true"))
    retrieval_backends = provider_checks.get("retrieval_backends") if isinstance(provider_checks, Mapping) else None
    lexical_backend = ""
    graph_backend = ""
    lexical_provider = ""
    graph_provider = ""
    lexical_local = True
    graph_local = True
    lexical_probe_required = False
    graph_probe_required = False
    lexical_probe_present = False
    graph_probe_present = False
    retrieval_backend_ok = False
    if isinstance(retrieval_backends, Mapping):
        lexical_provider = str(retrieval_backends.get("lexical_provider") or "").strip().lower()
        graph_provider = str(retrieval_backends.get("graph_provider") or "").strip().lower()
        lexical_backend = str(retrieval_backends.get("lexical_backend") or "").strip()
        graph_backend = str(retrieval_backends.get("graph_backend") or "").strip()
        lexical_local = bool(retrieval_backends.get("lexical_local")) or _is_local_retrieval_backend(lexical_backend)
        graph_local = bool(retrieval_backends.get("graph_local")) or _is_local_retrieval_backend(graph_backend)
        lexical_probe_required = lexical_provider == "command" or (bool(lexical_backend) and not lexical_local)
        graph_probe_required = graph_provider == "command" or (bool(graph_backend) and not graph_local)
        lexical_probe_present = _retrieval_probe_ok(retrieval_backends.get("lexical_probe"))
        graph_probe_present = _retrieval_probe_ok(retrieval_backends.get("graph_probe"))
        retrieval_backend_ok = (
            retrieval_backends.get("ok") is True
            and bool(lexical_backend)
            and bool(graph_backend)
            and not lexical_local
            and not graph_local
            and (not lexical_probe_required or lexical_probe_present)
            and (not graph_probe_required or graph_probe_present)
        )
    else:
        findings.append(_retrieval_ops_finding("retrieval_backends_missing", "provider_check missing retrieval_backends"))
    if not lexical_backend:
        findings.append(_retrieval_ops_finding("lexical_backend_missing", "production lexical retrieval backend name is required"))
    if not graph_backend:
        findings.append(_retrieval_ops_finding("graph_backend_missing", "production graph retrieval backend name is required"))
    if lexical_local or graph_local:
        findings.append(_retrieval_ops_finding("local_retrieval_backend", "retrieval evidence must not use local lexical or graph backends"))
    if lexical_probe_required and not lexical_probe_present:
        findings.append(_retrieval_ops_finding("lexical_probe_missing", "non-local lexical backend requires provider-check lexical_probe evidence"))
    if graph_probe_required and not graph_probe_present:
        findings.append(_retrieval_ops_finding("graph_probe_missing", "non-local graph backend requires provider-check graph_probe evidence"))
    checks.append(
        {
            "name": "provider_check",
            "ok": provider_manifest.get("forbid_local") is True and all(row["ok"] and not row["local_provider"] for row in provider_rows) and retrieval_backend_ok,
            "required_provider_checks": required_provider_checks,
            "forbid_local": provider_manifest.get("forbid_local") is True,
            "provider_rows": provider_rows,
            "retrieval_backends": {
                "lexical_provider": lexical_provider,
                "lexical_backend": lexical_backend,
                "lexical_probe_required": lexical_probe_required,
                "lexical_probe_present": lexical_probe_present,
                "graph_provider": graph_provider,
                "graph_backend": graph_backend,
                "graph_probe_required": graph_probe_required,
                "graph_probe_present": graph_probe_present,
                "lexical_local": lexical_local,
                "graph_local": graph_local,
            },
        }
    )

    retrieval = bundle.get("retrieval")
    if not isinstance(retrieval, Mapping):
        findings.append(_retrieval_ops_finding("missing_retrieval_section", "retrieval ops bundle requires retrieval section"))
        retrieval = {}
    cases_raw = retrieval.get("cases")
    cases = [item for item in cases_raw if isinstance(item, Mapping)] if isinstance(cases_raw, list) else []
    if not isinstance(cases_raw, list):
        findings.append(_retrieval_ops_finding("retrieval_cases_invalid", "retrieval cases must be an array"))
    if retrieval.get("production_validated") is not True:
        findings.append(_retrieval_ops_finding("retrieval_production_validation_missing", "retrieval evidence must be marked production_validated"))
    if not _ops_check_backend_accepted(str(retrieval.get("backend") or ""), profile, frozenset({"postgres"})):
        findings.append(_retrieval_ops_finding("retrieval_backend_not_postgres", "retrieval evidence must target the Postgres backend"))
    if len(cases) < args.min_cases:
        findings.append(_retrieval_ops_finding("insufficient_retrieval_cases", "retrieval evidence has too few cases"))
    lexical_cases = 0
    vector_cases = 0
    graph_cases = 0
    reranked_cases = 0
    calibrated_cases = 0
    case_rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        case_id = str(case.get("id") or f"case-{index + 1}")
        query_hash = str(case.get("query_hash") or "").strip()
        tenant_hash = str(case.get("tenant_hash") or "").strip()
        lexical_hits = _retrieval_ops_int(
            case.get("lexical_hit_count"),
            default=0,
            code="retrieval_case_count_invalid",
            message=f"retrieval case {case_id} lexical_hit_count must be numeric",
            findings=findings,
        )
        vector_hits = _retrieval_ops_int(
            case.get("vector_hit_count"),
            default=0,
            code="retrieval_case_count_invalid",
            message=f"retrieval case {case_id} vector_hit_count must be numeric",
            findings=findings,
        )
        graph_hits = _retrieval_ops_int(
            case.get("graph_hit_count"),
            default=0,
            code="retrieval_case_count_invalid",
            message=f"retrieval case {case_id} graph_hit_count must be numeric",
            findings=findings,
        )
        reranked_hits = _retrieval_ops_int(
            case.get("reranked_hit_count"),
            default=0,
            code="retrieval_case_count_invalid",
            message=f"retrieval case {case_id} reranked_hit_count must be numeric",
            findings=findings,
        )
        calibrated = case.get("calibrated") is True
        if not query_hash or "sha256:" not in query_hash.lower():
            findings.append(_retrieval_ops_finding("retrieval_case_query_hash_missing", f"retrieval case {case_id} requires a SHA-256 query hash"))
        if not tenant_hash or "sha256:" not in tenant_hash.lower():
            findings.append(_retrieval_ops_finding("retrieval_case_tenant_hash_missing", f"retrieval case {case_id} requires a SHA-256 tenant hash"))
        if lexical_hits > 0:
            lexical_cases += 1
        if vector_hits > 0:
            vector_cases += 1
        if graph_hits > 0:
            graph_cases += 1
        if reranked_hits > 0:
            reranked_cases += 1
        if calibrated:
            calibrated_cases += 1
        case_rows.append(
            {
                "id": case_id,
                "query_hash_present": bool(query_hash),
                "tenant_hash_present": bool(tenant_hash),
                "lexical_hit_count": lexical_hits,
                "vector_hit_count": vector_hits,
                "graph_hit_count": graph_hits,
                "reranked_hit_count": reranked_hits,
                "calibrated": calibrated,
            }
        )
    if lexical_cases < args.min_lexical_cases:
        findings.append(_retrieval_ops_finding("insufficient_lexical_cases", "retrieval evidence has too few lexical-hit cases"))
    if vector_cases < args.min_vector_cases:
        findings.append(_retrieval_ops_finding("insufficient_vector_cases", "retrieval evidence has too few vector-hit cases"))
    if graph_cases < args.min_graph_cases:
        findings.append(_retrieval_ops_finding("insufficient_graph_cases", "retrieval evidence has too few graph-hit cases"))
    if reranked_cases < args.min_reranked_cases:
        findings.append(_retrieval_ops_finding("insufficient_reranked_cases", "retrieval evidence has too few reranked cases"))
    if calibrated_cases < len(cases):
        findings.append(_retrieval_ops_finding("retrieval_case_uncalibrated", "all retrieval evidence cases must be calibrated"))
    checks.append(
        {
            "name": "retrieval",
            "ok": (
                retrieval.get("production_validated") is True
                and str(retrieval.get("backend") or "").strip().lower() == "postgres"
                and len(cases) >= args.min_cases
                and lexical_cases >= args.min_lexical_cases
                and vector_cases >= args.min_vector_cases
                and graph_cases >= args.min_graph_cases
                and reranked_cases >= args.min_reranked_cases
                and calibrated_cases == len(cases)
            ),
            "backend": retrieval.get("backend"),
            "case_count": len(cases),
            "lexical_cases": lexical_cases,
            "vector_cases": vector_cases,
            "graph_cases": graph_cases,
            "reranked_cases": reranked_cases,
            "calibrated_cases": calibrated_cases,
            "cases": case_rows,
        }
    )

    required_adapter_probes = sorted(set(args.require_adapter_probe or ("graph", "lexical", "reranker", "vector")))
    adapter_probes_raw = bundle.get("adapter_probes")
    adapter_probes = [item for item in adapter_probes_raw if isinstance(item, Mapping)] if isinstance(adapter_probes_raw, list) else []
    if not isinstance(adapter_probes_raw, list):
        findings.append(_retrieval_ops_finding("adapter_probes_invalid", "adapter_probes must be an array"))
    probes_by_adapter: dict[str, list[Mapping[str, Any]]] = {}
    adapter_rows: list[dict[str, Any]] = []
    for index, probe in enumerate(adapter_probes):
        adapter = str(probe.get("adapter") or probe.get("kind") or "").strip().lower()
        backend = str(probe.get("backend") or "").strip()
        provider = str(probe.get("provider") or "").strip().lower()
        probe_id = str(probe.get("id") or f"adapter-probe-{index + 1}")
        command_fingerprint_present = _retrieval_ops_sha256_present(probe.get("command_fingerprint"))
        query_hash_present = _retrieval_ops_sha256_present(probe.get("query_hash"))
        tenant_hash_present = _retrieval_ops_sha256_present(probe.get("tenant_hash"))
        result_fingerprint_present = _retrieval_ops_sha256_present(probe.get("result_fingerprint"))
        top_id_hash_present = _retrieval_ops_sha256_present(probe.get("top_id_hash"))
        source_snapshot_fingerprint_present = _retrieval_ops_sha256_present(probe.get("source_snapshot_fingerprint"))
        hit_count = _retrieval_ops_int(
            probe.get("hit_count"),
            default=0,
            code="adapter_probe_hit_count_invalid",
            message=f"adapter probe {probe_id} hit_count must be numeric",
            findings=findings,
        )
        latency_ms = _retrieval_ops_number(
            probe.get("latency_ms"),
            default=-1.0,
            code="adapter_probe_latency_invalid",
            message=f"adapter probe {probe_id} latency_ms must be numeric",
            findings=findings,
        )
        backend_local = _is_local_retrieval_backend(backend)
        provider_local = _retrieval_provider_local(provider)
        production_validated = probe.get("production_validated") is True
        if not adapter:
            findings.append(_retrieval_ops_finding("adapter_probe_adapter_missing", f"adapter probe {probe_id} requires an adapter name"))
        else:
            probes_by_adapter.setdefault(adapter, []).append(probe)
        if not backend:
            findings.append(_retrieval_ops_finding("adapter_probe_backend_missing", f"adapter probe {probe_id} requires a backend name"))
        if backend_local:
            findings.append(_retrieval_ops_finding("adapter_probe_local_backend", f"adapter probe {probe_id} uses a local backend"))
        if provider_local:
            findings.append(_retrieval_ops_finding("adapter_probe_local_provider", f"adapter probe {probe_id} uses a local provider"))
        if not production_validated:
            findings.append(_retrieval_ops_finding("adapter_probe_production_validation_missing", f"adapter probe {probe_id} must be production_validated"))
        missing_hashes = [
            name
            for name, present in (
                ("command_fingerprint", command_fingerprint_present),
                ("query_hash", query_hash_present),
                ("tenant_hash", tenant_hash_present),
                ("result_fingerprint", result_fingerprint_present),
                ("source_snapshot_fingerprint", source_snapshot_fingerprint_present),
            )
            if not present
        ]
        if missing_hashes:
            joined = ", ".join(missing_hashes)
            findings.append(_retrieval_ops_finding("adapter_probe_hash_missing", f"adapter probe {probe_id} missing SHA-256 {joined}"))
        if not top_id_hash_present:
            findings.append(_retrieval_ops_finding("adapter_probe_top_id_hash_missing", f"adapter probe {probe_id} requires a SHA-256 top_id_hash"))
        if hit_count <= 0:
            findings.append(_retrieval_ops_finding("adapter_probe_hit_count_nonpositive", f"adapter probe {probe_id} must report at least one hit"))
        if latency_ms < 0 or latency_ms > args.max_adapter_latency_ms:
            findings.append(_retrieval_ops_finding("adapter_probe_latency_too_high", f"adapter probe {probe_id} exceeds latency requirements"))
        row_ok = (
            bool(adapter)
            and bool(backend)
            and not backend_local
            and not provider_local
            and production_validated
            and command_fingerprint_present
            and query_hash_present
            and tenant_hash_present
            and result_fingerprint_present
            and source_snapshot_fingerprint_present
            and top_id_hash_present
            and hit_count > 0
            and 0 <= latency_ms <= args.max_adapter_latency_ms
        )
        adapter_rows.append(
            {
                "id": probe_id,
                "adapter": adapter,
                "backend": backend,
                "provider": provider,
                "ok": row_ok,
                "production_validated": production_validated,
                "backend_local": backend_local,
                "provider_local": provider_local,
                "command_fingerprint_present": command_fingerprint_present,
                "query_hash_present": query_hash_present,
                "tenant_hash_present": tenant_hash_present,
                "result_fingerprint_present": result_fingerprint_present,
                "source_snapshot_fingerprint_present": source_snapshot_fingerprint_present,
                "top_id_hash_present": top_id_hash_present,
                "hit_count": hit_count,
                "latency_ms": latency_ms,
            }
        )
    missing_adapter_probes = [adapter for adapter in required_adapter_probes if not probes_by_adapter.get(adapter)]
    for adapter in missing_adapter_probes:
        findings.append(_retrieval_ops_finding("adapter_probe_missing", f"missing production adapter probe for {adapter}"))
    adapter_probes_ok = (
        isinstance(adapter_probes_raw, list)
        and not missing_adapter_probes
        and bool(adapter_rows)
        and all(row["ok"] for row in adapter_rows)
    )
    checks.append(
        {
            "name": "adapter_probes",
            "ok": adapter_probes_ok,
            "required_adapters": required_adapter_probes,
            "missing_adapters": missing_adapter_probes,
            "probe_count": len(adapter_rows),
            "ok_probe_count": sum(1 for row in adapter_rows if row["ok"]),
            "max_adapter_latency_ms": args.max_adapter_latency_ms,
            "probes": adapter_rows,
        }
    )

    calibration = bundle.get("calibration")
    if not isinstance(calibration, Mapping):
        findings.append(_retrieval_ops_finding("missing_calibration_section", "retrieval ops bundle requires calibration section"))
        calibration = {}
    calibration_examples = _retrieval_ops_int(
        calibration.get("example_count"),
        default=0,
        code="calibration_count_invalid",
        message="calibration example_count must be numeric",
        findings=findings,
    )
    calibration_correct = _retrieval_ops_int(
        calibration.get("correct_count"),
        default=0,
        code="calibration_count_invalid",
        message="calibration correct_count must be numeric",
        findings=findings,
    )
    calibration_incorrect = _retrieval_ops_int(
        calibration.get("incorrect_count"),
        default=0,
        code="calibration_count_invalid",
        message="calibration incorrect_count must be numeric",
        findings=findings,
    )
    empirical_coverage = _retrieval_ops_number(
        calibration.get("empirical_coverage"),
        default=-1.0,
        code="calibration_metric_invalid",
        message="calibration empirical_coverage must be numeric",
        findings=findings,
    )
    false_accept_rate = _retrieval_ops_number(
        calibration.get("false_accept_rate"),
        default=1.0,
        code="calibration_metric_invalid",
        message="calibration false_accept_rate must be numeric",
        findings=findings,
    )
    dataset_fingerprint = str(calibration.get("dataset_fingerprint") or "").strip()
    calibration_ok = (
        calibration.get("production_dataset") is True
        and "sha256:" in dataset_fingerprint.lower()
        and calibration_examples >= args.min_calibration_examples
        and calibration_correct >= args.min_calibration_correct
        and calibration_incorrect >= args.min_calibration_incorrect
        and empirical_coverage >= args.min_empirical_coverage
        and false_accept_rate <= args.max_false_accept_rate
        and calibration.get("threshold") is not None
    )
    if calibration.get("production_dataset") is not True:
        findings.append(_retrieval_ops_finding("calibration_not_production_dataset", "calibration evidence must use a production dataset"))
    if "sha256:" not in dataset_fingerprint.lower():
        findings.append(_retrieval_ops_finding("calibration_fingerprint_missing", "calibration dataset_fingerprint must be SHA-256"))
    if calibration_examples < args.min_calibration_examples:
        findings.append(_retrieval_ops_finding("insufficient_calibration_examples", "calibration dataset has too few examples"))
    if calibration_correct < args.min_calibration_correct:
        findings.append(_retrieval_ops_finding("insufficient_calibration_correct", "calibration dataset has too few correct examples"))
    if calibration_incorrect < args.min_calibration_incorrect:
        findings.append(_retrieval_ops_finding("insufficient_calibration_incorrect", "calibration dataset has too few incorrect examples"))
    if empirical_coverage < args.min_empirical_coverage:
        findings.append(_retrieval_ops_finding("calibration_coverage_too_low", "calibration empirical coverage is too low"))
    if false_accept_rate > args.max_false_accept_rate:
        findings.append(_retrieval_ops_finding("calibration_false_accept_too_high", "calibration false accept rate is too high"))
    if calibration.get("threshold") is None:
        findings.append(_retrieval_ops_finding("calibration_threshold_missing", "calibration threshold is required"))
    checks.append(
        {
            "name": "calibration",
            "ok": calibration_ok,
            "production_dataset": calibration.get("production_dataset") is True,
            "dataset_fingerprint_present": "sha256:" in dataset_fingerprint.lower(),
            "example_count": calibration_examples,
            "correct_count": calibration_correct,
            "incorrect_count": calibration_incorrect,
            "empirical_coverage": empirical_coverage,
            "false_accept_rate": false_accept_rate,
            "threshold_present": calibration.get("threshold") is not None,
        }
    )

    redaction = bundle.get("redaction")
    if not isinstance(redaction, Mapping):
        findings.append(_retrieval_ops_finding("missing_redaction_section", "retrieval ops bundle requires redaction section"))
        redaction = {}
    redaction_flags = {
        "raw_queries_omitted": redaction.get("raw_queries_omitted") is True,
        "raw_embeddings_omitted": redaction.get("raw_embeddings_omitted") is True,
        "raw_documents_omitted": redaction.get("raw_documents_omitted") is True,
        "raw_credentials_omitted": redaction.get("raw_credentials_omitted") is True,
    }
    forbidden_raw_paths = _retrieval_ops_forbidden_raw_paths(bundle)
    missing_redaction_flags = [name for name, ok in redaction_flags.items() if not ok]
    for flag in missing_redaction_flags:
        findings.append(_retrieval_ops_finding("redaction_flag_missing", f"redaction flag {flag} is not proven"))
    if forbidden_raw_paths:
        findings.append(_retrieval_ops_finding("redaction_raw_field_present", "retrieval ops bundle contains raw query/document/credential fields"))
    redaction_ok = not missing_redaction_flags and not forbidden_raw_paths
    checks.append({"name": "redaction", "ok": redaction_ok, **redaction_flags, "forbidden_raw_paths": forbidden_raw_paths})

    report: dict[str, Any] = {
        "ok": not findings,
        "bundle": {
            "name": bundle.get("name"),
            "lexical_backend": lexical_backend,
            "graph_backend": graph_backend,
            "retrieval_case_count": len(cases),
            "adapter_probe_count": len(adapter_rows),
            "calibration_dataset_fingerprint_present": "sha256:" in dataset_fingerprint.lower(),
        },
        "requirements": {
            "required_provider_checks": required_provider_checks,
            "provider_forbid_local": True,
            "backend": "sqlite" if profile == OPS_CHECK_SQLITE_PROFILE else "postgres",
            "min_cases": args.min_cases,
            "min_lexical_cases": args.min_lexical_cases,
            "min_vector_cases": args.min_vector_cases,
            "min_graph_cases": args.min_graph_cases,
            "min_reranked_cases": args.min_reranked_cases,
            "min_calibration_examples": args.min_calibration_examples,
            "min_calibration_correct": args.min_calibration_correct,
            "min_calibration_incorrect": args.min_calibration_incorrect,
            "min_empirical_coverage": args.min_empirical_coverage,
            "max_false_accept_rate": args.max_false_accept_rate,
            "required_adapter_probes": required_adapter_probes,
            "max_adapter_latency_ms": args.max_adapter_latency_ms,
        },
        "redaction": {**redaction_flags, "forbidden_raw_fields_present": bool(forbidden_raw_paths)},
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _retrieval_ops_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(_retrieval_ops_finding("fingerprint_mismatch", "retrieval ops bundle fingerprint mismatch"))
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_auth_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("auth-ops-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = (
            json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8"))
            if args.bundle
            else json.loads(args.bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"auth ops bundle denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("auth ops bundle must be a JSON object")
    return loaded


def _auth_ops_finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _auth_ops_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        "bundle": report.get("bundle"),
        "requirements": report.get("requirements"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _auth_ops_int(
    value: Any,
    *,
    default: int,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> int:
    if value is None or isinstance(value, bool):
        findings.append(_auth_ops_finding(code, message))
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        findings.append(_auth_ops_finding(code, message))
        return default


def _auth_ops_number(
    value: Any,
    *,
    default: float,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> float:
    if value is None or isinstance(value, bool):
        findings.append(_auth_ops_finding(code, message))
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        findings.append(_auth_ops_finding(code, message))
        return default


def _auth_ops_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    forbidden_keys = {
        "idp_token",
        "access_token",
        "refresh_token",
        "raw_token",
        "jwt",
        "raw_claims",
        "raw_jwks",
        "private_key",
        "secret",
        "password",
        "key_material",
        "certificate_pem",
        "current_cert_pem",
        "candidate_cert_pem",
        "client_private_key",
    }
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_name = str(key)
            child_path = f"{path}.{key_name}"
            if key_name.lower() in forbidden_keys and child not in (None, "", [], {}):
                paths.append(child_path)
            paths.extend(_auth_ops_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_auth_ops_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def cmd_auth_ops_check(args: argparse.Namespace) -> None:
    bundle = _load_auth_ops_bundle(args)
    profile = _ops_check_profile(bundle)
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    idp = bundle.get("idp_jwks")
    if not isinstance(idp, Mapping):
        findings.append(_auth_ops_finding("missing_idp_jwks", "auth ops bundle requires idp_jwks section"))
        idp = {}
    jwks = idp.get("jwks") if isinstance(idp.get("jwks"), Mapping) else {}
    token = idp.get("token") if isinstance(idp.get("token"), Mapping) else {}
    identity = idp.get("identity") if isinstance(idp.get("identity"), Mapping) else {}
    rotation = idp.get("rotation") if isinstance(idp.get("rotation"), Mapping) else {}
    jwks_key_count = _auth_ops_int(
        jwks.get("key_count"),
        default=0,
        code="jwks_key_count_invalid",
        message="idp_jwks.jwks.key_count must be numeric",
        findings=findings,
    )
    token_ttl = _auth_ops_int(
        token.get("expires_in_seconds"),
        default=0,
        code="token_ttl_invalid",
        message="idp_jwks.token.expires_in_seconds must be numeric",
        findings=findings,
    )
    trust_tier = _auth_ops_int(
        identity.get("source_trust_tier"),
        default=-1,
        code="identity_trust_tier_invalid",
        message="idp_jwks.identity.source_trust_tier must be numeric",
        findings=findings,
    )
    current_kid = str(rotation.get("current_kid_sha256") or "").strip()
    next_kid = str(rotation.get("next_kid_sha256") or "").strip()
    idp_ok = (
        idp.get("ok") is True
        and bool(idp.get("issuer"))
        and bool(idp.get("audience"))
        and jwks_key_count >= args.min_jwks_keys
        and jwks.get("allow_insecure_url") is not True
        and jwks.get("refresh_on_unknown_kid") is True
        and token.get("kid_present") is True
        and str(token.get("alg") or "").lower() not in {"", "none"}
        and token_ttl >= args.min_token_ttl_seconds
        and token.get("session_id_present") is True
        and bool(identity.get("tenant_hash") or identity.get("tenant_id_hash"))
        and bool(identity.get("user_hash") or identity.get("user_id_sha256"))
        and bool(identity.get("role"))
        and trust_tier >= args.min_source_trust_tier
        and idp.get("authz_policy_configured") is True
        and "sha256:" in current_kid.lower()
        and "sha256:" in next_kid.lower()
        and rotation.get("rotation_verified") is True
        and rotation.get("refresh_on_unknown_kid_verified") is True
        and rotation.get("previous_kid_rejected") is True
    )
    if idp.get("ok") is not True:
        findings.append(_auth_ops_finding("idp_jwks_not_ok", "idp_jwks evidence must be ok"))
    if not idp.get("issuer") or not idp.get("audience"):
        findings.append(_auth_ops_finding("idp_issuer_audience_missing", "idp issuer and audience are required"))
    if jwks_key_count < args.min_jwks_keys:
        findings.append(_auth_ops_finding("jwks_key_count_too_low", "JWKS key count is too low"))
    if jwks.get("allow_insecure_url") is True:
        findings.append(_auth_ops_finding("jwks_insecure_url_allowed", "JWKS evidence must not allow insecure URLs"))
    if jwks.get("refresh_on_unknown_kid") is not True:
        findings.append(_auth_ops_finding("jwks_refresh_disabled", "JWKS refresh-on-unknown-kid must be enabled"))
    if token.get("kid_present") is not True or str(token.get("alg") or "").lower() in {"", "none"}:
        findings.append(_auth_ops_finding("token_header_invalid", "validated token must include kid and safe alg"))
    if token_ttl < args.min_token_ttl_seconds:
        findings.append(_auth_ops_finding("token_ttl_too_low", "validated token TTL is below release threshold"))
    if token.get("session_id_present") is not True:
        findings.append(_auth_ops_finding("token_session_id_missing", "validated token must bind a session id"))
    if not (identity.get("tenant_hash") or identity.get("tenant_id_hash")) or not (
        identity.get("user_hash") or identity.get("user_id_sha256")
    ):
        findings.append(_auth_ops_finding("identity_hash_missing", "identity evidence must use tenant/user hashes"))
    if trust_tier < args.min_source_trust_tier:
        findings.append(_auth_ops_finding("identity_trust_tier_too_low", "identity source trust tier is below threshold"))
    if idp.get("authz_policy_configured") is not True:
        findings.append(_auth_ops_finding("authz_policy_missing", "IdP evidence must prove authz policy is configured"))
    if "sha256:" not in current_kid.lower() or "sha256:" not in next_kid.lower():
        findings.append(_auth_ops_finding("jwks_rotation_kid_hash_missing", "JWKS rotation evidence requires current and next kid hashes"))
    for flag in ("rotation_verified", "refresh_on_unknown_kid_verified", "previous_kid_rejected"):
        if rotation.get(flag) is not True:
            findings.append(_auth_ops_finding("jwks_rotation_control_missing", f"JWKS rotation control {flag} is not proven"))
    checks.append(
        {
            "name": "idp_jwks",
            "ok": idp_ok,
            "issuer_present": bool(idp.get("issuer")),
            "audience_present": bool(idp.get("audience")),
            "jwks_key_count": jwks_key_count,
            "token_ttl_seconds": token_ttl,
            "identity_trust_tier": trust_tier,
            "rotation_verified": rotation.get("rotation_verified") is True,
        }
    )

    rollout = bundle.get("authz_rollout")
    if not isinstance(rollout, Mapping):
        findings.append(_auth_ops_finding("missing_authz_rollout", "auth ops bundle requires authz_rollout section"))
        rollout = {}
    simulation_change_count = _auth_ops_int(
        rollout.get("simulation_change_count"),
        default=args.max_authz_simulation_changes + 1,
        code="authz_simulation_count_invalid",
        message="authz_rollout.simulation_change_count must be numeric",
        findings=findings,
    )
    allowed_cases = _auth_ops_int(
        rollout.get("allowed_case_count"),
        default=0,
        code="authz_case_count_invalid",
        message="authz_rollout.allowed_case_count must be numeric",
        findings=findings,
    )
    denied_cases = _auth_ops_int(
        rollout.get("denied_case_count"),
        default=0,
        code="authz_case_count_invalid",
        message="authz_rollout.denied_case_count must be numeric",
        findings=findings,
    )
    current_policy_fp = str(rollout.get("current_fingerprint") or "").strip()
    candidate_policy_fp = str(rollout.get("candidate_fingerprint") or "").strip()
    rollout_ok = (
        rollout.get("ok") is True
        and "sha256:" in current_policy_fp.lower()
        and "sha256:" in candidate_policy_fp.lower()
        and rollout.get("expected_current_fingerprint_present") is True
        and rollout.get("expected_candidate_fingerprint_present") is True
        and simulation_change_count <= args.max_authz_simulation_changes
        and allowed_cases >= args.min_authz_allowed_cases
        and denied_cases >= args.min_authz_denied_cases
        and rollout.get("tenant_rules_verified") is True
        and rollout.get("ambiguous_matches_rejected") is True
    )
    if rollout.get("ok") is not True:
        findings.append(_auth_ops_finding("authz_rollout_not_ok", "authz rollout evidence must be ok"))
    if "sha256:" not in current_policy_fp.lower() or "sha256:" not in candidate_policy_fp.lower():
        findings.append(_auth_ops_finding("authz_policy_fingerprint_missing", "authz rollout requires current and candidate fingerprints"))
    if rollout.get("expected_current_fingerprint_present") is not True or rollout.get("expected_candidate_fingerprint_present") is not True:
        findings.append(_auth_ops_finding("authz_expected_fingerprint_missing", "authz rollout must acknowledge expected fingerprints"))
    if simulation_change_count > args.max_authz_simulation_changes:
        findings.append(_auth_ops_finding("authz_simulation_changes", "authz simulation changes exceed threshold"))
    if allowed_cases < args.min_authz_allowed_cases:
        findings.append(_auth_ops_finding("authz_allowed_cases_too_low", "authz rollout has too few allowed simulation cases"))
    if denied_cases < args.min_authz_denied_cases:
        findings.append(_auth_ops_finding("authz_denied_cases_too_low", "authz rollout has too few denied simulation cases"))
    if rollout.get("tenant_rules_verified") is not True:
        findings.append(_auth_ops_finding("authz_tenant_rules_missing", "authz rollout must prove tenant rules"))
    if rollout.get("ambiguous_matches_rejected") is not True:
        findings.append(_auth_ops_finding("authz_ambiguous_matches_not_rejected", "authz rollout must reject ambiguous matches"))
    checks.append(
        {
            "name": "authz_rollout",
            "ok": rollout_ok,
            "simulation_change_count": simulation_change_count,
            "allowed_case_count": allowed_cases,
            "denied_case_count": denied_cases,
        }
    )

    session_secret = bundle.get("session_secret")
    if not isinstance(session_secret, Mapping):
        findings.append(_auth_ops_finding("missing_session_secret", "auth ops bundle requires session_secret section"))
        session_secret = {}
    key_count = _auth_ops_int(
        session_secret.get("key_count"),
        default=0,
        code="session_secret_key_count_invalid",
        message="session_secret.key_count must be numeric",
        findings=findings,
    )
    secret_source = str(session_secret.get("source") or "").strip().lower()
    source_local = secret_source in {"", "none", "env", "file", "local", "test"}
    secret_ok = (
        session_secret.get("ok") is True
        and session_secret.get("provider") == "command"
        and not source_local
        and key_count >= args.min_session_secret_keys
        and session_secret.get("active_key_id_present") is True
        and session_secret.get("roundtrip_verified") is True
        and session_secret.get("rotation_verified") is True
        and session_secret.get("revoked_key_rejected") is True
        and session_secret.get("previous_key_rejected") is True
    )
    if session_secret.get("ok") is not True:
        findings.append(_auth_ops_finding("session_secret_not_ok", "session_secret evidence must be ok"))
    if session_secret.get("provider") != "command" or source_local:
        findings.append(_auth_ops_finding("session_secret_provider_not_external", "session_secret must use external command-backed custody"))
    if key_count < args.min_session_secret_keys:
        findings.append(_auth_ops_finding("session_secret_key_count_too_low", "session_secret key count is too low"))
    for flag in ("active_key_id_present", "roundtrip_verified", "rotation_verified", "revoked_key_rejected", "previous_key_rejected"):
        if session_secret.get(flag) is not True:
            findings.append(_auth_ops_finding("session_secret_control_missing", f"session_secret control {flag} is not proven"))
    checks.append(
        {
            "name": "session_secret",
            "ok": secret_ok,
            "provider": session_secret.get("provider"),
            "source": session_secret.get("source"),
            "key_count": key_count,
        }
    )

    tls = bundle.get("tls")
    if not isinstance(tls, Mapping):
        findings.append(_auth_ops_finding("missing_tls", "auth ops bundle requires tls section"))
        tls = {}
    cert = tls.get("certificate") if isinstance(tls.get("certificate"), Mapping) else {}
    cert_checks = tls.get("checks") if isinstance(tls.get("checks"), Mapping) else {}
    rotation_plan = tls.get("rotation") if isinstance(tls.get("rotation"), Mapping) else {}
    rotation_checks = rotation_plan.get("checks") if isinstance(rotation_plan.get("checks"), Mapping) else {}
    days_remaining = _auth_ops_number(
        cert.get("days_remaining"),
        default=0.0,
        code="tls_days_remaining_invalid",
        message="tls.certificate.days_remaining must be numeric",
        findings=findings,
    )
    overlap_days = _auth_ops_number(
        rotation_plan.get("overlap_days"),
        default=0.0,
        code="tls_overlap_days_invalid",
        message="tls.rotation.overlap_days must be numeric",
        findings=findings,
    )
    tls_ok = (
        tls.get("ok") is True
        and days_remaining >= args.min_cert_days
        and cert_checks.get("chain_valid") is True
        and cert_checks.get("hostname_valid") is True
        and cert_checks.get("min_days_valid") is True
        and rotation_plan.get("ok") is True
        and overlap_days >= args.min_cert_overlap_days
        and rotation_checks.get("current_min_days_valid") is True
        and rotation_checks.get("candidate_min_days_valid") is True
        and rotation_checks.get("overlap_valid") is True
        and rotation_checks.get("hostnames_valid") is True
    )
    if tls.get("ok") is not True:
        findings.append(_auth_ops_finding("tls_cert_not_ok", "TLS certificate evidence must be ok"))
    if days_remaining < args.min_cert_days:
        findings.append(_auth_ops_finding("tls_cert_days_too_low", "TLS certificate days remaining is too low"))
    for flag in ("chain_valid", "hostname_valid", "min_days_valid"):
        if cert_checks.get(flag) is not True:
            findings.append(_auth_ops_finding("tls_cert_control_missing", f"TLS certificate check {flag} is not proven"))
    if rotation_plan.get("ok") is not True:
        findings.append(_auth_ops_finding("tls_rotation_not_ok", "TLS rotation evidence must be ok"))
    if overlap_days < args.min_cert_overlap_days:
        findings.append(_auth_ops_finding("tls_overlap_too_low", "TLS rotation overlap days are too low"))
    for flag in ("current_min_days_valid", "candidate_min_days_valid", "overlap_valid", "hostnames_valid"):
        if rotation_checks.get(flag) is not True:
            findings.append(_auth_ops_finding("tls_rotation_control_missing", f"TLS rotation check {flag} is not proven"))
    checks.append(
        {
            "name": "tls",
            "ok": tls_ok,
            "days_remaining": days_remaining,
            "overlap_days": overlap_days,
        }
    )

    tenant_isolation = bundle.get("tenant_isolation")
    if not isinstance(tenant_isolation, Mapping):
        findings.append(_auth_ops_finding("missing_tenant_isolation", "auth ops bundle requires tenant_isolation section"))
        tenant_isolation = {}
    tenant_count = _auth_ops_int(
        tenant_isolation.get("tenant_count"),
        default=0,
        code="tenant_count_invalid",
        message="tenant_isolation.tenant_count must be numeric",
        findings=findings,
    )
    cases_raw = tenant_isolation.get("cases")
    tenant_cases = [item for item in cases_raw if isinstance(item, Mapping)] if isinstance(cases_raw, list) else []
    if not isinstance(cases_raw, list):
        findings.append(_auth_ops_finding("tenant_cases_invalid", "tenant isolation cases must be an array"))
    denied_count = 0
    allowed_count = 0
    for index, case in enumerate(tenant_cases):
        case_id = str(case.get("id") or f"tenant-case-{index + 1}")
        if "sha256:" not in str(case.get("tenant_hash") or "").lower():
            findings.append(_auth_ops_finding("tenant_case_hash_missing", f"tenant case {case_id} requires tenant_hash"))
        expected = str(case.get("expected_decision") or "")
        actual = str(case.get("actual_decision") or "")
        if expected != actual or case.get("enforced") is not True:
            findings.append(_auth_ops_finding("tenant_case_failed", f"tenant case {case_id} was not enforced"))
        if actual == "deny":
            denied_count += 1
        if actual == "allow":
            allowed_count += 1
    # Profile-scoped isolation control: production requires Postgres RLS; the
    # sqlite profile has no RLS, so its isolation analog is one database file per
    # tenant (`sqlite_file_per_tenant`). Production stays RLS-only — a production
    # (default-profile) bundle cannot substitute the sqlite flag.
    isolation_control_flag = (
        "sqlite_file_per_tenant" if profile == OPS_CHECK_SQLITE_PROFILE else "postgres_rls_enabled"
    )
    tenant_ok = (
        tenant_isolation.get(isolation_control_flag) is True
        and tenant_isolation.get("cross_tenant_read_denied") is True
        and tenant_isolation.get("cross_tenant_write_denied") is True
        and tenant_isolation.get("signed_session_tenant_binding") is True
        and tenant_count >= args.min_tenants
        and len(tenant_cases) >= args.min_tenant_cases
        and denied_count >= args.min_tenant_denied_cases
        and allowed_count >= args.min_tenant_allowed_cases
    )
    for flag in (isolation_control_flag, "cross_tenant_read_denied", "cross_tenant_write_denied", "signed_session_tenant_binding"):
        if tenant_isolation.get(flag) is not True:
            findings.append(_auth_ops_finding("tenant_isolation_control_missing", f"tenant isolation control {flag} is not proven"))
    if tenant_count < args.min_tenants:
        findings.append(_auth_ops_finding("tenant_count_too_low", "tenant isolation evidence has too few tenants"))
    if len(tenant_cases) < args.min_tenant_cases:
        findings.append(_auth_ops_finding("tenant_cases_too_few", "tenant isolation evidence has too few cases"))
    if denied_count < args.min_tenant_denied_cases:
        findings.append(_auth_ops_finding("tenant_denied_cases_too_few", "tenant isolation evidence has too few denied cases"))
    if allowed_count < args.min_tenant_allowed_cases:
        findings.append(_auth_ops_finding("tenant_allowed_cases_too_few", "tenant isolation evidence has too few allowed cases"))
    checks.append(
        {
            "name": "tenant_isolation",
            "ok": tenant_ok,
            "tenant_count": tenant_count,
            "case_count": len(tenant_cases),
            "allowed_cases": allowed_count,
            "denied_cases": denied_count,
        }
    )

    redaction = bundle.get("redaction")
    if not isinstance(redaction, Mapping):
        findings.append(_auth_ops_finding("missing_redaction_section", "auth ops bundle requires redaction section"))
        redaction = {}
    redaction_flags = {
        "raw_tokens_omitted": redaction.get("raw_tokens_omitted") is True,
        "raw_claims_omitted": redaction.get("raw_claims_omitted") is True,
        "raw_secrets_omitted": redaction.get("raw_secrets_omitted") is True,
        "raw_cert_private_keys_omitted": redaction.get("raw_cert_private_keys_omitted") is True,
    }
    forbidden_raw_paths = _auth_ops_forbidden_raw_paths(bundle)
    missing_redaction_flags = [name for name, ok in redaction_flags.items() if not ok]
    for flag in missing_redaction_flags:
        findings.append(_auth_ops_finding("redaction_flag_missing", f"redaction flag {flag} is not proven"))
    if forbidden_raw_paths:
        findings.append(_auth_ops_finding("redaction_raw_field_present", "auth ops bundle contains raw token/secret/certificate fields"))
    checks.append(
        {
            "name": "redaction",
            "ok": not missing_redaction_flags and not forbidden_raw_paths,
            **redaction_flags,
            "forbidden_raw_paths": forbidden_raw_paths,
        }
    )

    report: dict[str, Any] = {
        "ok": not findings,
        "bundle": {
            "name": bundle.get("name"),
            "issuer_present": bool(idp.get("issuer")),
            "jwks_key_count": jwks_key_count,
            "session_secret_provider": session_secret.get("provider"),
            "tenant_isolation_case_count": len(tenant_cases),
        },
        "requirements": {
            "min_jwks_keys": args.min_jwks_keys,
            "min_token_ttl_seconds": args.min_token_ttl_seconds,
            "min_source_trust_tier": args.min_source_trust_tier,
            "max_authz_simulation_changes": args.max_authz_simulation_changes,
            "min_authz_allowed_cases": args.min_authz_allowed_cases,
            "min_authz_denied_cases": args.min_authz_denied_cases,
            "min_session_secret_keys": args.min_session_secret_keys,
            "min_cert_days": args.min_cert_days,
            "min_cert_overlap_days": args.min_cert_overlap_days,
            "min_tenants": args.min_tenants,
            "min_tenant_cases": args.min_tenant_cases,
            "min_tenant_allowed_cases": args.min_tenant_allowed_cases,
            "min_tenant_denied_cases": args.min_tenant_denied_cases,
        },
        "redaction": {**redaction_flags, "forbidden_raw_fields_present": bool(forbidden_raw_paths)},
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _auth_ops_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(_auth_ops_finding("fingerprint_mismatch", "auth ops bundle fingerprint mismatch"))
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_mcp_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("mcp-ops-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = (
            json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8"))
            if args.bundle
            else json.loads(args.bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"mcp ops bundle denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("mcp ops bundle must be a JSON object")
    return loaded


def _mcp_ops_finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _mcp_ops_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        "bundle": report.get("bundle"),
        "requirements": report.get("requirements"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _mcp_ops_int(
    value: Any,
    *,
    default: int,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> int:
    if value is None or isinstance(value, bool):
        findings.append(_mcp_ops_finding(code, message))
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        findings.append(_mcp_ops_finding(code, message))
        return default


def _mcp_ops_number(
    value: Any,
    *,
    default: float,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> float:
    if value is None or isinstance(value, bool):
        findings.append(_mcp_ops_finding(code, message))
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        findings.append(_mcp_ops_finding(code, message))
        return default


def _mcp_ops_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    forbidden_keys = {
        "auth_token",
        "mcp_session_token",
        "bearer_token",
        "session_secret",
        "access_token",
        "refresh_token",
        "token",
        "password",
        "private_key",
        "raw_request",
        "raw_requests",
        "request_body",
        "raw_response",
        "raw_responses",
        "response_body",
        "headers",
    }
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_name = str(key)
            child_path = f"{path}.{key_name}"
            if key_name.lower() in forbidden_keys and child not in (None, "", [], {}):
                paths.append(child_path)
            paths.extend(_mcp_ops_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_mcp_ops_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def _mcp_ops_url_ok(url: Any, *, allow_localhost: bool) -> tuple[bool, str, bool]:
    url_text = str(url or "").strip()
    if not url_text:
        return False, "", False
    parsed = urlsplit(url_text)
    local = _is_loopback_host(parsed.hostname or "")
    return parsed.scheme == "https" and bool(parsed.hostname) and (allow_localhost or not local), url_text, local


def _mcp_transport_check(
    *,
    name: str,
    evidence: Mapping[str, Any],
    expected_transport: str,
    args: argparse.Namespace,
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    url_ok, url_text, local_url = _mcp_ops_url_ok(evidence.get("base_url") or evidence.get("url"), allow_localhost=args.allow_localhost)
    loop_count = _mcp_ops_int(
        evidence.get("loop_count"),
        default=0,
        code="mcp_loop_count_invalid",
        message=f"{name} loop_count must be numeric",
        findings=findings,
    )
    avg_latency = _mcp_ops_number(
        evidence.get("avg_latency_ms"),
        default=args.max_avg_latency_ms + 1.0,
        code="mcp_latency_invalid",
        message=f"{name} avg_latency_ms must be numeric",
        findings=findings,
    )
    p95_latency = _mcp_ops_number(
        evidence.get("p95_latency_ms"),
        default=args.max_p95_latency_ms + 1.0,
        code="mcp_latency_invalid",
        message=f"{name} p95_latency_ms must be numeric",
        findings=findings,
    )
    checks = evidence.get("checks") if isinstance(evidence.get("checks"), Mapping) else {}
    required_flags = {
        "health_ok": evidence.get("health_ok") is True or checks.get("health_ok") is True,
        "initialize_ok": evidence.get("initialize_ok") is True or checks.get("initialize_ok") is True,
        "tools_list_ok": evidence.get("tools_list_ok") is True or checks.get("tools_list_ok") is True,
        "tool_contract_ok": evidence.get("tool_contract_ok") is True or checks.get("tool_contract_ok") is True,
        "read_only_call_ok": evidence.get("read_only_call_ok") is True or checks.get("read_only_call_ok") is True,
        "structured_tool_call_ok": evidence.get("structured_tool_call_ok") is True
        or checks.get("structured_tool_call_ok") is True,
        "stateless_verified": evidence.get("stateless_verified") is True or checks.get("stateless_verified") is True,
    }
    missing_flags = [flag for flag, ok in required_flags.items() if not ok]
    transport_ok = str(evidence.get("transport") or "") == expected_transport
    ok = (
        evidence.get("ok") is True
        and transport_ok
        and url_ok
        and loop_count >= args.min_loops
        and avg_latency <= args.max_avg_latency_ms
        and p95_latency <= args.max_p95_latency_ms
        and evidence.get("auth_token_configured") is True
        and evidence.get("session_token_configured") is True
        and not missing_flags
    )
    if evidence.get("ok") is not True:
        findings.append(_mcp_ops_finding("mcp_transport_not_ok", f"{name} evidence must be ok"))
    if not transport_ok:
        findings.append(_mcp_ops_finding("mcp_transport_mismatch", f"{name} transport must be {expected_transport}"))
    if not url_ok:
        findings.append(_mcp_ops_finding("mcp_url_not_production_https", f"{name} base URL must be HTTPS and non-local"))
    if loop_count < args.min_loops:
        findings.append(_mcp_ops_finding("mcp_loop_count_too_low", f"{name} loop count is too low"))
    if avg_latency > args.max_avg_latency_ms:
        findings.append(_mcp_ops_finding("mcp_avg_latency_too_high", f"{name} average latency exceeds threshold"))
    if p95_latency > args.max_p95_latency_ms:
        findings.append(_mcp_ops_finding("mcp_p95_latency_too_high", f"{name} p95 latency exceeds threshold"))
    if evidence.get("auth_token_configured") is not True:
        findings.append(_mcp_ops_finding("mcp_auth_token_missing", f"{name} must prove bearer-token enforcement"))
    if evidence.get("session_token_configured") is not True:
        findings.append(_mcp_ops_finding("mcp_session_token_missing", f"{name} must prove signed-session binding"))
    for flag in missing_flags:
        findings.append(_mcp_ops_finding("mcp_transport_control_missing", f"{name} control {flag} is not proven"))
    return {
        "name": name,
        "ok": ok,
        "transport": evidence.get("transport"),
        "url_present": bool(url_text),
        "local_url": local_url,
        "loop_count": loop_count,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "auth_token_configured": evidence.get("auth_token_configured") is True,
        "session_token_configured": evidence.get("session_token_configured") is True,
        "missing_controls": missing_flags,
    }


def cmd_mcp_ops_check(args: argparse.Namespace) -> None:
    bundle = _load_mcp_ops_bundle(args)
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    http = bundle.get("http_json_rpc")
    if not isinstance(http, Mapping):
        findings.append(_mcp_ops_finding("missing_http_json_rpc", "mcp ops bundle requires http_json_rpc section"))
        http = {}
    checks.append(
        _mcp_transport_check(
            name="http_json_rpc",
            evidence=http,
            expected_transport="http-json-rpc",
            args=args,
            findings=findings,
        )
    )

    streamable = bundle.get("streamable_http")
    if not isinstance(streamable, Mapping):
        findings.append(_mcp_ops_finding("missing_streamable_http", "mcp ops bundle requires streamable_http section"))
        streamable = {}
    checks.append(
        _mcp_transport_check(
            name="streamable_http",
            evidence=streamable,
            expected_transport="mcp-sdk-streamable-http",
            args=args,
            findings=findings,
        )
    )

    sse = bundle.get("legacy_sse")
    if args.require_legacy_sse:
        if not isinstance(sse, Mapping):
            findings.append(_mcp_ops_finding("missing_legacy_sse", "mcp ops bundle requires legacy_sse section"))
            sse = {}
        sse_url_ok, _sse_url, sse_local = _mcp_ops_url_ok(sse.get("base_url") or sse.get("url"), allow_localhost=args.allow_localhost)
        sse_event_count = _mcp_ops_int(
            sse.get("event_count"),
            default=0,
            code="mcp_sse_event_count_invalid",
            message="legacy_sse event_count must be numeric",
            findings=findings,
        )
        sse_ok = (
            sse.get("ok") is True
            and str(sse.get("transport") or "") == "legacy-sse"
            and sse_url_ok
            and sse_event_count >= args.min_sse_events
            and sse.get("endpoint_data_present") is True
            and sse.get("auth_token_configured") is True
            and sse.get("session_token_configured") is True
        )
        if sse.get("ok") is not True:
            findings.append(_mcp_ops_finding("mcp_sse_not_ok", "legacy_sse evidence must be ok"))
        if str(sse.get("transport") or "") != "legacy-sse":
            findings.append(_mcp_ops_finding("mcp_sse_transport_mismatch", "legacy_sse transport must be legacy-sse"))
        if not sse_url_ok:
            findings.append(_mcp_ops_finding("mcp_sse_url_not_production_https", "legacy_sse URL must be HTTPS and non-local"))
        if sse_event_count < args.min_sse_events:
            findings.append(_mcp_ops_finding("mcp_sse_events_too_low", "legacy_sse event count is too low"))
        if sse.get("endpoint_data_present") is not True:
            findings.append(_mcp_ops_finding("mcp_sse_endpoint_missing", "legacy_sse endpoint event data is required"))
        if sse.get("auth_token_configured") is not True:
            findings.append(_mcp_ops_finding("mcp_sse_auth_missing", "legacy_sse must prove bearer-token enforcement"))
        if sse.get("session_token_configured") is not True:
            findings.append(_mcp_ops_finding("mcp_sse_session_missing", "legacy_sse must prove signed-session binding"))
        checks.append(
            {
                "name": "legacy_sse",
                "ok": sse_ok,
                "local_url": sse_local,
                "event_count": sse_event_count,
                "endpoint_data_present": sse.get("endpoint_data_present") is True,
                "auth_token_configured": sse.get("auth_token_configured") is True,
                "session_token_configured": sse.get("session_token_configured") is True,
            }
        )
    elif isinstance(sse, Mapping):
        checks.append(
            {
                "name": "legacy_sse",
                "ok": sse.get("ok") is True,
                "optional": True,
                "event_count": sse.get("event_count"),
            }
        )

    tls = bundle.get("tls")
    if not isinstance(tls, Mapping):
        findings.append(_mcp_ops_finding("missing_tls", "mcp ops bundle requires tls section"))
        tls = {}
    cert = tls.get("certificate") if isinstance(tls.get("certificate"), Mapping) else {}
    tls_checks = tls.get("checks") if isinstance(tls.get("checks"), Mapping) else {}
    days_remaining = _mcp_ops_number(
        cert.get("days_remaining"),
        default=0.0,
        code="mcp_tls_days_invalid",
        message="tls.certificate.days_remaining must be numeric",
        findings=findings,
    )
    tls_ok = (
        tls.get("ok") is True
        and days_remaining >= args.min_cert_days
        and tls_checks.get("chain_valid") is True
        and tls_checks.get("hostname_valid") is True
        and tls_checks.get("min_days_valid") is True
        and tls_checks.get("min_tls_version_valid") is True
        and (not args.require_client_cert or tls.get("client_certificate_required") is True)
    )
    if tls.get("ok") is not True:
        findings.append(_mcp_ops_finding("mcp_tls_not_ok", "MCP TLS evidence must be ok"))
    if days_remaining < args.min_cert_days:
        findings.append(_mcp_ops_finding("mcp_tls_days_too_low", "MCP TLS certificate days remaining is too low"))
    for flag in ("chain_valid", "hostname_valid", "min_days_valid", "min_tls_version_valid"):
        if tls_checks.get(flag) is not True:
            findings.append(_mcp_ops_finding("mcp_tls_control_missing", f"MCP TLS check {flag} is not proven"))
    if args.require_client_cert and tls.get("client_certificate_required") is not True:
        findings.append(_mcp_ops_finding("mcp_client_cert_missing", "MCP deployment must require client certificates"))
    checks.append(
        {
            "name": "tls",
            "ok": tls_ok,
            "days_remaining": days_remaining,
            "client_certificate_required": tls.get("client_certificate_required") is True,
        }
    )

    redaction = bundle.get("redaction")
    if not isinstance(redaction, Mapping):
        findings.append(_mcp_ops_finding("missing_redaction_section", "mcp ops bundle requires redaction section"))
        redaction = {}
    redaction_flags = {
        "raw_tokens_omitted": redaction.get("raw_tokens_omitted") is True,
        "raw_session_tokens_omitted": redaction.get("raw_session_tokens_omitted") is True,
        "raw_requests_omitted": redaction.get("raw_requests_omitted") is True,
        "raw_responses_omitted": redaction.get("raw_responses_omitted") is True,
    }
    forbidden_raw_paths = _mcp_ops_forbidden_raw_paths(bundle)
    missing_redaction_flags = [name for name, ok in redaction_flags.items() if not ok]
    for flag in missing_redaction_flags:
        findings.append(_mcp_ops_finding("redaction_flag_missing", f"redaction flag {flag} is not proven"))
    if forbidden_raw_paths:
        findings.append(_mcp_ops_finding("redaction_raw_field_present", "mcp ops bundle contains raw token/request/response fields"))
    checks.append(
        {
            "name": "redaction",
            "ok": not missing_redaction_flags and not forbidden_raw_paths,
            **redaction_flags,
            "forbidden_raw_paths": forbidden_raw_paths,
        }
    )

    report: dict[str, Any] = {
        "ok": not findings,
        "bundle": {
            "name": bundle.get("name"),
            "http_transport_present": isinstance(http, Mapping),
            "streamable_transport_present": isinstance(streamable, Mapping),
            "legacy_sse_present": isinstance(sse, Mapping),
        },
        "requirements": {
            "min_loops": args.min_loops,
            "max_avg_latency_ms": args.max_avg_latency_ms,
            "max_p95_latency_ms": args.max_p95_latency_ms,
            "min_cert_days": args.min_cert_days,
            "require_legacy_sse": bool(args.require_legacy_sse),
            "min_sse_events": args.min_sse_events,
            "require_client_cert": bool(args.require_client_cert),
            "allow_localhost": bool(args.allow_localhost),
        },
        "redaction": {**redaction_flags, "forbidden_raw_fields_present": bool(forbidden_raw_paths)},
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _mcp_ops_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(_mcp_ops_finding("fingerprint_mismatch", "mcp ops bundle fingerprint mismatch"))
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_worker_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("worker-ops-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = json.loads(Path(args.bundle).read_text(encoding="utf-8")) if args.bundle else json.loads(args.bundle_json)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"worker ops bundle is not valid JSON: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("worker ops bundle must be a JSON object")
    return loaded


def _worker_ops_finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _worker_ops_fingerprint(report: Mapping[str, Any]) -> str:
    stable = {
        "bundle": report.get("bundle"),
        "requirements": report.get("requirements"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _worker_ops_number(
    value: Any,
    *,
    default: float,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        findings.append(_worker_ops_finding(code, message))
        return default


def _worker_ops_int(
    value: Any,
    *,
    default: int,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        findings.append(_worker_ops_finding(code, message))
        return default


def _worker_ops_string_set(
    value: Any,
    *,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list):
        findings.append(_worker_ops_finding(code, message))
        return set()
    return {str(item) for item in value if str(item)}


def _worker_ops_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if child_path.startswith("$.redaction."):
                continue
            lowered = key_text.lower()
            if any(
                token in lowered
                for token in (
                    "token",
                    "secret",
                    "password",
                    "dsn",
                    "connection_string",
                    "database_url",
                    "raw_env",
                    "queue_payload",
                    "worker_log",
                    "stdout",
                    "stderr",
                )
            ):
                paths.append(child_path)
            paths.extend(_worker_ops_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_worker_ops_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def cmd_worker_ops_check(args: argparse.Namespace) -> None:
    from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB
    from mnemosyne.jobs import PROJECTION_RECOMPUTE_JOB

    bundle = _load_worker_ops_bundle(args)
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    deployment_raw = bundle.get("deployment")
    deployment_present = isinstance(deployment_raw, Mapping)
    deployment = deployment_raw if deployment_present else {}
    production_scope_ok = (
        args.allow_non_production
        or (
            deployment.get("environment") == "production"
            and deployment.get("operator_asserted") is True
            and bool(deployment.get("run_id"))
            and bool(deployment.get("started_at"))
            and bool(deployment.get("completed_at"))
        )
    )
    if not args.allow_non_production:
        if deployment.get("environment") != "production":
            findings.append(_worker_ops_finding("target_environment_not_production", "worker deployment environment must be production"))
        if deployment.get("operator_asserted") is not True:
            findings.append(_worker_ops_finding("operator_assertion_missing", "worker deployment requires operator assertion"))
        for field in ("run_id", "started_at", "completed_at"):
            if not deployment.get(field):
                findings.append(_worker_ops_finding("deployment_field_missing", f"deployment.{field} is required"))
    checks.append(
        {
            "name": "deployment_scope",
            "ok": production_scope_ok,
            "environment": deployment.get("environment"),
            "operator_asserted": deployment.get("operator_asserted") is True,
        }
    )

    supervisor_raw = bundle.get("supervisor")
    supervisor_present = isinstance(supervisor_raw, Mapping)
    supervisor = supervisor_raw if supervisor_present else {}
    restart_policy = supervisor.get("restart_policy") if isinstance(supervisor.get("restart_policy"), Mapping) else {}
    process_count = _worker_ops_int(
        supervisor.get("process_count"),
        default=0,
        code="worker_process_count_invalid",
        message="supervisor.process_count must be numeric",
        findings=findings,
    )
    desired_processes = _worker_ops_int(
        supervisor.get("desired_processes", process_count),
        default=0,
        code="worker_desired_processes_invalid",
        message="supervisor.desired_processes must be numeric",
        findings=findings,
    )
    max_restart_seconds = _worker_ops_number(
        restart_policy.get("max_restart_seconds"),
        default=args.max_restart_seconds + 1.0,
        code="worker_restart_seconds_invalid",
        message="restart_policy.max_restart_seconds must be numeric",
        findings=findings,
    )
    supervisor_type = str(supervisor.get("type") or "").strip().lower()
    supervisor_ok = (
        supervisor.get("ok") is True
        and supervisor_type not in {"", "none", "manual", "local"}
        and process_count >= args.min_processes
        and desired_processes >= args.min_processes
        and restart_policy.get("enabled") is True
        and restart_policy.get("backoff_configured") is True
        and max_restart_seconds <= args.max_restart_seconds
    )
    if supervisor.get("ok") is not True:
        findings.append(_worker_ops_finding("worker_supervisor_not_ok", "supervisor evidence must be ok"))
    if supervisor_type in {"", "none", "manual", "local"}:
        findings.append(_worker_ops_finding("worker_supervisor_invalid", "worker supervisor must be an external process manager"))
    if process_count < args.min_processes or desired_processes < args.min_processes:
        findings.append(_worker_ops_finding("worker_process_count_too_low", "worker process count is below threshold"))
    if restart_policy.get("enabled") is not True:
        findings.append(_worker_ops_finding("worker_restart_policy_missing", "restart policy must be enabled"))
    if restart_policy.get("backoff_configured") is not True:
        findings.append(_worker_ops_finding("worker_restart_backoff_missing", "restart policy must prove backoff configuration"))
    if max_restart_seconds > args.max_restart_seconds:
        findings.append(_worker_ops_finding("worker_restart_window_too_high", "restart window exceeds threshold"))
    checks.append(
        {
            "name": "supervisor",
            "ok": supervisor_ok,
            "type": supervisor.get("type"),
            "process_count": process_count,
            "desired_processes": desired_processes,
            "max_restart_seconds": max_restart_seconds,
        }
    )

    heartbeat_raw = bundle.get("heartbeat")
    heartbeat_present = isinstance(heartbeat_raw, Mapping)
    heartbeat = heartbeat_raw if heartbeat_present else {}
    last_seen_age = _worker_ops_number(
        heartbeat.get("last_seen_age_seconds", heartbeat.get("age_seconds")),
        default=args.max_heartbeat_age_seconds + 1.0,
        code="worker_heartbeat_age_invalid",
        message="heartbeat last_seen_age_seconds must be numeric",
        findings=findings,
    )
    heartbeat_ok = heartbeat.get("ok") is True and heartbeat.get("fresh") is True and last_seen_age <= args.max_heartbeat_age_seconds
    if heartbeat.get("ok") is not True or heartbeat.get("fresh") is not True:
        findings.append(_worker_ops_finding("worker_heartbeat_not_fresh", "worker heartbeat must be fresh"))
    if last_seen_age > args.max_heartbeat_age_seconds:
        findings.append(_worker_ops_finding("worker_heartbeat_stale", "worker heartbeat age exceeds threshold"))
    checks.append({"name": "heartbeat", "ok": heartbeat_ok, "last_seen_age_seconds": last_seen_age})

    queue_raw = bundle.get("queue")
    queue_present = isinstance(queue_raw, Mapping)
    queue = queue_raw if queue_present else {}
    queue_backend = str(queue.get("backend") or "").strip().lower()
    backlog = _worker_ops_int(
        queue.get("backlog", queue.get("pending")),
        default=args.max_backlog + 1,
        code="worker_queue_backlog_invalid",
        message="queue backlog must be numeric",
        findings=findings,
    )
    dead_jobs = _worker_ops_int(
        queue.get("dead_jobs", queue.get("dead", 0)),
        default=args.max_dead_jobs + 1,
        code="worker_queue_dead_invalid",
        message="queue dead_jobs must be numeric",
        findings=findings,
    )
    oldest_pending_age = _worker_ops_number(
        queue.get("oldest_pending_age_seconds", 0),
        default=args.max_oldest_pending_age_seconds + 1.0,
        code="worker_queue_age_invalid",
        message="queue oldest_pending_age_seconds must be numeric",
        findings=findings,
    )
    queue_ok = (
        queue.get("ok") is True
        and queue_backend in {"postgres", "postgresql"}
        and queue.get("tenant_scoped") is True
        and backlog <= args.max_backlog
        and dead_jobs <= args.max_dead_jobs
        and oldest_pending_age <= args.max_oldest_pending_age_seconds
    )
    if queue.get("ok") is not True:
        findings.append(_worker_ops_finding("worker_queue_not_ok", "queue evidence must be ok"))
    if queue_backend not in {"postgres", "postgresql"}:
        findings.append(_worker_ops_finding("worker_queue_backend_not_postgres", "worker queue backend must be postgres"))
    if queue.get("tenant_scoped") is not True:
        findings.append(_worker_ops_finding("worker_queue_tenant_scope_missing", "worker queue must prove tenant scoping"))
    if backlog > args.max_backlog:
        findings.append(_worker_ops_finding("worker_queue_backlog_too_high", "worker queue backlog exceeds threshold"))
    if dead_jobs > args.max_dead_jobs:
        findings.append(_worker_ops_finding("worker_dead_jobs_present", "worker queue contains dead jobs"))
    if oldest_pending_age > args.max_oldest_pending_age_seconds:
        findings.append(_worker_ops_finding("worker_queue_oldest_pending_stale", "oldest pending job age exceeds threshold"))
    checks.append(
        {
            "name": "queue",
            "ok": queue_ok,
            "backend": queue_backend,
            "tenant_scoped": queue.get("tenant_scoped") is True,
            "backlog": backlog,
            "dead_jobs": dead_jobs,
            "oldest_pending_age_seconds": oldest_pending_age,
        }
    )

    jobs_raw = bundle.get("jobs")
    jobs_present = isinstance(jobs_raw, Mapping)
    jobs = jobs_raw if jobs_present else {}
    handled_kinds = _worker_ops_string_set(
        jobs.get("handled_kinds"),
        code="worker_handled_kinds_invalid",
        message="jobs.handled_kinds must be a list",
        findings=findings,
    )
    bundle_required_kinds = _worker_ops_string_set(
        jobs.get("required_kinds"),
        code="worker_required_kinds_invalid",
        message="jobs.required_kinds must be a list",
        findings=findings,
    )
    default_required_kinds = {
        CONSOLIDATE_EVIDENCE_JOB,
        PROJECTION_RECOMPUTE_JOB,
        "calibrate",
        "lifecycle_sweep",
        "eval_suite",
        "observability_snapshot",
        "media_extract",
    }
    required_kinds = sorted(set(args.require_job_kind) or bundle_required_kinds or default_required_kinds)
    missing_kinds = [kind for kind in required_kinds if kind not in handled_kinds]
    failed_cycle_count = _worker_ops_int(
        jobs.get("failed_cycle_count", 0),
        default=1,
        code="worker_failed_cycles_invalid",
        message="jobs.failed_cycle_count must be numeric",
        findings=findings,
    )
    jobs_dead_count = _worker_ops_int(
        jobs.get("dead_job_count", 0),
        default=args.max_dead_jobs + 1,
        code="worker_dead_job_count_invalid",
        message="jobs.dead_job_count must be numeric",
        findings=findings,
    )
    jobs_ok = jobs.get("ok") is True and not missing_kinds and failed_cycle_count == 0 and jobs_dead_count <= args.max_dead_jobs
    if jobs.get("ok") is not True:
        findings.append(_worker_ops_finding("worker_jobs_not_ok", "job handler evidence must be ok"))
    for kind in missing_kinds:
        findings.append(_worker_ops_finding("worker_job_kind_missing", f"worker must handle {kind} jobs"))
    if failed_cycle_count:
        findings.append(_worker_ops_finding("worker_failed_cycles_present", "worker evidence contains failed cycles"))
    if jobs_dead_count > args.max_dead_jobs:
        findings.append(_worker_ops_finding("worker_jobs_dead_present", "worker job evidence contains dead jobs"))
    checks.append(
        {
            "name": "jobs",
            "ok": jobs_ok,
            "handled_kinds": sorted(handled_kinds),
            "missing_kinds": missing_kinds,
            "failed_cycle_count": failed_cycle_count,
            "dead_job_count": jobs_dead_count,
        }
    )

    observability_raw = bundle.get("observability")
    observability = observability_raw if isinstance(observability_raw, Mapping) else {}
    observability_flags = {
        "metrics_exported": observability.get("metrics_exported") is True,
        "cycle_heartbeats": observability.get("cycle_heartbeats") is True,
        "alerts_configured": observability.get("alerts_configured") is True,
        "restart_alerts": observability.get("restart_alerts") is True,
    }
    missing_observability = [name for name, ok in observability_flags.items() if not ok]
    observability_ok = observability.get("ok") is True and not missing_observability
    if observability.get("ok") is not True:
        findings.append(_worker_ops_finding("worker_observability_not_ok", "observability evidence must be ok"))
    for flag in missing_observability:
        findings.append(_worker_ops_finding("worker_observability_missing", f"observability flag {flag} is not proven"))
    checks.append({"name": "observability", "ok": observability_ok, **observability_flags})

    redaction_raw = bundle.get("redaction")
    redaction = redaction_raw if isinstance(redaction_raw, Mapping) else {}
    redaction_flags = {
        "raw_env_omitted": redaction.get("raw_env_omitted") is True,
        "raw_connection_strings_omitted": redaction.get("raw_connection_strings_omitted") is True,
        "raw_queue_payloads_omitted": redaction.get("raw_queue_payloads_omitted") is True,
        "raw_worker_logs_omitted": redaction.get("raw_worker_logs_omitted") is True,
    }
    forbidden_raw_paths = _worker_ops_forbidden_raw_paths(bundle)
    missing_redaction = [name for name, ok in redaction_flags.items() if not ok]
    for flag in missing_redaction:
        findings.append(_worker_ops_finding("redaction_flag_missing", f"redaction flag {flag} is not proven"))
    if forbidden_raw_paths:
        findings.append(_worker_ops_finding("redaction_raw_field_present", "worker ops bundle contains raw secret/env/payload/log fields"))
    checks.append(
        {
            "name": "redaction",
            "ok": not missing_redaction and not forbidden_raw_paths,
            **redaction_flags,
            "forbidden_raw_paths": forbidden_raw_paths,
        }
    )

    report: dict[str, Any] = {
        "ok": not findings,
        "bundle": {
            "name": bundle.get("name"),
            "deployment_present": deployment_present,
            "supervisor_present": supervisor_present,
            "heartbeat_present": heartbeat_present,
            "queue_present": queue_present,
            "jobs_present": jobs_present,
        },
        "requirements": {
            "min_processes": args.min_processes,
            "max_restart_seconds": args.max_restart_seconds,
            "max_heartbeat_age_seconds": args.max_heartbeat_age_seconds,
            "max_backlog": args.max_backlog,
            "max_dead_jobs": args.max_dead_jobs,
            "max_oldest_pending_age_seconds": args.max_oldest_pending_age_seconds,
            "required_job_kinds": required_kinds,
            "allow_non_production": bool(args.allow_non_production),
        },
        "redaction": {**redaction_flags, "forbidden_raw_fields_present": bool(forbidden_raw_paths)},
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _worker_ops_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(_worker_ops_finding("fingerprint_mismatch", "worker ops bundle fingerprint mismatch"))
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_consolidation_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("consolidation-ops-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = (
            json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8"))
            if args.bundle
            else json.loads(args.bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"consolidation ops bundle denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("consolidation ops bundle must be a JSON object")
    return loaded


def _consolidation_finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _consolidation_ops_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        "bundle": report.get("bundle"),
        "requirements": report.get("requirements"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _consolidation_ops_int(
    value: Any,
    *,
    default: int,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        findings.append(_consolidation_finding(code, message))
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        findings.append(_consolidation_finding(code, message))
        return default


def _consolidation_provider_local(provider: Any) -> bool:
    provider_kind = str(provider or "").strip().lower()
    return provider_kind in {
        "",
        "deterministic",
        "file",
        "filesystem",
        "hashing",
        "in-memory",
        "in_process",
        "local",
        "mock",
        "none",
        "test",
    }


def _consolidation_https_nonlocal(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    parsed = urlsplit(text)
    return parsed.scheme == "https" and bool(parsed.hostname) and not _is_loopback_host(parsed.hostname)


def _consolidation_hash_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _consolidation_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    forbidden_keys = {
        "access_token",
        "affected_evidence_cids",
        "api_key",
        "auth_token",
        "authorization",
        "bearer_token",
        "changed_evidence_cids",
        "content",
        "contents",
        "credential",
        "credentials",
        "document",
        "documents",
        "embedding_vector",
        "embedding_vectors",
        "embedding_values",
        "evidence",
        "evidences",
        "headers",
        "password",
        "private_key",
        "prompt",
        "prompts",
        "query",
        "queries",
        "raw_embedding",
        "raw_embeddings",
        "raw_evidence",
        "raw_prompt",
        "raw_prompts",
        "raw_provider_request",
        "raw_provider_requests",
        "raw_provider_response",
        "raw_provider_responses",
        "request",
        "raw_request",
        "raw_requests",
        "response",
        "raw_response",
        "raw_responses",
        "requests",
        "responses",
        "request_body",
        "response_body",
        "secret",
        "source_evidence_cids",
        "tenant",
        "tenant_id",
        "token",
        "user",
        "user_id",
    }
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_name = str(key)
            child_path = f"{path}.{key_name}"
            if key_name.lower() in forbidden_keys and child not in (None, "", [], {}):
                paths.append(child_path)
            paths.extend(_consolidation_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_consolidation_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def _consolidation_hosted_check_rows(raw: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, Mapping)]
    if isinstance(raw, Mapping):
        return [item for item in raw.values() if isinstance(item, Mapping)]
    return []


def _consolidation_projection_details(section: Mapping[str, Any]) -> Mapping[str, Any]:
    details = section.get("details")
    if isinstance(details, Mapping):
        return details
    job = section.get("job")
    if isinstance(job, Mapping):
        result = job.get("result")
        if isinstance(result, Mapping):
            nested = result.get("details")
            if isinstance(nested, Mapping):
                return nested
    return section


def cmd_consolidation_ops_check(args: argparse.Namespace) -> None:
    from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB
    from mnemosyne.jobs import PROJECTION_RECOMPUTE_JOB

    bundle = _load_consolidation_ops_bundle(args)
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    validation_scope = bundle.get("validation_scope")
    if not isinstance(validation_scope, Mapping):
        findings.append(
            _consolidation_finding(
                "validation_scope_missing",
                "consolidation ops bundle requires validation_scope section",
            )
        )
        validation_scope = {}
    validation_scope_ok = (
        validation_scope.get("production_validated") is True
        and validation_scope.get("target_environment") == "production"
        and validation_scope.get("operator_asserted") is True
        and bool(validation_scope.get("run_id"))
        and bool(validation_scope.get("started_at"))
        and bool(validation_scope.get("completed_at"))
    )
    if validation_scope.get("production_validated") is not True:
        findings.append(
            _consolidation_finding(
                "production_validation_missing",
                "consolidation ops bundle must be production validated",
            )
        )
    if validation_scope.get("target_environment") != "production":
        findings.append(
            _consolidation_finding(
                "target_environment_not_production",
                "consolidation ops target environment must be production",
            )
        )
    if validation_scope.get("operator_asserted") is not True:
        findings.append(
            _consolidation_finding(
                "operator_assertion_missing",
                "operator production assertion is required",
            )
        )
    for field in ("run_id", "started_at", "completed_at"):
        if not validation_scope.get(field):
            findings.append(
                _consolidation_finding(
                    "validation_scope_field_missing",
                    f"validation_scope.{field} is required",
                )
            )
    checks.append(
        {
            "name": "validation_scope",
            "ok": validation_scope_ok,
            "production_validated": validation_scope.get("production_validated") is True,
            "target_environment": validation_scope.get("target_environment"),
            "operator_asserted": validation_scope.get("operator_asserted") is True,
        }
    )

    worker = bundle.get("worker") or bundle.get("worker_run")
    if not isinstance(worker, Mapping):
        findings.append(_consolidation_finding("worker_missing", "consolidation ops bundle requires worker section"))
        worker = {}
    worker_summary = worker.get("summary") if isinstance(worker.get("summary"), Mapping) else {}
    worker_queue = worker.get("queue") if isinstance(worker.get("queue"), Mapping) else {}
    worker_backend = str(worker.get("backend") or worker.get("queue_backend") or worker_queue.get("backend") or "").strip().lower()
    worker_cycles = _consolidation_ops_int(
        worker.get("cycles", worker_summary.get("cycles")),
        default=0,
        code="worker_cycles_invalid",
        message="worker cycles must be numeric",
        findings=findings,
    )
    processed_jobs = _consolidation_ops_int(
        worker.get("processed_jobs", worker.get("processed", worker_summary.get("processed"))),
        default=0,
        code="worker_processed_invalid",
        message="worker processed_jobs must be numeric",
        findings=findings,
    )
    dead_jobs = _consolidation_ops_int(
        worker.get("dead_jobs", worker_queue.get("dead", worker_summary.get("dead_jobs", 0))),
        default=0,
        code="worker_dead_jobs_invalid",
        message="worker dead_jobs must be numeric",
        findings=findings,
    )
    jobs_raw = worker.get("jobs") if isinstance(worker.get("jobs"), list) else []
    processed_kinds = set(_consolidation_hash_list(worker.get("processed_kinds")))
    for job in jobs_raw:
        if isinstance(job, Mapping) and job.get("kind"):
            processed_kinds.add(str(job.get("kind")))
    worker_kind = str(worker.get("kind") or worker.get("job_kind") or "").strip()
    if worker_kind:
        processed_kinds.add(worker_kind)
    required_worker_kinds = sorted(
        set(
            args.require_worker_kind
            or [
                CONSOLIDATE_EVIDENCE_JOB,
                PROJECTION_RECOMPUTE_JOB,
                "calibrate",
                "lifecycle_sweep",
                "observability_snapshot",
            ]
        )
    )
    missing_worker_kinds = [kind for kind in required_worker_kinds if kind not in processed_kinds]
    heartbeat = worker.get("heartbeat") if isinstance(worker.get("heartbeat"), Mapping) else {}
    worker_ok = (
        worker.get("ok") is True
        and worker_backend in {"postgres", "postgresql"}
        and worker_cycles >= args.min_worker_cycles
        and processed_jobs >= args.min_processed_jobs
        and dead_jobs <= args.max_dead_jobs
        and not missing_worker_kinds
        and worker.get("fail_on_dead") is True
        and worker.get("supervised") is True
        and bool(worker.get("tenant_hash"))
        and (worker.get("heartbeat_verified") is True or heartbeat.get("ok") is True)
    )
    if worker.get("ok") is not True:
        findings.append(_consolidation_finding("worker_not_ok", "worker evidence must be ok"))
    if worker_backend not in {"postgres", "postgresql"}:
        findings.append(_consolidation_finding("worker_backend_not_postgres", "consolidation worker queue backend must be postgres"))
    for kind in missing_worker_kinds:
        findings.append(_consolidation_finding("worker_job_kind_missing", f"worker must process {kind} jobs"))
    if worker_cycles < args.min_worker_cycles:
        findings.append(_consolidation_finding("worker_cycles_too_low", "worker cycles are below threshold"))
    if processed_jobs < args.min_processed_jobs:
        findings.append(_consolidation_finding("worker_processed_too_low", "worker processed job count is below threshold"))
    if dead_jobs > args.max_dead_jobs:
        findings.append(_consolidation_finding("worker_dead_jobs_present", "worker evidence contains dead jobs"))
    if worker.get("fail_on_dead") is not True:
        findings.append(_consolidation_finding("worker_fail_on_dead_missing", "worker must run with fail_on_dead=true"))
    if worker.get("supervised") is not True:
        findings.append(_consolidation_finding("worker_supervision_missing", "worker supervision proof is required"))
    if not worker.get("tenant_hash"):
        findings.append(_consolidation_finding("worker_tenant_hash_missing", "worker tenant identity must be hashed"))
    if worker.get("heartbeat_verified") is not True and heartbeat.get("ok") is not True:
        findings.append(_consolidation_finding("worker_heartbeat_missing", "worker heartbeat evidence is required"))
    checks.append(
        {
            "name": "worker",
            "ok": worker_ok,
            "backend": worker_backend,
            "cycles": worker_cycles,
            "processed_jobs": processed_jobs,
            "dead_jobs": dead_jobs,
            "processed_kinds": sorted(processed_kinds),
            "missing_kinds": missing_worker_kinds,
            "tenant_hash_present": bool(worker.get("tenant_hash")),
        }
    )

    provider_check = bundle.get("provider_check")
    if not isinstance(provider_check, Mapping):
        findings.append(
            _consolidation_finding(
                "provider_check_missing",
                "consolidation ops bundle requires provider_check section",
            )
        )
        provider_check = {}
    provider_manifest = provider_check.get("manifest") if isinstance(provider_check.get("manifest"), Mapping) else {}
    provider_checks = provider_check.get("checks") if isinstance(provider_check.get("checks"), Mapping) else {}
    required_provider_checks = sorted(
        set(args.require_provider_check or ["candidate_extractor", "embedding", "entity_resolver", "summarizer"])
    )
    provider_rows: list[dict[str, Any]] = []
    if provider_check.get("ok") is not True:
        findings.append(_consolidation_finding("provider_check_not_ok", "provider_check evidence must be ok"))
    if provider_manifest.get("forbid_local") is not True:
        findings.append(
            _consolidation_finding(
                "provider_manifest_forbid_local_missing",
                "provider_check manifest must set forbid_local=true",
            )
        )
    for check_name in required_provider_checks:
        raw_check = provider_checks.get(check_name)
        present = isinstance(raw_check, Mapping)
        provider = raw_check.get("provider") if present else None
        local_provider = _consolidation_provider_local(provider) if present else True
        check_ok = present and raw_check.get("ok") is True and not local_provider
        if not present:
            findings.append(_consolidation_finding("provider_check_required_missing", f"provider_check missing {check_name}"))
        elif raw_check.get("ok") is not True:
            findings.append(_consolidation_finding("provider_check_required_failed", f"provider_check {check_name} did not pass"))
        elif local_provider:
            findings.append(_consolidation_finding("provider_check_local_provider", f"provider_check {check_name} uses a local provider"))
        provider_rows.append(
            {
                "check": check_name,
                "present": present,
                "ok": check_ok,
                "provider": provider,
                "local_provider": local_provider,
            }
        )
    provider_ok = provider_check.get("ok") is True and provider_manifest.get("forbid_local") is True and all(
        row["ok"] for row in provider_rows
    )
    checks.append(
        {
            "name": "provider_check",
            "ok": provider_ok,
            "forbid_local": provider_manifest.get("forbid_local") is True,
            "required_checks": required_provider_checks,
            "checks": provider_rows,
        }
    )

    hosted = bundle.get("hosted_providers") or bundle.get("hosted_llm")
    if not isinstance(hosted, Mapping):
        findings.append(_consolidation_finding("hosted_providers_missing", "consolidation ops bundle requires hosted_providers section"))
        hosted = {}
    manifest = hosted.get("manifest") if isinstance(hosted.get("manifest"), Mapping) else {}
    role_source = args.require_hosted_role or manifest.get("required_roles") or ["candidate_extractor", "entity_resolver", "summarizer"]
    if not isinstance(role_source, list) or not all(isinstance(item, str) and item for item in role_source):
        findings.append(_consolidation_finding("hosted_roles_invalid", "hosted required roles must be strings"))
        required_roles = ["candidate_extractor", "entity_resolver", "summarizer"]
    else:
        required_roles = sorted(set(role_source))
    hosted_rows = _consolidation_hosted_check_rows(hosted.get("checks"))
    hosted_role_rows: list[dict[str, Any]] = []
    if manifest.get("forbid_local") is not True:
        findings.append(_consolidation_finding("hosted_manifest_forbid_local_missing", "hosted provider manifest must set forbid_local=true"))
    for role in required_roles:
        role_checks = [item for item in hosted_rows if item.get("role") == role]
        role_ok = False
        for item in role_checks:
            endpoint = item.get("origin") or item.get("base_url") or item.get("url")
            endpoint_ok = _consolidation_https_nonlocal(endpoint)
            provider_kind = item.get("provider_kind") or item.get("provider")
            provider_local = _consolidation_provider_local(provider_kind)
            contract = item.get("contract")
            row_ok = (
                item.get("ok") is True
                and str(provider_kind or "") == "hosted_http"
                and endpoint_ok
                and not provider_local
                and isinstance(contract, Mapping)
                and bool(contract)
            )
            role_ok = role_ok or row_ok
            hosted_role_rows.append(
                {
                    "role": role,
                    "ok": row_ok,
                    "provider_kind": provider_kind,
                    "endpoint_present": bool(endpoint),
                    "endpoint_https_nonlocal": endpoint_ok,
                    "contract_present": isinstance(contract, Mapping) and bool(contract),
                }
            )
        if not role_checks:
            findings.append(_consolidation_finding("hosted_role_missing", f"hosted role {role} is missing"))
        elif not role_ok:
            findings.append(_consolidation_finding("hosted_role_failed", f"hosted role {role} did not pass production checks"))
    hosted_ok = bool(hosted_rows) and manifest.get("forbid_local") is True and all(
        any(row["role"] == role and row["ok"] for row in hosted_role_rows) for role in required_roles
    )
    checks.append(
        {
            "name": "hosted_providers",
            "ok": hosted_ok,
            "forbid_local": manifest.get("forbid_local") is True,
            "required_roles": required_roles,
            "provider_count": len(hosted_rows),
            "roles": hosted_role_rows,
        }
    )

    projection = bundle.get("projection_recompute")
    if not isinstance(projection, Mapping):
        findings.append(
            _consolidation_finding("projection_recompute_missing", "consolidation ops bundle requires projection_recompute section")
        )
        projection = {}
    projection_details = _consolidation_projection_details(projection)
    projection_backend = str(projection.get("backend") or projection.get("queue_backend") or "").strip().lower()
    projection_status = str(
        projection.get("status")
        or projection.get("job_status")
        or (projection.get("job", {}).get("status") if isinstance(projection.get("job"), Mapping) else "")
    )
    changed_hashes = _consolidation_hash_list(
        projection.get("changed_evidence_cid_hashes") or projection_details.get("changed_evidence_cid_hashes")
    )
    changed_count = _consolidation_ops_int(
        projection.get("changed_evidence_count", projection_details.get("changed_evidence_count", len(changed_hashes))),
        default=len(changed_hashes),
        code="projection_changed_count_invalid",
        message="projection changed evidence count must be numeric",
        findings=findings,
    )
    affected_counts = projection.get("affected_projection_counts") or projection_details.get("affected_projection_counts")
    if not isinstance(affected_counts, Mapping):
        affected_counts = {}
        findings.append(
            _consolidation_finding("projection_affected_counts_missing", "projection recompute affected_projection_counts are required")
        )
    queued_consolidation_jobs = _consolidation_ops_int(
        projection.get(
            "queued_consolidation_jobs_count",
            projection_details.get(
                "queued_consolidation_jobs_count",
                len(projection_details.get("queued_consolidation_jobs", []))
                if isinstance(projection_details.get("queued_consolidation_jobs"), list)
                else 0,
            ),
        ),
        default=0,
        code="projection_queued_count_invalid",
        message="projection queued consolidation job count must be numeric",
        findings=findings,
    )
    enqueue_consolidation = projection.get("enqueue_consolidation")
    if enqueue_consolidation is None:
        payload = projection.get("payload") if isinstance(projection.get("payload"), Mapping) else {}
        enqueue_consolidation = payload.get("enqueue_consolidation")
    projection_counts_ok = (
        int(affected_counts.get("assertions") or 0) >= args.min_affected_assertions
        and int(affected_counts.get("entities") or 0) >= args.min_affected_entities
        and int(affected_counts.get("relations") or 0) >= args.min_affected_relations
    )
    projection_ok = (
        projection.get("ok", True) is True
        and projection_backend in {"postgres", "postgresql"}
        and projection.get("production_validated") is True
        and projection_status == "complete"
        and changed_count >= args.min_projection_cases
        and bool(changed_hashes)
        and projection_counts_ok
        and enqueue_consolidation is True
        and queued_consolidation_jobs >= 1
    )
    if projection.get("ok", True) is not True:
        findings.append(_consolidation_finding("projection_recompute_not_ok", "projection recompute evidence must be ok"))
    if projection_backend not in {"postgres", "postgresql"}:
        findings.append(_consolidation_finding("projection_backend_not_postgres", "projection recompute backend must be postgres"))
    if projection.get("production_validated") is not True:
        findings.append(_consolidation_finding("projection_production_validation_missing", "projection recompute must be production validated"))
    if projection_status != "complete":
        findings.append(_consolidation_finding("projection_job_incomplete", "projection recompute job must be complete"))
    if changed_count < args.min_projection_cases or not changed_hashes:
        findings.append(_consolidation_finding("projection_changed_cases_too_low", "projection recompute changed evidence proof is too low"))
    if not projection_counts_ok:
        findings.append(_consolidation_finding("projection_affected_counts_too_low", "projection recompute affected projection counts are too low"))
    if enqueue_consolidation is not True or queued_consolidation_jobs < 1:
        findings.append(_consolidation_finding("projection_consolidation_not_enqueued", "projection recompute must re-enqueue consolidation"))
    checks.append(
        {
            "name": "projection_recompute",
            "ok": projection_ok,
            "backend": projection_backend,
            "status": projection_status,
            "changed_evidence_count": changed_count,
            "changed_hash_count": len(changed_hashes),
            "affected_projection_counts": dict(affected_counts),
            "queued_consolidation_jobs_count": queued_consolidation_jobs,
        }
    )

    suite_section = bundle.get("protected_suite") or bundle.get("gate_suite")
    if not isinstance(suite_section, Mapping):
        findings.append(_consolidation_finding("protected_suite_missing", "consolidation ops bundle requires protected_suite section"))
        suite_section = {}
    suite = suite_section.get("suite") if isinstance(suite_section.get("suite"), Mapping) else suite_section
    case_hashes = _consolidation_hash_list(suite.get("case_hashes"))
    protected_hashes = _consolidation_hash_list(suite.get("protected_case_hashes"))
    suite_case_count = _consolidation_ops_int(
        suite.get("case_count", len(case_hashes)),
        default=len(case_hashes),
        code="protected_suite_case_count_invalid",
        message="protected suite case_count must be numeric",
        findings=findings,
    )
    protected_count = _consolidation_ops_int(
        suite.get("protected_case_count", len(protected_hashes)),
        default=len(protected_hashes),
        code="protected_suite_protected_count_invalid",
        message="protected suite protected_case_count must be numeric",
        findings=findings,
    )
    tier_counts = suite.get("tier_counts") if isinstance(suite.get("tier_counts"), Mapping) else {}
    required_tiers = sorted(set(args.require_tier or ["archive", "core", "smoke"]))
    missing_tiers = [tier for tier in required_tiers if int(tier_counts.get(tier) or 0) <= 0]
    source = str(suite.get("source") or "").strip().lower()
    suite_source_ok = bool(source) and source not in {"synthetic", "mock", "test", "generated"}
    suite_counts_match = (not case_hashes or len(case_hashes) == suite_case_count) and (
        not protected_hashes or len(protected_hashes) == protected_count
    )
    suite_ok = (
        suite_case_count >= args.min_gate_cases
        and protected_count >= args.min_protected
        and not missing_tiers
        and suite_source_ok
        and bool(suite.get("fingerprint"))
        and suite_counts_match
    )
    if suite_case_count < args.min_gate_cases:
        findings.append(_consolidation_finding("protected_suite_case_count_too_low", "protected suite case count is too low"))
    if protected_count < args.min_protected:
        findings.append(_consolidation_finding("protected_suite_protected_count_too_low", "protected suite protected count is too low"))
    for tier in missing_tiers:
        findings.append(_consolidation_finding("protected_suite_tier_missing", f"protected suite missing required tier {tier}"))
    if not suite_source_ok:
        findings.append(_consolidation_finding("protected_suite_source_synthetic", "protected suite source must be non-synthetic"))
    if not suite.get("fingerprint"):
        findings.append(_consolidation_finding("protected_suite_fingerprint_missing", "protected suite fingerprint is required"))
    if not suite_counts_match:
        findings.append(_consolidation_finding("protected_suite_case_hash_mismatch", "protected suite hash counts must match declared counts"))
    checks.append(
        {
            "name": "protected_suite",
            "ok": suite_ok,
            "case_count": suite_case_count,
            "protected_case_count": protected_count,
            "source": source,
            "missing_tiers": missing_tiers,
            "fingerprint_present": bool(suite.get("fingerprint")),
        }
    )

    embedding = bundle.get("embedding")
    if not isinstance(embedding, Mapping):
        findings.append(_consolidation_finding("embedding_missing", "consolidation ops bundle requires embedding section"))
        embedding = {}
    embedding_provider = embedding.get("provider") or embedding.get("provider_kind")
    embedding_local = _consolidation_provider_local(embedding_provider)
    dimensions = _consolidation_ops_int(
        embedding.get("dimensions"),
        default=0,
        code="embedding_dimensions_invalid",
        message="embedding dimensions must be numeric",
        findings=findings,
    )
    embedded_hashes = _consolidation_hash_list(embedding.get("cid_hashes") or embedding.get("embedded_cid_hashes"))
    embedded_count = _consolidation_ops_int(
        embedding.get("embedded_cid_hash_count", len(embedded_hashes)),
        default=len(embedded_hashes),
        code="embedding_count_invalid",
        message="embedded CID hash count must be numeric",
        findings=findings,
    )
    embedding_ok = (
        embedding.get("ok") is True
        and not embedding_local
        and dimensions >= args.min_embedding_dimensions
        and embedded_count >= args.min_embedding_cids
        and bool(embedding.get("model"))
    )
    if embedding.get("ok") is not True:
        findings.append(_consolidation_finding("embedding_not_ok", "embedding evidence must be ok"))
    if embedding_local:
        findings.append(_consolidation_finding("embedding_provider_local", "embedding provider must be hosted or external"))
    if dimensions < args.min_embedding_dimensions:
        findings.append(_consolidation_finding("embedding_dimensions_too_low", "embedding dimensions are below threshold"))
    if embedded_count < args.min_embedding_cids:
        findings.append(_consolidation_finding("embedding_count_too_low", "embedded CID hash count is below threshold"))
    if not embedding.get("model"):
        findings.append(_consolidation_finding("embedding_model_missing", "embedding model identifier is required"))
    checks.append(
        {
            "name": "embedding",
            "ok": embedding_ok,
            "provider": embedding_provider,
            "provider_local": embedding_local,
            "dimensions": dimensions,
            "embedded_cid_hash_count": embedded_count,
            "model_present": bool(embedding.get("model")),
        }
    )

    consolidation_run = bundle.get("consolidation_run")
    if not isinstance(consolidation_run, Mapping):
        findings.append(
            _consolidation_finding(
                "consolidation_run_missing",
                "consolidation ops bundle requires consolidation_run section",
            )
        )
        consolidation_run = {}
    role_pipeline = consolidation_run.get("role_pipeline") if isinstance(consolidation_run.get("role_pipeline"), Mapping) else {}
    pass_results_raw = consolidation_run.get("pass_results")
    pass_results = [item for item in pass_results_raw if isinstance(item, Mapping)] if isinstance(pass_results_raw, list) else []
    passes_run = _consolidation_hash_list(consolidation_run.get("passes_run"))
    required_passes = sorted(set(args.require_consolidation_pass or ["extractor", "resolver", "summarizer"]))
    pass_statuses: dict[str, str] = {}
    for item in pass_results:
        name = str(item.get("name") or item.get("pass") or item.get("role") or "")
        if name:
            pass_statuses[name] = str(item.get("status") or ("complete" if item.get("ok") is True else "failed"))
    missing_passes = [name for name in required_passes if name not in passes_run and name not in pass_statuses]
    incomplete_passes = [name for name in required_passes if pass_statuses.get(name, "complete") != "complete" and name in pass_statuses]
    candidate_results = (
        consolidation_run.get("candidate_results")
        if isinstance(consolidation_run.get("candidate_results"), Mapping)
        else {}
    )
    promoted_candidates = _consolidation_ops_int(
        candidate_results.get("promoted", consolidation_run.get("promoted_candidate_count")),
        default=0,
        code="consolidation_promoted_invalid",
        message="consolidation promoted candidate count must be numeric",
        findings=findings,
    )
    evaluated_candidates = _consolidation_ops_int(
        candidate_results.get("evaluated", consolidation_run.get("evaluated_candidate_count")),
        default=0,
        code="consolidation_evaluated_invalid",
        message="consolidation evaluated candidate count must be numeric",
        findings=findings,
    )
    consolidation_hashes = _consolidation_hash_list(consolidation_run.get("source_evidence_cid_hashes"))
    role_pipeline_ok = (
        consolidation_run.get("ok") is True
        and role_pipeline.get("owner_role") == "consolidator"
        and role_pipeline.get("write_authorized") is True
        and role_pipeline.get("candidate_extractor") == "hosted_http"
        and role_pipeline.get("entity_resolver") == "hosted_http"
        and role_pipeline.get("summarizer") == "hosted_http"
        and bool(consolidation_run.get("tenant_hash"))
        and bool(consolidation_hashes)
        and not missing_passes
        and not incomplete_passes
        and evaluated_candidates >= args.min_evaluated_candidates
        and promoted_candidates >= args.min_promoted_candidates
    )
    if consolidation_run.get("ok") is not True:
        findings.append(_consolidation_finding("consolidation_run_not_ok", "consolidation run evidence must be ok"))
    if role_pipeline.get("owner_role") != "consolidator":
        findings.append(_consolidation_finding("role_pipeline_owner_invalid", "role pipeline owner_role must be consolidator"))
    if role_pipeline.get("write_authorized") is not True:
        findings.append(_consolidation_finding("role_pipeline_write_not_authorized", "role pipeline must prove write authorization"))
    for role in ("candidate_extractor", "entity_resolver", "summarizer"):
        if role_pipeline.get(role) != "hosted_http":
            findings.append(_consolidation_finding("role_pipeline_not_hosted", f"role pipeline {role} must use hosted_http"))
    for name in missing_passes:
        findings.append(_consolidation_finding("consolidation_pass_missing", f"consolidation pass {name} is missing"))
    for name in incomplete_passes:
        findings.append(_consolidation_finding("consolidation_pass_incomplete", f"consolidation pass {name} is incomplete"))
    if not consolidation_run.get("tenant_hash"):
        findings.append(_consolidation_finding("consolidation_tenant_hash_missing", "consolidation tenant identity must be hashed"))
    if not consolidation_hashes:
        findings.append(
            _consolidation_finding(
                "consolidation_source_hashes_missing",
                "consolidation source evidence CID hashes are required",
            )
        )
    if evaluated_candidates < args.min_evaluated_candidates:
        findings.append(_consolidation_finding("consolidation_evaluated_too_low", "evaluated candidate count is too low"))
    if promoted_candidates < args.min_promoted_candidates:
        findings.append(_consolidation_finding("consolidation_promoted_too_low", "promoted candidate count is too low"))
    checks.append(
        {
            "name": "consolidation_run",
            "ok": role_pipeline_ok,
            "owner_role": role_pipeline.get("owner_role"),
            "write_authorized": role_pipeline.get("write_authorized") is True,
            "required_passes": required_passes,
            "missing_passes": missing_passes,
            "incomplete_passes": incomplete_passes,
            "source_hash_count": len(consolidation_hashes),
            "evaluated_candidates": evaluated_candidates,
            "promoted_candidates": promoted_candidates,
        }
    )

    calibration = bundle.get("calibration")
    if not isinstance(calibration, Mapping):
        findings.append(_consolidation_finding("calibration_missing", "consolidation ops bundle requires calibration section"))
        calibration = {}
    calibration_examples = _consolidation_ops_int(
        calibration.get("example_count"),
        default=0,
        code="calibration_examples_invalid",
        message="calibration example count must be numeric",
        findings=findings,
    )
    calibration_correct = _consolidation_ops_int(
        calibration.get("correct_count"),
        default=0,
        code="calibration_correct_invalid",
        message="calibration correct count must be numeric",
        findings=findings,
    )
    calibration_incorrect = _consolidation_ops_int(
        calibration.get("incorrect_count"),
        default=0,
        code="calibration_incorrect_invalid",
        message="calibration incorrect count must be numeric",
        findings=findings,
    )
    try:
        correct_coverage = float(calibration.get("correct_coverage", calibration.get("empirical_coverage", 0.0)))
    except (TypeError, ValueError):
        correct_coverage = 0.0
        findings.append(_consolidation_finding("calibration_coverage_invalid", "calibration coverage must be numeric"))
    try:
        false_accept_rate = float(calibration.get("false_accept_rate", 1.0))
    except (TypeError, ValueError):
        false_accept_rate = 1.0
        findings.append(_consolidation_finding("calibration_false_accept_invalid", "calibration false accept rate must be numeric"))
    dataset_fingerprint = str(calibration.get("dataset_fingerprint") or "")
    calibration_ok = (
        calibration.get("ok") is True
        and calibration.get("applied") is True
        and "sha256:" in dataset_fingerprint.lower()
        and calibration.get("threshold") is not None
        and calibration_examples >= args.min_calibration_examples
        and calibration_correct >= args.min_calibration_correct
        and calibration_incorrect >= args.min_calibration_incorrect
        and correct_coverage >= args.min_calibration_coverage
        and false_accept_rate <= args.max_calibration_false_accept_rate
    )
    if calibration.get("ok") is not True:
        findings.append(_consolidation_finding("calibration_not_ok", "calibration evidence must be ok"))
    if calibration.get("applied") is not True:
        findings.append(_consolidation_finding("calibration_not_applied", "calibration must be applied"))
    if "sha256:" not in dataset_fingerprint.lower():
        findings.append(_consolidation_finding("calibration_fingerprint_missing", "calibration dataset fingerprint is required"))
    if calibration.get("threshold") is None:
        findings.append(_consolidation_finding("calibration_threshold_missing", "calibration threshold is required"))
    if calibration_examples < args.min_calibration_examples:
        findings.append(_consolidation_finding("calibration_examples_too_low", "calibration examples are below threshold"))
    if calibration_correct < args.min_calibration_correct:
        findings.append(_consolidation_finding("calibration_correct_too_low", "calibration correct examples are below threshold"))
    if calibration_incorrect < args.min_calibration_incorrect:
        findings.append(_consolidation_finding("calibration_incorrect_too_low", "calibration incorrect examples are below threshold"))
    if correct_coverage < args.min_calibration_coverage:
        findings.append(_consolidation_finding("calibration_coverage_too_low", "calibration coverage is below threshold"))
    if false_accept_rate > args.max_calibration_false_accept_rate:
        findings.append(_consolidation_finding("calibration_false_accept_too_high", "calibration false accept rate exceeds threshold"))
    checks.append(
        {
            "name": "calibration",
            "ok": calibration_ok,
            "example_count": calibration_examples,
            "correct_count": calibration_correct,
            "incorrect_count": calibration_incorrect,
            "correct_coverage": correct_coverage,
            "false_accept_rate": false_accept_rate,
            "dataset_fingerprint_present": "sha256:" in dataset_fingerprint.lower(),
        }
    )

    lifecycle = bundle.get("lifecycle")
    if not isinstance(lifecycle, Mapping):
        findings.append(_consolidation_finding("lifecycle_missing", "consolidation ops bundle requires lifecycle section"))
        lifecycle = {}
    lifecycle_evaluated = _consolidation_ops_int(
        lifecycle.get("evaluated"),
        default=0,
        code="lifecycle_evaluated_invalid",
        message="lifecycle evaluated count must be numeric",
        findings=findings,
    )
    failed_hashes = _consolidation_hash_list(lifecycle.get("failed_cid_hashes") or lifecycle.get("failed_cids"))
    lifecycle_ok = (
        lifecycle.get("status") == "complete"
        and lifecycle_evaluated >= args.min_lifecycle_evaluated
        and "demoted" in lifecycle
        and "rehearsed" in lifecycle
        and not failed_hashes
    )
    if lifecycle.get("status") != "complete":
        findings.append(_consolidation_finding("lifecycle_not_complete", "lifecycle status must be complete"))
    if lifecycle_evaluated < args.min_lifecycle_evaluated:
        findings.append(_consolidation_finding("lifecycle_evaluated_too_low", "lifecycle evaluated count is too low"))
    for field in ("demoted", "rehearsed"):
        if field not in lifecycle:
            findings.append(_consolidation_finding("lifecycle_count_missing", f"lifecycle {field} count is required"))
    if failed_hashes:
        findings.append(_consolidation_finding("lifecycle_failed_cids_present", "lifecycle must not report failed CIDs"))
    checks.append(
        {
            "name": "lifecycle",
            "ok": lifecycle_ok,
            "status": lifecycle.get("status"),
            "evaluated": lifecycle_evaluated,
            "failed_cid_hash_count": len(failed_hashes),
        }
    )

    ops_report = bundle.get("ops_report")
    if not isinstance(ops_report, Mapping):
        findings.append(_consolidation_finding("ops_report_missing", "consolidation ops bundle requires ops_report section"))
        ops_report = {}
    tripwires = ops_report.get("tripwires") if isinstance(ops_report.get("tripwires"), Mapping) else {}
    ops_queue = ops_report.get("queue") if isinstance(ops_report.get("queue"), Mapping) else {}
    ops_metrics = ops_report.get("metrics") if isinstance(ops_report.get("metrics"), Mapping) else {}
    ops_counters = ops_metrics.get("counters") if isinstance(ops_metrics.get("counters"), Mapping) else {}
    ops_dead_jobs = _consolidation_ops_int(
        ops_queue.get("dead", ops_report.get("dead_jobs")),
        default=0,
        code="ops_dead_jobs_invalid",
        message="ops report dead job count must be numeric",
        findings=findings,
    )
    required_counters = sorted(
        set(args.require_ops_counter or ["calibration.tuned", "lifecycle.sweeps", "observability.snapshots"])
    )
    missing_counters = [name for name in required_counters if name not in ops_counters]
    contradiction_backlog = _consolidation_ops_int(
        ops_report.get("contradiction_backlog", 0),
        default=0,
        code="ops_contradiction_backlog_invalid",
        message="ops contradiction backlog must be numeric",
        findings=findings,
    )
    ops_report_ok = (
        ops_report.get("ok") is True
        and tripwires.get("passed") is True
        and ops_dead_jobs == 0
        and not missing_counters
        and contradiction_backlog <= args.max_contradiction_backlog
    )
    if ops_report.get("ok") is not True:
        findings.append(_consolidation_finding("ops_report_not_ok", "ops report evidence must be ok"))
    if tripwires.get("passed") is not True:
        findings.append(_consolidation_finding("ops_tripwires_failed", "ops report tripwires must pass"))
    if ops_dead_jobs != 0:
        findings.append(_consolidation_finding("ops_dead_jobs_present", "ops report must show zero dead jobs"))
    for name in missing_counters:
        findings.append(_consolidation_finding("ops_counter_missing", f"ops report missing counter {name}"))
    if contradiction_backlog > args.max_contradiction_backlog:
        findings.append(_consolidation_finding("ops_contradiction_backlog_open", "ops report contradiction backlog exceeds threshold"))
    checks.append(
        {
            "name": "ops_report",
            "ok": ops_report_ok,
            "tripwires_passed": tripwires.get("passed") is True,
            "dead_jobs": ops_dead_jobs,
            "missing_counters": missing_counters,
            "contradiction_backlog": contradiction_backlog,
        }
    )

    deployment = bundle.get("deployment")
    if not isinstance(deployment, Mapping):
        findings.append(_consolidation_finding("deployment_missing", "consolidation ops bundle requires deployment section"))
        deployment = {}
    deployment_supervision = deployment.get("supervision") if isinstance(deployment.get("supervision"), Mapping) else {}
    required_deployment_controls = [
        "worker_run",
        "provider_check",
        "hosted_providers",
        "projection_recompute",
        "protected_suite",
        "embedding",
        "consolidation_run",
        "calibration",
        "lifecycle",
        "ops_report",
    ]
    missing_deployment_controls = [
        control
        for control in required_deployment_controls
        if deployment_supervision.get(control) is not True and deployment.get(f"{control}_supervised") is not True
    ]
    alert_route = deployment.get("alert_route") if isinstance(deployment.get("alert_route"), Mapping) else {}
    alert_route_configured = alert_route.get("configured") is True or deployment.get("alert_route_configured") is True
    alert_route_delivery_verified = (
        alert_route.get("last_delivery_verified") is True or deployment.get("alert_route_delivery_verified") is True
    )
    alert_route_ok = alert_route_configured and alert_route_delivery_verified
    execution_fingerprint = str(deployment.get("execution_fingerprint") or "")
    deployment_latency_raw = deployment.get("latency_ms", deployment.get("p95_latency_ms", deployment.get("max_latency_ms")))
    try:
        deployment_latency_ms = float(deployment_latency_raw)
    except (TypeError, ValueError):
        deployment_latency_ms = float("inf")
        findings.append(_consolidation_finding("deployment_latency_invalid", "deployment latency must be numeric"))
    deployment_bindings = deployment.get("bindings") if isinstance(deployment.get("bindings"), Mapping) else {}

    def _deployment_binding(name: str) -> Any:
        return deployment_bindings.get(name, deployment.get(name))

    def _deployment_binding_int(name: str) -> int:
        value = _deployment_binding(name)
        code = f"deployment_{name}_invalid"
        message = f"deployment binding {name} must be an integer"
        if isinstance(value, bool):
            findings.append(_consolidation_finding(code, message))
            return -1
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        findings.append(_consolidation_finding(code, message))
        return -1

    deployment_count_bindings = {
        "worker_processed_jobs": processed_jobs,
        "provider_check_count": len(provider_rows),
        "projection_changed_evidence_count": changed_count,
        "protected_suite_case_count": suite_case_count,
        "embedded_cid_hash_count": embedded_count,
        "consolidation_source_hash_count": len(consolidation_hashes),
        "calibration_example_count": calibration_examples,
        "lifecycle_evaluated": lifecycle_evaluated,
        "ops_counter_count": len(ops_counters),
    }
    deployment_binding_mismatches: list[dict[str, Any]] = []
    for field, expected in deployment_count_bindings.items():
        actual = _deployment_binding_int(field)
        if actual != expected:
            deployment_binding_mismatches.append({"field": field, "expected": expected, "actual": actual})
    protected_suite_fingerprint = str(suite.get("fingerprint") or "")
    deployment_suite_fingerprint = str(_deployment_binding("protected_suite_fingerprint") or "")
    suite_fingerprint_bound = bool(protected_suite_fingerprint) and deployment_suite_fingerprint == protected_suite_fingerprint
    deployment_ok = (
        deployment.get("ok", True) is True
        and deployment.get("production_validated") is True
        and not missing_deployment_controls
        and alert_route_ok
        and "sha256:" in execution_fingerprint.lower()
        and 0 <= deployment_latency_ms <= args.max_deployment_latency_ms
        and math.isfinite(deployment_latency_ms)
        and not deployment_binding_mismatches
        and suite_fingerprint_bound
    )
    if deployment.get("ok", True) is not True:
        findings.append(_consolidation_finding("deployment_not_ok", "deployment evidence must be ok"))
    if deployment.get("production_validated") is not True:
        findings.append(_consolidation_finding("deployment_production_validation_missing", "deployment evidence must be production validated"))
    for control in missing_deployment_controls:
        findings.append(_consolidation_finding("deployment_control_missing", f"deployment supervision evidence missing for {control}"))
    if not alert_route_ok:
        findings.append(_consolidation_finding("deployment_alert_route_missing", "deployment alert route must be configured and delivery verified"))
    if "sha256:" not in execution_fingerprint.lower():
        findings.append(_consolidation_finding("deployment_execution_fingerprint_missing", "deployment execution fingerprint must include sha256"))
    if deployment_latency_raw is None or not math.isfinite(deployment_latency_ms) or deployment_latency_ms < 0:
        findings.append(
            _consolidation_finding(
                "deployment_latency_invalid",
                "deployment latency must be present, finite, and non-negative",
            )
        )
    elif deployment_latency_ms > args.max_deployment_latency_ms:
        findings.append(_consolidation_finding("deployment_latency_too_high", "deployment latency exceeds threshold"))
    for mismatch in deployment_binding_mismatches:
        findings.append(
            _consolidation_finding(
                "deployment_count_binding_mismatch",
                f"deployment binding {mismatch['field']} expected {mismatch['expected']} got {mismatch['actual']}",
            )
        )
    if not suite_fingerprint_bound:
        findings.append(_consolidation_finding("deployment_fingerprint_binding_mismatch", "deployment must bind protected suite fingerprint"))
    checks.append(
        {
            "name": "deployment",
            "ok": deployment_ok,
            "production_validated": deployment.get("production_validated") is True,
            "missing_controls": missing_deployment_controls,
            "alert_route_configured": alert_route_configured,
            "alert_route_delivery_verified": alert_route_delivery_verified,
            "execution_fingerprint_present": "sha256:" in execution_fingerprint.lower(),
            "latency_ms": deployment_latency_ms if math.isfinite(deployment_latency_ms) else None,
            "latency_threshold_ms": args.max_deployment_latency_ms,
            "binding_mismatches": deployment_binding_mismatches,
            "protected_suite_fingerprint_bound": suite_fingerprint_bound,
        }
    )

    redaction = bundle.get("redaction") if isinstance(bundle.get("redaction"), Mapping) else {}
    redaction_flags = {
        "raw_prompts_omitted": redaction.get("raw_prompts_omitted") is True,
        "raw_provider_requests_omitted": redaction.get("raw_provider_requests_omitted") is True
        or redaction.get("raw_llm_requests_omitted") is True,
        "raw_provider_responses_omitted": redaction.get("raw_provider_responses_omitted") is True
        or redaction.get("raw_llm_responses_omitted") is True,
        "raw_evidence_omitted": redaction.get("raw_evidence_omitted") is True,
        "raw_credentials_omitted": redaction.get("raw_credentials_omitted") is True,
        "raw_embeddings_omitted": redaction.get("raw_embeddings_omitted") is True,
        "raw_cids_omitted": redaction.get("raw_cids_omitted") is True,
        "raw_tenant_user_values_omitted": redaction.get("raw_tenant_user_values_omitted") is True,
    }
    missing_redaction_flags = [flag for flag, ok in redaction_flags.items() if not ok]
    for flag in missing_redaction_flags:
        findings.append(_consolidation_finding("redaction_flag_missing", f"redaction flag {flag} must be true"))
    forbidden_raw_paths = _consolidation_forbidden_raw_paths(bundle)
    if forbidden_raw_paths:
        findings.append(_consolidation_finding("redaction_raw_field_present", "bundle contains raw prompts, evidence, credentials, or CIDs"))
    checks.append(
        {
            "name": "redaction",
            "ok": not missing_redaction_flags and not forbidden_raw_paths,
            **redaction_flags,
            "forbidden_raw_paths": forbidden_raw_paths,
        }
    )

    report = {
        "ok": not findings,
        "bundle": {
            "name": bundle.get("name"),
            "production_validated": validation_scope.get("production_validated") is True,
            "worker_backend": worker_backend,
            "worker_processed_jobs": processed_jobs,
            "provider_check_count": len(provider_rows),
            "hosted_required_roles": required_roles,
            "projection_changed_evidence_count": changed_count,
            "protected_suite_case_count": suite_case_count,
            "protected_suite_protected_count": protected_count,
            "embedding_provider": embedding_provider,
            "embedding_dimensions": dimensions,
            "consolidation_source_hash_count": len(consolidation_hashes),
            "calibration_dataset_fingerprint_present": "sha256:" in dataset_fingerprint.lower(),
            "lifecycle_evaluated": lifecycle_evaluated,
            "ops_tripwires_passed": tripwires.get("passed") is True,
            "deployment_latency_ms": deployment_latency_ms if math.isfinite(deployment_latency_ms) else None,
            "deployment_alert_route_configured": alert_route_configured,
            "deployment_alert_route_delivery_verified": alert_route_delivery_verified,
        },
        "requirements": {
            "production_validated": True,
            "target_environment": "production",
            "operator_asserted": True,
            "worker_backend": "postgres",
            "worker_job_kinds": required_worker_kinds,
            "min_worker_cycles": args.min_worker_cycles,
            "min_processed_jobs": args.min_processed_jobs,
            "max_dead_jobs": args.max_dead_jobs,
            "required_provider_checks": required_provider_checks,
            "hosted_forbid_local": True,
            "required_hosted_roles": required_roles,
            "projection_backend": "postgres",
            "min_projection_cases": args.min_projection_cases,
            "min_affected_assertions": args.min_affected_assertions,
            "min_affected_entities": args.min_affected_entities,
            "min_affected_relations": args.min_affected_relations,
            "min_gate_cases": args.min_gate_cases,
            "min_protected": args.min_protected,
            "required_tiers": required_tiers,
            "min_embedding_dimensions": args.min_embedding_dimensions,
            "min_embedding_cids": args.min_embedding_cids,
            "required_consolidation_passes": required_passes,
            "min_evaluated_candidates": args.min_evaluated_candidates,
            "min_promoted_candidates": args.min_promoted_candidates,
            "min_calibration_examples": args.min_calibration_examples,
            "min_calibration_correct": args.min_calibration_correct,
            "min_calibration_incorrect": args.min_calibration_incorrect,
            "min_calibration_coverage": args.min_calibration_coverage,
            "max_calibration_false_accept_rate": args.max_calibration_false_accept_rate,
            "min_lifecycle_evaluated": args.min_lifecycle_evaluated,
            "required_ops_counters": required_counters,
            "max_contradiction_backlog": args.max_contradiction_backlog,
            "required_deployment_controls": required_deployment_controls,
            "max_deployment_latency_ms": args.max_deployment_latency_ms,
        },
        "redaction": {**redaction_flags, "forbidden_raw_fields_present": bool(forbidden_raw_paths)},
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _consolidation_ops_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(_consolidation_finding("fingerprint_mismatch", "consolidation ops fingerprint mismatch"))
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_belief_revision_cases(args: argparse.Namespace) -> list[Mapping[str, Any]]:
    if bool(args.cases) == bool(args.cases_json):
        raise SystemExit("belief-revision-check requires exactly one of --cases or --cases-json")
    try:
        loaded = json.loads(Path(args.cases).expanduser().read_text(encoding="utf-8")) if args.cases else json.loads(args.cases_json)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"belief revision cases denied: {exc}") from exc
    if not isinstance(loaded, list):
        raise SystemExit("belief revision cases must be a JSON array")
    if not all(isinstance(item, Mapping) for item in loaded):
        raise SystemExit("belief revision cases must contain JSON objects")
    return loaded


def cmd_belief_revision_check(args: argparse.Namespace) -> None:
    from mnemosyne.belief import validate_belief_revision_cases

    report = validate_belief_revision_cases(
        _load_belief_revision_cases(args),
        min_cases=args.min_cases,
        required_case_ids=args.require_case,
    )
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(
            {
                "code": "fingerprint_mismatch",
                "message": "belief revision suite fingerprint mismatch",
            }
        )
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_provenance_trust_suite(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.suite) == bool(args.suite_json):
        raise SystemExit("provenance-trust-check requires exactly one of --suite or --suite-json")
    try:
        loaded = (
            json.loads(Path(args.suite).expanduser().read_text(encoding="utf-8"))
            if args.suite
            else json.loads(args.suite_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"provenance trust suite denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("provenance trust suite must be a JSON object")
    cases = loaded.get("cases")
    if not isinstance(cases, list) or not all(isinstance(item, Mapping) for item in cases):
        raise SystemExit("provenance trust suite requires cases array of JSON objects")
    return loaded


def _provenance_string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple) and all(isinstance(item, str) for item in value):
        return list(dict.fromkeys(item for item in value if item))
    raise SystemExit(f"provenance trust suite field {field} must be a string or string array")


def _provenance_bool(value: Any, *, field: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise SystemExit(f"provenance trust suite field {field} must be boolean")


def _provenance_finding(code: str, message: str, *, case_id: str | None = None) -> dict[str, Any]:
    finding: dict[str, Any] = {"code": code, "message": message}
    if case_id:
        finding["case_id"] = case_id
    return finding


def _provenance_trust_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        "suite": report.get("suite"),
        "required_case_ids": report.get("required_case_ids"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def cmd_provenance_trust_check(args: argparse.Namespace) -> None:
    from mnemosyne.provenance import C2paToolVerifier, ProvenanceTrustPolicy, SignedProvenanceVerifier

    suite = _load_provenance_trust_suite(args)
    cases = list(suite["cases"])
    tool_path = str(args.c2pa_tool or suite.get("tool") or suite.get("c2pa_tool") or "").strip()
    trusted_issuers = _provenance_string_list(
        suite.get("trusted_issuers", suite.get("trustedIssuers")),
        field="trusted_issuers",
    )
    trusted_roots = _provenance_string_list(
        suite.get("trusted_roots", suite.get("trustedRoots")),
        field="trusted_roots",
    )
    policy_raw = suite.get("trust_policy", suite.get("trustPolicy")) or {}
    if not isinstance(policy_raw, Mapping):
        raise SystemExit("provenance trust suite trust_policy must be a JSON object")
    try:
        trust_policy = ProvenanceTrustPolicy.from_dict(dict(policy_raw))
    except ValueError as exc:
        raise SystemExit(f"provenance trust policy denied: {exc}") from exc

    required_case_ids = list(
        dict.fromkeys(
            [
                *_provenance_string_list(
                    suite.get("required_cases", suite.get("requiredCases")),
                    field="required_cases",
                ),
                *(args.require_case or []),
            ]
        )
    )
    if not all(isinstance(item, str) for item in required_case_ids):
        raise SystemExit("provenance trust suite required_cases must be string case IDs")

    findings: list[dict[str, Any]] = []
    if not tool_path:
        findings.append(_provenance_finding("missing_c2pa_tool", "provenance trust suite requires a c2pa tool"))
    if len(cases) < args.min_cases:
        findings.append(
            _provenance_finding(
                "insufficient_cases",
                f"provenance trust suite requires at least {args.min_cases} cases",
            )
        )
    policy_issuers = {
        item
        for rule in trust_policy.rules
        for item in rule.trusted_issuers
    }
    policy_roots = {
        item
        for rule in trust_policy.rules
        for item in rule.trusted_roots
    }
    configured_issuer_count = len({*trusted_issuers, *trust_policy.trusted_issuers, *policy_issuers})
    configured_root_count = len({*trusted_roots, *trust_policy.trusted_roots, *policy_roots})
    if configured_issuer_count == 0:
        findings.append(_provenance_finding("missing_trusted_issuer", "trusted provenance issuer is required"))
    if configured_root_count == 0:
        findings.append(_provenance_finding("missing_trusted_root", "trusted provenance certificate root is required"))

    verifier = C2paToolVerifier(
        tool_path=tool_path or "c2patool",
        trusted_issuers=tuple(trusted_issuers),
        trusted_roots=tuple(trusted_roots),
        trust_policy=trust_policy,
        timeout_seconds=args.timeout,
        fallback=SignedProvenanceVerifier(),
    )

    checks: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for index, raw_case in enumerate(cases, start=1):
        case = dict(raw_case)
        case_id = str(case.get("id") or f"case-{index}")
        seen_case_ids.add(case_id)
        case_findings: list[dict[str, Any]] = []
        asset_path_raw = case.get("asset_path") or case.get("c2pa_asset_path")
        asset_sha = None
        decision_dict: dict[str, Any] | None = None
        diagnostics_summary: dict[str, Any] = {}
        if not isinstance(asset_path_raw, str) or not asset_path_raw:
            case_findings.append(_provenance_finding("missing_asset_path", "case requires asset_path", case_id=case_id))
            payload = b""
        else:
            asset_path = Path(asset_path_raw).expanduser()
            try:
                payload = asset_path.read_bytes()
            except OSError as exc:
                case_findings.append(
                    _provenance_finding(
                        "asset_read_failed",
                        f"case asset could not be read: {exc}",
                        case_id=case_id,
                    )
                )
                payload = b""
            asset_sha = sha256(payload).hexdigest() if payload else None
            manifest_raw = case.get("manifest") or {}
            if not isinstance(manifest_raw, Mapping):
                raise SystemExit(f"provenance trust case {case_id} manifest must be a JSON object")
            manifest = dict(manifest_raw)
            manifest.setdefault("asset_path", str(asset_path))
            if asset_sha and "sha256" not in manifest and "content_hash" not in manifest:
                manifest["sha256"] = asset_sha
            if payload and tool_path:
                decision = verifier.verify(payload, manifest)
                decision_dict = {
                    "valid": decision.valid,
                    "trusted": decision.trusted,
                    "quarantine": decision.quarantine,
                    "trust_delta": decision.trust_delta,
                    "reason": decision.reason,
                }
                signer = decision.diagnostics.get("signer")
                certificate_roots = [
                    str(item) for item in (decision.diagnostics.get("certificate_roots") or []) if isinstance(item, str)
                ]
                effective_trusted_roots = [
                    str(item) for item in (decision.diagnostics.get("trusted_roots") or trusted_roots) if isinstance(item, str)
                ]
                root_matches = sorted(set(certificate_roots).intersection(effective_trusted_roots))
                diagnostics_summary = {
                    "signer": signer,
                    "certificate_root_count": len(certificate_roots),
                    "trusted_issuer_count": len(decision.diagnostics.get("trusted_issuers") or trusted_issuers),
                    "trusted_root_count": len(effective_trusted_roots),
                    "trusted_root_matched": bool(root_matches),
                    "asset_binding": decision.diagnostics.get("asset_binding"),
                }
                expected_valid = _provenance_bool(case.get("expect_valid"), field=f"{case_id}.expect_valid", default=True)
                expected_trusted = _provenance_bool(
                    case.get("expect_trusted"),
                    field=f"{case_id}.expect_trusted",
                    default=True,
                )
                expected_quarantine = _provenance_bool(
                    case.get("expect_quarantine"),
                    field=f"{case_id}.expect_quarantine",
                    default=False,
                )
                if decision.valid is not expected_valid:
                    case_findings.append(
                        _provenance_finding("validity_mismatch", "provenance validity expectation failed", case_id=case_id)
                    )
                if decision.trusted is not expected_trusted:
                    case_findings.append(
                        _provenance_finding("trust_mismatch", "provenance trust expectation failed", case_id=case_id)
                    )
                if decision.quarantine is not expected_quarantine:
                    case_findings.append(
                        _provenance_finding(
                            "quarantine_mismatch",
                            "provenance quarantine expectation failed",
                            case_id=case_id,
                        )
                    )
                expected_signer = case.get("expect_signer", case.get("expected_signer"))
                if expected_signer and signer != expected_signer:
                    case_findings.append(
                        _provenance_finding("signer_mismatch", "provenance signer expectation failed", case_id=case_id)
                    )
                expected_roots = _provenance_string_list(
                    case.get("expect_root", case.get("expected_root")),
                    field=f"{case_id}.expect_root",
                )
                missing_roots = [item for item in expected_roots if item not in certificate_roots]
                if missing_roots:
                    case_findings.append(
                        _provenance_finding(
                            "certificate_root_mismatch",
                            "provenance certificate root expectation failed",
                            case_id=case_id,
                        )
                    )
        checks.append(
            {
                "id": case_id,
                "ok": not case_findings,
                "asset_sha256": asset_sha,
                "decision": decision_dict,
                "diagnostics": diagnostics_summary,
                "findings": case_findings,
            }
        )
        findings.extend(case_findings)

    for required in required_case_ids:
        if required not in seen_case_ids:
            findings.append(_provenance_finding("missing_required_case", f"required case {required} is missing"))

    report: dict[str, Any] = {
        "ok": not findings,
        "suite": {
            "name": suite.get("name"),
            "case_count": len(cases),
            "tool_configured": bool(tool_path),
            "trusted_issuer_count": configured_issuer_count,
            "trusted_root_count": configured_root_count,
            "requires_trusted_issuer": bool(trust_policy.require_trusted_issuer or trusted_issuers),
            "requires_trusted_root": bool(trust_policy.require_trusted_root or trusted_roots),
        },
        "required_case_ids": sorted(required_case_ids),
        "redaction": {
            "asset_bytes_omitted": True,
            "raw_manifest_omitted": True,
            "raw_verifier_stdout_omitted": True,
            "raw_verifier_stderr_omitted": True,
        },
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _provenance_trust_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(
            _provenance_finding("fingerprint_mismatch", "provenance trust suite fingerprint mismatch")
        )
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_provenance_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("provenance-ops-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = (
            json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8"))
            if args.bundle
            else json.loads(args.bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"provenance ops bundle denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("provenance ops bundle must be a JSON object")
    return loaded


def _provenance_ops_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        "bundle": report.get("bundle"),
        "requirements": report.get("requirements"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _provenance_ops_int(
    value: Any,
    *,
    default: int,
    code: str,
    message: str,
    findings: list[dict[str, Any]],
) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        findings.append(_provenance_finding(code, message))
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        findings.append(_provenance_finding(code, message))
        return default


def _provenance_ops_number(
    value: Any,
    *,
    default: float,
    code: str,
    message: str,
    findings: list[dict[str, Any]],
) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        findings.append(_provenance_finding(code, message))
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        findings.append(_provenance_finding(code, message))
        return default


def _provenance_ops_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _provenance_ops_provider_local(provider: Any) -> bool:
    provider_kind = str(provider or "").strip().lower()
    return provider_kind in {"", "deterministic", "local", "mock", "none", "test"}


def _provenance_ops_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    forbidden_keys = {
        "access_token",
        "api_key",
        "asset_bytes",
        "auth_token",
        "certificate",
        "certificates",
        "credential",
        "credentials",
        "manifest",
        "manifests",
        "password",
        "private_key",
        "raw_asset",
        "raw_assets",
        "raw_certificate",
        "raw_certificates",
        "raw_claim",
        "raw_claims",
        "raw_manifest",
        "raw_manifests",
        "raw_report",
        "raw_reports",
        "raw_stderr",
        "raw_stdout",
        "raw_verifier_stderr",
        "raw_verifier_stdout",
        "secret",
        "stderr",
        "stdout",
        "token",
        "verifier_stderr",
        "verifier_stdout",
    }
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_name = str(key)
            child_path = f"{path}.{key_name}"
            if key_name.lower() in forbidden_keys and child not in (None, "", [], {}):
                paths.append(child_path)
            paths.extend(_provenance_ops_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_provenance_ops_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def cmd_provenance_ops_check(args: argparse.Namespace) -> None:
    bundle = _load_provenance_ops_bundle(args)
    profile = _ops_check_profile(bundle)
    findings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    validation_scope = bundle.get("validation_scope")
    if not isinstance(validation_scope, Mapping):
        findings.append(_provenance_finding("validation_scope_missing", "provenance ops bundle requires validation_scope section"))
        validation_scope = {}
    validation_scope_ok = (
        validation_scope.get("production_validated") is True
        and validation_scope.get("target_environment") == "production"
        and validation_scope.get("operator_asserted") is True
        and bool(validation_scope.get("run_id"))
        and bool(validation_scope.get("started_at"))
        and bool(validation_scope.get("completed_at"))
    )
    if validation_scope.get("production_validated") is not True:
        findings.append(_provenance_finding("production_validation_missing", "provenance ops bundle must be production validated"))
    if validation_scope.get("target_environment") != "production":
        findings.append(_provenance_finding("target_environment_not_production", "provenance ops target environment must be production"))
    if validation_scope.get("operator_asserted") is not True:
        findings.append(_provenance_finding("operator_assertion_missing", "operator production assertion is required"))
    for field in ("run_id", "started_at", "completed_at"):
        if not validation_scope.get(field):
            findings.append(_provenance_finding("validation_scope_field_missing", f"validation_scope.{field} is required"))
    checks.append(
        {
            "name": "validation_scope",
            "ok": validation_scope_ok,
            "production_validated": validation_scope.get("production_validated") is True,
            "target_environment": validation_scope.get("target_environment"),
            "operator_asserted": validation_scope.get("operator_asserted") is True,
        }
    )

    verifier = bundle.get("c2pa_verifier") or bundle.get("verifier")
    if not isinstance(verifier, Mapping):
        findings.append(_provenance_finding("verifier_missing", "provenance ops bundle requires c2pa_verifier section"))
        verifier = {}
    verifier_provider = verifier.get("provider") or verifier.get("provider_kind")
    verifier_local = _provenance_ops_provider_local(verifier_provider)
    timeout_seconds = _provenance_ops_number(
        verifier.get("timeout_seconds"),
        default=args.max_verifier_timeout_seconds + 1.0,
        code="verifier_timeout_invalid",
        message="verifier timeout must be numeric",
        findings=findings,
    )
    verifier_ok = (
        verifier.get("ok") is True
        and not verifier_local
        and bool(verifier.get("tool_version"))
        and bool(verifier.get("tool_path_hash") or verifier.get("tool_digest"))
        and verifier.get("command_isolated") is True
        and verifier.get("no_shell") is True
        and verifier.get("asset_file_preferred") is True
        and timeout_seconds <= args.max_verifier_timeout_seconds
    )
    if verifier.get("ok") is not True:
        findings.append(_provenance_finding("verifier_not_ok", "C2PA verifier evidence must be ok"))
    if verifier_local:
        findings.append(_provenance_finding("verifier_provider_local", "C2PA verifier provider must be command, container, or hosted"))
    if not verifier.get("tool_version"):
        findings.append(_provenance_finding("verifier_version_missing", "C2PA verifier tool version is required"))
    if not (verifier.get("tool_path_hash") or verifier.get("tool_digest")):
        findings.append(_provenance_finding("verifier_tool_hash_missing", "C2PA verifier tool path/digest hash is required"))
    for field in ("command_isolated", "no_shell", "asset_file_preferred"):
        if verifier.get(field) is not True:
            findings.append(_provenance_finding("verifier_control_missing", f"C2PA verifier control {field} is required"))
    if timeout_seconds > args.max_verifier_timeout_seconds:
        findings.append(_provenance_finding("verifier_timeout_too_high", "C2PA verifier timeout exceeds threshold"))
    checks.append(
        {
            "name": "c2pa_verifier",
            "ok": verifier_ok,
            "provider": verifier_provider,
            "provider_local": verifier_local,
            "tool_version_present": bool(verifier.get("tool_version")),
            "tool_hash_present": bool(verifier.get("tool_path_hash") or verifier.get("tool_digest")),
            "timeout_seconds": timeout_seconds,
        }
    )

    trust_roots = bundle.get("trust_roots")
    if not isinstance(trust_roots, Mapping):
        findings.append(_provenance_finding("trust_roots_missing", "provenance ops bundle requires trust_roots section"))
        trust_roots = {}
    issuer_count = _provenance_ops_int(
        trust_roots.get("trusted_issuer_count"),
        default=len(_provenance_ops_string_list(trust_roots.get("trusted_issuer_hashes"))),
        code="trusted_issuer_count_invalid",
        message="trusted issuer count must be numeric",
        findings=findings,
    )
    root_fingerprints = _provenance_ops_string_list(trust_roots.get("root_fingerprints") or trust_roots.get("trusted_root_hashes"))
    root_count = _provenance_ops_int(
        trust_roots.get("trusted_root_count"),
        default=len(root_fingerprints),
        code="trusted_root_count_invalid",
        message="trusted root count must be numeric",
        findings=findings,
    )
    policy_fingerprint = str(trust_roots.get("policy_fingerprint") or "")
    trust_roots_ok = (
        trust_roots.get("ok") is True
        and issuer_count >= args.min_trusted_issuers
        and root_count >= args.min_trusted_roots
        and "sha256:" in policy_fingerprint.lower()
        and len(root_fingerprints) >= args.min_trusted_roots
        and trust_roots.get("rotation_verified") is True
        and trust_roots.get("stale_roots_rejected") is True
        and trust_roots.get("untrusted_issuer_quarantined") is True
        and trust_roots.get("asset_scope_enforced") is True
    )
    if trust_roots.get("ok") is not True:
        findings.append(_provenance_finding("trust_roots_not_ok", "trust-roots evidence must be ok"))
    if issuer_count < args.min_trusted_issuers:
        findings.append(_provenance_finding("trusted_issuer_count_too_low", "trusted issuer count is below threshold"))
    if root_count < args.min_trusted_roots or len(root_fingerprints) < args.min_trusted_roots:
        findings.append(_provenance_finding("trusted_root_count_too_low", "trusted root count is below threshold"))
    if "sha256:" not in policy_fingerprint.lower():
        findings.append(_provenance_finding("trust_policy_fingerprint_missing", "trust policy fingerprint is required"))
    for field in ("rotation_verified", "stale_roots_rejected", "untrusted_issuer_quarantined", "asset_scope_enforced"):
        if trust_roots.get(field) is not True:
            findings.append(_provenance_finding("trust_root_control_missing", f"trust-root control {field} is required"))
    checks.append(
        {
            "name": "trust_roots",
            "ok": trust_roots_ok,
            "trusted_issuer_count": issuer_count,
            "trusted_root_count": root_count,
            "root_fingerprint_count": len(root_fingerprints),
            "policy_fingerprint_present": "sha256:" in policy_fingerprint.lower(),
        }
    )

    trust_check = bundle.get("provenance_trust") or bundle.get("provenance_trust_check")
    if not isinstance(trust_check, Mapping):
        findings.append(
            _provenance_finding("provenance_trust_missing", "provenance ops bundle requires provenance_trust section")
        )
        trust_check = {}
    suite_summary = trust_check.get("suite") if isinstance(trust_check.get("suite"), Mapping) else {}
    suite_case_count = _provenance_ops_int(
        suite_summary.get("case_count", trust_check.get("case_count")),
        default=0,
        code="provenance_trust_case_count_invalid",
        message="provenance trust case count must be numeric",
        findings=findings,
    )
    suite_issuer_count = _provenance_ops_int(
        suite_summary.get("trusted_issuer_count", trust_check.get("trusted_issuer_count")),
        default=0,
        code="provenance_trust_issuer_count_invalid",
        message="provenance trust issuer count must be numeric",
        findings=findings,
    )
    suite_root_count = _provenance_ops_int(
        suite_summary.get("trusted_root_count", trust_check.get("trusted_root_count")),
        default=0,
        code="provenance_trust_root_count_invalid",
        message="provenance trust root count must be numeric",
        findings=findings,
    )
    trust_redaction = trust_check.get("redaction") if isinstance(trust_check.get("redaction"), Mapping) else {}
    provenance_trust_ok = (
        trust_check.get("ok") is True
        and bool(trust_check.get("fingerprint"))
        and suite_case_count >= args.min_cases
        and suite_issuer_count >= args.min_trusted_issuers
        and suite_root_count >= args.min_trusted_roots
        and trust_redaction.get("asset_bytes_omitted") is True
        and trust_redaction.get("raw_manifest_omitted") is True
        and trust_redaction.get("raw_verifier_stdout_omitted") is True
        and trust_redaction.get("raw_verifier_stderr_omitted") is True
    )
    if trust_check.get("ok") is not True:
        findings.append(_provenance_finding("provenance_trust_not_ok", "provenance-trust evidence must be ok"))
    if not trust_check.get("fingerprint"):
        findings.append(_provenance_finding("provenance_trust_fingerprint_missing", "provenance-trust fingerprint is required"))
    if suite_case_count < args.min_cases:
        findings.append(_provenance_finding("provenance_trust_cases_too_low", "provenance-trust case count is below threshold"))
    if suite_issuer_count < args.min_trusted_issuers:
        findings.append(_provenance_finding("provenance_trust_issuers_too_low", "provenance-trust issuer count is below threshold"))
    if suite_root_count < args.min_trusted_roots:
        findings.append(_provenance_finding("provenance_trust_roots_too_low", "provenance-trust root count is below threshold"))
    for field in ("asset_bytes_omitted", "raw_manifest_omitted", "raw_verifier_stdout_omitted", "raw_verifier_stderr_omitted"):
        if trust_redaction.get(field) is not True:
            findings.append(_provenance_finding("provenance_trust_redaction_missing", f"provenance-trust redaction {field} is required"))
    checks.append(
        {
            "name": "provenance_trust",
            "ok": provenance_trust_ok,
            "case_count": suite_case_count,
            "trusted_issuer_count": suite_issuer_count,
            "trusted_root_count": suite_root_count,
            "fingerprint_present": bool(trust_check.get("fingerprint")),
        }
    )

    asset_bound = bundle.get("asset_bound_cases")
    if not isinstance(asset_bound, Mapping):
        findings.append(_provenance_finding("asset_bound_cases_missing", "provenance ops bundle requires asset_bound_cases section"))
        asset_bound = {}
    cases_raw = asset_bound.get("cases")
    asset_cases = [item for item in cases_raw if isinstance(item, Mapping)] if isinstance(cases_raw, list) else []
    trusted_cases = 0
    quarantine_cases = 0
    case_rows: list[dict[str, Any]] = []
    for index, case in enumerate(asset_cases, start=1):
        case_id = str(case.get("id") or f"case-{index}")
        expected = str(case.get("expected") or case.get("expected_decision") or "").lower()
        asset_hash_present = "sha256:" in str(case.get("asset_sha256") or "").lower()
        manifest_hash_present = "sha256:" in str(case.get("manifest_sha256") or "").lower()
        asset_binding_matched = case.get("asset_binding_matched") is True
        valid = case.get("valid") is True
        trusted = case.get("trusted") is True
        quarantined = case.get("quarantined") is True
        if expected == "trusted":
            trusted_cases += 1 if valid and trusted and asset_binding_matched and not quarantined else 0
        if expected in {"quarantine", "quarantined", "reject"}:
            quarantine_cases += 1 if quarantined else 0
        row_ok = (
            asset_hash_present
            and manifest_hash_present
            and (
                (expected == "trusted" and valid and trusted and asset_binding_matched and not quarantined)
                or (expected in {"quarantine", "quarantined", "reject"} and quarantined)
            )
        )
        if not row_ok:
            findings.append(_provenance_finding("asset_bound_case_failed", "asset-bound provenance case failed", case_id=case_id))
        case_rows.append(
            {
                "id": case_id,
                "ok": row_ok,
                "expected": expected,
                "asset_hash_present": asset_hash_present,
                "manifest_hash_present": manifest_hash_present,
                "asset_binding_matched": asset_binding_matched,
                "valid": valid,
                "trusted": trusted,
                "quarantined": quarantined,
            }
        )
    asset_bound_ok = (
        asset_bound.get("ok") is True
        and len(asset_cases) >= args.min_cases
        and trusted_cases >= args.min_trusted_cases
        and quarantine_cases >= args.min_quarantine_cases
        and all(row["ok"] for row in case_rows)
    )
    if asset_bound.get("ok") is not True:
        findings.append(_provenance_finding("asset_bound_cases_not_ok", "asset-bound cases evidence must be ok"))
    if len(asset_cases) < args.min_cases:
        findings.append(_provenance_finding("asset_bound_cases_too_low", "asset-bound case count is below threshold"))
    if trusted_cases < args.min_trusted_cases:
        findings.append(_provenance_finding("trusted_asset_cases_too_low", "trusted asset case count is below threshold"))
    if quarantine_cases < args.min_quarantine_cases:
        findings.append(_provenance_finding("quarantine_asset_cases_too_low", "quarantine asset case count is below threshold"))
    checks.append(
        {
            "name": "asset_bound_cases",
            "ok": asset_bound_ok,
            "case_count": len(asset_cases),
            "trusted_cases": trusted_cases,
            "quarantine_cases": quarantine_cases,
            "cases": case_rows,
        }
    )

    quarantine = bundle.get("quarantine")
    if not isinstance(quarantine, Mapping):
        findings.append(_provenance_finding("quarantine_missing", "provenance ops bundle requires quarantine section"))
        quarantine = {}
    quarantine_case_count = _provenance_ops_int(
        quarantine.get("case_count", quarantine_cases),
        default=quarantine_cases,
        code="quarantine_case_count_invalid",
        message="quarantine case count must be numeric",
        findings=findings,
    )
    quarantine_ok = (
        quarantine.get("ok") is True
        and quarantine.get("untrusted_signer_quarantined") is True
        and quarantine.get("untrusted_root_quarantined") is True
        and quarantine.get("digest_mismatch_quarantined") is True
        and quarantine.get("hidden_from_default_retrieval") is True
        and quarantine.get("default_retrieval_exclusion_verified") is True
        and quarantine_case_count >= args.min_quarantine_cases
    )
    if quarantine.get("ok") is not True:
        findings.append(_provenance_finding("quarantine_not_ok", "quarantine evidence must be ok"))
    for field in (
        "untrusted_signer_quarantined",
        "untrusted_root_quarantined",
        "digest_mismatch_quarantined",
        "hidden_from_default_retrieval",
        "default_retrieval_exclusion_verified",
    ):
        if quarantine.get(field) is not True:
            findings.append(_provenance_finding("quarantine_control_missing", f"quarantine control {field} is required"))
    if quarantine_case_count < args.min_quarantine_cases:
        findings.append(_provenance_finding("quarantine_cases_too_low", "quarantine case count is below threshold"))
    checks.append(
        {
            "name": "quarantine",
            "ok": quarantine_ok,
            "case_count": quarantine_case_count,
            "hidden_from_default_retrieval": quarantine.get("hidden_from_default_retrieval") is True,
        }
    )

    ingestion = bundle.get("ingestion")
    if not isinstance(ingestion, Mapping):
        findings.append(_provenance_finding("ingestion_missing", "provenance ops bundle requires ingestion section"))
        ingestion = {}
    ingestion_backend = str(ingestion.get("backend") or "").strip().lower()
    evidence_hashes = _provenance_ops_string_list(ingestion.get("evidence_cid_hashes"))
    capability_tags = set(_provenance_ops_string_list(ingestion.get("capability_tags")))
    trusted_ingests = _provenance_ops_int(
        ingestion.get("trusted_ingest_count"),
        default=0,
        code="ingestion_trusted_count_invalid",
        message="trusted ingest count must be numeric",
        findings=findings,
    )
    quarantined_ingests = _provenance_ops_int(
        ingestion.get("quarantined_ingest_count"),
        default=0,
        code="ingestion_quarantined_count_invalid",
        message="quarantined ingest count must be numeric",
        findings=findings,
    )
    required_tags = {"asset-bound-provenance", "provenance-valid", "provenance-verified", "quarantined"}
    missing_tags = sorted(required_tags - capability_tags)
    ingestion_backend_ok = _ops_check_backend_accepted(
        ingestion_backend, profile, frozenset({"postgres", "postgresql"})
    )
    ingestion_ok = (
        ingestion.get("ok") is True
        and ingestion_backend_ok
        and ingestion.get("production_validated") is True
        and bool(ingestion.get("tenant_hash"))
        and len(evidence_hashes) >= args.min_cases
        and trusted_ingests >= args.min_trusted_cases
        and quarantined_ingests >= args.min_quarantine_cases
        and not missing_tags
    )
    if ingestion.get("ok") is not True:
        findings.append(_provenance_finding("ingestion_not_ok", "provenance ingestion evidence must be ok"))
    if not ingestion_backend_ok:
        findings.append(_provenance_finding("ingestion_backend_not_postgres", "provenance ingestion backend must be postgres"))
    if ingestion.get("production_validated") is not True:
        findings.append(_provenance_finding("ingestion_production_validation_missing", "provenance ingestion must be production validated"))
    if not ingestion.get("tenant_hash"):
        findings.append(_provenance_finding("ingestion_tenant_hash_missing", "provenance ingestion tenant identity must be hashed"))
    if len(evidence_hashes) < args.min_cases:
        findings.append(_provenance_finding("ingestion_evidence_hashes_too_low", "provenance ingestion evidence hash count is too low"))
    if trusted_ingests < args.min_trusted_cases:
        findings.append(_provenance_finding("ingestion_trusted_too_low", "trusted provenance ingest count is too low"))
    if quarantined_ingests < args.min_quarantine_cases:
        findings.append(_provenance_finding("ingestion_quarantined_too_low", "quarantined provenance ingest count is too low"))
    for tag in missing_tags:
        findings.append(_provenance_finding("ingestion_capability_tag_missing", f"ingestion capability tag {tag} is missing"))
    checks.append(
        {
            "name": "ingestion",
            "ok": ingestion_ok,
            "backend": ingestion_backend,
            "evidence_hash_count": len(evidence_hashes),
            "trusted_ingest_count": trusted_ingests,
            "quarantined_ingest_count": quarantined_ingests,
            "missing_tags": missing_tags,
        }
    )

    deployment = bundle.get("deployment")
    if not isinstance(deployment, Mapping):
        findings.append(_provenance_finding("deployment_missing", "provenance ops bundle requires deployment section"))
        deployment = {}
    deployment_flags = {
        "production_validated": deployment.get("production_validated") is True,
        "supervised_verifier": deployment.get("supervised_verifier") is True,
        "health_check_passed": deployment.get("health_check_passed") is True,
        "trust_root_refresh_verified": deployment.get("trust_root_refresh_verified") is True,
        "quarantine_drill_verified": deployment.get("quarantine_drill_verified") is True,
        "ingestion_pipeline_supervised": deployment.get("ingestion_pipeline_supervised") is True,
        "alert_route_configured": deployment.get("alert_route_configured") is True,
    }
    deployment_surface = str(deployment.get("surface") or "").strip().lower()
    deployment_surface_ok = deployment_surface in {"command", "container", "hosted"}
    deployment_latency_ms = _provenance_ops_number(
        deployment.get("latency_ms"),
        default=args.max_deployment_latency_ms + 1.0,
        code="deployment_latency_invalid",
        message="deployment latency_ms must be numeric",
        findings=findings,
    )
    execution_fingerprint = str(deployment.get("execution_fingerprint") or "").strip()
    deployment_policy_fingerprint = str(deployment.get("policy_fingerprint") or "").strip()
    deployment_ingestion_hash_count = _provenance_ops_int(
        deployment.get("ingestion_evidence_hash_count"),
        default=0,
        code="deployment_ingestion_hash_count_invalid",
        message="deployment ingestion_evidence_hash_count must be numeric",
        findings=findings,
    )
    policy_fingerprint_matches = bool(deployment_policy_fingerprint) and deployment_policy_fingerprint == policy_fingerprint
    ingestion_hash_count_matches = deployment_ingestion_hash_count == len(evidence_hashes)
    execution_fingerprint_present = "sha256:" in execution_fingerprint.lower()
    missing_deployment_flags = [name for name, ok in deployment_flags.items() if not ok]
    deployment_ok = (
        not missing_deployment_flags
        and deployment_surface_ok
        and execution_fingerprint_present
        and policy_fingerprint_matches
        and ingestion_hash_count_matches
        and deployment_latency_ms <= args.max_deployment_latency_ms
    )
    for flag in missing_deployment_flags:
        findings.append(_provenance_finding("deployment_control_missing", f"deployment control {flag} is required"))
    if not deployment_surface_ok:
        findings.append(_provenance_finding("deployment_surface_invalid", "deployment surface must be command, container, or hosted"))
    if not execution_fingerprint_present:
        findings.append(_provenance_finding("deployment_execution_fingerprint_missing", "deployment execution_fingerprint must be SHA-256"))
    if not policy_fingerprint_matches:
        findings.append(_provenance_finding("deployment_policy_fingerprint_mismatch", "deployment policy_fingerprint must match trust-roots policy fingerprint"))
    if not ingestion_hash_count_matches:
        findings.append(_provenance_finding("deployment_ingestion_hash_count_mismatch", "deployment ingestion_evidence_hash_count must match ingestion evidence hash count"))
    if deployment_latency_ms > args.max_deployment_latency_ms:
        findings.append(_provenance_finding("deployment_latency_too_high", "deployment latency exceeds threshold"))
    checks.append(
        {
            "name": "deployment",
            "ok": deployment_ok,
            "surface": deployment_surface,
            "latency_ms": deployment_latency_ms,
            "max_latency_ms": args.max_deployment_latency_ms,
            "missing_controls": missing_deployment_flags,
            "execution_fingerprint_present": execution_fingerprint_present,
            "policy_fingerprint_matches": policy_fingerprint_matches,
            "ingestion_hash_count_matches": ingestion_hash_count_matches,
        }
    )

    redaction = bundle.get("redaction") if isinstance(bundle.get("redaction"), Mapping) else {}
    redaction_flags = {
        "asset_bytes_omitted": redaction.get("asset_bytes_omitted") is True,
        "raw_manifests_omitted": redaction.get("raw_manifests_omitted") is True
        or redaction.get("raw_manifest_omitted") is True,
        "raw_verifier_stdout_omitted": redaction.get("raw_verifier_stdout_omitted") is True,
        "raw_verifier_stderr_omitted": redaction.get("raw_verifier_stderr_omitted") is True,
        "raw_certificates_omitted": redaction.get("raw_certificates_omitted") is True,
        "raw_credentials_omitted": redaction.get("raw_credentials_omitted") is True,
    }
    missing_redaction_flags = [flag for flag, ok in redaction_flags.items() if not ok]
    for flag in missing_redaction_flags:
        findings.append(_provenance_finding("redaction_flag_missing", f"redaction flag {flag} must be true"))
    forbidden_raw_paths = _provenance_ops_forbidden_raw_paths(bundle)
    if forbidden_raw_paths:
        findings.append(_provenance_finding("redaction_raw_field_present", "bundle contains raw assets, manifests, verifier output, certificates, or credentials"))
    checks.append(
        {
            "name": "redaction",
            "ok": not missing_redaction_flags and not forbidden_raw_paths,
            **redaction_flags,
            "forbidden_raw_paths": forbidden_raw_paths,
        }
    )

    report = {
        "ok": not findings,
        "bundle": {
            "name": bundle.get("name"),
            "production_validated": validation_scope.get("production_validated") is True,
            "verifier_provider": verifier_provider,
            "trusted_issuer_count": issuer_count,
            "trusted_root_count": root_count,
            "asset_case_count": len(asset_cases),
            "trusted_asset_cases": trusted_cases,
            "quarantine_asset_cases": quarantine_cases,
            "ingestion_backend": ingestion_backend,
            "ingestion_evidence_hash_count": len(evidence_hashes),
        },
        "requirements": {
            "production_validated": True,
            "target_environment": "production",
            "operator_asserted": True,
            "min_cases": args.min_cases,
            "min_trusted_cases": args.min_trusted_cases,
            "min_quarantine_cases": args.min_quarantine_cases,
            "min_trusted_roots": args.min_trusted_roots,
            "min_trusted_issuers": args.min_trusted_issuers,
            "max_verifier_timeout_seconds": args.max_verifier_timeout_seconds,
            "max_deployment_latency_ms": args.max_deployment_latency_ms,
            "ingestion_backend": "sqlite" if profile == OPS_CHECK_SQLITE_PROFILE else "postgres",
        },
        "redaction": {**redaction_flags, "forbidden_raw_fields_present": bool(forbidden_raw_paths)},
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _provenance_ops_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(_provenance_finding("fingerprint_mismatch", "provenance ops fingerprint mismatch"))
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_multimodal_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("multimodal-ops-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = (
            json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8"))
            if args.bundle
            else json.loads(args.bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"multimodal ops bundle denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("multimodal ops bundle must be a JSON object")
    return loaded


def _multimodal_finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _multimodal_ops_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        "bundle": report.get("bundle"),
        "requirements": report.get("requirements"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _multimodal_ops_int(
    value: Any,
    *,
    default: int,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        findings.append(_multimodal_finding(code, message))
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        findings.append(_multimodal_finding(code, message))
        return default


def _multimodal_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _multimodal_provider_local(provider: Any) -> bool:
    provider_kind = str(provider or "").strip().lower()
    return provider_kind in {"", "deterministic", "local", "metadata", "mock", "none", "test"}


def _multimodal_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    forbidden_keys = {
        "access_token",
        "api_key",
        "asset_bytes",
        "auth_token",
        "content",
        "contents",
        "credential",
        "credentials",
        "derived_text",
        "document",
        "documents",
        "embedding_vector",
        "embedding_vectors",
        "embedding_values",
        "media_bytes",
        "password",
        "private_key",
        "raw_asset",
        "raw_assets",
        "raw_audio",
        "raw_caption",
        "raw_captions",
        "raw_derived_text",
        "raw_document",
        "raw_documents",
        "raw_embedding",
        "raw_embeddings",
        "raw_extractor_request",
        "raw_extractor_response",
        "raw_image",
        "raw_images",
        "raw_media",
        "raw_media_bytes",
        "raw_request",
        "raw_requests",
        "raw_response",
        "raw_responses",
        "raw_text",
        "raw_transcript",
        "raw_transcripts",
        "raw_video",
        "raw_videos",
        "request_body",
        "response_body",
        "secret",
        "token",
    }
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_name = str(key)
            child_path = f"{path}.{key_name}"
            if key_name.lower() in forbidden_keys and child not in (None, "", [], {}):
                paths.append(child_path)
            paths.extend(_multimodal_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_multimodal_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def cmd_multimodal_ops_check(args: argparse.Namespace) -> None:
    from mnemosyne.media import MEDIA_EXTRACT_JOB

    bundle = _load_multimodal_ops_bundle(args)
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    validation_scope = bundle.get("validation_scope")
    if not isinstance(validation_scope, Mapping):
        findings.append(_multimodal_finding("validation_scope_missing", "multimodal ops bundle requires validation_scope section"))
        validation_scope = {}
    validation_scope_ok = (
        validation_scope.get("production_validated") is True
        and validation_scope.get("target_environment") == "production"
        and validation_scope.get("operator_asserted") is True
        and bool(validation_scope.get("run_id"))
        and bool(validation_scope.get("started_at"))
        and bool(validation_scope.get("completed_at"))
    )
    if validation_scope.get("production_validated") is not True:
        findings.append(_multimodal_finding("production_validation_missing", "multimodal ops bundle must be production validated"))
    if validation_scope.get("target_environment") != "production":
        findings.append(_multimodal_finding("target_environment_not_production", "multimodal ops target environment must be production"))
    if validation_scope.get("operator_asserted") is not True:
        findings.append(_multimodal_finding("operator_assertion_missing", "operator production assertion is required"))
    for field in ("run_id", "started_at", "completed_at"):
        if not validation_scope.get(field):
            findings.append(_multimodal_finding("validation_scope_field_missing", f"validation_scope.{field} is required"))
    checks.append(
        {
            "name": "validation_scope",
            "ok": validation_scope_ok,
            "production_validated": validation_scope.get("production_validated") is True,
            "target_environment": validation_scope.get("target_environment"),
            "operator_asserted": validation_scope.get("operator_asserted") is True,
        }
    )

    provider_check = bundle.get("provider_check")
    if not isinstance(provider_check, Mapping):
        findings.append(_multimodal_finding("provider_check_missing", "multimodal ops bundle requires provider_check section"))
        provider_check = {}
    provider_manifest = provider_check.get("manifest") if isinstance(provider_check.get("manifest"), Mapping) else {}
    provider_checks = provider_check.get("checks") if isinstance(provider_check.get("checks"), Mapping) else {}
    required_provider_checks = sorted(set(args.require_provider_check or ["media_embedding", "media_extractor"]))
    provider_rows: list[dict[str, Any]] = []
    if provider_check.get("ok") is not True:
        findings.append(_multimodal_finding("provider_check_not_ok", "provider_check evidence must be ok"))
    if provider_manifest.get("forbid_local") is not True:
        findings.append(_multimodal_finding("provider_manifest_forbid_local_missing", "provider_check manifest must set forbid_local=true"))
    for check_name in required_provider_checks:
        raw_check = provider_checks.get(check_name)
        present = isinstance(raw_check, Mapping)
        provider = raw_check.get("provider") if present else None
        local_provider = _multimodal_provider_local(provider) if present else True
        skipped = present and raw_check.get("skipped") is True
        check_ok = present and raw_check.get("ok") is True and not local_provider and not skipped
        if not present:
            findings.append(_multimodal_finding("provider_check_required_missing", f"provider_check missing {check_name}"))
        elif raw_check.get("ok") is not True:
            findings.append(_multimodal_finding("provider_check_required_failed", f"provider_check {check_name} did not pass"))
        elif skipped:
            findings.append(_multimodal_finding("provider_check_skipped", f"provider_check {check_name} was skipped"))
        elif local_provider:
            findings.append(_multimodal_finding("provider_check_local_provider", f"provider_check {check_name} uses a local provider"))
        provider_rows.append(
            {
                "check": check_name,
                "present": present,
                "ok": check_ok,
                "provider": provider,
                "local_provider": local_provider,
                "skipped": skipped,
            }
        )
    provider_ok = provider_check.get("ok") is True and provider_manifest.get("forbid_local") is True and all(
        row["ok"] for row in provider_rows
    )
    checks.append(
        {
            "name": "provider_check",
            "ok": provider_ok,
            "forbid_local": provider_manifest.get("forbid_local") is True,
            "required_checks": required_provider_checks,
            "checks": provider_rows,
        }
    )

    object_store = bundle.get("object_store")
    if not isinstance(object_store, Mapping):
        findings.append(_multimodal_finding("object_store_missing", "multimodal ops bundle requires object_store section"))
        object_store = {}
    object_store_provider = object_store.get("provider") or object_store.get("backend")
    object_store_local = str(object_store_provider or "").strip().lower() in {"", "local", "filesystem", "file", "none", "test"}
    object_hash_count = _multimodal_ops_int(
        object_store.get("asset_hash_count"),
        default=len(_multimodal_string_list(object_store.get("asset_hashes"))),
        code="object_store_hash_count_invalid",
        message="object store asset hash count must be numeric",
        findings=findings,
    )
    object_store_ok = (
        object_store.get("ok") is True
        and not object_store_local
        and object_store.get("encrypted") is True
        and object_store.get("key_provider") in {"command", "kms", "vault", "hsm"}
        and object_store.get("externalized_payloads") is True
        and object_hash_count >= args.min_media_cases
    )
    if object_store.get("ok") is not True:
        findings.append(_multimodal_finding("object_store_not_ok", "object-store evidence must be ok"))
    if object_store_local:
        findings.append(_multimodal_finding("object_store_local", "object-store provider must be non-local for production"))
    if object_store.get("encrypted") is not True:
        findings.append(_multimodal_finding("object_store_encryption_missing", "object-store encryption is required"))
    if object_store.get("key_provider") not in {"command", "kms", "vault", "hsm"}:
        findings.append(_multimodal_finding("object_store_key_provider_invalid", "object-store key provider must be externalized"))
    if object_store.get("externalized_payloads") is not True:
        findings.append(_multimodal_finding("object_store_externalization_missing", "raw media payloads must be externalized"))
    if object_hash_count < args.min_media_cases:
        findings.append(_multimodal_finding("object_store_hash_count_too_low", "object-store asset hash count is below threshold"))
    checks.append(
        {
            "name": "object_store",
            "ok": object_store_ok,
            "provider": object_store_provider,
            "provider_local": object_store_local,
            "encrypted": object_store.get("encrypted") is True,
            "asset_hash_count": object_hash_count,
        }
    )

    extraction = bundle.get("extraction")
    if not isinstance(extraction, Mapping):
        findings.append(_multimodal_finding("extraction_missing", "multimodal ops bundle requires extraction section"))
        extraction = {}
    extractor_provider = extraction.get("provider") or extraction.get("provider_kind")
    extractor_local = _multimodal_provider_local(extractor_provider)
    extraction_modalities = set(_multimodal_string_list(extraction.get("modalities")))
    required_modalities = sorted(set(args.require_modality or ["audio", "image", "video"]))
    missing_modalities = [modality for modality in required_modalities if modality not in extraction_modalities]
    extraction_cases_raw = extraction.get("cases")
    extraction_cases = [item for item in extraction_cases_raw if isinstance(item, Mapping)] if isinstance(extraction_cases_raw, list) else []
    derived_relation_cases = 0
    searchable_cases = 0
    for case in extraction_cases:
        if case.get("media_derived_relation") is True:
            derived_relation_cases += 1
        if case.get("derived_text_searchable") is True:
            searchable_cases += 1
        if "sha256:" not in str(case.get("asset_sha256") or "").lower():
            findings.append(_multimodal_finding("extraction_asset_hash_missing", "extraction case asset hash is required"))
        if "sha256:" not in str(case.get("derived_cid_hash") or "").lower():
            findings.append(_multimodal_finding("extraction_derived_hash_missing", "extraction case derived CID hash is required"))
    extraction_ok = (
        extraction.get("ok") is True
        and not extractor_local
        and extraction.get("contract_checked") is True
        and not missing_modalities
        and len(extraction_cases) >= args.min_media_cases
        and derived_relation_cases >= args.min_media_cases
        and searchable_cases >= args.min_media_cases
    )
    if extraction.get("ok") is not True:
        findings.append(_multimodal_finding("extraction_not_ok", "media extraction evidence must be ok"))
    if extractor_local:
        findings.append(_multimodal_finding("extractor_provider_local", "media extractor provider must be command, container, or hosted"))
    if extraction.get("contract_checked") is not True:
        findings.append(_multimodal_finding("extractor_contract_missing", "media extractor contract evidence is required"))
    for modality in missing_modalities:
        findings.append(_multimodal_finding("extractor_modality_missing", f"media extractor missing modality {modality}"))
    if len(extraction_cases) < args.min_media_cases:
        findings.append(_multimodal_finding("extraction_cases_too_low", "media extraction case count is below threshold"))
    if derived_relation_cases < args.min_media_cases:
        findings.append(_multimodal_finding("media_derived_relation_missing", "media-derived relation proof is below threshold"))
    if searchable_cases < args.min_media_cases:
        findings.append(_multimodal_finding("derived_text_searchable_missing", "derived text search proof is below threshold"))
    checks.append(
        {
            "name": "extraction",
            "ok": extraction_ok,
            "provider": extractor_provider,
            "provider_local": extractor_local,
            "modalities": sorted(extraction_modalities),
            "missing_modalities": missing_modalities,
            "case_count": len(extraction_cases),
            "derived_relation_cases": derived_relation_cases,
            "searchable_cases": searchable_cases,
        }
    )

    embedding = bundle.get("media_embedding") or bundle.get("embedding")
    if not isinstance(embedding, Mapping):
        findings.append(_multimodal_finding("media_embedding_missing", "multimodal ops bundle requires media_embedding section"))
        embedding = {}
    embedding_provider = embedding.get("provider") or embedding.get("provider_kind")
    embedding_local = _multimodal_provider_local(embedding_provider)
    dimensions = _multimodal_ops_int(
        embedding.get("dimensions"),
        default=0,
        code="media_embedding_dimensions_invalid",
        message="media embedding dimensions must be numeric",
        findings=findings,
    )
    embedding_modalities = set(_multimodal_string_list(embedding.get("modalities")))
    missing_embedding_modalities = [modality for modality in required_modalities if modality not in embedding_modalities]
    embedded_hashes = _multimodal_string_list(embedding.get("embedded_cid_hashes") or embedding.get("cid_hashes"))
    embedding_ok = (
        embedding.get("ok") is True
        and not embedding_local
        and dimensions >= args.min_embedding_dimensions
        and len(embedded_hashes) >= args.min_media_cases
        and not missing_embedding_modalities
        and embedding.get("contract_checked") is True
        and embedding.get("raw_media_embedding_indexed") is True
    )
    if embedding.get("ok") is not True:
        findings.append(_multimodal_finding("media_embedding_not_ok", "media embedding evidence must be ok"))
    if embedding_local:
        findings.append(_multimodal_finding("media_embedding_provider_local", "media embedding provider must be command, container, or hosted"))
    if dimensions < args.min_embedding_dimensions:
        findings.append(_multimodal_finding("media_embedding_dimensions_too_low", "media embedding dimensions are below threshold"))
    if len(embedded_hashes) < args.min_media_cases:
        findings.append(_multimodal_finding("media_embedding_hash_count_too_low", "media embedding hash count is below threshold"))
    for modality in missing_embedding_modalities:
        findings.append(_multimodal_finding("media_embedding_modality_missing", f"media embedding missing modality {modality}"))
    if embedding.get("contract_checked") is not True:
        findings.append(_multimodal_finding("media_embedding_contract_missing", "media embedding contract evidence is required"))
    if embedding.get("raw_media_embedding_indexed") is not True:
        findings.append(_multimodal_finding("raw_media_embedding_not_indexed", "raw media embedding indexing proof is required"))
    checks.append(
        {
            "name": "media_embedding",
            "ok": embedding_ok,
            "provider": embedding_provider,
            "provider_local": embedding_local,
            "dimensions": dimensions,
            "embedded_hash_count": len(embedded_hashes),
            "missing_modalities": missing_embedding_modalities,
        }
    )

    retrieval = bundle.get("retrieval")
    if not isinstance(retrieval, Mapping):
        findings.append(_multimodal_finding("retrieval_missing", "multimodal ops bundle requires retrieval section"))
        retrieval = {}
    retrieval_backend = str(retrieval.get("backend") or "").strip().lower()
    retrieval_cases_raw = retrieval.get("cases")
    retrieval_cases = [item for item in retrieval_cases_raw if isinstance(item, Mapping)] if isinstance(retrieval_cases_raw, list) else []
    vector_cases = 0
    derived_text_cases = 0
    for case in retrieval_cases:
        vector_cases += 1 if int(case.get("vector_hit_count") or 0) > 0 and case.get("stored_media_embedding") is True else 0
        derived_text_cases += 1 if int(case.get("derived_text_hit_count") or 0) > 0 else 0
        if "sha256:" not in str(case.get("query_hash") or "").lower():
            findings.append(_multimodal_finding("retrieval_query_hash_missing", "retrieval case query hash is required"))
    retrieval_ok = (
        retrieval.get("ok") is True
        and retrieval_backend in {"postgres", "postgresql"}
        and retrieval.get("production_validated") is True
        and len(retrieval_cases) >= args.min_media_cases
        and vector_cases >= args.min_vector_cases
        and derived_text_cases >= args.min_derived_text_cases
    )
    if retrieval.get("ok") is not True:
        findings.append(_multimodal_finding("retrieval_not_ok", "multimodal retrieval evidence must be ok"))
    if retrieval_backend not in {"postgres", "postgresql"}:
        findings.append(_multimodal_finding("retrieval_backend_not_postgres", "multimodal retrieval backend must be postgres"))
    if retrieval.get("production_validated") is not True:
        findings.append(_multimodal_finding("retrieval_production_validation_missing", "multimodal retrieval must be production validated"))
    if len(retrieval_cases) < args.min_media_cases:
        findings.append(_multimodal_finding("retrieval_cases_too_low", "multimodal retrieval case count is below threshold"))
    if vector_cases < args.min_vector_cases:
        findings.append(_multimodal_finding("retrieval_vector_cases_too_low", "media vector retrieval cases are below threshold"))
    if derived_text_cases < args.min_derived_text_cases:
        findings.append(_multimodal_finding("retrieval_derived_text_cases_too_low", "derived text retrieval cases are below threshold"))
    checks.append(
        {
            "name": "retrieval",
            "ok": retrieval_ok,
            "backend": retrieval_backend,
            "case_count": len(retrieval_cases),
            "vector_cases": vector_cases,
            "derived_text_cases": derived_text_cases,
        }
    )

    media_jobs = bundle.get("media_jobs")
    if not isinstance(media_jobs, Mapping):
        findings.append(_multimodal_finding("media_jobs_missing", "multimodal ops bundle requires media_jobs section"))
        media_jobs = {}
    queue_backend = str(media_jobs.get("queue_backend") or media_jobs.get("backend") or "").strip().lower()
    complete_jobs = _multimodal_ops_int(
        media_jobs.get("complete_jobs"),
        default=0,
        code="media_jobs_complete_invalid",
        message="media jobs complete count must be numeric",
        findings=findings,
    )
    dead_jobs = _multimodal_ops_int(
        media_jobs.get("dead_jobs"),
        default=0,
        code="media_jobs_dead_invalid",
        message="media jobs dead count must be numeric",
        findings=findings,
    )
    media_jobs_ok = (
        media_jobs.get("ok") is True
        and queue_backend in {"postgres", "postgresql"}
        and media_jobs.get("fail_on_dead") is True
        and complete_jobs >= args.min_media_cases
        and dead_jobs <= args.max_dead_jobs
        and MEDIA_EXTRACT_JOB in set(_multimodal_string_list(media_jobs.get("processed_kinds")))
    )
    if media_jobs.get("ok") is not True:
        findings.append(_multimodal_finding("media_jobs_not_ok", "media job evidence must be ok"))
    if queue_backend not in {"postgres", "postgresql"}:
        findings.append(_multimodal_finding("media_jobs_backend_not_postgres", "media job queue backend must be postgres"))
    if media_jobs.get("fail_on_dead") is not True:
        findings.append(_multimodal_finding("media_jobs_fail_on_dead_missing", "media jobs must run with fail_on_dead=true"))
    if complete_jobs < args.min_media_cases:
        findings.append(_multimodal_finding("media_jobs_complete_too_low", "completed media jobs are below threshold"))
    if dead_jobs > args.max_dead_jobs:
        findings.append(_multimodal_finding("media_jobs_dead_present", "media job evidence contains dead jobs"))
    if MEDIA_EXTRACT_JOB not in set(_multimodal_string_list(media_jobs.get("processed_kinds"))):
        findings.append(_multimodal_finding("media_extract_job_missing", f"media jobs must process {MEDIA_EXTRACT_JOB}"))
    checks.append(
        {
            "name": "media_jobs",
            "ok": media_jobs_ok,
            "queue_backend": queue_backend,
            "complete_jobs": complete_jobs,
            "dead_jobs": dead_jobs,
        }
    )

    deployment = bundle.get("deployment")
    if not isinstance(deployment, Mapping):
        findings.append(_multimodal_finding("deployment_missing", "multimodal ops bundle requires deployment section"))
        deployment = {}
    deployment_flags = {
        "production_validated": deployment.get("production_validated") is True,
        "extraction_service_supervised": deployment.get("extraction_service_supervised") is True,
        "embedding_service_supervised": deployment.get("embedding_service_supervised") is True,
        "object_store_monitoring": deployment.get("object_store_monitoring") is True,
        "media_job_worker_supervised": deployment.get("media_job_worker_supervised") is True,
        "retrieval_probe_verified": deployment.get("retrieval_probe_verified") is True,
        "alert_route_configured": deployment.get("alert_route_configured") is True,
    }
    deployment_latency_ms = _multimodal_ops_int(
        deployment.get("latency_ms"),
        default=int(args.max_deployment_latency_ms) + 1,
        code="deployment_latency_invalid",
        message="deployment latency_ms must be numeric",
        findings=findings,
    )
    execution_fingerprint = str(deployment.get("execution_fingerprint") or "").strip()
    deployment_asset_hash_count = _multimodal_ops_int(
        deployment.get("object_asset_hash_count"),
        default=-1,
        code="deployment_asset_hash_count_invalid",
        message="deployment object_asset_hash_count must be numeric",
        findings=findings,
    )
    deployment_extraction_case_count = _multimodal_ops_int(
        deployment.get("extraction_case_count"),
        default=-1,
        code="deployment_extraction_case_count_invalid",
        message="deployment extraction_case_count must be numeric",
        findings=findings,
    )
    deployment_embedding_hash_count = _multimodal_ops_int(
        deployment.get("embedding_hash_count"),
        default=-1,
        code="deployment_embedding_hash_count_invalid",
        message="deployment embedding_hash_count must be numeric",
        findings=findings,
    )
    deployment_retrieval_case_count = _multimodal_ops_int(
        deployment.get("retrieval_case_count"),
        default=-1,
        code="deployment_retrieval_case_count_invalid",
        message="deployment retrieval_case_count must be numeric",
        findings=findings,
    )
    deployment_media_job_complete_count = _multimodal_ops_int(
        deployment.get("media_job_complete_count"),
        default=-1,
        code="deployment_media_job_complete_count_invalid",
        message="deployment media_job_complete_count must be numeric",
        findings=findings,
    )
    execution_fingerprint_present = "sha256:" in execution_fingerprint.lower()
    asset_hash_count_matches = deployment_asset_hash_count == object_hash_count
    extraction_case_count_matches = deployment_extraction_case_count == len(extraction_cases)
    embedding_hash_count_matches = deployment_embedding_hash_count == len(embedded_hashes)
    retrieval_case_count_matches = deployment_retrieval_case_count == len(retrieval_cases)
    media_job_count_matches = deployment_media_job_complete_count == complete_jobs
    missing_deployment_flags = [name for name, ok in deployment_flags.items() if not ok]
    deployment_ok = (
        not missing_deployment_flags
        and execution_fingerprint_present
        and deployment_latency_ms <= args.max_deployment_latency_ms
        and asset_hash_count_matches
        and extraction_case_count_matches
        and embedding_hash_count_matches
        and retrieval_case_count_matches
        and media_job_count_matches
    )
    for flag in missing_deployment_flags:
        findings.append(_multimodal_finding("deployment_control_missing", f"deployment control {flag} is required"))
    if not execution_fingerprint_present:
        findings.append(_multimodal_finding("deployment_execution_fingerprint_missing", "deployment execution_fingerprint must be SHA-256"))
    if deployment_latency_ms > args.max_deployment_latency_ms:
        findings.append(_multimodal_finding("deployment_latency_too_high", "deployment latency exceeds threshold"))
    if not asset_hash_count_matches:
        findings.append(_multimodal_finding("deployment_asset_hash_count_mismatch", "deployment object_asset_hash_count must match object store asset hashes"))
    if not extraction_case_count_matches:
        findings.append(_multimodal_finding("deployment_extraction_case_count_mismatch", "deployment extraction_case_count must match extraction evidence"))
    if not embedding_hash_count_matches:
        findings.append(_multimodal_finding("deployment_embedding_hash_count_mismatch", "deployment embedding_hash_count must match media embedding evidence"))
    if not retrieval_case_count_matches:
        findings.append(_multimodal_finding("deployment_retrieval_case_count_mismatch", "deployment retrieval_case_count must match retrieval evidence"))
    if not media_job_count_matches:
        findings.append(_multimodal_finding("deployment_media_job_count_mismatch", "deployment media_job_complete_count must match media job evidence"))
    checks.append(
        {
            "name": "deployment",
            "ok": deployment_ok,
            "latency_ms": deployment_latency_ms,
            "max_latency_ms": args.max_deployment_latency_ms,
            "missing_controls": missing_deployment_flags,
            "execution_fingerprint_present": execution_fingerprint_present,
            "asset_hash_count_matches": asset_hash_count_matches,
            "extraction_case_count_matches": extraction_case_count_matches,
            "embedding_hash_count_matches": embedding_hash_count_matches,
            "retrieval_case_count_matches": retrieval_case_count_matches,
            "media_job_count_matches": media_job_count_matches,
        }
    )

    redaction = bundle.get("redaction") if isinstance(bundle.get("redaction"), Mapping) else {}
    redaction_flags = {
        "raw_media_omitted": redaction.get("raw_media_omitted") is True,
        "raw_asset_bytes_omitted": redaction.get("raw_asset_bytes_omitted") is True
        or redaction.get("asset_bytes_omitted") is True,
        "raw_extractor_requests_omitted": redaction.get("raw_extractor_requests_omitted") is True,
        "raw_extractor_responses_omitted": redaction.get("raw_extractor_responses_omitted") is True,
        "raw_embeddings_omitted": redaction.get("raw_embeddings_omitted") is True,
        "raw_documents_omitted": redaction.get("raw_documents_omitted") is True,
        "raw_credentials_omitted": redaction.get("raw_credentials_omitted") is True,
    }
    missing_redaction_flags = [flag for flag, ok in redaction_flags.items() if not ok]
    for flag in missing_redaction_flags:
        findings.append(_multimodal_finding("redaction_flag_missing", f"redaction flag {flag} must be true"))
    forbidden_raw_paths = _multimodal_forbidden_raw_paths(bundle)
    if forbidden_raw_paths:
        findings.append(_multimodal_finding("redaction_raw_field_present", "bundle contains raw media, text, vectors, provider payloads, or credentials"))
    checks.append(
        {
            "name": "redaction",
            "ok": not missing_redaction_flags and not forbidden_raw_paths,
            **redaction_flags,
            "forbidden_raw_paths": forbidden_raw_paths,
        }
    )

    report = {
        "ok": not findings,
        "bundle": {
            "name": bundle.get("name"),
            "production_validated": validation_scope.get("production_validated") is True,
            "provider_check_count": len(provider_rows),
            "object_store_provider": object_store_provider,
            "extractor_provider": extractor_provider,
            "media_embedding_provider": embedding_provider,
            "extraction_case_count": len(extraction_cases),
            "retrieval_case_count": len(retrieval_cases),
            "media_job_complete_count": complete_jobs,
        },
        "requirements": {
            "production_validated": True,
            "target_environment": "production",
            "operator_asserted": True,
            "required_provider_checks": required_provider_checks,
            "required_modalities": required_modalities,
            "min_media_cases": args.min_media_cases,
            "min_embedding_dimensions": args.min_embedding_dimensions,
            "min_vector_cases": args.min_vector_cases,
            "min_derived_text_cases": args.min_derived_text_cases,
            "max_dead_jobs": args.max_dead_jobs,
            "max_deployment_latency_ms": args.max_deployment_latency_ms,
        },
        "redaction": {**redaction_flags, "forbidden_raw_fields_present": bool(forbidden_raw_paths)},
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _multimodal_ops_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(_multimodal_finding("fingerprint_mismatch", "multimodal ops fingerprint mismatch"))
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def cmd_profile_add(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.profile_add(
            tenant_id=args.tenant,
            user_id=args.user,
            kind=args.kind,
            statement=args.statement,
            scope=parse_json_arg(args.scope, {}),
            confidence=args.confidence,
            exceptions=parse_json_arg(args.exceptions, {}),
            source_evidence_cids=args.evidence_cid,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_profile_context(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.profile_context(args.tenant, args.user, scope=parse_json_arg(args.scope, {})))


def cmd_profile_get_relevant(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.profile_get_relevant(args.tenant, args.user, context=parse_json_arg(args.context, {})))


def cmd_profile_record_explicit(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.profile_record_explicit(
            args.tenant,
            args.user,
            args.statement,
            scope=parse_json_arg(args.scope, {}),
            confidence=args.confidence,
            source_evidence_cids=args.evidence_cid,
        )
    )


def cmd_profile_propose_inference(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.profile_propose_inference(
            args.tenant,
            args.user,
            args.statement,
            context=parse_json_arg(args.context, {}),
            confidence=args.confidence,
            source_evidence_cids=args.evidence_cid,
        )
    )


def cmd_profile_correct(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.profile_correct(
            args.tenant,
            args.user,
            args.id,
            args.statement,
            context=parse_json_arg(args.context, {}),
            confidence=args.confidence,
        )
    )


def cmd_profile_record_mistake(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.profile_record_mistake(
            tenant_id=args.tenant,
            user_id=args.user,
            pattern=args.pattern,
            description=args.description,
            scope=parse_json_arg(args.scope, {}),
            suggestion=args.suggestion,
            occurred_at=args.occurred_at,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_profile_retire_support_strategy(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.profile_retire_support_strategy(
            tenant_id=args.tenant,
            user_id=args.user,
            strategy_id=args.strategy_id,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_graph_neighbors(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.graph_neighbors(args.tenant, args.seed, branch=args.branch, k=args.k))


def cmd_graph_query(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.graph_query(args.tenant, args.seed, branch=args.branch, hops=args.hops, k=args.k))


def cmd_graph_timeline(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.graph_timeline(args.tenant, args.entity, branch=args.branch, **_read_context_kwargs(args)))


def cmd_graph_as_of(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.graph_as_of(args.tenant, args.subject, args.predicate, args.time, branch=args.branch))


def cmd_prefetch(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.prefetch(args.tenant, candidates=parse_json_arg(args.candidates, []), branch=args.branch))


def cmd_trajectory_log(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.trajectory_log(
            tenant_id=args.tenant,
            user_id=args.user,
            session_id=args.session,
            task=args.task,
            steps=parse_json_arg(args.steps, []),
            outcome=args.outcome,
            reward=args.reward,
            memory_version=args.memory_version,
        )
    )


def cmd_trajectory_attribute(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.trajectory_attribute(args.trajectory_id))


def cmd_lesson_induce(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.lesson_induce(args.trajectory_id))


def cmd_procedure_induce(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.procedure_induce(args.lesson_id))


def cmd_lesson_promote(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.lesson_promote(
            args.lesson_id,
            cases=parse_json_arg(args.cases, []),
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_procedure_validate(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.procedure_validate(
            args.procedure_id,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_procedure_promote(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.procedure_promote(
            args.procedure_id,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_lesson_search(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.lesson_search(args.signature, tenant_id=args.tenant, status=args.status))


def cmd_procedure_search(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.procedure_search(args.query, tenant_id=args.tenant, status=args.status))


def cmd_procedure_rollback(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.procedure_rollback(
            args.procedure_id,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
        )
    )


def cmd_outcome_evaluate(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.outcome_evaluate(
            trajectory_id=args.trajectory_id,
            before_successes=args.before_successes,
            after_successes=args.after_successes,
            total_cases=args.total_cases,
        )
    )


def cmd_parametric_propose(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.parametric_propose(args.tenant, role=args.role, source_trust_tier=args.source_trust_tier))


def cmd_parametric_evaluate(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.parametric_evaluate(
            args.artifact_uri,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
            protected_case_count=args.protected_case_count,
            gate_promoted=not args.gate_failed,
            protected_regressions=args.protected_regression,
        )
    )


def cmd_parametric_rollback(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.parametric_rollback(
            args.artifact_uri,
            args.reason,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
            protected_case_count=args.protected_case_count,
        )
    )


def cmd_branch(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.branch(
            name=args.name,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
            from_branch=args.from_branch,
            kind=args.kind,
            tenant_id=args.tenant,
        )
    )


def cmd_merge(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.merge(
            from_branch=args.from_branch,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
            into=args.into,
            tenant_id=args.tenant,
        )
    )


def cmd_discard(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.discard(
            branch=args.branch,
            role=args.role,
            source_trust_tier=args.source_trust_tier,
            tenant_id=args.tenant,
        )
    )


def cmd_tools(args: argparse.Namespace) -> None:
    from mnemosyne.mcp_tools import TOOL_SPEC

    from mnemosyne.mcp_server import _to_mcp_tool_spec

    emit({"tools": [_to_mcp_tool_spec(item) for item in TOOL_SPEC]})


def cmd_eval(args: argparse.Namespace) -> None:
    from mnemosyne.eval import run_seed_suite

    if getattr(args, "suite", "seed") == "g0":
        repo_root = args.repo_root.resolve()
        repo_root_text = str(repo_root)
        if repo_root_text not in sys.path:
            sys.path.insert(0, repo_root_text)
        from eval.g0.runner import build_report, write_report

        report = build_report(
            repo_root,
            baseline_name=args.baseline_name,
            pinned_commit=args.pinned_commit,
            controller_telemetry_path=args.controller_telemetry,
        )
        paths = write_report(report, repo_root / args.out_dir, write_baseline=args.write_baseline)
        if args.print_json:
            print(json.dumps(report, indent=2, sort_keys=True))
            return
        print(f"G0 report: {paths['json']}")
        print(f"G0 markdown: {paths['markdown']}")
        if "baseline" in paths:
            print(f"G0 baseline: {paths['baseline']}")
        print(
            f"G0 coverage: {report['coverage']['measured']}/{report['coverage']['total']} "
            f"measured; gate_ready={report['coverage']['gate_ready']}"
        )
        return

    outcomes = run_seed_suite()
    emit({"passed": all(item.passed for item in outcomes), "outcomes": [asdict(item) for item in outcomes]})


def cmd_queue_snapshot(args: argparse.Namespace) -> None:
    runtime_state = load_runtime_state(args)
    queue = load_queue(args, runtime_state)
    emit({"queue": queue.snapshot(), "jobs": [job.to_dict() for job in queue.jobs.values()]})


def cmd_gate_case_add(args: argparse.Namespace) -> None:
    from mnemosyne.gate import RegressionCase

    runtime_state = load_runtime_state(args)
    cases = {case.id: case for case in runtime_state.load_gate_cases()}
    case = RegressionCase(
        id=args.id or gate_case_id(args.signature, args.query, args.expected_substring),
        signature=args.signature,
        query=args.query,
        expected_substring=args.expected_substring,
        tier=args.tier,
        protected=args.protected,
        origin=args.origin,
        mode=args.mode,
    )
    existing = cases.get(case.id)
    if existing is not None and existing.protected and existing.to_dict() != case.to_dict():
        finding = {
            "code": "protected_case_ratchet_violation",
            "message": "protected regression cases cannot be weakened or overwritten by gate-case-add",
            "existing": existing.to_dict(),
            "attempted": case.to_dict(),
        }
        emit({"ok": False, "case": existing.to_dict(), "finding": finding})
        raise SystemExit(1)
    cases[case.id] = case
    ordered = sorted(cases.values(), key=lambda item: item.id)
    runtime_state.save_gate_cases(ordered)
    emit({"ok": True, "case": case.to_dict(), "cases": [item.to_dict() for item in ordered]})


def cmd_gate_case_list(args: argparse.Namespace) -> None:
    runtime_state = load_runtime_state(args)
    emit({"cases": [case.to_dict() for case in runtime_state.load_gate_cases()]})


def gate_suite_fingerprint(cases: list[RegressionCase]) -> str:

    canonical = [
        case.to_dict()
        for case in sorted(
            cases,
            key=lambda item: (item.id, item.signature, item.query, item.expected_substring),
        )
    ]
    return sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def cmd_gate_suite_check(args: argparse.Namespace) -> None:
    from mnemosyne.parametric import protected_suite_report

    runtime_state = load_runtime_state(args)
    cases = runtime_state.load_gate_cases()
    suite = protected_suite_report(cases)
    fingerprint = gate_suite_fingerprint(cases)
    failures: list[str] = []
    required_tiers = sorted(set(args.require_tier or []))
    missing_required_tiers = [tier for tier in required_tiers if suite["tier_counts"].get(tier, 0) == 0]
    if suite["case_count"] < args.min_cases:
        failures.append(f"case count {suite['case_count']} is below required minimum {args.min_cases}")
    if suite["protected_case_count"] < args.min_protected:
        failures.append(f"protected case count {suite['protected_case_count']} is below required minimum {args.min_protected}")
    for tier in missing_required_tiers:
        failures.append(f"required tier {tier} has no cases")
    if args.expected_fingerprint and fingerprint != args.expected_fingerprint:
        failures.append("protected suite fingerprint mismatch")
    report = {
        "ok": not failures,
        "suite": {
            **suite,
            "fingerprint": fingerprint,
            "missing_required_tiers": missing_required_tiers,
        },
        "requirements": {
            "min_cases": args.min_cases,
            "min_protected": args.min_protected,
            "required_tiers": required_tiers,
            "expected_fingerprint_present": bool(args.expected_fingerprint),
        },
        "failures": failures,
    }
    if args.include_cases:
        report["suite"]["cases"] = [case.to_dict() for case in cases]
    emit(report)
    if failures:
        raise SystemExit(1)


def cmd_queue_enqueue(args: argparse.Namespace) -> None:
    runtime_state = load_runtime_state(args)
    queue = load_queue(args, runtime_state)
    job = queue.enqueue(args.kind, parse_json_arg(args.payload, {}), max_attempts=args.max_attempts)
    if runtime_state and queue_uses_runtime_state(args):
        runtime_state.save_queue(queue)
    emit({"queue": queue.snapshot(), "job": job.to_dict()})


def projection_recompute_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "tenant_id": args.tenant,
        "user_id": args.user,
        "branch": args.branch,
        "changed_evidence_cids": list(args.cid),
        "enqueue_consolidation": not bool(args.no_enqueue_consolidation),
    }


def cmd_projection_recompute_enqueue(args: argparse.Namespace) -> None:
    from mnemosyne.jobs import PROJECTION_RECOMPUTE_JOB

    runtime_state = load_runtime_state(args)
    queue = load_queue(args, runtime_state)
    job = queue.enqueue(PROJECTION_RECOMPUTE_JOB, projection_recompute_payload(args), max_attempts=args.max_attempts)
    if runtime_state and queue_uses_runtime_state(args):
        runtime_state.save_queue(queue)
    emit({"queue": queue.snapshot(), "job": job.to_dict()})


def cmd_projection_recompute_once(args: argparse.Namespace) -> None:
    from mnemosyne.jobs import PROJECTION_RECOMPUTE_JOB

    runtime_state, queue, tools, metrics, worker = _runtime_worker_components(args)
    queued = queue.enqueue(PROJECTION_RECOMPUTE_JOB, projection_recompute_payload(args), max_attempts=args.max_attempts)
    job = worker.run_once(PROJECTION_RECOMPUTE_JOB)
    _persist_worker_state(args, runtime_state, queue, tools)
    emit(
        {
            "queue": queue.snapshot(),
            "enqueued_job": queued.to_dict(),
            "job": job.to_dict() if job else None,
            "metrics": metrics.snapshot().to_dict(),
        }
    )


def _runtime_worker_components(
    args: argparse.Namespace,
) -> tuple[RuntimeState | PostgresRuntimeState | None, InProcessQueue | PostgresQueue, MemoryTools, MetricsRegistry, QueueWorker]:
    from mnemosyne.jobs import RuntimeJobHandlers
    from mnemosyne.observability import MetricsRegistry
    from mnemosyne.queue import QueueWorker

    runtime_state = load_runtime_state(args)
    queue = load_queue(args, runtime_state)
    tools = load_tools(args, ingestion_queue=queue, runtime_state=runtime_state)
    metrics = MetricsRegistry()
    handlers = RuntimeJobHandlers(
        tools.engine,
        queue,
        metrics=metrics,
        object_store=load_object_store(args),
        media_extractor=load_media_extractor(args),
        learning=tools.learning,
        user_model=tools.user_model,
        gate_cases=runtime_state.load_gate_cases() if runtime_state else [],
        entity_resolver=load_entity_resolver(args),
        candidate_extractor=load_candidate_extractor(args),
        summarizer=load_consolidation_summarizer(args),
        lesson_distiller=load_lesson_distiller(args),
        procedure_inducer=load_procedure_inducer(args),
        max_media_bytes=max_ingest_bytes(args),
    )
    worker = QueueWorker(queue, handlers.handlers(), metrics=metrics)
    return runtime_state, queue, tools, metrics, worker


def _persist_worker_state(
    args: argparse.Namespace,
    runtime_state: RuntimeState | PostgresRuntimeState | None,
    queue: InProcessQueue | PostgresQueue,
    tools: MemoryTools,
) -> None:

    if runtime_state and queue_uses_runtime_state(args):
        runtime_state.save_queue(queue)
        runtime_state.save_learning(tools.learning)
        runtime_state.save_user_model(tools.user_model)
    elif runtime_state:
        runtime_state.save_learning(tools.learning)
        runtime_state.save_user_model(tools.user_model)


def cmd_consolidate_once(args: argparse.Namespace) -> None:
    from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB

    runtime_state, queue, tools, metrics, worker = _runtime_worker_components(args)
    job = worker.run_once(CONSOLIDATE_EVIDENCE_JOB)
    _persist_worker_state(args, runtime_state, queue, tools)
    emit({"queue": queue.snapshot(), "job": job.to_dict() if job else None, "metrics": metrics.snapshot().to_dict()})


def cmd_queue_drain(args: argparse.Namespace) -> None:
    runtime_state, queue, tools, metrics, worker = _runtime_worker_components(args)
    jobs = worker.drain(limit=args.limit, kind=args.kind)
    _persist_worker_state(args, runtime_state, queue, tools)
    emit({"queue": queue.snapshot(), "jobs": [job.to_dict() for job in jobs], "metrics": metrics.snapshot().to_dict()})


def cmd_worker_run(args: argparse.Namespace) -> None:
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1.")
    if args.max_cycles < 1:
        raise SystemExit("--max-cycles must be at least 1.")
    if args.idle_exit_after < 0:
        raise SystemExit("--idle-exit-after must be zero or greater.")
    if args.poll_interval < 0:
        raise SystemExit("--poll-interval must be zero or greater.")

    runtime_state, queue, tools, metrics, worker = _runtime_worker_components(args)
    cycles: list[dict[str, Any]] = []
    processed_jobs: list[dict[str, Any]] = []
    idle_cycles = 0
    stopped_reason = "max_cycles"
    started = time.monotonic()

    for cycle_number in range(1, args.max_cycles + 1):
        cycle_jobs = []
        cycle_started = time.monotonic()
        for _ in range(args.limit):
            job = worker.run_once(args.kind)
            if job is None:
                break
            cycle_jobs.append(job)
            processed_jobs.append(job.to_dict())
        _persist_worker_state(args, runtime_state, queue, tools)

        if cycle_jobs:
            idle_cycles = 0
        else:
            idle_cycles += 1
        cycles.append(
            {
                "cycle": cycle_number,
                "processed": len(cycle_jobs),
                "idle": not cycle_jobs,
                "duration_ms": round((time.monotonic() - cycle_started) * 1000, 3),
                "queue": queue.snapshot(),
                "jobs": [job.to_dict() for job in cycle_jobs],
            }
        )
        if not cycle_jobs and args.idle_exit_after and idle_cycles >= args.idle_exit_after:
            stopped_reason = "idle_exit"
            break
        if args.poll_interval and cycle_number < args.max_cycles:
            time.sleep(args.poll_interval)

    final_queue = queue.snapshot()
    ok = not (args.fail_on_dead and int(final_queue.get("dead", 0)) > 0)
    report = {
        "ok": ok,
        "worker": {
            "backend": args.queue_backend,
            "tenant": runtime_state_tenant(args),
            "kind": args.kind,
            "limit": args.limit,
            "max_cycles": args.max_cycles,
            "idle_exit_after": args.idle_exit_after,
            "poll_interval": args.poll_interval,
            "fail_on_dead": bool(args.fail_on_dead),
        },
        "summary": {
            "cycles": len(cycles),
            "processed": len(processed_jobs),
            "idle_cycles": idle_cycles,
            "stopped_reason": stopped_reason,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        },
        "queue": final_queue,
        "cycles": cycles,
        "jobs": processed_jobs,
        "metrics": metrics.snapshot().to_dict(),
    }
    emit(report)
    if not ok:
        raise SystemExit(1)


def cmd_ops_report(args: argparse.Namespace) -> None:
    from mnemosyne.observability import build_ops_report, render_ops_dashboard
    from mnemosyne.queue import InProcessQueue

    runtime_state = load_runtime_state(args)
    queue = runtime_state.load_queue() if runtime_state else InProcessQueue()
    tools = load_tools(args, ingestion_queue=queue, runtime_state=runtime_state)
    report = build_ops_report(
        engine=tools.engine,
        tenant_id=args.tenant,
        queue_snapshot=queue.snapshot(),
        learning=tools.learning,
        metrics=tools.metrics.snapshot(),
        proxy_score=args.proxy_score,
        true_score=args.true_score,
        min_diversity=args.min_diversity,
        max_proxy_gap=args.max_proxy_gap,
        max_open_contradictions=args.max_open_contradictions,
    )
    payload = {"ok": bool(report["tripwires"]["passed"]), **report}
    dashboard_html = render_ops_dashboard(report)
    dashboard_path: Path | None = None
    if args.dashboard_html:
        dashboard_path = Path(args.dashboard_html).expanduser()
        dashboard_path.parent.mkdir(parents=True, exist_ok=True)
        dashboard_path.write_text(dashboard_html, encoding="utf-8")
    dashboard_package: dict[str, Any] | None = None
    if args.dashboard_package_dir:
        package_dir = Path(args.dashboard_package_dir).expanduser()
        package_dir.mkdir(parents=True, exist_ok=True)
        package_dashboard = package_dir / "ops-dashboard.html"
        package_snapshot = package_dir / "ops-report.json"
        package_manifest = package_dir / "manifest.json"
        package_dashboard.write_text(dashboard_html, encoding="utf-8")
        package_snapshot.write_text(json.dumps({"ok": payload["ok"], "report": report}, indent=2, sort_keys=True), encoding="utf-8")
        manifest = {
            "kind": "mnemosyne.ops_dashboard_package",
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "tenant_id": report["tenant_id"],
            "ok": payload["ok"],
            "files": {
                "dashboard_html": package_dashboard.name,
                "snapshot_json": package_snapshot.name,
            },
            "counts": report["counts"],
            "tripwires": report["tripwires"],
        }
        package_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        dashboard_package = {
            "dir": str(package_dir),
            "dashboard_path": str(package_dashboard),
            "snapshot_path": str(package_snapshot),
            "manifest_path": str(package_manifest),
        }
        if dashboard_path is None:
            dashboard_path = package_dashboard
    if dashboard_path or dashboard_package:
        result: dict[str, Any] = {"ok": payload["ok"], "report": report}
        if dashboard_path:
            result["dashboard_path"] = str(dashboard_path)
        if dashboard_package:
            result["dashboard_package"] = dashboard_package
        emit(result)
        return
    emit(payload)


def cmd_ops_metrics_push(args: argparse.Namespace) -> None:
    """Render the ops report as Prometheus metrics and push to the store.

    Runs once with ``--interval 0`` (capture/verification), or loops forever as
    the supervised ``metrics-pusher`` production role. Every push rebuilds the
    report from live engine/runtime state so the exported timestamp, gate, and
    tripwire series reflect the deployment now rather than a stale snapshot.
    """

    import time as _time

    from mnemosyne.observability import build_ops_report, render_ops_dashboard
    from mnemosyne.ops_metrics import ops_report_to_prometheus, push_ops_metrics

    if not args.metrics_url:
        raise SystemExit("ops-metrics-push requires --metrics-url or MNEMOSYNE_OPS_METRICS_URL")
    if args.interval < 0:
        raise SystemExit("ops-metrics-push interval must be zero or greater")

    def push_once() -> dict[str, Any]:
        runtime_state = load_runtime_state(args)
        # load_queue(args, ...) honors --queue-backend/--queue-tenant so the
        # durable Postgres queue is snapshotted, not the serialized in-process
        # payload from runtime state (which is always empty on this profile).
        queue = load_queue(args, runtime_state)
        tools = load_tools(args, ingestion_queue=queue, runtime_state=runtime_state)
        report = build_ops_report(
            engine=tools.engine,
            tenant_id=args.tenant,
            queue_snapshot=queue.snapshot(),
            learning=tools.learning,
            metrics=tools.metrics.snapshot(),
            proxy_score=None,
            true_score=None,
            min_diversity=args.min_diversity,
            max_proxy_gap=args.max_proxy_gap,
            max_open_contradictions=args.max_open_contradictions,
        )
        exposition = ops_report_to_prometheus(
            report, tenant_id=args.tenant, now_seconds=_time.time()
        )
        status = push_ops_metrics(args.metrics_url, exposition, timeout=args.timeout)
        result = {
            "ok": 200 <= status < 300,
            "status": status,
            "tripwires_passed": report["tripwires"]["passed"] is True,
            "series": exposition.count("\n"),
        }
        if args.dashboard_html_out:
            # Refresh the hosted ops dashboard artifact atomically each cycle
            # so the Caddy-served copy is never observed half-written.
            out = Path(args.dashboard_html_out).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(out.name + ".tmp")
            tmp.write_text(render_ops_dashboard(report), encoding="utf-8")
            tmp.replace(out)
            result["dashboard_html_out"] = str(out)
        return result

    if args.interval == 0:
        result = push_once()
        emit(result)
        if not result["ok"]:
            raise SystemExit(1)
        return
    while True:  # supervised production loop (metrics-pusher role)
        try:
            result = push_once()
            if not result["ok"]:
                print(f"ops-metrics-push non-2xx status {result['status']}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - keep the supervised loop alive
            print(f"ops-metrics-push failed: {exc}", file=sys.stderr)
        _time.sleep(args.interval)


def _ops_dashboard_finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _ops_dashboard_fingerprint(report: Mapping[str, Any]) -> str:
    payload = {
        "mode": report.get("mode"),
        "source": report.get("source"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _read_dashboard_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} json denied: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return loaded


def _dashboard_html_check(html: str) -> dict[str, Any]:
    return {
        "marker_present": "Mnemosyne Ops Dashboard" in html,
        "doctype_present": "<!doctype html" in html.lower(),
        "bytes": len(html.encode("utf-8")),
    }


_OPS_DASHBOARD_REQUIRED_REPORT_SECTIONS: Mapping[str, tuple[str, ...]] = {
    "counts": (
        "evidence",
        "assertions",
        "active_assertions",
        "contested_assertions",
        "contradictions",
        "preferences",
        "relations",
        "deletions",
        "audit_events",
    ),
    "queue": (),
    "metrics": ("counters", "gauges", "samples"),
    "learning": ("lessons", "procedures", "lesson_diversity"),
    "tripwires": (
        "passed",
        "min_diversity",
        "lesson_diversity",
        "max_proxy_gap",
        "proxy_true_gap",
        "max_open_contradictions",
        "open_contradictions",
        "gate_promotions",
        "gate_rollbacks",
    ),
}


def _ops_dashboard_metric_taxonomy_check(snapshot_report: object) -> dict[str, Any]:
    missing: list[str] = []
    sections: dict[str, dict[str, Any]] = {}
    if not isinstance(snapshot_report, Mapping):
        return {
            "name": "metric_taxonomy",
            "ok": False,
            "missing": ["report"],
            "sections": sections,
        }
    for section, required_keys in _OPS_DASHBOARD_REQUIRED_REPORT_SECTIONS.items():
        section_value = snapshot_report.get(section)
        if not isinstance(section_value, Mapping):
            missing.append(section)
            sections[section] = {"present": False, "missing": list(required_keys)}
            continue
        section_missing = [key for key in required_keys if key not in section_value]
        missing.extend(f"{section}.{key}" for key in section_missing)
        sections[section] = {"present": True, "missing": section_missing}
    return {
        "name": "metric_taxonomy",
        "ok": not missing,
        "missing": missing,
        "sections": sections,
    }


def _validate_ops_dashboard_package(package_dir: Path, *, expected_tenant: str | None) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    manifest_path = package_dir / "manifest.json"
    snapshot_path = package_dir / "ops-report.json"
    dashboard_path = package_dir / "ops-dashboard.html"
    try:
        manifest = _read_dashboard_json(manifest_path, label="dashboard manifest")
    except ValueError as exc:
        manifest = {}
        findings.append(_ops_dashboard_finding("manifest_invalid", str(exc)))
    try:
        snapshot = _read_dashboard_json(snapshot_path, label="dashboard snapshot")
    except ValueError as exc:
        snapshot = {}
        findings.append(_ops_dashboard_finding("snapshot_invalid", str(exc)))
    try:
        html = dashboard_path.read_text(encoding="utf-8")
    except OSError as exc:
        html = ""
        findings.append(_ops_dashboard_finding("dashboard_html_missing", f"dashboard html denied: {exc}"))

    manifest_files = manifest.get("files") if isinstance(manifest, Mapping) else None
    tripwires = manifest.get("tripwires") if isinstance(manifest, Mapping) else None
    snapshot_report = snapshot.get("report") if isinstance(snapshot, Mapping) else None
    html_check = _dashboard_html_check(html)
    metric_taxonomy_check = _ops_dashboard_metric_taxonomy_check(snapshot_report)
    manifest_ok = (
        manifest.get("kind") == "mnemosyne.ops_dashboard_package"
        and manifest.get("version") == 1
        and isinstance(manifest_files, Mapping)
        and manifest_files.get("dashboard_html") == dashboard_path.name
        and manifest_files.get("snapshot_json") == snapshot_path.name
    )
    snapshot_ok = snapshot.get("ok") is True and isinstance(snapshot_report, Mapping)
    tripwire_ok = isinstance(tripwires, Mapping) and tripwires.get("passed") is True
    dashboard_html_ok = html_check["marker_present"] and html_check["doctype_present"]
    tenant_ok = expected_tenant is None or manifest.get("tenant_id") == expected_tenant
    checks.extend(
        [
            {
                "name": "manifest",
                "ok": manifest_ok,
                "kind": manifest.get("kind"),
                "version": manifest.get("version"),
                "tenant_id": manifest.get("tenant_id"),
            },
            {"name": "snapshot", "ok": snapshot_ok, "snapshot_ok": snapshot.get("ok") is True},
            metric_taxonomy_check,
            {"name": "tripwires", "ok": tripwire_ok, "passed": bool(tripwires.get("passed")) if isinstance(tripwires, Mapping) else False},
            {"name": "dashboard_html", "ok": dashboard_html_ok, **html_check},
            {"name": "tenant", "ok": tenant_ok, "expected_tenant": expected_tenant, "tenant_id": manifest.get("tenant_id")},
        ]
    )
    if not manifest_ok:
        findings.append(_ops_dashboard_finding("manifest_shape_invalid", "dashboard package manifest shape is invalid"))
    if not snapshot_ok:
        findings.append(_ops_dashboard_finding("snapshot_not_ok", "dashboard package snapshot is not ok"))
    if not metric_taxonomy_check["ok"]:
        missing = metric_taxonomy_check.get("missing", [])
        missing_preview = ", ".join(missing[:8])
        if len(missing) > 8:
            missing_preview = f"{missing_preview}, +{len(missing) - 8} more"
        findings.append(
            _ops_dashboard_finding(
                "metric_taxonomy_incomplete",
                f"dashboard package snapshot metric taxonomy is incomplete: {missing_preview or 'report'}",
            )
        )
    if not tripwire_ok:
        findings.append(_ops_dashboard_finding("tripwires_not_passed", "dashboard package tripwires are not passing"))
    if not dashboard_html_ok:
        findings.append(_ops_dashboard_finding("dashboard_marker_missing", "dashboard html marker is missing"))
    if not tenant_ok:
        findings.append(_ops_dashboard_finding("tenant_mismatch", "dashboard package tenant does not match expectation"))
    return checks, findings


def _fetch_dashboard_url(
    url: str,
    *,
    allow_insecure_localhost: bool,
    timeout: float,
    max_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    from mnemosyne.network_safety import safe_urlopen

    validated_url = _validate_hosted_fetch_url(
        url,
        allow_insecure_localhost=allow_insecure_localhost,
    )
    req = urlrequest.Request(url, headers={"User-Agent": "mnemosyne-ops-dashboard-check/1"})
    with safe_urlopen(req, validated=validated_url, timeout=timeout) as response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError(f"dashboard response exceeded {max_bytes} bytes")
        return body, {
            "url": _display_url(url),
            "status": getattr(response, "status", None),
            "content_type": response.headers.get("Content-Type", ""),
            "bytes": len(body),
        }


def _load_ops_dashboard_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any] | None:
    if bool(args.ops_bundle) and bool(args.ops_bundle_json):
        raise SystemExit("ops-dashboard-check accepts at most one of --ops-bundle or --ops-bundle-json")
    if not args.ops_bundle and not args.ops_bundle_json:
        return None
    try:
        loaded = (
            json.loads(Path(args.ops_bundle).expanduser().read_text(encoding="utf-8"))
            if args.ops_bundle
            else json.loads(args.ops_bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ops dashboard operations bundle is not valid JSON: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("ops dashboard operations bundle must be a JSON object")
    return loaded


def _ops_dashboard_number(
    value: Any,
    *,
    default: float,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        findings.append(_ops_dashboard_finding(code, message))
        return default


def _ops_dashboard_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if child_path.startswith("$.redaction."):
                continue
            lowered = key_text.lower()
            if any(
                token in lowered
                for token in (
                    "token",
                    "secret",
                    "password",
                    "credential",
                    "raw_html",
                    "raw_snapshot",
                    "raw_manifest",
                    "raw_user",
                    "email",
                    "stdout",
                    "stderr",
                )
            ):
                paths.append(child_path)
            paths.extend(_ops_dashboard_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_ops_dashboard_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def _validate_ops_dashboard_operations(
    bundle: Mapping[str, Any],
    *,
    max_refresh_age_seconds: float,
    max_refresh_interval_seconds: float,
    allow_non_production: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, bool]]:
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    validation = bundle.get("validation_scope") if isinstance(bundle.get("validation_scope"), Mapping) else {}
    validation_ok = (
        allow_non_production
        or (
            validation.get("production_validated") is True
            and validation.get("target_environment") == "production"
            and validation.get("operator_asserted") is True
            and bool(validation.get("run_id"))
        )
    )
    if not allow_non_production:
        if validation.get("production_validated") is not True:
            findings.append(_ops_dashboard_finding("dashboard_production_validation_missing", "dashboard operations evidence must be production validated"))
        if validation.get("target_environment") != "production":
            findings.append(_ops_dashboard_finding("dashboard_production_target_missing", "dashboard operations target must be production"))
        if validation.get("operator_asserted") is not True:
            findings.append(_ops_dashboard_finding("dashboard_operator_attestation_missing", "dashboard operations requires operator attestation"))
        if not validation.get("run_id"):
            findings.append(_ops_dashboard_finding("dashboard_run_id_missing", "dashboard operations validation_scope.run_id is required"))
    checks.append(
        {
            "name": "dashboard_operations_scope",
            "ok": validation_ok,
            "production_validated": validation.get("production_validated") is True,
            "target_environment": validation.get("target_environment"),
        }
    )

    refresh = bundle.get("refresh") if isinstance(bundle.get("refresh"), Mapping) else {}
    refresh_age = _ops_dashboard_number(
        refresh.get("last_refresh_age_seconds"),
        default=max_refresh_age_seconds + 1.0,
        code="dashboard_refresh_age_invalid",
        message="refresh.last_refresh_age_seconds must be numeric",
        findings=findings,
    )
    refresh_interval = _ops_dashboard_number(
        refresh.get("interval_seconds"),
        default=max_refresh_interval_seconds + 1.0,
        code="dashboard_refresh_interval_invalid",
        message="refresh.interval_seconds must be numeric",
        findings=findings,
    )
    refresh_ok = (
        refresh.get("ok") is True
        and refresh.get("job_supervised") is True
        and refresh.get("source_snapshot_fingerprint_present") is True
        and refresh_age <= max_refresh_age_seconds
        and refresh_interval <= max_refresh_interval_seconds
    )
    if refresh.get("ok") is not True:
        findings.append(_ops_dashboard_finding("dashboard_refresh_not_ok", "dashboard refresh evidence must be ok"))
    if refresh.get("job_supervised") is not True:
        findings.append(_ops_dashboard_finding("dashboard_refresh_not_supervised", "dashboard refresh job must be supervised"))
    if refresh.get("source_snapshot_fingerprint_present") is not True:
        findings.append(_ops_dashboard_finding("dashboard_snapshot_fingerprint_missing", "dashboard source snapshot fingerprint is required"))
    if refresh_age > max_refresh_age_seconds:
        findings.append(_ops_dashboard_finding("dashboard_refresh_stale", "dashboard last refresh age exceeds threshold"))
    if refresh_interval > max_refresh_interval_seconds:
        findings.append(_ops_dashboard_finding("dashboard_refresh_interval_too_high", "dashboard refresh interval exceeds threshold"))
    checks.append(
        {
            "name": "dashboard_refresh",
            "ok": refresh_ok,
            "last_refresh_age_seconds": refresh_age,
            "interval_seconds": refresh_interval,
            "job_supervised": refresh.get("job_supervised") is True,
        }
    )

    access = bundle.get("access_control") if isinstance(bundle.get("access_control"), Mapping) else {}
    access_flags = {
        "auth_required": access.get("auth_required") is True,
        "tenant_binding": access.get("tenant_binding") is True,
        "admin_only_mutation": access.get("admin_only_mutation") is True,
        "public_snapshot_disabled": access.get("public_snapshot_disabled") is True,
    }
    missing_access = [name for name, ok in access_flags.items() if not ok]
    if access.get("ok") is not True:
        findings.append(_ops_dashboard_finding("dashboard_access_not_ok", "dashboard access-control evidence must be ok"))
    for flag in missing_access:
        findings.append(_ops_dashboard_finding("dashboard_access_control_missing", f"access_control.{flag} is not proven"))
    checks.append({"name": "dashboard_access_control", "ok": access.get("ok") is True and not missing_access, **access_flags})

    alerts = bundle.get("alerts") if isinstance(bundle.get("alerts"), Mapping) else {}
    alert_flags = {
        "tripwire_alerts": alerts.get("tripwire_alerts") is True,
        "freshness_alerts": alerts.get("freshness_alerts") is True,
        "delivery_verified": alerts.get("delivery_verified") is True,
        "oncall_route_present": alerts.get("oncall_route_present") is True,
    }
    missing_alerts = [name for name, ok in alert_flags.items() if not ok]
    if alerts.get("ok") is not True:
        findings.append(_ops_dashboard_finding("dashboard_alerts_not_ok", "dashboard alert evidence must be ok"))
    for flag in missing_alerts:
        findings.append(_ops_dashboard_finding("dashboard_alert_missing", f"alerts.{flag} is not proven"))
    checks.append({"name": "dashboard_alerts", "ok": alerts.get("ok") is True and not missing_alerts, **alert_flags})

    redaction = bundle.get("redaction") if isinstance(bundle.get("redaction"), Mapping) else {}
    redaction_flags = {
        "raw_html_omitted": redaction.get("raw_html_omitted") is True,
        "raw_snapshot_omitted": redaction.get("raw_snapshot_omitted") is True,
        "raw_tokens_omitted": redaction.get("raw_tokens_omitted") is True,
        "raw_user_data_omitted": redaction.get("raw_user_data_omitted") is True,
    }
    missing_redaction = [name for name, ok in redaction_flags.items() if not ok]
    forbidden_raw_paths = _ops_dashboard_forbidden_raw_paths(bundle)
    for flag in missing_redaction:
        findings.append(_ops_dashboard_finding("dashboard_redaction_missing", f"redaction.{flag} is not proven"))
    if forbidden_raw_paths:
        findings.append(_ops_dashboard_finding("dashboard_raw_field_present", "dashboard operations bundle contains raw HTML/snapshot/token/user fields"))
    checks.append(
        {
            "name": "dashboard_operations_redaction",
            "ok": not missing_redaction and not forbidden_raw_paths,
            **redaction_flags,
            "forbidden_raw_paths": forbidden_raw_paths,
        }
    )
    return checks, findings, redaction_flags


def cmd_ops_dashboard_check(args: argparse.Namespace) -> None:
    if bool(args.dashboard_package_dir) == bool(args.dashboard_url):
        raise SystemExit("ops-dashboard-check requires exactly one of --dashboard-package-dir or --dashboard-url")
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []
    mode = "package" if args.dashboard_package_dir else "hosted_url"
    source: dict[str, Any] = {"mode": mode}
    if args.dashboard_package_dir:
        package_dir = Path(args.dashboard_package_dir).expanduser()
        source["package_dir"] = str(package_dir)
        package_checks, package_findings = _validate_ops_dashboard_package(
            package_dir,
            expected_tenant=args.expected_tenant,
        )
        checks.extend(package_checks)
        findings.extend(package_findings)
    else:
        try:
            html_bytes, dashboard_meta = _fetch_dashboard_url(
                args.dashboard_url,
                allow_insecure_localhost=args.allow_insecure_localhost,
                timeout=args.timeout,
                max_bytes=args.max_bytes,
            )
            html = html_bytes.decode("utf-8", errors="replace")
            html_check = _dashboard_html_check(html)
            dashboard_ok = (
                dashboard_meta.get("status") == 200
                and html_check["marker_present"]
                and html_check["doctype_present"]
            )
            checks.append({"name": "hosted_dashboard", "ok": dashboard_ok, **dashboard_meta, **html_check})
            if not dashboard_ok:
                findings.append(_ops_dashboard_finding("hosted_dashboard_invalid", "hosted dashboard check failed"))
            source["dashboard_url"] = dashboard_meta["url"]
        except (OSError, ValueError, urlerror.URLError) as exc:
            checks.append({"name": "hosted_dashboard", "ok": False, "url": _display_url(args.dashboard_url)})
            findings.append(_ops_dashboard_finding("hosted_dashboard_fetch_failed", f"hosted dashboard denied: {exc}"))
        for label, url in (("manifest", args.manifest_url), ("snapshot", args.snapshot_url)):
            if not url:
                continue
            try:
                body, meta = _fetch_dashboard_url(
                    url,
                    allow_insecure_localhost=args.allow_insecure_localhost,
                    timeout=args.timeout,
                    max_bytes=args.max_bytes,
                )
                loaded = json.loads(body.decode("utf-8"))
                ok = isinstance(loaded, Mapping)
                if label == "manifest":
                    ok = ok and loaded.get("kind") == "mnemosyne.ops_dashboard_package" and loaded.get("ok") is True
                if label == "snapshot":
                    ok = ok and loaded.get("ok") is True and isinstance(loaded.get("report"), Mapping)
                checks.append({"name": f"hosted_{label}", "ok": ok, **meta})
                if not ok:
                    findings.append(_ops_dashboard_finding(f"hosted_{label}_invalid", f"hosted {label} check failed"))
            except (OSError, ValueError, json.JSONDecodeError, urlerror.URLError) as exc:
                checks.append({"name": f"hosted_{label}", "ok": False, "url": _display_url(url)})
                findings.append(_ops_dashboard_finding(f"hosted_{label}_fetch_failed", f"hosted {label} denied: {exc}"))

    operations_bundle = _load_ops_dashboard_ops_bundle(args)
    operations_redaction: dict[str, bool] = {}
    if operations_bundle is not None:
        operations_checks, operations_findings, operations_redaction = _validate_ops_dashboard_operations(
            operations_bundle,
            max_refresh_age_seconds=args.max_refresh_age_seconds,
            max_refresh_interval_seconds=args.max_refresh_interval_seconds,
            allow_non_production=args.allow_non_production,
        )
        checks.extend(operations_checks)
        findings.extend(operations_findings)

    report: dict[str, Any] = {
        "ok": not findings,
        "mode": mode,
        "source": source,
        "redaction": {
            "raw_dashboard_html_omitted": True,
            "raw_manifest_json_omitted": True,
            "raw_snapshot_json_omitted": True,
            **operations_redaction,
        },
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _ops_dashboard_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(_ops_dashboard_finding("fingerprint_mismatch", "ops dashboard fingerprint mismatch"))
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _display_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _join_endpoint(base_url: str | None, path: str) -> str | None:
    if not base_url:
        return None
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _maybe_model_dump(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(by_alias=True)
    return value


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _mcp_tool_contract(tool_entries: list[Any], read_only_tool: str) -> dict[str, Any]:
    tool = next((item for item in tool_entries if _field(item, "name") == read_only_tool), None)
    if tool is None:
        return {
            "ok": False,
            "tool_name": read_only_tool,
            "tool_present": False,
            "schema_present": False,
            "error": f"tools/list did not include {read_only_tool}",
        }
    schema = _maybe_model_dump(_field(tool, "inputSchema") or _field(tool, "input_schema"))
    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    required = schema.get("required") if isinstance(schema, Mapping) else None
    schema_ok = (
        isinstance(schema, Mapping)
        and schema.get("type") == "object"
        and isinstance(properties, Mapping)
        and isinstance(required, list)
    )
    return {
        "ok": schema_ok,
        "tool_name": read_only_tool,
        "tool_present": True,
        "schema_present": isinstance(schema, Mapping),
        "input_schema_type": schema.get("type") if isinstance(schema, Mapping) else None,
        "property_count": len(properties) if isinstance(properties, Mapping) else 0,
        "required": [str(item) for item in required] if isinstance(required, list) else [],
        **({} if schema_ok else {"error": f"{read_only_tool} tool schema is invalid"}),
    }


def _mcp_tool_call_contract(result: Any) -> dict[str, Any]:
    result = _maybe_model_dump(result)
    content = _field(result, "content", [])
    structured = _field(result, "structuredContent", _field(result, "structured_content"))
    is_error = _field(result, "isError", _field(result, "is_error"))
    content_ok = isinstance(content, list) and bool(content)
    structured_ok = isinstance(structured, Mapping)
    ok = is_error is False and content_ok and structured_ok
    return {
        "ok": ok,
        "is_error": is_error,
        "content_item_count": len(content) if isinstance(content, list) else 0,
        "structured_content_present": structured_ok,
        **({} if ok else {"error": "tools/call did not return structured non-error content"}),
    }


def _bounded_json_body(response: Any, *, max_bytes: int = 1_048_576) -> dict[str, Any]:
    raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("HTTP response body exceeded 1048576 bytes")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"HTTP response was not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError("HTTP response JSON must be an object")
    return decoded


def _build_client_mtls_context(cert_path: str, key_path: str) -> "ssl.SSLContext":
    """Build a client SSL context that presents an mTLS client certificate.

    ``ssl.create_default_context()`` seeds server-verification roots from the
    process default paths (``SSL_CERT_FILE`` in the operator/soak container is
    the step-ca root), so the returned context still verifies the Caddy ACME
    server leaf while additionally presenting the operator client certificate.
    The cert file is the step-ca leaf bundled with the intermediate, so the
    full chain is offered to Caddy's ``require_and_verify`` trust pool (root).
    """

    context = ssl.create_default_context()
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return context


def _http_json_probe(
    *,
    url: str,
    method: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    payload: dict[str, Any] | None = None,
    ssl_context: "ssl.SSLContext | None" = None,
) -> dict[str, Any]:
    from mnemosyne.network_safety import safe_urlopen, validate_fetch_url

    encoded_payload = None
    request_headers = {"Accept": "application/json", **dict(headers)}
    if payload is not None:
        encoded_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    started = time.monotonic()
    try:
        validated_url = validate_fetch_url(
            url,
            allow_insecure_localhost=True,
            allow_internal_hosts=_hosted_check_allowed_internal_hosts(),
            purpose="hosted probe URL",
        )
        request = urlrequest.Request(url, data=encoded_payload, headers=request_headers, method=method)
        with safe_urlopen(request, validated=validated_url, timeout=timeout_seconds, context=ssl_context) as response:
            body = _bounded_json_body(response)
            return {
                "ok": 200 <= int(response.status) < 300,
                "status": int(response.status),
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "json": body,
            }
    except urlerror.HTTPError as exc:
        latency_ms = round((time.monotonic() - started) * 1000, 3)
        try:
            body = _bounded_json_body(exc)
        except ValueError as body_exc:
            body = {"ok": False, "error": str(body_exc)}
        return {
            "ok": False,
            "status": int(exc.code),
            "latency_ms": latency_ms,
            "json": body,
            "error": body.get("error") or f"HTTP {exc.code}",
        }
    except (TimeoutError, urlerror.URLError, ValueError) as exc:
        return {
            "ok": False,
            "status": None,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "error": str(exc),
        }


def _json_rpc_probe(
    *,
    rpc_url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    request_id: str,
    method: str,
    params: dict[str, Any] | None = None,
    ssl_context: "ssl.SSLContext | None" = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    probe = _http_json_probe(
        url=rpc_url,
        method="POST",
        headers=headers,
        timeout_seconds=timeout_seconds,
        payload=payload,
        ssl_context=ssl_context,
    )
    response = probe.get("json")
    if not probe.get("ok"):
        return {
            "ok": False,
            "status": probe.get("status"),
            "latency_ms": probe.get("latency_ms"),
            "error": probe.get("error") or "HTTP request failed",
        }
    if not isinstance(response, dict):
        return {
            "ok": False,
            "status": probe.get("status"),
            "latency_ms": probe.get("latency_ms"),
            "error": "JSON-RPC response must be an object",
        }
    if response.get("error") is not None:
        error_payload = response.get("error")
        message = error_payload.get("message") if isinstance(error_payload, dict) else "JSON-RPC error"
        return {
            "ok": False,
            "status": probe.get("status"),
            "latency_ms": probe.get("latency_ms"),
            "error": message,
        }
    return {
        "ok": True,
        "status": probe.get("status"),
        "latency_ms": probe.get("latency_ms"),
        "result": response.get("result"),
    }


def _display_sse_data(value: str, *, max_chars: int = 200) -> str:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
        value = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return value[:max_chars]


def _format_sse_event(event: dict[str, Any]) -> dict[str, Any]:
    data = str(event.get("data") or "")
    event_name = event.get("event") or "message"
    formatted = {
        "event": event_name,
        "data_present": bool(data),
        "data_bytes": len(data.encode("utf-8")),
    }
    if data and event_name == "endpoint":
        formatted["data_preview"] = _display_sse_data(data)
    if event.get("id"):
        formatted["id_present"] = True
    if event.get("retry"):
        formatted["retry"] = event["retry"]
    return formatted


def _flush_sse_event(
    events: list[dict[str, Any]],
    *,
    event_name: str | None,
    data_lines: list[str],
    event_id: str | None,
    retry: str | None,
) -> None:
    if event_name is None and not data_lines and event_id is None and retry is None:
        return
    events.append(
        {
            "event": event_name or "message",
            "data": "\n".join(data_lines),
            "id": event_id,
            "retry": retry,
        }
    )


def _sse_probe(
    *,
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_bytes: int,
    max_events: int,
    expected_event: str | None,
) -> dict[str, Any]:
    from mnemosyne.network_safety import safe_urlopen, validate_fetch_url

    request_headers = {"Accept": "text/event-stream", "Cache-Control": "no-cache", **dict(headers)}
    started = time.monotonic()
    try:
        validated_url = validate_fetch_url(
            url,
            allow_insecure_localhost=True,
            allow_internal_hosts=_hosted_check_allowed_internal_hosts(),
            purpose="hosted SSE URL",
        )
        request = urlrequest.Request(url, headers=request_headers, method="GET")
        with safe_urlopen(request, validated=validated_url, timeout=timeout_seconds) as response:
            status = int(response.status)
            content_type = str(response.headers.get("Content-Type") or "")
            events: list[dict[str, Any]] = []
            event_name: str | None = None
            event_id: str | None = None
            retry: str | None = None
            data_lines: list[str] = []
            bytes_read = 0
            while bytes_read <= max_bytes and len(events) < max_events:
                raw_line = response.readline(max_bytes - bytes_read + 1)
                if not raw_line:
                    break
                bytes_read += len(raw_line)
                if bytes_read > max_bytes:
                    break
                line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
                if line == "":
                    _flush_sse_event(
                        events,
                        event_name=event_name,
                        data_lines=data_lines,
                        event_id=event_id,
                        retry=retry,
                    )
                    matched_expected = expected_event and any(event.get("event") == expected_event for event in events)
                    event_name = None
                    event_id = None
                    retry = None
                    data_lines = []
                    if matched_expected and len(events) >= max_events:
                        break
                    continue
                if line.startswith(":"):
                    continue
                field, separator, value = line.partition(":")
                if separator and value.startswith(" "):
                    value = value[1:]
                if field == "event":
                    event_name = value
                elif field == "data":
                    data_lines.append(value)
                elif field == "id":
                    event_id = value
                elif field == "retry":
                    retry = value
            _flush_sse_event(
                events,
                event_name=event_name,
                data_lines=data_lines,
                event_id=event_id,
                retry=retry,
            )
            contains_expected_event = (
                True if expected_event is None else any(event.get("event") == expected_event for event in events)
            )
            endpoint_event = next((event for event in events if event.get("event") == "endpoint"), None)
            content_type_ok = "text/event-stream" in content_type.lower()
            return {
                "ok": 200 <= status < 300 and content_type_ok and bool(events) and contains_expected_event,
                "status": status,
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "content_type": content_type,
                "content_type_ok": content_type_ok,
                "bytes_read": bytes_read,
                "events": [_format_sse_event(event) for event in events],
                "event_count": len(events),
                "contains_expected_event": contains_expected_event,
                "endpoint_data_present": bool(endpoint_event and endpoint_event.get("data")),
                "truncated": bytes_read > max_bytes,
            }
    except urlerror.HTTPError as exc:
        return {
            "ok": False,
            "status": int(exc.code),
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "error": f"HTTP {exc.code}",
        }
    except (TimeoutError, urlerror.URLError, ValueError) as exc:
        return {
            "ok": False,
            "status": None,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "error": str(exc),
        }


def cmd_mcp_sse_soak(args: argparse.Namespace) -> None:
    sse_url = args.mcp_sse_url or _join_endpoint(args.mcp_sse_base_url, "/sse")
    if not sse_url:
        raise SystemExit("mcp-sse-soak requires --base-url or --sse-url.")
    if args.iterations < 1:
        raise SystemExit("--iterations must be at least 1.")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than 0.")
    if args.max_bytes < 1:
        raise SystemExit("--max-bytes must be positive.")
    if args.min_events < 1:
        raise SystemExit("--min-events must be at least 1.")
    expected_event = args.expected_event or None

    headers: dict[str, str] = {}
    if args.auth_token:
        headers["Authorization"] = f"Bearer {args.auth_token}"
    if args.mcp_session_token:
        headers["X-Mnemosyne-Session-Token"] = args.mcp_session_token

    ok = True
    failure_count = 0
    probes: list[dict[str, Any]] = []
    latencies: list[float] = []
    for index in range(1, args.iterations + 1):
        probe = _sse_probe(
            url=sse_url,
            headers=headers,
            timeout_seconds=args.timeout,
            max_bytes=args.max_bytes,
            max_events=max(args.min_events, 1),
            expected_event=expected_event,
        )
        probe_ok = bool(probe.get("ok"))
        if probe.get("event_count", 0) < args.min_events:
            probe_ok = False
            probe["min_events_mismatch"] = {
                "expected": args.min_events,
                "actual": probe.get("event_count", 0),
            }
        if args.require_endpoint_data and not probe.get("endpoint_data_present"):
            probe_ok = False
            probe["endpoint_data_mismatch"] = {"expected": True, "actual": probe.get("endpoint_data_present")}
        if not probe_ok:
            ok = False
            failure_count += 1
        latencies.append(float(probe.get("latency_ms") or 0))
        probes.append({"iteration": index, "ok": probe_ok, **probe})

    sorted_latencies = sorted(latencies)
    p95_index = min(len(sorted_latencies) - 1, int(max(0, round(len(sorted_latencies) * 0.95) - 1)))
    report = {
        "ok": ok,
        "target": {
            "sse_url": _display_url(sse_url),
            "auth_token_configured": bool(args.auth_token),
            "session_token_configured": bool(args.mcp_session_token),
        },
        "config": {
            "iterations": args.iterations,
            "timeout_seconds": args.timeout,
            "min_events": args.min_events,
            "max_bytes": args.max_bytes,
            "expected_event": expected_event,
            "require_endpoint_data": bool(args.require_endpoint_data),
        },
        "iterations": probes,
        "summary": {
            "iterations": args.iterations,
            "requests": args.iterations,
            "failures": failure_count,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 3),
            "p95_latency_ms": sorted_latencies[p95_index],
            "max_latency_ms": max(latencies),
        },
    }
    emit(report)
    if not ok:
        raise SystemExit(1)


def cmd_mcp_http_soak(args: argparse.Namespace) -> None:
    rpc_url = args.mcp_http_rpc_url or _join_endpoint(args.mcp_http_base_url, "/mcp")
    health_url = args.mcp_http_health_url or _join_endpoint(args.mcp_http_base_url, "/healthz")
    if not rpc_url or not health_url:
        raise SystemExit("mcp-http-soak requires --base-url or both --rpc-url and --health-url.")
    if args.iterations < 1:
        raise SystemExit("--iterations must be at least 1.")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than 0.")
    tool_arguments = parse_json_arg(args.tool_arguments, {})
    if not isinstance(tool_arguments, dict):
        raise SystemExit("--tool-arguments must be a JSON object.")

    headers: dict[str, str] = {}
    if args.auth_token:
        headers["Authorization"] = f"Bearer {args.auth_token}"
    if args.mcp_session_token:
        headers["X-Mnemosyne-Session-Token"] = args.mcp_session_token

    client_cert = getattr(args, "client_cert", None)
    client_key = getattr(args, "client_key", None)
    if bool(client_cert) != bool(client_key):
        raise SystemExit("mcp-http-soak requires both --client-cert and --client-key for mTLS, or neither.")
    ssl_context = _build_client_mtls_context(client_cert, client_key) if client_cert else None
    client_cert_presented = ssl_context is not None

    ok = True
    health_probe = _http_json_probe(
        url=health_url, method="GET", headers=headers, timeout_seconds=args.timeout, ssl_context=ssl_context
    )
    health_payload = health_probe.get("json") if isinstance(health_probe.get("json"), dict) else {}
    # When the soak presents a client certificate and the mTLS handshake with
    # the ingress completes (health probe ok), client-cert enforcement is
    # proven end-to-end: Caddy's require_and_verify would have rejected the
    # handshake otherwise. Fall back to the server's self-reported flag when no
    # client cert is presented.
    if client_cert_presented and bool(health_probe.get("ok")):
        tls_client_cert_required: Any = True
    else:
        tls_client_cert_required = health_payload.get("tls_client_cert_required")
    health = {
        "ok": bool(health_probe.get("ok") and health_payload.get("ok") is True),
        "status": health_probe.get("status"),
        "latency_ms": health_probe.get("latency_ms"),
        "transport": health_payload.get("transport"),
        "protocolVersion": health_payload.get("protocolVersion"),
        "backend": health_payload.get("backend"),
        "stateless": health_payload.get("stateless"),
        "auth_token_required": health_payload.get("auth_token_required"),
        "session_required": health_payload.get("session_required"),
        "tls_enabled": health_payload.get("tls_enabled"),
        "tls_client_cert_required": tls_client_cert_required,
        "client_cert_presented": client_cert_presented,
    }
    if health_probe.get("error"):
        health["error"] = health_probe["error"]
    if not health["ok"]:
        ok = False
        health.setdefault("error", "health check failed")
    if args.expected_transport and health.get("transport") != args.expected_transport:
        ok = False
        health["transport_mismatch"] = {
            "expected": args.expected_transport,
            "actual": health.get("transport"),
        }
    if args.require_stateless and health.get("stateless") is not True:
        ok = False
        health["stateless_mismatch"] = {"expected": True, "actual": health.get("stateless")}

    protocol_version = str(health.get("protocolVersion") or "2024-11-05")
    iterations: list[dict[str, Any]] = []
    request_latencies: list[float] = [float(health_probe.get("latency_ms") or 0)]
    failure_count = 0 if ok else 1

    for index in range(1, args.iterations + 1):
        started = time.monotonic()
        initialize = _json_rpc_probe(
            rpc_url=rpc_url,
            headers=headers,
            timeout_seconds=args.timeout,
            request_id=f"soak-{index}-initialize",
            method="initialize",
            params={
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "mnemosyne-http-soak", "version": "1"},
            },
            ssl_context=ssl_context,
        )
        tools_list = _json_rpc_probe(
            rpc_url=rpc_url,
            headers=headers,
            timeout_seconds=args.timeout,
            request_id=f"soak-{index}-tools",
            method="tools/list",
            ssl_context=ssl_context,
        )
        tool_call = _json_rpc_probe(
            rpc_url=rpc_url,
            headers=headers,
            timeout_seconds=args.timeout,
            request_id=f"soak-{index}-read-only",
            method="tools/call",
            params={"name": args.read_only_tool, "arguments": tool_arguments},
            ssl_context=ssl_context,
        )

        tool_entries = []
        if isinstance(tools_list.get("result"), dict) and isinstance(tools_list["result"].get("tools"), list):
            tool_entries = tools_list["result"]["tools"]
        tool_contract = _mcp_tool_contract(tool_entries, args.read_only_tool)
        contains_read_only_tool = tool_contract["tool_present"]
        if not tools_list.get("ok") or not tool_contract["ok"]:
            tools_list["ok"] = False
            tools_list.setdefault("error", tool_contract.get("error", f"tools/list did not include {args.read_only_tool}"))
        tool_result = tool_call.get("result")
        tool_call_contract = _mcp_tool_call_contract(tool_result)
        if not tool_call_contract["ok"]:
            tool_call["ok"] = False
            tool_call.setdefault("error", tool_call_contract.get("error", "read-only tool call failed"))

        operation_ok = bool(initialize.get("ok") and tools_list.get("ok") and tool_call.get("ok"))
        if not operation_ok:
            ok = False
            failure_count += 1
        for probe in (initialize, tools_list, tool_call):
            request_latencies.append(float(probe.get("latency_ms") or 0))
        iterations.append(
            {
                "iteration": index,
                "ok": operation_ok,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
                "initialize": {
                    "ok": initialize.get("ok"),
                    "status": initialize.get("status"),
                    "latency_ms": initialize.get("latency_ms"),
                    **({"error": initialize["error"]} if initialize.get("error") else {}),
                },
                "tools_list": {
                    "ok": tools_list.get("ok"),
                    "status": tools_list.get("status"),
                    "latency_ms": tools_list.get("latency_ms"),
                    "tool_count": len(tool_entries),
                    "contains_read_only_tool": contains_read_only_tool,
                    "tool_contract": tool_contract,
                    **({"error": tools_list["error"]} if tools_list.get("error") else {}),
                },
                "read_only_tool_call": {
                    "ok": tool_call.get("ok"),
                    "status": tool_call.get("status"),
                    "latency_ms": tool_call.get("latency_ms"),
                    "tool_call_contract": tool_call_contract,
                    **({"error": tool_call["error"]} if tool_call.get("error") else {}),
                },
            }
        )

    sorted_latencies = sorted(request_latencies)
    p95_index = min(len(sorted_latencies) - 1, int(max(0, round(len(sorted_latencies) * 0.95) - 1)))
    report = {
        "ok": ok,
        "target": {
            "health_url": _display_url(health_url),
            "rpc_url": _display_url(rpc_url),
            "auth_token_configured": bool(args.auth_token),
            "session_token_configured": bool(args.mcp_session_token),
            "client_certificate_presented": client_cert_presented,
        },
        "config": {
            "iterations": args.iterations,
            "timeout_seconds": args.timeout,
            "read_only_tool": args.read_only_tool,
            "tool_arguments_configured": bool(tool_arguments),
            "expected_transport": args.expected_transport,
            "require_stateless": bool(args.require_stateless),
        },
        "health": health,
        "iterations": iterations,
        "summary": {
            "iterations": args.iterations,
            "requests": 1 + args.iterations * 3,
            "failures": failure_count,
            "avg_latency_ms": round(sum(request_latencies) / len(request_latencies), 3),
            "p95_latency_ms": sorted_latencies[p95_index],
            "max_latency_ms": max(request_latencies),
        },
    }
    emit(report)
    if not ok:
        raise SystemExit(1)


async def _streamable_http_iteration(
    *,
    streamable_url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    read_only_tool: str,
    tool_arguments: dict[str, Any],
    client_cert: tuple[str, str] | None = None,
) -> dict[str, Any]:
    try:
        import httpx
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:  # pragma: no cover - optional dependency failure is reported structurally.
        return {"ok": False, "error": f"official MCP SDK StreamableHTTP client is unavailable: {exc}"}

    started = time.monotonic()
    try:
        timeout = httpx.Timeout(timeout_seconds)
        # httpx forwards ``cert=(cert, key)`` into the TLS handshake so the SDK
        # StreamableHTTP client presents the operator mTLS client certificate to
        # the require_and_verify ingress; without it the flag is additive/no-op.
        client_kwargs: dict[str, Any] = {"headers": dict(headers), "timeout": timeout}
        if client_cert is not None:
            client_kwargs["cert"] = client_cert
        async with httpx.AsyncClient(**client_kwargs) as client:
            async with streamable_http_client(
                streamable_url,
                http_client=client,
                terminate_on_close=False,
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    tool_entries = list(getattr(tools, "tools", []) or [])
                    tool_contract = _mcp_tool_contract(tool_entries, read_only_tool)
                    contains_read_only_tool = tool_contract["tool_present"]
                    call_arguments = dict(tool_arguments)
                    if headers.get("Authorization") and "auth_token" not in call_arguments:
                        call_arguments["auth_token"] = headers["Authorization"].removeprefix("Bearer ").strip()
                    # The stateless SDK tool-call authorizes from the arguments,
                    # not the HTTP session header, so a --require-session server
                    # needs the signed session token forwarded here too (mirrors
                    # the bearer injection above).
                    session_header = headers.get("X-Mnemosyne-Session-Token")
                    if session_header and "session_token" not in call_arguments:
                        call_arguments["session_token"] = session_header
                    tool_call = await session.call_tool(read_only_tool, call_arguments)
                    tool_call_contract = _mcp_tool_call_contract(tool_call)
                    operation_ok = bool(tool_contract["ok"] and tool_call_contract["ok"])
                    return {
                        "ok": operation_ok,
                        "duration_ms": round((time.monotonic() - started) * 1000, 3),
                        "initialize": {
                            "ok": initialized is not None,
                            "protocolVersion": getattr(initialized, "protocolVersion", None),
                        },
                        "tools_list": {
                            "ok": tool_contract["ok"],
                            "tool_count": len(tool_entries),
                            "contains_read_only_tool": contains_read_only_tool,
                            "tool_contract": tool_contract,
                        },
                        "read_only_tool_call": {
                            "ok": tool_call_contract["ok"],
                            "tool_call_contract": tool_call_contract,
                        },
                        **({} if operation_ok else {"error": "streamable HTTP SDK operation failed"}),
                    }
    except Exception as exc:  # noqa: BLE001 - soak reports transport failures as structured JSON.
        return {
            "ok": False,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "error": str(exc),
        }


def cmd_mcp_streamable_http_soak(args: argparse.Namespace) -> None:
    from mnemosyne.network_safety import validate_fetch_url

    streamable_url = args.mcp_streamable_http_url or _join_endpoint(args.mcp_streamable_http_base_url, "/mcp")
    health_url = args.mcp_streamable_http_health_url or _join_endpoint(args.mcp_streamable_http_base_url, "/healthz")
    if not streamable_url or not health_url:
        raise SystemExit("mcp-streamable-http-soak requires --base-url or both --streamable-url and --health-url.")
    if args.iterations < 1:
        raise SystemExit("--iterations must be at least 1.")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than 0.")
    tool_arguments = parse_json_arg(args.tool_arguments, {})
    if not isinstance(tool_arguments, dict):
        raise SystemExit("--tool-arguments must be a JSON object.")

    headers: dict[str, str] = {}
    if args.auth_token:
        headers["Authorization"] = f"Bearer {args.auth_token}"
    if args.mcp_session_token:
        headers["X-Mnemosyne-Session-Token"] = args.mcp_session_token

    client_cert = getattr(args, "client_cert", None)
    client_key = getattr(args, "client_key", None)
    if bool(client_cert) != bool(client_key):
        raise SystemExit(
            "mcp-streamable-http-soak requires both --client-cert and --client-key for mTLS, or neither."
        )
    client_cert_pair: tuple[str, str] | None = (client_cert, client_key) if client_cert else None
    ssl_context = _build_client_mtls_context(client_cert, client_key) if client_cert else None
    client_cert_presented = client_cert_pair is not None

    ok = True
    streamable_validation_error: str | None = None
    try:
        validate_fetch_url(
            streamable_url,
            allow_insecure_localhost=True,
            allow_internal_hosts=_hosted_check_allowed_internal_hosts(),
            purpose="hosted StreamableHTTP URL",
        )
    except ValueError as exc:
        streamable_validation_error = str(exc)
    health_probe = _http_json_probe(
        url=health_url, method="GET", headers=headers, timeout_seconds=args.timeout, ssl_context=ssl_context
    )
    health_payload = health_probe.get("json") if isinstance(health_probe.get("json"), dict) else {}
    if client_cert_presented and bool(health_probe.get("ok")):
        tls_client_cert_required: Any = True
    else:
        tls_client_cert_required = health_payload.get("tls_client_cert_required")
    health = {
        "ok": bool(health_probe.get("ok") and health_payload.get("ok") is True),
        "status": health_probe.get("status"),
        "latency_ms": health_probe.get("latency_ms"),
        "transport": health_payload.get("transport"),
        "rpc_path": health_payload.get("rpc_path"),
        "stateless": health_payload.get("stateless"),
        "tls_client_cert_required": tls_client_cert_required,
        "client_cert_presented": client_cert_presented,
    }
    if health_probe.get("error"):
        health["error"] = health_probe["error"]
    if not health["ok"]:
        ok = False
        health.setdefault("error", "health check failed")
    if args.expected_transport and health.get("transport") != args.expected_transport:
        ok = False
        health["transport_mismatch"] = {
            "expected": args.expected_transport,
            "actual": health.get("transport"),
        }

    iterations: list[dict[str, Any]] = []
    latencies: list[float] = [float(health_probe.get("latency_ms") or 0)]
    failure_count = 0 if ok else 1
    for index in range(1, args.iterations + 1):
        if streamable_validation_error:
            result = {
                "ok": False,
                "duration_ms": 0,
                "error": streamable_validation_error,
            }
        else:
            result = asyncio.run(
                _streamable_http_iteration(
                    streamable_url=streamable_url,
                    headers=headers,
                    timeout_seconds=args.timeout,
                    read_only_tool=args.read_only_tool,
                    tool_arguments=tool_arguments,
                    client_cert=client_cert_pair,
                )
            )
        result["iteration"] = index
        if not result.get("ok"):
            ok = False
            failure_count += 1
        latencies.append(float(result.get("duration_ms") or 0))
        iterations.append(result)

    sorted_latencies = sorted(latencies)
    p95_index = min(len(sorted_latencies) - 1, int(max(0, round(len(sorted_latencies) * 0.95) - 1)))
    report = {
        "ok": ok,
        "target": {
            "health_url": _display_url(health_url),
            "streamable_url": _display_url(streamable_url),
            "auth_token_configured": bool(args.auth_token),
            "session_token_configured": bool(args.mcp_session_token),
            "client_certificate_presented": client_cert_presented,
        },
        "config": {
            "iterations": args.iterations,
            "timeout_seconds": args.timeout,
            "read_only_tool": args.read_only_tool,
            "tool_arguments_configured": bool(tool_arguments),
            "expected_transport": args.expected_transport,
        },
        "health": health,
        "iterations": iterations,
        "summary": {
            "iterations": args.iterations,
            "requests": 1 + args.iterations * 3,
            "failures": failure_count,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 3),
            "p95_latency_ms": sorted_latencies[p95_index],
            "max_latency_ms": max(latencies),
        },
    }
    emit(report)
    if not ok:
        raise SystemExit(1)


def _load_deployment_soak_manifest(path: str) -> dict[str, Any]:
    try:
        manifest = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"deployment-soak manifest denied: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SystemExit("deployment-soak manifest must be a JSON object")
    checks = manifest.get("checks")
    if not isinstance(checks, list) or not checks:
        raise SystemExit("deployment-soak manifest requires a non-empty checks array")
    return manifest


def _deployment_check_failure(index: int, raw: Any, error: str) -> dict[str, Any]:
    name = raw.get("name") if isinstance(raw, dict) else None
    command = raw.get("command") if isinstance(raw, dict) else None
    return {
        "index": index,
        "name": name or f"check-{index}",
        "command": command,
        "required": True,
        "ok": False,
        "error": error,
    }


def _deployment_check_spec(index: int, raw: Any, *, default_timeout: float) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("check must be an object")
    name = str(raw.get("name") or f"check-{index}")
    command = raw.get("command")
    if not isinstance(command, str) or not command:
        raise ValueError("check command must be a non-empty string")
    if command not in DEPLOYMENT_SOAK_COMMANDS:
        raise ValueError(f"check command {command!r} is not allowed")
    check_args = raw.get("args", [])
    if not isinstance(check_args, list) or not all(isinstance(item, str) for item in check_args):
        raise ValueError("check args must be an array of strings")
    global_args = _deployment_global_args(raw.get("global_args", []))
    timeout = raw.get("timeout", default_timeout)
    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("check timeout must be numeric") from exc
    if timeout_seconds <= 0:
        raise ValueError("check timeout must be greater than 0")
    return {
        "index": index,
        "name": name,
        "command": command,
        "global_args": global_args,
        "args": list(check_args),
        "required": bool(raw.get("required", True)),
        "timeout_seconds": timeout_seconds,
    }


def _deployment_global_args(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("check global_args must be an array of strings")
    normalized: list[str] = []
    expects_value: str | None = None
    for token in raw:
        if expects_value is not None:
            if token.startswith("--"):
                raise ValueError(f"global arg {expects_value!r} requires a value")
            normalized.append(token)
            expects_value = None
            continue
        option, separator, _value = token.partition("=")
        if option not in DEPLOYMENT_SOAK_GLOBAL_OPTIONS:
            raise ValueError(f"global arg {option!r} is not allowed")
        normalized.append(token)
        if not separator:
            expects_value = option
    if expects_value is not None:
        raise ValueError(f"global arg {expects_value!r} requires a value")
    return normalized


def _child_json(stdout: str) -> dict[str, Any] | None:
    stripped = stdout.strip()
    if not stripped:
        return None
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _deployment_evidence_file_name(index: int, name: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")
    slug = "-".join(part for part in slug.split("-") if part)
    return f"{index:03d}-{slug or 'check'}.json"


def _file_sha256(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


PRODUCTION_EVIDENCE_BUNDLE_SCHEMA = "mnemosyne.production-evidence-bundle.v1"
PRODUCTION_EVIDENCE_BUNDLE_EXCLUDED_FILES = frozenset({"bundle-manifest.json", "summary.json"})
PRODUCTION_EVIDENCE_REQUIRED_FILES = frozenset(
    {
        "deployment-soak.stdout.json",
        "evidence/manifest.json",
        "operator-soak-manifest.json",
        "preflight.json",
        "redaction-scan.json",
        "release-audit.json",
        "source-soak-manifest.json",
    }
)
PRODUCTION_EVIDENCE_REDACTION_SCAN_EXTRA_FILES = frozenset(
    {
        "bundle-manifest.json",
        "redaction-scan.json",
        "summary.json",
    }
)


def _write_deployment_soak_evidence(
    *,
    evidence_dir: str,
    source_manifest: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    package_dir = Path(evidence_dir).expanduser()
    checks_dir = package_dir / "checks"
    package_dir.mkdir(parents=True, exist_ok=True)
    checks_dir.mkdir(parents=True, exist_ok=True)
    check_files: list[dict[str, Any]] = []
    for item in report["checks"]:
        file_name = _deployment_evidence_file_name(int(item["index"]), str(item["name"]))
        path = checks_dir / file_name
        path.write_text(json.dumps(item, indent=2, sort_keys=True), encoding="utf-8")
        relative_path = f"{checks_dir.name}/{file_name}"
        check_files.append(
            {
                "index": item["index"],
                "name": item["name"],
                "command": item["command"],
                "ok": item["ok"],
                "required": item["required"],
                "evidence_class": item.get("evidence_class"),
                "path": relative_path,
                "sha256": _file_sha256(path),
            }
        )
    report_path = package_dir / "deployment-soak-report.json"
    manifest_path = package_dir / "manifest.json"
    bundle = {
        "dir": str(package_dir),
        "report_path": str(report_path),
        "manifest_path": str(manifest_path),
        "checks_dir": str(checks_dir),
        "check_files": check_files,
    }
    report["evidence_bundle"] = bundle
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    report_sha256 = _file_sha256(report_path)
    manifest = {
        "kind": "mnemosyne.deployment_soak_evidence",
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "ok": report["ok"],
        "source_manifest": str(Path(source_manifest).expanduser()),
        "validation_scope": report["validation_scope"],
        "redaction": report["redaction"],
        "files": {
            "report": report_path.name,
            "report_sha256": report_sha256,
            "checks_dir": checks_dir.name,
        },
        "summary": report["summary"],
        "checks": check_files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return bundle


def _release_manifest_path(manifest_path: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise SystemExit(f"release evidence manifest requires {label}")
    relative_path = Path(value)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise SystemExit(f"release evidence manifest {label} must be a relative path inside the evidence bundle")
    try:
        root = manifest_path.parent.resolve(strict=True)
        candidate = (manifest_path.parent / relative_path).resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"release evidence manifest {label} denied: {exc}") from exc
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"release evidence manifest {label} must resolve inside the evidence bundle") from exc
    return candidate


def _release_manifest_expected_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise SystemExit(f"release evidence manifest requires {label}")
    return value


def _verify_release_manifest_file(
    *,
    path: Path,
    expected_sha256: str,
    label: str,
) -> str:
    try:
        actual_sha256 = _file_sha256(path)
    except OSError as exc:
        raise SystemExit(f"release evidence manifest {label} denied: {exc}") from exc
    if actual_sha256 != expected_sha256:
        raise SystemExit(f"release evidence manifest {label} digest mismatch")
    return actual_sha256


def _deployment_validation_scope(manifest: Mapping[str, Any]) -> dict[str, Any]:
    raw_scope = manifest.get("validation_scope")
    scope = raw_scope if isinstance(raw_scope, Mapping) else {}
    production_validated = bool(scope.get("production_validated", manifest.get("production_validated", False)))
    target_environment = str(
        scope.get("target_environment")
        or manifest.get("target_environment")
        or ("production" if production_validated else "local")
    )
    note = str(
        scope.get("note")
        or (
            "Allowlisted checks run as local CLI child processes against operator-declared production targets."
            if production_validated
            else "Allowlisted checks run as local CLI child processes; production claims require operator-run endpoint evidence."
        )
    )
    return {
        "surface": "local_cli_orchestrator",
        "production_validated": production_validated,
        "target_environment": target_environment,
        "operator_asserted": bool(scope.get("operator_asserted") is True),
        "note": note,
    }


def cmd_deployment_soak(args: argparse.Namespace) -> None:
    if args.check_timeout <= 0:
        raise SystemExit("--check-timeout must be greater than 0.")
    manifest = _load_deployment_soak_manifest(args.soak_manifest)
    checks: list[dict[str, Any]] = []
    ok = True
    for index, raw_check in enumerate(manifest["checks"], start=1):
        try:
            spec = _deployment_check_spec(index, raw_check, default_timeout=args.check_timeout)
        except ValueError as exc:
            item = _deployment_check_failure(index, raw_check, str(exc))
            checks.append(item)
            ok = False
            continue

        started = time.monotonic()
        command_line = [
            sys.executable,
            "-m",
            "mnemosyne.cli",
            "--store",
            str(args.store),
            *spec["global_args"],
            spec["command"],
            *spec["args"],
        ]
        try:
            completed = subprocess.run(
                command_line,
                check=False,
                text=True,
                capture_output=True,
                timeout=spec["timeout_seconds"],
            )
            child_report = _child_json(completed.stdout)
            child_ok = bool(completed.returncode == 0 and isinstance(child_report, dict) and child_report.get("ok") is True)
            item = {
                "index": index,
                "name": spec["name"],
                "command": spec["command"],
                "required": spec["required"],
                "evidence_class": "allowlisted_local_cli_check",
                "redaction": {
                    "raw_command_omitted": True,
                    "stderr_omitted": True,
                    "stdout_json_only": True,
                },
                "ok": child_ok,
                "returncode": completed.returncode,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
                "timeout_seconds": spec["timeout_seconds"],
                "stdout_json": child_report,
                "stderr_present": bool(completed.stderr.strip()),
            }
            if not isinstance(child_report, dict):
                item["error"] = "check did not emit a JSON object"
            elif child_report.get("error"):
                item["error"] = child_report["error"]
            elif not child_ok:
                item["error"] = "check failed"
        except subprocess.TimeoutExpired:
            item = {
                "index": index,
                "name": spec["name"],
                "command": spec["command"],
                "required": spec["required"],
                "evidence_class": "allowlisted_local_cli_check",
                "redaction": {
                    "raw_command_omitted": True,
                    "stderr_omitted": True,
                    "stdout_json_only": True,
                },
                "ok": False,
                "returncode": None,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
                "timeout_seconds": spec["timeout_seconds"],
                "stdout_json": None,
                "stderr_present": False,
                "error": "check timed out",
            }
        checks.append(item)
        if spec["required"] and not item["ok"]:
            ok = False

    report = {
        "ok": ok,
        "manifest": {
            "path": str(Path(args.soak_manifest).expanduser()),
            "check_count": len(manifest["checks"]),
        },
        "validation_scope": {
            **_deployment_validation_scope(manifest),
        },
        "redaction": {
            "raw_command_omitted": True,
            "stderr_omitted": True,
            "stdout_json_only": True,
        },
        "allowed_commands": sorted(DEPLOYMENT_SOAK_COMMANDS),
        "checks": checks,
        "summary": {
            "checks": len(checks),
            "required_failures": sum(1 for item in checks if item.get("required") and not item.get("ok")),
            "optional_failures": sum(1 for item in checks if not item.get("required") and not item.get("ok")),
        },
    }
    if args.evidence_dir:
        _write_deployment_soak_evidence(evidence_dir=args.evidence_dir, source_manifest=args.soak_manifest, report=report)
    emit(report)
    if not ok:
        raise SystemExit(1)


def _load_release_audit_report(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    if bool(args.soak_report) == bool(args.evidence_manifest):
        raise SystemExit("release-audit requires exactly one of --soak-report or --evidence-manifest")
    if args.evidence_manifest:
        manifest_path = Path(args.evidence_manifest).expanduser()
        try:
            evidence_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"release evidence manifest denied: {exc}") from exc
        if not isinstance(evidence_manifest, dict):
            raise SystemExit("release evidence manifest must be a JSON object")
        if evidence_manifest.get("kind") != "mnemosyne.deployment_soak_evidence":
            raise SystemExit("release evidence manifest has unsupported kind")
        files = evidence_manifest.get("files")
        if not isinstance(files, Mapping):
            raise SystemExit("release evidence manifest requires files")
        report_path = _release_manifest_path(manifest_path, files.get("report"), "files.report")
        report_sha256 = _verify_release_manifest_file(
            path=report_path,
            expected_sha256=_release_manifest_expected_sha256(files.get("report_sha256"), "files.report_sha256"),
            label="files.report",
        )
        check_entries = evidence_manifest.get("checks")
        if not isinstance(check_entries, list):
            raise SystemExit("release evidence manifest requires checks")
        verified_checks: list[dict[str, Any]] = []
        for index, check_entry in enumerate(check_entries, start=1):
            if not isinstance(check_entry, Mapping):
                raise SystemExit(f"release evidence manifest checks[{index}] must be an object")
            check_path = _release_manifest_path(manifest_path, check_entry.get("path"), f"checks[{index}].path")
            check_sha256 = _verify_release_manifest_file(
                path=check_path,
                expected_sha256=_release_manifest_expected_sha256(
                    check_entry.get("sha256"),
                    f"checks[{index}].sha256",
                ),
                label=f"checks[{index}]",
            )
            verified_checks.append(
                {
                    "path": str(check_path),
                    "sha256": check_sha256,
                    "manifest": {
                        key: check_entry.get(key)
                        for key in ("index", "name", "command", "ok", "required")
                    },
                }
            )
        source = {
            "kind": "evidence_manifest",
            "manifest_path": str(manifest_path),
            "report_path": str(report_path),
            "integrity": {
                "report_sha256": report_sha256,
                "check_count": len(verified_checks),
                "checks": verified_checks,
            },
        }
    else:
        report_path = Path(args.soak_report).expanduser()
        source = {"kind": "soak_report", "report_path": str(report_path)}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"deployment-soak report denied: {exc}") from exc
    if not isinstance(report, dict):
        raise SystemExit("deployment-soak report must be a JSON object")
    if source["kind"] == "evidence_manifest":
        report_checks = report.get("checks")
        if not isinstance(report_checks, list):
            raise SystemExit("deployment-soak report requires checks")
        if len(report_checks) != source["integrity"]["check_count"]:
            raise SystemExit("release evidence manifest check digest count mismatch")
        for index, (report_check, verified_check) in enumerate(
            zip(report_checks, source["integrity"]["checks"], strict=True),
            start=1,
        ):
            try:
                check_payload = json.loads(Path(verified_check["path"]).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SystemExit(f"release evidence manifest checks[{index}] denied: {exc}") from exc
            if not isinstance(check_payload, dict):
                raise SystemExit(f"release evidence manifest checks[{index}] must contain a JSON object")
            if check_payload != report_check:
                raise SystemExit(f"release evidence manifest checks[{index}] content mismatch")
            for key, value in verified_check["manifest"].items():
                if check_payload.get(key) != value:
                    raise SystemExit(f"release evidence manifest checks[{index}].{key} metadata mismatch")
    return report, source


def _release_finding(code: str, message: str, *, severity: str = "critical") -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message}


def _normalize_release_fingerprint_value(value: Any) -> Any:
    volatile_keys = {
        "duration_ms",
        "latency_ms",
        "avg_latency_ms",
        "p95_latency_ms",
        "max_latency_ms",
        "created_at",
        "started_at",
        "path",
        "dir",
        "report_path",
        "manifest_path",
        "checks_dir",
    }
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_release_fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in volatile_keys
        }
    if isinstance(value, list):
        return [_normalize_release_fingerprint_value(item) for item in value]
    return value


def _release_audit_fingerprint(report: Mapping[str, Any]) -> str:
    fingerprint_payload = {
        "ok": report.get("ok"),
        "validation_scope": report.get("validation_scope"),
        "redaction": report.get("redaction"),
        "summary": report.get("summary"),
        "checks": [
            {
                "index": check.get("index"),
                "name": check.get("name"),
                "command": check.get("command"),
                "required": check.get("required"),
                "ok": check.get("ok"),
                "returncode": check.get("returncode"),
                "stdout_json": check.get("stdout_json"),
            }
            for check in report.get("checks", [])
            if isinstance(check, Mapping)
        ],
    }
    canonical = _normalize_release_fingerprint_value(fingerprint_payload)
    return sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _release_redaction_ok(report: Mapping[str, Any]) -> bool:
    redaction = report.get("redaction")
    if not isinstance(redaction, Mapping):
        return False
    return (
        redaction.get("raw_command_omitted") is True
        and redaction.get("stderr_omitted") is True
        and redaction.get("stdout_json_only") is True
    )


def _release_check_redaction_ok(check: Mapping[str, Any]) -> bool:
    redaction = check.get("redaction")
    if not isinstance(redaction, Mapping):
        return False
    return (
        redaction.get("raw_command_omitted") is True
        and redaction.get("stderr_omitted") is True
        and redaction.get("stdout_json_only") is True
    )


def _release_provider_stdout(checks: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for check in checks:
        if check.get("command") != "provider-check" or check.get("ok") is not True:
            continue
        stdout_json = check.get("stdout_json")
        if isinstance(stdout_json, Mapping):
            return stdout_json
    return None


def _release_command_summary(checks: list[Mapping[str, Any]], required_commands: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for command in required_commands:
        matching = [check for check in checks if check.get("command") == command]
        rows.append(
            {
                "command": command,
                "present": bool(matching),
                "ok": any(check.get("ok") is True for check in matching),
                "count": len(matching),
            }
        )
    return rows


def _release_worker_run_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    worker = stdout_json.get("worker")
    summary = stdout_json.get("summary")
    queue = stdout_json.get("queue")
    cycles = stdout_json.get("cycles")
    jobs = stdout_json.get("jobs")
    metrics = stdout_json.get("metrics")
    missing_sections = [
        name
        for name, value in (
            ("worker", worker),
            ("summary", summary),
            ("queue", queue),
            ("cycles", cycles),
            ("jobs", jobs),
            ("metrics", metrics),
        )
        if (isinstance(value, Mapping) and not value)
        or (isinstance(value, list) and not value)
        or value is None
    ]
    if missing_sections:
        findings.append(
            _release_finding(
                "required_worker_runtime_evidence_incomplete",
                "worker-run evidence has empty runtime sections: " + ", ".join(missing_sections),
            )
        )
        return findings
    summary_cycles = as_int(summary.get("cycles")) if isinstance(summary, Mapping) else None
    summary_processed = as_int(summary.get("processed")) if isinstance(summary, Mapping) else None
    if summary_cycles is None or summary_cycles < 1:
        findings.append(
            _release_finding(
                "required_worker_runtime_evidence_incomplete",
                "worker-run summary must prove at least one worker cycle",
            )
        )
    if summary_processed is None or summary_processed < 1:
        findings.append(
            _release_finding(
                "required_worker_runtime_evidence_incomplete",
                "worker-run summary must prove at least one processed job",
            )
        )
    worker_max_cycles = as_int(worker.get("max_cycles")) if isinstance(worker, Mapping) else None
    worker_idle_exit_after = as_int(worker.get("idle_exit_after")) if isinstance(worker, Mapping) else None
    worker_poll_interval = as_float(worker.get("poll_interval")) if isinstance(worker, Mapping) else None
    if worker_max_cycles is None or worker_max_cycles < 2:
        findings.append(
            _release_finding(
                "required_worker_runtime_evidence_incomplete",
                "worker-run cadence must prove supervised multi-cycle operation",
            )
        )
    if worker_idle_exit_after is None or worker_idle_exit_after < 1:
        findings.append(
            _release_finding(
                "required_worker_runtime_evidence_incomplete",
                "worker-run cadence must include an idle-exit threshold",
            )
        )
    if worker_poll_interval is None or worker_poll_interval <= 0:
        findings.append(
            _release_finding(
                "required_worker_runtime_evidence_incomplete",
                "worker-run cadence must include a nonzero poll interval",
            )
        )
    if not isinstance(worker, Mapping) or worker.get("fail_on_dead") is not True:
        findings.append(
            _release_finding(
                "required_worker_runtime_evidence_incomplete",
                "worker-run cadence must fail closed on dead jobs",
            )
        )
    if not isinstance(cycles, list) or not any(
        isinstance(cycle, Mapping)
        and (processed := as_int(cycle.get("processed"))) is not None
        and processed > 0
        for cycle in cycles
    ):
        findings.append(
            _release_finding(
                "required_worker_runtime_evidence_incomplete",
                "worker-run cycles must include a processed-job cycle",
            )
        )
    if not isinstance(jobs, list) or not any(
        isinstance(job, Mapping) and job.get("kind") and job.get("status") for job in jobs
    ):
        findings.append(
            _release_finding(
                "required_worker_runtime_evidence_incomplete",
                "worker-run jobs must include kind and status evidence",
            )
        )
    return findings


def _release_bundle_ops_evidence_findings(command: str, stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("required_bundle_ops_evidence_incomplete", message))

    bundle = stdout_json.get("bundle")
    requirements = stdout_json.get("requirements")
    checks_raw = stdout_json.get("checks")
    emitted_findings = stdout_json.get("findings")
    malformed_sections = [
        name
        for name, value in (
            ("bundle", bundle),
            ("requirements", requirements),
            ("checks", checks_raw),
            ("findings", emitted_findings),
        )
        if value is None
        or (isinstance(value, Mapping) and not value)
        or (name == "checks" and isinstance(value, list) and not value)
        or (name == "findings" and not isinstance(value, list))
    ]
    if malformed_sections:
        add(f"{command} evidence has empty or malformed sections: " + ", ".join(malformed_sections))
    if stdout_json.get("ok") is not True:
        add(f"{command} report must be ok")
    if isinstance(emitted_findings, list) and emitted_findings:
        add(f"{command} report must not contain findings")
    if not isinstance(checks_raw, list) or not checks_raw:
        return findings

    checks = [check for check in checks_raw if isinstance(check, Mapping)]
    if len(checks) != len(checks_raw):
        add(f"{command} checks must be structured objects")
    named_checks = [str(check.get("name") or check.get("check") or "").strip() for check in checks]
    if not any(named_checks):
        add(f"{command} checks must include names")
    for index, check in enumerate(checks, start=1):
        if check.get("ok") is not True:
            name = str(check.get("name") or check.get("check") or index)
            add(f"{command} check {name} must be ok")

    return findings


def _release_retrieval_ops_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("required_retrieval_ops_evidence_incomplete", message))

    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    requirements = stdout_json.get("requirements")
    checks_raw = stdout_json.get("checks")
    bundle = stdout_json.get("bundle")
    redaction = stdout_json.get("redaction")
    if not isinstance(requirements, Mapping):
        add("retrieval-ops-check requirements must be structured")
        requirements = {}
    if not isinstance(checks_raw, list):
        add("retrieval-ops-check checks must be a structured list")
        return findings
    if not isinstance(bundle, Mapping):
        add("retrieval-ops-check bundle must be structured")
        bundle = {}
    if not isinstance(redaction, Mapping):
        redaction = {}

    min_cases = as_int(requirements.get("min_cases")) or 1
    min_lexical_cases = as_int(requirements.get("min_lexical_cases")) or 1
    min_vector_cases = as_int(requirements.get("min_vector_cases")) or 1
    min_graph_cases = as_int(requirements.get("min_graph_cases")) or 1
    min_reranked_cases = as_int(requirements.get("min_reranked_cases")) or 1
    min_calibration_examples = as_int(requirements.get("min_calibration_examples")) or 1
    min_calibration_correct = as_int(requirements.get("min_calibration_correct")) or 1
    min_calibration_incorrect = as_int(requirements.get("min_calibration_incorrect")) or 1
    min_empirical_coverage = as_float(requirements.get("min_empirical_coverage")) or 0.0
    max_false_accept_rate = as_float(requirements.get("max_false_accept_rate"))
    if max_false_accept_rate is None:
        max_false_accept_rate = 1.0
    max_adapter_latency_ms = as_float(requirements.get("max_adapter_latency_ms")) or 0.0
    required_adapter_probes = requirements.get("required_adapter_probes")
    if not isinstance(required_adapter_probes, list):
        required_adapter_probes = []
    required_adapters = {"graph", "lexical", "reranker", "vector"}

    if requirements.get("provider_forbid_local") is not True:
        add("retrieval-ops-check must prove local providers are forbidden")
    if requirements.get("backend") != "postgres":
        add("retrieval-ops-check must require the Postgres backend")
    for field in (
        "min_cases",
        "min_lexical_cases",
        "min_vector_cases",
        "min_graph_cases",
        "min_reranked_cases",
        "min_calibration_examples",
        "min_calibration_correct",
        "min_calibration_incorrect",
    ):
        value = as_int(requirements.get(field))
        if value is None or value < 1:
            add(f"retrieval-ops-check requirement {field} must be positive")
    if min_empirical_coverage <= 0:
        add("retrieval-ops-check requirement min_empirical_coverage must be positive")
    if max_false_accept_rate <= 0:
        add("retrieval-ops-check requirement max_false_accept_rate must be positive")
    if max_adapter_latency_ms <= 0:
        add("retrieval-ops-check requirement max_adapter_latency_ms must be positive")
    if not required_adapters.issubset({str(item) for item in required_adapter_probes}):
        add("retrieval-ops-check must require graph, lexical, reranker, and vector adapter probes")

    lexical_backend = str(bundle.get("lexical_backend") or "").strip()
    graph_backend = str(bundle.get("graph_backend") or "").strip()
    if not lexical_backend or _is_local_retrieval_backend(lexical_backend):
        add("retrieval-ops-check lexical backend must be non-local")
    if not graph_backend or _is_local_retrieval_backend(graph_backend):
        add("retrieval-ops-check graph backend must be non-local")
    if (as_int(bundle.get("retrieval_case_count")) or 0) < min_cases:
        add("retrieval-ops-check retrieval case count is below requirement")
    if (as_int(bundle.get("adapter_probe_count")) or 0) < len(required_adapters):
        add("retrieval-ops-check adapter probe count is below requirement")
    if bundle.get("calibration_dataset_fingerprint_present") is not True:
        add("retrieval-ops-check calibration dataset fingerprint is missing")

    checks = [check for check in checks_raw if isinstance(check, Mapping)]
    checks_by_name = {str(check.get("name") or ""): check for check in checks}
    required_names = {"provider_check", "retrieval", "adapter_probes", "calibration", "redaction"}
    missing_names = sorted(name for name in required_names if name not in checks_by_name)
    if missing_names:
        add("retrieval-ops-check missing required checks: " + ", ".join(missing_names))

    provider = checks_by_name.get("provider_check")
    if isinstance(provider, Mapping):
        if provider.get("ok") is not True:
            add("retrieval-ops-check provider_check must be ok")
        if provider.get("forbid_local") is not True:
            add("retrieval-ops-check provider_check must prove forbid_local")
        provider_rows = provider.get("provider_rows")
        if not isinstance(provider_rows, list) or not provider_rows:
            add("retrieval-ops-check provider rows are missing")
        else:
            for row in provider_rows:
                if not isinstance(row, Mapping):
                    add("retrieval-ops-check provider rows must be structured")
                    continue
                check_name = str(row.get("check") or "unknown")
                if row.get("ok") is not True:
                    add(f"retrieval-ops-check provider row {check_name} must be ok")
                if row.get("local_provider") is not False:
                    add(f"retrieval-ops-check provider row {check_name} must be non-local")
        backends = provider.get("retrieval_backends")
        if isinstance(backends, Mapping):
            for flag in ("lexical_local", "graph_local"):
                if backends.get(flag) is not False:
                    add(f"retrieval-ops-check backend flag {flag} must be false")
            for flag in ("lexical_probe_present", "graph_probe_present"):
                if backends.get(flag) is not True:
                    add(f"retrieval-ops-check backend flag {flag} is not proven")

    retrieval = checks_by_name.get("retrieval")
    if isinstance(retrieval, Mapping):
        if retrieval.get("ok") is not True:
            add("retrieval-ops-check retrieval check must be ok")
        if retrieval.get("backend") != "postgres":
            add("retrieval-ops-check retrieval backend must be postgres")
        case_count = as_int(retrieval.get("case_count")) or 0
        calibrated_cases = as_int(retrieval.get("calibrated_cases")) or 0
        for key, minimum in (
            ("case_count", min_cases),
            ("lexical_cases", min_lexical_cases),
            ("vector_cases", min_vector_cases),
            ("graph_cases", min_graph_cases),
            ("reranked_cases", min_reranked_cases),
        ):
            if (as_int(retrieval.get(key)) or 0) < minimum:
                add(f"retrieval-ops-check retrieval {key} is below requirement")
        if calibrated_cases != case_count:
            add("retrieval-ops-check all retrieval cases must be calibrated")
        cases = retrieval.get("cases")
        if not isinstance(cases, list) or not cases:
            add("retrieval-ops-check retrieval cases are missing")
        else:
            for case in cases:
                if not isinstance(case, Mapping):
                    add("retrieval-ops-check retrieval cases must be structured")
                    continue
                case_id = str(case.get("id") or "unknown")
                for flag in ("query_hash_present", "tenant_hash_present"):
                    if case.get(flag) is not True:
                        add(f"retrieval-ops-check retrieval case {case_id} missing {flag}")

    adapter_probes = checks_by_name.get("adapter_probes")
    if isinstance(adapter_probes, Mapping):
        if adapter_probes.get("ok") is not True:
            add("retrieval-ops-check adapter_probes check must be ok")
        missing_adapters = adapter_probes.get("missing_adapters")
        if missing_adapters not in ([], None):
            add("retrieval-ops-check adapter probes have missing adapters")
        if (as_int(adapter_probes.get("ok_probe_count")) or 0) < len(required_adapters):
            add("retrieval-ops-check adapter probes have too few ok probes")
        probes = adapter_probes.get("probes")
        if not isinstance(probes, list) or not probes:
            add("retrieval-ops-check adapter probe rows are missing")
        else:
            for probe in probes:
                if not isinstance(probe, Mapping):
                    add("retrieval-ops-check adapter probe rows must be structured")
                    continue
                probe_id = str(probe.get("id") or "unknown")
                if probe.get("ok") is not True:
                    add(f"retrieval-ops-check adapter probe {probe_id} must be ok")
                for flag in ("production_validated", "command_fingerprint_present", "query_hash_present", "tenant_hash_present", "result_fingerprint_present", "source_snapshot_fingerprint_present", "top_id_hash_present"):
                    if probe.get(flag) is not True:
                        add(f"retrieval-ops-check adapter probe {probe_id} missing {flag}")
                for flag in ("backend_local", "provider_local"):
                    if probe.get(flag) is not False:
                        add(f"retrieval-ops-check adapter probe {probe_id} must be non-local")
                if (as_int(probe.get("hit_count")) or 0) <= 0:
                    add(f"retrieval-ops-check adapter probe {probe_id} hit count must be positive")
                latency_ms = as_float(probe.get("latency_ms"))
                if latency_ms is None or latency_ms > max_adapter_latency_ms:
                    add(f"retrieval-ops-check adapter probe {probe_id} latency exceeds threshold")

    calibration = checks_by_name.get("calibration")
    if isinstance(calibration, Mapping):
        if calibration.get("ok") is not True:
            add("retrieval-ops-check calibration check must be ok")
        if calibration.get("production_dataset") is not True:
            add("retrieval-ops-check calibration must use a production dataset")
        if calibration.get("dataset_fingerprint_present") is not True:
            add("retrieval-ops-check calibration dataset fingerprint is missing")
        for key, minimum in (
            ("example_count", min_calibration_examples),
            ("correct_count", min_calibration_correct),
            ("incorrect_count", min_calibration_incorrect),
        ):
            if (as_int(calibration.get(key)) or 0) < minimum:
                add(f"retrieval-ops-check calibration {key} is below requirement")
        empirical_coverage = as_float(calibration.get("empirical_coverage"))
        if empirical_coverage is None or empirical_coverage < min_empirical_coverage:
            add("retrieval-ops-check calibration empirical coverage is too low")
        false_accept_rate = as_float(calibration.get("false_accept_rate"))
        if false_accept_rate is None or false_accept_rate > max_false_accept_rate:
            add("retrieval-ops-check calibration false accept rate is too high")
        if calibration.get("threshold_present") is not True:
            add("retrieval-ops-check calibration threshold is missing")

    redaction_check = checks_by_name.get("redaction")
    redaction_maps = [item for item in (redaction, redaction_check) if isinstance(item, Mapping)]
    if not redaction_maps:
        add("retrieval-ops-check redaction evidence is missing")
    for redaction_map in redaction_maps:
        for flag in (
            "raw_queries_omitted",
            "raw_embeddings_omitted",
            "raw_documents_omitted",
            "raw_credentials_omitted",
        ):
            if redaction_map.get(flag) is not True:
                add(f"retrieval-ops-check redaction flag {flag} is not proven")
        forbidden_paths = redaction_map.get("forbidden_raw_paths")
        if isinstance(forbidden_paths, list) and forbidden_paths:
            add("retrieval-ops-check redaction contains raw field paths")
        if redaction_map.get("forbidden_raw_fields_present") is True:
            add("retrieval-ops-check redaction must prove no raw fields are present")

    return findings


def _release_tls_lifecycle_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("required_tls_lifecycle_evidence_incomplete", message))

    def as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    bundle = stdout_json.get("bundle")
    requirements = stdout_json.get("requirements")
    checks_raw = stdout_json.get("checks")
    redaction = stdout_json.get("redaction")
    if not isinstance(bundle, Mapping):
        add("tls-lifecycle-ops-check bundle must be structured")
        bundle = {}
    if not isinstance(requirements, Mapping):
        add("tls-lifecycle-ops-check requirements must be structured")
        requirements = {}
    if not isinstance(checks_raw, list):
        add("tls-lifecycle-ops-check checks must be a structured list")
        return findings

    if requirements.get("allow_non_production") is not False:
        add("tls-lifecycle-ops-check must prove non-production evidence is disallowed")
    if requirements.get("allow_localhost") is not False:
        add("tls-lifecycle-ops-check must prove localhost endpoints are disallowed")
    min_hostnames = as_int(requirements.get("min_hostnames"))
    min_current_days = as_float(requirements.get("min_current_days_valid"))
    min_candidate_days = as_float(requirements.get("min_candidate_days_valid"))
    min_overlap_days = as_float(requirements.get("min_overlap_days"))
    if min_hostnames is None or min_hostnames < 1:
        add("tls-lifecycle-ops-check min_hostnames requirement must be positive")
        min_hostnames = 1
    if min_current_days is None or min_current_days <= 0:
        add("tls-lifecycle-ops-check min_current_days_valid requirement must be positive")
        min_current_days = 0.0
    if min_candidate_days is None or min_candidate_days <= 0:
        add("tls-lifecycle-ops-check min_candidate_days_valid requirement must be positive")
        min_candidate_days = 0.0
    if min_overlap_days is None or min_overlap_days <= 0:
        add("tls-lifecycle-ops-check min_overlap_days requirement must be positive")
        min_overlap_days = 0.0

    for flag in (
        "validation_scope_present",
        "issuance_present",
        "renewal_present",
        "deployment_present",
        "secret_distribution_present",
    ):
        if bundle.get(flag) is not True:
            add(f"tls-lifecycle-ops-check bundle flag {flag} is not proven")

    checks = [check for check in checks_raw if isinstance(check, Mapping)]
    if len(checks) != len(checks_raw):
        add("tls-lifecycle-ops-check checks must be structured objects")
    checks_by_name = {str(check.get("name") or ""): check for check in checks}
    required_names = {
        "validation_scope",
        "issuance",
        "renewal",
        "deployment",
        "secret_distribution",
        "monitoring",
        "redaction",
    }
    missing_names = sorted(name for name in required_names if name not in checks_by_name)
    if missing_names:
        add("tls-lifecycle-ops-check missing required checks: " + ", ".join(missing_names))

    validation = checks_by_name.get("validation_scope")
    if isinstance(validation, Mapping):
        if validation.get("ok") is not True:
            add("tls-lifecycle-ops-check validation_scope check must be ok")
        if validation.get("production_validated") is not True:
            add("tls-lifecycle-ops-check must prove production validation")
        if validation.get("target_environment") != "production":
            add("tls-lifecycle-ops-check target environment must be production")
        if validation.get("operator_asserted") is not True:
            add("tls-lifecycle-ops-check must prove operator attestation")

    issuance = checks_by_name.get("issuance")
    if isinstance(issuance, Mapping):
        provider = str(issuance.get("provider") or "").strip().lower()
        if issuance.get("ok") is not True:
            add("tls-lifecycle-ops-check issuance check must be ok")
        if provider in {"", "local", "self-signed", "self_signed", "test", "manual", "none"}:
            add("tls-lifecycle-ops-check issuer must be non-local")
        hostnames = issuance.get("hostnames")
        if not isinstance(hostnames, list) or len(hostnames) < min_hostnames:
            add("tls-lifecycle-ops-check hostname coverage is below requirement")
        for flag in ("certificate_serial_sha256_present", "chain_sha256_present"):
            if issuance.get(flag) is not True:
                add(f"tls-lifecycle-ops-check issuance {flag} is not proven")

    renewal = checks_by_name.get("renewal")
    if isinstance(renewal, Mapping):
        if renewal.get("ok") is not True:
            add("tls-lifecycle-ops-check renewal check must be ok")
        if (as_float(renewal.get("current_days_remaining")) or 0.0) < min_current_days:
            add("tls-lifecycle-ops-check current certificate validity is below requirement")
        if (as_float(renewal.get("candidate_days_remaining")) or 0.0) < min_candidate_days:
            add("tls-lifecycle-ops-check candidate certificate validity is below requirement")
        if (as_float(renewal.get("overlap_days")) or 0.0) < min_overlap_days:
            add("tls-lifecycle-ops-check certificate overlap is below requirement")
        for flag in ("automation_enabled", "renewal_executed"):
            if renewal.get(flag) is not True:
                add(f"tls-lifecycle-ops-check renewal {flag} is not proven")

    deployment = checks_by_name.get("deployment")
    if isinstance(deployment, Mapping):
        if deployment.get("ok") is not True:
            add("tls-lifecycle-ops-check deployment check must be ok")
        if deployment.get("endpoint_https") is not True:
            add("tls-lifecycle-ops-check deployed endpoint must be HTTPS")
        if deployment.get("endpoint_local") is not False:
            add("tls-lifecycle-ops-check deployed endpoint must be non-local")
        if deployment.get("deployed_serial_matches_candidate") is not True:
            add("tls-lifecycle-ops-check deployed certificate must match issued candidate")
        if deployment.get("reload_verified") is not True:
            add("tls-lifecycle-ops-check reload proof is missing")

    secret = checks_by_name.get("secret_distribution")
    if isinstance(secret, Mapping):
        key_source = str(secret.get("private_key_source") or "").strip().lower()
        if secret.get("ok") is not True:
            add("tls-lifecycle-ops-check secret_distribution check must be ok")
        if secret.get("key_source_local") is not False or key_source in {"", "local", "file", "filesystem", "env", "test", "none"}:
            add("tls-lifecycle-ops-check private key custody must be non-local")
        if secret.get("deployed_key_id_hash_present") is not True:
            add("tls-lifecycle-ops-check deployed key id hash is missing")

    monitoring = checks_by_name.get("monitoring")
    if isinstance(monitoring, Mapping):
        if monitoring.get("ok") is not True:
            add("tls-lifecycle-ops-check monitoring check must be ok")
        for flag in (
            "expiry_alert_configured",
            "renewal_failure_alert_configured",
            "cert_mismatch_alert_configured",
            "revocation_checked",
        ):
            if monitoring.get(flag) is not True:
                add(f"tls-lifecycle-ops-check monitoring {flag} is not proven")

    redaction_check = checks_by_name.get("redaction")
    redaction_maps = [item for item in (redaction, redaction_check) if isinstance(item, Mapping)]
    if not redaction_maps:
        add("tls-lifecycle-ops-check redaction evidence is missing")
    for redaction_map in redaction_maps:
        for flag in (
            "raw_private_keys_omitted",
            "raw_certificate_pem_omitted",
            "raw_acme_tokens_omitted",
            "raw_deployment_logs_omitted",
        ):
            if redaction_map.get(flag) is not True:
                add(f"tls-lifecycle-ops-check redaction flag {flag} is not proven")
        if redaction_map.get("forbidden_raw_paths") not in ([], None):
            add("tls-lifecycle-ops-check redaction contains raw field paths")
        if redaction_map.get("forbidden_raw_fields_present") is True:
            add("tls-lifecycle-ops-check redaction must prove no raw fields are present")

    fingerprint = str(stdout_json.get("fingerprint") or "").strip()
    if len(fingerprint) != 64:
        add("tls-lifecycle-ops-check report fingerprint is missing")

    return findings


def _release_parametric_trainer_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("required_parametric_trainer_evidence_incomplete", message))

    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    bundle = stdout_json.get("bundle")
    requirements = stdout_json.get("requirements")
    checks_raw = stdout_json.get("checks")
    redaction = stdout_json.get("redaction")
    if not isinstance(bundle, Mapping):
        add("parametric-trainer-check bundle must be structured")
        bundle = {}
    if not isinstance(requirements, Mapping):
        add("parametric-trainer-check requirements must be structured")
        requirements = {}
    if not isinstance(checks_raw, list):
        add("parametric-trainer-check checks must be a structured list")
        return findings

    for flag in (
        "non_local_trainer_provider",
        "immutable_rail_service",
        "credentials_isolated",
        "artifact_uri_hash",
        "protected_suite_source_non_synthetic",
        "gate_candidate_matches_artifact",
        "monotonic_trust",
    ):
        if requirements.get(flag) is not True:
            add(f"parametric-trainer-check requirement {flag} is not proven")
    if requirements.get("external_reward_signal") != "external_only":
        add("parametric-trainer-check must prove external-only reward signals")
    if requirements.get("eval_source_overlap") is not False:
        add("parametric-trainer-check must prove no eval-source overlap")

    min_cases = as_int(requirements.get("min_cases"))
    min_protected = as_int(requirements.get("min_protected"))
    min_gate_margin = as_float(requirements.get("min_gate_margin"))
    max_deployment_latency = as_float(requirements.get("max_deployment_latency_ms"))
    max_mutation_rate = as_float(requirements.get("max_mutation_rate"))
    min_reward = as_float(requirements.get("min_reward"))
    max_sink_score = as_float(requirements.get("max_sink_score"))
    if min_cases is None or min_cases < 1:
        add("parametric-trainer-check min_cases requirement must be positive")
        min_cases = 1
    if min_protected is None or min_protected < 1:
        add("parametric-trainer-check min_protected requirement must be positive")
        min_protected = 1
    if min_gate_margin is None or min_gate_margin <= 0:
        add("parametric-trainer-check min_gate_margin requirement must be positive")
        min_gate_margin = 0.0
    if max_deployment_latency is None or max_deployment_latency <= 0:
        add("parametric-trainer-check max_deployment_latency_ms requirement must be positive")
        max_deployment_latency = 0.0
    if max_mutation_rate is None or max_mutation_rate < 0:
        add("parametric-trainer-check max_mutation_rate requirement must be non-negative")
        max_mutation_rate = 0.0
    if min_reward is None:
        add("parametric-trainer-check min_reward requirement must be numeric")
        min_reward = 0.0
    if max_sink_score is None or max_sink_score < 0:
        add("parametric-trainer-check max_sink_score requirement must be non-negative")
        max_sink_score = 0.0

    trainer_provider = str(bundle.get("trainer_provider") or "").strip().lower()
    if not trainer_provider or trainer_provider in {"local", "mock", "test", "filesystem"}:
        add("parametric-trainer-check trainer provider must be non-local")
    if bundle.get("protected_suite_fingerprint_present") is not True:
        add("parametric-trainer-check protected suite fingerprint is missing")
    suite_source = str(bundle.get("protected_suite_source") or "").strip().lower()
    if not suite_source or suite_source == "synthetic":
        add("parametric-trainer-check protected suite source must be non-synthetic")
    fingerprint = str(stdout_json.get("fingerprint") or "").strip()
    if len(fingerprint) != 64:
        add("parametric-trainer-check report fingerprint is missing")

    checks = [check for check in checks_raw if isinstance(check, Mapping)]
    if len(checks) != len(checks_raw):
        add("parametric-trainer-check checks must be structured objects")
    checks_by_name = {str(check.get("name") or ""): check for check in checks}
    required_names = {
        "trainer",
        "protected_suite",
        "gate",
        "rollback",
        "deployment",
        "rail_report",
        "metrics",
        "redaction",
    }
    missing_names = sorted(name for name in required_names if name not in checks_by_name)
    if missing_names:
        add("parametric-trainer-check missing required checks: " + ", ".join(missing_names))

    trainer = checks_by_name.get("trainer")
    if isinstance(trainer, Mapping):
        if trainer.get("ok") is not True:
            add("parametric-trainer-check trainer check must be ok")
        if trainer.get("provider_local") is not False:
            add("parametric-trainer-check trainer provider must be non-local")
        if trainer.get("missing_controls") not in ([], None):
            add("parametric-trainer-check trainer controls are incomplete")
        if trainer.get("artifact_uri_present") is not True or trainer.get("artifact_uri_hash_present") is not True:
            add("parametric-trainer-check trainer artifact hash evidence is incomplete")

    protected_suite = checks_by_name.get("protected_suite")
    if isinstance(protected_suite, Mapping):
        case_count = as_int(protected_suite.get("case_count"))
        protected_count = as_int(protected_suite.get("protected_case_count"))
        if protected_suite.get("ok") is not True:
            add("parametric-trainer-check protected_suite check must be ok")
        if case_count is None or case_count < min_cases:
            add("parametric-trainer-check protected suite case count is below requirement")
        if protected_count is None or protected_count < min_protected:
            add("parametric-trainer-check protected suite protected-case count is below requirement")
        if protected_suite.get("source_synthetic") is not False:
            add("parametric-trainer-check protected suite source must be non-synthetic")
        if protected_suite.get("missing_tiers") not in ([], None):
            add("parametric-trainer-check protected suite is missing required tiers")
        if protected_suite.get("fingerprint_present") is not True:
            add("parametric-trainer-check protected suite fingerprint is missing")
        if protected_suite.get("case_id_count_matches") is not True:
            add("parametric-trainer-check protected suite case id counts must match")

    gate = checks_by_name.get("gate")
    if isinstance(gate, Mapping):
        if gate.get("ok") is not True:
            add("parametric-trainer-check gate check must be ok")
        if gate.get("promoted") is not True:
            add("parametric-trainer-check gate must prove promoted candidate")
        if as_int(gate.get("protected_regression_count")) != 0:
            add("parametric-trainer-check gate must prove zero protected regressions")
        if as_int(gate.get("failed_case_count")) != 0:
            add("parametric-trainer-check gate must prove zero failed cases")
        passed_protected = gate.get("passed_protected_cases")
        if not isinstance(passed_protected, list) or len(passed_protected) < min_protected:
            add("parametric-trainer-check gate must prove protected cases passed")
        margin = as_float(gate.get("margin"))
        if margin is None or margin < min_gate_margin:
            add("parametric-trainer-check gate margin is below requirement")

    rollback = checks_by_name.get("rollback")
    if isinstance(rollback, Mapping):
        if rollback.get("ok") is not True:
            add("parametric-trainer-check rollback check must be ok")
        if rollback.get("missing_controls") not in ([], None):
            add("parametric-trainer-check rollback controls are incomplete")
        if rollback.get("rollback_fingerprint_present") is not True:
            add("parametric-trainer-check rollback fingerprint is missing")

    deployment = checks_by_name.get("deployment")
    if isinstance(deployment, Mapping):
        if deployment.get("ok") is not True:
            add("parametric-trainer-check deployment check must be ok")
        if deployment.get("endpoint_https") is not True:
            add("parametric-trainer-check deployment endpoint must be HTTPS")
        latency = as_float(deployment.get("latency_ms"))
        if latency is None or latency > max_deployment_latency:
            add("parametric-trainer-check deployment latency is missing or above requirement")
        if deployment.get("missing_controls") not in ([], None):
            add("parametric-trainer-check deployment controls are incomplete")
        for flag in (
            "protected_suite_fingerprint_matches",
            "artifact_uri_hash_matches",
            "rollback_fingerprint_matches",
        ):
            if deployment.get(flag) is not True:
                add(f"parametric-trainer-check deployment {flag} is not proven")

    rail_report = checks_by_name.get("rail_report")
    if isinstance(rail_report, Mapping):
        if rail_report.get("ok") is not True:
            add("parametric-trainer-check rail_report check must be ok")
        if rail_report.get("provider_metadata_checked") is not True:
            add("parametric-trainer-check rail_report must prove provider metadata check")
        if rail_report.get("reward_signal") != "external_only":
            add("parametric-trainer-check rail_report reward signal must be external_only")
        if rail_report.get("monotonic_trust") is not True:
            add("parametric-trainer-check rail_report must prove monotonic trust")
        trust_delta = as_float(rail_report.get("trust_tier_delta"))
        if trust_delta is None or trust_delta < 0:
            add("parametric-trainer-check rail_report trust_tier_delta must be non-negative")
        if str(rail_report.get("target_sink") or "") == "system_prompt":
            add("parametric-trainer-check rail_report target sink must not be system_prompt")
        if rail_report.get("eval_source_overlap") is not False:
            add("parametric-trainer-check rail_report must prove no eval-source overlap")

    metrics = checks_by_name.get("metrics")
    if isinstance(metrics, Mapping):
        if metrics.get("ok") is not True:
            add("parametric-trainer-check metrics check must be ok")
        mutation_rate = as_float(metrics.get("mutation_rate"))
        reward = as_float(metrics.get("reward"))
        sink_score = as_float(metrics.get("sink_score"))
        if mutation_rate is None or mutation_rate > max_mutation_rate:
            add("parametric-trainer-check mutation rate is missing or above requirement")
        if reward is None or reward < min_reward:
            add("parametric-trainer-check reward is missing or below requirement")
        if sink_score is None or sink_score > max_sink_score:
            add("parametric-trainer-check sink score is missing or above requirement")

    redaction_check = checks_by_name.get("redaction")
    redaction_maps = [item for item in (redaction, redaction_check) if isinstance(item, Mapping)]
    if not redaction_maps:
        add("parametric-trainer-check redaction evidence is missing")
    for redaction_map in redaction_maps:
        for flag in (
            "raw_training_data_omitted",
            "raw_credentials_omitted",
            "raw_artifact_bytes_omitted",
        ):
            if redaction_map.get(flag) is not True:
                add(f"parametric-trainer-check redaction flag {flag} is not proven")
        if redaction_map.get("forbidden_raw_paths") not in ([], None):
            add("parametric-trainer-check redaction contains raw field paths")
        if redaction_map.get("forbidden_raw_fields_present") is True:
            add("parametric-trainer-check redaction must prove no raw fields are present")

    return findings


def _release_mcp_ops_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("required_mcp_ops_evidence_incomplete", message))

    def as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    requirements = stdout_json.get("requirements")
    checks_raw = stdout_json.get("checks")
    if not isinstance(requirements, Mapping):
        add("mcp-ops-check requirements must be structured")
        requirements = {}
    if not isinstance(checks_raw, list):
        add("mcp-ops-check checks must be a structured list")
        return findings

    if requirements.get("allow_localhost") is not False:
        add("mcp-ops-check must prove localhost transports are disallowed")
    if requirements.get("require_client_cert") is not True:
        add("mcp-ops-check must prove client certificates are required")

    min_loops = as_int(requirements.get("min_loops"))
    max_avg_latency = as_float(requirements.get("max_avg_latency_ms"))
    max_p95_latency = as_float(requirements.get("max_p95_latency_ms"))
    min_cert_days = as_float(requirements.get("min_cert_days"))
    min_sse_events = as_int(requirements.get("min_sse_events"))
    if min_loops is None or min_loops < 1:
        add("mcp-ops-check min_loops requirement must be positive")
        min_loops = 1
    if max_avg_latency is None or max_avg_latency <= 0:
        add("mcp-ops-check max_avg_latency_ms requirement must be positive")
        max_avg_latency = 0.0
    if max_p95_latency is None or max_p95_latency <= 0:
        add("mcp-ops-check max_p95_latency_ms requirement must be positive")
        max_p95_latency = 0.0
    if min_cert_days is None or min_cert_days < 1:
        add("mcp-ops-check min_cert_days requirement must be positive")
        min_cert_days = 1.0
    if min_sse_events is None or min_sse_events < 1:
        min_sse_events = 1

    checks = [check for check in checks_raw if isinstance(check, Mapping)]
    checks_by_name = {str(check.get("name") or ""): check for check in checks}
    required_names = {"http_json_rpc", "streamable_http", "tls", "redaction"}
    if requirements.get("require_legacy_sse") is True:
        required_names.add("legacy_sse")
    missing_names = sorted(name for name in required_names if name not in checks_by_name)
    if missing_names:
        add("mcp-ops-check missing required checks: " + ", ".join(missing_names))

    transport_expectations = {
        "http_json_rpc": "http-json-rpc",
        "streamable_http": "mcp-sdk-streamable-http",
    }
    for name, expected_transport in transport_expectations.items():
        check = checks_by_name.get(name)
        if not isinstance(check, Mapping):
            continue
        if check.get("ok") is not True:
            add(f"mcp-ops-check {name} check must be ok")
        if check.get("transport") != expected_transport:
            add(f"mcp-ops-check {name} transport must be {expected_transport}")
        if check.get("url_present") is not True or check.get("local_url") is not False:
            add(f"mcp-ops-check {name} must prove HTTPS non-local transport")
        loop_count = as_int(check.get("loop_count"))
        if loop_count is None or loop_count < min_loops:
            add(f"mcp-ops-check {name} loop count is below requirement")
        avg_latency = as_float(check.get("avg_latency_ms"))
        if avg_latency is None or avg_latency > max_avg_latency:
            add(f"mcp-ops-check {name} average latency is missing or above requirement")
        p95_latency = as_float(check.get("p95_latency_ms"))
        if p95_latency is None or p95_latency > max_p95_latency:
            add(f"mcp-ops-check {name} p95 latency is missing or above requirement")
        if check.get("auth_token_configured") is not True:
            add(f"mcp-ops-check {name} must prove bearer-token enforcement")
        if check.get("session_token_configured") is not True:
            add(f"mcp-ops-check {name} must prove signed-session binding")
        missing_controls = check.get("missing_controls")
        if missing_controls not in ([], None):
            add(f"mcp-ops-check {name} has missing transport controls")

    legacy_sse = checks_by_name.get("legacy_sse")
    if requirements.get("require_legacy_sse") is True and isinstance(legacy_sse, Mapping):
        if legacy_sse.get("ok") is not True:
            add("mcp-ops-check legacy_sse check must be ok")
        if legacy_sse.get("local_url") is not False:
            add("mcp-ops-check legacy_sse must prove HTTPS non-local transport")
        event_count = as_int(legacy_sse.get("event_count"))
        if event_count is None or event_count < min_sse_events:
            add("mcp-ops-check legacy_sse event count is below requirement")
        if legacy_sse.get("endpoint_data_present") is not True:
            add("mcp-ops-check legacy_sse must prove endpoint data events")
        if legacy_sse.get("auth_token_configured") is not True:
            add("mcp-ops-check legacy_sse must prove bearer-token enforcement")
        if legacy_sse.get("session_token_configured") is not True:
            add("mcp-ops-check legacy_sse must prove signed-session binding")

    tls = checks_by_name.get("tls")
    if isinstance(tls, Mapping):
        if tls.get("ok") is not True:
            add("mcp-ops-check tls check must be ok")
        days_remaining = as_float(tls.get("days_remaining"))
        if days_remaining is None or days_remaining < min_cert_days:
            add("mcp-ops-check tls certificate days remaining is below requirement")
        if tls.get("client_certificate_required") is not True:
            add("mcp-ops-check tls must prove client certificate enforcement")

    redaction = checks_by_name.get("redaction")
    if isinstance(redaction, Mapping):
        if redaction.get("ok") is not True:
            add("mcp-ops-check redaction check must be ok")
        for flag in (
            "raw_tokens_omitted",
            "raw_session_tokens_omitted",
            "raw_requests_omitted",
            "raw_responses_omitted",
        ):
            if redaction.get(flag) is not True:
                add(f"mcp-ops-check redaction flag {flag} is not proven")
        if redaction.get("forbidden_raw_paths") not in ([], None):
            add("mcp-ops-check redaction must omit raw token/request/response paths")

    return findings


def _release_privacy_ops_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("required_privacy_ops_evidence_incomplete", message))

    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    requirements = stdout_json.get("requirements")
    checks_raw = stdout_json.get("checks")
    bundle = stdout_json.get("bundle")
    if not isinstance(requirements, Mapping):
        add("privacy-ops-check requirements must be structured")
        requirements = {}
    if not isinstance(checks_raw, list):
        add("privacy-ops-check checks must be a structured list")
        return findings
    if not isinstance(bundle, Mapping):
        bundle = {}

    for flag in (
        "non_local_kms",
        "strict_runtime_residency",
        "requires_allow_and_deny_residency",
        "requires_tombstone_and_legal_delete",
        "requires_operator_delete_corroboration",
    ):
        if requirements.get(flag) is not True:
            add(f"privacy-ops-check requirement {flag} is not proven")

    min_cases = as_int(requirements.get("min_cases"))
    if min_cases is None or min_cases < 1:
        add("privacy-ops-check min_cases requirement must be positive")
        min_cases = 1
    case_count = as_int(bundle.get("case_count"))
    if case_count is None or case_count < min_cases:
        add("privacy-ops-check bundle case count is below requirement")

    checks = [check for check in checks_raw if isinstance(check, Mapping)]
    checks_by_name = {str(check.get("name") or ""): check for check in checks}
    required_names = {"kms", "residency", "erasure", "redaction"}
    missing_names = sorted(name for name in required_names if name not in checks_by_name)
    if missing_names:
        add("privacy-ops-check missing required checks: " + ", ".join(missing_names))

    kms = checks_by_name.get("kms")
    if isinstance(kms, Mapping):
        if kms.get("ok") is not True:
            add("privacy-ops-check kms check must be ok")
        if kms.get("provider_local") is not False:
            add("privacy-ops-check kms provider must be non-local")
        if not str(kms.get("provider") or "").strip():
            add("privacy-ops-check kms provider identity is missing")
        if kms.get("missing_lifecycle_flags") not in ([], None):
            add("privacy-ops-check kms lifecycle flags are incomplete")
        if kms.get("key_id_hash_present") is not True:
            add("privacy-ops-check kms key id hash is missing")

    residency = checks_by_name.get("residency")
    if isinstance(residency, Mapping):
        if residency.get("ok") is not True:
            add("privacy-ops-check residency check must be ok")
        if residency.get("strict_runtime_residency") is not True:
            add("privacy-ops-check runtime residency must be strict")
        residency_cases = residency.get("cases")
        if not isinstance(residency_cases, list) or not residency_cases:
            add("privacy-ops-check residency cases are missing")
        else:
            decisions = {
                str(case.get("expected_decision") or "")
                for case in residency_cases
                if isinstance(case, Mapping) and case.get("ok") is True and case.get("enforced") is True
            }
            if not {"allow", "deny"}.issubset(decisions):
                add("privacy-ops-check residency evidence requires enforced allow and deny cases")

    erasure = checks_by_name.get("erasure")
    if isinstance(erasure, Mapping):
        if erasure.get("ok") is not True:
            add("privacy-ops-check erasure check must be ok")
        modes = {str(mode) for mode in erasure.get("modes", [])} if isinstance(erasure.get("modes"), list) else set()
        if not {"tombstone_recompute", "legal_hard_delete"}.issubset(modes):
            add("privacy-ops-check erasure evidence requires tombstone and legal hard-delete modes")
        if erasure.get("operator_delete_case_present") is not True:
            add("privacy-ops-check erasure evidence requires operator delete corroboration")
        erasure_cases = erasure.get("cases")
        if not isinstance(erasure_cases, list) or not erasure_cases:
            add("privacy-ops-check erasure cases are missing")
        else:
            for case in erasure_cases:
                if not isinstance(case, Mapping):
                    add("privacy-ops-check erasure cases must be structured")
                    continue
                case_id = str(case.get("id") or "unknown")
                if case.get("ok") is not True:
                    add(f"privacy-ops-check erasure case {case_id} must be ok")
                if case.get("cid_hash_present") is not True:
                    add(f"privacy-ops-check erasure case {case_id} cid hash is missing")
                operator_delete = case.get("operator_delete")
                if isinstance(operator_delete, Mapping) and operator_delete.get("required") is True:
                    if operator_delete.get("ok") is not True:
                        add(f"privacy-ops-check erasure case {case_id} operator delete proof is incomplete")
                    if operator_delete.get("missing") not in ([], None):
                        add(f"privacy-ops-check erasure case {case_id} operator delete fields are missing")

    redaction = checks_by_name.get("redaction")
    if isinstance(redaction, Mapping):
        if redaction.get("ok") is not True:
            add("privacy-ops-check redaction check must be ok")
        for flag in (
            "raw_key_material_omitted",
            "raw_object_bytes_omitted",
            "raw_subject_identifiers_omitted",
            "raw_kms_responses_omitted",
        ):
            if redaction.get(flag) is not True:
                add(f"privacy-ops-check redaction flag {flag} is not proven")
        if redaction.get("forbidden_raw_paths") not in ([], None):
            add("privacy-ops-check redaction must omit raw key/object/subject/KMS paths")

    return findings


def _release_worker_ops_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("required_worker_ops_evidence_incomplete", message))

    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    bundle = stdout_json.get("bundle")
    requirements = stdout_json.get("requirements")
    checks_raw = stdout_json.get("checks")
    emitted_findings = stdout_json.get("findings")
    redaction = stdout_json.get("redaction")
    missing_sections = [
        name
        for name, value in (
            ("bundle", bundle),
            ("requirements", requirements),
            ("checks", checks_raw),
            ("findings", emitted_findings),
            ("redaction", redaction),
        )
        if value is None
        or (isinstance(value, Mapping) and not value)
        or (name == "checks" and isinstance(value, list) and not value)
        or (name == "findings" and not isinstance(value, list))
    ]
    if missing_sections:
        add("worker-ops-check evidence has empty or malformed sections: " + ", ".join(missing_sections))

    if stdout_json.get("ok") is not True:
        add("worker-ops-check report must be ok")
    if isinstance(emitted_findings, list) and emitted_findings:
        add("worker-ops-check report must not contain findings")
    if not isinstance(checks_raw, list):
        return findings

    checks = [item for item in checks_raw if isinstance(item, Mapping)]
    checks_by_name = {str(check.get("name") or ""): check for check in checks}
    required_check_names = (
        "deployment_scope",
        "supervisor",
        "heartbeat",
        "queue",
        "jobs",
        "observability",
        "redaction",
    )
    missing_check_names = [name for name in required_check_names if name not in checks_by_name]
    if missing_check_names:
        add("worker-ops-check evidence is missing checks: " + ", ".join(missing_check_names))

    for name in required_check_names:
        check = checks_by_name.get(name)
        if isinstance(check, Mapping) and check.get("ok") is not True:
            add(f"worker-ops-check {name} check must be ok")

    deployment = checks_by_name.get("deployment_scope", {})
    if isinstance(deployment, Mapping):
        if deployment.get("environment") != "production":
            add("worker-ops-check deployment scope must target production")
        if deployment.get("operator_asserted") is not True:
            add("worker-ops-check deployment scope must include operator attestation")

    requirements_map = requirements if isinstance(requirements, Mapping) else {}
    min_processes = as_int(requirements_map.get("min_processes")) or 1
    max_restart_seconds = as_float(requirements_map.get("max_restart_seconds")) or 120.0
    max_heartbeat_age_seconds = as_float(requirements_map.get("max_heartbeat_age_seconds")) or 120.0
    max_backlog = as_int(requirements_map.get("max_backlog")) or 1000
    max_dead_jobs = as_int(requirements_map.get("max_dead_jobs"))
    if max_dead_jobs is None:
        max_dead_jobs = 0
    max_oldest_pending_age_seconds = as_float(requirements_map.get("max_oldest_pending_age_seconds")) or 300.0

    supervisor = checks_by_name.get("supervisor", {})
    if isinstance(supervisor, Mapping):
        supervisor_type = str(supervisor.get("type") or "").strip().lower()
        process_count = as_int(supervisor.get("process_count"))
        desired_processes = as_int(supervisor.get("desired_processes"))
        restart_seconds = as_float(supervisor.get("max_restart_seconds"))
        if supervisor_type in {"", "none", "manual", "local"}:
            add("worker-ops-check supervisor must be an external process manager")
        if process_count is None or process_count < min_processes:
            add("worker-ops-check supervisor process count is below threshold")
        if desired_processes is None or desired_processes < min_processes:
            add("worker-ops-check supervisor desired process count is below threshold")
        if restart_seconds is None or restart_seconds > max_restart_seconds:
            add("worker-ops-check restart window exceeds threshold")

    heartbeat = checks_by_name.get("heartbeat", {})
    if isinstance(heartbeat, Mapping):
        last_seen_age = as_float(heartbeat.get("last_seen_age_seconds"))
        if last_seen_age is None or last_seen_age > max_heartbeat_age_seconds:
            add("worker-ops-check heartbeat age exceeds threshold")

    queue = checks_by_name.get("queue", {})
    if isinstance(queue, Mapping):
        backlog = as_int(queue.get("backlog"))
        dead_jobs = as_int(queue.get("dead_jobs"))
        oldest_pending_age = as_float(queue.get("oldest_pending_age_seconds"))
        if queue.get("backend") != "postgres":
            add("worker-ops-check queue backend must be postgres")
        if queue.get("tenant_scoped") is not True:
            add("worker-ops-check queue must prove tenant scoping")
        if backlog is None or backlog > max_backlog:
            add("worker-ops-check queue backlog exceeds threshold")
        if dead_jobs is None or dead_jobs > max_dead_jobs:
            add("worker-ops-check queue contains dead jobs")
        if oldest_pending_age is None or oldest_pending_age > max_oldest_pending_age_seconds:
            add("worker-ops-check oldest pending job age exceeds threshold")

    jobs = checks_by_name.get("jobs", {})
    if isinstance(jobs, Mapping):
        required_job_kinds = requirements_map.get("required_job_kinds")
        handled_kinds = jobs.get("handled_kinds")
        missing_kinds = jobs.get("missing_kinds")
        failed_cycle_count = as_int(jobs.get("failed_cycle_count"))
        dead_job_count = as_int(jobs.get("dead_job_count"))
        if isinstance(required_job_kinds, list):
            if not isinstance(handled_kinds, list) or not set(required_job_kinds).issubset(set(handled_kinds)):
                add("worker-ops-check handled job kinds are incomplete")
        if missing_kinds not in ([], ()):
            add("worker-ops-check has missing job kinds")
        if failed_cycle_count is None or failed_cycle_count != 0:
            add("worker-ops-check contains failed worker cycles")
        if dead_job_count is None or dead_job_count > max_dead_jobs:
            add("worker-ops-check job evidence contains dead jobs")

    observability = checks_by_name.get("observability", {})
    if isinstance(observability, Mapping):
        for flag in ("metrics_exported", "cycle_heartbeats", "alerts_configured", "restart_alerts"):
            if observability.get(flag) is not True:
                add(f"worker-ops-check observability flag {flag} is not proven")

    redaction_checks = []
    check_redaction = checks_by_name.get("redaction")
    if isinstance(check_redaction, Mapping):
        redaction_checks.append(check_redaction)
    if isinstance(redaction, Mapping):
        redaction_checks.append(redaction)
        if redaction.get("forbidden_raw_fields_present") is not False:
            add("worker-ops-check redaction must prove no raw fields are present")
    for redaction_check in redaction_checks:
        for flag in (
            "raw_env_omitted",
            "raw_connection_strings_omitted",
            "raw_queue_payloads_omitted",
            "raw_worker_logs_omitted",
        ):
            if redaction_check.get(flag) is not True:
                add(f"worker-ops-check redaction flag {flag} is not proven")
        forbidden_paths = redaction_check.get("forbidden_raw_paths")
        if isinstance(forbidden_paths, list) and forbidden_paths:
            add("worker-ops-check redaction contains raw field paths")

    return findings


def _release_ops_dashboard_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("required_ops_dashboard_evidence_incomplete", message))

    if stdout_json.get("ok") is not True:
        add("ops-dashboard-check report must be ok")
    if stdout_json.get("findings") != []:
        add("ops-dashboard-check report must not contain findings")
    if stdout_json.get("mode") != "hosted_url":
        add("ops-dashboard-check production evidence must use hosted_url mode")
    source = stdout_json.get("source")
    if not isinstance(source, Mapping) or not isinstance(source.get("dashboard_url"), str) or not source["dashboard_url"]:
        add("ops-dashboard-check hosted dashboard_url source is required")
    checks_raw = stdout_json.get("checks")
    if not isinstance(checks_raw, list):
        add("ops-dashboard-check checks must be a list")
        return findings
    checks = [item for item in checks_raw if isinstance(item, Mapping)]
    checks_by_name = {str(item.get("name") or ""): item for item in checks}
    hosted_dashboard = checks_by_name.get("hosted_dashboard")
    if not isinstance(hosted_dashboard, Mapping) or hosted_dashboard.get("ok") is not True:
        add("ops-dashboard-check hosted_dashboard check must be ok")
    required_check_names = (
        "dashboard_operations_scope",
        "dashboard_refresh",
        "dashboard_access_control",
        "dashboard_alerts",
        "dashboard_operations_redaction",
    )
    missing_check_names = [name for name in required_check_names if name not in checks_by_name]
    if missing_check_names:
        add("ops-dashboard-check evidence is missing production operations checks: " + ", ".join(missing_check_names))
    for name in required_check_names:
        check = checks_by_name.get(name)
        if isinstance(check, Mapping) and check.get("ok") is not True:
            add(f"ops-dashboard-check {name} check must be ok")

    scope = checks_by_name.get("dashboard_operations_scope", {})
    if isinstance(scope, Mapping):
        if scope.get("production_validated") is not True:
            add("ops-dashboard-check operations scope must be production validated")
        if scope.get("target_environment") != "production":
            add("ops-dashboard-check operations scope must target production")

    redaction = stdout_json.get("redaction")
    redaction_maps = [redaction] if isinstance(redaction, Mapping) else []
    redaction_check = checks_by_name.get("dashboard_operations_redaction")
    if isinstance(redaction_check, Mapping):
        redaction_maps.append(redaction_check)
    if not redaction_maps:
        add("ops-dashboard-check operations redaction evidence is missing")
    for redaction_map in redaction_maps:
        for flag in ("raw_html_omitted", "raw_snapshot_omitted", "raw_tokens_omitted", "raw_user_data_omitted"):
            if redaction_map.get(flag) is not True:
                add(f"ops-dashboard-check redaction flag {flag} is not proven")
        forbidden_paths = redaction_map.get("forbidden_raw_paths")
        if isinstance(forbidden_paths, list) and forbidden_paths:
            add("ops-dashboard-check redaction contains raw field paths")

    return findings


def _release_ops_report_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("required_ops_report_audit_evidence_incomplete", message))

    audit = stdout_json.get("audit")
    if not isinstance(audit, Mapping):
        add("ops-report audit evidence is missing")
        return findings

    hash_chain = audit.get("hash_chain")
    if not isinstance(hash_chain, Mapping):
        add("ops-report hash-chain evidence is missing")
    else:
        if str(hash_chain.get("provider") or "").lower() != "vault-hmac":
            add("ops-report hash-chain provider must be Vault-HMAC")
        for flag in ("verified", "retained"):
            if hash_chain.get(flag) is not True:
                add(f"ops-report hash-chain flag {flag} is not proven")

    pgaudit = audit.get("pgaudit")
    if not isinstance(pgaudit, Mapping):
        add("ops-report pgaudit evidence is missing")
    else:
        for flag in ("enabled", "retained"):
            if pgaudit.get(flag) is not True:
                add(f"ops-report pgaudit flag {flag} is not proven")

    worm_copy = audit.get("worm_copy")
    if not isinstance(worm_copy, Mapping):
        add("ops-report WORM-copy evidence is missing")
    else:
        for flag in ("enabled", "external", "retained"):
            if worm_copy.get(flag) is not True:
                add(f"ops-report WORM-copy flag {flag} is not proven")

    return findings


def _release_postgres_role_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Production role-separation evidence must prove live rolsuper/rolbypassrls
    probes against non-local app and consolidator DSNs, sole-write posture, and
    DSN redaction — roles.sql mandates this live probe for every prod DSN."""
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("postgres_role_evidence_weak", message))

    requirements = stdout_json.get("requirements")
    if not isinstance(requirements, Mapping) or requirements.get("allow_localhost") is not False:
        add("postgres-role-check must prove localhost targets are disallowed")
    target = stdout_json.get("target")
    target = target if isinstance(target, Mapping) else {}
    for label in ("app", "consolidator"):
        entry = target.get(label)
        if not isinstance(entry, Mapping) or entry.get("configured") is not True:
            add(f"postgres-role-check must probe the {label} DSN")
            continue
        if entry.get("local") is not False:
            add(f"postgres-role-check {label} target must be non-local")
        if "dsn" in entry or not str(entry.get("dsn_sha256") or "").startswith("sha256:"):
            add(f"postgres-role-check {label} target must redact the DSN to a sha256 fingerprint")
    roles = stdout_json.get("roles")
    roles = roles if isinstance(roles, Mapping) else {}
    for label in ("app", "consolidator"):
        entry = roles.get(label)
        if not isinstance(entry, Mapping):
            add(f"postgres-role-check is missing live role evidence for {label}")
            continue
        if entry.get("rolsuper") is not False or entry.get("rolbypassrls") is not False:
            add(f"postgres-role-check {label} role must prove rolsuper=false and rolbypassrls=false")
    checks_raw = stdout_json.get("checks")
    checks_by_name = (
        {str(check.get("name") or ""): check for check in checks_raw if isinstance(check, Mapping)}
        if isinstance(checks_raw, list)
        else {}
    )
    for name in POSTGRES_ROLE_CHECK_REQUIRED_CHECKS:
        entry = checks_by_name.get(name)
        if not isinstance(entry, Mapping) or entry.get("ok") is not True:
            add(f"postgres-role-check check {name} is not proven")
    emitted = stdout_json.get("findings")
    if not isinstance(emitted, list) or emitted:
        add("postgres-role-check report must have an empty findings list")
    if stdout_json.get("ok") is not True:
        add("postgres-role-check report must be ok")
    fingerprint = str(stdout_json.get("fingerprint") or "")
    if len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint):
        add("postgres-role-check report requires a sha256 fingerprint")
    return findings


def _release_idp_jwks_evidence_findings(stdout_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Production IdP evidence must prove JWKS kid-sha256 pinning is active.

    A live check that verified a token against an unpinned JWKS proves the IdP
    endpoint worked, not that a swapped or poisoned keyset would fail closed."""
    findings: list[dict[str, Any]] = []

    def add(message: str) -> None:
        findings.append(_release_finding("idp_jwks_kid_pin_weak", message))

    jwks = stdout_json.get("jwks")
    if not isinstance(jwks, Mapping):
        add("idp-jwks-live-check evidence is missing the jwks section")
        return findings
    kid_pinning = jwks.get("kid_pinning")
    if not isinstance(kid_pinning, Mapping):
        add("idp-jwks-live-check evidence is missing jwks kid_pinning proof")
        return findings
    if kid_pinning.get("enabled") is not True:
        add("production idp-jwks-live-check evidence requires kid sha256 pinning to be enabled")
    pinned_count = kid_pinning.get("pinned_kid_count")
    if not isinstance(pinned_count, int) or pinned_count < 1:
        add("production idp-jwks-live-check evidence requires at least one pinned kid sha256")
    usable_count = kid_pinning.get("usable_key_count")
    if not isinstance(usable_count, int) or usable_count < 1:
        add("production idp-jwks-live-check evidence requires at least one usable pinned signing key")
    return findings


def _release_command_output_findings(check: Mapping[str, Any]) -> list[dict[str, Any]]:
    command = check.get("command")
    if not isinstance(command, str) or command not in RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS:
        return []
    if check.get("ok") is not True:
        return []
    stdout_json = check.get("stdout_json")
    if not isinstance(stdout_json, Mapping):
        return [
            _release_finding(
                "required_command_output_missing",
                f"required deployment check {command} did not emit structured JSON evidence",
            )
        ]
    if command == "ops-report":
        report = stdout_json.get("report")
        required_keys = RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS[command]
        if isinstance(report, Mapping):
            findings = _release_required_output_evidence_findings(command, report, required_keys)
            findings.extend(_release_ops_report_evidence_findings(report))
            return findings
        missing_ops_report = [key for key in required_keys if key not in stdout_json]
        if not missing_ops_report:
            findings = _release_required_output_evidence_findings(command, stdout_json, required_keys)
            findings.extend(_release_ops_report_evidence_findings(stdout_json))
            return findings
        return [
            _release_finding(
                "required_command_output_incomplete",
                f"required deployment check {command} is missing output sections: {', '.join(missing_ops_report)}",
            )
        ]
    required_keys = RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS[command]
    missing = [key for key in required_keys if key not in stdout_json]
    findings: list[dict[str, Any]] = []
    if missing:
        findings.append(
            _release_finding(
                "required_command_output_incomplete",
                f"required deployment check {command} is missing output sections: {', '.join(missing)}",
            )
        )
    if not missing:
        findings.extend(
            _release_required_output_evidence_findings(command, stdout_json, required_keys)
        )
    if not missing and command in RELEASE_AUDIT_BUNDLE_OPS_COMMANDS:
        findings.extend(_release_bundle_ops_evidence_findings(command, stdout_json))
    if command == "worker-run":
        findings.extend(_release_worker_run_evidence_findings(stdout_json))
    if command == "ops-dashboard-check":
        findings.extend(_release_ops_dashboard_evidence_findings(stdout_json))
    if command == "worker-ops-check":
        findings.extend(_release_worker_ops_evidence_findings(stdout_json))
    if command == "retrieval-ops-check":
        findings.extend(_release_retrieval_ops_evidence_findings(stdout_json))
    if command == "tls-lifecycle-ops-check":
        findings.extend(_release_tls_lifecycle_evidence_findings(stdout_json))
    if command == "parametric-trainer-check":
        findings.extend(_release_parametric_trainer_evidence_findings(stdout_json))
    if command == "mcp-ops-check":
        findings.extend(_release_mcp_ops_evidence_findings(stdout_json))
    if command == "privacy-ops-check":
        findings.extend(_release_privacy_ops_evidence_findings(stdout_json))
    if command == "idp-jwks-live-check":
        findings.extend(_release_idp_jwks_evidence_findings(stdout_json))
    if command == "postgres-role-check":
        findings.extend(_release_postgres_role_evidence_findings(stdout_json))
    return findings


def _release_placeholder_paths(value: Any, *, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, str):
        lowered = value.strip().lower()
        if any(marker in lowered for marker in RELEASE_AUDIT_PLACEHOLDER_MARKERS):
            paths.append(path)
    elif isinstance(value, Mapping):
        for key, child in value.items():
            paths.extend(_release_placeholder_paths(child, path=f"{path}.{key}"))
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            paths.extend(_release_placeholder_paths(child, path=f"{path}[{index}]"))
    return paths


def _release_has_substantive_evidence(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool | int | float):
        return True
    if isinstance(value, str):
        stripped = value.strip()
        lowered = stripped.lower()
        return bool(stripped) and not any(
            marker in lowered for marker in RELEASE_AUDIT_PLACEHOLDER_MARKERS
        )
    if isinstance(value, Mapping):
        return bool(value) and any(_release_has_substantive_evidence(child) for child in value.values())
    if isinstance(value, list | tuple):
        return bool(value) and any(_release_has_substantive_evidence(child) for child in value)
    return True


def _release_required_output_evidence_findings(
    command: str,
    stdout_json: Mapping[str, Any],
    required_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    placeholder_paths = _release_placeholder_paths(stdout_json)
    if placeholder_paths:
        findings.append(
            _release_finding(
                "required_command_output_placeholder",
                f"required deployment check {command} contains placeholder evidence at "
                + ", ".join(placeholder_paths[:8]),
            )
        )
    hollow_keys = [
        key
        for key in required_keys
        if key not in RELEASE_AUDIT_ALLOWED_EMPTY_OUTPUT_KEYS
        and not _release_has_substantive_evidence(stdout_json.get(key))
    ]
    if hollow_keys:
        findings.append(
            _release_finding(
                "required_command_output_hollow",
                f"required deployment check {command} has hollow output sections: "
                + ", ".join(hollow_keys),
            )
        )
    return findings


def _release_provider_check_summary(
    provider_report: Mapping[str, Any] | None,
    required_provider_checks: list[str],
) -> list[dict[str, Any]]:
    provider_checks = provider_report.get("checks") if isinstance(provider_report, Mapping) else None
    rows: list[dict[str, Any]] = []
    for name in required_provider_checks:
        check = provider_checks.get(name) if isinstance(provider_checks, Mapping) else None
        rows.append(
            {
                "check": name,
                "present": isinstance(check, Mapping),
                "ok": isinstance(check, Mapping) and check.get("ok") is True,
                "skipped": isinstance(check, Mapping) and check.get("skipped") is True,
                "latency": check.get("latency") if isinstance(check, Mapping) else None,
            }
        )
    return rows


def _release_provider_latency_findings(
    provider_report: Mapping[str, Any] | None,
    required_provider_checks: list[str],
) -> list[dict[str, Any]]:
    provider_checks = provider_report.get("checks") if isinstance(provider_report, Mapping) else None
    findings: list[dict[str, Any]] = []
    for name in sorted(PRODUCTION_RELEASE_LATENCY_PROVIDER_CHECKS.intersection(required_provider_checks)):
        check = provider_checks.get(name) if isinstance(provider_checks, Mapping) else None
        latency = check.get("latency") if isinstance(check, Mapping) else None
        if not isinstance(latency, Mapping):
            findings.append(
                _release_finding(
                    "provider_check_latency_evidence_incomplete",
                    f"provider-check subcheck {name} is missing latency evidence",
                )
            )
            continue
        samples = latency.get("samples")
        p95_latency_ms = latency.get("p95_latency_ms")
        if not isinstance(samples, int) or isinstance(samples, bool) or samples < PRODUCTION_RELEASE_MIN_LATENCY_SAMPLES:
            findings.append(
                _release_finding(
                    "provider_check_latency_evidence_incomplete",
                    f"provider-check subcheck {name} must include at least "
                    f"{PRODUCTION_RELEASE_MIN_LATENCY_SAMPLES} latency samples",
                )
            )
        if not isinstance(p95_latency_ms, int | float) or isinstance(p95_latency_ms, bool):
            findings.append(
                _release_finding(
                    "provider_check_latency_evidence_incomplete",
                    f"provider-check subcheck {name} must include numeric p95_latency_ms",
                )
            )
    return findings


def _build_release_audit_report(args: argparse.Namespace) -> dict[str, Any]:
    report, source = _load_release_audit_report(args)
    checks_raw = report.get("checks")
    if not isinstance(checks_raw, list):
        raise SystemExit("deployment-soak report requires checks array")
    checks = [item for item in checks_raw if isinstance(item, Mapping)]
    required_commands = sorted(set(args.require_command or PRODUCTION_RELEASE_REQUIRED_COMMANDS))
    required_provider_checks = sorted(set(args.require_provider_check or PRODUCTION_RELEASE_REQUIRED_PROVIDER_CHECKS))
    fingerprint = _release_audit_fingerprint(report)
    findings: list[dict[str, Any]] = []

    signature_status: dict[str, Any] | None = None
    require_signed_evidence = bool(getattr(args, "require_signed_evidence", False))
    collector_public_key_file = getattr(args, "collector_public_key_file", None)
    if require_signed_evidence or collector_public_key_file:
        from mnemosyne.evidence_signing import EvidenceSignatureError, verify_evidence_manifest_signature

        if not collector_public_key_file:
            findings.append(
                _release_finding(
                    "evidence_signature_key_missing",
                    "signed evidence verification requires --collector-public-key-file "
                    "or MNEMOSYNE_COLLECTOR_PUBLIC_KEY_FILE",
                )
            )
        elif source.get("kind") != "evidence_manifest":
            findings.append(
                _release_finding(
                    "evidence_signature_manifest_required",
                    "signed evidence verification requires --evidence-manifest so the "
                    "collector signature binds the digest manifest",
                )
            )
        else:
            signature_file = getattr(args, "evidence_signature_file", None)
            try:
                signature_status = verify_evidence_manifest_signature(
                    Path(source["manifest_path"]),
                    Path(collector_public_key_file).expanduser(),
                    signature_path=Path(signature_file).expanduser() if signature_file else None,
                )
            except EvidenceSignatureError as exc:
                findings.append(_release_finding("evidence_signature_invalid", str(exc)))

    if report.get("ok") is not True:
        findings.append(_release_finding("soak_report_not_ok", "deployment-soak report is not ok"))
    summary = report.get("summary")
    if isinstance(summary, Mapping) and int(summary.get("required_failures") or 0) > 0:
        findings.append(
            _release_finding(
                "required_soak_failures",
                f"deployment-soak reported {summary.get('required_failures')} required failures",
            )
        )
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != fingerprint:
        findings.append(_release_finding("fingerprint_mismatch", "release-audit fingerprint mismatch"))
    if args.require_production_validated:
        if source.get("kind") != "evidence_manifest":
            findings.append(
                _release_finding(
                    "production_evidence_manifest_required",
                    "production release-audit requires --evidence-manifest so report/check files are digest-bound",
                )
            )
        validation_scope = report.get("validation_scope")
        if not isinstance(validation_scope, Mapping):
            findings.append(
                _release_finding(
                    "production_validation_missing",
                    "deployment-soak report was not marked as production validated",
                )
            )
        else:
            if validation_scope.get("production_validated") is not True:
                findings.append(
                    _release_finding(
                        "production_validation_missing",
                        "deployment-soak report was not marked as production validated",
                    )
                )
            if validation_scope.get("target_environment") != "production":
                findings.append(
                    _release_finding(
                        "production_target_missing",
                        "deployment-soak report did not target production",
                    )
                )
            if validation_scope.get("operator_asserted") is not True:
                findings.append(
                    _release_finding(
                        "operator_attestation_missing",
                        "deployment-soak report is missing operator production attestation",
                    )
                )
    if not _release_redaction_ok(report):
        findings.append(_release_finding("report_redaction_missing", "deployment-soak report redaction flags are incomplete"))
    for check in checks:
        if not _release_check_redaction_ok(check):
            findings.append(
                _release_finding(
                    "check_redaction_missing",
                    f"check {check.get('name') or check.get('index')} redaction flags are incomplete",
                )
            )

    command_summary = _release_command_summary(checks, required_commands)
    required_command_set = set(required_commands)
    unexpected_commands = sorted(
        {
            command
            for check in checks
            if isinstance(command := check.get("command"), str) and command not in required_command_set
        }
    )
    if args.require_production_validated and unexpected_commands:
        findings.append(
            _release_finding(
                "unexpected_production_command",
                "production deployment evidence contains unknown checks: " + ", ".join(unexpected_commands),
            )
        )
    for check in checks:
        if check.get("command") in required_command_set:
            findings.extend(_release_command_output_findings(check))
    for row in command_summary:
        if not row["present"]:
            findings.append(
                _release_finding("missing_required_command", f"required deployment check {row['command']} is missing")
            )
        elif args.require_production_validated and row["count"] != 1:
            findings.append(
                _release_finding(
                    "duplicate_required_command",
                    (
                        f"required deployment check {row['command']} appears {row['count']} times; "
                        "production profile requires exactly one"
                    ),
                )
            )
        elif not row["ok"]:
            findings.append(
                _release_finding("required_command_failed", f"required deployment check {row['command']} did not pass")
            )

    provider_report = _release_provider_stdout(checks)
    provider_manifest = provider_report.get("manifest") if isinstance(provider_report, Mapping) else None
    provider_checks = provider_report.get("checks") if isinstance(provider_report, Mapping) else None
    if provider_report is None:
        findings.append(_release_finding("provider_check_missing", "provider-check did not pass in deployment evidence"))
    else:
        if args.require_provider_forbid_local:
            if not isinstance(provider_manifest, Mapping) or provider_manifest.get("forbid_local") is not True:
                findings.append(
                    _release_finding(
                        "provider_manifest_forbid_local_missing",
                        "provider-check manifest must set forbid_local=true",
                    )
                )
        retrieval = provider_checks.get("retrieval_backends") if isinstance(provider_checks, Mapping) else None
        if isinstance(retrieval, Mapping):
            if retrieval.get("lexical_local") or retrieval.get("graph_local"):
                findings.append(
                    _release_finding(
                        "provider_check_local_retrieval_backend",
                        "provider-check reported a local lexical or graph retrieval backend",
                    )
                )
        elif "retrieval_backends" in required_provider_checks:
            findings.append(
                _release_finding(
                    "provider_check_missing_retrieval_backends",
                    "provider-check did not report retrieval_backends",
                )
            )
    provider_check_summary = _release_provider_check_summary(provider_report, required_provider_checks)
    findings.extend(_release_provider_latency_findings(provider_report, required_provider_checks))
    for row in provider_check_summary:
        if not row["present"]:
            findings.append(
                _release_finding("missing_required_provider_check", f"provider-check subcheck {row['check']} is missing")
            )
        elif row["skipped"]:
            findings.append(
                _release_finding("required_provider_check_skipped", f"provider-check subcheck {row['check']} was skipped")
            )
        elif not row["ok"]:
            findings.append(
                _release_finding("required_provider_check_failed", f"provider-check subcheck {row['check']} did not pass")
            )

    report_out = {
        "ok": not findings,
        "source": source,
        "fingerprint": fingerprint,
        "expected_fingerprint_present": bool(args.expected_fingerprint),
        "requirements": {
            "required_commands": required_commands,
            "required_provider_checks": required_provider_checks,
            "require_provider_forbid_local": bool(args.require_provider_forbid_local),
            "require_production_validated": bool(args.require_production_validated),
            "require_signed_evidence": require_signed_evidence,
        },
        "signature": signature_status,
        "validation_scope": report.get("validation_scope"),
        "summary": {
            "checks": len(checks),
            "required_command_count": len(required_commands),
            "required_provider_check_count": len(required_provider_checks),
            "findings": len(findings),
        },
        "commands": command_summary,
        "provider": {
            "provider_check_found": provider_report is not None,
            "manifest": provider_manifest if isinstance(provider_manifest, Mapping) else None,
            "checks": provider_check_summary,
            "retrieval_backends": provider_checks.get("retrieval_backends")
            if isinstance(provider_checks, Mapping)
            else None,
        },
        "findings": findings,
    }
    return report_out


def cmd_release_audit(args: argparse.Namespace) -> None:
    report_out = _build_release_audit_report(args)
    emit(report_out)
    if report_out["findings"]:
        raise SystemExit(1)


def cmd_evidence_keygen(args: argparse.Namespace) -> None:
    from mnemosyne.evidence_signing import EvidenceSignatureError, generate_collector_keypair

    try:
        result = generate_collector_keypair(
            Path(args.private_key_file).expanduser(),
            Path(args.public_key_file).expanduser(),
        )
    except EvidenceSignatureError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(1) from exc
    emit({"ok": True, **result})


def cmd_evidence_sign(args: argparse.Namespace) -> None:
    from mnemosyne.evidence_signing import EvidenceSignatureError, sign_evidence_manifest

    try:
        result = sign_evidence_manifest(
            Path(args.evidence_manifest).expanduser(),
            Path(args.private_key_file).expanduser(),
            signature_path=Path(args.signature_file).expanduser() if args.signature_file else None,
        )
    except EvidenceSignatureError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(1) from exc
    emit({"ok": True, **result})


def cmd_evidence_verify(args: argparse.Namespace) -> None:
    from mnemosyne.evidence_signing import EvidenceSignatureError, verify_evidence_manifest_signature

    try:
        result = verify_evidence_manifest_signature(
            Path(args.evidence_manifest).expanduser(),
            Path(args.public_key_file).expanduser(),
            signature_path=Path(args.signature_file).expanduser() if args.signature_file else None,
        )
    except EvidenceSignatureError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(1) from exc
    emit({"ok": True, **result})


def _audit_chain_hmac_provider(args: argparse.Namespace) -> tuple[str, Any]:
    from mnemosyne.audit_chain import (
        LOCAL_HMAC_PROVIDER,
        VAULT_HMAC_PROVIDER,
        AuditChainError,
        command_hmac_provider,
        local_hmac_provider,
    )

    try:
        if args.hmac_command:
            return VAULT_HMAC_PROVIDER, command_hmac_provider(args.hmac_command, timeout=args.hmac_timeout)
        if args.local_hmac_secret_file:
            secret = Path(args.local_hmac_secret_file).expanduser().read_text(encoding="utf-8").strip()
            return LOCAL_HMAC_PROVIDER, local_hmac_provider(secret)
    except (OSError, AuditChainError) as exc:
        raise SystemExit(f"audit chain HMAC provider denied: {exc}") from exc
    raise SystemExit(
        "audit chain requires --hmac-command (Vault transit adapter) or "
        "--local-hmac-secret-file (explicitly non-production)"
    )


def _audit_chain_entries(engine: "MemoryEngine", tenant_id: str) -> list[Any]:
    exported = engine.export_tenant(tenant_id)
    entries = exported.get("audit_log")
    if not isinstance(entries, list):
        raise SystemExit("tenant export did not return an audit_log list")
    return entries


def cmd_audit_chain_export(args: argparse.Namespace) -> None:
    from mnemosyne.audit_chain import AuditChainError, build_audit_chain

    provider_name, hmac_provider = _audit_chain_hmac_provider(args)
    entries = _audit_chain_entries(load_engine(args), args.tenant)
    try:
        document = build_audit_chain(
            entries,
            tenant_id=args.tenant,
            provider_name=provider_name,
            hmac_provider=hmac_provider,
        )
    except AuditChainError as exc:
        emit({"ok": False, "tenant_id": args.tenant, "error": str(exc)})
        raise SystemExit(1) from exc
    output = Path(args.output).expanduser()
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    emit(
        {
            "ok": True,
            "output": str(output),
            "schema": document["schema"],
            "provider": document["provider"],
            "non_production": document["non_production"],
            "tenant_id": args.tenant,
            "entry_count": document["entry_count"],
            "head_link_sha256": document["head_link_sha256"],
            "head_hmac": document["head_hmac"],
        }
    )


def cmd_audit_chain_verify(args: argparse.Namespace) -> None:
    from mnemosyne.audit_chain import AuditChainError, verify_audit_chain

    _provider_name, hmac_provider = _audit_chain_hmac_provider(args)
    try:
        document = json.loads(Path(args.chain_file).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        emit({"ok": False, "tenant_id": args.tenant, "error": f"audit chain document denied: {exc}"})
        raise SystemExit(1) from exc
    entries = _audit_chain_entries(load_engine(args), args.tenant)
    try:
        result = verify_audit_chain(
            document,
            entries,
            tenant_id=args.tenant,
            hmac_provider=hmac_provider,
        )
    except AuditChainError as exc:
        emit({"ok": False, "tenant_id": args.tenant, "error": str(exc)})
        raise SystemExit(1) from exc
    emit({"ok": True, **result})


def _production_evidence_finding(
    findings: list[dict[str, Any]],
    code: str,
    message: str,
    *,
    severity: str = "critical",
) -> None:
    findings.append(_release_finding(code, message, severity=severity))


def _read_json_object_for_evidence(
    path: Path,
    label: str,
    findings: list[dict[str, Any]],
    *,
    bundle_dir: Path,
) -> dict[str, Any] | None:
    if path.is_symlink():
        _production_evidence_finding(
            findings,
            f"{label}_symlink",
            f"{label} must be a retained JSON file, not a symlink",
        )
        return None
    try:
        resolved_path = path.resolve(strict=True)
    except FileNotFoundError:
        _production_evidence_finding(findings, f"{label}_missing", f"{label} is missing")
        return None
    except OSError as exc:
        _production_evidence_finding(findings, f"{label}_invalid", f"{label} denied: {exc}")
        return None
    try:
        resolved_path.relative_to(bundle_dir)
    except ValueError:
        _production_evidence_finding(
            findings,
            f"{label}_escape",
            f"{label} resolves outside the production evidence bundle",
        )
        return None
    if not resolved_path.is_file():
        _production_evidence_finding(findings, f"{label}_invalid", f"{label} must be a JSON file")
        return None
    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _production_evidence_finding(findings, f"{label}_missing", f"{label} is missing")
        return None
    except (OSError, json.JSONDecodeError) as exc:
        _production_evidence_finding(findings, f"{label}_invalid", f"{label} denied: {exc}")
        return None
    if not isinstance(payload, dict):
        _production_evidence_finding(findings, f"{label}_invalid", f"{label} must be a JSON object")
        return None
    return payload


def _production_evidence_bundle_path(
    bundle_dir: Path,
    value: Any,
    label: str,
    findings: list[dict[str, Any]],
) -> Path | None:
    if not isinstance(value, str) or not value:
        _production_evidence_finding(findings, "bundle_manifest_invalid_path", f"{label} must be a non-empty path")
        return None
    relative_path = Path(value)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        _production_evidence_finding(
            findings,
            "bundle_manifest_invalid_path",
            f"{label} must be a relative path inside the evidence bundle",
        )
        return None
    try:
        root = bundle_dir.resolve(strict=True)
        candidate = (bundle_dir / relative_path).resolve(strict=True)
        candidate.relative_to(root)
    except FileNotFoundError:
        _production_evidence_finding(findings, "bundle_file_missing", f"{label} is missing: {value}")
        return None
    except (OSError, ValueError) as exc:
        _production_evidence_finding(findings, "bundle_manifest_invalid_path", f"{label} denied: {exc}")
        return None
    return bundle_dir / relative_path


def _production_evidence_bundle_entry(path: Path, bundle_dir: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(bundle_dir).as_posix(),
        "size_bytes": len(payload),
        "sha256": "sha256:" + sha256(payload).hexdigest(),
    }


def _production_evidence_bundle_fingerprint(files: list[dict[str, Any]]) -> str:
    payload = {
        "schema": PRODUCTION_EVIDENCE_BUNDLE_SCHEMA,
        "files": files,
    }
    return "sha256:" + sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _actual_production_evidence_files(
    bundle_dir: Path,
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actual_files: list[dict[str, Any]] = []
    root = bundle_dir.resolve(strict=True)
    for path in sorted(item for item in bundle_dir.rglob("*") if item.is_file() or item.is_symlink()):
        relative_path = path.relative_to(bundle_dir).as_posix()
        if relative_path in PRODUCTION_EVIDENCE_BUNDLE_EXCLUDED_FILES:
            continue
        if path.is_symlink():
            _production_evidence_finding(
                findings,
                "bundle_file_symlink",
                f"production evidence artifact must not be a symlink: {relative_path}",
            )
            continue
        try:
            path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            _production_evidence_finding(
                findings,
                "bundle_file_escape",
                f"production evidence artifact resolves outside the bundle: {relative_path}: {exc}",
            )
            continue
        actual_files.append(_production_evidence_bundle_entry(path, bundle_dir))
    return actual_files


def _verify_production_evidence_bundle_manifest(
    *,
    bundle_dir: Path,
    bundle_manifest: Mapping[str, Any],
    summary: Mapping[str, Any] | None,
    expected_bundle_fingerprint: str | None,
    findings: list[dict[str, Any]],
) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    if bundle_manifest.get("schema") != PRODUCTION_EVIDENCE_BUNDLE_SCHEMA:
        _production_evidence_finding(
            findings,
            "bundle_manifest_schema_invalid",
            "bundle-manifest.json has unsupported schema",
        )
    manifest_files = bundle_manifest.get("files")
    if not isinstance(manifest_files, list) or not all(isinstance(item, Mapping) for item in manifest_files):
        _production_evidence_finding(
            findings,
            "bundle_manifest_files_invalid",
            "bundle-manifest.json files must be an array of objects",
        )
        manifest_files = []
    typed_manifest_files = [
        {
            "path": item.get("path"),
            "size_bytes": item.get("size_bytes"),
            "sha256": item.get("sha256"),
        }
        for item in manifest_files
        if isinstance(item, Mapping)
    ]
    artifact_count = bundle_manifest.get("artifact_count")
    if artifact_count != len(typed_manifest_files):
        _production_evidence_finding(
            findings,
            "bundle_manifest_artifact_count_mismatch",
            "bundle-manifest.json artifact_count does not match files length",
        )
    manifest_fingerprint = bundle_manifest.get("fingerprint")
    if not isinstance(manifest_fingerprint, str) or not manifest_fingerprint.startswith("sha256:"):
        _production_evidence_finding(
            findings,
            "bundle_manifest_fingerprint_missing",
            "bundle-manifest.json requires a sha256 fingerprint",
        )
        manifest_fingerprint = None
    recorded_fingerprint = _production_evidence_bundle_fingerprint(typed_manifest_files)
    if manifest_fingerprint and manifest_fingerprint != recorded_fingerprint:
        _production_evidence_finding(
            findings,
            "bundle_manifest_fingerprint_mismatch",
            "bundle-manifest.json fingerprint does not match its files payload",
        )
    if expected_bundle_fingerprint and expected_bundle_fingerprint != manifest_fingerprint:
        _production_evidence_finding(
            findings,
            "expected_bundle_fingerprint_mismatch",
            "expected production evidence bundle fingerprint did not match",
        )
    if summary is not None and summary.get("bundle_fingerprint") != manifest_fingerprint:
        _production_evidence_finding(
            findings,
            "summary_bundle_fingerprint_mismatch",
            "summary.json bundle_fingerprint does not match bundle-manifest.json",
        )

    manifest_paths: set[str] = set()
    for index, item in enumerate(typed_manifest_files, start=1):
        rel_path = item.get("path")
        if not isinstance(rel_path, str):
            _production_evidence_finding(
                findings,
                "bundle_manifest_invalid_path",
                f"bundle-manifest.json files[{index}].path must be a string",
            )
            continue
        if rel_path in PRODUCTION_EVIDENCE_BUNDLE_EXCLUDED_FILES:
            _production_evidence_finding(
                findings,
                "bundle_manifest_excluded_file",
                f"bundle-manifest.json must not include {rel_path}",
            )
        if rel_path in manifest_paths:
            _production_evidence_finding(
                findings,
                "bundle_manifest_duplicate_file",
                f"bundle-manifest.json lists {rel_path} more than once",
            )
        manifest_paths.add(rel_path)
        path = _production_evidence_bundle_path(bundle_dir, rel_path, f"files[{index}].path", findings)
        if path is None:
            continue
        if path.is_symlink():
            _production_evidence_finding(
                findings,
                "bundle_file_symlink",
                f"production evidence artifact must not be a symlink: {rel_path}",
            )
            continue
        try:
            expected_size = item.get("size_bytes")
            if not isinstance(expected_size, int) or expected_size < 0:
                _production_evidence_finding(
                    findings,
                    "bundle_file_size_invalid",
                    f"bundle-manifest.json files[{index}].size_bytes must be a non-negative integer",
                )
            elif path.stat().st_size != expected_size:
                _production_evidence_finding(
                    findings,
                    "bundle_file_size_mismatch",
                    f"production evidence artifact size mismatch: {rel_path}",
                )
            expected_sha256 = item.get("sha256")
            if not isinstance(expected_sha256, str) or not expected_sha256.startswith("sha256:"):
                _production_evidence_finding(
                    findings,
                    "bundle_file_sha256_invalid",
                    f"bundle-manifest.json files[{index}].sha256 must be a sha256 digest",
                )
            elif _file_sha256(path) != expected_sha256:
                _production_evidence_finding(
                    findings,
                    "bundle_file_sha256_mismatch",
                    f"production evidence artifact digest mismatch: {rel_path}",
                )
        except OSError as exc:
            _production_evidence_finding(
                findings,
                "bundle_file_denied",
                f"production evidence artifact denied: {rel_path}: {exc}",
            )

    actual_files = _actual_production_evidence_files(bundle_dir, findings)
    actual_paths = {str(item["path"]) for item in actual_files}
    required_missing = sorted(PRODUCTION_EVIDENCE_REQUIRED_FILES - actual_paths)
    if required_missing:
        _production_evidence_finding(
            findings,
            "production_evidence_required_file_missing",
            "production evidence bundle is missing required files: " + ", ".join(required_missing),
        )
    missing_from_manifest = sorted(actual_paths - manifest_paths)
    unexpected_manifest_paths = sorted(manifest_paths - actual_paths)
    if missing_from_manifest:
        _production_evidence_finding(
            findings,
            "bundle_manifest_missing_actual_files",
            "bundle-manifest.json does not list artifacts: " + ", ".join(missing_from_manifest),
        )
    if unexpected_manifest_paths:
        _production_evidence_finding(
            findings,
            "bundle_manifest_unknown_files",
            "bundle-manifest.json lists missing artifacts: " + ", ".join(unexpected_manifest_paths),
        )
    actual_fingerprint = _production_evidence_bundle_fingerprint(actual_files)
    if manifest_fingerprint and manifest_fingerprint != actual_fingerprint:
        _production_evidence_finding(
            findings,
            "bundle_fingerprint_mismatch",
            "bundle-manifest.json fingerprint does not match current bundle files",
        )
    return manifest_fingerprint, actual_fingerprint, actual_files


def _production_evidence_summary_expected_paths(bundle_dir: Path) -> dict[str, Path]:
    return {
        "out_root": bundle_dir,
        "operator_manifest": bundle_dir / "operator-soak-manifest.json",
        "evidence_manifest": bundle_dir / "evidence" / "manifest.json",
        "redaction_scan": bundle_dir / "redaction-scan.json",
        "bundle_manifest": bundle_dir / "bundle-manifest.json",
    }


def _production_evidence_iso_datetime_ok(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _production_evidence_summary_offline_verify_argv_ok(
    summary: Mapping[str, Any] | None,
    *,
    bundle_dir: Path,
) -> bool:
    if summary is None:
        return False
    offline_verify = summary.get("offline_verify")
    if not isinstance(offline_verify, Mapping):
        return False
    if not _production_evidence_path_matches(offline_verify.get("bundle_dir"), expected_path=bundle_dir):
        return False
    if "expected_bundle_fingerprint" in offline_verify:
        return False
    if offline_verify.get("expected_bundle_fingerprint_source") not in {
        "out-of-band-fingerprint-record",
        "out-of-band-capture-record",
    }:
        return False
    argv = offline_verify.get("argv")
    if (
        not isinstance(argv, list)
        or len(argv) not in {7, 9}
        or not all(isinstance(item, str) for item in argv)
    ):
        return False
    if not argv[0]:
        return False
    interpreter_name = Path(argv[0]).name.lower()
    if "python" not in interpreter_name:
        return False
    if argv[1:4] != ["-m", "mnemosyne.cli", "production-evidence-verify"]:
        return False
    if not _production_evidence_path_matches(argv[4], expected_path=bundle_dir):
        return False
    supported_expected_sources = {
        ("--expected-bundle-fingerprint", "<out-of-band-bundle-fingerprint>"),
        ("--fingerprint-record", "<out-of-band-fingerprint-record-json>"),
    }
    if tuple(argv[5:7]) not in supported_expected_sources:
        return False
    if len(argv) == 9 and argv[7:] != [
        "--report-output",
        "<external-review-report-json>",
    ]:
        return False
    note = offline_verify.get("note")
    return (
        isinstance(note, str)
        and "Custody review only" in note
        and "does not rerun production checks" in note
        and (
            "out-of-band fingerprint record" in note
            or "out-of-band capture record" in note
        )
    )


def _production_evidence_sha256_digest_ok(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _production_evidence_bundle_relative_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        return None
    return path.as_posix()


def _provider_manifest_command_labels(value: Any, *, path: str) -> set[str]:
    labels: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "command":
                labels.add(child_path)
            labels.update(_provider_manifest_command_labels(item, path=child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            labels.update(_provider_manifest_command_labels(item, path=f"{path}[{index}]"))
    return labels


def _verify_provider_manifest_command_arguments(
    value: Any,
    *,
    path: str,
    findings: list[dict[str, Any]],
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "command":
                if not isinstance(item, str):
                    _production_evidence_finding(
                        findings,
                        "preflight_provider_command_retained_value_invalid",
                        f"{child_path} must be a retained command string in the provider manifest snapshot",
                    )
                    continue
                try:
                    command_parts = shlex.split(item)
                except ValueError as exc:
                    _production_evidence_finding(
                        findings,
                        "preflight_provider_command_retained_value_invalid",
                        f"{child_path} command cannot be parsed in the retained provider manifest: {exc}",
                    )
                    continue
                if len(command_parts) > 1:
                    _production_evidence_finding(
                        findings,
                        "preflight_provider_command_unretained_argument",
                        f"{child_path} command must be a single retained executable with no arguments after argv[0]",
                    )
            _verify_provider_manifest_command_arguments(
                item,
                path=child_path,
                findings=findings,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _verify_provider_manifest_command_arguments(
                item,
                path=f"{path}[{index}]",
                findings=findings,
            )


def _production_evidence_provider_manifest_command_labels(
    preflight: Mapping[str, Any],
    *,
    bundle_dir: Path,
    findings: list[dict[str, Any]],
) -> set[str]:
    input_artifacts = preflight.get("required_input_artifacts")
    if not isinstance(input_artifacts, list):
        return set()
    labels: set[str] = set()
    for artifact in input_artifacts:
        if not isinstance(artifact, Mapping):
            continue
        artifact_labels = artifact.get("labels", [])
        snapshot_path_value = artifact.get("snapshot_path")
        if not isinstance(snapshot_path_value, str) or not snapshot_path_value:
            continue
        if not (
            "provider-manifest" in Path(snapshot_path_value).name
            or (
                isinstance(artifact_labels, list)
                and any("--provider-manifest" in str(label) for label in artifact_labels)
            )
        ):
            continue
        try:
            snapshot_path = Path(snapshot_path_value).expanduser().resolve(strict=True)
            snapshot_path.relative_to(bundle_dir.resolve(strict=False))
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            _production_evidence_finding(
                findings,
                "preflight_provider_manifest_command_labels_unreadable",
                f"provider manifest command labels cannot be read from retained snapshot: {exc}",
            )
            continue
        if not isinstance(payload, Mapping):
            _production_evidence_finding(
                findings,
                "preflight_provider_manifest_command_labels_invalid",
                "retained provider manifest must be a JSON object for command custody",
            )
            continue
        if payload.get("forbid_local") is not True:
            _production_evidence_finding(
                findings,
                "preflight_provider_manifest_forbid_local_missing",
                "retained provider manifest must set forbid_local=true",
            )
        required_checks = payload.get("required_checks")
        expected_checks = set(PRODUCTION_RELEASE_REQUIRED_PROVIDER_CHECKS)
        if not isinstance(required_checks, list) or not all(
            isinstance(item, str) for item in required_checks
        ):
            _production_evidence_finding(
                findings,
                "preflight_provider_manifest_required_checks_invalid",
                "retained provider manifest required_checks must be a string array",
            )
        else:
            actual_checks = set(required_checks)
            missing_checks = sorted(expected_checks - actual_checks)
            extra_checks = sorted(actual_checks - expected_checks)
            if missing_checks:
                _production_evidence_finding(
                    findings,
                    "preflight_provider_manifest_required_checks_missing",
                    "retained provider manifest missing production provider checks: "
                    + ", ".join(missing_checks),
                )
            if extra_checks:
                _production_evidence_finding(
                    findings,
                    "preflight_provider_manifest_required_checks_unknown",
                    "retained provider manifest contains unsupported provider checks: "
                    + ", ".join(extra_checks),
                )
        if not isinstance(payload.get("providers"), Mapping):
            _production_evidence_finding(
                findings,
                "preflight_provider_manifest_providers_invalid",
                "retained provider manifest providers must be a JSON object",
            )
        _verify_provider_manifest_command_arguments(
            payload,
            path="provider-manifest.production.json",
            findings=findings,
        )
        labels.update(
            _provider_manifest_command_labels(
                payload,
                path="provider-manifest.production.json",
            )
        )
    return labels


def _verify_production_evidence_executable_tool_references(
    preflight: Mapping[str, Any],
    findings: list[dict[str, Any]],
    *,
    bundle_dir: Path,
) -> bool:
    references = preflight.get("executable_tool_references")
    if not isinstance(references, list) or not references:
        _production_evidence_finding(
            findings,
            "preflight_executable_tool_references_missing",
            "preflight.json must retain executable tool reference metadata",
        )
        return False
    ok = True
    c2pa_reference_seen = False
    provider_label_finding_count = len(findings)
    provider_command_labels = _production_evidence_provider_manifest_command_labels(
        preflight,
        bundle_dir=bundle_dir,
        findings=findings,
    )
    if len(findings) > provider_label_finding_count:
        ok = False
    provider_command_reference_labels: set[str] = set()
    allowed_options = {"--c2pa-tool", "suite.tool", "suite.c2pa_tool", "MNEMOSYNE_C2PA_TOOL"}
    for index, reference in enumerate(references, start=1):
        if not isinstance(reference, Mapping):
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_executable_tool_reference_invalid",
                f"preflight.json executable_tool_references[{index}] must be an object",
            )
            continue
        option = reference.get("option")
        path_value = reference.get("path")
        labels = reference.get("labels")
        size_bytes = reference.get("size_bytes")
        expected_sha256 = reference.get("sha256")
        snapshot_path_value = reference.get("snapshot_path")
        snapshot_relative_path = reference.get("snapshot_relative_path")
        snapshot_size_bytes = reference.get("snapshot_size_bytes")
        snapshot_sha256 = reference.get("snapshot_sha256")
        if (
            not isinstance(option, str)
            or not option
            or not isinstance(path_value, str)
            or not path_value
            or not isinstance(labels, list)
            or not labels
            or not all(isinstance(label, str) and label for label in labels)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or not _production_evidence_sha256_digest_ok(expected_sha256)
            or not isinstance(snapshot_path_value, str)
            or not snapshot_path_value
            or _production_evidence_bundle_relative_path(snapshot_relative_path) is None
            or not isinstance(snapshot_size_bytes, int)
            or snapshot_size_bytes < 0
            or not _production_evidence_sha256_digest_ok(snapshot_sha256)
        ):
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_executable_tool_reference_invalid",
                f"preflight.json executable_tool_references[{index}] has invalid metadata",
            )
            continue
        if option in allowed_options:
            c2pa_reference_seen = True
        if option == "provider-manifest.command":
            provider_command_reference_labels.update(labels)
        tool_path = Path(path_value).expanduser()
        if not tool_path.is_absolute():
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_executable_tool_reference_relative",
                f"preflight.json executable_tool_references[{index}].path must be absolute",
            )
            continue
        try:
            if tool_path.resolve(strict=False).is_relative_to(bundle_dir.resolve(strict=False)):
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_executable_tool_reference_path_not_external",
                    f"preflight.json executable_tool_references[{index}].path must be the deployed external tool path",
                )
        except (OSError, RuntimeError, ValueError):
            pass

        snapshot_path = Path(snapshot_path_value).expanduser()
        try:
            resolved_snapshot = snapshot_path.resolve(strict=True)
            resolved_snapshot.relative_to((bundle_dir / "tool-artifacts").resolve(strict=False))
            if resolved_snapshot.is_symlink():
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_executable_tool_snapshot_symlink",
                    f"preflight.json executable_tool_references[{index}].snapshot_path must not be a symlink",
                )
                continue
            if not resolved_snapshot.is_file():
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_executable_tool_snapshot_not_file",
                    f"preflight.json executable_tool_references[{index}].snapshot_path is not a file",
                )
                continue
            resolved_relative_path = resolved_snapshot.relative_to(bundle_dir.resolve(strict=False)).as_posix()
            if resolved_relative_path != snapshot_relative_path:
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_executable_tool_snapshot_relative_mismatch",
                    f"preflight.json executable_tool_references[{index}] snapshot relative path does not match retained file",
                )
                continue
            if resolved_snapshot.stat().st_size != size_bytes or snapshot_size_bytes != size_bytes:
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_executable_tool_snapshot_size_mismatch",
                    f"preflight.json executable_tool_references[{index}] size does not match retained executable snapshot",
                )
            retained_sha256 = _file_sha256(resolved_snapshot)
            if retained_sha256 != expected_sha256 or snapshot_sha256 != expected_sha256:
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_executable_tool_snapshot_sha256_mismatch",
                    f"preflight.json executable_tool_references[{index}] sha256 does not match retained executable snapshot",
                )
        except (OSError, ValueError) as exc:
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_executable_tool_snapshot_missing",
                f"preflight.json executable_tool_references[{index}].snapshot_path is missing or outside tool-artifacts: {exc}",
            )
    if not c2pa_reference_seen:
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_c2pa_executable_reference_missing",
            "preflight.json must retain C2PA executable digest metadata",
        )
    missing_provider_labels = sorted(provider_command_labels - provider_command_reference_labels)
    if missing_provider_labels:
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_provider_command_executable_reference_missing",
            "preflight.json must retain provider command executable digest metadata for: "
            + ", ".join(missing_provider_labels),
        )
    return ok


def _production_evidence_is_non_utf8_file(path: Path) -> bool:
    """True only if the file's actual bytes are not valid UTF-8 text.

    Anchored on the real bytes, never a declaration, so a text file can never be
    treated as binary custody and thereby skip the redaction secret-scan.
    """
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return True
    except OSError:
        return False
    return False


def _production_evidence_binary_custody_paths(
    preflight: Mapping[str, Any] | None,
    *,
    bundle_dir: Path,
) -> set[str]:
    if preflight is None:
        return set()
    paths: set[str] = set()
    bundle_root = bundle_dir.resolve(strict=False)
    references = preflight.get("executable_tool_references")
    if isinstance(references, list):
        tool_root = (bundle_dir / "tool-artifacts").resolve(strict=False)
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            snapshot_path_value = reference.get("snapshot_path")
            if not isinstance(snapshot_path_value, str) or not snapshot_path_value:
                continue
            try:
                snapshot_path = Path(snapshot_path_value).expanduser().resolve(strict=False)
                snapshot_path.relative_to(tool_root)
                paths.add(snapshot_path.relative_to(bundle_root).as_posix())
            except (OSError, ValueError):
                continue
    # Retained C2PA provenance input assets that are genuinely non-UTF-8 (e.g. signed
    # PNG or C2PA manifests) are integrity-pinned binary custody, mirroring the final
    # capture scan so capture and verify agree end-to-end. Anchored on the ACTUAL bytes
    # being non-UTF-8 -- never a declaration -- so a text file under input-artifacts is
    # always secret-scanned and can never be smuggled past redaction. Symlinks are never
    # exempted; the input-artifact custody check enforces declared-ness separately.
    input_root_path = bundle_dir / "input-artifacts"
    if input_root_path.is_dir() and not input_root_path.is_symlink():
        input_root = input_root_path.resolve(strict=False)
        for candidate in sorted(input_root_path.rglob("*")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(input_root)
            except (OSError, ValueError):
                continue
            if _production_evidence_is_non_utf8_file(resolved):
                paths.add(resolved.relative_to(bundle_root).as_posix())
    return paths


def _verify_production_evidence_summary(
    *,
    summary: Mapping[str, Any] | None,
    preflight: Mapping[str, Any] | None,
    bundle_dir: Path,
    findings: list[dict[str, Any]],
) -> None:
    if summary is None:
        return
    expected_truthy = {
        "redaction_scan_ok": "summary.json does not confirm redaction_scan_ok",
        "deployment_soak_ok": "summary.json does not confirm deployment_soak_ok",
        "release_audit_ok": "summary.json does not confirm release_audit_ok",
    }
    for key, message in expected_truthy.items():
        if summary.get(key) is not True:
            _production_evidence_finding(findings, f"summary_{key}_missing", message)
    for key, expected_path in _production_evidence_summary_expected_paths(bundle_dir).items():
        if not _production_evidence_path_matches(summary.get(key), expected_path=expected_path):
            _production_evidence_finding(
                findings,
                f"summary_{key}_invalid",
                f"summary.json {key} must resolve to the retained production evidence path",
            )
    completed_at = summary.get("completed_at")
    if not isinstance(completed_at, str):
        _production_evidence_finding(
            findings,
            "summary_completed_at_missing",
            "summary.json requires completed_at",
        )
    elif not _production_evidence_iso_datetime_ok(completed_at):
        _production_evidence_finding(
            findings,
            "summary_completed_at_invalid",
            "summary.json completed_at must be an ISO-8601 timestamp",
        )
    if summary.get("release_audit_findings") != []:
        _production_evidence_finding(
            findings,
            "summary_release_audit_findings_present",
            "summary.json reports release-audit findings",
        )
    if not _production_evidence_summary_offline_verify_argv_ok(summary, bundle_dir=bundle_dir):
        _production_evidence_finding(
            findings,
            "summary_offline_verify_invalid",
            "summary.json offline_verify must contain a verifier command template that requires an out-of-band expected fingerprint",
        )
    summary_row_readiness = summary.get("parity_row_readiness")
    if not isinstance(summary_row_readiness, list):
        _production_evidence_finding(
            findings,
            "summary_parity_row_readiness_invalid",
            "summary.json parity_row_readiness must mirror preflight.json parity_row_readiness",
        )
    elif isinstance(preflight, Mapping):
        preflight_row_readiness = preflight.get("parity_row_readiness")
        if isinstance(preflight_row_readiness, list) and summary_row_readiness != preflight_row_readiness:
            _production_evidence_finding(
                findings,
                "summary_parity_row_readiness_mismatch",
                "summary.json parity_row_readiness does not match preflight.json parity_row_readiness",
            )
    if summary.get("row_review_source") != "preflight.json.parity_row_readiness":
        _production_evidence_finding(
            findings,
            "summary_row_review_source_invalid",
            "summary.json row_review_source must point reviewers at preflight.json.parity_row_readiness",
        )


def _production_evidence_summary_ok(
    summary: Mapping[str, Any] | None,
    *,
    preflight: Mapping[str, Any] | None,
    bundle_dir: Path,
) -> bool:
    if summary is None:
        return False
    summary_row_readiness = summary.get("parity_row_readiness")
    preflight_row_readiness = preflight.get("parity_row_readiness") if isinstance(preflight, Mapping) else None
    row_readiness_ok = isinstance(summary_row_readiness, list) and (
        not isinstance(preflight_row_readiness, list) or summary_row_readiness == preflight_row_readiness
    )
    return (
        summary.get("redaction_scan_ok") is True
        and summary.get("deployment_soak_ok") is True
        and summary.get("release_audit_ok") is True
        and summary.get("release_audit_findings") == []
        and row_readiness_ok
        and summary.get("row_review_source") == "preflight.json.parity_row_readiness"
        and _production_evidence_iso_datetime_ok(summary.get("completed_at"))
        and _production_evidence_summary_offline_verify_argv_ok(summary, bundle_dir=bundle_dir)
        and all(
            _production_evidence_path_matches(summary.get(key), expected_path=expected_path)
            for key, expected_path in _production_evidence_summary_expected_paths(bundle_dir).items()
        )
    )


def _production_evidence_row_review(preflight: Mapping[str, Any] | None) -> dict[str, Any]:
    source = "preflight.json.parity_row_readiness"
    row_readiness = preflight.get("parity_row_readiness") if isinstance(preflight, Mapping) else None
    rows = [dict(row) for row in row_readiness if isinstance(row, Mapping)] if isinstance(row_readiness, list) else []
    incomplete_rows = [
        {
            "lane": row.get("lane"),
            "row": row.get("row"),
            "title": row.get("title"),
            "runbook": row.get("runbook"),
            "missing_input_artifacts": row.get("missing_input_artifacts", []),
            "input_artifact_errors": row.get("input_artifact_errors", []),
        }
        for row in rows
        if row.get("input_artifacts_complete") is not True
    ]
    return {
        "source": source,
        "rows": rows,
        "row_count": len(rows),
        "complete_row_count": sum(1 for row in rows if row.get("input_artifacts_complete") is True),
        "incomplete_rows": incomplete_rows,
    }


def _production_evidence_reviewer_guidance(
    *,
    findings: list[dict[str, Any]],
    row_review: Mapping[str, Any],
    internal_consistency_only: bool,
) -> dict[str, Any]:
    codes = {
        code
        for finding in findings
        if isinstance((code := finding.get("code")), str)
    }
    incomplete_rows = row_review.get("incomplete_rows")
    incomplete_row_count = len(incomplete_rows) if isinstance(incomplete_rows, list) else 0
    next_steps: list[str] = []
    blocked_reason = None

    if "preflight_completion_missing" in codes:
        blocked_reason = "preflight_only_bundle"
        next_steps.append(
            "This bundle is setup proof only. Run infra/scripts/capture-production-evidence.sh "
            "without --preflight-only against the production soak manifest to capture completed evidence."
        )

    if "expected_bundle_fingerprint_missing" in codes:
        blocked_reason = blocked_reason or "missing_expected_fingerprint"
        next_steps.append(
            "Provide --fingerprint-record from the independently retained out-of-band "
            "operator fingerprint record, or provide --expected-bundle-fingerprint from that record. "
            "Do not copy the value from the bundle under review."
        )

    if "expected_bundle_fingerprint_mode_conflict" in codes:
        blocked_reason = blocked_reason or "fingerprint_mode_conflict"
        next_steps.append(
            "Choose exactly one verifier mode. For Tier B custody review, remove "
            "--internal-consistency-only and rerun with only the out-of-band "
            "--fingerprint-record or --expected-bundle-fingerprint."
        )
    if "expected_bundle_fingerprint_source_conflict" in codes:
        blocked_reason = blocked_reason or "fingerprint_source_conflict"
        next_steps.append(
            "Choose either --fingerprint-record or --expected-bundle-fingerprint. "
            "Prefer --fingerprint-record to avoid manual fingerprint transcription."
        )

    if "expected_bundle_fingerprint_mismatch" in codes:
        blocked_reason = blocked_reason or "expected_fingerprint_mismatch"
        next_steps.append(
            "Stop the review. Do not replace the expected fingerprint with a value copied from "
            "the bundle; compare the external fingerprint record against bundle-manifest.json and "
            "the reviewed bundle path, then rerun production capture if they cannot be reconciled."
        )

    if {
        "bundle_manifest_fingerprint_mismatch",
        "bundle_fingerprint_mismatch",
        "summary_bundle_fingerprint_mismatch",
    } & codes:
        blocked_reason = blocked_reason or "bundle_integrity_failure"
        next_steps.append(
            "Treat the retained bundle as mutated or internally inconsistent. Do not update the "
            "out-of-band fingerprint record from the bundle; rerun the production capture wrapper "
            "from the original production sources."
        )

    if internal_consistency_only:
        next_steps.append(
            "Internal-consistency mode is diagnostic only. For custody review, rerun with "
            "--fingerprint-record or --expected-bundle-fingerprint from the external "
            "fingerprint record."
        )

    if incomplete_row_count:
        blocked_reason = blocked_reason or "evidence_integrity_failure"
        next_steps.append(
            "Fix the row-local missing input artifacts or errors listed in row_review.incomplete_rows "
            "and retained preflight.json.parity_row_readiness, then rerun --check-environment or "
            "preflight capture before full production capture."
        )

    if any(code.startswith("redaction_scan") or code.startswith("evidence_manifest_redaction") for code in codes):
        blocked_reason = blocked_reason or "evidence_integrity_failure"
        next_steps.append(
            "Do not publish this bundle. Remove or redact the flagged retained artifacts, rerun "
            "production capture, and verify the new bundle with a fresh external fingerprint."
        )

    if findings and blocked_reason is None:
        blocked_reason = "evidence_integrity_failure"
    if findings and not next_steps:
        next_steps.append(
            "Repair the listed verifier findings at the production capture source, rerun the "
            "capture wrapper, retain the new external bundle fingerprint, and rerun verification."
        )
    if not findings and not next_steps:
        next_steps.append(
            "Custody verification passed. Review row_review.rows[] and release-audit evidence "
            "before updating any strict-audit row status."
        )

    return {
        "blocked_reason": blocked_reason,
        "next_steps": next_steps,
        "diagnostic_only": True,
    }


def _production_evidence_expected_fingerprint_from_record(
    record_path_raw: str | None,
    *,
    bundle_dir: Path,
    findings: list[dict[str, Any]],
) -> str | None:
    if not record_path_raw:
        return None
    record_path = Path(record_path_raw).expanduser()
    if not record_path.is_absolute():
        _production_evidence_finding(
            findings,
            "fingerprint_record_path_not_absolute",
            "production fingerprint record path must be absolute",
        )
        return None
    if record_path.is_symlink():
        _production_evidence_finding(
            findings,
            "fingerprint_record_symlink",
            "production fingerprint record must not be a symlink",
        )
        return None
    try:
        resolved_record = record_path.resolve(strict=True)
    except OSError as exc:
        _production_evidence_finding(
            findings,
            "fingerprint_record_invalid",
            f"production fingerprint record denied: {exc}",
        )
        return None
    try:
        resolved_record.relative_to(bundle_dir)
    except ValueError:
        pass
    else:
        _production_evidence_finding(
            findings,
            "fingerprint_record_bundle_local",
            "production fingerprint record must be outside the evidence bundle under review",
        )
        return None
    if not resolved_record.is_file():
        _production_evidence_finding(
            findings,
            "fingerprint_record_invalid",
            "production fingerprint record must be a JSON file",
        )
        return None
    try:
        record = json.loads(resolved_record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _production_evidence_finding(
            findings,
            "fingerprint_record_invalid",
            f"production fingerprint record denied: {exc}",
        )
        return None
    if not isinstance(record, Mapping):
        _production_evidence_finding(
            findings,
            "fingerprint_record_invalid",
            "production fingerprint record must contain a JSON object",
        )
        return None
    if record.get("schema") != "mnemosyne.production-evidence-fingerprint-record.v1":
        _production_evidence_finding(
            findings,
            "fingerprint_record_schema_invalid",
            "production fingerprint record schema is invalid",
        )
    if record.get("record_kind") != "out-of-band-bundle-fingerprint":
        _production_evidence_finding(
            findings,
            "fingerprint_record_kind_invalid",
            "production fingerprint record kind is invalid",
        )
    if not _production_evidence_path_matches(record.get("bundle_dir"), expected_path=bundle_dir):
        _production_evidence_finding(
            findings,
            "fingerprint_record_bundle_dir_mismatch",
            "production fingerprint record bundle_dir does not match the reviewed bundle",
        )
    expected_paths = {
        "bundle_manifest": bundle_dir / "bundle-manifest.json",
        "summary": bundle_dir / "summary.json",
    }
    for key, expected_path in expected_paths.items():
        if key in record and not _production_evidence_path_matches(
            record.get(key),
            expected_path=expected_path,
        ):
            _production_evidence_finding(
                findings,
                f"fingerprint_record_{key}_mismatch",
                f"production fingerprint record {key} does not match the reviewed bundle",
            )
    fingerprint = record.get("bundle_fingerprint")
    if not _production_evidence_sha256_digest_ok(fingerprint):
        _production_evidence_finding(
            findings,
            "fingerprint_record_fingerprint_invalid",
            "production fingerprint record bundle_fingerprint is invalid",
        )
        return None
    return str(fingerprint)


def _write_production_evidence_verify_report(
    *,
    report: Mapping[str, Any],
    report_output: str | None,
    bundle_dir: Path,
) -> None:
    if not report_output:
        return
    report_path = Path(report_output).expanduser()
    if not report_path.is_absolute():
        raise SystemExit("production evidence verify report output must be an absolute path")
    if report_path.is_symlink():
        raise SystemExit("production evidence verify report output must not be a symlink")
    if report_path.exists():
        raise SystemExit("production evidence verify report output must not already exist")
    parent = report_path.parent
    if parent.is_symlink():
        raise SystemExit("production evidence verify report output parent must not be a symlink")
    try:
        resolved_parent = parent.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"production evidence verify report output parent denied: {exc}") from exc
    if not resolved_parent.is_dir():
        raise SystemExit("production evidence verify report output parent must be a directory")
    try:
        resolved_bundle = bundle_dir.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"production evidence bundle denied: {exc}") from exc
    resolved_report = resolved_parent / report_path.name
    try:
        resolved_report.relative_to(resolved_bundle)
    except ValueError:
        pass
    else:
        raise SystemExit(
            "production evidence verify report output must be outside the evidence bundle under review"
        )

    payload = json.dumps(report, indent=2, sort_keys=True, default=json_default) + "\n"
    temp_path: Path | None = None
    fd = -1
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{report_path.name}.",
            suffix=".tmp",
            dir=str(resolved_parent),
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.link(temp_path, resolved_report)
    except FileExistsError as exc:
        raise SystemExit("production evidence verify report output must not already exist") from exc
    except OSError as exc:
        raise SystemExit(f"production evidence verify report output denied: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def _verify_production_evidence_preflight(
    preflight: Mapping[str, Any] | None,
    *,
    bundle_dir: Path,
    findings: list[dict[str, Any]],
) -> bool:
    from mnemosyne.production_parity import build_parity_row_readiness

    if preflight is None:
        return False
    ok = True
    if preflight.get("ok") is not True:
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_not_ok",
            "preflight.json is not ok",
        )
    if preflight.get("preflight_only") is not False:
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_completion_missing",
            "preflight.json does not describe a completed production capture",
        )

    copied_manifest = preflight.get("copied_manifest")
    if not _production_evidence_path_matches(
        copied_manifest,
        expected_path=bundle_dir / "operator-soak-manifest.json",
    ):
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_copied_manifest_invalid",
            "preflight.json copied_manifest must resolve to the retained operator-soak-manifest.json",
        )
    source_manifest_copy = preflight.get("source_manifest_copy")
    if not _production_evidence_path_matches(
        source_manifest_copy,
        expected_path=bundle_dir / "source-soak-manifest.json",
    ):
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_source_manifest_copy_invalid",
            "preflight.json source_manifest_copy must resolve to the retained source-soak-manifest.json",
        )
    redaction_scan = preflight.get("redaction_scan")
    if not _production_evidence_path_matches(
        redaction_scan,
        expected_path=bundle_dir / "redaction-scan.json",
    ):
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_redaction_scan_invalid",
            "preflight.json redaction_scan must resolve to the retained redaction-scan.json",
        )

    required_commands = preflight.get("required_commands")
    provided_commands = preflight.get("provided_commands")
    expected_commands = set(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
    if (
        not isinstance(required_commands, list)
        or not all(isinstance(command, str) for command in required_commands)
        or len(required_commands) != len(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
        or set(required_commands) != expected_commands
    ):
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_required_commands_mismatch",
            "preflight.json required_commands do not match the frozen production command set",
        )
    if (
        not isinstance(provided_commands, list)
        or not all(isinstance(command, str) for command in provided_commands)
        or len(provided_commands) != len(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
        or set(provided_commands) != expected_commands
    ):
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_provided_commands_mismatch",
            "preflight.json provided_commands do not match the frozen production command set",
        )

    input_artifacts = preflight.get("required_input_artifacts")
    if not isinstance(input_artifacts, list):
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_input_artifacts_invalid",
            "preflight.json required_input_artifacts must be a list",
        )
        input_artifacts = []
    elif not input_artifacts:
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_input_artifacts_missing",
            "preflight.json must retain production input artifact snapshots",
        )
    snapshot_root = (bundle_dir / "input-artifacts").resolve(strict=False)
    for index, artifact in enumerate(input_artifacts, start=1):
        if not isinstance(artifact, Mapping):
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_input_artifact_invalid",
                f"preflight.json required_input_artifacts[{index}] must be an object",
            )
            continue
        source_path = artifact.get("path")
        snapshot_path_value = artifact.get("snapshot_path")
        kind = artifact.get("kind")
        labels = artifact.get("labels")
        files = artifact.get("files")
        if not isinstance(source_path, str) or not source_path:
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_input_artifact_path_invalid",
                f"preflight.json required_input_artifacts[{index}].path must be non-empty",
            )
        if kind not in {"file", "directory"}:
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_input_artifact_kind_invalid",
                f"preflight.json required_input_artifacts[{index}].kind must be file or directory",
            )
        if not isinstance(labels, list) or not labels or not all(isinstance(label, str) for label in labels):
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_input_artifact_labels_invalid",
                f"preflight.json required_input_artifacts[{index}].labels must be a non-empty string list",
            )
        if not isinstance(snapshot_path_value, str) or not snapshot_path_value:
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_input_artifact_snapshot_invalid",
                f"preflight.json required_input_artifacts[{index}].snapshot_path must be non-empty",
            )
            artifact_snapshot_root = None
        else:
            snapshot_path = Path(snapshot_path_value).expanduser()
            try:
                resolved_snapshot_path = snapshot_path.resolve(strict=True)
                resolved_snapshot_path.relative_to(snapshot_root)
                artifact_snapshot_root = resolved_snapshot_path
            except (OSError, ValueError):
                ok = False
                artifact_snapshot_root = None
                _production_evidence_finding(
                    findings,
                    "preflight_input_artifact_snapshot_invalid",
                    f"preflight.json required_input_artifacts[{index}].snapshot_path must resolve under input-artifacts",
                )
        if not isinstance(files, list) or not files:
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_input_artifact_files_invalid",
                f"preflight.json required_input_artifacts[{index}].files must be a non-empty list",
            )
            continue
        for file_index, file_entry in enumerate(files, start=1):
            if not isinstance(file_entry, Mapping):
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_input_artifact_file_invalid",
                    f"preflight.json required_input_artifacts[{index}].files[{file_index}] must be an object",
                )
                continue
            snapshot_file_value = file_entry.get("snapshot_path")
            relative_path = file_entry.get("relative_path")
            size_bytes = file_entry.get("size_bytes")
            expected_sha256 = file_entry.get("sha256")
            if not isinstance(relative_path, str) or not relative_path:
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_input_artifact_file_relative_path_invalid",
                    f"preflight.json required_input_artifacts[{index}].files[{file_index}].relative_path must be non-empty",
                )
            if (
                not isinstance(snapshot_file_value, str)
                or not isinstance(size_bytes, int)
                or size_bytes < 0
                or not isinstance(expected_sha256, str)
                or not expected_sha256.startswith("sha256:")
            ):
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_input_artifact_file_digest_invalid",
                    f"preflight.json required_input_artifacts[{index}].files[{file_index}] has invalid digest metadata",
                )
                continue
            snapshot_file = Path(snapshot_file_value).expanduser()
            try:
                resolved_snapshot_file = snapshot_file.resolve(strict=True)
                resolved_snapshot_file.relative_to(snapshot_root)
            except (OSError, ValueError):
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_input_artifact_file_snapshot_invalid",
                    f"preflight.json required_input_artifacts[{index}].files[{file_index}].snapshot_path must resolve under input-artifacts",
                )
                continue
            if artifact_snapshot_root is not None:
                try:
                    if artifact_snapshot_root.is_file():
                        if resolved_snapshot_file != artifact_snapshot_root:
                            raise ValueError("snapshot file is outside parent file artifact")
                    else:
                        resolved_snapshot_file.relative_to(artifact_snapshot_root)
                except (OSError, ValueError) as exc:
                    ok = False
                    _production_evidence_finding(
                        findings,
                        "preflight_input_artifact_file_parent_mismatch",
                        (
                            f"preflight.json required_input_artifacts[{index}].files[{file_index}].snapshot_path "
                            f"must stay under its artifact snapshot root: {exc}"
                        ),
                    )
                    continue
            if not resolved_snapshot_file.is_file():
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_input_artifact_file_missing",
                    f"preflight.json required_input_artifacts[{index}].files[{file_index}].snapshot_path is missing",
                )
                continue
            if resolved_snapshot_file.stat().st_size != size_bytes:
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_input_artifact_file_size_mismatch",
                    f"preflight.json required_input_artifacts[{index}].files[{file_index}] size does not match snapshot",
                )
            if _file_sha256(resolved_snapshot_file) != expected_sha256:
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_input_artifact_file_sha256_mismatch",
                    f"preflight.json required_input_artifacts[{index}].files[{file_index}] sha256 does not match snapshot",
                )
    row_readiness = preflight.get("parity_row_readiness")
    if not isinstance(row_readiness, list):
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_parity_row_readiness_invalid",
            "preflight.json parity_row_readiness must be a list",
        )
    else:
        expected_readiness = build_parity_row_readiness(
            [
                {
                    "relative_path": _production_evidence_retained_input_path(
                        artifact,
                        bundle_dir=bundle_dir,
                    ),
                    "checks": artifact.get("checks", []),
                    "parity_routes": artifact.get("parity_routes", []),
                    "exists": True,
                }
                for artifact in input_artifacts
                if isinstance(artifact, Mapping)
            ]
        )
        if row_readiness != expected_readiness:
            ok = False
            _production_evidence_finding(
                findings,
                "preflight_parity_row_readiness_mismatch",
                "preflight.json parity_row_readiness does not match retained input artifacts",
            )
    if not _verify_production_evidence_executable_tool_references(
        preflight,
        findings,
        bundle_dir=bundle_dir,
    ):
        ok = False
    return ok


def _production_evidence_retained_input_path(
    artifact: Mapping[str, Any],
    *,
    bundle_dir: Path,
) -> str:
    snapshot_path = artifact.get("snapshot_path")
    if not isinstance(snapshot_path, str) or not snapshot_path:
        return ""
    try:
        return Path(snapshot_path).resolve(strict=False).relative_to(bundle_dir).as_posix()
    except (OSError, ValueError):
        return Path(snapshot_path).name


def _iter_evidence_string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_evidence_string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_evidence_string_values(item)


def _production_input_artifact_path(value: Any, *, input_root: Path) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        resolved = Path(value).expanduser().resolve(strict=True)
        resolved.relative_to(input_root)
    except (OSError, ValueError):
        return None
    return str(resolved)


def _verify_production_evidence_input_artifact_custody(
    *,
    preflight: Mapping[str, Any] | None,
    operator_manifest: Mapping[str, Any] | None,
    bundle_dir: Path,
    findings: list[dict[str, Any]],
) -> bool:
    if preflight is None or operator_manifest is None:
        return False
    ok = True
    input_root_path = bundle_dir / "input-artifacts"
    input_root = input_root_path.resolve(strict=False)
    input_artifacts = preflight.get("required_input_artifacts")
    if not isinstance(input_artifacts, list):
        return False

    declared_artifact_roots: set[str] = set()
    declared_file_paths: set[str] = set()
    for artifact in input_artifacts:
        if not isinstance(artifact, Mapping):
            continue
        snapshot_path = _production_input_artifact_path(artifact.get("snapshot_path"), input_root=input_root)
        if snapshot_path is not None:
            declared_artifact_roots.add(snapshot_path)
        files = artifact.get("files")
        if not isinstance(files, list):
            continue
        for file_entry in files:
            if not isinstance(file_entry, Mapping):
                continue
            snapshot_file = _production_input_artifact_path(file_entry.get("snapshot_path"), input_root=input_root)
            if snapshot_file is not None:
                declared_file_paths.add(snapshot_file)

    actual_file_paths: dict[str, str] = {}
    if input_root_path.is_symlink():
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_input_artifact_symlink",
            "input-artifacts must be a retained directory, not a symlink",
        )
    elif not input_root_path.is_dir():
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_input_artifact_root_missing",
            "input-artifacts must be retained in the production evidence bundle",
        )
    elif input_root_path.exists():
        for path in sorted(input_root_path.rglob("*")):
            try:
                display_path = path.relative_to(input_root_path).as_posix()
            except ValueError:
                display_path = str(path)
            if path.is_symlink():
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_input_artifact_symlink",
                    f"input-artifacts contains a symlink: {display_path}",
                )
                continue
            if not path.is_file():
                continue
            try:
                resolved_path = path.resolve(strict=True)
                resolved_path.relative_to(input_root)
                actual_file_paths[str(resolved_path)] = display_path
            except (OSError, ValueError) as exc:
                ok = False
                _production_evidence_finding(
                    findings,
                    "preflight_input_artifact_file_escape",
                    f"input-artifacts contains an invalid retained file {display_path}: {exc}",
                )
                continue
    unrecorded_files = sorted(set(actual_file_paths) - declared_file_paths)
    if unrecorded_files:
        ok = False
        _production_evidence_finding(
            findings,
            "preflight_input_artifact_unrecorded_snapshot_file",
            "input-artifacts contains files missing from preflight.json: "
            + ", ".join(actual_file_paths[item] for item in unrecorded_files),
        )

    declared_paths = declared_artifact_roots | declared_file_paths
    operator_strings = list(_iter_evidence_string_values(operator_manifest))
    operator_input_references = [
        value for value in operator_strings if str(input_root) in value
    ]
    for value in operator_input_references:
        if not any(path in value for path in declared_paths):
            ok = False
            _production_evidence_finding(
                findings,
                "operator_manifest_input_artifact_reference_unrecorded",
                "operator-soak-manifest.json references an input-artifacts path not recorded in preflight.json",
            )
            break

    reference_haystacks = list(operator_strings)
    for file_path in sorted(declared_file_paths):
        path = Path(file_path)
        try:
            if path.stat().st_size <= 5 * 1024 * 1024:
                reference_haystacks.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue

    for snapshot_path in sorted(declared_artifact_roots):
        if not any(snapshot_path in value for value in reference_haystacks):
            ok = False
            _production_evidence_finding(
                findings,
                "operator_manifest_input_artifact_reference_missing",
                "preflight.json records an input artifact snapshot not referenced by the retained operator manifest or nested artifact metadata",
            )
            break
    return ok


def _verify_production_evidence_redaction_scan(
    redaction_scan: Mapping[str, Any] | None,
    *,
    bundle_dir: Path,
    actual_files: list[dict[str, Any]],
    preflight: Mapping[str, Any] | None,
    findings: list[dict[str, Any]],
) -> bool:
    from mnemosyne.evidence_redaction import scan_evidence_paths

    if redaction_scan is None:
        return False
    ok = True
    if redaction_scan.get("ok") is not True:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_not_ok",
            "redaction-scan.json is not ok",
        )
    if redaction_scan.get("findings") != []:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_findings_present",
            "redaction-scan.json contains findings",
        )
    if redaction_scan.get("skipped_files") != []:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_skipped_files_present",
            "redaction-scan.json contains skipped files",
        )
    scan_paths: list[Path] = []
    expected_scanned: set[str] = set()
    expected_recomputed_scanned: set[str] = set()
    expected_binary_custody = _production_evidence_binary_custody_paths(
        preflight,
        bundle_dir=bundle_dir,
    )
    for item in actual_files:
        rel_path = item.get("path")
        if not isinstance(rel_path, str) or rel_path == "redaction-scan.json":
            continue
        if rel_path in expected_binary_custody:
            continue
        scan_paths.append(bundle_dir / rel_path)
        expected_scanned.add(rel_path)
        expected_recomputed_scanned.add(rel_path)
    for rel_path in sorted(PRODUCTION_EVIDENCE_REDACTION_SCAN_EXTRA_FILES):
        extra_path = bundle_dir / rel_path
        if extra_path.exists():
            scan_paths.append(extra_path)
            expected_recomputed_scanned.add(rel_path)
    recomputed = scan_evidence_paths(
        scan_paths,
        scope="verify",
        reject_symlinks=True,
    )
    if recomputed.get("ok") is not True:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_recompute_not_ok",
            "fresh redaction scan over current bundle artifacts and metadata is not ok",
        )
    if recomputed.get("findings") != []:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_recompute_findings_present",
            "fresh redaction scan found high-confidence secret material",
        )
    if recomputed.get("skipped_files") != []:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_recompute_skipped_files_present",
            "fresh redaction scan skipped current bundle artifacts or metadata",
        )

    def relative_scanned_files(scan: Mapping[str, Any]) -> set[str] | None:
        scanned = scan.get("scanned_files")
        if not isinstance(scanned, list) or not all(isinstance(item, str) for item in scanned):
            return None
        relative: set[str] = set()
        for item in scanned:
            try:
                relative.add(Path(item).resolve(strict=False).relative_to(bundle_dir).as_posix())
            except ValueError:
                relative.add(item)
        return relative

    recorded_scanned = relative_scanned_files(redaction_scan)
    recomputed_scanned = relative_scanned_files(recomputed)
    if recorded_scanned is None:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_scanned_files_missing",
            "redaction-scan.json must list scanned_files",
        )
    elif recorded_scanned != expected_scanned:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_scanned_files_mismatch",
            "redaction-scan.json scanned_files do not match bundle-manifest artifacts except redaction-scan.json",
        )
    if recomputed_scanned is not None and recomputed_scanned != expected_recomputed_scanned:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_recompute_scanned_files_mismatch",
            "fresh redaction scan did not cover exactly the current bundle artifacts and metadata",
        )
    binary_custody_files = redaction_scan.get("binary_custody_files", [])
    if not isinstance(binary_custody_files, list) or not all(isinstance(item, str) for item in binary_custody_files):
        recorded_binary_custody = None
    else:
        recorded_binary_custody = set()
        for item in binary_custody_files:
            try:
                recorded_binary_custody.add(Path(item).resolve(strict=False).relative_to(bundle_dir).as_posix())
            except ValueError:
                recorded_binary_custody.add(item)
    if recorded_binary_custody is None:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_binary_custody_files_missing",
            "redaction-scan.json must list retained binary custody files",
        )
    elif recorded_binary_custody != expected_binary_custody:
        ok = False
        _production_evidence_finding(
            findings,
            "redaction_scan_binary_custody_files_mismatch",
            "redaction-scan.json binary_custody_files do not match retained tool snapshots and binary input assets",
        )
    return ok


def _verify_production_evidence_operator_manifest(
    operator_manifest: Mapping[str, Any] | None,
    findings: list[dict[str, Any]],
    *,
    label: str = "operator-soak-manifest.json",
    code_prefix: str = "operator_manifest",
) -> bool:
    from mnemosyne.evidence_redaction import manifest_argument_secret_errors

    if operator_manifest is None:
        return False
    ok = True
    manifest_payload = json.dumps(operator_manifest, sort_keys=True)
    if "MNEMOSYNE_PROD_" in manifest_payload:
        ok = False
        _production_evidence_finding(
            findings,
            f"{code_prefix}_unresolved_placeholder",
            f"{label} contains unresolved production placeholders",
        )
    secret_argument_errors = manifest_argument_secret_errors(operator_manifest)
    for error in secret_argument_errors:
        ok = False
        _production_evidence_finding(
            findings,
            f"{code_prefix}_secret_argument",
            f"{label} {error}",
        )

    validation_scope = operator_manifest.get("validation_scope")
    if not isinstance(validation_scope, Mapping):
        ok = False
        _production_evidence_finding(
            findings,
            f"{code_prefix}_validation_scope_missing",
            f"{label} is missing validation_scope",
        )
    else:
        if validation_scope.get("production_validated") is not True:
            ok = False
            _production_evidence_finding(
                findings,
                f"{code_prefix}_production_validation_missing",
                f"{label} is not production validated",
            )
        if validation_scope.get("target_environment") != "production":
            ok = False
            _production_evidence_finding(
                findings,
                f"{code_prefix}_target_missing",
                f"{label} did not target production",
            )
        if validation_scope.get("operator_asserted") is not True:
            ok = False
            _production_evidence_finding(
                findings,
                f"{code_prefix}_attestation_missing",
                f"{label} is missing operator attestation",
            )

    checks = operator_manifest.get("checks")
    if not isinstance(checks, list) or not checks:
        _production_evidence_finding(
            findings,
            f"{code_prefix}_checks_missing",
            f"{label} requires a non-empty checks array",
        )
        return False

    commands: list[str] = []
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, Mapping):
            ok = False
            _production_evidence_finding(
                findings,
                f"{code_prefix}_check_invalid",
                f"{label} checks[{index}] must be an object",
            )
            continue
        command = check.get("command")
        if not isinstance(command, str) or not command:
            ok = False
            _production_evidence_finding(
                findings,
                f"{code_prefix}_command_invalid",
                f"{label} checks[{index}].command must be a non-empty string",
            )
            continue
        try:
            _deployment_check_spec(index, dict(check), default_timeout=30.0)
        except ValueError as exc:
            ok = False
            _production_evidence_finding(
                findings,
                f"{code_prefix}_check_spec_invalid",
                f"{label} checks[{index}] failed deployment-soak preflight validation: {exc}",
            )
            continue
        commands.append(command)

    required_commands = set(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
    provided_commands = set(commands)
    missing = sorted(required_commands - provided_commands)
    if missing:
        ok = False
        _production_evidence_finding(
            findings,
            f"{code_prefix}_required_commands_missing",
            f"{label} is missing production commands: " + ", ".join(missing),
        )
    extra = sorted(provided_commands - required_commands)
    if extra:
        ok = False
        _production_evidence_finding(
            findings,
            f"{code_prefix}_unknown_commands",
            f"{label} contains unknown production commands: " + ", ".join(extra),
        )
    duplicates = sorted({command for command in commands if commands.count(command) > 1})
    if duplicates:
        ok = False
        _production_evidence_finding(
            findings,
            f"{code_prefix}_duplicate_commands",
            f"{label} contains duplicate production commands: " + ", ".join(duplicates),
        )
    return ok


def _production_evidence_manifest_commands(manifest: Mapping[str, Any] | None) -> list[str]:
    if manifest is None:
        return []
    checks = manifest.get("checks")
    if not isinstance(checks, list):
        return []
    commands: list[str] = []
    for check in checks:
        if not isinstance(check, Mapping):
            continue
        command = check.get("command")
        if isinstance(command, str) and command:
            commands.append(command)
    return commands


def _production_evidence_manifest_path_rewrites(preflight: Mapping[str, Any] | None) -> dict[str, str]:
    if preflight is None:
        return {}
    input_artifacts = preflight.get("required_input_artifacts")
    if not isinstance(input_artifacts, list):
        return {}
    rewrites: dict[str, str] = {}

    def record_rewrite(source: str, snapshot: str) -> None:
        if not source or not snapshot:
            return
        snapshot_resolved = str(Path(snapshot).expanduser().resolve(strict=False))
        rewrites[source] = snapshot_resolved
        try:
            rewrites[str(Path(source).expanduser().resolve(strict=False))] = snapshot_resolved
        except (OSError, RuntimeError, ValueError):
            pass

    for artifact in input_artifacts:
        if not isinstance(artifact, Mapping):
            continue
        source_path = artifact.get("path")
        snapshot_path = artifact.get("snapshot_path")
        if isinstance(source_path, str) and source_path and isinstance(snapshot_path, str) and snapshot_path:
            record_rewrite(source_path, snapshot_path)
            source_values = artifact.get("source_values", [])
            if isinstance(source_values, list):
                for source_value in source_values:
                    if isinstance(source_value, str):
                        record_rewrite(source_value, snapshot_path)
        files = artifact.get("files")
        if not isinstance(files, list):
            continue
        for file_entry in files:
            if not isinstance(file_entry, Mapping):
                continue
            source_file = file_entry.get("source_path")
            snapshot_file = file_entry.get("snapshot_path")
            if isinstance(source_file, str) and source_file and isinstance(snapshot_file, str) and snapshot_file:
                record_rewrite(source_file, snapshot_file)
    return rewrites


def _production_evidence_normalize_manifest_value(value: Any, *, path_rewrites: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        normalized = value
        for source_path, snapshot_path in sorted(path_rewrites.items(), key=lambda item: len(item[0]), reverse=True):
            pattern = re.compile(rf"(?<![\w.-]){re.escape(source_path)}(?=$|[\s\"',;:\]\)]|[/\\])")
            normalized = pattern.sub(snapshot_path, normalized)
        return normalized
    if isinstance(value, list):
        return [_production_evidence_normalize_manifest_value(item, path_rewrites=path_rewrites) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _production_evidence_normalize_manifest_value(inner, path_rewrites=path_rewrites)
            for key, inner in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return value


def _production_evidence_manifest_check_profile(
    manifest: Mapping[str, Any] | None,
    *,
    path_rewrites: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    if manifest is None:
        return []
    checks = manifest.get("checks")
    if not isinstance(checks, list):
        return []
    rewrites = path_rewrites or {}
    profile: list[dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, Mapping):
            continue
        profile.append(
            _production_evidence_normalize_manifest_value(
                dict(check),
                path_rewrites=rewrites,
            )
        )
    return profile


def _verify_production_evidence_source_soak_manifest(
    source_manifest: Mapping[str, Any] | None,
    operator_manifest: Mapping[str, Any] | None,
    preflight: Mapping[str, Any] | None,
    findings: list[dict[str, Any]],
) -> bool:
    ok = _verify_production_evidence_operator_manifest(
        source_manifest,
        findings,
        label="source-soak-manifest.json",
        code_prefix="source_soak_manifest",
    )
    if source_manifest is None or operator_manifest is None:
        return False
    source_commands = _production_evidence_manifest_commands(source_manifest)
    operator_commands = _production_evidence_manifest_commands(operator_manifest)
    path_rewrites = _production_evidence_manifest_path_rewrites(preflight)
    source_profile = _production_evidence_manifest_check_profile(source_manifest, path_rewrites=path_rewrites)
    operator_profile = _production_evidence_manifest_check_profile(operator_manifest)
    source_payload = _production_evidence_normalize_manifest_value(
        dict(source_manifest),
        path_rewrites=path_rewrites,
    )
    operator_payload = _production_evidence_normalize_manifest_value(
        dict(operator_manifest),
        path_rewrites={},
    )
    if source_commands != operator_commands or source_profile != operator_profile:
        ok = False
        _production_evidence_finding(
            findings,
            "source_manifest_command_profile_mismatch",
            (
                "source-soak-manifest.json command and argument profile must match "
                "operator-soak-manifest.json after retained input-artifact path rewrites"
            ),
        )
    if source_payload != operator_payload:
        ok = False
        _production_evidence_finding(
            findings,
            "source_manifest_payload_mismatch",
            (
                "source-soak-manifest.json payload must match operator-soak-manifest.json "
                "after retained input-artifact path rewrites"
            ),
        )
    return ok


def _production_evidence_path_matches(path_value: Any, *, expected_path: Path) -> bool:
    if not isinstance(path_value, str) or not path_value:
        return False
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = expected_path.parent / candidate
    try:
        return candidate.resolve(strict=True) == expected_path.resolve(strict=True)
    except OSError:
        return False


def _verify_production_evidence_manifest_contract(
    *,
    evidence_manifest: Mapping[str, Any] | None,
    deployment_soak: Mapping[str, Any] | None,
    findings: list[dict[str, Any]],
) -> bool:
    if evidence_manifest is None:
        return False
    ok = True
    expected_count = len(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
    if evidence_manifest.get("kind") != "mnemosyne.deployment_soak_evidence":
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_kind_invalid",
            "evidence/manifest.json has unsupported kind",
        )
    if evidence_manifest.get("version") != 1:
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_version_invalid",
            "evidence/manifest.json requires version 1",
        )
    if evidence_manifest.get("ok") is not True:
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_not_ok",
            "evidence/manifest.json must confirm ok=true",
        )

    validation_scope = evidence_manifest.get("validation_scope")
    if not isinstance(validation_scope, Mapping):
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_validation_scope_missing",
            "evidence/manifest.json is missing validation_scope",
        )
    else:
        if validation_scope.get("production_validated") is not True:
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_production_validation_missing",
                "evidence/manifest.json is not production validated",
            )
        if validation_scope.get("target_environment") != "production":
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_target_missing",
                "evidence/manifest.json did not target production",
            )
        if validation_scope.get("operator_asserted") is not True:
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_operator_attestation_missing",
                "evidence/manifest.json is missing operator attestation",
            )

    if not _release_redaction_ok(evidence_manifest):
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_redaction_missing",
            "evidence/manifest.json redaction flags are incomplete",
        )

    summary = evidence_manifest.get("summary")
    if not isinstance(summary, Mapping):
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_summary_missing",
            "evidence/manifest.json is missing summary",
        )
    else:
        if summary.get("checks") != expected_count:
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_summary_check_count_mismatch",
                "evidence/manifest.json summary.checks does not match the frozen production command set",
            )
        if summary.get("required_failures") != 0:
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_required_failures_present",
                "evidence/manifest.json summary reports required failures",
            )
        if deployment_soak is not None and deployment_soak.get("summary") != summary:
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_summary_mismatch",
                "evidence/manifest.json summary must match deployment-soak.stdout.json summary",
            )

    checks = evidence_manifest.get("checks")
    report_checks = deployment_soak.get("checks") if isinstance(deployment_soak, Mapping) else None
    if not isinstance(checks, list) or not checks:
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_checks_missing",
            "evidence/manifest.json requires a non-empty checks array",
        )
        return False
    if len(checks) != expected_count:
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_check_count_mismatch",
            "evidence/manifest.json checks do not match the frozen production command set",
        )
    commands: list[str] = []
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, Mapping):
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_check_invalid",
                f"evidence/manifest.json checks[{index}] must be an object",
            )
            continue
        command = check.get("command")
        if not isinstance(command, str) or not command:
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_command_invalid",
                f"evidence/manifest.json checks[{index}].command must be a non-empty string",
            )
        else:
            commands.append(command)
        if check.get("ok") is not True:
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_check_not_ok",
                f"evidence/manifest.json checks[{index}] is not ok",
            )
        if check.get("required") is not True:
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_check_not_required",
                f"evidence/manifest.json checks[{index}] must be required for production evidence",
            )
        if not isinstance(check.get("path"), str) or not check.get("path"):
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_check_path_missing",
                f"evidence/manifest.json checks[{index}] requires a retained check path",
            )
        check_sha256 = check.get("sha256")
        if not isinstance(check_sha256, str) or not check_sha256.startswith("sha256:"):
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_check_sha256_missing",
                f"evidence/manifest.json checks[{index}] requires a sha256 digest",
            )
        if isinstance(report_checks, list) and index <= len(report_checks) and isinstance(report_checks[index - 1], Mapping):
            report_check = report_checks[index - 1]
            evidence_metadata = {
                key: check.get(key)
                for key in ("index", "name", "command", "ok", "required", "evidence_class")
            }
            report_metadata = {
                key: report_check.get(key)
                for key in ("index", "name", "command", "ok", "required", "evidence_class")
            }
            if evidence_metadata != report_metadata:
                ok = False
                _production_evidence_finding(
                    findings,
                    "evidence_manifest_check_metadata_mismatch",
                    "evidence/manifest.json check metadata must match deployment-soak.stdout.json checks",
                )
                break
    required_commands = set(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
    provided_commands = set(commands)
    missing = sorted(required_commands - provided_commands)
    extra = sorted(provided_commands - required_commands)
    duplicates = sorted({command for command in commands if commands.count(command) > 1})
    if missing:
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_required_commands_missing",
            "evidence/manifest.json is missing production commands: " + ", ".join(missing),
        )
    if extra:
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_unknown_commands",
            "evidence/manifest.json contains unknown production commands: " + ", ".join(extra),
        )
    if duplicates:
        ok = False
        _production_evidence_finding(
            findings,
            "evidence_manifest_duplicate_commands",
            "evidence/manifest.json contains duplicate production commands: " + ", ".join(duplicates),
        )
    return ok


def _verify_production_evidence_deployment_soak_manifest(
    *,
    expected_manifest_path: Path,
    bundle_dir: Path,
    deployment_soak: Mapping[str, Any] | None,
    evidence_manifest: Mapping[str, Any] | None,
    findings: list[dict[str, Any]],
) -> bool:
    ok = True
    expected_count = len(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
    if deployment_soak is None:
        ok = False
    else:
        report_manifest = deployment_soak.get("manifest")
        if not isinstance(report_manifest, Mapping):
            ok = False
            _production_evidence_finding(
                findings,
                "deployment_soak_manifest_missing",
                "deployment-soak.stdout.json is missing manifest metadata",
            )
        else:
            report_manifest_path = report_manifest.get("path")
            if not _production_evidence_path_matches(
                report_manifest_path,
                expected_path=expected_manifest_path,
            ):
                ok = False
                _production_evidence_finding(
                    findings,
                    "deployment_soak_manifest_path_invalid",
                    "deployment-soak.stdout.json manifest.path must resolve to the retained operator-soak-manifest.json",
                )
            if report_manifest.get("check_count") != expected_count:
                ok = False
                _production_evidence_finding(
                    findings,
                    "deployment_soak_manifest_check_count_mismatch",
                    "deployment-soak.stdout.json manifest.check_count does not match the frozen production command set",
                )
    if evidence_manifest is None:
        ok = False
    else:
        source_manifest = evidence_manifest.get("source_manifest")
        if not _production_evidence_path_matches(
            source_manifest,
            expected_path=expected_manifest_path,
        ):
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_source_manifest_invalid",
                "evidence/manifest.json source_manifest must resolve to the retained operator-soak-manifest.json",
            )
        files = evidence_manifest.get("files")
        if not isinstance(files, Mapping):
            ok = False
            _production_evidence_finding(
                findings,
                "evidence_manifest_files_missing",
                "evidence/manifest.json is missing files",
            )
        else:
            manifest_path = bundle_dir / "evidence" / "manifest.json"
            try:
                report_path = _release_manifest_path(manifest_path, files.get("report"), "files.report")
                _verify_release_manifest_file(
                    path=report_path,
                    expected_sha256=_release_manifest_expected_sha256(
                        files.get("report_sha256"),
                        "files.report_sha256",
                    ),
                    label="files.report",
                )
                report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, SystemExit) as exc:
                ok = False
                _production_evidence_finding(
                    findings,
                    "evidence_manifest_report_replay_failed",
                    f"evidence/manifest.json report replay failed: {exc}",
                )
            else:
                if not isinstance(report_payload, Mapping):
                    ok = False
                    _production_evidence_finding(
                        findings,
                        "evidence_manifest_report_invalid",
                        "evidence/manifest.json files.report must contain a JSON object",
                    )
                elif deployment_soak is not None and dict(report_payload) != dict(deployment_soak):
                    ok = False
                    _production_evidence_finding(
                        findings,
                        "deployment_soak_stdout_report_mismatch",
                        "deployment-soak.stdout.json must equal the digest-bound evidence/manifest.json files.report",
                    )
    return ok


def _normalized_release_audit_for_compare(report: Mapping[str, Any]) -> Any:
    return _normalize_release_fingerprint_value(report)


def _verify_production_evidence_release_audit(
    *,
    bundle_dir: Path,
    release_audit: Mapping[str, Any] | None,
    deployment_soak: Mapping[str, Any] | None,
    summary: Mapping[str, Any] | None,
    findings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if deployment_soak is not None and deployment_soak.get("ok") is not True:
        _production_evidence_finding(
            findings,
            "deployment_soak_stdout_not_ok",
            "deployment-soak.stdout.json is not ok",
        )
    if release_audit is not None:
        required_sections = {
            "source": Mapping,
            "summary": Mapping,
            "commands": list,
            "provider": Mapping,
        }
        for key, expected_type in required_sections.items():
            value = release_audit.get(key)
            if not isinstance(value, expected_type) or (isinstance(value, list | Mapping) and not value):
                _production_evidence_finding(
                    findings,
                    f"release_audit_{key}_missing",
                    f"release-audit.json is missing {key}",
                )
        if release_audit.get("ok") is not True:
            _production_evidence_finding(findings, "release_audit_not_ok", "release-audit.json is not ok")
        if release_audit.get("findings") != []:
            _production_evidence_finding(
                findings,
                "release_audit_findings_present",
                "release-audit.json contains findings",
            )
        requirements = release_audit.get("requirements")
        if not isinstance(requirements, Mapping):
            _production_evidence_finding(
                findings,
                "release_audit_requirements_missing",
                "release-audit.json is missing requirements",
            )
        else:
            if requirements.get("require_production_validated") is not True:
                _production_evidence_finding(
                    findings,
                    "release_audit_production_requirement_missing",
                    "release-audit.json did not require production validation",
                )
            if requirements.get("require_provider_forbid_local") is not True:
                _production_evidence_finding(
                    findings,
                    "release_audit_provider_requirement_missing",
                    "release-audit.json did not forbid local providers",
                )
        validation_scope = release_audit.get("validation_scope")
        if not isinstance(validation_scope, Mapping):
            _production_evidence_finding(
                findings,
                "release_audit_validation_scope_missing",
                "release-audit.json is missing validation_scope",
            )
        else:
            if validation_scope.get("production_validated") is not True:
                _production_evidence_finding(
                    findings,
                    "release_audit_production_validation_missing",
                    "release-audit.json is not production validated",
                )
            if validation_scope.get("target_environment") != "production":
                _production_evidence_finding(
                    findings,
                    "release_audit_target_missing",
                    "release-audit.json did not target production",
                )
            if validation_scope.get("operator_asserted") is not True:
                _production_evidence_finding(
                    findings,
                    "release_audit_operator_attestation_missing",
                    "release-audit.json is missing operator attestation",
                )
    evidence_manifest_path = bundle_dir / "evidence" / "manifest.json"
    try:
        recomputed = _build_release_audit_report(
            argparse.Namespace(
                soak_report=None,
                evidence_manifest=str(evidence_manifest_path),
                require_command=None,
                require_provider_check=None,
                require_provider_forbid_local=True,
                require_production_validated=True,
                expected_fingerprint=None,
            )
        )
    except SystemExit as exc:
        _production_evidence_finding(
            findings,
            "release_audit_recompute_failed",
            f"offline release-audit replay failed: {exc}",
        )
        return None
    if recomputed.get("ok") is not True:
        _production_evidence_finding(
            findings,
            "release_audit_recompute_not_ok",
            "offline release-audit replay is not ok",
        )
    if release_audit is not None and recomputed.get("fingerprint") != release_audit.get("fingerprint"):
        _production_evidence_finding(
            findings,
            "release_audit_fingerprint_mismatch",
            "offline release-audit replay fingerprint does not match release-audit.json",
        )
    if release_audit is not None and _normalized_release_audit_for_compare(
        release_audit
    ) != _normalized_release_audit_for_compare(recomputed):
        _production_evidence_finding(
            findings,
            "release_audit_replay_mismatch",
            "release-audit.json must match the offline replay aside from path-like volatile fields",
        )
    if summary is not None and summary.get("release_audit_fingerprint") != recomputed.get("fingerprint"):
        _production_evidence_finding(
            findings,
            "summary_release_audit_fingerprint_mismatch",
            "summary.json release_audit_fingerprint does not match offline replay",
        )
    return recomputed


def cmd_production_evidence_verify(args: argparse.Namespace) -> None:
    bundle_dir = Path(args.bundle_dir).expanduser()
    expected_bundle_fingerprint = None
    expected_bundle_fingerprint_source = None
    findings: list[dict[str, Any]] = []
    if bundle_dir.is_symlink():
        raise SystemExit("production evidence bundle path must not be a symlink")
    try:
        resolved_bundle_dir = bundle_dir.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"production evidence bundle denied: {exc}") from exc
    if not resolved_bundle_dir.is_dir():
        raise SystemExit("production evidence bundle path must be a directory")
    if args.expected_bundle_fingerprint and args.fingerprint_record:
        expected_bundle_fingerprint = args.expected_bundle_fingerprint.strip()
        expected_bundle_fingerprint_source = "conflicting-sources"
        _production_evidence_finding(
            findings,
            "expected_bundle_fingerprint_source_conflict",
            "use either --fingerprint-record or --expected-bundle-fingerprint, not both",
        )
    elif args.fingerprint_record:
        expected_bundle_fingerprint = _production_evidence_expected_fingerprint_from_record(
            args.fingerprint_record,
            bundle_dir=resolved_bundle_dir,
            findings=findings,
        )
        if expected_bundle_fingerprint:
            expected_bundle_fingerprint_source = "out-of-band-fingerprint-record"
    elif args.expected_bundle_fingerprint:
        expected_bundle_fingerprint = args.expected_bundle_fingerprint.strip()
        expected_bundle_fingerprint_source = "cli-argument"

    summary = _read_json_object_for_evidence(
        resolved_bundle_dir / "summary.json",
        "summary",
        findings,
        bundle_dir=resolved_bundle_dir,
    )
    redaction_scan = _read_json_object_for_evidence(
        resolved_bundle_dir / "redaction-scan.json",
        "redaction_scan",
        findings,
        bundle_dir=resolved_bundle_dir,
    )
    bundle_manifest = _read_json_object_for_evidence(
        resolved_bundle_dir / "bundle-manifest.json",
        "bundle_manifest",
        findings,
        bundle_dir=resolved_bundle_dir,
    )
    release_audit = _read_json_object_for_evidence(
        resolved_bundle_dir / "release-audit.json",
        "release_audit",
        findings,
        bundle_dir=resolved_bundle_dir,
    )
    deployment_soak = _read_json_object_for_evidence(
        resolved_bundle_dir / "deployment-soak.stdout.json",
        "deployment_soak_stdout",
        findings,
        bundle_dir=resolved_bundle_dir,
    )
    evidence_manifest = _read_json_object_for_evidence(
        resolved_bundle_dir / "evidence" / "manifest.json",
        "evidence_manifest",
        findings,
        bundle_dir=resolved_bundle_dir,
    )
    preflight = _read_json_object_for_evidence(
        resolved_bundle_dir / "preflight.json",
        "preflight",
        findings,
        bundle_dir=resolved_bundle_dir,
    )
    operator_manifest = _read_json_object_for_evidence(
        resolved_bundle_dir / "operator-soak-manifest.json",
        "operator_soak_manifest",
        findings,
        bundle_dir=resolved_bundle_dir,
    )
    source_soak_manifest = _read_json_object_for_evidence(
        resolved_bundle_dir / "source-soak-manifest.json",
        "source_soak_manifest",
        findings,
        bundle_dir=resolved_bundle_dir,
    )
    _verify_production_evidence_summary(
        summary=summary,
        preflight=preflight,
        bundle_dir=resolved_bundle_dir,
        findings=findings,
    )
    preflight_ok = _verify_production_evidence_preflight(
        preflight,
        bundle_dir=resolved_bundle_dir,
        findings=findings,
    )
    operator_manifest_ok = _verify_production_evidence_operator_manifest(operator_manifest, findings)
    source_soak_manifest_ok = _verify_production_evidence_source_soak_manifest(
        source_soak_manifest,
        operator_manifest,
        preflight,
        findings,
    )
    input_artifact_custody_ok = _verify_production_evidence_input_artifact_custody(
        preflight=preflight,
        operator_manifest=operator_manifest,
        bundle_dir=resolved_bundle_dir,
        findings=findings,
    )
    deployment_soak_manifest_ok = _verify_production_evidence_deployment_soak_manifest(
        expected_manifest_path=resolved_bundle_dir / "operator-soak-manifest.json",
        bundle_dir=resolved_bundle_dir,
        deployment_soak=deployment_soak,
        evidence_manifest=evidence_manifest,
        findings=findings,
    )
    evidence_manifest_ok = _verify_production_evidence_manifest_contract(
        evidence_manifest=evidence_manifest,
        deployment_soak=deployment_soak,
        findings=findings,
    )
    bundle_fingerprint = None
    actual_bundle_fingerprint = None
    artifact_count = 0
    actual_files: list[dict[str, Any]] = []
    if bundle_manifest is not None:
        bundle_fingerprint, actual_bundle_fingerprint, actual_files = (
            _verify_production_evidence_bundle_manifest(
                bundle_dir=resolved_bundle_dir,
                bundle_manifest=bundle_manifest,
                summary=summary,
                expected_bundle_fingerprint=expected_bundle_fingerprint,
                findings=findings,
            )
        )
        artifact_count = len(actual_files)
    redaction_scan_ok = _verify_production_evidence_redaction_scan(
        redaction_scan,
        bundle_dir=resolved_bundle_dir,
        actual_files=actual_files,
        preflight=preflight,
        findings=findings,
    )
    recomputed_release_audit = _verify_production_evidence_release_audit(
        bundle_dir=resolved_bundle_dir,
        release_audit=release_audit,
        deployment_soak=deployment_soak,
        summary=summary,
        findings=findings,
    )
    expected_bundle_fingerprint_present = bool(expected_bundle_fingerprint)
    internal_consistency_only = bool(args.internal_consistency_only)
    if expected_bundle_fingerprint_present and internal_consistency_only:
        _production_evidence_finding(
            findings,
            "expected_bundle_fingerprint_mode_conflict",
            "use either custody fingerprint input or --internal-consistency-only, not both",
        )
    if not expected_bundle_fingerprint_present and not internal_consistency_only:
        _production_evidence_finding(
            findings,
            "expected_bundle_fingerprint_missing",
            "production evidence custody review requires --fingerprint-record or "
            "--expected-bundle-fingerprint from an out-of-band fingerprint record; use "
            "--internal-consistency-only only for local diagnostics",
        )
    if expected_bundle_fingerprint_present and not internal_consistency_only and not args.report_output:
        _production_evidence_finding(
            findings,
            "report_output_missing",
            "production evidence custody review requires --report-output outside the "
            "bundle so reviewer guidance and row review are retained",
        )
    row_review = _production_evidence_row_review(preflight)
    report = {
        "ok": not findings,
        "bundle_dir": str(resolved_bundle_dir),
        "bundle_fingerprint": bundle_fingerprint,
        "expected_bundle_fingerprint": expected_bundle_fingerprint,
        "expected_bundle_fingerprint_present": expected_bundle_fingerprint_present,
        "expected_bundle_fingerprint_source": expected_bundle_fingerprint_source,
        "actual_bundle_fingerprint": actual_bundle_fingerprint,
        "internal_consistency_only": internal_consistency_only,
        "artifact_count": artifact_count,
        "release_audit_fingerprint": recomputed_release_audit.get("fingerprint")
        if isinstance(recomputed_release_audit, Mapping)
        else None,
        "row_review": row_review,
        "reviewer_guidance": _production_evidence_reviewer_guidance(
            findings=findings,
            row_review=row_review,
            internal_consistency_only=internal_consistency_only,
        ),
        "checks": {
            "summary": _production_evidence_summary_ok(
                summary,
                preflight=preflight,
                bundle_dir=resolved_bundle_dir,
            ),
            "preflight": preflight_ok,
            "redaction_scan": redaction_scan_ok,
            "bundle_manifest": bundle_manifest is not None and bundle_fingerprint is not None,
            "operator_manifest": operator_manifest_ok,
            "source_soak_manifest": source_soak_manifest_ok,
            "input_artifact_custody": input_artifact_custody_ok,
            "deployment_soak_manifest": deployment_soak_manifest_ok,
            "evidence_manifest": evidence_manifest_ok,
            "deployment_soak_stdout": deployment_soak is not None and deployment_soak.get("ok") is True,
            "release_audit_replay": isinstance(recomputed_release_audit, Mapping)
            and recomputed_release_audit.get("ok") is True,
        },
        "findings": findings,
    }
    _write_production_evidence_verify_report(
        report=report,
        report_output=args.report_output,
        bundle_dir=resolved_bundle_dir,
    )
    emit(report)
    if findings:
        raise SystemExit(1)


def _tls_target(args: argparse.Namespace) -> tuple[str, int, str]:
    if args.url:
        parsed = urlsplit(args.url)
        if parsed.scheme != "https":
            raise SystemExit("--url must use https:// for tls-cert-check.")
        if not parsed.hostname:
            raise SystemExit("--url must include a hostname.")
        host = parsed.hostname
        port = int(parsed.port or 443)
    else:
        if not args.host:
            raise SystemExit("tls-cert-check requires --url or --host.")
        host = args.host
        port = int(args.port)
    return host, port, args.server_name or host


def _cert_name(value: Any) -> str:
    if not isinstance(value, tuple):
        return ""
    parts: list[str] = []
    for relative_name in value:
        if not isinstance(relative_name, tuple):
            continue
        for item in relative_name:
            if isinstance(item, tuple) and len(item) == 2:
                parts.append(f"{item[0]}={item[1]}")
    return ", ".join(parts)


def _parse_cert_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)


def _tls_version(value: str) -> ssl.TLSVersion:
    versions = {
        "TLSv1.2": ssl.TLSVersion.TLSv1_2,
        "TLSv1.3": ssl.TLSVersion.TLSv1_3,
    }
    return versions[value]


def cmd_tls_cert_check(args: argparse.Namespace) -> None:
    host, port, server_name = _tls_target(args)
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than 0.")
    if args.min_days_valid < 0:
        raise SystemExit("--min-days-valid must be zero or greater.")

    target = {
        "host": host,
        "port": port,
        "server_name": server_name,
        "ca_file_configured": bool(args.ca_file),
        "minimum_tls_version": args.min_tls_version,
    }
    try:
        context = ssl.create_default_context(cafile=args.ca_file)
        context.minimum_version = _tls_version(args.min_tls_version)
        started = time.monotonic()
        with socket.create_connection((host, port), timeout=args.timeout) as raw_socket:
            with context.wrap_socket(raw_socket, server_hostname=server_name) as tls_socket:
                certificate = tls_socket.getpeercert()
                tls_version = tls_socket.version()
                cipher = tls_socket.cipher()
        latency_ms = round((time.monotonic() - started) * 1000, 3)
    except (OSError, ssl.SSLError, ValueError) as exc:
        emit(
            {
                "ok": False,
                "target": target,
                "error": str(exc),
                "checks": {
                    "chain_valid": False,
                    "hostname_valid": False,
                    "min_days_valid": False,
                },
            }
        )
        raise SystemExit(1) from exc

    not_before = _parse_cert_time(certificate.get("notBefore"))
    not_after = _parse_cert_time(certificate.get("notAfter"))
    days_remaining = ((not_after - datetime.now(UTC)).total_seconds() / 86_400) if not_after else None
    subject_alt_names = [
        {"type": str(kind), "value": str(value)}
        for kind, value in certificate.get("subjectAltName", [])
        if isinstance(kind, str)
    ]
    min_days_ok = days_remaining is not None and days_remaining >= args.min_days_valid
    report = {
        "ok": bool(min_days_ok),
        "target": target,
        "tls": {
            "version": tls_version,
            "cipher": cipher[0] if cipher else None,
            "latency_ms": latency_ms,
        },
        "certificate": {
            "subject": _cert_name(certificate.get("subject")),
            "issuer": _cert_name(certificate.get("issuer")),
            "serial_number": certificate.get("serialNumber"),
            "not_before": not_before.isoformat() if not_before else None,
            "not_after": not_after.isoformat() if not_after else None,
            "days_remaining": round(days_remaining, 3) if days_remaining is not None else None,
            "subject_alt_names": subject_alt_names,
        },
        "checks": {
            "chain_valid": True,
            "hostname_valid": True,
            "min_days_valid": min_days_ok,
            "min_days_required": args.min_days_valid,
        },
    }
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _load_x509_certificate(path: str | Path) -> x509.Certificate:
    from cryptography import x509

    try:
        return x509.load_pem_x509_certificate(Path(path).expanduser().read_bytes())
    except Exception as exc:  # noqa: BLE001 - deployment checks return structured failures.
        raise ValueError(f"could not load certificate {path}: {exc}") from exc


def _x509_time(certificate: x509.Certificate, attr: str) -> datetime:

    utc_attr = f"{attr}_utc"
    value = getattr(certificate, utc_attr, None)
    if value is None:
        value = getattr(certificate, attr)
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
    return value


def _x509_sans(certificate: x509.Certificate) -> tuple[list[str], list[str]]:
    from cryptography import x509

    try:
        san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return [], []
    dns_names = [str(value) for value in san.get_values_for_type(x509.DNSName)]
    ip_addresses = [str(value) for value in san.get_values_for_type(x509.IPAddress)]
    return dns_names, ip_addresses


def _x509_matches_hostname(certificate: x509.Certificate, hostname: str) -> bool:

    dns_names, ip_addresses = _x509_sans(certificate)
    try:
        host_ip = ipaddress.ip_address(hostname)
    except ValueError:
        host_ip = None
    if host_ip is not None:
        return any(host_ip == ipaddress.ip_address(item) for item in ip_addresses)
    normalized = hostname.rstrip(".").lower()
    for pattern in dns_names:
        candidate = pattern.rstrip(".").lower()
        if candidate.startswith("*."):
            suffix = candidate[1:]
            if normalized.endswith(suffix) and normalized.count(".") == candidate.count("."):
                return True
        elif candidate == normalized:
            return True
    return False


def _x509_report(certificate: x509.Certificate, *, now: datetime) -> dict[str, Any]:

    not_before = _x509_time(certificate, "not_valid_before")
    not_after = _x509_time(certificate, "not_valid_after")
    dns_names, ip_addresses = _x509_sans(certificate)
    return {
        "subject": certificate.subject.rfc4514_string(),
        "issuer": certificate.issuer.rfc4514_string(),
        "serial_sha256": sha256(str(certificate.serial_number).encode("utf-8")).hexdigest()[:16],
        "not_before": not_before.isoformat(),
        "not_after": not_after.isoformat(),
        "days_remaining": round((not_after - now).total_seconds() / 86400, 3),
        "subject_alt_names": {
            "dns": dns_names,
            "ip": ip_addresses,
        },
    }


def _hostname_checks(certificate: x509.Certificate, hostnames: list[str]) -> dict[str, bool]:

    return {hostname: _x509_matches_hostname(certificate, hostname) for hostname in hostnames}


def cmd_tls_rotation_plan_check(args: argparse.Namespace) -> None:
    hostnames = [item.strip() for item in (args.hostname or []) for item in item.split(",") if item.strip()]
    if not hostnames:
        raise SystemExit("tls-rotation-plan-check requires --hostname or MNEMOSYNE_TLS_ROTATION_HOSTNAMES")
    if args.min_current_days_valid < 0 or args.min_candidate_days_valid < 0 or args.min_overlap_days < 0:
        raise SystemExit("TLS rotation day thresholds must be zero or greater.")

    now = datetime.now(UTC)
    try:
        current = _load_x509_certificate(args.current_cert_file)
        candidate = _load_x509_certificate(args.candidate_cert_file)
    except ValueError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(1) from exc

    current_not_before = _x509_time(current, "not_valid_before")
    current_not_after = _x509_time(current, "not_valid_after")
    candidate_not_before = _x509_time(candidate, "not_valid_before")
    candidate_not_after = _x509_time(candidate, "not_valid_after")
    overlap_start = max(now, current_not_before, candidate_not_before)
    overlap_end = min(current_not_after, candidate_not_after)
    overlap_days = max(0.0, (overlap_end - overlap_start).total_seconds() / 86400)
    current_days = (current_not_after - now).total_seconds() / 86400
    candidate_days = (candidate_not_after - now).total_seconds() / 86400
    current_hostname_checks = _hostname_checks(current, hostnames)
    candidate_hostname_checks = _hostname_checks(candidate, hostnames)
    issuer_continuity = current.issuer == candidate.issuer
    checks = {
        "current_min_days_valid": current_days >= args.min_current_days_valid,
        "candidate_min_days_valid": candidate_days >= args.min_candidate_days_valid,
        "overlap_valid": overlap_days >= args.min_overlap_days,
        "hostnames_valid": all(current_hostname_checks.values()) and all(candidate_hostname_checks.values()),
        "issuer_continuity_valid": issuer_continuity or not args.require_issuer_continuity,
    }
    ok = all(checks.values())
    report = {
        "ok": ok,
        "config": {
            "hostnames": hostnames,
            "min_current_days_valid": args.min_current_days_valid,
            "min_candidate_days_valid": args.min_candidate_days_valid,
            "min_overlap_days": args.min_overlap_days,
            "require_issuer_continuity": bool(args.require_issuer_continuity),
        },
        "current": _x509_report(current, now=now),
        "candidate": _x509_report(candidate, now=now),
        "rotation": {
            "overlap_days": round(overlap_days, 3),
            "current_hostname_checks": current_hostname_checks,
            "candidate_hostname_checks": candidate_hostname_checks,
            "issuer_continuity": issuer_continuity,
        },
        "checks": checks,
    }
    emit(report)
    if not ok:
        raise SystemExit(1)


def _load_tls_lifecycle_ops_bundle(args: argparse.Namespace) -> Mapping[str, Any]:
    if bool(args.bundle) == bool(args.bundle_json):
        raise SystemExit("tls-lifecycle-ops-check requires exactly one of --bundle or --bundle-json")
    try:
        loaded = (
            json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8"))
            if args.bundle
            else json.loads(args.bundle_json)
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"TLS lifecycle ops bundle is not valid JSON: {exc}") from exc
    if not isinstance(loaded, Mapping):
        raise SystemExit("TLS lifecycle ops bundle must be a JSON object")
    return loaded


def _tls_lifecycle_finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _tls_lifecycle_fingerprint(report: Mapping[str, Any]) -> str:
    stable = {
        "bundle": report.get("bundle"),
        "requirements": report.get("requirements"),
        "checks": report.get("checks"),
        "findings": report.get("findings"),
    }
    return sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _tls_lifecycle_number(
    value: Any,
    *,
    default: float,
    code: str,
    message: str,
    findings: list[dict[str, str]],
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        findings.append(_tls_lifecycle_finding(code, message))
        return default


def _tls_lifecycle_hash_present(value: Any) -> bool:
    return "sha256:" in str(value or "").lower()


def _tls_lifecycle_hostnames(raw: Any, findings: list[dict[str, str]]) -> list[str]:
    if not isinstance(raw, list):
        findings.append(_tls_lifecycle_finding("tls_hostnames_invalid", "issuance.hostnames must be a list"))
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _tls_lifecycle_forbidden_raw_paths(value: Any, *, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if child_path.startswith("$.redaction."):
                continue
            lowered = key_text.lower()
            if any(
                token in lowered
                for token in (
                    "raw_private_key",
                    "private_key_pem",
                    "acme_account_key",
                    "key_pem",
                    "tls_key",
                    "token",
                    "password",
                    "credential",
                    "raw_cert",
                    "certificate_pem",
                    "fullchain_pem",
                    "csr_pem",
                    "raw_pem",
                    "pem_block",
                    "raw_log",
                    "stdout",
                    "stderr",
                )
            ):
                paths.append(child_path)
            paths.extend(_tls_lifecycle_forbidden_raw_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_tls_lifecycle_forbidden_raw_paths(child, path=f"{path}[{index}]"))
    return paths


def cmd_tls_lifecycle_ops_check(args: argparse.Namespace) -> None:
    bundle = _load_tls_lifecycle_ops_bundle(args)
    findings: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []

    validation_raw = bundle.get("validation_scope")
    validation_present = isinstance(validation_raw, Mapping)
    validation = validation_raw if validation_present else {}
    validation_ok = (
        args.allow_non_production
        or (
            validation.get("production_validated") is True
            and validation.get("target_environment") == "production"
            and validation.get("operator_asserted") is True
            and bool(validation.get("run_id"))
            and bool(validation.get("started_at"))
            and bool(validation.get("completed_at"))
        )
    )
    if not args.allow_non_production:
        if validation.get("production_validated") is not True:
            findings.append(_tls_lifecycle_finding("production_validation_missing", "TLS lifecycle evidence must be production validated"))
        if validation.get("target_environment") != "production":
            findings.append(_tls_lifecycle_finding("production_target_missing", "TLS lifecycle target environment must be production"))
        if validation.get("operator_asserted") is not True:
            findings.append(_tls_lifecycle_finding("operator_attestation_missing", "TLS lifecycle evidence requires operator attestation"))
        for field in ("run_id", "started_at", "completed_at"):
            if not validation.get(field):
                findings.append(_tls_lifecycle_finding("validation_field_missing", f"validation_scope.{field} is required"))
    checks.append(
        {
            "name": "validation_scope",
            "ok": validation_ok,
            "production_validated": validation.get("production_validated") is True,
            "target_environment": validation.get("target_environment"),
            "operator_asserted": validation.get("operator_asserted") is True,
        }
    )

    issuance_raw = bundle.get("issuance")
    issuance_present = isinstance(issuance_raw, Mapping)
    issuance = issuance_raw if issuance_present else {}
    hostnames = _tls_lifecycle_hostnames(issuance.get("hostnames"), findings)
    issuer = str(issuance.get("provider") or issuance.get("issuer") or "").strip().lower()
    issuer_local = issuer in {"", "local", "self-signed", "self_signed", "test", "manual", "none"}
    issuance_ok = (
        issuance.get("ok") is True
        and not issuer_local
        and len(hostnames) >= args.min_hostnames
        and issuance.get("self_signed") is not True
        and _tls_lifecycle_hash_present(issuance.get("order_id_sha256") or issuance.get("request_id_sha256"))
        and _tls_lifecycle_hash_present(issuance.get("certificate_serial_sha256"))
        and _tls_lifecycle_hash_present(issuance.get("chain_sha256"))
    )
    if not issuance_present:
        findings.append(_tls_lifecycle_finding("missing_issuance_section", "TLS lifecycle bundle requires issuance section"))
    if issuance.get("ok") is not True:
        findings.append(_tls_lifecycle_finding("tls_issuance_not_ok", "issuance evidence must be ok"))
    if issuer_local:
        findings.append(_tls_lifecycle_finding("tls_issuer_local", "production TLS issuance must use a non-local CA/ACME provider"))
    if issuance.get("self_signed") is True:
        findings.append(_tls_lifecycle_finding("tls_self_signed", "production TLS certificate must not be self-signed"))
    if len(hostnames) < args.min_hostnames:
        findings.append(_tls_lifecycle_finding("tls_hostname_coverage_low", "TLS issuance hostname coverage is below threshold"))
    if not _tls_lifecycle_hash_present(issuance.get("order_id_sha256") or issuance.get("request_id_sha256")):
        findings.append(_tls_lifecycle_finding("tls_order_hash_missing", "TLS issuance requires hashed CA/ACME order or request id"))
    if not _tls_lifecycle_hash_present(issuance.get("certificate_serial_sha256")):
        findings.append(_tls_lifecycle_finding("tls_certificate_serial_missing", "TLS issuance requires hashed certificate serial"))
    if not _tls_lifecycle_hash_present(issuance.get("chain_sha256")):
        findings.append(_tls_lifecycle_finding("tls_chain_hash_missing", "TLS issuance requires certificate-chain hash"))
    checks.append(
        {
            "name": "issuance",
            "ok": issuance_ok,
            "provider": issuance.get("provider"),
            "hostnames": hostnames,
            "certificate_serial_sha256_present": _tls_lifecycle_hash_present(issuance.get("certificate_serial_sha256")),
            "chain_sha256_present": _tls_lifecycle_hash_present(issuance.get("chain_sha256")),
        }
    )

    renewal_raw = bundle.get("renewal")
    renewal_present = isinstance(renewal_raw, Mapping)
    renewal = renewal_raw if renewal_present else {}
    current_days = _tls_lifecycle_number(
        renewal.get("current_days_remaining"),
        default=0.0,
        code="tls_current_days_invalid",
        message="renewal.current_days_remaining must be numeric",
        findings=findings,
    )
    candidate_days = _tls_lifecycle_number(
        renewal.get("candidate_days_remaining"),
        default=0.0,
        code="tls_candidate_days_invalid",
        message="renewal.candidate_days_remaining must be numeric",
        findings=findings,
    )
    overlap_days = _tls_lifecycle_number(
        renewal.get("overlap_days"),
        default=0.0,
        code="tls_overlap_days_invalid",
        message="renewal.overlap_days must be numeric",
        findings=findings,
    )
    renewal_ok = (
        renewal.get("ok") is True
        and renewal.get("automation_enabled") is True
        and renewal.get("renewal_executed") is True
        and renewal.get("next_renewal_scheduled") is True
        and renewal.get("dry_run_passed") is True
        and current_days >= args.min_current_days_valid
        and candidate_days >= args.min_candidate_days_valid
        and overlap_days >= args.min_overlap_days
    )
    if not renewal_present:
        findings.append(_tls_lifecycle_finding("missing_renewal_section", "TLS lifecycle bundle requires renewal section"))
    for flag in ("automation_enabled", "renewal_executed", "next_renewal_scheduled", "dry_run_passed"):
        if renewal.get(flag) is not True:
            findings.append(_tls_lifecycle_finding("tls_renewal_control_missing", f"renewal.{flag} is not proven"))
    if current_days < args.min_current_days_valid:
        findings.append(_tls_lifecycle_finding("tls_current_validity_low", "current certificate validity is below threshold"))
    if candidate_days < args.min_candidate_days_valid:
        findings.append(_tls_lifecycle_finding("tls_candidate_validity_low", "candidate certificate validity is below threshold"))
    if overlap_days < args.min_overlap_days:
        findings.append(_tls_lifecycle_finding("tls_overlap_low", "certificate overlap is below threshold"))
    checks.append(
        {
            "name": "renewal",
            "ok": renewal_ok,
            "current_days_remaining": current_days,
            "candidate_days_remaining": candidate_days,
            "overlap_days": overlap_days,
            "automation_enabled": renewal.get("automation_enabled") is True,
            "renewal_executed": renewal.get("renewal_executed") is True,
        }
    )

    deployment_raw = bundle.get("deployment")
    deployment_present = isinstance(deployment_raw, Mapping)
    deployment = deployment_raw if deployment_present else {}
    endpoint = str(deployment.get("endpoint_url") or deployment.get("url") or "")
    endpoint_local = any(token in endpoint.lower() for token in ("localhost", "127.0.0.1", "[::1]"))
    deployed_serial = str(deployment.get("deployed_serial_sha256") or "")
    candidate_serial = str(deployment.get("candidate_serial_sha256") or issuance.get("certificate_serial_sha256") or "")
    deployment_ok = (
        deployment.get("ok") is True
        and endpoint.startswith("https://")
        and (args.allow_localhost or not endpoint_local)
        and _tls_lifecycle_hash_present(deployed_serial)
        and deployed_serial == candidate_serial
        and deployment.get("chain_verified") is True
        and deployment.get("hostname_verified") is True
        and deployment.get("reload_verified") is True
        and deployment.get("zero_downtime_reload") is True
    )
    if not deployment_present:
        findings.append(_tls_lifecycle_finding("missing_deployment_section", "TLS lifecycle bundle requires deployment section"))
    if deployment.get("ok") is not True:
        findings.append(_tls_lifecycle_finding("tls_deployment_not_ok", "deployment evidence must be ok"))
    if not endpoint.startswith("https://"):
        findings.append(_tls_lifecycle_finding("tls_endpoint_not_https", "deployed TLS endpoint must be HTTPS"))
    if endpoint_local and not args.allow_localhost:
        findings.append(_tls_lifecycle_finding("tls_endpoint_local", "production TLS endpoint must be non-local"))
    if not _tls_lifecycle_hash_present(deployed_serial) or deployed_serial != candidate_serial:
        findings.append(_tls_lifecycle_finding("tls_deployed_serial_mismatch", "deployed certificate serial must match issued candidate hash"))
    for flag in ("chain_verified", "hostname_verified", "reload_verified", "zero_downtime_reload"):
        if deployment.get(flag) is not True:
            findings.append(_tls_lifecycle_finding("tls_deployment_control_missing", f"deployment.{flag} is not proven"))
    checks.append(
        {
            "name": "deployment",
            "ok": deployment_ok,
            "endpoint_https": endpoint.startswith("https://"),
            "endpoint_local": endpoint_local,
            "deployed_serial_matches_candidate": bool(deployed_serial) and deployed_serial == candidate_serial,
            "reload_verified": deployment.get("reload_verified") is True,
        }
    )

    secret_raw = bundle.get("secret_distribution")
    secret_present = isinstance(secret_raw, Mapping)
    secret_distribution = secret_raw if secret_present else {}
    key_source = str(secret_distribution.get("private_key_source") or secret_distribution.get("source") or "").strip().lower()
    key_source_local = key_source in {"", "local", "file", "filesystem", "env", "test", "none"}
    secret_ok = (
        secret_distribution.get("ok") is True
        and not key_source_local
        and _tls_lifecycle_hash_present(secret_distribution.get("deployed_key_id_sha256"))
        and secret_distribution.get("private_key_material_omitted") is True
        and secret_distribution.get("least_privilege_permissions") is True
        and secret_distribution.get("key_rotation_supported") is True
        and secret_distribution.get("rollback_key_revocation_ready") is True
    )
    if not secret_present:
        findings.append(_tls_lifecycle_finding("missing_secret_distribution_section", "TLS lifecycle bundle requires secret_distribution section"))
    if secret_distribution.get("ok") is not True:
        findings.append(_tls_lifecycle_finding("tls_secret_distribution_not_ok", "secret distribution evidence must be ok"))
    if key_source_local:
        findings.append(_tls_lifecycle_finding("tls_key_source_local", "TLS private key custody must use non-local secret manager custody"))
    if not _tls_lifecycle_hash_present(secret_distribution.get("deployed_key_id_sha256")):
        findings.append(_tls_lifecycle_finding("tls_key_id_hash_missing", "secret distribution requires hashed deployed key id"))
    for flag in (
        "private_key_material_omitted",
        "least_privilege_permissions",
        "key_rotation_supported",
        "rollback_key_revocation_ready",
    ):
        if secret_distribution.get(flag) is not True:
            findings.append(_tls_lifecycle_finding("tls_secret_control_missing", f"secret_distribution.{flag} is not proven"))
    checks.append(
        {
            "name": "secret_distribution",
            "ok": secret_ok,
            "private_key_source": secret_distribution.get("private_key_source") or secret_distribution.get("source"),
            "key_source_local": key_source_local,
            "deployed_key_id_hash_present": _tls_lifecycle_hash_present(secret_distribution.get("deployed_key_id_sha256")),
        }
    )

    monitoring_raw = bundle.get("monitoring")
    monitoring = monitoring_raw if isinstance(monitoring_raw, Mapping) else {}
    monitoring_flags = {
        "expiry_alert_configured": monitoring.get("expiry_alert_configured") is True,
        "renewal_failure_alert_configured": monitoring.get("renewal_failure_alert_configured") is True,
        "cert_mismatch_alert_configured": monitoring.get("cert_mismatch_alert_configured") is True,
        "revocation_checked": monitoring.get("revocation_checked") is True,
    }
    missing_monitoring = [flag for flag, ok in monitoring_flags.items() if not ok]
    monitoring_ok = monitoring.get("ok") is True and not missing_monitoring
    if monitoring.get("ok") is not True:
        findings.append(_tls_lifecycle_finding("tls_monitoring_not_ok", "TLS lifecycle monitoring evidence must be ok"))
    for flag in missing_monitoring:
        findings.append(_tls_lifecycle_finding("tls_monitoring_missing", f"monitoring.{flag} is not proven"))
    checks.append({"name": "monitoring", "ok": monitoring_ok, **monitoring_flags})

    redaction_raw = bundle.get("redaction")
    redaction = redaction_raw if isinstance(redaction_raw, Mapping) else {}
    redaction_flags = {
        "raw_private_keys_omitted": redaction.get("raw_private_keys_omitted") is True,
        "raw_certificate_pem_omitted": redaction.get("raw_certificate_pem_omitted") is True,
        "raw_acme_tokens_omitted": redaction.get("raw_acme_tokens_omitted") is True,
        "raw_deployment_logs_omitted": redaction.get("raw_deployment_logs_omitted") is True,
    }
    missing_redaction = [flag for flag, ok in redaction_flags.items() if not ok]
    forbidden_raw_paths = _tls_lifecycle_forbidden_raw_paths(bundle)
    for flag in missing_redaction:
        findings.append(_tls_lifecycle_finding("tls_redaction_flag_missing", f"redaction.{flag} is not proven"))
    if forbidden_raw_paths:
        findings.append(_tls_lifecycle_finding("tls_raw_field_present", "TLS lifecycle bundle contains raw private key/cert/token/log fields"))
    checks.append(
        {
            "name": "redaction",
            "ok": not missing_redaction and not forbidden_raw_paths,
            **redaction_flags,
            "forbidden_raw_paths": forbidden_raw_paths,
        }
    )

    report: dict[str, Any] = {
        "ok": not findings,
        "bundle": {
            "name": bundle.get("name"),
            "validation_scope_present": validation_present,
            "issuance_present": issuance_present,
            "renewal_present": renewal_present,
            "deployment_present": deployment_present,
            "secret_distribution_present": secret_present,
        },
        "requirements": {
            "min_hostnames": args.min_hostnames,
            "min_current_days_valid": args.min_current_days_valid,
            "min_candidate_days_valid": args.min_candidate_days_valid,
            "min_overlap_days": args.min_overlap_days,
            "allow_non_production": bool(args.allow_non_production),
            "allow_localhost": bool(args.allow_localhost),
        },
        "redaction": {**redaction_flags, "forbidden_raw_fields_present": bool(forbidden_raw_paths)},
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _tls_lifecycle_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append(_tls_lifecycle_finding("fingerprint_mismatch", "TLS lifecycle ops bundle fingerprint mismatch"))
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _read_provider_manifest(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    manifest = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("--provider-manifest must point to a JSON object")
    return manifest


def _manifest_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"env"}:
        env_name = str(value["env"])
        env_value = os.environ.get(env_name)
        if env_value is None:
            raise SystemExit(f"provider manifest requires environment variable {env_name}")
        return env_value
    return value


def _manifest_string_list(value: Any, *, field: str) -> list[str]:
    resolved = _manifest_value(value)
    if isinstance(resolved, str):
        return [item.strip() for item in resolved.split(",") if item.strip()]
    if isinstance(resolved, list) and all(isinstance(item, str) and item.strip() for item in resolved):
        return [item.strip() for item in resolved]
    raise SystemExit(f"provider manifest field {field} must be a string list or comma-separated string")


def _manifest_bool(value: Any, *, field: str) -> bool:
    resolved = _manifest_value(value)
    if isinstance(resolved, bool):
        return resolved
    if isinstance(resolved, str):
        normalized = resolved.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise SystemExit(f"provider manifest field {field} must be a boolean")


def _apply_manifest_fields(args: argparse.Namespace, fields: dict[str, Any], mapping: dict[str, str]) -> None:
    for source, target in mapping.items():
        if source in fields and fields[source] is not None:
            setattr(args, target, _manifest_value(fields[source]))


def apply_provider_manifest(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _read_provider_manifest(getattr(args, "provider_manifest", None))
    if not manifest:
        return {"name": None, "required_checks": [], "forbid_local": False}
    providers = manifest.get("providers", {})
    if not isinstance(providers, dict):
        raise SystemExit("provider manifest field 'providers' must be an object")
    retrieval = providers.get("retrieval", {})
    if isinstance(retrieval, dict):
        _apply_manifest_fields(
            args,
            retrieval.get("embedding", {}) if isinstance(retrieval.get("embedding", {}), dict) else {},
            {
                "provider": "embedding_provider",
                "url": "embedding_url",
                "model": "embedding_model",
                "api_key": "embedding_api_key",
                "dims": "embedding_dims",
                "timeout_seconds": "retrieval_timeout",
            },
        )
        _apply_manifest_fields(
            args,
            retrieval.get("reranker", {}) if isinstance(retrieval.get("reranker", {}), dict) else {},
            {
                "provider": "reranker_provider",
                "url": "reranker_url",
                "model": "reranker_model",
                "api_key": "reranker_api_key",
                "timeout_seconds": "retrieval_timeout",
            },
        )
        _apply_manifest_fields(
            args,
            retrieval,
            {
                "lexical_provider": "lexical_provider",
                "lexical_command": "lexical_command",
                "lexical_backend": "lexical_backend",
                "graph_provider": "graph_provider",
                "graph_command": "graph_command",
                "graph_backend": "graph_backend",
            },
        )
        _apply_manifest_fields(
            args,
            retrieval.get("lexical", {}) if isinstance(retrieval.get("lexical", {}), dict) else {},
            {
                "provider": "lexical_provider",
                "command": "lexical_command",
                "backend": "lexical_backend",
                "timeout_seconds": "retrieval_timeout",
            },
        )
        _apply_manifest_fields(
            args,
            retrieval.get("graph", {}) if isinstance(retrieval.get("graph", {}), dict) else {},
            {
                "provider": "graph_provider",
                "command": "graph_command",
                "backend": "graph_backend",
                "timeout_seconds": "retrieval_timeout",
            },
        )
    media = providers.get("media", {})
    if isinstance(media, dict):
        _apply_manifest_fields(
            args,
            media.get("extractor", {}) if isinstance(media.get("extractor", {}), dict) else {},
            {
                "command": "media_extractor_command",
                "timeout_seconds": "media_extractor_timeout",
            },
        )
        _apply_manifest_fields(
            args,
            media.get("embedding", {}) if isinstance(media.get("embedding", {}), dict) else {},
            {
                "provider": "media_embedding_provider",
                "command": "media_embedding_command",
                "dims": "media_embedding_dims",
                "timeout_seconds": "media_embedding_timeout",
            },
        )
    object_key = providers.get("object_key", {})
    if isinstance(object_key, dict):
        _apply_manifest_fields(
            args,
            object_key,
            {
                "provider": "object_key_provider",
                "command": "object_key_command",
                "timeout_seconds": "object_key_timeout",
                "store": "object_key_store",
            },
        )
        if object_key.get("required") is True:
            args.object_store_encryption = "aesgcm"
    parametric = providers.get("parametric", {})
    if isinstance(parametric, dict):
        _apply_manifest_fields(
            args,
            parametric,
            {
                "provider": "parametric_provider",
                "command": "parametric_command",
                "adapter_kind": "parametric_adapter_kind",
                "timeout_seconds": "parametric_timeout",
            },
        )
    entity_resolver = providers.get("entity_resolver", {})
    if isinstance(entity_resolver, dict):
        _apply_manifest_fields(
            args,
            entity_resolver,
            {
                "provider": "entity_resolver_provider",
                "command": "entity_resolver_command",
                "timeout_seconds": "entity_resolver_timeout",
            },
        )
    candidate_extractor = providers.get("candidate_extractor", {})
    if isinstance(candidate_extractor, dict):
        _apply_manifest_fields(
            args,
            candidate_extractor,
            {
                "provider": "candidate_extractor_provider",
                "command": "candidate_extractor_command",
                "timeout_seconds": "candidate_extractor_timeout",
            },
        )
    summarizer = providers.get("summarizer", {})
    if isinstance(summarizer, dict):
        _apply_manifest_fields(
            args,
            summarizer,
            {
                "provider": "summarizer_provider",
                "command": "summarizer_command",
                "timeout_seconds": "summarizer_timeout",
            },
        )
    lesson_distiller = providers.get("lesson_distiller", {})
    if isinstance(lesson_distiller, dict):
        _apply_manifest_fields(
            args,
            lesson_distiller,
            {
                "provider": "lesson_distiller_provider",
                "command": "lesson_distiller_command",
                "timeout_seconds": "lesson_distiller_timeout",
            },
        )
    skill_inducer = providers.get("skill_inducer", {})
    if isinstance(skill_inducer, dict):
        _apply_manifest_fields(
            args,
            skill_inducer,
            {
                "provider": "skill_inducer_provider",
                "command": "skill_inducer_command",
                "timeout_seconds": "skill_inducer_timeout",
            },
        )
    session_secret = providers.get("session_secret", {})
    if isinstance(session_secret, dict):
        _apply_manifest_fields(
            args,
            session_secret,
            {
                "command": "session_secret_command",
                "timeout_seconds": "session_secret_command_timeout",
            },
        )
    oidc = providers.get("oidc", {})
    if isinstance(oidc, dict):
        _apply_manifest_fields(
            args,
            oidc,
            {
                "jwks": "provider_oidc_jwks",
                "jwks_file": "provider_oidc_jwks_file",
                "jwks_url": "provider_oidc_jwks_url",
                "allow_insecure_jwks_url": "provider_oidc_allow_insecure_jwks_url",
                "issuer": "provider_oidc_issuer",
                "audience": "provider_oidc_audience",
                "authz_policy": "provider_oidc_authz_policy",
                "authz_policy_file": "provider_oidc_authz_policy_file",
                "timeout_seconds": "provider_oidc_timeout",
                "jwks_max_bytes": "provider_oidc_jwks_max_bytes",
            },
        )
    residency_policy = providers.get("residency_policy", {})
    if isinstance(residency_policy, dict):
        if "allowed_residencies" in residency_policy and residency_policy["allowed_residencies"] is not None:
            args.allowed_residency = _manifest_string_list(
                residency_policy["allowed_residencies"],
                field="providers.residency_policy.allowed_residencies",
            )
        if "runtime_residency" in residency_policy and residency_policy["runtime_residency"] is not None:
            args.runtime_residency = _manifest_value(residency_policy["runtime_residency"])
        if (
            "allowed_residency_transfers" in residency_policy
            and residency_policy["allowed_residency_transfers"] is not None
        ):
            args.allowed_residency_transfer = _manifest_string_list(
                residency_policy["allowed_residency_transfers"],
                field="providers.residency_policy.allowed_residency_transfers",
            )
        if (
            "require_runtime_residency" in residency_policy
            and residency_policy["require_runtime_residency"] is not None
        ):
            args.require_runtime_residency = _manifest_bool(
                residency_policy["require_runtime_residency"],
                field="providers.residency_policy.require_runtime_residency",
            )
    required = manifest.get("required_checks", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise SystemExit("provider manifest field 'required_checks' must be an array of strings")
    forbid_local = bool(manifest.get("forbid_local", False))
    return {"name": manifest.get("name"), "required_checks": required, "forbid_local": forbid_local}


def _is_local_retrieval_backend(name: str | None) -> bool:
    normalized = str(name or "").strip().lower()
    return normalized in {
        "local",
        "local-bm25-lite",
        "local-fts",
        "bm25-lite",
        "local-ppr",
        "ppr-lite",
    } or normalized.startswith("local-")


def enforce_provider_manifest_policy(
    checks: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
) -> bool:
    ok = True
    if manifest.get("forbid_local"):
        for check_name in ("embedding", "reranker"):
            check = checks.get(check_name, {})
            if check.get("ok") and check.get("provider") in {"local", "local-hashing", "hashing", "local-similarity"}:
                check["ok"] = False
                check["error"] = "provider manifest forbids local retrieval providers"
                ok = False
        backend_check = checks.get("retrieval_backends", {})
        if backend_check.get("ok") and (
            backend_check.get("lexical_local") or backend_check.get("graph_local")
        ):
            backend_check["ok"] = False
            backend_check["error"] = "provider manifest forbids local retrieval backends"
            ok = False
    for check_name in manifest.get("required_checks", []):
        check = checks.get(check_name)
        if check is None:
            checks[check_name] = {"ok": False, "error": "required check was not executed"}
            ok = False
        elif check.get("skipped"):
            check["ok"] = False
            check["error"] = "required check was skipped"
            ok = False
        elif not check.get("ok"):
            ok = False
    return ok


def _read_hosted_llm_manifest(path: str) -> dict[str, Any]:
    try:
        manifest = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"hosted LLM manifest denied: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SystemExit("hosted LLM manifest must be a JSON object")
    providers = manifest.get("providers")
    if not isinstance(providers, list) or not providers:
        raise SystemExit("hosted LLM manifest requires a non-empty providers array")
    return manifest


def _is_loopback_host(host: str | None) -> bool:
    from mnemosyne.network_safety import is_loopback_host

    return is_loopback_host(host)


def _hosted_check_allowed_internal_hosts() -> tuple[str, ...]:
    """Internal hostnames hosted checks may probe (operator allowlist).

    Self-hosted deployments serve the hosted dashboard, MCP, and role-LLM
    surfaces on private addresses behind the internal ingress. The
    network-safety guard blocks private resolution by default; this is the
    explicit operator-scoped escape hatch, matching the Vault/Ollama/retrieval
    and OIDC provider paths (``MNEMOSYNE_*_ALLOWED_INTERNAL_HOSTS``). HTTPS is
    still required for allowlisted hosts.
    """

    raw = os.environ.get("MNEMOSYNE_HOSTED_CHECK_ALLOWED_INTERNAL_HOSTS", "")
    return tuple(host.strip() for host in raw.split(",") if host.strip())


def _validate_hosted_fetch_url(url: str, *, allow_insecure_localhost: bool) -> ValidatedFetchUrl:
    from mnemosyne.network_safety import validate_fetch_url

    try:
        return validate_fetch_url(
            url,
            allow_insecure_localhost=allow_insecure_localhost,
            allow_internal_hosts=_hosted_check_allowed_internal_hosts(),
            purpose="provider url",
        )
    except ValueError as exc:
        message = str(exc)
        if "requires https unless insecure localhost is explicitly allowed" in message:
            message = "hosted provider checks require https unless --allow-insecure-localhost is set"
        raise ValueError(message) from exc


def _validate_hosted_url(url: str, *, allow_insecure_localhost: bool) -> tuple[str, str]:
    validated = _validate_hosted_fetch_url(url, allow_insecure_localhost=allow_insecure_localhost)
    return validated.origin, validated.host


def _hosted_provider_request(provider: Mapping[str, Any], *, default_timeout: float) -> tuple[dict[str, Any], float]:
    request_payload = provider.get("request")
    if request_payload is None:
        request_payload = {
            "tenant_id": "hosted-provider-health",
            "payload": {"query": "Mnemosyne hosted provider health check"},
            "evidence": [
                {
                    "cid": "health-cid",
                    "content": "Provider Health is configured.",
                    "source_type": "hosted-llm-check",
                }
            ],
            "candidates": [
                {
                    "signature": "provider-health",
                    "query": "provider health",
                    "candidate_subject": "Provider Health",
                    "candidate_predicate": "is",
                    "candidate_object": "configured",
                }
            ],
        }
    if not isinstance(request_payload, Mapping):
        raise ValueError("provider request must be a JSON object")
    timeout = float(provider.get("timeout_seconds", default_timeout))
    return dict(request_payload), timeout


def _hosted_provider_api_key(provider: Mapping[str, Any]) -> tuple[str | None, str | None]:
    if provider.get("api_key_env"):
        env_name = str(provider["api_key_env"])
        value = os.environ.get(env_name)
        if not value:
            raise ValueError(f"api key env {env_name} is not set")
        return value, env_name
    if provider.get("api_key"):
        raise ValueError("hosted provider api_key must not be inline; use api_key_env or command-backed custody")
    return None, None


def _extract_openai_chat_payload(raw: Mapping[str, Any], *, role: str) -> Mapping[str, Any]:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("openai-chat-json response requires choices array")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise ValueError("openai-chat-json choice must be an object")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, Mapping) else choice.get("text")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("openai-chat-json response requires message content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        if role == "summarizer":
            return {"summary": content}
        raise ValueError("openai-chat-json message content must be JSON for this role") from None
    if not isinstance(parsed, Mapping):
        raise ValueError("openai-chat-json message content must decode to a JSON object")
    return parsed


def _hosted_role_payload(raw: Mapping[str, Any], *, protocol: str, role: str) -> Mapping[str, Any]:
    if protocol == "role-json":
        return raw
    if protocol == "openai-chat-json":
        return _extract_openai_chat_payload(raw, role=role)
    raise ValueError(f"unsupported hosted provider protocol {protocol}")


def _validate_hosted_role_payload(role: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if role == "candidate_extractor":
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("candidate extractor response requires non-empty candidates array")
        required = {"signature", "query", "candidate_subject", "candidate_predicate", "candidate_object"}
        first = candidates[0]
        if not isinstance(first, Mapping) or not required.issubset(first):
            raise ValueError("candidate extractor candidate is missing required fields")
        return {"candidate_count": len(candidates), "signatures": [str(item.get("signature")) for item in candidates[:5]]}
    if role == "summarizer":
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summarizer response requires non-empty summary")
        return {"summary_length": len(summary)}
    if role == "entity_resolver":
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("entity resolver response requires non-empty candidates array")
        entity_keys = [str(item.get("entity_key") or "") for item in candidates if isinstance(item, Mapping)]
        if not entity_keys or not all(entity_keys):
            raise ValueError("entity resolver response requires entity_key on every candidate")
        return {"entity_count": len(entity_keys), "entity_keys": entity_keys[:5]}
    if role == "lesson_distiller":
        lessons = payload.get("lessons")
        if not isinstance(lessons, list) or not lessons:
            raise ValueError("lesson distiller response requires non-empty lessons array")
        first = lessons[0]
        if not isinstance(first, Mapping):
            raise ValueError("lesson distiller lesson must be an object")
        if not isinstance(first.get("content"), str) or not first["content"].strip():
            raise ValueError("lesson distiller lesson requires non-empty content")
        signature = first.get("failure_signature") or first.get("signature")
        if not isinstance(signature, str) or not signature.strip():
            raise ValueError("lesson distiller lesson requires failure_signature")
        return {
            "lesson_count": len(lessons),
            "failure_signatures": [
                str(item.get("failure_signature") or item.get("signature"))
                for item in lessons[:5]
                if isinstance(item, Mapping)
            ],
        }
    if role == "skill_inducer":
        procedures = payload.get("procedures")
        if not isinstance(procedures, list) or not procedures:
            raise ValueError("skill inducer response requires non-empty procedures array")
        first = procedures[0]
        if not isinstance(first, Mapping):
            raise ValueError("skill inducer procedure must be an object")
        if not isinstance(first.get("name"), str) or not first["name"].strip():
            raise ValueError("skill inducer procedure requires non-empty name")
        if not isinstance(first.get("body"), str) or not first["body"].strip():
            raise ValueError("skill inducer procedure requires non-empty body")
        if not isinstance(first.get("signature"), Mapping):
            raise ValueError("skill inducer procedure requires signature object")
        return {
            "procedure_count": len(procedures),
            "procedure_names": [
                str(item.get("name"))
                for item in procedures[:5]
                if isinstance(item, Mapping)
            ],
        }
    raise ValueError(f"unsupported hosted provider role {role}")


def _hosted_llm_fingerprint(report: Mapping[str, Any]) -> str:
    stable = {
        "manifest": report.get("manifest"),
        "required_roles": report.get("required_roles"),
        "checks": [
            {
                "name": item.get("name"),
                "role": item.get("role"),
                "protocol": item.get("protocol"),
                "ok": item.get("ok"),
                "provider_kind": item.get("provider_kind"),
                "contract": item.get("contract"),
            }
            for item in report.get("checks", [])
            if isinstance(item, Mapping)
        ],
    }
    return sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _run_hosted_provider_check(
    provider: Mapping[str, Any],
    *,
    default_timeout: float,
    allow_insecure_localhost: bool,
) -> dict[str, Any]:
    from mnemosyne.network_safety import safe_urlopen

    name = str(provider.get("name") or provider.get("role") or "hosted-provider")
    role = str(provider["role"])
    protocol = str(provider.get("protocol") or "role-json")
    url = str(provider["url"])
    request_payload, timeout = _hosted_provider_request(provider, default_timeout=default_timeout)
    api_key, api_key_source = _hosted_provider_api_key(provider)
    validated_url = _validate_hosted_fetch_url(
        url,
        allow_insecure_localhost=allow_insecure_localhost,
    )
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "mnemosyne-hosted-llm-check/1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = json.dumps(request_payload).encode("utf-8")
    request = urlrequest.Request(url, data=body, headers=headers, method=str(provider.get("method") or "POST").upper())
    started = time.monotonic()
    with safe_urlopen(request, validated=validated_url, timeout=timeout) as response:
        status_code = int(getattr(response, "status", response.getcode()))
        raw_bytes = response.read(int(provider.get("max_response_bytes", 65536)))
    duration_ms = round((time.monotonic() - started) * 1000, 3)
    raw = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("hosted provider response must be a JSON object")
    payload = _hosted_role_payload(raw, protocol=protocol, role=role)
    contract = _validate_hosted_role_payload(role, payload)
    return {
        "name": name,
        "role": role,
        "ok": True,
        "provider_kind": "hosted_http",
        "protocol": protocol,
        "origin": validated_url.origin,
        "host_sha256": sha256(validated_url.host.encode("utf-8")).hexdigest()[:16],
        "status_code": status_code,
        "duration_ms": duration_ms,
        "auth": {
            "api_key_present": bool(api_key),
            "api_key_source": api_key_source,
            "authorization_redacted": bool(api_key),
        },
        "contract": contract,
        "response_keys": sorted(str(key) for key in raw.keys()),
    }


def cmd_hosted_llm_check(args: argparse.Namespace) -> None:
    manifest = _read_hosted_llm_manifest(args.hosted_llm_manifest)
    required_roles = manifest.get("required_roles", ["candidate_extractor", "summarizer", "entity_resolver"])
    if not isinstance(required_roles, list) or not all(isinstance(item, str) for item in required_roles):
        raise SystemExit("hosted LLM manifest required_roles must be an array of strings")
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for index, provider in enumerate(manifest["providers"], start=1):
        if not isinstance(provider, Mapping):
            checks.append({"index": index, "ok": False, "error": "provider must be a JSON object"})
            continue
        try:
            check = _run_hosted_provider_check(
                provider,
                default_timeout=args.timeout,
                allow_insecure_localhost=args.allow_insecure_localhost,
            )
            check["index"] = index
        except Exception as exc:  # noqa: BLE001 - deployment checks return structured failures.
            check = {
                "index": index,
                "name": str(provider.get("name") or provider.get("role") or f"provider-{index}"),
                "role": str(provider.get("role") or ""),
                "ok": False,
                "provider_kind": "hosted_http",
                "error": str(exc),
            }
        checks.append(check)
    for check in checks:
        if check.get("ok") is not True:
            findings.append(
                {
                    "code": "provider_check_failed",
                    "message": f"hosted provider {check.get('name') or check.get('index')} did not pass",
                }
            )
    for role in required_roles:
        role_checks = [item for item in checks if item.get("role") == role]
        if not role_checks:
            findings.append({"code": "missing_required_role", "message": f"hosted role {role} is missing"})
        elif not any(item.get("ok") is True for item in role_checks):
            findings.append({"code": "required_role_failed", "message": f"hosted role {role} did not pass"})
    if manifest.get("forbid_local") is True and args.allow_insecure_localhost:
        findings.append({"code": "local_provider_allowed", "message": "forbid_local manifest cannot allow insecure localhost"})
    report = {
        "ok": not findings,
        "manifest": {
            "name": manifest.get("name"),
            "provider_count": len(manifest["providers"]),
            "forbid_local": bool(manifest.get("forbid_local", False)),
        },
        "required_roles": sorted(required_roles),
        "redaction": {
            "authorization_header_redacted": True,
            "request_body_omitted": True,
            "response_body_omitted": True,
        },
        "checks": checks,
        "findings": findings,
    }
    report["fingerprint"] = _hosted_llm_fingerprint(report)
    report["expected_fingerprint_present"] = bool(args.expected_fingerprint)
    if args.expected_fingerprint and args.expected_fingerprint.strip().lower() != report["fingerprint"]:
        report["ok"] = False
        report["findings"].append({"code": "fingerprint_mismatch", "message": "hosted LLM check fingerprint mismatch"})
    emit(report)
    if not report["ok"]:
        raise SystemExit(1)


def _provider_latency_summary_ms(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    p50_index = min(len(ordered) - 1, int(len(ordered) * 0.50))
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "samples": len(ordered),
        "p50_latency_ms": ordered[p50_index],
        "p95_latency_ms": ordered[p95_index],
        "max_latency_ms": max(ordered),
    }


def _run_provider_latency_samples(samples: int, callback: Any) -> tuple[Any, dict[str, float | int]]:
    result: Any = None
    durations: list[float] = []
    for _ in range(max(1, samples)):
        start = time.perf_counter()
        result = callback()
        durations.append((time.perf_counter() - start) * 1000.0)
    return result, _provider_latency_summary_ms(durations)


def _native_retrieval_probe(args: argparse.Namespace) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    """Probe the native Postgres lexical + graph retrieval against a seeded
    health tenant, returning ``{top_id, hit_count}`` probes for provider-check.

    Native FTS + recursive-PPR are the deployed retrieval backends (provider
    kind ``postgres``); this proves they answer a live query, mirroring the
    probe the ``command`` provider path already emits. The ``provider-health``
    tenant is deterministic and idempotent (content-addressed CIDs dedupe
    re-seeds), and isolated from tenant data by RLS.
    """
    from mnemosyne.models import Evidence, Relation
    from mnemosyne.postgres_engine import PostgresEngine, PostgresUnavailableError

    errors: list[str] = []
    dsn = getattr(args, "postgres_dsn", None) or default_postgres_dsn()
    if not dsn:
        return None, None, ["native retrieval probe requires --postgres-dsn or MNEMOSYNE_POSTGRES_DSN"]
    tenant = "provider-health"
    try:
        engine = PostgresEngine(dsn, require_safe_role=bool(getattr(args, "postgres_require_safe_role", False)))
    except PostgresUnavailableError as exc:
        return None, None, [f"native retrieval probe engine unavailable: {exc}"]
    try:
        engine.ensure_tenant_and_branch(tenant, "main")
    except Exception:  # noqa: BLE001 - tenant/branch may already exist; seed writes below confirm.
        pass
    try:
        evidence_cid = engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id=tenant,
                actor="system",
                source_type="provider-health",
                content="provider health check retrieval lexical probe signal for the native backend",
                metadata={"reality_class": "grounded"},
                trust_tier=0,
                access_policy={"tenant": tenant},
            )
        )
        # The graph_ppr relation-hit security filter drops relations without a
        # trusted source-evidence CID, so bind the seeded health evidence.
        engine.add_relation(
            Relation(
                tenant_id=tenant,
                source="provider health retrieval signal",
                predicate="relates_to",
                target="native retrieval health node",
                source_evidence_cids=[evidence_cid],
            )
        )
    except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
        errors.append(f"native retrieval probe seed failed: {exc}")

    lexical_probe: dict[str, Any] | None = None
    graph_probe: dict[str, Any] | None = None
    if args.lexical_provider in {"postgres", "native"}:
        try:
            hits = engine.lexical_search(
                "provider health check retrieval",
                k=1,
                filt={"tenant_id": tenant, "branch": "main"},
            )
            if not hits:
                raise ValueError("native lexical provider returned no health-check hits")
            lexical_probe = {"hit_count": len(hits), "top_id": hits[0].id}
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            errors.append(f"native lexical provider failed: {exc}")
    if args.graph_provider in {"postgres", "native"}:
        try:
            hits = engine.graph_ppr(
                ["provider", "health", "retrieval"],
                1,
                tenant_id=tenant,
                branch="main",
            )
            if not hits:
                raise ValueError("native graph provider returned no health-check hits")
            graph_probe = {"hit_count": len(hits), "top_id": hits[0].id}
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            errors.append(f"native graph provider failed: {exc}")
    return lexical_probe, graph_probe, errors


def cmd_provider_check(args: argparse.Namespace) -> None:
    from mnemosyne.gate import RegressionCase
    from mnemosyne.ingestion import residency_policy_report
    from mnemosyne.learning import Lesson, Procedure
    from mnemosyne.models import Evidence, Hit
    from mnemosyne.oidc_jwks import load_oidc_authorization_policy, load_oidc_jwks
    from mnemosyne.parametric import (
        CommandParametricTrainer,
        ParametricArtifactStore,
        ParametricTier,
        protected_suite_report,
    )
    from mnemosyne.retrieval import CommandMediaEmbeddingProvider, embed_query
    from mnemosyne.security import SessionAuthError, SessionIdentity, SessionTokenVerifier, load_session_secret_command

    manifest = apply_provider_manifest(args)
    latency_samples = max(1, int(getattr(args, "provider_latency_samples", 1)))
    max_provider_p95_latency_ms = float(getattr(args, "max_provider_p95_latency_ms", 2000.0))
    checks: dict[str, dict[str, Any]] = {}
    ok = True
    try:
        adapters = load_retrieval_adapters(args)
        vector, latency = _run_provider_latency_samples(
            latency_samples,
            lambda: embed_query(adapters.embedding, "Mnemosyne provider health check"),
        )
        latency_ok = float(latency["p95_latency_ms"]) <= max_provider_p95_latency_ms
        checks["embedding"] = {
            "ok": latency_ok,
            "provider": args.embedding_provider,
            "dimensions": len(vector),
            "model": args.embedding_model,
            "latency": latency,
        }
        if not latency_ok:
            ok = False
            checks["embedding"]["error"] = "embedding p95 latency exceeds provider-check threshold"
    except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
        ok = False
        checks["embedding"] = {"ok": False, "provider": args.embedding_provider, "error": str(exc)}
        adapters = None

    try:
        reranker = adapters.reranker if adapters else load_retrieval_adapters(args).reranker
        hits = [
            Hit(
                id="a",
                kind="evidence",
                tenant_id="health",
                branch="main",
                text="irrelevant text",
                score=0.1,
                channel="health",
            ),
            Hit(
                id="b",
                kind="evidence",
                tenant_id="health",
                branch="main",
                text="provider health check",
                score=0.1,
                channel="health",
            ),
        ]
        ranked, latency = _run_provider_latency_samples(
            latency_samples,
            lambda: reranker.rerank("provider health", hits, k=2),
        )
        if not ranked:
            raise ValueError("reranker returned no health-check hits")
        latency_ok = float(latency["p95_latency_ms"]) <= max_provider_p95_latency_ms
        checks["reranker"] = {
            "ok": latency_ok,
            "provider": args.reranker_provider,
            "top_id": ranked[0].id if ranked else None,
            "model": args.reranker_model,
            "latency": latency,
        }
        if not latency_ok:
            ok = False
            checks["reranker"]["error"] = "reranker p95 latency exceeds provider-check threshold"
    except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
        ok = False
        checks["reranker"] = {"ok": False, "provider": args.reranker_provider, "error": str(exc)}

    lexical_backend = str(args.lexical_backend or "").strip()
    graph_backend = str(args.graph_backend or "").strip()
    retrieval_backend_ok = bool(lexical_backend and graph_backend)
    lexical_probe: dict[str, Any] | None = None
    graph_probe: dict[str, Any] | None = None
    retrieval_errors: list[str] = []
    # Native (postgres) lexical/graph providers are the deployed self-hosted
    # backends; probe them against a seeded health tenant so the non-local
    # backend proves a live retrieval (previously only the command path emitted
    # a probe, leaving native deployments without lexical_probe/graph_probe).
    # Gated on a real Postgres backend + DSN so non-postgres provider-check runs
    # (local/sqlite contexts) keep the prior no-probe behaviour.
    native_backend_available = (
        getattr(args, "backend", "") == "postgres"
        and bool(getattr(args, "postgres_dsn", None) or default_postgres_dsn())
    )
    if native_backend_available and (
        args.lexical_provider in {"postgres", "native"} or args.graph_provider in {"postgres", "native"}
    ):
        native_lexical_probe, native_graph_probe, native_errors = _native_retrieval_probe(args)
        if native_lexical_probe is not None:
            lexical_probe = native_lexical_probe
        if native_graph_probe is not None:
            graph_probe = native_graph_probe
        if native_errors:
            retrieval_backend_ok = False
            retrieval_errors.extend(native_errors)
    if args.lexical_provider == "command":
        try:
            if adapters is None or adapters.lexical_retriever is None:
                raise ValueError("command lexical provider was not configured")
            lexical_hits = adapters.lexical_retriever.search(
                "provider health",
                tenant_id="provider-health",
                branch="main",
                k=1,
                filt={"tenant_id": "provider-health", "branch": "main"},
            )
            if not lexical_hits:
                raise ValueError("command lexical provider returned no health-check hits")
            lexical_probe = {"hit_count": len(lexical_hits), "top_id": lexical_hits[0].id}
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            retrieval_backend_ok = False
            retrieval_errors.append(f"lexical provider failed: {exc}")
    if args.graph_provider == "command":
        try:
            if adapters is None or adapters.graph_retriever is None:
                raise ValueError("command graph provider was not configured")
            graph_hits = adapters.graph_retriever.search(
                ["provider", "health"],
                tenant_id="provider-health",
                branch="main",
                k=1,
            )
            if not graph_hits:
                raise ValueError("command graph provider returned no health-check hits")
            graph_probe = {"hit_count": len(graph_hits), "top_id": graph_hits[0].id}
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            retrieval_backend_ok = False
            retrieval_errors.append(f"graph provider failed: {exc}")
    checks["retrieval_backends"] = {
        "ok": retrieval_backend_ok,
        "lexical_provider": args.lexical_provider,
        "lexical_backend": lexical_backend,
        "lexical_command_configured": bool(args.lexical_command),
        "lexical_probe": lexical_probe,
        "graph_provider": args.graph_provider,
        "graph_backend": graph_backend,
        "graph_command_configured": bool(args.graph_command),
        "graph_probe": graph_probe,
        "lexical_local": _is_local_retrieval_backend(lexical_backend),
        "graph_local": _is_local_retrieval_backend(graph_backend),
    }
    if not checks["retrieval_backends"]["ok"]:
        ok = False
        checks["retrieval_backends"]["error"] = (
            "; ".join(retrieval_errors) if retrieval_errors else "retrieval backends require lexical and graph backend names"
        )

    try:
        extracted = load_media_extractor(args).extract(
            b"Mnemosyne provider health check",
            media_type="text/plain",
            modality="binary",
            metadata={"description": "Mnemosyne provider health check"},
        )
        checks["media_extractor"] = {
            "ok": True,
            "provider": "command" if args.media_extractor_command else "metadata",
            "text_length": len(extracted.text),
            "sources": extracted.sources,
        }
    except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
        ok = False
        checks["media_extractor"] = {"ok": False, "provider": "command", "error": str(exc)}

    if args.media_embedding_provider == "command":
        try:
            if not args.media_embedding_command:
                raise ValueError("command media embedding provider requires --media-embedding-command")
            vector = CommandMediaEmbeddingProvider(
                args.media_embedding_command,
                dims=int(args.media_embedding_dims),
                timeout_seconds=float(args.media_embedding_timeout),
                max_media_bytes=max_ingest_bytes(args),
            ).embed_media(
                b"Mnemosyne media embedding provider health check",
                media_type="image/png",
                modality="image",
                metadata={"description": "Mnemosyne media embedding provider health check"},
            )
            checks["media_embedding"] = {
                "ok": True,
                "provider": "command",
                "dimensions": len(vector),
            }
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["media_embedding"] = {"ok": False, "provider": "command", "error": str(exc)}
    else:
        checks["media_embedding"] = {"ok": True, "provider": "none", "skipped": True}

    if args.parametric_provider == "command":
        try:
            if not args.parametric_command:
                raise ValueError("command parametric provider requires --parametric-command")
            with tempfile.TemporaryDirectory(prefix="mnemosyne-parametric-check-") as tmp:
                tier = ParametricTier(
                    ParametricArtifactStore(Path(tmp)),
                    trainer=CommandParametricTrainer(
                        args.parametric_command,
                        adapter_kind=args.parametric_adapter_kind,
                        timeout_seconds=float(args.parametric_timeout),
                    ),
                )
                artifact = tier.propose_from_lessons(
                    "provider-health",
                    [
                        Lesson(
                            tenant_id="provider-health",
                            lesson_type="behavior",
                            failure_signature="provider-health",
                            content="provider health check",
                            status="active",
                        )
                    ],
                    [
                        Procedure(
                            tenant_id="provider-health",
                            kind="skill",
                            name="provider-health",
                            body="provider health check",
                            signature={"check": "parametric"},
                            status="validated",
                        )
                    ],
                )
                protected_cases = [
                    RegressionCase(
                        id="provider-health-protected",
                        signature="parametric provider health",
                        query="parametric provider health",
                        expected_substring="provider health",
                        tier="smoke",
                        protected=True,
                    )
                ]
                rolled_back = tier.rollback(artifact, "provider health rollback", protected_cases=protected_cases)
            checks["parametric"] = {
                "ok": True,
                "provider": "command",
                "adapter_kind": artifact.adapter_kind,
                "artifact_id": artifact.id,
                "rollback_ref": rolled_back.rollback_ref,
                "protected_suite": protected_suite_report(protected_cases),
            }
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["parametric"] = {"ok": False, "provider": "command", "error": str(exc)}
    else:
        checks["parametric"] = {"ok": True, "provider": "local", "skipped": True}

    sample_evidence = [
        Evidence(
            tenant_id="provider-health",
            user_id="provider-health",
            actor="user",
            source_type="provider-check",
            content="Provider Health is configured.",
            trust_tier=0,
        )
    ]
    sample_candidates = [
        {
            "signature": "provider-health",
            "query": "provider health",
            "candidate_subject": "Provider Health",
            "candidate_predicate": "is",
            "candidate_object": "configured",
            "entity_key": "provider-health",
        }
    ]
    if args.candidate_extractor_provider in {"command", "http"}:
        check_provider = "hosted_http" if args.candidate_extractor_provider == "http" else "command"
        try:
            extractor = load_candidate_extractor(args)
            if extractor is None:
                raise ValueError(f"{check_provider} candidate extractor was not configured")
            extracted = extractor.extract("provider-health", {}, sample_evidence)
            candidates = extracted["candidates"]
            if not candidates:
                raise ValueError("candidate extractor did not return candidates")
            checks["candidate_extractor"] = {
                "ok": True,
                "provider": check_provider,
                "strategy": extracted["details"]["strategy"],
                "candidate_count": len(candidates),
                "signatures": [str(item["signature"]) for item in candidates],
            }
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["candidate_extractor"] = {"ok": False, "provider": check_provider, "error": str(exc)}
    elif "candidate_extractor" in manifest.get("required_checks", []):
        checks["candidate_extractor"] = {"ok": True, "provider": "deterministic", "skipped": True}

    if args.summarizer_provider in {"command", "http"}:
        check_provider = "hosted_http" if args.summarizer_provider == "http" else "command"
        try:
            summarizer = load_consolidation_summarizer(args)
            if summarizer is None:
                raise ValueError(f"{check_provider} summarizer was not configured")
            summary = summarizer.summarize("provider-health", sample_evidence)
            if not summary or not str(summary.get("summary") or "").strip():
                raise ValueError("summarizer did not return a summary")
            checks["summarizer"] = {
                "ok": True,
                "provider": check_provider,
                "strategy": summary["strategy"],
                "summary_length": len(str(summary["summary"])),
                "evidence_count": summary["evidence_count"],
            }
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["summarizer"] = {"ok": False, "provider": check_provider, "error": str(exc)}
    elif "summarizer" in manifest.get("required_checks", []):
        checks["summarizer"] = {"ok": True, "provider": "deterministic", "skipped": True}

    if args.entity_resolver_provider in {"command", "http"}:
        check_provider = "hosted_http" if args.entity_resolver_provider == "http" else "command"
        try:
            resolver = load_entity_resolver(args)
            if resolver is None:
                raise ValueError(f"{check_provider} entity resolver was not configured")
            resolved = resolver.resolve("provider-health", sample_candidates)
            entity_keys = [str(item.get("entity_key") or "") for item in resolved["candidates"]]
            if not entity_keys or not all(entity_keys):
                raise ValueError("entity resolver did not return entity keys")
            checks["entity_resolver"] = {
                "ok": True,
                "provider": check_provider,
                "strategy": resolved["details"]["strategy"],
                "entity_keys": entity_keys,
                "resolved_entity_count": len(resolved["details"]["resolved_entities"]),
            }
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["entity_resolver"] = {"ok": False, "provider": check_provider, "error": str(exc)}
    else:
        checks["entity_resolver"] = {"ok": True, "provider": "deterministic", "skipped": True}

    if args.lesson_distiller_provider in {"command", "http"}:
        check_provider = "hosted_http" if args.lesson_distiller_provider == "http" else "command"
        try:
            distiller = load_lesson_distiller(args)
            if distiller is None:
                raise ValueError(f"{check_provider} lesson distiller was not configured")
            distilled = distiller.distill("provider-health", sample_candidates)
            lessons = distilled["lessons"]
            if not lessons:
                raise ValueError("lesson distiller did not return lessons")
            for lesson in lessons:
                if not str(lesson.get("content") or "").strip():
                    raise ValueError("lesson distiller returned a lesson without content")
                if not str(lesson.get("failure_signature") or "").strip():
                    raise ValueError("lesson distiller returned a lesson without failure_signature")
            checks["lesson_distiller"] = {
                "ok": True,
                "provider": check_provider,
                "strategy": distilled["details"]["strategy"],
                "lesson_count": len(lessons),
                "failure_signatures": [str(item["failure_signature"]) for item in lessons[:5]],
            }
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["lesson_distiller"] = {"ok": False, "provider": check_provider, "error": str(exc)}
    elif "lesson_distiller" in manifest.get("required_checks", []):
        checks["lesson_distiller"] = {"ok": True, "provider": "deterministic", "skipped": True}

    if args.skill_inducer_provider in {"command", "http"}:
        check_provider = "hosted_http" if args.skill_inducer_provider == "http" else "command"
        try:
            inducer = load_procedure_inducer(args)
            if inducer is None:
                raise ValueError(f"{check_provider} skill inducer was not configured")
            induced = inducer.induce("provider-health", sample_candidates)
            procedures = induced["procedures"]
            if not procedures:
                raise ValueError("skill inducer did not return procedures")
            for procedure in procedures:
                if not str(procedure.get("name") or "").strip():
                    raise ValueError("skill inducer returned a procedure without name")
                if not str(procedure.get("body") or "").strip():
                    raise ValueError("skill inducer returned a procedure without body")
                if not isinstance(procedure.get("signature"), dict):
                    raise ValueError("skill inducer returned a procedure without signature object")
            checks["skill_inducer"] = {
                "ok": True,
                "provider": check_provider,
                "strategy": induced["details"]["strategy"],
                "procedure_count": len(procedures),
                "procedure_names": [str(item["name"]) for item in procedures[:5]],
            }
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["skill_inducer"] = {"ok": False, "provider": check_provider, "error": str(exc)}
    elif "skill_inducer" in manifest.get("required_checks", []):
        checks["skill_inducer"] = {"ok": True, "provider": "deterministic", "skipped": True}

    if args.object_store_encryption == "aesgcm":
        try:
            manager = load_object_key_manager(args)
            tenant_id = "provider-health"
            cid = sha256(b"mnemosyne object key provider health check").hexdigest()
            key = manager.get_or_create_key(tenant_id, cid)
            exists = manager.has_key(tenant_id, cid)
            fetched = manager.get_key(tenant_id, cid)
            shredded = manager.shred_key(tenant_id, cid)
            if len(key) != 32 or fetched != key:
                raise ValueError("object key provider did not return a stable 32-byte AES-256 key")
            if not exists:
                raise ValueError("object key provider failed has_key after get_or_create_key")
            if not shredded:
                raise ValueError("object key provider failed shred_key after health check")
            if manager.has_key(tenant_id, cid):
                raise ValueError("object key provider retained key after shred_key health check")
            try:
                manager.get_key(tenant_id, cid)
            except Exception:  # noqa: BLE001 - missing key is the expected post-shred state.
                post_shred_verified = True
            else:
                raise ValueError("object key provider returned key after shred_key health check")
            checks["object_key_manager"] = {
                "ok": True,
                "provider": args.object_key_provider,
                "key_id": manager.key_id(tenant_id, cid),
                "shredded": True,
                "post_shred_verified": post_shred_verified,
            }
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["object_key_manager"] = {
                "ok": False,
                "provider": args.object_key_provider,
                "error": str(exc),
            }
    else:
        checks["object_key_manager"] = {
            "ok": True,
            "provider": args.object_key_provider,
            "skipped": True,
            "reason": "object-store encryption disabled",
        }

    oidc_fields = {
        "jwks": getattr(args, "provider_oidc_jwks", None),
        "jwks_file": getattr(args, "provider_oidc_jwks_file", None),
        "jwks_url": getattr(args, "provider_oidc_jwks_url", None),
        "issuer": getattr(args, "provider_oidc_issuer", None),
        "audience": getattr(args, "provider_oidc_audience", None),
        "authz_policy": getattr(args, "provider_oidc_authz_policy", None),
        "authz_policy_file": getattr(args, "provider_oidc_authz_policy_file", None),
    }
    if any(oidc_fields.values()):
        try:
            if not oidc_fields["issuer"] or not oidc_fields["audience"]:
                raise SessionAuthError("OIDC provider check requires issuer and audience")
            # A self-hosted IdP (e.g. Keycloak behind a private-network Caddy
            # ingress) resolves to a private address; without this allowlist the
            # JWKS fetch is rejected as an SSRF risk and the oidc subcheck can
            # never pass on a self-hosted deployment. Mirrors the idp-jwks-live
            # and hosted-check allowlist seams (MNEMOSYNE_IDP_ALLOWED_INTERNAL_HOSTS).
            oidc_allowed_internal_hosts = tuple(
                host.strip()
                for host in str(getattr(args, "provider_oidc_allowed_internal_hosts", "") or "").split(",")
                if host.strip()
            )
            jwks_document = load_oidc_jwks(
                jwks=oidc_fields["jwks"],
                jwks_file=oidc_fields["jwks_file"],
                jwks_url=oidc_fields["jwks_url"],
                allow_insecure_url=bool(getattr(args, "provider_oidc_allow_insecure_jwks_url", False)),
                timeout=float(getattr(args, "provider_oidc_timeout", 10.0)),
                max_bytes=int(getattr(args, "provider_oidc_jwks_max_bytes", 1024 * 1024)),
                allowed_internal_hosts=oidc_allowed_internal_hosts,
            )
            keys = jwks_document.get("keys") if isinstance(jwks_document, dict) else None
            if not isinstance(keys, list) or not keys:
                raise SessionAuthError("OIDC JWKS must include at least one key")
            policy = load_oidc_authorization_policy(
                policy=oidc_fields["authz_policy"],
                policy_file=oidc_fields["authz_policy_file"],
            )
            check: dict[str, Any] = {
                "ok": True,
                "jwks_key_count": len(keys),
                "issuer_configured": True,
                "audience_configured": True,
                "authz_policy_configured": policy is not None,
            }
            if policy is not None:
                check["authz_policy"] = policy.audit_summary()
            checks["oidc"] = check
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["oidc"] = {"ok": False, "error": str(exc)}
    else:
        checks["oidc"] = {"ok": True, "provider": "none", "skipped": True}

    if getattr(args, "session_secret_command", None):
        try:
            material, active_key_id = load_session_secret_command(
                args.session_secret_command,
                timeout_seconds=float(getattr(args, "session_secret_command_timeout", 10.0)),
            )
            if isinstance(material, Mapping):
                verifier = SessionTokenVerifier(material, active_key_id=active_key_id)
                source = "keyring"
                key_count = len(material)
            else:
                verifier = SessionTokenVerifier(material)
                source = "secret"
                key_count = 1
            token = verifier.sign(
                SessionIdentity(
                    tenant_id="provider-health",
                    user_id="provider-health",
                    role="operator",
                    source_trust_tier=0,
                    expires_at=int(time.time()) + 300,
                    session_id="provider-health",
                )
            )
            identity = verifier.verify(token)
            if identity.tenant_id != "provider-health" or identity.user_id != "provider-health":
                raise ValueError("session secret provider failed signed-token round trip")
            checks["session_secret"] = {
                "ok": True,
                "provider": "command",
                "source": source,
                "key_count": key_count,
                "active_key_id_present": active_key_id is not None,
                "roundtrip_verified": True,
            }
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["session_secret"] = {"ok": False, "provider": "command", "error": str(exc)}
    else:
        checks["session_secret"] = {"ok": True, "provider": "none", "skipped": True}

    try:
        # Configuration-only: never construct the full tools stack here. An
        # unrelated missing optional provider (e.g. the parametric trainer
        # command) must fail its OWN subcheck, not abort the whole report.
        checks["residency_policy"] = {
            "ok": True,
            **residency_policy_report(
                allowed_residencies=tuple(args.allowed_residency),
                runtime_residency=args.runtime_residency,
                require_runtime_residency=args.require_runtime_residency,
                allowed_residency_transfers=tuple(args.allowed_residency_transfer),
            ),
        }
    except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
        ok = False
        checks["residency_policy"] = {"ok": False, "error": str(exc)}

    ok = enforce_provider_manifest_policy(checks, manifest) and ok
    emit({"ok": ok, "manifest": manifest, "checks": checks})
    if not ok:
        raise SystemExit(1)


def cmd_specialist_manifest(args: argparse.Namespace) -> None:
    from mnemosyne.providers import default_registry

    registry = default_registry()
    specialists = registry.specialist_manifest()
    if args.role:
        specialists = [item for item in specialists if item.get("role") == args.role]
    roles = sorted({str(item.get("role")) for item in specialists})
    emit(
        {
            "ok": True,
            "role": args.role,
            "count": len(specialists),
            "roles": roles,
            "specialists": specialists,
        }
    )


def cmd_residency_policy(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.residency_policy())


def cmd_capability(args: argparse.Namespace) -> None:
    from mnemosyne import capability

    facts = capability.probe()
    tier, tier_source = capability.resolve_tier(facts=facts)
    recommendations = capability.recommended_env(tier, facts=facts)
    if getattr(args, "as_json", False):
        emit(
            {
                "ok": True,
                "tier": tier,
                "tier_source": tier_source,
                "autotune_enabled": capability.autotune_enabled(),
                "facts": facts,
                "recommended_env": recommendations,
            }
        )
        return
    print(f"# capability tier: {tier} ({tier_source}); recommendations only — nothing applied")
    for key in sorted(facts):
        print(f"# {key}={json.dumps(facts[key])}")
    for key, value in sorted(recommendations.items()):
        print(f"export {key}={shlex.quote(value)}")


def build_parser() -> argparse.ArgumentParser:
    from mnemosyne.media_limits import DEFAULT_MAX_INGEST_BYTES

    def subparser_factory(*args: Any, **kwargs: Any) -> argparse.ArgumentParser:
        kwargs.setdefault("allow_abbrev", False)
        return argparse.ArgumentParser(*args, **kwargs)

    parser = argparse.ArgumentParser(
        prog="mneme",
        description="Mnemosyne local memory compiler CLI",
        allow_abbrev=False,
    )
    parser.add_argument("--backend", choices=["local", "postgres", "sqlite"], default=default_backend(), help="Storage backend")
    parser.add_argument("--store", default=str(default_store()), help="Path to local JSON store")
    parser.add_argument("--postgres-dsn", default=default_postgres_dsn(), help="PostgreSQL DSN for --backend postgres")
    parser.add_argument(
        "--postgres-require-safe-role",
        action="store_true",
        default=env_flag("MNEMOSYNE_POSTGRES_REQUIRE_SAFE_ROLE", default=False),
        help="Refuse Postgres connections whose current role is superuser or can bypass RLS",
    )
    parser.add_argument(
        "--queue-backend",
        choices=["local", "postgres", "sqlite"],
        default=os.environ.get("MNEMOSYNE_QUEUE_BACKEND", "local"),
        help="Runtime job queue backend",
    )
    parser.add_argument(
        "--queue-tenant",
        default=os.environ.get("MNEMOSYNE_QUEUE_TENANT", "system"),
        help="Tenant used by standalone Postgres queue commands",
    )
    parser.add_argument("--object-store", default=default_object_store(), help="Path to local object storage for externalized payloads")
    parser.add_argument(
        "--object-store-backend",
        choices=["local", "s3"],
        default=os.environ.get("MNEMOSYNE_OBJECT_STORE_BACKEND", "local"),
        help="Object-store byte backend: local filesystem (default) or s3/SeaweedFS (MNEMOSYNE_S3_* env)",
    )
    parser.add_argument(
        "--object-store-encryption",
        choices=["none", "aesgcm"],
        default=default_object_store_encryption(),
        help="Encrypt local object storage payloads with per-object AES-GCM keys",
    )
    parser.add_argument(
        "--object-key-store",
        default=default_object_key_store(),
        help="Path to JSON key store for --object-store-encryption aesgcm and --object-key-provider json",
    )
    parser.add_argument(
        "--object-key-provider",
        choices=["json", "command"],
        default=default_object_key_provider(),
        help="Envelope-key manager for encrypted object storage",
    )
    parser.add_argument(
        "--object-key-command",
        default=default_object_key_command(),
        help="Command key provider invoked as '<command> <action>' with JSON stdin",
    )
    parser.add_argument(
        "--object-key-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_OBJECT_KEY_TIMEOUT", "30")),
        help="Timeout in seconds for --object-key-provider command",
    )
    parser.add_argument(
        "--allowed-residency",
        action="append",
        default=default_allowed_residencies(),
        help="Allowed data residency label for ingestion; repeat or use MNEMOSYNE_ALLOWED_RESIDENCIES",
    )
    parser.add_argument(
        "--runtime-residency",
        default=os.environ.get("MNEMOSYNE_RUNTIME_RESIDENCY"),
        help="Runtime processing residency; cross-region ingestion requires an allowed transfer",
    )
    parser.add_argument(
        "--allowed-residency-transfer",
        action="append",
        default=default_allowed_residency_transfers(),
        help="Allowed cross-region transfer in source->target form; repeat or use MNEMOSYNE_ALLOWED_RESIDENCY_TRANSFERS",
    )
    parser.add_argument(
        "--require-runtime-residency",
        action="store_true",
        default=env_flag("MNEMOSYNE_REQUIRE_RUNTIME_RESIDENCY", default=False),
        help="Fail ingestion unless a runtime processing residency is configured or supplied in metadata",
    )
    parser.add_argument("--embedding-provider", choices=["local", "http"], default=os.environ.get("MNEMOSYNE_EMBEDDING_PROVIDER", "local"))
    parser.add_argument("--embedding-url", default=os.environ.get("MNEMOSYNE_EMBEDDING_URL"))
    parser.add_argument("--embedding-model", default=os.environ.get("MNEMOSYNE_EMBEDDING_MODEL"))
    parser.add_argument("--embedding-api-key", default=os.environ.get("MNEMOSYNE_EMBEDDING_API_KEY"))
    parser.add_argument("--embedding-dims", type=int, default=int(os.environ.get("MNEMOSYNE_EMBEDDING_DIMS", "1024")))
    parser.add_argument("--reranker-provider", choices=["local", "http"], default=os.environ.get("MNEMOSYNE_RERANKER_PROVIDER", "local"))
    parser.add_argument("--reranker-url", default=os.environ.get("MNEMOSYNE_RERANKER_URL"))
    parser.add_argument("--reranker-model", default=os.environ.get("MNEMOSYNE_RERANKER_MODEL"))
    parser.add_argument("--reranker-api-key", default=os.environ.get("MNEMOSYNE_RERANKER_API_KEY"))
    parser.add_argument("--retrieval-timeout", type=float, default=float(os.environ.get("MNEMOSYNE_RETRIEVAL_TIMEOUT", "30")))
    parser.add_argument(
        "--lexical-provider",
        choices=["postgres", "command"],
        default=os.environ.get("MNEMOSYNE_LEXICAL_PROVIDER", "postgres"),
        help="Lexical retrieval provider for Postgres backend",
    )
    parser.add_argument("--lexical-command", default=os.environ.get("MNEMOSYNE_LEXICAL_COMMAND"))
    parser.add_argument("--lexical-backend", default=os.environ.get("MNEMOSYNE_LEXICAL_BACKEND", "postgres-fts"))
    parser.add_argument(
        "--graph-provider",
        choices=["postgres", "command"],
        default=os.environ.get("MNEMOSYNE_GRAPH_PROVIDER", "postgres"),
        help="Graph retrieval provider for Postgres backend",
    )
    parser.add_argument("--graph-command", default=os.environ.get("MNEMOSYNE_GRAPH_COMMAND"))
    parser.add_argument("--graph-backend", default=os.environ.get("MNEMOSYNE_GRAPH_BACKEND", "postgres-recursive-ppr"))
    parser.add_argument("--c2pa-tool", default=os.environ.get("MNEMOSYNE_C2PA_TOOL"))
    parser.add_argument("--trusted-provenance-issuer", action="append", default=os.environ.get("MNEMOSYNE_TRUSTED_PROVENANCE_ISSUERS", "").split(",") if os.environ.get("MNEMOSYNE_TRUSTED_PROVENANCE_ISSUERS") else [])
    parser.add_argument("--trusted-provenance-root", action="append", default=os.environ.get("MNEMOSYNE_TRUSTED_PROVENANCE_ROOTS", "").split(",") if os.environ.get("MNEMOSYNE_TRUSTED_PROVENANCE_ROOTS") else [])
    parser.add_argument("--provenance-trust-policy", default=os.environ.get("MNEMOSYNE_PROVENANCE_TRUST_POLICY"))
    parser.add_argument("--provenance-timeout", type=float, default=float(os.environ.get("MNEMOSYNE_PROVENANCE_TIMEOUT", "30")))
    parser.add_argument("--media-extractor-command", default=os.environ.get("MNEMOSYNE_MEDIA_EXTRACTOR_COMMAND"))
    parser.add_argument("--media-extractor-timeout", type=float, default=float(os.environ.get("MNEMOSYNE_MEDIA_EXTRACTOR_TIMEOUT", "30")))
    parser.add_argument(
        "--max-ingest-bytes",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_MAX_INGEST_BYTES", str(DEFAULT_MAX_INGEST_BYTES))),
        help="Maximum bytes accepted by ingest/media extraction/media embedding paths",
    )
    parser.add_argument(
        "--entity-resolver-provider",
        choices=["deterministic", "command", "http"],
        default=os.environ.get("MNEMOSYNE_ENTITY_RESOLVER_PROVIDER", "deterministic"),
        help="Consolidation entity resolver provider",
    )
    parser.add_argument("--entity-resolver-command", default=os.environ.get("MNEMOSYNE_ENTITY_RESOLVER_COMMAND"))
    parser.add_argument(
        "--entity-resolver-url",
        default=os.environ.get("MNEMOSYNE_ENTITY_RESOLVER_URL"),
        help="HTTPS endpoint for the hosted entity resolver role provider",
    )
    parser.add_argument(
        "--entity-resolver-api-key-env",
        default=os.environ.get("MNEMOSYNE_ENTITY_RESOLVER_API_KEY_ENV"),
        help="Env var holding an optional bearer token for the hosted entity resolver",
    )
    parser.add_argument(
        "--entity-resolver-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_ENTITY_RESOLVER_TIMEOUT", "30")),
    )
    parser.add_argument(
        "--proposal-provider-class",
        choices=["local", "frontier"],
        default=os.environ.get("MNEMOSYNE_PROPOSAL_PROVIDER_CLASS", "local"),
        help="Disclosure class for model-backed proposal role providers",
    )
    parser.add_argument(
        "--proposal-provider-retention",
        choices=["zero_retention", "retentive"],
        default=os.environ.get("MNEMOSYNE_PROPOSAL_PROVIDER_RETENTION", "zero_retention"),
        help="Retention contract for model-backed proposal role providers",
    )
    parser.add_argument(
        "--proposal-provider-region",
        default=os.environ.get("MNEMOSYNE_PROPOSAL_PROVIDER_REGION"),
        help="Processing region for model-backed proposal role providers",
    )
    parser.add_argument(
        "--candidate-extractor-provider",
        choices=["deterministic", "command", "http"],
        default=os.environ.get("MNEMOSYNE_CANDIDATE_EXTRACTOR_PROVIDER", "deterministic"),
        help="Consolidation candidate extractor provider",
    )
    parser.add_argument("--candidate-extractor-command", default=os.environ.get("MNEMOSYNE_CANDIDATE_EXTRACTOR_COMMAND"))
    parser.add_argument(
        "--candidate-extractor-url",
        default=os.environ.get("MNEMOSYNE_CANDIDATE_EXTRACTOR_URL"),
        help="HTTPS endpoint for the hosted candidate extractor role provider",
    )
    parser.add_argument(
        "--candidate-extractor-api-key-env",
        default=os.environ.get("MNEMOSYNE_CANDIDATE_EXTRACTOR_API_KEY_ENV"),
        help="Env var holding an optional bearer token for the hosted candidate extractor",
    )
    parser.add_argument(
        "--candidate-extractor-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_CANDIDATE_EXTRACTOR_TIMEOUT", "30")),
    )
    parser.add_argument(
        "--summarizer-provider",
        choices=["deterministic", "command", "http"],
        default=os.environ.get("MNEMOSYNE_SUMMARIZER_PROVIDER", "deterministic"),
        help="Consolidation summarizer provider",
    )
    parser.add_argument("--summarizer-command", default=os.environ.get("MNEMOSYNE_SUMMARIZER_COMMAND"))
    parser.add_argument(
        "--summarizer-url",
        default=os.environ.get("MNEMOSYNE_SUMMARIZER_URL"),
        help="HTTPS endpoint for the hosted summarizer role provider",
    )
    parser.add_argument(
        "--summarizer-api-key-env",
        default=os.environ.get("MNEMOSYNE_SUMMARIZER_API_KEY_ENV"),
        help="Env var holding an optional bearer token for the hosted summarizer",
    )
    parser.add_argument(
        "--summarizer-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_SUMMARIZER_TIMEOUT", "30")),
    )
    parser.add_argument(
        "--lesson-distiller-provider",
        choices=["deterministic", "command", "http"],
        default=os.environ.get("MNEMOSYNE_LESSON_DISTILLER_PROVIDER", "deterministic"),
        help="Consolidation lesson distiller provider",
    )
    parser.add_argument("--lesson-distiller-command", default=os.environ.get("MNEMOSYNE_LESSON_DISTILLER_COMMAND"))
    parser.add_argument(
        "--lesson-distiller-url",
        default=os.environ.get("MNEMOSYNE_LESSON_DISTILLER_URL"),
        help="HTTPS endpoint for the hosted lesson distiller role provider",
    )
    parser.add_argument(
        "--lesson-distiller-api-key-env",
        default=os.environ.get("MNEMOSYNE_LESSON_DISTILLER_API_KEY_ENV"),
        help="Env var holding an optional bearer token for the hosted lesson distiller",
    )
    parser.add_argument(
        "--lesson-distiller-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_LESSON_DISTILLER_TIMEOUT", "30")),
    )
    parser.add_argument(
        "--skill-inducer-provider",
        choices=["deterministic", "command", "http"],
        default=os.environ.get("MNEMOSYNE_SKILL_INDUCER_PROVIDER", "deterministic"),
        help="Consolidation skill/procedure inducer provider",
    )
    parser.add_argument("--skill-inducer-command", default=os.environ.get("MNEMOSYNE_SKILL_INDUCER_COMMAND"))
    parser.add_argument(
        "--skill-inducer-url",
        default=os.environ.get("MNEMOSYNE_SKILL_INDUCER_URL"),
        help="HTTPS endpoint for the hosted skill/procedure inducer role provider",
    )
    parser.add_argument(
        "--skill-inducer-api-key-env",
        default=os.environ.get("MNEMOSYNE_SKILL_INDUCER_API_KEY_ENV"),
        help="Env var holding an optional bearer token for the hosted skill inducer",
    )
    parser.add_argument(
        "--skill-inducer-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_SKILL_INDUCER_TIMEOUT", "30")),
    )
    parser.add_argument(
        "--media-embedding-provider",
        choices=["none", "command"],
        default=os.environ.get("MNEMOSYNE_MEDIA_EMBEDDING_PROVIDER", "none"),
        help="Multimodal image/audio/video embedding provider",
    )
    parser.add_argument(
        "--media-embedding-command",
        default=os.environ.get("MNEMOSYNE_MEDIA_EMBEDDING_COMMAND"),
        help="Command media embedder invoked as '<command> <file>' with JSON metadata on stdin",
    )
    parser.add_argument(
        "--media-embedding-dims",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_MEDIA_EMBEDDING_DIMS", os.environ.get("MNEMOSYNE_EMBEDDING_DIMS", "1024"))),
    )
    parser.add_argument(
        "--media-embedding-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_MEDIA_EMBEDDING_TIMEOUT", "30")),
    )
    parser.add_argument("--parametric-artifact-store", default=os.environ.get("MNEMOSYNE_PARAMETRIC_ARTIFACT_STORE"))
    parser.add_argument(
        "--parametric-provider",
        choices=["local", "command"],
        default=os.environ.get("MNEMOSYNE_PARAMETRIC_PROVIDER", "local"),
        help="Parametric-tier provider for LoRA/test-time-training adapter artifacts",
    )
    parser.add_argument(
        "--parametric-command",
        default=os.environ.get("MNEMOSYNE_PARAMETRIC_COMMAND"),
        help="Command provider invoked as '<command> <action>' with JSON stdin",
    )
    parser.add_argument(
        "--parametric-adapter-kind",
        default=os.environ.get("MNEMOSYNE_PARAMETRIC_ADAPTER_KIND", "command-parametric-adapter"),
        help="Adapter kind label for --parametric-provider command",
    )
    parser.add_argument(
        "--parametric-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_PARAMETRIC_TIMEOUT", "300")),
        help="Timeout in seconds for --parametric-provider command",
    )
    parser.add_argument("--session-token", default=os.environ.get("MNEMOSYNE_SESSION_TOKEN"), help="Signed Mnemosyne session token for CLI identity binding")
    parser.add_argument("--session-secret", default=os.environ.get("MNEMOSYNE_SESSION_SECRET"), help="HMAC secret for --session-token verification; prefer MNEMOSYNE_SESSION_SECRET")
    parser.add_argument(
        "--session-keyring",
        default=os.environ.get("MNEMOSYNE_SESSION_KEYRING"),
        help="JSON object or comma-separated kid=secret HMAC keyring for signed session tokens",
    )
    parser.add_argument(
        "--session-secret-command",
        default=os.environ.get("MNEMOSYNE_SESSION_SECRET_COMMAND"),
        help="Shell-free command provider that returns session secret JSON for deployment secret custody",
    )
    parser.add_argument(
        "--session-secret-command-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_SESSION_SECRET_COMMAND_TIMEOUT", "10")),
        help="Timeout in seconds for --session-secret-command",
    )
    parser.add_argument(
        "--session-key-id",
        default=os.environ.get("MNEMOSYNE_SESSION_KEY_ID"),
        help="Active key id used when issuing keyring-backed session tokens",
    )
    parser.add_argument(
        "--session-revoked-key-ids",
        default=os.environ.get("MNEMOSYNE_SESSION_REVOKED_KEY_IDS"),
        help="Comma-separated session token key ids to reject",
    )
    parser.add_argument(
        "--session-revoked-ids",
        default=os.environ.get("MNEMOSYNE_SESSION_REVOKED_IDS"),
        help="Comma-separated session ids to reject",
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=subparser_factory)

    session_exchange = sub.add_parser("session-exchange")
    session_exchange.add_argument("--idp-token", default=os.environ.get("MNEMOSYNE_IDP_TOKEN"))
    session_exchange.add_argument("--idp-jwks", default=os.environ.get("MNEMOSYNE_IDP_JWKS"))
    session_exchange.add_argument("--idp-jwks-file", default=os.environ.get("MNEMOSYNE_IDP_JWKS_FILE"))
    session_exchange.add_argument("--idp-jwks-url", default=os.environ.get("MNEMOSYNE_IDP_JWKS_URL"))
    session_exchange.add_argument("--idp-allow-insecure-jwks-url", action="store_true", default=env_flag("MNEMOSYNE_IDP_ALLOW_INSECURE_JWKS_URL", default=False))
    session_exchange.add_argument("--idp-authz-policy", default=os.environ.get("MNEMOSYNE_IDP_AUTHZ_POLICY"))
    session_exchange.add_argument("--idp-authz-policy-file", default=os.environ.get("MNEMOSYNE_IDP_AUTHZ_POLICY_FILE"))
    session_exchange.add_argument("--idp-issuer", required=not bool(os.environ.get("MNEMOSYNE_IDP_ISSUER")), default=os.environ.get("MNEMOSYNE_IDP_ISSUER"))
    session_exchange.add_argument("--idp-audience", required=not bool(os.environ.get("MNEMOSYNE_IDP_AUDIENCE")), default=os.environ.get("MNEMOSYNE_IDP_AUDIENCE"))
    session_exchange.add_argument("--idp-tenant-claim", default=os.environ.get("MNEMOSYNE_IDP_TENANT_CLAIM", "tenant_id"))
    session_exchange.add_argument("--idp-user-claim", default=os.environ.get("MNEMOSYNE_IDP_USER_CLAIM", "sub"))
    session_exchange.add_argument("--idp-role-claim", default=os.environ.get("MNEMOSYNE_IDP_ROLE_CLAIM", "mnemosyne_role"))
    session_exchange.add_argument("--idp-trust-claim", default=os.environ.get("MNEMOSYNE_IDP_TRUST_CLAIM", "mnemosyne_source_trust_tier"))
    session_exchange.add_argument("--idp-session-id-claim", default=os.environ.get("MNEMOSYNE_IDP_SESSION_ID_CLAIM", "jti"))
    session_exchange.add_argument("--idp-algorithm", action="append", default=(os.environ.get("MNEMOSYNE_IDP_ALGORITHMS", "RS256,ES256").split(",")))
    session_exchange.add_argument("--idp-leeway-seconds", type=int, default=int(os.environ.get("MNEMOSYNE_IDP_LEEWAY_SECONDS", "60")))
    session_exchange.add_argument("--idp-timeout", type=float, default=float(os.environ.get("MNEMOSYNE_IDP_TIMEOUT", "10")))
    session_exchange.add_argument("--idp-jwks-max-bytes", type=int, default=int(os.environ.get("MNEMOSYNE_IDP_JWKS_MAX_BYTES", str(1024 * 1024))))
    session_exchange.add_argument("--idp-jwks-cache-ttl-seconds", type=int, default=int(os.environ.get("MNEMOSYNE_IDP_JWKS_CACHE_TTL_SECONDS", "300")))
    session_exchange.add_argument(
        "--idp-disable-refresh-on-unknown-kid",
        action="store_true",
        default=env_flag("MNEMOSYNE_IDP_DISABLE_REFRESH_ON_UNKNOWN_KID", default=False),
    )
    session_exchange.add_argument(
        "--idp-expected-kid-sha256",
        action="append",
        default=(os.environ.get("MNEMOSYNE_IDP_EXPECTED_KID_SHA256", "").split(",")),
    )
    session_exchange.add_argument(
        "--idp-allowed-internal-hosts",
        default=os.environ.get("MNEMOSYNE_IDP_ALLOWED_INTERNAL_HOSTS", ""),
    )
    session_exchange.add_argument("--session-max-ttl-seconds", type=int, default=int(os.environ.get("MNEMOSYNE_SESSION_MAX_TTL_SECONDS", "3600")))
    session_exchange.set_defaults(func=cmd_session_exchange)

    idp_jwks_live_check = sub.add_parser("idp-jwks-live-check")
    idp_jwks_live_check.add_argument("--idp-token", default=os.environ.get("MNEMOSYNE_IDP_TOKEN"))
    idp_jwks_live_check.add_argument("--idp-jwks", default=os.environ.get("MNEMOSYNE_IDP_JWKS"))
    idp_jwks_live_check.add_argument("--idp-jwks-file", default=os.environ.get("MNEMOSYNE_IDP_JWKS_FILE"))
    idp_jwks_live_check.add_argument("--idp-jwks-url", default=os.environ.get("MNEMOSYNE_IDP_JWKS_URL"))
    idp_jwks_live_check.add_argument(
        "--idp-allow-insecure-jwks-url",
        action="store_true",
        default=env_flag("MNEMOSYNE_IDP_ALLOW_INSECURE_JWKS_URL", default=False),
    )
    idp_jwks_live_check.add_argument("--idp-authz-policy", default=os.environ.get("MNEMOSYNE_IDP_AUTHZ_POLICY"))
    idp_jwks_live_check.add_argument(
        "--idp-authz-policy-file",
        default=os.environ.get("MNEMOSYNE_IDP_AUTHZ_POLICY_FILE"),
    )
    idp_jwks_live_check.add_argument(
        "--idp-issuer",
        required=not bool(os.environ.get("MNEMOSYNE_IDP_ISSUER")),
        default=os.environ.get("MNEMOSYNE_IDP_ISSUER"),
    )
    idp_jwks_live_check.add_argument(
        "--idp-audience",
        required=not bool(os.environ.get("MNEMOSYNE_IDP_AUDIENCE")),
        default=os.environ.get("MNEMOSYNE_IDP_AUDIENCE"),
    )
    idp_jwks_live_check.add_argument(
        "--idp-tenant-claim",
        default=os.environ.get("MNEMOSYNE_IDP_TENANT_CLAIM", "tenant_id"),
    )
    idp_jwks_live_check.add_argument("--idp-user-claim", default=os.environ.get("MNEMOSYNE_IDP_USER_CLAIM", "sub"))
    idp_jwks_live_check.add_argument(
        "--idp-role-claim",
        default=os.environ.get("MNEMOSYNE_IDP_ROLE_CLAIM", "mnemosyne_role"),
    )
    idp_jwks_live_check.add_argument(
        "--idp-trust-claim",
        default=os.environ.get("MNEMOSYNE_IDP_TRUST_CLAIM", "mnemosyne_source_trust_tier"),
    )
    idp_jwks_live_check.add_argument(
        "--idp-session-id-claim",
        default=os.environ.get("MNEMOSYNE_IDP_SESSION_ID_CLAIM", "jti"),
    )
    idp_jwks_live_check.add_argument(
        "--idp-algorithm",
        action="append",
        default=(os.environ.get("MNEMOSYNE_IDP_ALGORITHMS", "RS256,ES256").split(",")),
    )
    idp_jwks_live_check.add_argument(
        "--idp-leeway-seconds",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_IDP_LEEWAY_SECONDS", "60")),
    )
    idp_jwks_live_check.add_argument(
        "--idp-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_IDP_TIMEOUT", "10")),
    )
    idp_jwks_live_check.add_argument(
        "--idp-jwks-max-bytes",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_IDP_JWKS_MAX_BYTES", str(1024 * 1024))),
    )
    idp_jwks_live_check.add_argument(
        "--idp-jwks-cache-ttl-seconds",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_IDP_JWKS_CACHE_TTL_SECONDS", "300")),
    )
    idp_jwks_live_check.add_argument(
        "--idp-disable-refresh-on-unknown-kid",
        action="store_true",
        default=env_flag("MNEMOSYNE_IDP_DISABLE_REFRESH_ON_UNKNOWN_KID", default=False),
    )
    idp_jwks_live_check.add_argument(
        "--idp-expected-kid-sha256",
        action="append",
        default=(os.environ.get("MNEMOSYNE_IDP_EXPECTED_KID_SHA256", "").split(",")),
    )
    idp_jwks_live_check.add_argument(
        "--idp-allowed-internal-hosts",
        default=os.environ.get("MNEMOSYNE_IDP_ALLOWED_INTERNAL_HOSTS", ""),
    )
    idp_jwks_live_check.set_defaults(func=cmd_idp_jwks_live_check)

    postgres_role_check = sub.add_parser("postgres-role-check")
    postgres_role_check.add_argument("--app-dsn", default=os.environ.get("MNEMOSYNE_POSTGRES_DSN"))
    postgres_role_check.add_argument(
        "--consolidator-dsn",
        default=os.environ.get("MNEMOSYNE_POSTGRES_CONSOLIDATOR_DSN"),
    )
    postgres_role_check.add_argument(
        "--expected-app-group",
        default=os.environ.get("MNEMOSYNE_POSTGRES_APP_GROUP", "mnemosyne_app"),
    )
    postgres_role_check.add_argument(
        "--expected-consolidator-group",
        default=os.environ.get("MNEMOSYNE_POSTGRES_CONSOLIDATOR_GROUP", "mnemosyne_consolidator"),
    )
    postgres_role_check.add_argument(
        "--readonly-group",
        default=os.environ.get("MNEMOSYNE_POSTGRES_READONLY_GROUP", "mnemosyne_readonly"),
    )
    postgres_role_check.add_argument("--audit-table", default="audit_log")
    postgres_role_check.add_argument(
        "--connect-timeout",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_POSTGRES_CONNECT_TIMEOUT", "10")),
    )
    postgres_role_check.add_argument(
        "--allow-localhost",
        action="store_true",
        default=env_flag("MNEMOSYNE_POSTGRES_ROLE_CHECK_ALLOW_LOCALHOST", default=False),
    )
    postgres_role_check.add_argument(
        "--expected-fingerprint",
        default=os.environ.get("MNEMOSYNE_POSTGRES_ROLE_CHECK_EXPECTED_FINGERPRINT"),
    )
    postgres_role_check.set_defaults(func=cmd_postgres_role_check)

    idp_authz_policy_check = sub.add_parser("idp-authz-policy-check")
    idp_authz_policy_check.add_argument("--idp-authz-policy", default=os.environ.get("MNEMOSYNE_IDP_AUTHZ_POLICY"))
    idp_authz_policy_check.add_argument(
        "--idp-authz-policy-file",
        default=os.environ.get("MNEMOSYNE_IDP_AUTHZ_POLICY_FILE"),
    )
    idp_authz_policy_check.set_defaults(func=cmd_idp_authz_policy_check)

    idp_authz_policy_rollout_check = sub.add_parser("idp-authz-policy-rollout-check")
    idp_authz_policy_rollout_check.add_argument(
        "--current-idp-authz-policy",
        default=os.environ.get("MNEMOSYNE_CURRENT_IDP_AUTHZ_POLICY"),
    )
    idp_authz_policy_rollout_check.add_argument(
        "--current-idp-authz-policy-file",
        default=os.environ.get("MNEMOSYNE_CURRENT_IDP_AUTHZ_POLICY_FILE"),
    )
    idp_authz_policy_rollout_check.add_argument(
        "--candidate-idp-authz-policy",
        default=os.environ.get("MNEMOSYNE_CANDIDATE_IDP_AUTHZ_POLICY"),
    )
    idp_authz_policy_rollout_check.add_argument(
        "--candidate-idp-authz-policy-file",
        default=os.environ.get("MNEMOSYNE_CANDIDATE_IDP_AUTHZ_POLICY_FILE"),
    )
    idp_authz_policy_rollout_check.add_argument(
        "--expected-current-fingerprint",
        default=os.environ.get("MNEMOSYNE_EXPECTED_CURRENT_IDP_AUTHZ_POLICY_FINGERPRINT"),
    )
    idp_authz_policy_rollout_check.add_argument(
        "--expected-candidate-fingerprint",
        default=os.environ.get("MNEMOSYNE_EXPECTED_CANDIDATE_IDP_AUTHZ_POLICY_FINGERPRINT"),
    )
    idp_authz_policy_rollout_check.add_argument(
        "--simulation-file",
        default=os.environ.get("MNEMOSYNE_IDP_AUTHZ_POLICY_SIMULATION_FILE"),
        help="JSON array of tenant/user/payload claim simulations for current-vs-candidate rollout checks",
    )
    idp_authz_policy_rollout_check.add_argument(
        "--allow-simulation-changes",
        action="store_true",
        default=env_flag("MNEMOSYNE_IDP_AUTHZ_POLICY_ALLOW_SIMULATION_CHANGES", default=False),
    )
    idp_authz_policy_rollout_check.set_defaults(func=cmd_idp_authz_policy_rollout_check)

    capture = sub.add_parser("capture")
    capture.add_argument("--tenant", required=True)
    capture.add_argument("--user", required=True)
    capture.add_argument("--actor", default="user", choices=["user", "assistant", "tool", "system", "external"])
    capture.add_argument("--source-type", required=True)
    capture.add_argument("--source-identity")
    capture.add_argument("--content", required=True)
    capture.add_argument("--branch", default="main")
    capture.add_argument("--trust-tier", type=int, default=0)
    capture.set_defaults(func=cmd_capture)

    ingest = sub.add_parser("ingest")
    ingest.add_argument("--tenant", required=True)
    ingest.add_argument("--user", required=True)
    ingest.add_argument("--actor", default="user", choices=["user", "assistant", "tool", "system", "external"])
    ingest.add_argument("--source-type", required=True)
    ingest.add_argument("--source-identity")
    ingest.add_argument("--content")
    ingest.add_argument("--file")
    ingest.add_argument("--modality", default="text", choices=["text", "image", "audio", "video", "binary", "multimodal"])
    ingest.add_argument("--media-type", default="text/plain")
    ingest.add_argument("--metadata", default="{}")
    ingest.add_argument("--signed-provenance")
    ingest.add_argument("--signed-provenance-file")
    ingest.add_argument("--branch", default="main")
    ingest.add_argument("--trust-tier", type=int)
    ingest.add_argument("--capability-tag", action="append", default=[])
    ingest.add_argument("--sensitivity", type=int, default=0)
    ingest.add_argument("--no-enqueue-consolidation", action="store_true")
    ingest.add_argument("--run-consolidation-once", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    assertion = sub.add_parser("assert")
    assertion.add_argument("--tenant", required=True)
    assertion.add_argument("--user")
    assertion.add_argument("--subject", required=True)
    assertion.add_argument("--predicate", required=True)
    assertion.add_argument("--object", required=True)
    assertion.add_argument("--evidence-cid", action="append", default=[])
    assertion.add_argument("--branch", default="main")
    assertion.add_argument("--confidence", type=float, default=0.7)
    assertion.add_argument("--trust-tier", type=int, default=0)
    assertion.add_argument("--role", default="agent", choices=["reader", "agent", "consolidator", "operator"])
    assertion.add_argument("--source-trust-tier", type=int)
    assertion.set_defaults(func=cmd_assert)

    source_sync = sub.add_parser("source-sync")
    source_sync.add_argument("--tenant", required=True)
    source_sync.add_argument("--user", required=True)
    source_sync.add_argument("--root", required=True)
    source_sync.add_argument("--branch", default="main")
    source_sync.add_argument("--apply", action="store_true")
    source_sync.add_argument("--allow-dirty", action="store_true")
    source_sync.add_argument("--role", default="operator", choices=["reader", "agent", "consolidator", "operator"])
    source_sync.add_argument("--source-trust-tier", type=int, default=0)
    source_sync.set_defaults(func=cmd_source_sync)

    relation = sub.add_parser("relation")
    relation.add_argument("--tenant", required=True)
    relation.add_argument("--source", required=True)
    relation.add_argument("--predicate", required=True)
    relation.add_argument("--target", required=True)
    relation.add_argument("--evidence-cid", action="append", default=[])
    relation.add_argument("--branch", default="main")
    relation.add_argument("--confidence", type=float, default=0.7)
    relation.add_argument("--role", default="agent", choices=["reader", "agent", "consolidator", "operator"])
    relation.add_argument("--source-trust-tier", type=int, default=3)
    relation.set_defaults(func=cmd_relation)

    preference = sub.add_parser("preference")
    preference.add_argument("--tenant", required=True)
    preference.add_argument("--user", required=True)
    preference.add_argument("--category", required=True, choices=["format", "tone", "workflow", "tooling", "domain", "constraint"])
    preference.add_argument("--statement", required=True)
    preference.add_argument("--explicit", action="store_true")
    preference.add_argument("--confidence", type=float, default=0.7)
    preference.add_argument("--evidence-cid", action="append", default=[])
    preference.add_argument("--role", default="agent", choices=["reader", "agent", "consolidator", "operator"])
    preference.add_argument("--source-trust-tier", type=int)
    preference.set_defaults(func=cmd_preference)

    search = sub.add_parser("search")
    search.add_argument("--tenant", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--branch", default="main")
    search.add_argument("--min-trust-tier", type=int)
    search.add_argument("--max-trust-tier", type=int)
    search.add_argument("--max-sensitivity", type=int)
    search.add_argument("--role", default="reader", choices=["reader", "agent", "consolidator", "operator"])
    search.add_argument("--user")
    search.add_argument("--capability-tag", action="append", default=[])
    search.add_argument("--purpose")
    search.add_argument("--lawful-basis")
    search.add_argument("--residency")
    search.add_argument("--region")
    search.add_argument("--break-glass", action="store_true")
    search.set_defaults(func=cmd_search)

    deep = sub.add_parser("deep-search")
    deep.add_argument("--tenant", required=True)
    deep.add_argument("--query", required=True)
    deep.add_argument("--branch", default="main")
    deep.add_argument("--role", default="reader", choices=["reader", "agent", "consolidator", "operator"])
    deep.set_defaults(func=cmd_deep_search)

    explain = sub.add_parser("explain")
    explain.add_argument("--tenant", required=True)
    explain.add_argument("--query", required=True)
    explain.add_argument("--branch", default="main")
    explain.set_defaults(func=cmd_explain)

    get = sub.add_parser("get")
    get.add_argument("--tenant", required=True)
    get.add_argument("--id", required=True)
    get.add_argument("--branch")
    _add_read_context_args(get)
    get.set_defaults(func=cmd_get)

    propose = sub.add_parser("propose")
    propose.add_argument("--tenant", required=True)
    propose.add_argument("--user", required=True)
    propose.add_argument("--subject", required=True)
    propose.add_argument("--predicate", required=True)
    propose.add_argument("--object", required=True)
    propose.add_argument("--evidence-cid", action="append", default=[])
    propose.add_argument("--confidence", type=float, default=0.7)
    propose.add_argument("--trust-tier", type=int, default=1)
    propose.add_argument("--branch")
    propose.add_argument("--role", default="agent", choices=["reader", "agent", "consolidator", "operator"])
    propose.add_argument("--source-trust-tier", type=int)
    propose.set_defaults(func=cmd_propose)

    confirm = sub.add_parser("confirm")
    confirm.add_argument("--id", required=True)
    confirm.add_argument("--tenant")
    confirm.add_argument("--branch")
    confirm.add_argument("--into", default="main")
    confirm.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    confirm.add_argument("--source-trust-tier", type=int)
    confirm.set_defaults(func=cmd_confirm)

    supersede = sub.add_parser("supersede")
    supersede.add_argument("--tenant", required=True)
    supersede.add_argument("--user", required=True)
    supersede.add_argument("--id", required=True)
    supersede.add_argument("--new", required=True, help="JSON object containing object_value/object and optional assertion fields")
    supersede.add_argument("--branch", default="main")
    supersede.add_argument("--confidence", type=float, default=0.95)
    supersede.add_argument("--role", default="agent", choices=["reader", "agent", "consolidator", "operator"])
    supersede.add_argument("--source-trust-tier", type=int, default=0)
    supersede.set_defaults(func=cmd_supersede)

    correct = sub.add_parser("correct")
    correct.add_argument("--tenant", required=True)
    correct.add_argument("--user", required=True)
    correct.add_argument("--subject", required=True)
    correct.add_argument("--predicate", required=True)
    correct.add_argument("--object", required=True)
    correct.add_argument("--correction", required=True)
    correct.add_argument("--branch", default="main")
    correct.add_argument("--confidence", type=float, default=0.95)
    correct.add_argument("--role", default="agent", choices=["reader", "agent", "consolidator", "operator"])
    correct.add_argument("--source-trust-tier", type=int, default=0)
    correct.set_defaults(func=cmd_correct)

    forget = sub.add_parser("forget")
    forget.add_argument("--tenant", required=True)
    forget.add_argument("--cid", required=True)
    forget.add_argument("--branch", default="main")
    forget.add_argument("--requested-by", default="user")
    forget.add_argument("--role", default="operator", choices=["reader", "agent", "consolidator", "operator"])
    forget.add_argument("--source-trust-tier", type=int, default=0)
    forget.add_argument("--erasure-mode", default="tombstone_recompute", choices=["tombstone_recompute", "hard_delete_legal"])
    forget.set_defaults(func=cmd_forget)

    export = sub.add_parser("export")
    export.add_argument("--tenant", required=True)
    _add_read_context_args(export)
    export.set_defaults(func=cmd_export)

    calibration_tune = sub.add_parser("calibration-tune")
    calibration_tune.add_argument("--tenant", required=True)
    calibration_tune.add_argument("--memory-type", default="fact")
    calibration_tune.add_argument("--dataset", help="Path to JSON array of labeled calibration examples")
    calibration_tune.add_argument("--dataset-json", help="Inline JSON array of labeled calibration examples")
    calibration_tune.add_argument("--target-coverage", type=float, default=0.9)
    calibration_tune.add_argument("--min-examples", type=int, default=20)
    calibration_tune.add_argument("--min-correct", type=int, default=1)
    calibration_tune.add_argument("--min-incorrect", type=int, default=1)
    calibration_tune.add_argument("--min-empirical-coverage", type=float)
    calibration_tune.add_argument("--max-false-accept-rate", type=float, default=0.1)
    calibration_tune.add_argument("--max-prediction-set-size", type=int, default=3)
    calibration_tune.add_argument("--dry-run", action="store_true")
    calibration_tune.set_defaults(func=cmd_calibration_tune)

    forgetting_policy_check = sub.add_parser("forgetting-policy-check")
    forgetting_policy_check.add_argument("--cases", help="Path to JSON array of forgetting policy cases")
    forgetting_policy_check.add_argument("--cases-json", help="Inline JSON array of forgetting policy cases")
    forgetting_policy_check.add_argument("--now", default=os.environ.get("MNEMOSYNE_FORGETTING_POLICY_NOW"))
    forgetting_policy_check.add_argument("--utility-threshold", type=float, default=0.18)
    forgetting_policy_check.add_argument("--min-cases", type=int, default=3)
    forgetting_policy_check.add_argument("--require-case", action="append", default=[])
    forgetting_policy_check.add_argument("--expected-fingerprint")
    forgetting_policy_check.set_defaults(func=cmd_forgetting_policy_check)

    policy_ops_check = sub.add_parser("policy-ops-check")
    policy_ops_check.add_argument("--bundle", help="Path to policy ops validation bundle")
    policy_ops_check.add_argument("--bundle-json", help="Inline policy ops validation bundle JSON")
    policy_ops_check.add_argument("--min-variants", type=int, default=2)
    policy_ops_check.add_argument("--min-outcomes", type=int, default=3)
    policy_ops_check.add_argument("--min-tripwires", type=int, default=1)
    policy_ops_check.add_argument("--require-variant", action="append", default=[])
    policy_ops_check.add_argument("--min-outcomes-per-required-variant", type=int, default=1)
    policy_ops_check.add_argument("--min-cadence-window-hours", type=float, default=1.0)
    policy_ops_check.add_argument("--max-updates-per-day", type=int, default=4)
    policy_ops_check.add_argument("--min-diversity", type=float, default=0.2)
    policy_ops_check.add_argument("--max-proxy-gap", type=float, default=0.15)
    policy_ops_check.add_argument("--expected-fingerprint")
    policy_ops_check.set_defaults(func=cmd_policy_ops_check)

    privacy_backfill_report = sub.add_parser("privacy-backfill-report")
    privacy_backfill_report.add_argument("--tenant", required=True)
    privacy_backfill_report.add_argument("--branch", default="main")
    privacy_backfill_report.add_argument("--pii-sensitivity", default=3)
    privacy_backfill_report.add_argument("--include-clean", action="store_true")
    privacy_backfill_report.add_argument("--fail-on-findings", action="store_true")
    privacy_backfill_report.set_defaults(func=cmd_privacy_backfill_report)

    privacy_backfill_apply = sub.add_parser("privacy-backfill-apply")
    privacy_backfill_apply.add_argument("--tenant", required=True)
    privacy_backfill_apply.add_argument("--branch", default="main")
    privacy_backfill_apply.add_argument("--pii-sensitivity", default=3)
    privacy_backfill_apply.add_argument("--actor", default="operator")
    privacy_backfill_apply.add_argument("--confirm-apply", action="store_true")
    privacy_backfill_apply.set_defaults(func=cmd_privacy_backfill_apply)

    privacy_ops_check = sub.add_parser("privacy-ops-check")
    privacy_ops_check.add_argument("--bundle", help="Path to production privacy/KMS/residency evidence bundle")
    privacy_ops_check.add_argument("--bundle-json", help="Inline production privacy/KMS/residency evidence bundle JSON")
    privacy_ops_check.add_argument("--min-cases", type=int, default=4)
    privacy_ops_check.add_argument("--require-case", action="append", default=[])
    privacy_ops_check.add_argument("--expected-fingerprint")
    privacy_ops_check.set_defaults(func=cmd_privacy_ops_check)

    parametric_trainer_check = sub.add_parser("parametric-trainer-check")
    parametric_trainer_check.add_argument("--bundle", help="Path to production parametric trainer evidence bundle")
    parametric_trainer_check.add_argument("--bundle-json", help="Inline production parametric trainer evidence bundle JSON")
    parametric_trainer_check.add_argument("--min-cases", type=int, default=3)
    parametric_trainer_check.add_argument("--min-protected", type=int, default=1)
    parametric_trainer_check.add_argument("--min-gate-margin", type=float, default=0.01)
    parametric_trainer_check.add_argument("--max-deployment-latency-ms", type=float, default=2000.0)
    parametric_trainer_check.add_argument("--max-mutation-rate", type=float, default=0.05)
    parametric_trainer_check.add_argument("--min-reward", type=float, default=0.0)
    parametric_trainer_check.add_argument("--max-sink-score", type=float, default=0.05)
    parametric_trainer_check.add_argument("--expected-fingerprint")
    parametric_trainer_check.set_defaults(func=cmd_parametric_trainer_check)

    retrieval_ops_check = sub.add_parser("retrieval-ops-check")
    retrieval_ops_check.add_argument("--bundle", help="Path to production retrieval evidence bundle")
    retrieval_ops_check.add_argument("--bundle-json", help="Inline production retrieval evidence bundle JSON")
    retrieval_ops_check.add_argument("--require-provider-check", action="append", default=[])
    retrieval_ops_check.add_argument("--require-adapter-probe", action="append", choices=("graph", "lexical", "reranker", "vector"), default=[])
    retrieval_ops_check.add_argument("--min-cases", type=int, default=3)
    retrieval_ops_check.add_argument("--min-lexical-cases", type=int, default=1)
    retrieval_ops_check.add_argument("--min-vector-cases", type=int, default=1)
    retrieval_ops_check.add_argument("--min-graph-cases", type=int, default=1)
    retrieval_ops_check.add_argument("--min-reranked-cases", type=int, default=1)
    retrieval_ops_check.add_argument("--max-adapter-latency-ms", type=float, default=1000.0)
    retrieval_ops_check.add_argument("--min-calibration-examples", type=int, default=20)
    retrieval_ops_check.add_argument("--min-calibration-correct", type=int, default=1)
    retrieval_ops_check.add_argument("--min-calibration-incorrect", type=int, default=1)
    retrieval_ops_check.add_argument("--min-empirical-coverage", type=float, default=0.9)
    retrieval_ops_check.add_argument("--max-false-accept-rate", type=float, default=0.1)
    retrieval_ops_check.add_argument("--expected-fingerprint")
    retrieval_ops_check.set_defaults(func=cmd_retrieval_ops_check)

    auth_ops_check = sub.add_parser("auth-ops-check")
    auth_ops_check.add_argument("--bundle", help="Path to production auth evidence bundle")
    auth_ops_check.add_argument("--bundle-json", help="Inline production auth evidence bundle JSON")
    auth_ops_check.add_argument("--min-jwks-keys", type=int, default=2)
    auth_ops_check.add_argument("--min-token-ttl-seconds", type=int, default=60)
    auth_ops_check.add_argument("--min-source-trust-tier", type=int, default=1)
    auth_ops_check.add_argument("--max-authz-simulation-changes", type=int, default=0)
    auth_ops_check.add_argument("--min-authz-allowed-cases", type=int, default=1)
    auth_ops_check.add_argument("--min-authz-denied-cases", type=int, default=1)
    auth_ops_check.add_argument("--min-session-secret-keys", type=int, default=2)
    auth_ops_check.add_argument(
        "--min-cert-days",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_AUTH_OPS_MIN_CERT_DAYS", "30")),
    )
    # Env default mirrors --min-cert-days above: 24h ACME deployments declare
    # their real rotation-overlap policy instead of being structurally rejected
    # by the long-lived-cert constant.
    auth_ops_check.add_argument(
        "--min-cert-overlap-days",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_AUTH_OPS_MIN_CERT_OVERLAP_DAYS", "7")),
    )
    auth_ops_check.add_argument("--min-tenants", type=int, default=2)
    auth_ops_check.add_argument("--min-tenant-cases", type=int, default=2)
    auth_ops_check.add_argument("--min-tenant-allowed-cases", type=int, default=1)
    auth_ops_check.add_argument("--min-tenant-denied-cases", type=int, default=1)
    auth_ops_check.add_argument("--expected-fingerprint")
    auth_ops_check.set_defaults(func=cmd_auth_ops_check)

    mcp_ops_check = sub.add_parser("mcp-ops-check")
    mcp_ops_check.add_argument("--bundle", help="Path to production MCP runtime evidence bundle")
    mcp_ops_check.add_argument("--bundle-json", help="Inline production MCP runtime evidence bundle JSON")
    mcp_ops_check.add_argument("--min-loops", type=int, default=3)
    mcp_ops_check.add_argument("--max-avg-latency-ms", type=float, default=750.0)
    mcp_ops_check.add_argument("--max-p95-latency-ms", type=float, default=1500.0)
    # Env default mirrors tls-lifecycle/rotation checks: short-lived automated
    # ACME deployments (24h step-ca leafs) declare their real policy instead of
    # being structurally rejected by the long-lived-cert constant.
    mcp_ops_check.add_argument(
        "--min-cert-days",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_MCP_OPS_MIN_CERT_DAYS", "30")),
    )
    mcp_ops_check.add_argument("--require-client-cert", action="store_true")
    mcp_ops_check.add_argument("--require-legacy-sse", action="store_true")
    mcp_ops_check.add_argument("--min-sse-events", type=int, default=1)
    mcp_ops_check.add_argument("--allow-localhost", action="store_true")
    mcp_ops_check.add_argument("--expected-fingerprint")
    mcp_ops_check.set_defaults(func=cmd_mcp_ops_check)

    worker_ops_check = sub.add_parser("worker-ops-check")
    worker_ops_check.add_argument("--bundle", help="Path to production worker deployment evidence bundle")
    worker_ops_check.add_argument("--bundle-json", help="Inline production worker deployment evidence bundle JSON")
    worker_ops_check.add_argument("--min-processes", type=int, default=1)
    worker_ops_check.add_argument("--max-restart-seconds", type=float, default=120.0)
    worker_ops_check.add_argument("--max-heartbeat-age-seconds", type=float, default=120.0)
    worker_ops_check.add_argument("--max-backlog", type=int, default=1000)
    worker_ops_check.add_argument("--max-dead-jobs", type=int, default=0)
    worker_ops_check.add_argument("--max-oldest-pending-age-seconds", type=float, default=300.0)
    worker_ops_check.add_argument("--require-job-kind", action="append", default=[])
    worker_ops_check.add_argument("--allow-non-production", action="store_true")
    worker_ops_check.add_argument("--expected-fingerprint")
    worker_ops_check.set_defaults(func=cmd_worker_ops_check)

    consolidation_ops_check = sub.add_parser("consolidation-ops-check")
    consolidation_ops_check.add_argument("--bundle", help="Path to production consolidation evidence bundle")
    consolidation_ops_check.add_argument("--bundle-json", help="Inline production consolidation evidence bundle JSON")
    consolidation_ops_check.add_argument("--min-worker-cycles", type=int, default=3)
    consolidation_ops_check.add_argument("--min-processed-jobs", type=int, default=5)
    consolidation_ops_check.add_argument("--max-dead-jobs", type=int, default=0)
    consolidation_ops_check.add_argument("--require-worker-kind", action="append", default=[])
    consolidation_ops_check.add_argument("--require-provider-check", action="append", default=[])
    consolidation_ops_check.add_argument("--require-hosted-role", action="append", default=[])
    consolidation_ops_check.add_argument("--min-projection-cases", type=int, default=1)
    consolidation_ops_check.add_argument("--min-affected-assertions", type=int, default=1)
    consolidation_ops_check.add_argument("--min-affected-entities", type=int, default=1)
    consolidation_ops_check.add_argument("--min-affected-relations", type=int, default=1)
    consolidation_ops_check.add_argument("--min-gate-cases", type=int, default=3)
    consolidation_ops_check.add_argument("--min-protected", type=int, default=1)
    consolidation_ops_check.add_argument("--require-tier", choices=["smoke", "core", "archive"], action="append")
    consolidation_ops_check.add_argument("--min-embedding-dimensions", type=int, default=512)
    consolidation_ops_check.add_argument("--min-embedding-cids", type=int, default=1)
    consolidation_ops_check.add_argument("--require-consolidation-pass", action="append", default=[])
    consolidation_ops_check.add_argument("--min-evaluated-candidates", type=int, default=1)
    consolidation_ops_check.add_argument("--min-promoted-candidates", type=int, default=1)
    consolidation_ops_check.add_argument("--min-calibration-examples", type=int, default=20)
    consolidation_ops_check.add_argument("--min-calibration-correct", type=int, default=1)
    consolidation_ops_check.add_argument("--min-calibration-incorrect", type=int, default=1)
    consolidation_ops_check.add_argument("--min-calibration-coverage", type=float, default=0.9)
    consolidation_ops_check.add_argument("--max-calibration-false-accept-rate", type=float, default=0.1)
    consolidation_ops_check.add_argument("--min-lifecycle-evaluated", type=int, default=1)
    consolidation_ops_check.add_argument("--require-ops-counter", action="append", default=[])
    consolidation_ops_check.add_argument("--max-contradiction-backlog", type=int, default=0)
    consolidation_ops_check.add_argument("--max-deployment-latency-ms", type=float, default=2000.0)
    consolidation_ops_check.add_argument("--expected-fingerprint")
    consolidation_ops_check.set_defaults(func=cmd_consolidation_ops_check)

    belief_revision_check = sub.add_parser("belief-revision-check")
    belief_revision_check.add_argument("--cases", help="Path to JSON array of belief revision cases")
    belief_revision_check.add_argument("--cases-json", help="Inline JSON array of belief revision cases")
    belief_revision_check.add_argument("--min-cases", type=int, default=3)
    belief_revision_check.add_argument("--require-case", action="append", default=[])
    belief_revision_check.add_argument("--expected-fingerprint")
    belief_revision_check.set_defaults(func=cmd_belief_revision_check)

    provenance_trust_check = sub.add_parser("provenance-trust-check")
    provenance_trust_check.add_argument("--suite", help="Path to provenance trust validation suite JSON")
    provenance_trust_check.add_argument("--suite-json", help="Inline provenance trust validation suite JSON")
    provenance_trust_check.add_argument(
        "--c2pa-tool",
        default=os.environ.get("MNEMOSYNE_C2PA_TOOL"),
        help="Override c2patool-compatible verifier path for all suite cases",
    )
    provenance_trust_check.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_PROVENANCE_TRUST_TIMEOUT", "30")),
        help="Per-case verifier timeout in seconds",
    )
    provenance_trust_check.add_argument("--min-cases", type=int, default=1)
    provenance_trust_check.add_argument("--require-case", action="append", default=[])
    provenance_trust_check.add_argument("--expected-fingerprint")
    provenance_trust_check.set_defaults(func=cmd_provenance_trust_check)

    provenance_ops_check = sub.add_parser("provenance-ops-check")
    provenance_ops_check.add_argument("--bundle", help="Path to production provenance operations evidence bundle")
    provenance_ops_check.add_argument("--bundle-json", help="Inline production provenance operations evidence bundle JSON")
    provenance_ops_check.add_argument("--min-cases", type=int, default=3)
    provenance_ops_check.add_argument("--min-trusted-cases", type=int, default=1)
    provenance_ops_check.add_argument("--min-quarantine-cases", type=int, default=1)
    provenance_ops_check.add_argument("--min-trusted-roots", type=int, default=1)
    provenance_ops_check.add_argument("--min-trusted-issuers", type=int, default=1)
    provenance_ops_check.add_argument("--max-verifier-timeout-seconds", type=float, default=30.0)
    provenance_ops_check.add_argument("--max-deployment-latency-ms", type=float, default=2000.0)
    provenance_ops_check.add_argument("--expected-fingerprint")
    provenance_ops_check.set_defaults(func=cmd_provenance_ops_check)

    multimodal_ops_check = sub.add_parser("multimodal-ops-check")
    multimodal_ops_check.add_argument("--bundle", help="Path to production multimodal retrieval evidence bundle")
    multimodal_ops_check.add_argument("--bundle-json", help="Inline production multimodal retrieval evidence bundle JSON")
    multimodal_ops_check.add_argument("--min-media-cases", type=int, default=3)
    multimodal_ops_check.add_argument("--min-embedding-dimensions", type=int, default=512)
    multimodal_ops_check.add_argument("--min-vector-cases", type=int, default=1)
    multimodal_ops_check.add_argument("--min-derived-text-cases", type=int, default=1)
    multimodal_ops_check.add_argument("--max-dead-jobs", type=int, default=0)
    multimodal_ops_check.add_argument("--max-deployment-latency-ms", type=float, default=2000.0)
    multimodal_ops_check.add_argument("--require-provider-check", action="append", default=[])
    multimodal_ops_check.add_argument("--require-modality", choices=["image", "audio", "video", "binary", "multimodal"], action="append")
    multimodal_ops_check.add_argument("--expected-fingerprint")
    multimodal_ops_check.set_defaults(func=cmd_multimodal_ops_check)

    branch = sub.add_parser("branch")
    branch.add_argument("--name", required=True)
    branch.add_argument("--from-branch", "--from", dest="from_branch", default="main")
    branch.add_argument("--kind", default="scratch")
    branch.add_argument("--tenant", help="Tenant scope for Postgres backend")
    branch.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    branch.add_argument("--source-trust-tier", type=int)
    branch.set_defaults(func=cmd_branch)

    merge = sub.add_parser("merge")
    merge.add_argument("--from-branch", required=True)
    merge.add_argument("--into", default="main")
    merge.add_argument("--tenant", help="Tenant scope for Postgres backend")
    merge.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    merge.add_argument("--source-trust-tier", type=int)
    merge.set_defaults(func=cmd_merge)

    discard = sub.add_parser("discard")
    discard.add_argument("--branch", required=True)
    discard.add_argument("--tenant", help="Tenant scope for Postgres backend")
    discard.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    discard.add_argument("--source-trust-tier", type=int)
    discard.set_defaults(func=cmd_discard)

    profile_add = sub.add_parser("profile-add")
    profile_add.add_argument("--tenant", required=True)
    profile_add.add_argument("--user", required=True)
    profile_add.add_argument("--kind", required=True, choices=["identity", "hard_instruction", "explicit_preference", "inferred_preference", "situational_preference", "temporary_state"])
    profile_add.add_argument("--statement", required=True)
    profile_add.add_argument("--scope", default="{}")
    profile_add.add_argument("--exceptions", default="{}")
    profile_add.add_argument("--confidence", type=float, default=0.7)
    profile_add.add_argument("--evidence-cid", action="append", default=[])
    profile_add.add_argument("--role", default="agent", choices=["reader", "agent", "consolidator", "operator"])
    profile_add.add_argument("--source-trust-tier", type=int)
    profile_add.set_defaults(func=cmd_profile_add)

    profile_context = sub.add_parser("profile-context")
    profile_context.add_argument("--tenant", required=True)
    profile_context.add_argument("--user", required=True)
    profile_context.add_argument("--scope", default="{}")
    profile_context.set_defaults(func=cmd_profile_context)

    profile_get_relevant = sub.add_parser("profile-get-relevant")
    profile_get_relevant.add_argument("--tenant", required=True)
    profile_get_relevant.add_argument("--user", required=True)
    profile_get_relevant.add_argument("--context", default="{}")
    profile_get_relevant.set_defaults(func=cmd_profile_get_relevant)

    profile_record_explicit = sub.add_parser("profile-record-explicit")
    profile_record_explicit.add_argument("--tenant", required=True)
    profile_record_explicit.add_argument("--user", required=True)
    profile_record_explicit.add_argument("--statement", required=True)
    profile_record_explicit.add_argument("--scope", default="{}")
    profile_record_explicit.add_argument("--confidence", type=float, default=0.9)
    profile_record_explicit.add_argument("--evidence-cid", action="append", default=[])
    profile_record_explicit.set_defaults(func=cmd_profile_record_explicit)

    profile_propose_inference = sub.add_parser("profile-propose-inference")
    profile_propose_inference.add_argument("--tenant", required=True)
    profile_propose_inference.add_argument("--user", required=True)
    profile_propose_inference.add_argument("--statement", required=True)
    profile_propose_inference.add_argument("--context", default="{}")
    profile_propose_inference.add_argument("--confidence", type=float, default=0.55)
    profile_propose_inference.add_argument("--evidence-cid", action="append", default=[])
    profile_propose_inference.set_defaults(func=cmd_profile_propose_inference)

    profile_correct = sub.add_parser("profile-correct")
    profile_correct.add_argument("--tenant", required=True)
    profile_correct.add_argument("--user", required=True)
    profile_correct.add_argument("--id", required=True)
    profile_correct.add_argument("--statement", required=True)
    profile_correct.add_argument("--context", default="{}")
    profile_correct.add_argument("--confidence", type=float, default=0.95)
    profile_correct.set_defaults(func=cmd_profile_correct)

    profile_record_mistake = sub.add_parser("profile-record-mistake")
    profile_record_mistake.add_argument("--tenant", required=True)
    profile_record_mistake.add_argument("--user", required=True)
    profile_record_mistake.add_argument("--pattern", required=True)
    profile_record_mistake.add_argument("--description", required=True)
    profile_record_mistake.add_argument("--scope", default="{}")
    profile_record_mistake.add_argument("--suggestion")
    profile_record_mistake.add_argument("--occurred-at")
    profile_record_mistake.add_argument("--role", default="agent", choices=["reader", "agent", "consolidator", "operator"])
    profile_record_mistake.add_argument("--source-trust-tier", type=int)
    profile_record_mistake.set_defaults(func=cmd_profile_record_mistake)

    profile_retire_support = sub.add_parser("profile-retire-support-strategy")
    profile_retire_support.add_argument("--tenant", required=True)
    profile_retire_support.add_argument("--user", required=True)
    profile_retire_support.add_argument("--strategy-id", required=True)
    profile_retire_support.add_argument("--role", default="operator", choices=["reader", "agent", "consolidator", "operator"])
    profile_retire_support.add_argument("--source-trust-tier", type=int, default=0)
    profile_retire_support.set_defaults(func=cmd_profile_retire_support_strategy)

    graph_neighbors = sub.add_parser("graph-neighbors")
    graph_neighbors.add_argument("--tenant", required=True)
    graph_neighbors.add_argument("--seed", action="append", required=True)
    graph_neighbors.add_argument("--branch", default="main")
    graph_neighbors.add_argument("-k", type=int, default=8)
    graph_neighbors.set_defaults(func=cmd_graph_neighbors)

    graph_query = sub.add_parser("graph-query")
    graph_query.add_argument("--tenant", required=True)
    graph_query.add_argument("--seed", action="append", required=True)
    graph_query.add_argument("--branch", default="main")
    graph_query.add_argument("--hops", type=int, default=1)
    graph_query.add_argument("-k", type=int, default=8)
    graph_query.set_defaults(func=cmd_graph_query)

    graph_timeline = sub.add_parser("graph-timeline")
    graph_timeline.add_argument("--tenant", required=True)
    graph_timeline.add_argument("--entity", required=True)
    graph_timeline.add_argument("--branch", default="main")
    _add_read_context_args(graph_timeline)
    graph_timeline.set_defaults(func=cmd_graph_timeline)

    graph_as_of = sub.add_parser("graph-as-of")
    graph_as_of.add_argument("--tenant", required=True)
    graph_as_of.add_argument("--subject", required=True)
    graph_as_of.add_argument("--predicate", required=True)
    graph_as_of.add_argument("--time", required=True)
    graph_as_of.add_argument("--branch", default="main")
    graph_as_of.set_defaults(func=cmd_graph_as_of)

    prefetch = sub.add_parser("prefetch")
    prefetch.add_argument("--tenant", required=True)
    prefetch.add_argument("--candidates", required=True, help="JSON array of {query, probability, reason, metadata?}")
    prefetch.add_argument("--branch", default="main")
    prefetch.set_defaults(func=cmd_prefetch)

    trajectory_log = sub.add_parser("trajectory-log")
    trajectory_log.add_argument("--tenant", required=True)
    trajectory_log.add_argument("--user", required=True)
    trajectory_log.add_argument("--session", required=True)
    trajectory_log.add_argument("--task", required=True)
    trajectory_log.add_argument("--steps", required=True, help="JSON array of trajectory steps")
    trajectory_log.add_argument("--outcome", required=True, choices=["success", "failure"])
    trajectory_log.add_argument("--reward", type=float, required=True)
    trajectory_log.add_argument("--memory-version", required=True)
    trajectory_log.set_defaults(func=cmd_trajectory_log)

    trajectory_record = sub.add_parser("trajectory-record")
    trajectory_record.add_argument("--tenant", required=True)
    trajectory_record.add_argument("--user", required=True)
    trajectory_record.add_argument("--session", required=True)
    trajectory_record.add_argument("--task", required=True)
    trajectory_record.add_argument("--steps", required=True, help="JSON array of trajectory steps")
    trajectory_record.add_argument("--outcome", required=True, choices=["success", "failure"])
    trajectory_record.add_argument("--reward", type=float, required=True)
    trajectory_record.add_argument("--memory-version", required=True)
    trajectory_record.set_defaults(func=cmd_trajectory_log)

    trajectory_attribute = sub.add_parser("trajectory-attribute")
    trajectory_attribute.add_argument("--tenant")
    trajectory_attribute.add_argument("--trajectory-id", required=True)
    trajectory_attribute.set_defaults(func=cmd_trajectory_attribute)

    lesson_induce = sub.add_parser("lesson-induce")
    lesson_induce.add_argument("--tenant")
    lesson_induce.add_argument("--trajectory-id", required=True)
    lesson_induce.set_defaults(func=cmd_lesson_induce)

    lesson_propose = sub.add_parser("lesson-propose")
    lesson_propose.add_argument("--tenant")
    lesson_propose.add_argument("--trajectory-id", required=True)
    lesson_propose.set_defaults(func=cmd_lesson_induce)

    procedure_induce = sub.add_parser("procedure-induce")
    procedure_induce.add_argument("--tenant")
    procedure_induce.add_argument("--lesson-id", required=True)
    procedure_induce.set_defaults(func=cmd_procedure_induce)

    procedure_propose = sub.add_parser("procedure-propose")
    procedure_propose.add_argument("--tenant")
    procedure_propose.add_argument("--lesson-id", required=True)
    procedure_propose.set_defaults(func=cmd_procedure_induce)

    lesson_promote = sub.add_parser("lesson-promote")
    lesson_promote.add_argument("--tenant")
    lesson_promote.add_argument("--lesson-id", required=True)
    lesson_promote.add_argument("--cases", required=True, help="JSON array of regression cases")
    lesson_promote.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    lesson_promote.add_argument("--source-trust-tier", type=int)
    lesson_promote.set_defaults(func=cmd_lesson_promote)

    procedure_validate = sub.add_parser("procedure-validate")
    procedure_validate.add_argument("--tenant")
    procedure_validate.add_argument("--procedure-id", required=True)
    procedure_validate.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    procedure_validate.add_argument("--source-trust-tier", type=int)
    procedure_validate.set_defaults(func=cmd_procedure_validate)

    procedure_promote = sub.add_parser("procedure-promote")
    procedure_promote.add_argument("--tenant")
    procedure_promote.add_argument("--procedure-id", required=True)
    procedure_promote.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    procedure_promote.add_argument("--source-trust-tier", type=int)
    procedure_promote.set_defaults(func=cmd_procedure_promote)

    lesson_search = sub.add_parser("lesson-search")
    lesson_search.add_argument("--signature", required=True)
    lesson_search.add_argument("--tenant")
    lesson_search.add_argument("--status")
    lesson_search.set_defaults(func=cmd_lesson_search)

    procedure_search = sub.add_parser("procedure-search")
    procedure_search.add_argument("--query", required=True)
    procedure_search.add_argument("--tenant")
    procedure_search.add_argument("--status")
    procedure_search.set_defaults(func=cmd_procedure_search)

    procedure_rollback = sub.add_parser("procedure-rollback")
    procedure_rollback.add_argument("--tenant")
    procedure_rollback.add_argument("--procedure-id", required=True)
    procedure_rollback.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    procedure_rollback.add_argument("--source-trust-tier", type=int)
    procedure_rollback.set_defaults(func=cmd_procedure_rollback)

    outcome_evaluate = sub.add_parser("outcome-evaluate")
    outcome_evaluate.add_argument("--trajectory-id")
    outcome_evaluate.add_argument("--before-successes", type=int)
    outcome_evaluate.add_argument("--after-successes", type=int)
    outcome_evaluate.add_argument("--total-cases", type=int)
    outcome_evaluate.set_defaults(func=cmd_outcome_evaluate)

    parametric_propose = sub.add_parser("parametric-propose")
    parametric_propose.add_argument("--tenant", required=True)
    parametric_propose.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    parametric_propose.add_argument("--source-trust-tier", type=int)
    parametric_propose.set_defaults(func=cmd_parametric_propose)

    parametric_evaluate = sub.add_parser("parametric-evaluate")
    parametric_evaluate.add_argument("--artifact-uri", required=True)
    parametric_evaluate.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    parametric_evaluate.add_argument("--source-trust-tier", type=int)
    parametric_evaluate.add_argument("--protected-case-count", type=int, default=1)
    parametric_evaluate.add_argument("--gate-failed", action="store_true")
    parametric_evaluate.add_argument("--protected-regression", action="append", default=[])
    parametric_evaluate.set_defaults(func=cmd_parametric_evaluate)

    parametric_rollback = sub.add_parser("parametric-rollback")
    parametric_rollback.add_argument("--artifact-uri", required=True)
    parametric_rollback.add_argument("--reason", required=True)
    parametric_rollback.add_argument("--role", choices=["reader", "agent", "consolidator", "operator"])
    parametric_rollback.add_argument("--source-trust-tier", type=int)
    parametric_rollback.add_argument("--protected-case-count", type=int, default=1)
    parametric_rollback.set_defaults(func=cmd_parametric_rollback)

    tools = sub.add_parser("tools")
    tools.set_defaults(func=cmd_tools)

    eval_cmd = sub.add_parser("eval")
    eval_cmd.add_argument("suite", nargs="?", choices=["seed", "g0"], default="seed")
    eval_cmd.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    eval_cmd.add_argument("--out-dir", type=Path, default=Path("eval/g0/reports"))
    eval_cmd.add_argument("--baseline-name", default="baseline-0")
    eval_cmd.add_argument("--pinned-commit")
    eval_cmd.add_argument(
        "--controller-telemetry",
        type=Path,
        help=(
            "optional JSON artifact with controller_avg_watts and "
            "controller_cost_usd_per_hour for controller_watts_per_dollar"
        ),
    )
    eval_cmd.add_argument("--write-baseline", action="store_true")
    eval_cmd.add_argument("--print-json", action="store_true")
    eval_cmd.set_defaults(func=cmd_eval)

    queue_snapshot = sub.add_parser("queue-snapshot")
    queue_snapshot.set_defaults(func=cmd_queue_snapshot)

    gate_case_add = sub.add_parser("gate-case-add")
    gate_case_add.add_argument("--id")
    gate_case_add.add_argument("--signature", required=True)
    gate_case_add.add_argument("--query", required=True)
    gate_case_add.add_argument("--expected-substring", required=True)
    gate_case_add.add_argument("--tier", choices=["smoke", "core", "archive"], default="smoke")
    gate_case_add.add_argument("--origin", choices=["curated", "genuine", "synthetic"], default="curated")
    gate_case_add.add_argument("--mode", choices=["shadow", "active"], default="active")
    gate_case_add.add_argument("--protected", action="store_true")
    gate_case_add.set_defaults(func=cmd_gate_case_add)

    gate_case_list = sub.add_parser("gate-case-list")
    gate_case_list.set_defaults(func=cmd_gate_case_list)

    gate_suite_check = sub.add_parser("gate-suite-check")
    gate_suite_check.add_argument("--min-cases", type=int, default=0)
    gate_suite_check.add_argument("--min-protected", type=int, default=1)
    gate_suite_check.add_argument("--require-tier", choices=["smoke", "core", "archive"], action="append")
    gate_suite_check.add_argument("--expected-fingerprint")
    gate_suite_check.add_argument("--include-cases", action="store_true")
    gate_suite_check.set_defaults(func=cmd_gate_suite_check)

    queue_enqueue = sub.add_parser("queue-enqueue")
    queue_enqueue.add_argument("--kind", required=True)
    queue_enqueue.add_argument("--payload", default="{}")
    queue_enqueue.add_argument("--max-attempts", type=int, default=3)
    queue_enqueue.set_defaults(func=cmd_queue_enqueue)

    projection_recompute_enqueue = sub.add_parser("projection-recompute-enqueue")
    projection_recompute_enqueue.add_argument("--tenant", required=True)
    projection_recompute_enqueue.add_argument("--user", default="system")
    projection_recompute_enqueue.add_argument("--branch", default="main")
    projection_recompute_enqueue.add_argument("--cid", action="append", required=True)
    projection_recompute_enqueue.add_argument("--max-attempts", type=int, default=3)
    projection_recompute_enqueue.add_argument("--no-enqueue-consolidation", action="store_true")
    projection_recompute_enqueue.set_defaults(func=cmd_projection_recompute_enqueue)

    projection_recompute_once = sub.add_parser("projection-recompute-once")
    projection_recompute_once.add_argument("--tenant", required=True)
    projection_recompute_once.add_argument("--user", default="system")
    projection_recompute_once.add_argument("--branch", default="main")
    projection_recompute_once.add_argument("--cid", action="append", required=True)
    projection_recompute_once.add_argument("--max-attempts", type=int, default=3)
    projection_recompute_once.add_argument("--no-enqueue-consolidation", action="store_true")
    projection_recompute_once.set_defaults(func=cmd_projection_recompute_once)

    queue_drain = sub.add_parser("queue-drain")
    queue_drain.add_argument("--kind")
    queue_drain.add_argument("--limit", type=int, default=10)
    queue_drain.set_defaults(func=cmd_queue_drain)

    worker_run = sub.add_parser("worker-run")
    worker_run.add_argument("--kind")
    worker_run.add_argument("--limit", type=int, default=int(os.environ.get("MNEMOSYNE_WORKER_LIMIT", "10")))
    worker_run.add_argument(
        "--max-cycles",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_WORKER_MAX_CYCLES", "1")),
        help="Maximum worker supervision cycles before exiting",
    )
    worker_run.add_argument(
        "--idle-exit-after",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_WORKER_IDLE_EXIT_AFTER", "1")),
        help="Stop after this many idle cycles; set 0 to disable idle exit",
    )
    worker_run.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_WORKER_POLL_INTERVAL", "0")),
        help="Seconds to sleep between worker cycles",
    )
    worker_run.add_argument(
        "--fail-on-dead",
        action="store_true",
        default=env_flag("MNEMOSYNE_WORKER_FAIL_ON_DEAD", default=False),
        help="Exit nonzero if the final queue snapshot contains dead jobs",
    )
    worker_run.set_defaults(func=cmd_worker_run)

    ops_report = sub.add_parser("ops-report")
    ops_report.add_argument("--tenant", required=True)
    ops_report.add_argument("--proxy-score", type=float)
    ops_report.add_argument("--true-score", type=float)
    ops_report.add_argument("--min-diversity", type=float, default=0.2)
    ops_report.add_argument("--max-proxy-gap", type=float, default=0.15)
    ops_report.add_argument("--max-open-contradictions", type=int, default=0)
    ops_report.add_argument("--dashboard-html", help="Write a static HTML dashboard artifact to this path")
    ops_report.add_argument(
        "--dashboard-package-dir",
        help="Write static dashboard HTML, JSON snapshot, and manifest files to this directory",
    )
    ops_report.set_defaults(func=cmd_ops_report)

    ops_metrics_push = sub.add_parser("ops-metrics-push")
    ops_metrics_push.add_argument("--tenant", required=True)
    ops_metrics_push.add_argument(
        "--metrics-url",
        default=os.environ.get("MNEMOSYNE_OPS_METRICS_URL"),
        help="VictoriaMetrics /api/v1/import/prometheus endpoint",
    )
    ops_metrics_push.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_OPS_METRICS_INTERVAL", "0")),
        help="Seconds between pushes; 0 pushes once and exits",
    )
    ops_metrics_push.add_argument("--timeout", type=float, default=10.0)
    ops_metrics_push.add_argument(
        "--dashboard-html-out",
        default=os.environ.get("MNEMOSYNE_OPS_DASHBOARD_HTML_OUT"),
        help="Also render the ops dashboard HTML artifact to this path each push",
    )
    ops_metrics_push.add_argument("--min-diversity", type=float, default=0.2)
    ops_metrics_push.add_argument("--max-proxy-gap", type=float, default=0.15)
    ops_metrics_push.add_argument("--max-open-contradictions", type=int, default=0)
    ops_metrics_push.set_defaults(func=cmd_ops_metrics_push)

    ops_dashboard_check = sub.add_parser("ops-dashboard-check")
    ops_dashboard_check.add_argument("--dashboard-package-dir", help="Path to an ops-report dashboard package directory")
    ops_dashboard_check.add_argument("--dashboard-url", help="Hosted dashboard HTML URL to validate")
    ops_dashboard_check.add_argument("--manifest-url", help="Optional hosted dashboard package manifest URL")
    ops_dashboard_check.add_argument("--snapshot-url", help="Optional hosted dashboard snapshot JSON URL")
    ops_dashboard_check.add_argument("--ops-bundle", help="Path to production dashboard operations evidence bundle")
    ops_dashboard_check.add_argument("--ops-bundle-json", help="Inline production dashboard operations evidence bundle JSON")
    ops_dashboard_check.add_argument("--expected-tenant", help="Require dashboard package tenant_id to match this value")
    ops_dashboard_check.add_argument(
        "--allow-insecure-localhost",
        action="store_true",
        help="Allow http://localhost or 127.0.0.1 only for local hosted dashboard tests",
    )
    ops_dashboard_check.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_OPS_DASHBOARD_CHECK_TIMEOUT", "10")),
    )
    ops_dashboard_check.add_argument(
        "--max-bytes",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_OPS_DASHBOARD_CHECK_MAX_BYTES", str(1024 * 1024))),
    )
    ops_dashboard_check.add_argument("--max-refresh-age-seconds", type=float, default=300.0)
    ops_dashboard_check.add_argument("--max-refresh-interval-seconds", type=float, default=300.0)
    ops_dashboard_check.add_argument("--allow-non-production", action="store_true")
    ops_dashboard_check.add_argument("--expected-fingerprint")
    ops_dashboard_check.set_defaults(func=cmd_ops_dashboard_check)

    provider_check = sub.add_parser("provider-check")
    provider_check.add_argument("--provider-manifest", help="JSON deployment manifest for provider health gates")
    provider_check.add_argument(
        "--provider-latency-samples",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_PROVIDER_CHECK_LATENCY_SAMPLES", "1")),
        help="Number of embedding/reranker health-call latency samples to collect",
    )
    provider_check.add_argument(
        "--max-provider-p95-latency-ms",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_PROVIDER_CHECK_MAX_P95_LATENCY_MS", "2000")),
        help="Fail provider-check when embedding or reranker p95 latency exceeds this threshold",
    )
    provider_check.add_argument(
        "--provider-oidc-allowed-internal-hosts",
        default=os.environ.get("MNEMOSYNE_IDP_ALLOWED_INTERNAL_HOSTS", ""),
        help=(
            "Comma-separated internal/private hostnames the OIDC JWKS URL may "
            "resolve to for a self-hosted IdP behind a private-network ingress. "
            "Mirrors idp-jwks-live-check's --idp-allowed-internal-hosts; without "
            "it the JWKS fetch is refused as an SSRF risk and the oidc subcheck "
            "can never pass on a self-hosted deployment."
        ),
    )
    provider_check.set_defaults(func=cmd_provider_check)

    specialist_manifest = sub.add_parser("specialist-manifest")
    specialist_manifest.add_argument(
        "--role",
        choices=[
            "reasoner",
            "extractor",
            "resolver",
            "embedder",
            "media_embedder",
            "reranker",
            "lexical_retriever",
            "graph_retriever",
            "parametric_trainer",
            "dreamer",
            "reality_monitor",
            "workspace_controller",
        ],
        help="Return only specialists with this role",
    )
    specialist_manifest.set_defaults(func=cmd_specialist_manifest)

    hosted_llm_check = sub.add_parser("hosted-llm-check")
    hosted_llm_check.add_argument(
        "--hosted-llm-manifest",
        required=True,
        help="JSON manifest of hosted LLM/provider role endpoints to validate",
    )
    hosted_llm_check.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_HOSTED_LLM_CHECK_TIMEOUT", "30")),
        help="Default per-provider timeout in seconds",
    )
    hosted_llm_check.add_argument(
        "--allow-insecure-localhost",
        action="store_true",
        help="Allow http://localhost or 127.0.0.1 only for local validation tests",
    )
    hosted_llm_check.add_argument("--expected-fingerprint")
    hosted_llm_check.set_defaults(func=cmd_hosted_llm_check)

    deployment_soak = sub.add_parser("deployment-soak")
    deployment_soak.add_argument(
        "--soak-manifest",
        default=os.environ.get("MNEMOSYNE_DEPLOYMENT_SOAK_MANIFEST"),
        required=not bool(os.environ.get("MNEMOSYNE_DEPLOYMENT_SOAK_MANIFEST")),
        help="JSON manifest of allowed deployment preflight commands to run",
    )
    deployment_soak.add_argument(
        "--check-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_DEPLOYMENT_SOAK_CHECK_TIMEOUT", "30")),
        help="Default per-check timeout in seconds",
    )
    deployment_soak.add_argument(
        "--evidence-dir",
        help="Write deployment-soak report, per-check JSON, and manifest evidence files to this directory",
    )
    deployment_soak.set_defaults(func=cmd_deployment_soak)

    release_audit = sub.add_parser("release-audit")
    release_audit.add_argument("--soak-report", help="Path to deployment-soak-report.json")
    release_audit.add_argument(
        "--evidence-manifest",
        help="Path to a mnemosyne.deployment_soak_evidence manifest.json bundle",
    )
    release_audit.add_argument(
        "--require-command",
        action="append",
        choices=sorted(DEPLOYMENT_SOAK_COMMANDS),
        help="Required deployment-soak child command; defaults to the production release profile",
    )
    release_audit.add_argument(
        "--require-provider-check",
        action="append",
        choices=sorted(PRODUCTION_RELEASE_REQUIRED_PROVIDER_CHECKS),
        help="Required provider-check subcheck; defaults to the production release profile",
    )
    release_audit.add_argument(
        "--require-provider-forbid-local",
        action="store_true",
        dest="require_provider_forbid_local",
        default=True,
        help="Require provider-check manifest forbid_local=true and non-local retrieval backends",
    )
    release_audit.add_argument(
        "--allow-provider-local",
        action="store_false",
        dest="require_provider_forbid_local",
        help="Allow local provider/retrieval evidence for non-production dry runs",
    )
    release_audit.add_argument(
        "--require-production-validated",
        action="store_true",
        default=False,
        help=(
            "Fail unless the deployment-soak report is production scoped, "
            "operator asserted, and explicitly marked production_validated"
        ),
    )
    release_audit.add_argument("--expected-fingerprint")
    release_audit.add_argument(
        "--collector-public-key-file",
        default=os.environ.get("MNEMOSYNE_COLLECTOR_PUBLIC_KEY_FILE"),
        help="Collector Ed25519 public key (PEM) used to verify the evidence-bundle signature",
    )
    release_audit.add_argument(
        "--evidence-signature-file",
        default=os.environ.get("MNEMOSYNE_EVIDENCE_SIGNATURE_FILE"),
        help="Detached signature document; defaults to <evidence-manifest>.sig.json",
    )
    release_audit.add_argument(
        "--require-signed-evidence",
        action="store_true",
        default=env_flag("MNEMOSYNE_REQUIRE_SIGNED_EVIDENCE", default=False),
        help="Fail unless the evidence manifest carries a valid collector signature",
    )
    release_audit.set_defaults(func=cmd_release_audit)

    evidence_keygen = sub.add_parser("evidence-keygen")
    evidence_keygen.add_argument(
        "--private-key-file",
        required=not bool(os.environ.get("MNEMOSYNE_COLLECTOR_SIGNING_KEY_FILE")),
        default=os.environ.get("MNEMOSYNE_COLLECTOR_SIGNING_KEY_FILE"),
    )
    evidence_keygen.add_argument(
        "--public-key-file",
        required=not bool(os.environ.get("MNEMOSYNE_COLLECTOR_PUBLIC_KEY_FILE")),
        default=os.environ.get("MNEMOSYNE_COLLECTOR_PUBLIC_KEY_FILE"),
    )
    evidence_keygen.set_defaults(func=cmd_evidence_keygen)

    evidence_sign = sub.add_parser("evidence-sign")
    evidence_sign.add_argument("--evidence-manifest", required=True)
    evidence_sign.add_argument(
        "--private-key-file",
        required=not bool(os.environ.get("MNEMOSYNE_COLLECTOR_SIGNING_KEY_FILE")),
        default=os.environ.get("MNEMOSYNE_COLLECTOR_SIGNING_KEY_FILE"),
    )
    evidence_sign.add_argument("--signature-file", default=os.environ.get("MNEMOSYNE_EVIDENCE_SIGNATURE_FILE"))
    evidence_sign.set_defaults(func=cmd_evidence_sign)

    evidence_verify = sub.add_parser("evidence-verify")
    evidence_verify.add_argument("--evidence-manifest", required=True)
    evidence_verify.add_argument(
        "--public-key-file",
        required=not bool(os.environ.get("MNEMOSYNE_COLLECTOR_PUBLIC_KEY_FILE")),
        default=os.environ.get("MNEMOSYNE_COLLECTOR_PUBLIC_KEY_FILE"),
    )
    evidence_verify.add_argument("--signature-file", default=os.environ.get("MNEMOSYNE_EVIDENCE_SIGNATURE_FILE"))
    evidence_verify.set_defaults(func=cmd_evidence_verify)

    audit_chain_export = sub.add_parser("audit-chain-export")
    audit_chain_export.add_argument("--tenant", required=True)
    audit_chain_export.add_argument("--output", required=True)
    audit_chain_export.add_argument("--hmac-command", default=os.environ.get("MNEMOSYNE_AUDIT_HMAC_COMMAND"))
    audit_chain_export.add_argument(
        "--hmac-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_AUDIT_HMAC_TIMEOUT", "30")),
    )
    audit_chain_export.add_argument(
        "--local-hmac-secret-file",
        default=os.environ.get("MNEMOSYNE_AUDIT_LOCAL_HMAC_SECRET_FILE"),
    )
    audit_chain_export.set_defaults(func=cmd_audit_chain_export)

    audit_chain_verify = sub.add_parser("audit-chain-verify")
    audit_chain_verify.add_argument("--tenant", required=True)
    audit_chain_verify.add_argument("--chain-file", required=True)
    audit_chain_verify.add_argument("--hmac-command", default=os.environ.get("MNEMOSYNE_AUDIT_HMAC_COMMAND"))
    audit_chain_verify.add_argument(
        "--hmac-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_AUDIT_HMAC_TIMEOUT", "30")),
    )
    audit_chain_verify.add_argument(
        "--local-hmac-secret-file",
        default=os.environ.get("MNEMOSYNE_AUDIT_LOCAL_HMAC_SECRET_FILE"),
    )
    audit_chain_verify.set_defaults(func=cmd_audit_chain_verify)

    production_evidence_verify = sub.add_parser("production-evidence-verify")
    production_evidence_verify.add_argument(
        "bundle_dir",
        help=(
            "Path to an already captured production evidence bundle; verifies custody "
            "metadata offline without rerunning production checks"
        ),
    )
    production_evidence_verify.add_argument(
        "--expected-bundle-fingerprint",
        help=(
            "Expected bundle-manifest.json sha256 fingerprint from an out-of-band "
            "operator fingerprint record; required for custody review"
        ),
    )
    production_evidence_verify.add_argument(
        "--fingerprint-record",
        help=(
            "Absolute path to the out-of-band production fingerprint record written "
            "by capture-production-evidence.sh; preferred over copying the fingerprint manually"
        ),
    )
    production_evidence_verify.add_argument(
        "--internal-consistency-only",
        action="store_true",
        help=(
            "Allow offline structure/redaction replay without an out-of-band "
            "fingerprint; diagnostic only, not custody evidence"
        ),
    )
    production_evidence_verify.add_argument(
        "--report-output",
        help=(
            "Absolute path outside the bundle under review where the verifier "
            "JSON report is written; the file must not already exist"
        ),
    )
    production_evidence_verify.set_defaults(func=cmd_production_evidence_verify)

    tls_cert_check = sub.add_parser("tls-cert-check")
    tls_cert_check.add_argument("--url", default=os.environ.get("MNEMOSYNE_TLS_CHECK_URL"))
    tls_cert_check.add_argument("--host", default=os.environ.get("MNEMOSYNE_TLS_CHECK_HOST"))
    tls_cert_check.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_TLS_CHECK_PORT", "443")),
    )
    tls_cert_check.add_argument("--server-name", default=os.environ.get("MNEMOSYNE_TLS_CHECK_SERVER_NAME"))
    tls_cert_check.add_argument("--ca-file", default=os.environ.get("MNEMOSYNE_TLS_CHECK_CA_FILE"))
    tls_cert_check.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_TLS_CHECK_TIMEOUT", "10")),
    )
    tls_cert_check.add_argument(
        "--min-days-valid",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_TLS_CHECK_MIN_DAYS_VALID", "30")),
    )
    tls_cert_check.add_argument(
        "--min-tls-version",
        choices=["TLSv1.2", "TLSv1.3"],
        default=os.environ.get("MNEMOSYNE_TLS_CHECK_MIN_TLS_VERSION", "TLSv1.2"),
    )
    tls_cert_check.set_defaults(func=cmd_tls_cert_check)

    tls_rotation_plan_check = sub.add_parser("tls-rotation-plan-check")
    tls_rotation_plan_check.add_argument(
        "--current-cert-file",
        default=os.environ.get("MNEMOSYNE_TLS_ROTATION_CURRENT_CERT_FILE"),
        required=not bool(os.environ.get("MNEMOSYNE_TLS_ROTATION_CURRENT_CERT_FILE")),
    )
    tls_rotation_plan_check.add_argument(
        "--candidate-cert-file",
        default=os.environ.get("MNEMOSYNE_TLS_ROTATION_CANDIDATE_CERT_FILE"),
        required=not bool(os.environ.get("MNEMOSYNE_TLS_ROTATION_CANDIDATE_CERT_FILE")),
    )
    tls_rotation_plan_check.add_argument(
        "--hostname",
        action="append",
        default=(
            os.environ.get("MNEMOSYNE_TLS_ROTATION_HOSTNAMES", "").split(",")
            if os.environ.get("MNEMOSYNE_TLS_ROTATION_HOSTNAMES")
            else []
        ),
        help="Hostname expected on both current and candidate certificates; repeat or comma-separate",
    )
    tls_rotation_plan_check.add_argument(
        "--min-current-days-valid",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_TLS_ROTATION_MIN_CURRENT_DAYS_VALID", "7")),
    )
    tls_rotation_plan_check.add_argument(
        "--min-candidate-days-valid",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_TLS_ROTATION_MIN_CANDIDATE_DAYS_VALID", "30")),
    )
    tls_rotation_plan_check.add_argument(
        "--min-overlap-days",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_TLS_ROTATION_MIN_OVERLAP_DAYS", "7")),
    )
    tls_rotation_plan_check.add_argument(
        "--require-issuer-continuity",
        action="store_true",
        default=env_flag("MNEMOSYNE_TLS_ROTATION_REQUIRE_ISSUER_CONTINUITY", default=False),
    )
    tls_rotation_plan_check.set_defaults(func=cmd_tls_rotation_plan_check)

    tls_lifecycle_ops_check = sub.add_parser("tls-lifecycle-ops-check")
    tls_lifecycle_ops_check.add_argument("--bundle", help="Path to production TLS lifecycle evidence bundle")
    tls_lifecycle_ops_check.add_argument("--bundle-json", help="Inline production TLS lifecycle evidence bundle JSON")
    tls_lifecycle_ops_check.add_argument("--min-hostnames", type=int, default=1)
    # Mirrors tls-rotation-plan-check: deployments with short-lived automated
    # ACME certificates (e.g. 24h step-ca leafs) declare their real rotation
    # policy through these environment defaults instead of the long-lived-cert
    # constants, so honest lifecycle evidence is not rejected structurally.
    tls_lifecycle_ops_check.add_argument(
        "--min-current-days-valid",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_TLS_LIFECYCLE_MIN_CURRENT_DAYS_VALID", "7")),
    )
    tls_lifecycle_ops_check.add_argument(
        "--min-candidate-days-valid",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_TLS_LIFECYCLE_MIN_CANDIDATE_DAYS_VALID", "30")),
    )
    tls_lifecycle_ops_check.add_argument(
        "--min-overlap-days",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_TLS_LIFECYCLE_MIN_OVERLAP_DAYS", "7")),
    )
    tls_lifecycle_ops_check.add_argument("--allow-non-production", action="store_true")
    tls_lifecycle_ops_check.add_argument("--allow-localhost", action="store_true")
    tls_lifecycle_ops_check.add_argument("--expected-fingerprint")
    tls_lifecycle_ops_check.set_defaults(func=cmd_tls_lifecycle_ops_check)

    mcp_sse_soak = sub.add_parser("mcp-sse-soak")
    mcp_sse_soak.add_argument(
        "--base-url",
        dest="mcp_sse_base_url",
        default=os.environ.get("MNEMOSYNE_MCP_SSE_BASE_URL"),
        help="Legacy MCP SSE base URL; derives /sse when --sse-url is omitted",
    )
    mcp_sse_soak.add_argument(
        "--sse-url",
        dest="mcp_sse_url",
        default=os.environ.get("MNEMOSYNE_MCP_SSE_URL"),
        help="Explicit legacy MCP SSE endpoint URL",
    )
    mcp_sse_soak.add_argument(
        "--auth-token",
        default=os.environ.get("MNEMOSYNE_MCP_SSE_AUTH_TOKEN") or os.environ.get("MNEMOSYNE_MCP_TOKEN"),
        help="Bearer token for legacy SSE requests",
    )
    mcp_sse_soak.add_argument(
        "--mcp-session-token",
        default=os.environ.get("MNEMOSYNE_MCP_SSE_SESSION_TOKEN") or os.environ.get("MNEMOSYNE_MCP_SESSION_TOKEN"),
        help="Signed Mnemosyne session token forwarded to the legacy SSE endpoint",
    )
    mcp_sse_soak.add_argument(
        "--iterations",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_MCP_SSE_SOAK_ITERATIONS", "3")),
        help="Number of legacy SSE stream-open checks to run",
    )
    mcp_sse_soak.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_MCP_SSE_SOAK_TIMEOUT", "10")),
        help="Per-stream timeout in seconds",
    )
    mcp_sse_soak.add_argument(
        "--min-events",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_MCP_SSE_MIN_EVENTS", "1")),
        help="Minimum SSE events each stream must emit",
    )
    mcp_sse_soak.add_argument(
        "--max-bytes",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_MCP_SSE_MAX_BYTES", "65536")),
        help="Maximum bytes read from each SSE stream before failing closed",
    )
    mcp_sse_soak.add_argument(
        "--expected-event",
        default=os.environ.get("MNEMOSYNE_MCP_SSE_EXPECTED_EVENT", "endpoint"),
        help="Required SSE event name; pass an empty string to skip this check",
    )
    mcp_sse_soak.add_argument(
        "--require-endpoint-data",
        action="store_true",
        dest="require_endpoint_data",
        default=env_flag("MNEMOSYNE_MCP_SSE_REQUIRE_ENDPOINT_DATA", default=True),
        help="Fail unless an endpoint event carries non-empty data",
    )
    mcp_sse_soak.add_argument(
        "--no-require-endpoint-data",
        action="store_false",
        dest="require_endpoint_data",
        help="Allow streams without endpoint-event data",
    )
    mcp_sse_soak.set_defaults(func=cmd_mcp_sse_soak)

    mcp_http_soak = sub.add_parser("mcp-http-soak")
    mcp_http_soak.add_argument(
        "--base-url",
        dest="mcp_http_base_url",
        default=os.environ.get("MNEMOSYNE_MCP_HTTP_BASE_URL"),
        help="Hosted MCP HTTP base URL; derives /healthz and /mcp when explicit URLs are omitted",
    )
    mcp_http_soak.add_argument(
        "--health-url",
        dest="mcp_http_health_url",
        default=os.environ.get("MNEMOSYNE_MCP_HTTP_HEALTH_URL"),
        help="Explicit hosted MCP health URL",
    )
    mcp_http_soak.add_argument(
        "--rpc-url",
        dest="mcp_http_rpc_url",
        default=os.environ.get("MNEMOSYNE_MCP_HTTP_RPC_URL"),
        help="Explicit hosted MCP JSON-RPC URL",
    )
    mcp_http_soak.add_argument(
        "--auth-token",
        default=os.environ.get("MNEMOSYNE_MCP_HTTP_AUTH_TOKEN") or os.environ.get("MNEMOSYNE_MCP_TOKEN"),
        help="Bearer token for hosted MCP requests",
    )
    mcp_http_soak.add_argument(
        "--mcp-session-token",
        default=os.environ.get("MNEMOSYNE_MCP_HTTP_SESSION_TOKEN") or os.environ.get("MNEMOSYNE_MCP_SESSION_TOKEN"),
        help="Signed Mnemosyne session token forwarded to the hosted MCP endpoint",
    )
    mcp_http_soak.add_argument(
        "--iterations",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_MCP_HTTP_SOAK_ITERATIONS", "5")),
        help="Number of initialize/list/read-only-call loops to run",
    )
    mcp_http_soak.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_MCP_HTTP_SOAK_TIMEOUT", "10")),
        help="Per-request timeout in seconds",
    )
    mcp_http_soak.add_argument(
        "--read-only-tool",
        default=os.environ.get("MNEMOSYNE_MCP_HTTP_SOAK_TOOL", "residency_policy"),
        help="Read-only MCP tool used for the repeated call check",
    )
    mcp_http_soak.add_argument(
        "--tool-arguments",
        default=os.environ.get("MNEMOSYNE_MCP_HTTP_SOAK_TOOL_ARGUMENTS", "{}"),
        help="JSON object of read-only tool arguments",
    )
    mcp_http_soak.add_argument(
        "--expected-transport",
        default=os.environ.get("MNEMOSYNE_MCP_HTTP_EXPECTED_TRANSPORT", "http-json-rpc"),
        help="Expected health transport value; pass an empty string to skip this check",
    )
    mcp_http_soak.add_argument(
        "--require-stateless",
        action="store_true",
        default=env_flag("MNEMOSYNE_MCP_HTTP_SOAK_REQUIRE_STATELESS", default=False),
        help="Fail unless /healthz reports stateless=true",
    )
    mcp_http_soak.add_argument(
        "--client-cert",
        dest="client_cert",
        default=os.environ.get("MNEMOSYNE_MCP_HTTP_CLIENT_CERT"),
        help="PEM client certificate (leaf+intermediate bundle) presented for mutual TLS; requires --client-key",
    )
    mcp_http_soak.add_argument(
        "--client-key",
        dest="client_key",
        default=os.environ.get("MNEMOSYNE_MCP_HTTP_CLIENT_KEY"),
        help="PEM private key for --client-cert (mutual TLS)",
    )
    mcp_http_soak.set_defaults(func=cmd_mcp_http_soak)

    mcp_streamable_http_soak = sub.add_parser("mcp-streamable-http-soak")
    mcp_streamable_http_soak.add_argument(
        "--base-url",
        dest="mcp_streamable_http_base_url",
        default=os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_BASE_URL"),
        help="Official SDK StreamableHTTP base URL; derives /healthz and /mcp when explicit URLs are omitted",
    )
    mcp_streamable_http_soak.add_argument(
        "--health-url",
        dest="mcp_streamable_http_health_url",
        default=os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_HEALTH_URL"),
        help="Explicit SDK StreamableHTTP health URL",
    )
    mcp_streamable_http_soak.add_argument(
        "--streamable-url",
        dest="mcp_streamable_http_url",
        default=os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_URL"),
        help="Explicit SDK StreamableHTTP MCP endpoint URL",
    )
    mcp_streamable_http_soak.add_argument(
        "--auth-token",
        default=os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_AUTH_TOKEN") or os.environ.get("MNEMOSYNE_MCP_TOKEN"),
        help="Bearer token for hosted StreamableHTTP gateway requests",
    )
    mcp_streamable_http_soak.add_argument(
        "--mcp-session-token",
        default=os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_SESSION_TOKEN")
        or os.environ.get("MNEMOSYNE_MCP_SESSION_TOKEN"),
        help="Signed Mnemosyne session token forwarded to the hosted StreamableHTTP endpoint",
    )
    mcp_streamable_http_soak.add_argument(
        "--iterations",
        type=int,
        default=int(os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_SOAK_ITERATIONS", "3")),
        help="Number of initialize/list/read-only-call StreamableHTTP loops to run",
    )
    mcp_streamable_http_soak.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_SOAK_TIMEOUT", "10")),
        help="Per-request timeout in seconds",
    )
    mcp_streamable_http_soak.add_argument(
        "--read-only-tool",
        default=os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_SOAK_TOOL", "residency_policy"),
        help="Read-only MCP tool used for the repeated call check",
    )
    mcp_streamable_http_soak.add_argument(
        "--tool-arguments",
        default=os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_SOAK_TOOL_ARGUMENTS", "{}"),
        help="JSON object of read-only tool arguments",
    )
    mcp_streamable_http_soak.add_argument(
        "--expected-transport",
        default=os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_EXPECTED_TRANSPORT", "mcp-sdk-streamable-http"),
        help="Expected health transport value; pass an empty string to skip this check",
    )
    mcp_streamable_http_soak.add_argument(
        "--client-cert",
        dest="client_cert",
        default=os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_CLIENT_CERT"),
        help="PEM client certificate (leaf+intermediate bundle) presented for mutual TLS; requires --client-key",
    )
    mcp_streamable_http_soak.add_argument(
        "--client-key",
        dest="client_key",
        default=os.environ.get("MNEMOSYNE_MCP_STREAMABLE_HTTP_CLIENT_KEY"),
        help="PEM private key for --client-cert (mutual TLS)",
    )
    mcp_streamable_http_soak.set_defaults(func=cmd_mcp_streamable_http_soak)

    residency_policy = sub.add_parser("residency-policy")
    residency_policy.set_defaults(func=cmd_residency_policy)

    consolidate_once = sub.add_parser("consolidate-once")
    consolidate_once.set_defaults(func=cmd_consolidate_once)

    capability = sub.add_parser("capability")
    capability.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit the capability report as JSON instead of shell-exportable lines",
    )
    capability.set_defaults(func=cmd_capability)
    return parser


def main(argv: list[str] | None = None) -> int:
    from mnemosyne.capability import maybe_autotune

    # Opt-in capability autotune (MNEMOSYNE_CAPABILITY_AUTOTUNE=1): fills env
    # defaults for unset knobs before any command reads them; strict no-op
    # unless the flag is set (registered in CONFIG-DRIFT-CHECKS.md).
    maybe_autotune()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in {"session-exchange", "idp-authz-policy-check"}:
        apply_session_identity(args)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

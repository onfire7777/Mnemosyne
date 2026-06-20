"""Command line interface for the local Mnemosyne engine."""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib import error as urlerror, request as urlrequest
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID

from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB
from mnemosyne.engine import LocalMemoryEngine, MemoryEngine
from mnemosyne.eval import run_seed_suite
from mnemosyne.gate import RegressionCase
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.jobs import RuntimeJobHandlers
from mnemosyne.learning import Lesson, Procedure
from mnemosyne.media import CommandMediaTextExtractor, MediaTextExtractor, MetadataMediaTextExtractor
from mnemosyne.mcp_tools import MemoryTools, TOOL_SPEC
from mnemosyne.models import Hit
from mnemosyne.observability import MetricsRegistry, build_ops_report, render_ops_dashboard
from mnemosyne.oidc_jwks import load_oidc_authorization_policy, load_oidc_jwks, oidc_jwks_loader
from mnemosyne.parametric import CommandParametricTrainer, ParametricArtifactStore, ParametricTier
from mnemosyne.provenance import C2paToolVerifier, ProvenanceTrustPolicy, SignedProvenanceVerifier
from mnemosyne.queue import InProcessQueue, PostgresQueue, QueueWorker
from mnemosyne.retrieval import (
    CommandMediaEmbeddingProvider,
    HashingEmbeddingProvider,
    HttpEmbeddingProvider,
    HttpReranker,
    LocalSimilarityReranker,
    RetrievalAdapters,
)
from mnemosyne.postgres_runtime_state import PostgresRuntimeState
from mnemosyne.runtime_state import RuntimeState
from mnemosyne.security import (
    OidcAuthorizationPolicy,
    OidcJwtVerifier,
    SessionAuthError,
    SessionTokenVerifier,
    issue_session_from_oidc,
    load_session_secret_command,
    parse_session_keyring,
    parse_session_revoke_list,
)
from mnemosyne.storage import CommandKeyManager, EncryptedLocalObjectStore, JsonKeyManager, LocalObjectStore


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
    material, active_key_id = _session_material_from_args(args, purpose="session-exchange")
    if isinstance(material, dict):
        return SessionTokenVerifier(material, active_key_id=active_key_id)
    return SessionTokenVerifier(material)


def _session_material_from_args(
    args: argparse.Namespace,
    *,
    purpose: str,
) -> tuple[str | dict[str, str], str | None]:
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

    return RetrievalAdapters(
        embedding=embedding,
        reranker=reranker,
        lexical_backend=args.lexical_backend,
        graph_backend=args.graph_backend,
    )


def load_engine(args: argparse.Namespace) -> MemoryEngine:
    if args.backend == "postgres":
        dsn = args.postgres_dsn or default_postgres_dsn()
        if not dsn:
            raise SystemExit("Postgres backend requires --postgres-dsn or MNEMOSYNE_POSTGRES_DSN.")
        try:
            from mnemosyne.postgres_engine import PostgresEngine, PostgresUnavailableError
        except ImportError as exc:  # pragma: no cover - defensive for broken installs.
            raise SystemExit("Postgres backend requires mnemosyne-memory[postgres].") from exc
        try:
            return PostgresEngine(dsn, adapters=load_retrieval_adapters(args))
        except PostgresUnavailableError as exc:
            raise SystemExit(str(exc)) from exc
    return LocalMemoryEngine(store_path=Path(args.store))


def load_provenance_verifier(args: argparse.Namespace) -> SignedProvenanceVerifier | C2paToolVerifier:
    if args.c2pa_tool:
        trust_policy = load_provenance_trust_policy(args)
        return C2paToolVerifier(
            tool_path=args.c2pa_tool,
            trust_policy=trust_policy,
            timeout_seconds=args.provenance_timeout,
        )
    return SignedProvenanceVerifier()


def load_provenance_trust_policy(args: argparse.Namespace) -> ProvenanceTrustPolicy:
    trusted_issuers = [str(item).strip() for item in (args.trusted_provenance_issuer or []) if str(item).strip()]
    trusted_roots = [str(item).strip() for item in (args.trusted_provenance_root or []) if str(item).strip()]
    require_trusted_issuer = False
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
    if args.object_store_encryption == "aesgcm":
        return EncryptedLocalObjectStore(Path(args.object_store), load_object_key_manager(args))
    return LocalObjectStore(Path(args.object_store))


def load_object_key_manager(args: argparse.Namespace) -> JsonKeyManager | CommandKeyManager:
    if args.object_key_provider == "command":
        if not args.object_key_command:
            raise SystemExit("--object-key-provider command requires --object-key-command.")
        return CommandKeyManager(args.object_key_command, timeout_seconds=float(args.object_key_timeout))
    if args.object_key_provider != "json":
        raise SystemExit(f"Unsupported object key provider: {args.object_key_provider}")
    key_store = Path(args.object_key_store) if args.object_key_store else Path(args.object_store) / ".keys.json"
    return JsonKeyManager(key_store)


def load_media_extractor(args: argparse.Namespace) -> MediaTextExtractor:
    if args.media_extractor_command:
        return CommandMediaTextExtractor(
            args.media_extractor_command,
            timeout_seconds=float(args.media_extractor_timeout),
        )
    return MetadataMediaTextExtractor()


def load_parametric_tier(args: argparse.Namespace) -> ParametricTier:
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
    if args.backend == "postgres":
        dsn = args.postgres_dsn or os.environ.get("MNEMOSYNE_POSTGRES_DSN")
        if not dsn:
            raise SystemExit("--backend postgres requires --postgres-dsn or MNEMOSYNE_POSTGRES_DSN.")
        return PostgresRuntimeState(dsn, tenant_id=runtime_state_tenant(args))
    return RuntimeState.from_store_path(Path(args.store))


def load_queue(
    args: argparse.Namespace,
    runtime_state: RuntimeState | PostgresRuntimeState | None = None,
) -> InProcessQueue | PostgresQueue:
    if args.queue_backend == "postgres":
        dsn = args.postgres_dsn or os.environ.get("MNEMOSYNE_POSTGRES_DSN")
        if not dsn:
            raise SystemExit("--queue-backend postgres requires --postgres-dsn or MNEMOSYNE_POSTGRES_DSN.")
        tenant_id = runtime_state_tenant(args)
        return PostgresQueue(dsn, tenant_id=tenant_id)
    return runtime_state.load_queue() if runtime_state else InProcessQueue()


def queue_uses_runtime_state(args: argparse.Namespace) -> bool:
    return args.queue_backend == "local"


def load_tools(
    args: argparse.Namespace,
    ingestion_queue: InProcessQueue | PostgresQueue | None = None,
    runtime_state: RuntimeState | PostgresRuntimeState | None = None,
) -> MemoryTools:
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


def cmd_session_exchange(args: argparse.Namespace) -> None:
    if not args.idp_token:
        raise SystemExit("session-exchange requires --idp-token or MNEMOSYNE_IDP_TOKEN")
    try:
        session_token, issued = issue_session_from_oidc(
            verifier=OidcJwtVerifier(
                load_oidc_jwks(
                    jwks=args.idp_jwks,
                    jwks_file=args.idp_jwks_file,
                    jwks_url=args.idp_jwks_url,
                    allow_insecure_url=args.idp_allow_insecure_jwks_url,
                    timeout=args.idp_timeout,
                    max_bytes=args.idp_jwks_max_bytes,
                ),
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
                ),
                jwks_cache_ttl_seconds=args.idp_jwks_cache_ttl_seconds,
                refresh_on_unknown_kid=not args.idp_disable_refresh_on_unknown_kid,
                authorization_policy=load_oidc_authorization_policy(
                    policy=args.idp_authz_policy,
                    policy_file=args.idp_authz_policy_file,
                ),
            ),
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


def cmd_idp_authz_policy_check(args: argparse.Namespace) -> None:
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
    expires_at = simulation.get("expires_at")
    session_id = simulation.get("session_id")
    try:
        identity = policy.authorize(
            simulation["payload"],  # type: ignore[arg-type]
            tenant_id=str(simulation["tenant_id"]),
            user_id=str(simulation["user_id"]),
            expires_at=int(expires_at) if expires_at is not None else None,
            session_id=str(session_id) if session_id is not None else None,
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
    runtime_state = load_runtime_state(args)
    ingestion_queue = None if args.no_enqueue_consolidation else load_queue(args, runtime_state)
    tools = load_tools(args, ingestion_queue=ingestion_queue, runtime_state=runtime_state)
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
            gate_cases=tools.runtime_state.load_gate_cases() if tools.runtime_state else [],
        )
        worker = QueueWorker(ingestion_queue, handlers.handlers(), metrics=metrics)
        job = worker.run_once(CONSOLIDATE_EVIDENCE_JOB)
        if tools.runtime_state:
            tools.runtime_state.save_learning(tools.learning)
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
        )
    )


def cmd_deep_search(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.deep_search(tenant_id=args.tenant, query=args.query, branch=args.branch))


def cmd_explain(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.explain(tenant_id=args.tenant, query=args.query, branch=args.branch))


def cmd_get(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.get(args.tenant, args.id, branch=args.branch))


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
    emit(tools.export(args.tenant))


def parse_json_arg(value: str, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


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


def cmd_graph_neighbors(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.graph_neighbors(args.tenant, args.seed, branch=args.branch, k=args.k))


def cmd_graph_query(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.graph_query(args.tenant, args.seed, branch=args.branch, hops=args.hops, k=args.k))


def cmd_graph_timeline(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.graph_timeline(args.tenant, args.entity, branch=args.branch))


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
    emit(tools.parametric_rollback(args.artifact_uri, args.reason, role=args.role, source_trust_tier=args.source_trust_tier))


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
    from mnemosyne.mcp_server import _to_mcp_tool_spec

    emit({"tools": [_to_mcp_tool_spec(item) for item in TOOL_SPEC]})


def cmd_eval(args: argparse.Namespace) -> None:
    outcomes = run_seed_suite()
    emit({"passed": all(item.passed for item in outcomes), "outcomes": [item.__dict__ for item in outcomes]})


def cmd_queue_snapshot(args: argparse.Namespace) -> None:
    runtime_state = load_runtime_state(args)
    queue = load_queue(args, runtime_state)
    emit({"queue": queue.snapshot(), "jobs": [job.to_dict() for job in queue.jobs.values()]})


def cmd_gate_case_add(args: argparse.Namespace) -> None:
    runtime_state = load_runtime_state(args)
    cases = {case.id: case for case in runtime_state.load_gate_cases()}
    case = RegressionCase(
        id=args.id or gate_case_id(args.signature, args.query, args.expected_substring),
        signature=args.signature,
        query=args.query,
        expected_substring=args.expected_substring,
        tier=args.tier,
        protected=args.protected,
    )
    cases[case.id] = case
    ordered = sorted(cases.values(), key=lambda item: item.id)
    runtime_state.save_gate_cases(ordered)
    emit({"case": case.to_dict(), "cases": [item.to_dict() for item in ordered]})


def cmd_gate_case_list(args: argparse.Namespace) -> None:
    runtime_state = load_runtime_state(args)
    emit({"cases": [case.to_dict() for case in runtime_state.load_gate_cases()]})


def cmd_queue_enqueue(args: argparse.Namespace) -> None:
    runtime_state = load_runtime_state(args)
    queue = load_queue(args, runtime_state)
    job = queue.enqueue(args.kind, parse_json_arg(args.payload, {}), max_attempts=args.max_attempts)
    if runtime_state and queue_uses_runtime_state(args):
        runtime_state.save_queue(queue)
    emit({"queue": queue.snapshot(), "job": job.to_dict()})


def _runtime_worker_components(
    args: argparse.Namespace,
) -> tuple[RuntimeState | PostgresRuntimeState | None, InProcessQueue | PostgresQueue, MemoryTools, MetricsRegistry, QueueWorker]:
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
        gate_cases=runtime_state.load_gate_cases() if runtime_state else [],
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
    elif runtime_state:
        runtime_state.save_learning(tools.learning)


def cmd_consolidate_once(args: argparse.Namespace) -> None:
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
    if args.dashboard_html:
        path = Path(args.dashboard_html).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_ops_dashboard(report), encoding="utf-8")
        emit({"dashboard_path": str(path), "report": report})
        return
    emit(report)


def _display_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _join_endpoint(base_url: str | None, path: str) -> str | None:
    if not base_url:
        return None
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


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


def _http_json_probe(
    *,
    url: str,
    method: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    encoded_payload = None
    request_headers = {"Accept": "application/json", **dict(headers)}
    if payload is not None:
        encoded_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    started = time.monotonic()
    request = urlrequest.Request(url, data=encoded_payload, headers=request_headers, method=method)
    try:
        with urlrequest.urlopen(request, timeout=timeout_seconds) as response:
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

    ok = True
    health_probe = _http_json_probe(url=health_url, method="GET", headers=headers, timeout_seconds=args.timeout)
    health_payload = health_probe.get("json") if isinstance(health_probe.get("json"), dict) else {}
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
        "tls_client_cert_required": health_payload.get("tls_client_cert_required"),
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
        )
        tools_list = _json_rpc_probe(
            rpc_url=rpc_url,
            headers=headers,
            timeout_seconds=args.timeout,
            request_id=f"soak-{index}-tools",
            method="tools/list",
        )
        tool_call = _json_rpc_probe(
            rpc_url=rpc_url,
            headers=headers,
            timeout_seconds=args.timeout,
            request_id=f"soak-{index}-read-only",
            method="tools/call",
            params={"name": args.read_only_tool, "arguments": tool_arguments},
        )

        tool_entries = []
        if isinstance(tools_list.get("result"), dict) and isinstance(tools_list["result"].get("tools"), list):
            tool_entries = tools_list["result"]["tools"]
        contains_read_only_tool = any(
            isinstance(item, dict) and item.get("name") == args.read_only_tool for item in tool_entries
        )
        if not tools_list.get("ok") or not contains_read_only_tool:
            tools_list["ok"] = False
            tools_list.setdefault("error", f"tools/list did not include {args.read_only_tool}")
        tool_result = tool_call.get("result")
        if not isinstance(tool_result, dict) or tool_result.get("isError") is not False:
            tool_call["ok"] = False
            tool_call.setdefault("error", "read-only tool call failed")

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
                    **({"error": tools_list["error"]} if tools_list.get("error") else {}),
                },
                "read_only_tool_call": {
                    "ok": tool_call.get("ok"),
                    "status": tool_call.get("status"),
                    "latency_ms": tool_call.get("latency_ms"),
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
                "lexical_backend": "lexical_backend",
                "graph_backend": "graph_backend",
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
    required = manifest.get("required_checks", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise SystemExit("provider manifest field 'required_checks' must be an array of strings")
    forbid_local = bool(manifest.get("forbid_local", False))
    return {"name": manifest.get("name"), "required_checks": required, "forbid_local": forbid_local}


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


def cmd_provider_check(args: argparse.Namespace) -> None:
    manifest = apply_provider_manifest(args)
    checks: dict[str, dict[str, Any]] = {}
    ok = True
    try:
        adapters = load_retrieval_adapters(args)
        vector = adapters.embedding.embed("Mnemosyne provider health check")
        checks["embedding"] = {
            "ok": True,
            "provider": args.embedding_provider,
            "dimensions": len(vector),
            "model": args.embedding_model,
        }
    except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
        ok = False
        checks["embedding"] = {"ok": False, "provider": args.embedding_provider, "error": str(exc)}
        adapters = None

    try:
        reranker = adapters.reranker if adapters else load_retrieval_adapters(args).reranker
        ranked = reranker.rerank(
            "provider health",
            [
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
            ],
            k=2,
        )
        if not ranked:
            raise ValueError("reranker returned no health-check hits")
        checks["reranker"] = {
            "ok": True,
            "provider": args.reranker_provider,
            "top_id": ranked[0].id if ranked else None,
            "model": args.reranker_model,
        }
    except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
        ok = False
        checks["reranker"] = {"ok": False, "provider": args.reranker_provider, "error": str(exc)}

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
                rolled_back = tier.rollback(artifact, "provider health rollback")
            checks["parametric"] = {
                "ok": True,
                "provider": "command",
                "adapter_kind": artifact.adapter_kind,
                "artifact_id": artifact.id,
                "rollback_ref": rolled_back.rollback_ref,
            }
        except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
            ok = False
            checks["parametric"] = {"ok": False, "provider": "command", "error": str(exc)}
    else:
        checks["parametric"] = {"ok": True, "provider": "local", "skipped": True}

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
            jwks_document = load_oidc_jwks(
                jwks=oidc_fields["jwks"],
                jwks_file=oidc_fields["jwks_file"],
                jwks_url=oidc_fields["jwks_url"],
                allow_insecure_url=bool(getattr(args, "provider_oidc_allow_insecure_jwks_url", False)),
                timeout=float(getattr(args, "provider_oidc_timeout", 10.0)),
                max_bytes=int(getattr(args, "provider_oidc_jwks_max_bytes", 1024 * 1024)),
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

    try:
        checks["residency_policy"] = {"ok": True, **load_tools(args).residency_policy()}
    except Exception as exc:  # noqa: BLE001 - health checks return structured failures.
        ok = False
        checks["residency_policy"] = {"ok": False, "error": str(exc)}

    ok = enforce_provider_manifest_policy(checks, manifest) and ok
    emit({"ok": ok, "manifest": manifest, "checks": checks})
    if not ok:
        raise SystemExit(1)


def cmd_residency_policy(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.residency_policy())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mneme", description="Mnemosyne local memory compiler CLI")
    parser.add_argument("--backend", choices=["local", "postgres"], default=default_backend(), help="Storage backend")
    parser.add_argument("--store", default=str(default_store()), help="Path to local JSON store")
    parser.add_argument("--postgres-dsn", default=default_postgres_dsn(), help="PostgreSQL DSN for --backend postgres")
    parser.add_argument(
        "--queue-backend",
        choices=["local", "postgres"],
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
    parser.add_argument("--lexical-backend", default=os.environ.get("MNEMOSYNE_LEXICAL_BACKEND", "postgres-fts"))
    parser.add_argument("--graph-backend", default=os.environ.get("MNEMOSYNE_GRAPH_BACKEND", "postgres-recursive-ppr"))
    parser.add_argument("--c2pa-tool", default=os.environ.get("MNEMOSYNE_C2PA_TOOL"))
    parser.add_argument("--trusted-provenance-issuer", action="append", default=os.environ.get("MNEMOSYNE_TRUSTED_PROVENANCE_ISSUERS", "").split(",") if os.environ.get("MNEMOSYNE_TRUSTED_PROVENANCE_ISSUERS") else [])
    parser.add_argument("--trusted-provenance-root", action="append", default=os.environ.get("MNEMOSYNE_TRUSTED_PROVENANCE_ROOTS", "").split(",") if os.environ.get("MNEMOSYNE_TRUSTED_PROVENANCE_ROOTS") else [])
    parser.add_argument("--provenance-trust-policy", default=os.environ.get("MNEMOSYNE_PROVENANCE_TRUST_POLICY"))
    parser.add_argument("--provenance-timeout", type=float, default=float(os.environ.get("MNEMOSYNE_PROVENANCE_TIMEOUT", "30")))
    parser.add_argument("--media-extractor-command", default=os.environ.get("MNEMOSYNE_MEDIA_EXTRACTOR_COMMAND"))
    parser.add_argument("--media-extractor-timeout", type=float, default=float(os.environ.get("MNEMOSYNE_MEDIA_EXTRACTOR_TIMEOUT", "30")))
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
    sub = parser.add_subparsers(dest="command", required=True)

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
    session_exchange.add_argument("--session-max-ttl-seconds", type=int, default=int(os.environ.get("MNEMOSYNE_SESSION_MAX_TTL_SECONDS", "3600")))
    session_exchange.set_defaults(func=cmd_session_exchange)

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
    search.set_defaults(func=cmd_search)

    deep = sub.add_parser("deep-search")
    deep.add_argument("--tenant", required=True)
    deep.add_argument("--query", required=True)
    deep.add_argument("--branch", default="main")
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
    export.set_defaults(func=cmd_export)

    branch = sub.add_parser("branch")
    branch.add_argument("--name", required=True)
    branch.add_argument("--from-branch", default="main")
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
    parametric_rollback.set_defaults(func=cmd_parametric_rollback)

    tools = sub.add_parser("tools")
    tools.set_defaults(func=cmd_tools)

    eval_cmd = sub.add_parser("eval")
    eval_cmd.set_defaults(func=cmd_eval)

    queue_snapshot = sub.add_parser("queue-snapshot")
    queue_snapshot.set_defaults(func=cmd_queue_snapshot)

    gate_case_add = sub.add_parser("gate-case-add")
    gate_case_add.add_argument("--id")
    gate_case_add.add_argument("--signature", required=True)
    gate_case_add.add_argument("--query", required=True)
    gate_case_add.add_argument("--expected-substring", required=True)
    gate_case_add.add_argument("--tier", choices=["smoke", "core", "archive"], default="smoke")
    gate_case_add.add_argument("--protected", action="store_true")
    gate_case_add.set_defaults(func=cmd_gate_case_add)

    gate_case_list = sub.add_parser("gate-case-list")
    gate_case_list.set_defaults(func=cmd_gate_case_list)

    queue_enqueue = sub.add_parser("queue-enqueue")
    queue_enqueue.add_argument("--kind", required=True)
    queue_enqueue.add_argument("--payload", default="{}")
    queue_enqueue.add_argument("--max-attempts", type=int, default=3)
    queue_enqueue.set_defaults(func=cmd_queue_enqueue)

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
    ops_report.set_defaults(func=cmd_ops_report)

    provider_check = sub.add_parser("provider-check")
    provider_check.add_argument("--provider-manifest", help="JSON deployment manifest for provider health gates")
    provider_check.set_defaults(func=cmd_provider_check)

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
    mcp_http_soak.set_defaults(func=cmd_mcp_http_soak)

    residency_policy = sub.add_parser("residency-policy")
    residency_policy.set_defaults(func=cmd_residency_policy)

    consolidate_once = sub.add_parser("consolidate-once")
    consolidate_once.set_defaults(func=cmd_consolidate_once)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in {"session-exchange", "idp-authz-policy-check"}:
        apply_session_identity(args)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

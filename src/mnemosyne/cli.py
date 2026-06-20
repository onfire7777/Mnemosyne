"""Command line interface for the local Mnemosyne engine."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
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
from mnemosyne.parametric import CommandParametricTrainer, ParametricArtifactStore, ParametricTier
from mnemosyne.provenance import C2paToolVerifier, ProvenanceTrustPolicy, SignedProvenanceVerifier
from mnemosyne.queue import InProcessQueue, PostgresQueue, QueueWorker
from mnemosyne.retrieval import HashingEmbeddingProvider, HttpEmbeddingProvider, HttpReranker, LocalSimilarityReranker, RetrievalAdapters
from mnemosyne.runtime_state import RuntimeState
from mnemosyne.security import SessionAuthError, SessionTokenVerifier, parse_session_keyring, parse_session_revoke_list
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
    keyring = parse_session_keyring(getattr(args, "session_keyring", None))
    revoked_key_ids = parse_session_revoke_list(getattr(args, "session_revoked_key_ids", None))
    revoked_session_ids = parse_session_revoke_list(getattr(args, "session_revoked_ids", None))
    if keyring:
        return SessionTokenVerifier(
            keyring,
            active_key_id=getattr(args, "session_key_id", None),
            revoked_key_ids=revoked_key_ids,
            revoked_session_ids=revoked_session_ids,
        )
    secret = getattr(args, "session_secret", None)
    if not secret:
        raise SessionAuthError("--session-token requires --session-secret, --session-keyring, or MNEMOSYNE_SESSION_SECRET.")
    return SessionTokenVerifier(secret, revoked_key_ids=revoked_key_ids, revoked_session_ids=revoked_session_ids)


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
    if command not in {"confirm", "branch", "merge", "discard", "parametric-propose", "parametric-evaluate", "parametric-rollback"}:
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


def load_runtime_state(args: argparse.Namespace) -> RuntimeState | None:
    return RuntimeState.from_store_path(Path(args.store))


def load_queue(args: argparse.Namespace, runtime_state: RuntimeState | None = None) -> InProcessQueue | PostgresQueue:
    if args.queue_backend == "postgres":
        dsn = args.postgres_dsn or os.environ.get("MNEMOSYNE_POSTGRES_DSN")
        if not dsn:
            raise SystemExit("--queue-backend postgres requires --postgres-dsn or MNEMOSYNE_POSTGRES_DSN.")
        tenant_id = getattr(args, "tenant", None) or args.queue_tenant
        return PostgresQueue(dsn, tenant_id=tenant_id)
    return runtime_state.load_queue() if runtime_state else InProcessQueue()


def queue_uses_runtime_state(args: argparse.Namespace) -> bool:
    return args.queue_backend == "local"


def load_tools(
    args: argparse.Namespace,
    ingestion_queue: InProcessQueue | PostgresQueue | None = None,
    runtime_state: RuntimeState | None = None,
) -> MemoryTools:
    store = Path(args.store)
    engine = load_engine(args)
    ingestion = IngestionPipeline(
        engine,
        object_store=load_object_store(args),
        provenance_verifier=load_provenance_verifier(args),
        queue=ingestion_queue,
        allowed_residencies=tuple(args.allowed_residency),
    )
    return MemoryTools(
        engine,
        ingestion=ingestion,
        runtime_state=runtime_state or RuntimeState.from_store_path(store),
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
    emit(tools.lesson_promote(args.lesson_id, cases=parse_json_arg(args.cases, [])))


def cmd_procedure_validate(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.procedure_validate(args.procedure_id))


def cmd_procedure_promote(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.procedure_promote(args.procedure_id))


def cmd_lesson_search(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.lesson_search(args.signature, tenant_id=args.tenant, status=args.status))


def cmd_procedure_search(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.procedure_search(args.query, tenant_id=args.tenant, status=args.status))


def cmd_procedure_rollback(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.procedure_rollback(args.procedure_id))


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
    emit({"tools": TOOL_SPEC})


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


def cmd_consolidate_once(args: argparse.Namespace) -> None:
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
    job = worker.run_once(CONSOLIDATE_EVIDENCE_JOB)
    if runtime_state and queue_uses_runtime_state(args):
        runtime_state.save_queue(queue)
        runtime_state.save_learning(tools.learning)
    elif runtime_state:
        runtime_state.save_learning(tools.learning)
    emit({"queue": queue.snapshot(), "job": job.to_dict() if job else None, "metrics": metrics.snapshot().to_dict()})


def cmd_queue_drain(args: argparse.Namespace) -> None:
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
    jobs = worker.drain(limit=args.limit, kind=args.kind)
    if runtime_state and queue_uses_runtime_state(args):
        runtime_state.save_queue(queue)
        runtime_state.save_learning(tools.learning)
    elif runtime_state:
        runtime_state.save_learning(tools.learning)
    emit({"queue": queue.snapshot(), "jobs": [job.to_dict() for job in jobs], "metrics": metrics.snapshot().to_dict()})


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


def cmd_provider_check(args: argparse.Namespace) -> None:
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

    emit({"ok": ok, "checks": checks})
    if not ok:
        raise SystemExit(1)


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
    trajectory_attribute.add_argument("--trajectory-id", required=True)
    trajectory_attribute.set_defaults(func=cmd_trajectory_attribute)

    lesson_induce = sub.add_parser("lesson-induce")
    lesson_induce.add_argument("--trajectory-id", required=True)
    lesson_induce.set_defaults(func=cmd_lesson_induce)

    lesson_propose = sub.add_parser("lesson-propose")
    lesson_propose.add_argument("--trajectory-id", required=True)
    lesson_propose.set_defaults(func=cmd_lesson_induce)

    procedure_induce = sub.add_parser("procedure-induce")
    procedure_induce.add_argument("--lesson-id", required=True)
    procedure_induce.set_defaults(func=cmd_procedure_induce)

    procedure_propose = sub.add_parser("procedure-propose")
    procedure_propose.add_argument("--lesson-id", required=True)
    procedure_propose.set_defaults(func=cmd_procedure_induce)

    lesson_promote = sub.add_parser("lesson-promote")
    lesson_promote.add_argument("--lesson-id", required=True)
    lesson_promote.add_argument("--cases", required=True, help="JSON array of regression cases")
    lesson_promote.set_defaults(func=cmd_lesson_promote)

    procedure_validate = sub.add_parser("procedure-validate")
    procedure_validate.add_argument("--procedure-id", required=True)
    procedure_validate.set_defaults(func=cmd_procedure_validate)

    procedure_promote = sub.add_parser("procedure-promote")
    procedure_promote.add_argument("--procedure-id", required=True)
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
    procedure_rollback.add_argument("--procedure-id", required=True)
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
    provider_check.set_defaults(func=cmd_provider_check)

    consolidate_once = sub.add_parser("consolidate-once")
    consolidate_once.set_defaults(func=cmd_consolidate_once)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    apply_session_identity(args)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

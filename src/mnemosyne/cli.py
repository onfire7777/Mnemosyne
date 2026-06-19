"""Command line interface for the local Mnemosyne engine."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from mnemosyne.engine import LocalMemoryEngine, MemoryEngine
from mnemosyne.eval import run_seed_suite
from mnemosyne.mcp_tools import MemoryTools, TOOL_SPEC
from mnemosyne.models import Assertion, Relation
from mnemosyne.runtime_state import RuntimeState


def default_store() -> Path:
    return Path(os.environ.get("MNEME_STORE", ".mnemosyne/store.json"))


def default_backend() -> str:
    return os.environ.get("MNEME_BACKEND", "local")


def default_postgres_dsn() -> str | None:
    return os.environ.get("MNEMOSYNE_POSTGRES_DSN")


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
            return PostgresEngine(dsn)
        except PostgresUnavailableError as exc:
            raise SystemExit(str(exc)) from exc
    return LocalMemoryEngine(store_path=Path(args.store))


def load_tools(args: argparse.Namespace) -> MemoryTools:
    store = Path(args.store)
    return MemoryTools(load_engine(args), runtime_state=RuntimeState.from_store_path(store))


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


def cmd_assert(args: argparse.Namespace) -> None:
    engine = load_engine(args)
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=args.tenant,
            user_id=args.user,
            subject=args.subject,
            predicate=args.predicate,
            object=args.object,
            source_evidence_cids=args.evidence_cid,
            confidence=args.confidence,
            status="active",
            trust_tier=args.trust_tier,
            access_policy={"tenant": args.tenant},
        ),
        branch=args.branch,
    )
    emit({"id": assertion_id, "branch": args.branch})


def cmd_relation(args: argparse.Namespace) -> None:
    engine = load_engine(args)
    relation_id = engine.add_relation(
        Relation(
            tenant_id=args.tenant,
            source=args.source,
            predicate=args.predicate,
            target=args.target,
            confidence=args.confidence,
            source_evidence_cids=args.evidence_cid,
            access_policy={"tenant": args.tenant},
        ),
        branch=args.branch,
    )
    emit({"id": relation_id, "branch": args.branch})


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
            max_sensitivity=args.max_sensitivity,
        )
    )


def cmd_deep_search(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.deep_search(tenant_id=args.tenant, query=args.query, branch=args.branch))


def cmd_explain(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.explain(tenant_id=args.tenant, query=args.query, branch=args.branch))


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


def cmd_graph_neighbors(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.graph_neighbors(args.tenant, args.seed, branch=args.branch, k=args.k))


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


def cmd_parametric_propose(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(tools.parametric_propose(args.tenant))


def cmd_parametric_evaluate(args: argparse.Namespace) -> None:
    tools = load_tools(args)
    emit(
        tools.parametric_evaluate(
            args.tenant,
            protected_case_count=args.protected_case_count,
            gate_promoted=not args.gate_failed,
            protected_regressions=args.protected_regression,
        )
    )


def cmd_branch(args: argparse.Namespace) -> None:
    engine = load_engine(args)
    try:
        engine.branch(name=args.name, frm=args.from_branch, kind=args.kind, tenant_id=args.tenant)
    except TypeError:
        engine.branch(name=args.name, frm=args.from_branch, kind=args.kind)
    emit({"branch": args.name, "from": args.from_branch, "kind": args.kind})


def cmd_merge(args: argparse.Namespace) -> None:
    engine = load_engine(args)
    try:
        report = engine.merge(frm=args.from_branch, into=args.into, tenant_id=args.tenant)
    except TypeError:
        report = engine.merge(frm=args.from_branch, into=args.into)
    emit(report.to_dict())


def cmd_discard(args: argparse.Namespace) -> None:
    engine = load_engine(args)
    try:
        engine.discard(args.branch, tenant_id=args.tenant)
    except TypeError:
        engine.discard(args.branch)
    emit({"discarded": args.branch})


def cmd_tools(args: argparse.Namespace) -> None:
    emit({"tools": TOOL_SPEC})


def cmd_eval(args: argparse.Namespace) -> None:
    outcomes = run_seed_suite()
    emit({"passed": all(item.passed for item in outcomes), "outcomes": [item.__dict__ for item in outcomes]})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mneme", description="Mnemosyne local memory compiler CLI")
    parser.add_argument("--backend", choices=["local", "postgres"], default=default_backend(), help="Storage backend")
    parser.add_argument("--store", default=str(default_store()), help="Path to local JSON store")
    parser.add_argument("--postgres-dsn", default=default_postgres_dsn(), help="PostgreSQL DSN for --backend postgres")
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture")
    capture.add_argument("--tenant", required=True)
    capture.add_argument("--user", required=True)
    capture.add_argument("--actor", default="user", choices=["user", "assistant", "tool", "system", "external"])
    capture.add_argument("--source-type", required=True)
    capture.add_argument("--source-identity")
    capture.add_argument("--content", required=True)
    capture.add_argument("--branch", default="main")
    capture.add_argument("--trust-tier", type=int, default=1)
    capture.set_defaults(func=cmd_capture)

    assertion = sub.add_parser("assert")
    assertion.add_argument("--tenant", required=True)
    assertion.add_argument("--user")
    assertion.add_argument("--subject", required=True)
    assertion.add_argument("--predicate", required=True)
    assertion.add_argument("--object", required=True)
    assertion.add_argument("--evidence-cid", action="append", default=[])
    assertion.add_argument("--branch", default="main")
    assertion.add_argument("--confidence", type=float, default=0.7)
    assertion.add_argument("--trust-tier", type=int, default=1)
    assertion.set_defaults(func=cmd_assert)

    relation = sub.add_parser("relation")
    relation.add_argument("--tenant", required=True)
    relation.add_argument("--source", required=True)
    relation.add_argument("--predicate", required=True)
    relation.add_argument("--target", required=True)
    relation.add_argument("--evidence-cid", action="append", default=[])
    relation.add_argument("--branch", default="main")
    relation.add_argument("--confidence", type=float, default=0.7)
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

    correct = sub.add_parser("correct")
    correct.add_argument("--tenant", required=True)
    correct.add_argument("--user", required=True)
    correct.add_argument("--subject", required=True)
    correct.add_argument("--predicate", required=True)
    correct.add_argument("--object", required=True)
    correct.add_argument("--correction", required=True)
    correct.add_argument("--branch", default="main")
    correct.add_argument("--confidence", type=float, default=0.95)
    correct.set_defaults(func=cmd_correct)

    forget = sub.add_parser("forget")
    forget.add_argument("--tenant", required=True)
    forget.add_argument("--cid", required=True)
    forget.add_argument("--branch", default="main")
    forget.add_argument("--requested-by", default="user")
    forget.add_argument("--role", default="operator", choices=["reader", "agent", "consolidator", "operator"])
    forget.add_argument("--source-trust-tier", type=int, default=3)
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
    branch.set_defaults(func=cmd_branch)

    merge = sub.add_parser("merge")
    merge.add_argument("--from-branch", required=True)
    merge.add_argument("--into", default="main")
    merge.add_argument("--tenant", help="Tenant scope for Postgres backend")
    merge.set_defaults(func=cmd_merge)

    discard = sub.add_parser("discard")
    discard.add_argument("--branch", required=True)
    discard.add_argument("--tenant", help="Tenant scope for Postgres backend")
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

    graph_neighbors = sub.add_parser("graph-neighbors")
    graph_neighbors.add_argument("--tenant", required=True)
    graph_neighbors.add_argument("--seed", action="append", required=True)
    graph_neighbors.add_argument("--branch", default="main")
    graph_neighbors.add_argument("-k", type=int, default=8)
    graph_neighbors.set_defaults(func=cmd_graph_neighbors)

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

    trajectory_attribute = sub.add_parser("trajectory-attribute")
    trajectory_attribute.add_argument("--trajectory-id", required=True)
    trajectory_attribute.set_defaults(func=cmd_trajectory_attribute)

    lesson_induce = sub.add_parser("lesson-induce")
    lesson_induce.add_argument("--trajectory-id", required=True)
    lesson_induce.set_defaults(func=cmd_lesson_induce)

    procedure_induce = sub.add_parser("procedure-induce")
    procedure_induce.add_argument("--lesson-id", required=True)
    procedure_induce.set_defaults(func=cmd_procedure_induce)

    lesson_promote = sub.add_parser("lesson-promote")
    lesson_promote.add_argument("--lesson-id", required=True)
    lesson_promote.add_argument("--cases", required=True, help="JSON array of regression cases")
    lesson_promote.set_defaults(func=cmd_lesson_promote)

    procedure_validate = sub.add_parser("procedure-validate")
    procedure_validate.add_argument("--procedure-id", required=True)
    procedure_validate.set_defaults(func=cmd_procedure_validate)

    parametric_propose = sub.add_parser("parametric-propose")
    parametric_propose.add_argument("--tenant", required=True)
    parametric_propose.set_defaults(func=cmd_parametric_propose)

    parametric_evaluate = sub.add_parser("parametric-evaluate")
    parametric_evaluate.add_argument("--tenant", required=True)
    parametric_evaluate.add_argument("--protected-case-count", type=int, default=1)
    parametric_evaluate.add_argument("--gate-failed", action="store_true")
    parametric_evaluate.add_argument("--protected-regression", action="append", default=[])
    parametric_evaluate.set_defaults(func=cmd_parametric_evaluate)

    tools = sub.add_parser("tools")
    tools.set_defaults(func=cmd_tools)

    eval_cmd = sub.add_parser("eval")
    eval_cmd.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line interface for the local Mnemosyne engine."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.eval import run_seed_suite
from mnemosyne.mcp_tools import MemoryTools, TOOL_SPEC
from mnemosyne.models import Assertion, Evidence, Preference, Relation


def default_store() -> Path:
    return Path(os.environ.get("MNEME_STORE", ".mnemosyne/store.json"))


def load_engine(args: argparse.Namespace) -> LocalMemoryEngine:
    return LocalMemoryEngine(store_path=Path(args.store))


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def cmd_capture(args: argparse.Namespace) -> None:
    tools = MemoryTools(load_engine(args))
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
    engine = load_engine(args)
    preference_id = engine.add_preference(
        Preference(
            tenant_id=args.tenant,
            user_id=args.user,
            category=args.category,
            statement=args.statement,
            explicit=args.explicit,
            confidence=args.confidence,
            source_evidence_cids=args.evidence_cid,
        )
    )
    emit({"id": preference_id})


def cmd_search(args: argparse.Namespace) -> None:
    tools = MemoryTools(load_engine(args))
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
    tools = MemoryTools(load_engine(args))
    emit(tools.deep_search(tenant_id=args.tenant, query=args.query, branch=args.branch))


def cmd_explain(args: argparse.Namespace) -> None:
    tools = MemoryTools(load_engine(args))
    emit(tools.explain(tenant_id=args.tenant, query=args.query, branch=args.branch))


def cmd_correct(args: argparse.Namespace) -> None:
    tools = MemoryTools(load_engine(args))
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
    tools = MemoryTools(load_engine(args))
    emit(tools.forget(tenant_id=args.tenant, cid=args.cid, branch=args.branch, requested_by=args.requested_by))


def cmd_export(args: argparse.Namespace) -> None:
    tools = MemoryTools(load_engine(args))
    emit(tools.export(args.tenant))


def cmd_branch(args: argparse.Namespace) -> None:
    engine = load_engine(args)
    engine.branch(name=args.name, frm=args.from_branch, kind=args.kind)
    emit({"branch": args.name, "from": args.from_branch, "kind": args.kind})


def cmd_merge(args: argparse.Namespace) -> None:
    engine = load_engine(args)
    emit(engine.merge(frm=args.from_branch, into=args.into).to_dict())


def cmd_discard(args: argparse.Namespace) -> None:
    engine = load_engine(args)
    engine.discard(args.branch)
    emit({"discarded": args.branch})


def cmd_tools(args: argparse.Namespace) -> None:
    emit({"tools": TOOL_SPEC})


def cmd_eval(args: argparse.Namespace) -> None:
    outcomes = run_seed_suite()
    emit({"passed": all(item.passed for item in outcomes), "outcomes": [item.__dict__ for item in outcomes]})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mneme", description="Mnemosyne local memory compiler CLI")
    parser.add_argument("--store", default=str(default_store()), help="Path to local JSON store")
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
    forget.set_defaults(func=cmd_forget)

    export = sub.add_parser("export")
    export.add_argument("--tenant", required=True)
    export.set_defaults(func=cmd_export)

    branch = sub.add_parser("branch")
    branch.add_argument("--name", required=True)
    branch.add_argument("--from-branch", default="main")
    branch.add_argument("--kind", default="scratch")
    branch.set_defaults(func=cmd_branch)

    merge = sub.add_parser("merge")
    merge.add_argument("--from-branch", required=True)
    merge.add_argument("--into", default="main")
    merge.set_defaults(func=cmd_merge)

    discard = sub.add_parser("discard")
    discard.add_argument("--branch", required=True)
    discard.set_defaults(func=cmd_discard)

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


"""Development-only public backend/transport parity; never a measured M16 claim."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path

from eval.public.adapters.backend_transport_parity import CallError, PublicPair

PAIRS = ("local/cli", "sqlite/cli", "local/mcp-stdio", "sqlite/mcp-stdio")
EXPECTED = {
    "get_fact": {
        "content": "The m16quartz beacon is violet.",
        "tenant_id": "m16",
        "branch": "main",
    },
    "search_fact": [
        {
            "text": "The m16quartz beacon is violet.",
            "tenant_id": "m16",
            "branch": "main",
            "provenance": ["fact"],
        }
    ],
    "correction": {
        "subject": "m16copper",
        "predicate": "color",
        "object": "green",
        "provenance": ["correction"],
    },
    "working_before": [
        {
            "content": "Check the m16quartz beacon.",
            "kind": "current_plan",
            "tenant_id": "m16",
            "session_id": "session",
            "task_id": "task",
            "provenance": ["fact"],
        }
    ],
    "working_after_invalid": [
        {
            "content": "Check the m16quartz beacon.",
            "kind": "current_plan",
            "tenant_id": "m16",
            "session_id": "session",
            "task_id": "task",
            "provenance": ["fact"],
        }
    ],
    "working_after": [],
    "wrong_session": "authorization",
    "wrong_agent": "authorization",
    "reader": "authorization",
    "unchanged_action": [{"ref": "notify"}],
    "invalid_interval": "validation",
    "invalid_type": "validation",
    "no_partial_write": 1,
    "before_due": [],
    "at_due": ["notify"],
    "same_tick": [],
    "cross_tenant": "not_found",
    "forgotten": True,
    "get_forgotten": "not_found",
    "search_forgotten": [],
}


class Handles:
    def __init__(self):
        self.ids: dict[str, str] = {}

    def bind(self, label, value):
        if (
            not isinstance(value, str)
            or not value
            or value in self.ids
            or label in self.ids.values()
        ):
            raise ValueError("duplicate or invalid handle")
        self.ids[value] = label
        return value

    def reference(self, value):
        if value not in self.ids:
            raise ValueError("unknown reference")
        return self.ids[value]


def project_hits(hits, handles):
    return [
        dict(
            **{k: hit[k] for k in ("text", "tenant_id", "branch")},
            provenance=[handles.reference(p) for p in hit["provenance"]],
        )
        for hit in hits
    ]


def compare_runs(runs):
    failures = []
    expected_keys = {(p, i) for p in PAIRS for i in range(5)}
    seen = set()
    for run in runs:
        key = (run.get("pair"), run.get("repeat"))
        if (
            key not in expected_keys
            or key in seen
            or run.get("observations") != EXPECTED
            or "failure" in run
        ):
            failures.append(f"invalid or failed cell {key}")
        seen.add(key)
    if seen != expected_keys:
        failures.append("missing or unexpected cells")
    return {
        "development_conformance": "failed" if failures else "passed",
        "failures": failures,
        "admission_state": "PROPOSED",
        "publishable": False,
        "pbpp_headline_eligible": False,
        "m16_status": "partial",
        "executed_cells": len(runs),
        "required_cells": 20,
        "migration": "not_executed: public migration seam absent",
        "resource_admission": "not_measured",
        "unavailable": {
            p: "external service and resource admission required"
            for p in (
                "postgres/cli",
                "postgres/mcp-stdio",
                "local/hosted-http",
                "sqlite/hosted-http",
                "postgres/hosted-http",
            )
        },
    }


def run_cassette(pair, repeat, root, *, deadline=None):
    seam = PublicPair(
        pair, Path(root) / pair.replace("/", "-") / str(repeat), deadline=deadline
    )
    handles = Handles()
    observed = {}
    common = {"tenant_id": "m16", "user_id": "owner"}

    def call(name, **args):
        return seam.call(name, args)

    def error(case, name, args, markers, category, identity=None):
        try:
            seam.call(name, args, identity=identity)
        except CallError as exc:
            message = str(exc).lower()
            observed[case] = (
                category if any(m in message for m in markers) else "unclassified"
            )
        else:
            observed[case] = "unexpected_success"

    try:
        fact = handles.bind(
            "fact",
            call(
                "capture",
                **common,
                actor="user",
                session_id="session",
                source_identity="m16-cassette",
                turn_index=0,
                source_type="m16",
                content="The m16quartz beacon is violet.",
            )["cid"],
        )
        handles.bind(
            "other",
            call(
                "capture",
                **common,
                actor="user",
                session_id="session",
                source_identity="m16-cassette",
                turn_index=1,
                source_type="m16",
                content="The m16amber pebble is round.",
            )["cid"],
        )
        record = call("get", tenant_id="m16", id=fact)["record"]
        observed["get_fact"] = {
            k: record[k] for k in ("content", "tenant_id", "branch")
        }
        observed["search_fact"] = project_hits(
            call("search", tenant_id="m16", query="m16quartz")["hits"], handles
        )
        corrected = call(
            "correct",
            **common,
            subject="m16copper",
            predicate="color",
            object_value="green",
            correction_text="The m16copper color is green.",
        )
        assertion = call("get", tenant_id="m16", id=corrected["id"])["record"]
        if len(assertion["source_evidence_cids"]) != 1:
            raise ValueError("unexpected correction provenance")
        handles.bind("correction", assertion["source_evidence_cids"][0])
        observed["correction"] = {
            k: assertion[k] for k in ("subject", "predicate", "object")
        }
        observed["correction"]["provenance"] = [
            handles.reference(x) for x in assertion["source_evidence_cids"]
        ]
        scope = dict(
            **common,
            agent_id="agent",
            session_id="session",
            task_id="task",
            branch="main",
        )
        call(
            "working_seed",
            **scope,
            kind="current_plan",
            content="Check the m16quartz beacon.",
            evidence_ids=[fact],
            ttl_seconds=60,
            created_at="2026-01-01T12:00:00Z",
            source_trust_tier=0,
        )
        for name, now in (
            ("working_before", "12:00:30"),
            ("working_after", "12:01:00"),
        ):
            items = call("working_query", **scope, as_of=f"2026-01-01T{now}Z")["items"]
            observed[name] = [
                dict(
                    **{
                        k: i[k]
                        for k in (
                            "content",
                            "kind",
                            "tenant_id",
                            "session_id",
                            "task_id",
                        )
                    },
                    provenance=[handles.reference(x) for x in i["evidence_ids"]],
                )
                for i in items
            ]
        schedule = dict(
            **common,
            agent_id="agent",
            trigger_type="exact_time",
            trigger_expression={"at": "2026-01-01T12:00:00Z"},
            action={"ref": "notify"},
            due_at="2026-01-01T12:00:00Z",
            evidence_ids=[fact],
        )
        intention = call("schedule_intention", **schedule)["intention_id"]
        update = dict(
            **common, agent_id="agent", intention_id=intention, action={"ref": "wrong"}
        )
        for case, identity, markers in (
            ("wrong_session", {"session_id": "foreign"}, ["session"]),
            ("wrong_agent", {"agent_id": "foreign"}, ["agent", "mismatch"]),
            ("reader", {"role": "reader"}, ["reader", "denied"]),
        ):
            error(case, "update_intention", update, markers, "authorization", identity)
        observed["unchanged_action"] = [
            i["action"] for i in call("list_intentions", tenant_id="m16")["intentions"]
        ]
        error(
            "invalid_interval",
            "schedule_intention",
            dict(
                schedule, recurrence_policy={"type": "interval", "interval_seconds": 0}
            ),
            ["interval_seconds"],
            "validation",
        )
        error(
            "invalid_type",
            "working_seed",
            dict(
                scope,
                kind="current_plan",
                content="bad",
                evidence_ids=[fact],
                ttl_seconds="broken",
                created_at="2026-01-01T12:00:00Z",
                source_trust_tier=0,
            ),
            ["invalid int", "integer", "ttl_seconds"],
            "validation",
        )
        items = call("working_query", **scope, as_of="2026-01-01T12:00:30Z")["items"]
        observed["working_after_invalid"] = [
            dict(
                **{
                    k: i[k]
                    for k in ("content", "kind", "tenant_id", "session_id", "task_id")
                },
                provenance=[handles.reference(x) for x in i["evidence_ids"]],
            )
            for i in items
        ]
        observed["no_partial_write"] = len(
            call("list_intentions", tenant_id="m16")["intentions"]
        )
        for case, now in (
            ("before_due", "11:59:59"),
            ("at_due", "12:00:00"),
            ("same_tick", "12:00:00"),
        ):
            result = call(
                "evaluate_intentions",
                tenant_id="m16",
                evaluated_at=f"2026-01-01T{now}Z",
                trigger_context={
                    "infrastructure_available": True,
                    "tenant_id": "m16",
                    "events": [],
                    "conditions": {},
                },
                operating_point={
                    "operating_point_id": "m16-dev",
                    "threshold": 1.0,
                    "measured_precision": 1.0,
                    "measured_recall": 1.0,
                    "measurement_cid": fact,
                },
            )
            observed[case] = [i["action"]["ref"] for i in result["intentions"]]
        error(
            "cross_tenant",
            "get",
            {"tenant_id": "foreign", "id": fact},
            ["not found"],
            "not_found",
            {"tenant_id": "foreign"},
        )
        observed["forgotten"] = call("forget", tenant_id="m16", cid=fact)["erased"]
        error(
            "get_forgotten",
            "get",
            {"tenant_id": "m16", "id": fact},
            ["not found"],
            "not_found",
        )
        observed["search_forgotten"] = project_hits(
            call("search", tenant_id="m16", query="m16quartz")["hits"], handles
        )
        return {
            "pair": pair,
            "repeat": repeat,
            "observations": observed,
            "raw": seam.raw,
        }
    except Exception as exc:
        return {
            "pair": pair,
            "repeat": repeat,
            "observations": observed,
            "raw": seam.raw,
            "failure": f"{type(exc).__name__}: {exc}",
        }
    finally:
        seam.close()


def run_matrix(output_dir):
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + 900
    runs = []
    for pair in PAIRS:
        for repeat in range(5):
            result = run_cassette(pair, repeat, root, deadline=deadline)
            envelopes = result.pop("raw")
            result["operation_count"] = len(envelopes)
            raw = json.dumps(envelopes, sort_keys=True, separators=(",", ":")).encode()
            relative = f"{pair.replace('/', '-')}/{repeat}/raw.json"
            (root / relative).write_bytes(raw)
            result.update(raw_path=relative, raw_sha256=hashlib.sha256(raw).hexdigest())
            runs.append(result)
    report = compare_runs(runs)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    report.update(
        expected_observations=EXPECTED,
        completed_operations=sum(r["operation_count"] for r in runs),
        required_operations=500,
        source_dirty=bool(dirty),
        source_snapshot="working tree; two harness hashes only, not an immutable product snapshot",
        schema_version="m16-development/1",
        runs=runs,
        source_commit=commit,
        python=platform.python_version(),
        platform=platform.platform(),
        cassette_sha256=hashlib.sha256(
            json.dumps(EXPECTED, sort_keys=True).encode()
        ).hexdigest(),
        source_sha256={
            str(p.relative_to(Path(__file__).resolve().parents[2])): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in (
                Path(__file__),
                Path(__file__).parent / "adapters/backend_transport_parity.py",
            )
        },
        operating_point="synthetic deterministic fixture; not calibrated performance evidence",
        costs={"provider": None, "tokens": None, "rss": None, "energy": None},
    )
    (root / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    report = run_matrix(args.output_dir)
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}, sort_keys=True))
    return 0 if report["development_conformance"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Tier-B production parity row metadata shared by evidence tooling."""

from __future__ import annotations

from typing import Any


PARITY_ROUTES: dict[str, dict[str, object]] = {
    "B1": {
        "lane": "B1",
        "row": 1,
        "title": "Production Postgres retrieval",
        "runbook": ".planning/runbooks/row-01-production-postgres-retrieval.md",
    },
    "B2": {
        "lane": "B2",
        "row": 2,
        "title": "Tenant isolation and auth",
        "runbook": ".planning/runbooks/row-02-tenant-isolation-and-auth.md",
    },
    "B3": {
        "lane": "B3",
        "row": 3,
        "title": "CLI/MCP runtime coverage",
        "runbook": ".planning/runbooks/row-03-cli-mcp-runtime-coverage.md",
    },
    "B4": {
        "lane": "B4",
        "row": 4,
        "title": "Consolidation role pipeline",
        "runbook": ".planning/runbooks/row-04-consolidation-role-pipeline.md",
    },
    "B5": {
        "lane": "B5",
        "row": 5,
        "title": "Signed provenance",
        "runbook": ".planning/runbooks/row-05-signed-provenance.md",
    },
    "B6": {
        "lane": "B6",
        "row": 6,
        "title": "Multimodal retrieval",
        "runbook": ".planning/runbooks/row-06-multimodal-retrieval.md",
    },
    "B7": {
        "lane": "B7",
        "row": 7,
        "title": "Privacy and erasure",
        "runbook": ".planning/runbooks/row-07-privacy-and-erasure.md",
    },
    "B8": {
        "lane": "B8",
        "row": 8,
        "title": "Observability dashboards",
        "runbook": ".planning/runbooks/row-08-observability-dashboards.md",
    },
    "B9": {
        "lane": "B9",
        "row": 9,
        "title": "Parametric tier",
        "runbook": ".planning/runbooks/row-09-parametric-tier.md",
    },
    "B10": {
        "lane": "B10",
        "row": 10,
        "title": "Live parity suite",
        "runbook": ".planning/runbooks/row-10-live-parity-suite.md",
    },
}


PARITY_LANES_BY_COMMAND: dict[str, list[str]] = {
    "auth-ops-check": ["B2"],
    "belief-revision-check": ["B10"],
    "calibration-tune": ["B9"],
    "consolidation-ops-check": ["B4"],
    "forgetting-policy-check": ["B7"],
    "gate-suite-check": ["B4"],
    "hosted-llm-check": ["B9"],
    "idp-authz-policy-rollout-check": ["B2"],
    "idp-jwks-live-check": ["B2"],
    "mcp-http-soak": ["B3"],
    "mcp-ops-check": ["B3"],
    "mcp-streamable-http-soak": ["B3"],
    "multimodal-ops-check": ["B6"],
    "ops-dashboard-check": ["B8"],
    "ops-report": ["B8"],
    "parametric-trainer-check": ["B9"],
    "policy-ops-check": ["B2"],
    "privacy-ops-check": ["B7"],
    "projection-recompute-once": ["B4"],
    "provider-check": ["B1", "B2", "B4", "B6", "B7", "B9", "B10"],
    "provenance-ops-check": ["B5"],
    "provenance-trust-check": ["B5"],
    "retrieval-ops-check": ["B1"],
    "tls-cert-check": ["B2"],
    "tls-lifecycle-ops-check": ["B2"],
    "tls-rotation-plan-check": ["B2"],
    "worker-ops-check": ["B4"],
    "worker-run": ["B4"],
}


def parity_lanes_for_command(command: str) -> list[str]:
    return list(PARITY_LANES_BY_COMMAND.get(command, []))


def parity_lane_sort_key(lane: str) -> tuple[int, str]:
    if lane.startswith("B") and lane[1:].isdigit():
        return int(lane[1:]), lane
    return 10_000, lane


def parity_routes_for_lanes(lanes: list[str]) -> list[dict[str, object]]:
    return [
        PARITY_ROUTES[lane]
        for lane in sorted(set(lanes), key=parity_lane_sort_key)
        if lane in PARITY_ROUTES
    ]


def annotate_artifact_routes(artifact: dict[str, object]) -> None:
    lanes: list[str] = []
    checks = artifact.get("checks", [])
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict):
                check_lanes = check.get("parity_lanes", [])
                if isinstance(check_lanes, list):
                    lanes.extend(str(lane) for lane in check_lanes)
    artifact["parity_routes"] = parity_routes_for_lanes(lanes)


def build_parity_row_readiness(
    artifacts: list[dict[str, object]],
    *,
    row_errors: dict[str, list[str]] | None = None,
) -> list[dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    seen_artifacts: dict[str, set[str]] = {}
    seen_checks: dict[str, set[tuple[str, str, str]]] = {}
    includes_exists = any("exists" in artifact for artifact in artifacts)
    row_errors = row_errors or {}

    for artifact in artifacts:
        relative_path = artifact.get("relative_path")
        if not isinstance(relative_path, str) or not relative_path:
            continue
        routes = artifact.get("parity_routes", [])
        if not isinstance(routes, list):
            continue
        checks = artifact.get("checks", [])
        if not isinstance(checks, list):
            checks = []
        exists = artifact.get("exists")
        for route in routes:
            if not isinstance(route, dict):
                continue
            lane = route.get("lane")
            if not isinstance(lane, str) or lane not in PARITY_ROUTES:
                continue
            row = rows.setdefault(
                lane,
                {
                    "lane": lane,
                    "row": PARITY_ROUTES[lane]["row"],
                    "strict_audit_row": PARITY_ROUTES[lane]["row"],
                    "title": PARITY_ROUTES[lane]["title"],
                    "runbook": PARITY_ROUTES[lane]["runbook"],
                    "required_input_artifacts": [],
                    "checks": [],
                },
            )
            seen_artifacts.setdefault(lane, set())
            if relative_path not in seen_artifacts[lane]:
                row["required_input_artifacts"].append(relative_path)
                seen_artifacts[lane].add(relative_path)
            if includes_exists and exists is False:
                row.setdefault("missing_input_artifacts", []).append(relative_path)
            seen_checks.setdefault(lane, set())
            for check in checks:
                if not isinstance(check, dict):
                    continue
                check_lanes = check.get("parity_lanes", [])
                if not isinstance(check_lanes, list) or lane not in check_lanes:
                    continue
                name = check.get("name")
                command = check.get("command")
                option = check.get("option")
                if not all(isinstance(value, str) for value in (name, command, option)):
                    continue
                check_key = (name, command, option)
                if check_key in seen_checks[lane]:
                    continue
                row["checks"].append(
                    {
                        "name": name,
                        "command": command,
                        "option": option,
                    }
                )
                seen_checks[lane].add(check_key)

    for lane, errors in row_errors.items():
        if lane not in PARITY_ROUTES:
            continue
        row = rows.setdefault(
            lane,
            {
                "lane": lane,
                "row": PARITY_ROUTES[lane]["row"],
                "strict_audit_row": PARITY_ROUTES[lane]["row"],
                "title": PARITY_ROUTES[lane]["title"],
                "runbook": PARITY_ROUTES[lane]["runbook"],
                "required_input_artifacts": [],
                "checks": [],
            },
        )
        row.setdefault("input_artifact_errors", []).extend(errors)

    for row in rows.values():
        required = row["required_input_artifacts"]
        if isinstance(required, list):
            row["required_input_artifact_count"] = len(required)
            row["required_input_artifacts"] = sorted(required)
        checks = row["checks"]
        if isinstance(checks, list):
            row["checks"] = sorted(
                checks,
                key=lambda item: (
                    str(item.get("command", "")) if isinstance(item, dict) else "",
                    str(item.get("name", "")) if isinstance(item, dict) else "",
                    str(item.get("option", "")) if isinstance(item, dict) else "",
                ),
            )
        if includes_exists:
            missing = sorted(set(_string_list(row.get("missing_input_artifacts", []))))
            errors = sorted(set(_string_list(row.get("input_artifact_errors", []))))
            row["missing_input_artifacts"] = missing
            row["input_artifact_errors"] = errors
            row["input_artifacts_complete"] = not missing and not errors

    return sorted(rows.values(), key=lambda row: int(row["row"]))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]

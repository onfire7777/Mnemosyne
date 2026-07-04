"""Ops-report metrics push for the self-hosted production profile.

The production observability contract (`infra/observability/vmalert/mnemosyne.yml`)
alerts on ``mnemosyne_ops_report_timestamp_seconds`` and
``mnemosyne_release_gate_open``. This module renders an ops report snapshot as
Prometheus exposition text and pushes it to VictoriaMetrics'
``/api/v1/import/prometheus`` endpoint through the shared fail-closed
``network_safety`` guard, so the tripwire metrics actually exist in the store
instead of the alerts silently watching an absent series.

The exposition renderer is a pure function so its behavior is pinned by unit
tests; only the push helper touches the network, and only through
``validate_fetch_url``/``safe_urlopen`` with an explicit operator-scoped
internal-host allowlist (``MNEMOSYNE_OPS_METRICS_ALLOWED_INTERNAL_HOSTS``),
matching the Vault/Ollama/retrieval provider paths.
"""

from __future__ import annotations

import json
import os
import re
from hashlib import sha256
from typing import Any, Mapping
from urllib import request as urlrequest

from mnemosyne.network_safety import safe_urlopen, validate_fetch_url

_LABEL_SAFE = re.compile(r"[^A-Za-z0-9_.:-]")
_METRIC_SAFE = re.compile(r"[^a-zA-Z0-9_]")


def _label_value(value: str) -> str:
    return _LABEL_SAFE.sub("_", str(value))[:120]


def _metric_suffix(value: str) -> str:
    return _METRIC_SAFE.sub("_", str(value)).strip("_").lower()[:80]


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        if number == number and number not in (float("inf"), float("-inf")):
            return number
    return None


def ops_report_fingerprint(report: Mapping[str, Any]) -> str:
    """Stable SHA-256 fingerprint of the ops report snapshot."""

    payload = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def ops_report_to_prometheus(
    report: Mapping[str, Any],
    *,
    tenant_id: str,
    now_seconds: float,
) -> str:
    """Render an ops report as Prometheus exposition text (pure function).

    Emits the two series the production vmalert rules depend on
    (``mnemosyne_ops_report_timestamp_seconds`` and
    ``mnemosyne_release_gate_open``), a fingerprint info series for the
    dashboard snapshot-provenance contract, and bounded numeric gauges for
    counts, queue state, and tripwire status. Raw string content never enters
    the exposition; only numeric values and sanitized labels.
    """

    tenant = _label_value(tenant_id)
    tripwires = report.get("tripwires") if isinstance(report.get("tripwires"), Mapping) else {}
    passed = tripwires.get("passed") is True
    lines = [
        f'mnemosyne_ops_report_timestamp_seconds{{tenant="{tenant}"}} {float(now_seconds):.3f}',
        f'mnemosyne_release_gate_open{{tenant="{tenant}"}} {0 if passed else 1}',
        f'mnemosyne_tripwires_passed{{tenant="{tenant}"}} {1 if passed else 0}',
        'mnemosyne_ops_report_info{tenant="%s",fingerprint="%s"} 1'
        % (tenant, ops_report_fingerprint(report)),
    ]
    counts = report.get("counts") if isinstance(report.get("counts"), Mapping) else {}
    for key in sorted(counts):
        number = _finite_number(counts[key])
        if number is not None:
            lines.append(
                f'mnemosyne_count{{tenant="{tenant}",kind="{_label_value(key)}"}} {number:g}'
            )
    queue = report.get("queue") if isinstance(report.get("queue"), Mapping) else {}
    for key in sorted(queue):
        number = _finite_number(queue[key])
        if number is not None:
            suffix = _metric_suffix(key)
            if suffix:
                lines.append(f'mnemosyne_queue_{suffix}{{tenant="{tenant}"}} {number:g}')
    learning = report.get("learning") if isinstance(report.get("learning"), Mapping) else {}
    for key in sorted(learning):
        number = _finite_number(learning[key])
        if number is not None:
            suffix = _metric_suffix(key)
            if suffix:
                lines.append(f'mnemosyne_learning_{suffix}{{tenant="{tenant}"}} {number:g}')
    return "\n".join(lines) + "\n"


def ops_metrics_allowed_internal_hosts() -> tuple[str, ...]:
    """Internal hostnames the metrics push may reach (operator allowlist)."""

    raw = os.environ.get("MNEMOSYNE_OPS_METRICS_ALLOWED_INTERNAL_HOSTS", "")
    return tuple(host.strip() for host in raw.split(",") if host.strip())


def push_ops_metrics(url: str, exposition: str, *, timeout: float = 10.0) -> int:
    """POST exposition text to the metrics store through the shared guard.

    The metrics store lives on the isolated internal network (plain HTTP on a
    private address), so the operator must explicitly allowlist its hostname;
    everything else stays fail-closed exactly like the other provider paths.
    """

    hosts = ops_metrics_allowed_internal_hosts()
    validated = validate_fetch_url(
        url,
        allow_insecure_localhost=True,
        allow_internal_hosts=hosts,
        allow_insecure_internal_hosts=hosts,
        purpose="ops metrics push URL",
    )
    req = urlrequest.Request(
        url,
        data=exposition.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
        method="POST",
    )
    with safe_urlopen(req, validated=validated, timeout=timeout) as response:
        return int(getattr(response, "status", 0) or getattr(response, "code", 0) or 0)

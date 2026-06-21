"""Render harness results to JSON + Markdown SLO reports (blueprint §16/§33).

The JSON report is the machine-readable evidence artifact (the "captured evidence
artifact" the §0 definition-of-done requires). The Markdown report is the human
SLO scorecard with confidence intervals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_reports(result: dict[str, Any], out_dir: Path, stamp: str | None = None) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"slo_report_{stamp}.json"
    md_path = out_dir / f"slo_report_{stamp}.md"
    latest_json = out_dir / "slo_report_latest.json"
    latest_md = out_dir / "slo_report_latest.md"

    json_text = json.dumps(result, indent=2, default=str)
    json_path.write_text(json_text)
    latest_json.write_text(json_text)

    md = render_markdown(result)
    md_path.write_text(md)
    latest_md.write_text(md)
    return {"json": json_path, "md": md_path, "latest_json": latest_json, "latest_md": latest_md}


def _fmt_ci(ci: dict[str, Any] | None) -> str:
    if not ci:
        return "—"
    low = ci.get("ci_low")
    high = ci.get("ci_high")
    if low is None or high is None:
        return "—"
    return f"[{low:.4f}, {high:.4f}] ({ci.get('ci_method','')})"


def _verdict_line(v: dict[str, Any], suite_label: str = "") -> str:
    mark = "PASS" if v.get("pass") else "FAIL"
    op = v.get("op", "")
    ci = _fmt_ci(v.get("ci"))
    note = f" — {v['note']}" if v.get("note") else ""
    name = f"{suite_label} · {v['name']}" if suite_label else v["name"]
    return f"| {name} | {v.get('value')} | {op} {v.get('target')} | **{mark}** | {ci}{note} |"


def render_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []
    meta = result.get("meta", {})
    lines.append("# Mnemosyne §33 Evaluation / SLO Report")
    lines.append("")
    lines.append(f"- **Generated:** {meta.get('generated_at','')}")
    lines.append(f"- **Backend:** `{meta.get('backend','local')}`  ")
    lines.append(f"- **Embedding path:** {meta.get('embedding_path','local deterministic (hashing stand-in)')}")
    lines.append(f"- **Ignition mode:** **{result.get('ignition',{}).get('mode','?')}** "
                 f"(suite_size={result.get('ignition',{}).get('suite_size','?')} / N={result.get('ignition',{}).get('ignition_n','?')})")
    lines.append("")
    overall = result.get("overall", {})
    lines.append(f"- **Overall:** {overall.get('passed',0)}/{overall.get('total',0)} checks pass "
                 f"({'ALL GREEN' if overall.get('all_pass') else 'see failures'})")
    if result.get("ignition", {}).get("mode") == "SHADOW":
        lines.append("")
        lines.append("> **SHADOW MODE** — suite has not reached ignition size N. Verdicts below are "
                     "**advisory only** and do not gate promotion (blueprint §33 suite-ignition).")
    lines.append("")

    # SLO scorecard
    lines.append("## SLO scorecard")
    lines.append("")
    lines.append("| Metric | Value | Target | Verdict | 95% CI |")
    lines.append("|---|---|---|---|---|")
    seen_suite_counts: dict[str, int] = {}
    for suite in result.get("slo_suites", []):
        sname = suite.get("suite", "?")
        # Disambiguate repeated suites (e.g. curated vs synthetic retrieval).
        seen_suite_counts[sname] = seen_suite_counts.get(sname, 0) + 1
        label = sname
        if sname == "retrieval":
            label = f"retrieval[{'synthetic' if seen_suite_counts[sname] > 1 else 'curated'}]"
        for v in suite.get("verdicts", []):
            lines.append(_verdict_line(v, suite_label=label))
    lines.append("")

    # Mandatory test classes
    lines.append("## §33 mandatory test classes")
    lines.append("")
    lines.append("| Class | Verdict | Detail |")
    lines.append("|---|---|---|")
    for cls in result.get("mandatory_classes", []):
        mark = "PASS" if cls.get("passed") else "FAIL"
        lines.append(f"| {cls['name']} | **{mark}** | {cls.get('detail','')} |")
    lines.append("")

    # Per-suite detail
    lines.append("## Suite detail")
    lines.append("")
    for suite in result.get("slo_suites", []):
        lines.append(f"### {suite.get('suite','?')}")
        lines.append("")
        lines.append("```json")
        compact = {k: v for k, v in suite.items() if k not in ("per_query", "rows", "bins")}
        lines.append(json.dumps(compact, indent=2, default=str))
        lines.append("```")
        lines.append("")

    # Sharpening note
    lines.append("## How this sharpens with real services")
    lines.append("")
    lines.append(
        "These numbers run against the **local deterministic engine** (hashing pseudo-embeddings + "
        "local lexical reranker). They are real measurements of the current system, but the retrieval "
        "and calibration numbers are **floor estimates**. To sharpen (blueprint FR-3 keystone):"
    )
    lines.append("")
    lines.append("1. Stand up the real embedding + cross-encoder service (docker-compose, §I).")
    lines.append("2. Re-run with `--embedding-provider http --embedding-url ... --reranker-provider http ...` "
                 "passed through `--global-flag`. No harness change is needed — the CLI driver forwards them.")
    lines.append("3. Re-run against Postgres with `--backend postgres --postgres-dsn ...` to measure true "
                 "service-side fast-path latency and prove G8 portability (identical suite, both backends).")
    lines.append("4. Set `MNEMO_EVAL_JUDGE_CMD` to a strict LLM judge to replace the substring judge for G2.")
    lines.append("")
    return "\n".join(lines)

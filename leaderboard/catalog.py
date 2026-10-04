"""Versioned program scope, kept separate from measured result records."""

from html import escape
import json
from pathlib import Path
import re


def load_catalog() -> dict:
    catalog = json.loads(Path(__file__).with_name("catalog.json").read_text())
    if catalog.get("schema_version") != "openmembench.scope-catalog/v1":
        raise ValueError("unsupported scope catalog")
    if not re.fullmatch(r"[0-9a-f]{40}", catalog.get("source_commit", "")):
        raise ValueError("catalog needs an immutable source commit")
    for key, prefix, count in (("capabilities", "C", 24), ("modules", "M", 20)):
        entries = catalog[key]
        if [row["id"] for row in entries] != [f"{prefix}{i:02}" for i in range(1, count + 1)]:
            raise ValueError(f"incomplete or duplicated {key}")
    known = {row["id"] for row in catalog["modules"]}
    for row in catalog["capabilities"] + catalog["joint_scenarios"]:
        if not row["modules"] or not set(row["modules"]) <= known:
            raise ValueError("unknown capability module")
    for field in ("scope_source", "status_source"):
        path = catalog[field]
        if not re.fullmatch(r"docs/[A-Za-z0-9_./-]+\.md", path) or ".." in path.split("/"):
            raise ValueError("catalog source must be a repository document")
    return catalog


def _source(catalog: dict, field: str, label: str) -> str:
    url = ("https://github.com/onfire7777/Mnemosyne/blob/"
           + catalog["source_commit"] + "/" + catalog[field])
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'


def _modules(ids: list[str]) -> str:
    return ", ".join(f'<a href="#{escape(item, quote=True)}">{escape(item)}</a>' for item in ids)


def coverage_body(catalog: dict) -> str:
    rows = "".join(
        f'<tr id="{row["id"]}"><th scope="row">{row["id"]} · {escape(row["name"])}</th>'
        f'<td>{_modules(row["modules"])}</td></tr>'
        for row in catalog["capabilities"]
    )
    modules = "".join(
        f'<section id="{row["id"]}" class="scope-card"><h3>{row["id"]} · {escape(row["name"])}</h3>'
        f'<p>{escape(row["status"])}</p></section>' for row in catalog["modules"]
    )
    scenarios = "".join(
        f'<li><strong>{escape(row["name"])}</strong>: {_modules(row["modules"])}</li>'
        for row in catalog["joint_scenarios"]
    )
    return (
        '<h1>What complete memory needs to prove</h1>'
        '<p class="intro">24 capabilities. 20 modules. Evidence for how they work together.</p>'
        '<div class="prose"><p>This is the scope of the benchmark program, '
        'not a measured system score. It does not certify Mnemosyne or any other system. '
        'Per-system support and quality need separately verified adapters and runs.</p>'
        f'<p>Reviewed {escape(catalog["reviewed_at"])}. '
        + _source(catalog, "scope_source", "Read the whole-memory specification") + ' · '
        + _source(catalog, "status_source", "Inspect the implementation audit") + '</p></div>'
        '<h2>Capability map</h2><div class="table-scroll" role="region" '
        'aria-label="Capability map" tabindex="0"><table class="capability-map"><thead><tr>'
        '<th scope="col">Capability</th><th scope="col">Benchmark modules</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div>'
        '<h2 class="section-heading">Module implementation and remaining evidence</h2>'
        f'<div class="scope-grid">{modules}</div>'
        '<section class="prose"><h2 class="section-heading">Test the interactions too</h2>'
        f'<ul>{scenarios}</ul><p>These joint scenarios remain planned until the relevant '
        'modules and their combined behavior have measured evidence. Passing an isolated '
        'module does not establish the joint result.</p>'
        '<p><a href="benchmarks.html">Explore the benchmark catalog</a> · '
        '<a href="data/catalog.json" download>Download scope catalog (JSON)</a></p></section>'
    )


def benchmarks_body(catalog: dict) -> str:
    rows = "".join(
        f'<tr><th scope="row">{escape(row["name"])}</th><td>{escape(row["status"])}</td>'
        f'<td>{escape(row["policy"])}</td></tr>' for row in catalog["benchmarks"]
    )
    return (
        '<h1>A broader view of memory</h1><p class="intro">Established benchmarks '
        'and a whole-memory program, with their evidence kept distinct.</p>'
        '<div class="prose"><p>This catalog tracks the original planned benchmark '
        'families. A catalog entry is not a result, proof of admission or confirmation '
        'that its full workload runs on this computer.</p>'
        '<h2>Three tracks, separate conclusions</h2><p><strong>Official upstream:</strong> '
        'the original protocol, inputs and scoring, unchanged. '
        '<strong>Enhanced successor:</strong> separately versioned tests with disclosed '
        'differences and controls. <strong>Development:</strong> local fixtures and '
        'conformance tests, never substituted for official results.</p>'
        '<p>LongMemEval-QA is internal-only under the current publication policy. '
        'Retrieval and answer quality remain separate. No combined overall rank is implied.</p>'
        + _source(catalog, "status_source", "Read the full slate and source audit") + '</div>'
        '<h2 class="section-heading">Planned benchmark families</h2>'
        '<div class="table-scroll" role="region" aria-label="Benchmark catalog" tabindex="0">'
        '<table><thead><tr><th scope="col">Family</th><th scope="col">Implementation and evidence</th>'
        f'<th scope="col">Reporting policy</th></tr></thead><tbody>{rows}</tbody></table></div>'
        '<section class="prose"><h2 class="section-heading">Beyond individual benchmark scores</h2>'
        '<p><a href="coverage.html">Explore all 24 capabilities and 20 modules</a>, '
        'including correction, forgetting, provenance, future actions, security and recovery.</p>'
        '<p><a href="comparisons.html#coverage">Read the current landscape and coverage gaps</a> · '
        '<a href="systems.html">Explore memory systems</a> · '
        '<a href="data/catalog.json" download>Download scope catalog (JSON)</a></p></section>'
    )

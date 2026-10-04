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
        '<div class="prose"><p>The Mnemetric Whole-Memory Benchmark is our own suite within '
        'this multi-benchmark platform. This is the scope of the benchmark program, '
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


def _protocol_notes(catalog: dict) -> str:
    return (
        '<details class="protocol-panel" id="protocol-fit"><summary>What these tests see—and what they miss</summary><div class="prose">'
        '<p><strong>Existing benchmarks can evaluate Mnemosyne, but a score does not '
        'describe its whole memory system.</strong> Coverage means which behaviors a '
        'protocol measures. Adapter compatibility means which system interfaces a runner '
        'actually exercises. Limited coverage is not evidence of incompatibility.</p>'
        '<p>For Mnemosyne, the accurate limitation is <strong>partial measurement of '
        'the implemented memory lifecycle</strong>, not that conventional benchmarks '
        'cannot measure it. A question-answering test can measure the benefit of an '
        'internal memory mechanism when that mechanism is enabled during the run. '
        'It cannot establish the behavior of operations the run never invokes. '
        'Any missing integration belongs to our adapter status, not to an assumption '
        'that the benchmark is inherently incompatible.</p>'
        '<p><a href="https://github.com/xiaowu0162/LongMemEval#-testing-your-system">'
        'LongMemEval explicitly supports custom systems</a>: process timestamped histories '
        'and submit answers. Its original tasks cover extraction, multi-session reasoning, '
        'updates, temporal reasoning and abstention. '
        '<a href="https://github.com/snap-research/locomo#data">LoCoMo</a> covers '
        'conversational QA, event summarization and multimodal dialog generation; a QA-only '
        'run covers only part of that release. These are useful measurements, not tests '
        'of every operational property. These statements concern the original protocols, '
        'not every newer version or benchmark in this catalog.</p>'
        '<p>Version matters: the LongMemEval repository now points to '
        '<a href="https://github.com/xiaowu0162/LongMemEval">LongMemEval-V2</a>. '
        'The coverage discussion here concerns the original protocol used by our '
        'current run; it is not a coverage assessment of V2.</p>'
        '<h3>Our current runner has a narrower view</h3>'
        '<p>The local LongMemEval retrieval runner batch-captures each question’s history '
        'into an isolated store, searches it and scores retrieved session IDs. It measures '
        'Recall@5 and nDCG@5, not generated-answer quality. It does not explicitly drive '
        'scheduled consolidation or rehearsal over time, branch/merge workflows, recurring '
        'actions, deletion verification or tenant-isolation attacks. Those capabilities '
        'need their own exercised interfaces and evidence.</p>'
        '<p>For example, answering a question about dates tests temporal reasoning. '
        'It does not by itself test whether a memory survives months of interference, '
        'whether scheduled rehearsal preserves it, or whether a deletion prevents it '
        'from resurfacing. Those are different behaviors requiring explicit workloads '
        'and checks. A retrieval score alone cannot establish them.</p>'
        '<p>Mnemosyne already has implementations and regression tests for several of '
        'these behaviors, including branch/merge, recurring actions and protected-memory '
        'rehearsal. Their complete whole-memory evaluations remain unfinished. '
        '<a href="comparisons.html">Inspect implementation evidence and its limits</a> · '
        '<a href="coverage.html">See module status</a>.</p>'
        '<h3>Fair evidence, including weaknesses</h3>'
        '<p>A low score remains a real result for the tested configuration; untested '
        'features do not cancel it or prove superiority. We must preserve upstream '
        'protocols for comparable results and disclose adapter limitations. Additional '
        'whole-memory tests belong in a separately identified track, with the same '
        'rules available to every participating system.</p>'
        '<h2>Three tracks, separate conclusions</h2><p><strong>Official upstream:</strong> '
        'the original protocol, inputs and scoring, unchanged. '
        '<strong>Enhanced successor:</strong> separately versioned tests with disclosed '
        'differences and controls. <strong>Development:</strong> local fixtures and '
        'conformance tests, never substituted for official results.</p>'
        '<p>LongMemEval-QA is internal-only under the current publication policy. '
        'Retrieval and answer quality remain separate. No combined overall rank is implied.</p>'
        + _source(catalog, "status_source", "Read the full slate and source audit") + '</div></details>'
    )


def benchmarks_body(catalog: dict) -> str:
    cards = []
    for number, row in enumerate(catalog["benchmarks"], 1):
        planned = row["status"].startswith("Planned family;")
        stage = "planned" if planned else "development"
        label = "Planned family" if planned else "Development components"
        cards.append(
            f'<article class="benchmark-card" data-benchmark data-stage="{stage}">'
            f'<div class="card-meta"><span class="card-number">{number:02d}</span>'
            f'<span class="badge badge-{stage}">{label}</span></div>'
            f'<h3>{escape(row["name"])}</h3><p>{escape(row["status"])}</p>'
            '<details><summary>Reporting rules</summary>'
            f'<p>{escape(row["policy"])}</p></details></article>'
        )
    count = len(cards)
    return (
        '<div class="hero catalog-hero"><div><p class="eyebrow">BENCHMARK LIBRARY</p>'
        '<h1>A broader view<br>of AI memory.</h1>'
        '<p class="intro">Explore established benchmarks and the behaviors that a '
        'complete memory system needs to prove.</p></div>'
        '<a class="button secondary hero-aside" href="coverage.html">Explore whole-memory coverage ↗</a></div>'
        '<div class="stats-strip" aria-label="Planned evaluation scope">'
        f'<div class="stat"><strong>{count:02d}</strong><span>Benchmark families</span></div>'
        f'<div class="stat"><strong>{len(catalog["capabilities"]):02d}</strong><span>Memory capabilities</span></div>'
        f'<div class="stat"><strong>{len(catalog["modules"]):02d}</strong><span>Whole-memory modules</span></div>'
        '<div class="stat"><strong>Open</strong><span>Methods &amp; evidence</span></div></div>'
        '<div class="callout"><strong>Coverage is not compatibility.</strong> '
        'Existing benchmarks can evaluate Mnemosyne. Our current runs measure only part '
        'of its memory lifecycle. <a href="#protocol-fit">Understand the limits →</a></div>'
        '<section class="benchmark-library" aria-labelledby="library-title"><div class="library-heading">'
        '<div><p class="eyebrow">THE EVALUATION LANDSCAPE</p><h2 id="library-title">Find a benchmark</h2></div>'
        '<a class="subtle-link" href="data/catalog.json" download>Download catalog ↓</a></div>'
        '<p class="library-description">These are scope and implementation labels, not admission badges or performance '
        'results. A catalog entry is not a result or proof that its full workload runs on this computer.</p>'
        '<div class="library-controls" id="library-controls" hidden>'
        '<label class="search-field"><span class="search-symbol" aria-hidden="true">⌕</span><span class="sr-only">Search benchmarks</span>'
        '<input type="search" id="benchmark-search" placeholder="Search benchmarks, behaviors, or evidence…"></label>'
        '<fieldset class="filter-group"><legend class="sr-only">Implementation stage</legend>'
        '<label><input type="radio" name="stage" value="all" checked><span>All families</span></label>'
        '<label><input type="radio" name="stage" value="development"><span>Development</span></label>'
        '<label><input type="radio" name="stage" value="planned"><span>Planned</span></label></fieldset></div>'
        f'<p id="benchmark-count" class="muted" role="status" aria-live="polite">{count} benchmark families</p>'
        '<div class="benchmark-grid">' + ''.join(cards) + '</div>'
        '<div id="search-empty" class="search-empty" hidden><h3>No matching benchmarks</h3>'
        '<p>Try a broader term or another implementation stage.</p>'
        '<button type="button" id="benchmark-reset">Clear filters</button></div></section>'
        '<section class="feature-band"><div><p class="eyebrow">BEYOND A SINGLE SCORE</p>'
        '<h2>Memory is more than recall.</h2><p>Correction. Forgetting. Provenance. '
        'Future actions. Security. Recovery. Explore the complete planned scope and '
        'the evidence still needed.</p></div>'
        '<a class="button" href="coverage.html">Explore 20 modules →</a></section>'
        + _protocol_notes(catalog)
        + '<p class="section-links"><a href="comparisons.html#coverage">Coverage gaps</a> · '
        '<a href="systems.html">Memory systems</a> · <a href="methods.html">Methodology</a></p>'
    )

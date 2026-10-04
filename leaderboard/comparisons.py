"""Source-reviewed comparisons; no competitor scores or inferred absences."""

from html import escape

SOURCE_ROOT = "https://github.com/onfire7777/Mnemosyne/blob/b0cdbd8986b94c91a3bf20833ed33f405612025a/"

FEATURES = (
    (
        "Evidence you can trace, rebuild and branch",
        "Content-addressed evidence underlies rebuildable beliefs. Tenant memory can be "
        "branched, merged or discarded. Temporal queries preserve the distinction between "
        "current and historical beliefs.",
        "Implemented interfaces and regression coverage; this is not a completed "
        "cross-system reliability benchmark.",
        "Graphiti also documents temporal history and provenance. Those are shared "
        "capabilities, not exclusive Mnemosyne features. Its documented graph design "
        "differs from Mnemosyne's evidence-ledger and branch/merge model.",
        "tests/test_sqlite_branch_merge.py", "Graphiti",
        "https://github.com/getzep/graphiti",
    ),
    (
        "Memory for what to do next",
        "TTL-bounded working memory can be promoted or expired. Signed, session-bound "
        "intentions support triggers and explicit recurrence policies.",
        "Implemented and locally tested. M12 and M13 remain partial: multiweek recurrence, "
        "calibrated controls, lateness magnitude and capacity evidence remain unfinished.",
        "Letta documents editable, shareable in-context memory blocks. MemOS documents "
        "asynchronous ingestion scheduling. Neither description by itself establishes "
        "the same intention-firing contract; this is not proof those products lack it.",
        "tests/test_public_action_recurrence.py", "Letta memory blocks",
        "https://docs.letta.com/v1-sdk/concepts/stateful-agents",
    ),
    (
        "Controlled learning and deletion",
        "Consolidation uses a promotion gate and rollback; deletion has signed evidence "
        "and verification primitives. These controls make change auditable.",
        "Implemented primitives, with deployment-specific evidence still required. "
        "Deletion does not establish unlearning in model weights or every external provider.",
        "Cognee documents session lessons, feedback and deletion; MemOS documents "
        "correction and reusable skills. Learning and forgetting are shared concerns. "
        "Their exact guarantees require contract-level tests, not a feature checklist.",
        "src/mnemosyne/gate.py", "Cognee operations",
        "https://github.com/topoteretes/cognee",
    ),
    (
        "Local memory with explicit access boundaries",
        "Mnemosyne offers local SQLite and PostgreSQL paths, signed sessions, tenant "
        "boundaries and capability checks. BurnOS compatibility has dedicated tests.",
        "Implemented paths and compatibility checks; production readiness still depends "
        "on the selected backend and deployment evidence.",
        "Mem0 offers open-source and managed variants; MemOS offers local and cloud "
        "deployments. Local operation is not unique. Supermemory's documented temporal "
        "graph API and HippoRAG's graph-assisted retrieval provide other design choices.",
        "tests/test_burnos_http_compatibility.py", "MemOS deployment choices",
        "https://github.com/MemTensor/MemOS",
    ),
)

BENCHMARKS = (
    ("LongMemEval", "Information extraction, multi-session reasoning, temporal reasoning, "
     "knowledge updates and abstention in conversational QA.",
     "A QA score does not by itself establish branch rollback, tenant isolation or "
     "scheduled-action correctness.", "https://github.com/xiaowu0162/LongMemEval"),
    ("LoCoMo", "Long conversations with question answering, event summarization and "
     "multimodal dialogue-generation tasks; individual adapters may expose only QA.",
     "Report the task actually run. A QA-only adapter does not test the full release "
     "or establish erasure and operational guarantees.", "https://github.com/snap-research/locomo"),
    ("MemoryAgentBench", "Incremental interactions covering accurate retrieval, test-time "
     "learning, long-range understanding and conflict resolution (selective forgetting "
     "in the paper's terminology).",
     "Conflict-resolution scores do not establish physical erasure from every storage "
     "surface or model unlearning.", "https://github.com/HUST-AI-HYZ/MemoryAgentBench"),
    ("LoCoMo-Plus", "Adds a cognitive category: connecting a later trigger query to "
     "an earlier cue across conversations.",
     "Implicit recall in an answer is different from a persistent scheduler meeting "
     "deadlines, cancellation and recurrence contracts.", "https://github.com/xjtuleeyf/Locomo-Plus"),
    ("MemLens", "Visual and textual conversational memory across long contexts, "
     "including updates, temporal reasoning and answer refusal.",
     "Multimodal accuracy still needs separate access-control, provenance and resource "
     "envelope checks. Disclose full-dataset versus agent-subset evaluation.",
     "https://github.com/xrenaf/MEMLENS"),
    ("OmniMemEval", "A broad framework combining user-memory benchmarks and agent-task "
     "evaluation, including reasoning, information retrieval, knowledge work and coding.",
     "Broad task coverage is valuable. It does not automatically certify this project's "
     "specific invariants; map each release requirement to an actual test and artifact.",
     "https://github.com/MemTensor/OmniMemEval"),
)


def _link(url: str, label: str) -> str:
    return f'<a href="{escape(url, quote=True)}" rel="noreferrer">{escape(label)}</a>'


def comparisons_body() -> str:
    features = "".join(
        f'<section><h3>{escape(title)}</h3><p>{escape(ours)}</p>'
        f'<p><strong>Current evidence:</strong> {escape(status)} '
        f'{_link(SOURCE_ROOT + source, "Mnemosyne source")}</p>'
        f'<p><strong>Comparison:</strong> {escape(comparison)} '
        f'{_link(url, peer)}</p></section>'
        for title, ours, status, comparison, source, peer, url in FEATURES
    )
    rows = "".join(
        f'<tr><th scope="row">{_link(url, name)}</th><td>{escape(coverage)}</td>'
        f'<td>{escape(gap)}</td></tr>'
        for name, coverage, gap, url in BENCHMARKS
    )
    return (
        '<article><h1>Memory is more than recall</h1>'
        '<p class="intro">What stands out in Mnemosyne, what other systems share, '
        'and what a benchmark score leaves unanswered.</p>'
        '<p><a href="#features">Mnemosyne features</a> · '
        '<a href="#coverage">Benchmark coverage</a> · '
        '<a href="#remaining">What remains unproven</a></p>'
        '<div class="prose"><p>Primary-source review: 2026-10-04. This is a scoped '
        'comparison of documented designs and six evaluation projects, not an exhaustive '
        'survey or a measured ranking. “Not documented” does not mean “not supported”. '
        'No exclusive feature or best-system claim has been established.</p>'
        '<h2 id="features">What stands out in Mnemosyne</h2>' + features +
        '<p>Compare the combination and its guarantees, not a count of checkmarks. '
        '<a href="systems.html">Read the source-linked profiles of all eight systems.</a> '
        'Additional comparison sources: '
        + _link("https://github.com/mem0ai/mem0", "Mem0") + ', '
        + _link("https://github.com/MemTensor/MemOS", "MemOS") + ', '
        + _link("https://supermemory.ai/docs/concepts/how-it-works", "Supermemory") + ', '
        + _link("https://github.com/OSU-NLP-Group/HippoRAG", "HippoRAG") + '.</p>'
        '<h2 id="coverage">Where benchmark coverage stops</h2>'
        '<p>Existing benchmarks provide useful evidence, and broader suites are emerging. '
        'Our review does not establish that any one of the six projects below validates '
        'every requirement in Mnemosyne’s release plan. That is a coverage finding for '
        'this plan—not a claim that no solid memory benchmark exists.</p></div>'
        '<div class="table-scroll" role="region" aria-label="Benchmark coverage" tabindex="0">'
        '<table><thead><tr><th scope="col">Benchmark</th><th scope="col">Documented focus</th>'
        '<th scope="col">Additional evidence needed</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div>'
        '<div class="prose"><h2>What a complete memory evaluation should establish</h2>'
        '<p>For this project: recall and grounded answers; change over time and contradictions; '
        'learning without regressions; working-memory limits and future intentions; '
        'provenance and verifiable deletion; isolation and poisoning resistance; confidence '
        'and abstention; multimodal fidelity; latency, cost and resource use; and reproducible '
        'results across supported deployments.</p>'
        '<p>This checklist is derived from '
        + _link(SOURCE_ROOT + "docs/blueprint/eval/00-traceability-matrix.md", "our traceability matrix") +
        ', not a universal scientific definition of memory. Supplemental tests must preserve '
        'upstream benchmark scores, disclose limitations and apply the same rules to every entrant.</p>'
        '<h2 id="remaining">What we still have to prove</h2><p>Mnemosyne has not completed this full evaluation. '
        'Real comparable runs, missing development coverage, deployment evidence and public '
        'reproduction remain open. Our benchmark framework is not proof of our own superiority.</p>'
        '<p><a href="index.html">Inspect the available results</a> · '
        '<a href="methods.html">Read the methods</a></p></div></article>'
    )

# Proof-site preparation and local reader receipt

Date: 2026-10-04. This receipt advances original Plan B L2/L3 and real-run
preparation; it does not close those deliverables or replace Plans A/B.

## Implemented and checked

The existing static renderer now supplies a responsive results table, explicit
empty state, methods reading guide, and consistent result/trace navigation.
Rows preserve record IDs, operator and publication disclosures, supplied
uncertainty and immutable artifact digests. Missing intervals are labeled as
missing; the renderer does not invent a confidence level or a universal ranking.

The CLI supports an empty JSON array without trace mappings. Nonempty results
still require validated trace mappings and existing artifact custody checks.
An empty preview can be generated without synthetic leaderboard entries:

```sh
printf '[]\n' > /tmp/mnemosyne-empty-results.json
python -m leaderboard.render /tmp/mnemosyne-empty-results.json /tmp/mnemosyne-proof-preview
python -m http.server 8791 --bind 127.0.0.1 --directory /tmp/mnemosyne-proof-preview
```

Validation: 352 tests passed across render, output smoke, publish, readiness,
result contract and signed ledger modules. Ten governance/publication-policy
tests passed; Ruff passed for changed Python files. The broader repository
suite remains in progress with four certificate-rotation failures; these
focused passes are not an all-suite or release-readiness claim.

Browser checks used the actual generated pages: Results → Methods → Results;
an explicitly labeled synthetic UI fixture → run disclosures → result →
question trace. This checks navigation only, not measured system quality.
At 390px the empty page has 390px document width and no horizontal overflow.

Visual comparison against the generated desktop concept retained: (1) white
background and navy text; (2) serif headline hierarchy; (3) Results/Methods
navigation; (4) five-column bordered table; (5) explicit empty evidence state;
(6) two explanatory columns, stacked on mobile; (7) operator-entry footer.
The implementation uses a narrower centered content area and native system
body type, so wrapping differs from the concept. Primary copy is preserved.
Local screenshots are in the ignored completion evidence directory.

## Reader runtime restored

Official Ollama 0.35.1 macOS distribution installed in the user's Applications
directory. Deep strict code-signature verification passed; signing authority
is Infra Technologies, Inc. The service binds to `127.0.0.1:11434`.

- CLI SHA-256: `5f0e245e8369a66b7b24654c51c8ec95f3eab9a1e263f6e95e20d2d4374b8e26`.
- Model: `qwen3:8b`, Q4_K_M, 5,225,388,164 bytes as reported by `/api/tags`.
- Installed manifest digest matches the planned pin:
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
- Generic smoke prompt requested the word `READY`; generation returned `READY`
  with `done=true`. It used no benchmark input or protected attempt.
- Host: arm64 Mac, 16 GiB RAM. This does not satisfy physical 8-GiB
  Windows/Linux acceptance or establish performance results.

## Remaining evidence and delivery

| Requirement | Current state / next evidence |
|---|---|
| Original raw benchmark artifacts | Referenced local artifact directory absent; recover or create new properly registered runs, never synthesize old evidence. |
| Frozen Phase 12 v19 candidate | Original external manifest absent; preserve its identity and historical attempt records. Do not recreate a manifest and claim the old digest. |
| Canonical scale gate | Evaluator and unprotected `qa_scale_dev_v1` exist. Exact candidate/runtime-bound 24-case passing receipt still needed before protected execution. |
| Real comparisons | Current-version registered runs under the same protocol, budgets and supported adapters; retain failed attempts and disclose absent systems. |
| L2 completion | Public versioned data, permanent URLs, deployed site, data mirror and at least one real fully browsable system remain unverified. |
| L3 completion | Reading guide and architecture summaries for the eight planned entries are prepared and linked locally. Public deployment and the full transparent methodology remain unfinished. |
| Launch | Register A real evidence, methods paper, populated adversarial report and operational public dispute channel remain open. |

`BOARD-STATUS.md` now distinguishes implemented tools from missing launch
evidence. No gate was removed or marked satisfied by this receipt. BurnOS
production APIs and transport behavior are unchanged by the renderer work.

## Hardware feasibility follow-up

After the owner asked whether this computer could actually run the planned
workload, live inspection identified an Apple M1 Pro with 10 CPU cores and
16 GiB unified memory. The short generation above took approximately 5.01
seconds including 4.56 seconds loading; it used a 2,048-token context and is
not evidence that the full reader workload fits.

A separate synthetic resource preflight invoked the real grounded-reader
provider with 24,000 evidence characters and the unchanged registered decoding
options. A monitor sampled macOS `kern.memorystatus_vm_pressure_level` every
two seconds and terminated the preflight if warning/critical pressure appeared.
Pressure changed from 1 (normal) to 2 (warning) during model loading; the monitor
terminated the caller after 2.04 seconds. Ollama logged client cancellation and
aborted loading. A subsequent check showed normal pressure and no loaded model.
Swap usage remained 722.56 MiB across the sampled interval.

The Ollama log reported a 4,096-token context for the actual reader request,
roughly 5,311 MiB projected Metal allocation and 373 MiB host allocation. These
are runtime estimates, not measured peak resident usage; the canceled load did
not establish sustainable throughput, full-context coverage or completion.
The difference between the default context and maximum evidence budget also
needs verification before a valid full benchmark.

Therefore full local model-benchmark feasibility is **not established under
current application load**. The 24-case scale run has not started, no protected
attempt was consumed, and no model/context/acceptance criterion was weakened.
Continue ordinary code tests locally and existing CI checks. Before model
benchmarks, obtain a successful monitored preflight at the required settings
with sufficient headroom, or use a suitable separately authorized compute host.
Do not close the user's other applications or launch paid compute implicitly.

## Architecture explainer follow-up

`leaderboard/explainers.py` supplies a source-owned `systems.html` page linked
from the methods guide. It covers Mem0, Graphiti/Zep, Letta, Cognee, MemOS,
Supermemory, HippoRAG and Mnemosyne. Summaries were checked against their linked
official documentation/repositories on 2026-10-04, using the historical market
research as a starting inventory rather than copying its dated feature or
performance claims. Each entry links its source; the Mnemosyne link is pinned
to the inspected commit. Hosted products and open-source variants are not
treated as interchangeable. No vendor score is imported as a measured result.

The renderer remains offline: these source links are fixed editorial links,
not fetches or URLs supplied by result records. Its prior result/trace URL
validation remains unchanged. Ruff and 89 relevant render/publication/policy
tests passed. The actual browser path from Methods to the eight-entry guide
was inspected. This prepares L3 content but does not establish its public
publication or close the methods-paper requirement.

## Trace semantics and registered retrieval preparation

A trace review found that the `answer` field in deterministic retrieval runs
contains a retrieved identifier, while the site previously called it a final
answer. The renderer now labels it “Retrieval output (not a generated answer)”.
QA traces retain “Final answer”; unrecognized families use “Recorded output”.
Eighty-five focused rendering, publication and policy checks passed, as did
Ruff. Browser navigation through a synthetic result to its trace confirmed
the corrected label; the temporary synthetic site was then removed and the
empty real-results preview restored.

The signed registration in
`eval/registrations/2026-10-04-longmemeval-retrieval-b0cdbd89/` fixes a
500-question, retrieval-only characterization at source commit
`b0cdbd8986b94c91a3bf20833ed33f405612025a`. Its signature, seven source-file
hashes, clean detached checkout and both raw dataset digests were verified.
The detached checkout creates no additional named branch. Public registration
verification, completion of the existing local test workload, and an exclusive
start receipt remain execution gates. No scoring attempt has started.

`docs/research/OpenMemBench-Methods-Draft.md` records the methods and remaining
publication requirements. Neither this draft nor the single-system retrieval
registration replaces the original comparative roster, QA evaluation,
adversarial report, independent review or public website requirements.

## Feature comparison and coverage review

At the owner's request, the homepage links a new `comparisons.html` page.
It highlights evidence-ledger/branch semantics, working and prospective memory,
gated learning/deletion, and local access boundaries. Each section distinguishes
implemented primitives from remaining validation. It cites the pinned Mnemosyne
source and the relevant peer's documentation. It does not infer that a peer
lacks a capability merely because its overview does not document it.

Primary sources reviewed on 2026-10-04 include the official repositories/docs
for Mem0, Graphiti, Letta, Cognee, MemOS, Supermemory and HippoRAG, linked in the
page and the existing system profiles. Shared features are explicitly credited.
No verified exclusive feature or comparative superiority claim was established.

The benchmark table reviews the official sources for
[LongMemEval](https://github.com/xiaowu0162/LongMemEval),
[LoCoMo](https://github.com/snap-research/locomo),
[MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench),
[LoCoMo-Plus](https://github.com/xjtuleeyf/Locomo-Plus),
[MemLens](https://github.com/xrenaf/MEMLENS), and
[OmniMemEval](https://github.com/MemTensor/OmniMemEval).
These form a scoped review, not an exhaustive catalog. Broader work such as
OmniMemEval is included rather than treating conversational QA as the entire
field. The additional-evidence column is our inference from the documented
task boundary and the original project traceability requirements. It does not
claim that no good memory benchmark exists or that every listed benchmark
lacks every listed capability.

Browser checks verified homepage navigation, the coverage anchor and primary
source links in the rendered page. At a 390px viewport, the page remains 390px
wide; the 540px comparison table scrolls inside its 350px region. Desktop and
mobile screenshots are retained in the completion evidence directory.

## Downloadable evidence

The renderer exports validated result records as JSON. For v2 records it also
exports the exact verified bytes of build/config JSON, the bundle manifest and
raw traces, using the same in-memory snapshots as validation and rendering.
These are individual artifacts, not a complete downloadable benchmark bundle.
Legacy v1 records without verified artifact bindings get only result JSON.
Full raw-data mirrors and public hosting remain separate unfinished delivery.

The JSON projection retains array order for record identity; HTML metric order
remains deterministic. Generated record JSON escapes markup characters without
changing decoded values, while digest-bound files remain byte-for-byte intact.
Production hosting must serve these files as JSON/JSONL downloads with correct
content types and `X-Content-Type-Options: nosniff`; rendering alone does not
configure a host. All source rights and publication gates still apply.

Validation: 85 focused render/publication/policy checks and Ruff passed. The
tests cover exported digest equality and the verified trace snapshot even when
the original file changes after its first read. The full older-source suite
remains running; this is not an all-suite pass claim.

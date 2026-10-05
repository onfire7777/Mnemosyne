# Mnemetric repository ownership

The website and benchmark program now have a dedicated repository:
https://github.com/onfire7777/Mnemetric

Its initial extraction commit is `d42a7ff`. It owns the website, WMBS benchmark
suite, adapters, scoring methodology, benchmark plans and historical evidence.
The local checkout is `/Users/admin/Desktop/Mnemetric`.

Mnemosyne continues to own the memory engine, storage/retrieval/consolidation,
native runtime, serving interfaces and BurnOS compatibility. Mnemetric initially
installs the runtime from exact revision
`e1ad2d0cf5ac19298547740363795c2ad25da356`.

Existing copies here are retained as a compatibility bridge; future benchmark
and website changes belong in Mnemetric. There is no automatic bidirectional
sync. Before removing legacy copies, update dependent CI and scripts through a
reviewed change and verify their replacement interfaces. Historical evidence
must retain its original hashes and source identities.

See Mnemetric's SCOPE.md, .planning/ROADMAP.md, EXTRACTION.json and VALIDATION.md
for ownership, preserved plans, source provenance and current verification limits.
This extraction is not completion of either project's remaining acceptance gates.

## Current delivery locations

The benchmark platform is hosted at https://mnemetric.burnos.app and the distinct
Mnemosyne product presentation at https://mnemosyne.burnos.app. Both use separate
Cloudflare Pages projects and shared BurnOS styling; https://burnos.app and its
existing deployment are unchanged. Source for both presentation sites belongs
to Mnemetric; memory-runtime deployment and public API compatibility remain here.

Mnemetric now retains official MemoryAgentBench source/configuration pins,
complete four-split dataset inventory, SH-6k retrieval diagnostics, prepared
answer requests and strict scoring-input joins. These do not establish full
benchmark execution, answer quality or superiority. Follow its current roadmap
and verification receipts rather than interpreting legacy copies here as current
implementation state. Hosted generation awaits an API key and spending limit;
the owner's current direction is to continue all feasible work without one.

## Explicit read-only evaluation retrieval policy

Mnemetric's four-task MemoryAgentBench diagnostic exposed a budget mismatch:
Mnemosyne's default 4096 estimated-token budget cannot fit two of the official
chunks in any of the 17 tested contexts. Preserve that diagnostic as default
behavior; it is not a ten-chunk comparison.

The public `eval-query-batch` command now accepts `--retrieval-token-budget`
(1..262144) and `--retrieval-top-k` (1..100). They require the existing local
`--evaluation-read-only` mode. When supplied, the command applies a temporary
policy copy and reports the effective `evaluation_policy` in its output.
It does not persist the policy, alter ordinary search defaults, or expose
additional policy controls through BurnOS's MCP interface. Existing commands
without either option retain their output shape.

The real CLI regression exercises two chunks individually larger than the
default budget, verifies both can be returned under the explicit evaluation
budget, checks all store files remain byte-identical, and repeats the default
query to prove its result is unchanged. Bounds are validated before loading
input files or the store. A fair benchmark still needs a declared profile,
matched budget semantics, pinned runtime, and a fresh retained run; the new
options alone establish neither equivalence nor answer quality.

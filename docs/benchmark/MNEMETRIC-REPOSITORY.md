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

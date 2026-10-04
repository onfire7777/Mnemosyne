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

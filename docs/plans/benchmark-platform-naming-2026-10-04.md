# Benchmark platform naming decision

Status: applied to the local website preview, 2026-10-04; public deployment pending.
Parent: [platform experience contract](benchmark-platform-experience-2026-10-04.md).

## Names and meaning

- Website/platform: **Mnemetric** (pronounced “neh-MET-rik”).
- Our benchmark suite: **Mnemetric Whole-Memory Benchmark**.
- Short suite reference after first mention: **Mnemetric WM**.
- Website descriptor: **Evidence for AI memory.**

The coined platform name combines the memory root “mnem-” with “metric”. It
states the platform's purpose without promising a winner, institutional
independence, certification, or universal coverage already achieved. The full
suite name describes the original whole-memory scope: retrieval, change over
time, learning, forgetting, security, action, recovery and operational behavior.
Its version and measured coverage must always accompany results; “whole-memory”
is the intended construct, not proof that every module has shipped.

Mnemetric hosts multiple systems and multiple suites. The Mnemetric Whole-Memory
Benchmark is one suite; LongMemEval, LoCoMo and other upstream benchmarks retain
their own names and attribution. Mnemosyne remains the memory product and one
entrant, with operator conflicts disclosed. Shared memory-related terminology
does not imply independent governance.

## Preliminary collision research

Web searches on 2026-10-04 covered exact names, benchmark/software/company
contexts, and GitHub/PyPI/npm-indexed results. Separate exact queries for
“Mnemetric” and “Mnemetric Bench” returned no results. This is a preliminary
search finding, not proof of worldwide uniqueness or cleared domain/trademark
rights. No domain or account was registered or purchased.

Rejected alternatives:

| Candidate | Finding / decision |
|---|---|
| Memspan | Existing persistent AI-memory product: https://memspan.ai/ |
| Memoraxis | Existing AI business-memory product: https://memoraxis.com/ |
| Memorion | Existing memory-assistant offering: https://memorion.me/en/docs/mcp |
| MemoryBench | Existing research benchmark: https://memorybench.thuir.cn/ |
| OpenMemBench | Existing project working name; descriptive but does not clearly distinguish the platform from its own suite. Retain as historical and technical identifier. |
| Recallibre | More spelling ambiguity; “recall” also overemphasizes retrieval relative to the retained whole-memory scope. |

Mnemetric's tradeoff is the less familiar silent-m spelling. Use the clear AI
memory descriptor beside the name and pronunciation in the about page. Prefer
this meaningful, concise coined name to an unrelated invented word or a
superiority claim such as “Ultimate Memory Benchmark”.

## Rollout and compatibility

Apply the names to site titles, header, explanatory copy and current roadmap
references in a coordinated UI pass. Preserve historical plan titles and explain
the mapping instead of rewriting approved history. Keep OpenMemBench schema
identifiers, WMBS module IDs, CLI flags, package names, immutable record IDs,
registration bytes, signatures, links and BurnOS interfaces unchanged.

Before a public launch, recheck exact and similar names and the intended domain.
Do not claim a domain is available merely because search returns no results.
This naming decision changes no benchmark, acceptance criterion, score, or
publication gate.

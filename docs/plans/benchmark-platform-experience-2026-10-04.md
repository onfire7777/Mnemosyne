# OpenMemBench platform experience and implementation contract

Status: source implementation contract; no measured result or launch approval.
Parent: [full original-plan scope audit](benchmark-platform-scope-audit-2026-10-04.md).
Authority: Plan B L1–L4 and WMBS §§7, 9.5, 9.6, 15. This contract describes
the product surface those plans deferred; it changes no scorer or acceptance gate.

Naming direction: [Mnemetric platform and whole-memory suite](benchmark-platform-naming-2026-10-04.md). Existing technical identifiers remain unchanged.

## Main experience

The homepage is a benchmark workspace. Its first choices are the benchmark,
track/version, comparison division and systems. Readers see results or explicit
missing evidence, then drill into methods, runs and question traces. Mnemosyne
is one entrant; its capability explanation is not the site's main sales pitch.

Retain static hosting and the existing renderer/publication authority. Use
small progressive client-side controls over already validated, locally exported
data. Core content and links work without JavaScript. No browser request to a
vendor, tracking service or mutable score API is needed. Introducing a frontend
framework is optional implementation detail, never a second data authority.

## Information architecture

| Surface | Required content and behavior |
|---|---|
| Benchmark workspace | Filter compatible result groups, select multiple systems, see evidence state and comparison limitations before any sort/rank. Empty state links to scope, systems and methods. |
| Systems directory | Eight initial planned entrants, separately identified product/OSS variants, versioned adapters, native/emulated/unsupported hooks, source links, measured coverage and missing-run reasons. Additional entrants follow the same intake. |
| Benchmark directory | Full original upstream slate and WMBS modules, protocol/version, construct, scoring, required resources, admitted/runnable/measured state, official/successor/development distinction. A named paper without a runnable pin remains unadmitted. |
| Coverage matrix | C01–C24 mapped to M01–M20 and the six joint scenarios; per-system evidence state and links. No score or support claim inferred merely from an architecture description. |
| Comparison detail | Side-by-side compatible metrics, uncertainty, sample size, failed gates, attempt states, model/backend/hardware/resource differences and downloadable projection provenance. |
| Run/trace detail | Existing immutable IDs and permanent paths, exact build/config/bundle/trace digests, per-question evidence, reproduction command, downloads, attempt and supersession links. |
| Methods and trust | Registration, roster, complete attempt ledger, contamination/rights, judge diagnostics, operator conflicts, losses, appeals, change log and archival data. |

The existing `comparisons.html` educational page remains reachable. It is not
renamed into a measured comparison page or used as evidence of superiority.

## Data and projection boundaries

1. **Atomic evidence:** existing result-v1/v2 records, digest-bound artifacts
   and signed ledger. Validate these before making a view. Preserve v1 bytes;
   legacy records without comparison metadata stay browsable but cannot be
   silently upgraded into v2 comparisons.
2. **Catalog metadata:** separately versioned system, benchmark and capability
   descriptors. These describe intended coverage and source evidence, not
   fabricated results. Every status needs an artifact/reference and review
   date. Clearly distinguish program implementation from entrant capability.
3. **Derived views:** projections over named atomic records. Reuse
   `validate_projection`; no manually edited score table. Publish selected IDs,
   filters, exclusions, metric identity, compatibility fields, weighting (if
   any), denominator and uncertainty method. URL query state must reproduce
   the same selection against the same dataset version.
4. **Missing information:** render “not measured” or “metadata unavailable”.
   Never infer sample count, confidence level, hardware, scorer or support
   from a name. A CI range alone does not prove a 95% confidence level.

Compatibility requires the same track kind, benchmark/version, scorer,
metric family/name/unit and division. Compare dataset split, model policy,
backend, resource profile and hardware explicitly from atomic identity and
bound configuration. Local efficiency ranks require identical verified
resource conditions; hosted service outcomes are a separate division.
Absent or incompatible metadata blocks the affected comparison and explains
why; it does not hide the record. Different system/build versions remain
visible. Judge/prompt differences block judged-QA equivalence.

Versioned comparison semantics need to pin any additional metadata that the
current projection-v1 key does not express. Do not invent field values or
reinterpret old projections to get a convenient grouping. The current schema
has limited resource units and uncertainty metadata; show only supported
facts until a compatible, tested extension is defined.

Unknown/malformed compatibility keys and duplicate record selections must be
rejected. Failed safety gates stay prominent and cannot enter an average.
No default all-capability total or cross-track rank. Explicit exploratory
averages may only appear after their compatible population, missingness,
weights and reproducible calculation are implemented and validated.

## Interaction and accessibility acceptance

- Filters have labels, keyboard operation, visible selected state, clear/reset
  actions and result counts. Back/forward and a copied URL preserve selection.
- System selection is not preselected to favor Mnemosyne. Deterministic name
  ordering is the initial fallback; any metric sort states direction and ties.
- Tables retain semantic headers and contained horizontal scrolling on narrow
  screens. Status uses text as well as color. Focus is visible and filter
  updates are announced without moving focus unexpectedly.
- A missing run remains visible via the roster/ledger, with its reason. A
  system with no suitable results is not silently removed from coverage.
- Educational diagrams and charts supplement accessible tables. No invented
  points, scores, error bars or interpolated missing measurements.

## Delivery sequence and validation

1. Harden the existing projection validator before exposing comparison input.
   Regression cases must reject omitted/null compatibility, duplicate source
   selection, incompatible tracks/scorers and hidden safety failures.
2. Add a versioned catalog for the full retained system/benchmark/module scope
   and render benchmark/system/coverage pages. Validate all source links and
   C01–C24/M01–M20 mappings. No fixture is a published result.
3. Define and test comparison metadata extensions, grouping and provenance.
   Test equal-looking metric names with different scorers/splits/units, mixed
   profiles, duplicate attempts and unavailable metadata. A valid record is
   not automatically an eligible comparison.
4. Add progressively enhanced workspace controls and side-by-side views using
   those projections. Exercise selection, reset, sharing, keyboard behavior,
   empty/partial/failed-result states and mobile overflow in the real browser.
5. Connect eligible real bundles, roster/ledger, reproduction and trust pages.
   Preserve raw-byte downloads and fail-closed publication. Synthetic test
   fixtures stay unmistakably labeled and out of the deployed dataset.
6. Deploy only after the original publication gates and concrete approval;
   verify public URLs, trace navigation, download digests and archival access.

Each slice is independently testable but none closes Plan B by itself.
Continue missing benchmark modules, real external adapters and Plan A product
quality work alongside platform implementation. Resource limits determine
where a run happens, not whether its original acceptance requirement survives.

Implementation update: declared-context grouping and the static/progressive comparison workspace are implemented in `leaderboard/grouping.py`, `leaderboard/workspace.py` and `leaderboard/comparison.js`. URL filters pin source identity; missing context remains excluded. Operational admission, full ledger integration and real competitor evidence remain open.

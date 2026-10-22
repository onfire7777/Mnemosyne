# Work Items

| ID | title | role | targets | surface | status | evidence | notes |
|----|-------|------|---------|---------|--------|----------|-------|
| WI-001 | Establish scope and auth | lead | case | process | done | scope.md; case-guard PASS | Includes user-authorized Codex development inference |
| WI-002 | Inspect Hindsight capabilities | research | pinned source/docs | read-only | done | docs/HINDSIGHT-COMPARISON.md | 19 capabilities; no copied code |
| WI-003 | Verify published comparison meaning | ranking | published receipts | read-only | done | benchmark-aggregate.json | Historical 462/500; not a controlled ranking |
| WI-004 | Repair disclosure, date and snapshot defects | implementation | local runtime/eval | source/tests | done | regression and verification logs | Production-wide bug elimination is not established |
| WI-005 | Expose bounded grounded reflection | implementation/review | Python/MCP/CLI | source/tests | done | reflect-after.xml; docs/reflect.md | Independent review; configured live provider untested |
| WI-006 | Preserve local source BM25 ranking | implementation/review | retrieval pipeline | source/tests | done | tests/test_default_source_ranking.py | Mixed/provider/media routes preserved |
| WI-007 | Verify frozen candidate | lead | candidate/test suites | local tests | done | runtime-final-verification.xml | 1672 passed, 114 skipped; broad exploratory run incomplete |
| WI-008 | Evaluate through Codex | lead | official dev split | authorized inference | deferred | codex-eval/ | Five-question smoke completed; larger runs aborted for runtime repairs; no heldout tuning |
| WI-009 | Record report, diagrams and limits | lead | case/docs | documentation | done | docs/2026-10-22-memory-audit-report.md | Full parity remains work; manual maintained answers added in WI-013 |

| WI-010 | Guard summary and proposal source custody | implementation/review | consolidation and scoped reads | source/tests | done | runtime-final-verification.xml; derived-read-custody-verification.xml | Preserve source controls through generation, replay and deletion |
| WI-011 | Repair entity identity and API isolation | implementation/review | resolver and entity boundaries | source/tests | done | entity-identity-after.xml | Distinct Unicode keys; detached mutable values |
| WI-012 | Normalize historical query timestamps | implementation | retrieval pipeline | source/tests | done | as-of-after.log | ISO/datetime parity; reject invalid input before providers |
| WI-013 | Implement private maintained answers | implementation/review | service, three stores, Python/MCP/CLI | source/tests | done | mental-models-final-verification.xml; evidence/E-mental-models.md | 1889 passed, 114 skipped; manual refresh, no live PostgreSQL validation |
| WI-014 | Add durable background refresh and PostgreSQL publication guard | implementation/review | scoped worker, service, Python/MCP/CLI, PostgreSQL | source/tests | done | evidence/E-background-refresh.md | Opt-in leases, retry, recovery, cancellation and authority revalidation; live PostgreSQL remains untested |

## Coverage
- [x] Capability comparison and bounded audit completed; remaining parity gaps recorded
- [x] Observed Critical/High candidates triaged
- [x] Validated findings have Evidence (E-*)
- [x] Call paths documented
- [x] Timeline continuous across major phases
- [x] Report and data-flow diagram drafted following reporting workflow
- [x] Field journal anonymized

## Refs
- skills/ops/timeline-workitem.md
- skills/ops/evidence-finding-path.md

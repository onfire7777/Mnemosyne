# Work Items

Mnemosyne status reconciled on 2026-10-26 against `0d947f5c`. Earlier test counts
remain receipts for their individual phases. The Hindsight research in WI-002
remains pinned to the 2026-10-22 review; this reconciliation is not a new vendor
comparison or benchmark result.

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
| WI-013 | Implement private maintained answers | implementation/review | service, three stores, Python/MCP/CLI | source/tests | done | mental-models-final-verification.xml; evidence/E-mental-models.md | Historical phase: 1889 passed, 114 skipped; manual refresh. Later live PostgreSQL validation is recorded in WI-015. |
| WI-014 | Add durable background refresh and PostgreSQL publication guard | implementation/review | scoped worker, service, Python/MCP/CLI, PostgreSQL | source/tests | done | evidence/E-background-refresh.md | Opt-in leases, retry, recovery, cancellation and authority revalidation; later live PostgreSQL validation is recorded in WI-015. |
| WI-015 | Validate PostgreSQL publication and source-change refresh | implementation/review | disposable PostgreSQL 16.15, restricted roles | live/unit tests | done | [Report and receipts](postgres-live/change-refresh/REPORT.md) | 239 mixed tests passed, including 20 live cases; 9/9 role checks. Production-scale contention remains unmeasured. |
| WI-016 | Implement atomic document revisions | implementation/review | service and three native stores | source/tests | done | [Implementation report](document-revisions/REPORT.md); [contract](../../docs/document-revisions.md) | Owner-scoped create/replace/append/get, CAS, unchanged occurrence reuse, retirement and transactional receipts. Automatic changed-segment extraction, MCP/CLI transport and differing-branch reconciliation remain pending. |

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

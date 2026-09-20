# Phase 15 S4 performance, scale, and resource integration

This is the 15-03-05 integration record for P15-S4. It reconciles the already
merged 15-03-01 through 15-03-04 handoffs onto one exact-head candidate and
reports harness implementation, internally recorded development receipts,
provider-decision output, CAP-006, and CAP-011 as separate states.

It is not an official result, production rollout, hardware receipt, operator
custody packet, public number, or leadership claim. Synthetic-development
receipts and schema stubs are not admitted measurements. This file asserts no
P95, no production 100k behavior, and no physical 8 GiB acceptance.

`.planning/REQUIREMENTS.md` is not updated by this lease.

## Exact-head candidate

- Integration base (GREEN tip that already contains 15-03-01..04 and their
  lease-map receipts):
  `e1424ce049dccc0e91117ee5b59ad3de8dcaa984`
  (`Merge pull request #175`).
- This lease adds only:
  - `eval/reports/phase-15-s4-performance-scale.md`
- Exact HEAD SHA is the commit that lands that path on that base. Do not treat
  the base SHA as the closure HEAD.

## State classes

Do not collapse these states.

| State | Meaning on this tip |
|---|---|
| harness-ready | Deterministic drivers, contract tests, and receipt ABI exist on tip. This is source/harness evidence only. |
| internally recorded | A committed JSON receipt exists. Unless `admitted_measurement` is true, it is not a measured CAP close. |
| measured | An admitted, exact-SHA measurement with operator/hardware admission. **Absent on this tip.** |
| blocked | Named external evidence is missing. The gap is not waived. |

## Predecessor handoffs already on tip

| Task | PR | Merge SHA | Last receipt-writing SHA | Receipt path on tip | Receipt class | `claim_status` |
|---|---|---|---|---|---|---|
| 15-03-01 | #166 | `88724b16b30aa232c03018ec1768362032981d41` | `b1d375374faa5176ab76feb708a81604c9841593` | `eval/latency/reports/phase15-s4-warm.json` | `synthetic-development` | `synthetic-development-receipt-only` |
| 15-03-01 | #166 | `88724b16b30aa232c03018ec1768362032981d41` | `b1d375374faa5176ab76feb708a81604c9841593` | `eval/latency/reports/phase15-s4-concurrent.json` | `synthetic-development` | `synthetic-development-receipt-only` |
| 15-03-02 | #168 | `bd07367a119398680c9ec571dc2dc0bf5c5e4a30` | `78f8ccc183f504fc17d7446ebc9967a8161a47ed` | `eval/provider_bakeoff/reports/phase15-s4-provider.json` | `synthetic-development` | `synthetic-development-receipt-only` |
| 15-03-03 | #169 | `ac5a8aefc4e7713a0f274b48bc681e39090fad13` | `04c41f2e185677e57315eb8bad838cfdfe7420f2` | `eval/scale/reports/phase15-s4-100k.json` | `synthetic-development` | `harness-ready-blocked` |
| 15-03-04 | #174 | `03501545899f5bb2bb15816e217c26002fe58244` | `4acd2f5d1ff2084e71507e9c5ce3c6bb4bcf4537` | `eval/compact_answering/reports/phase15-s4-8gb-windows.json` | `schema-stub` | `harness-ready-blocked` |
| 15-03-04 | #174 | `03501545899f5bb2bb15816e217c26002fe58244` | `4acd2f5d1ff2084e71507e9c5ce3c6bb4bcf4537` | `eval/compact_answering/reports/phase15-s4-8gb-linux.json` | `schema-stub` | `harness-ready-blocked` |

Tip blob SHAs at `e1424ce049dccc0e91117ee5b59ad3de8dcaa984`:

- `eval/latency/reports/phase15-s4-warm.json` `ea3b6ec0b35f807d4997160607993d3e422dc982`
- `eval/latency/reports/phase15-s4-concurrent.json` `cd934d0222e2dbf149dda58fbe3941492b9ac0a1`
- `eval/provider_bakeoff/reports/phase15-s4-provider.json` `b842981f61fa4db19a48666a56fa519fe5e469ec`
- `eval/scale/reports/phase15-s4-100k.json` `20cd3cb22a9030a4fa656ab5987a488f0e60ad21`
- `eval/compact_answering/reports/phase15-s4-8gb-windows.json` `41b927213686b30ff7cde77a293990aebbeb7c88`
- `eval/compact_answering/reports/phase15-s4-8gb-linux.json` `ce6d81311fd60e55d0597c76f2125a74a3ba3978`

Every receipt above records `official_claim: false` and
`admitted_measurement: false`.

## 15-03-01 warm-serial and concurrent latency

Harness landed by #166. Warm-serial and concurrent remain distinct named
distributions and are not merged.

Both committed receipts bind `identity.repository_sha` to
`c871fc10b2470dcca39d602fb7624f2177fa9289`, record
`receipt_class: synthetic-development`, and mark their distributions
`official_claim: false` and `asserted: false`. Warm-serial declares and observes
max in-flight `1` with no overlap. Concurrent declares and observes max
in-flight `3` with overlap and `matches_declaration: true`. Each distribution
records `sample_count: 9`. Those fields identify the synthetic-development
receipts; they are not admitted P95 evidence.

**Harness:** ready. **Measured warm/concurrent P95:** blocked.
This cell does not close CAP-006.

## 15-03-02 provider bake-off

Harness landed by #168. The committed receipt records
`official_p95_claim: false` and `performance_claim: null`.

Its `decision` object is:

- `decision: select`
- `selected: synthetic-a`
- `rollback_value: local`
- `blockers: []`
- `config_promotion: false`
- `requires_retained_measured_evidence: true`

That output is a synthetic-development harness decision, not a configuration
promotion and not a production default. The receipt also records
`identity.repository_sha` as `5c4f47f1db59ab8287d879bf71853198345b23fa`. That
value is cited only as a field inside the tip blob; it is not a reachable git
object on this repository tip.

**Harness:** ready. **Measured identical-workload provider default:** blocked.
This cell does not close CAP-006.

## 15-03-03 100k behavior and production backfill

Harness landed by #169. The committed receipt records
`harness_ready: true`, `claim_status: harness-ready-blocked`,
`identity.based_on_sha: e32e1cb7ceb455ffbfd06ddc6c0bd2d526bfe4d4`,
`identity.item_count: 100000`, and `identity.workload:
phase15-s4-100k-synthetic-dev-v1`. The `item_count` field is harness identity,
not a measured 100k run.

Its query distribution records `sample_count: 0` and `p50_ms` / `p95_ms` /
`p99_ms` as `null`. Its `cap006` object is `{status: open, measured_100k: false}`.
Recorded blockers:

- `admitted_100k_measurement_missing`
- `production_backfill_operator_window_missing`
- `cap006_remains_open`

**Harness:** ready. **Measured 100k and production backfill:** blocked.
This cell does not close CAP-006.

## 15-03-04 physical 8 GiB compact grounded-QA

Harness and schema stubs landed by #174. Both committed receipts record
`receipt_class: schema-stub`, `harness_ready: true`,
`claim_status: harness-ready-blocked`, `physical: false`,
`host_class: development-stub`, `measured: false`,
`identity.based_on_sha: eed2d1f8a531b181665c4d1745b54472df0e7a41`, and
`cap011: {status: open, closes: false, measured: false}`. Quality columns
(`em`, `f1`, `recall_at_5`, `ndcg_at_5`, CAP-003, deterministic retrieval,
grounding, abstention, Section 31, Section 33, custody) are `null`. Recorded
blockers on both platforms:

- `physical_dual_host_measurement_missing`
- `cap011_remains_open`

`.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md` on this tip states that a
stub, development host, or single-platform receipt does not close CAP-011.
Physical dual-host measured runs remain later operator work.

**Harness:** ready. **Measured physical Windows and Linux 8 GiB acceptance:**
blocked. Stub receipts do not close CAP-011.

## CAP row status

This lease does not flip `.planning/REQUIREMENTS.md`. The rows stay Planned
there. The integration record below is the 15-03-05 truth for these two cells.

| ID | Recorded status | Why |
|---|---|---|
| CAP-006 | OPEN | Warm/concurrent, provider, and 100k receipts on tip are synthetic-development or harness-ready-blocked. No admitted measured P95, no measured 100k, no production backfill, and no retained measured provider-default evidence exist. |
| CAP-011 | harness-ready-blocked | Windows and Linux schema stubs are harness-ready only. Physical dual-host measurement is missing. Stubs do not close the row. |

Absent production, 100k, provider-default, physical-host, custody, or protected
evidence remains literally blocked. No asserted, public, official, or
leadership claim is emitted.

## Verify command

The 15-03-05 plan lists:

```bash
uv run --locked python -m pytest eval/latency/test_latency_bench.py eval/tests/test_provider_bakeoff.py tests/test_scale_100k.py tests/test_postgres_perf_lanes.py tests/test_compact_answering_acceptance.py tests/test_planning_traceability.py -q
```

Those commands pin predecessor harness contracts. Passing them does not create
measured CAP-006 or CAP-011 evidence.

`tests/test_planning_traceability.py` binds Phase 15 S4 only through
`.planning/phases/15-security-calibration-performance-and-scale-columns/15-03-PLAN.md`
frontmatter (`CAP-006`, `CAP-011`, `RAIL-001`..`004`). It does not require this
report path to exist. This lease does not add a lease-map or traceability edit.

## Lease boundaries

This lease did not update `GOAL.md`, `.planning/STATE.md`,
`.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, the write-lease map, any
Exact 8 retrieval/pipeline/test path, the CAP-011 acceptance trio, provider
bake-off sources, or scale 100k sources. It does not invent M16 and does not
treat 100k identity fields or stub receipts as measured results.

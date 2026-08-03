# WMBS M01–M20 completeness — recomputation derivation notes

**Recomputed from the tree** at canonical `main@b8673031` plus the unpushed
controller branch `codex/goalex-whole-memory-pilot`. **Documentation only.**
This file authorizes no artifact: no module implementation, no scorer or
registry admission, no protocol change, no publication claim, and no progress
counter movement. It is the audit trail behind
`docs/coordination/2026-08-03-wmbs-module-completeness-inventory.md`; every
non-obvious cell of that inventory cites a line below.

## 1. Method

For each module M01…M20 the recomputation asked six separate questions and
recorded the file path and line for each answer, rather than using the
existence of `eval/public/wmbs_mNN.py` as a proxy:

1. **Approved exact plan** — a per-module implementation contract under
   `docs/plans/` or `docs/superpowers/plans/`, *and* whether that contract is
   frozen/approved or still a `PROPOSED` planning artifact.
2. **Fixture** — a committed file under `eval/public/fixtures/`.
3. **Scorer** — any of: a standalone `eval/public/wmbs_mNN.py`; an inline
   `_score_wmbs_*` branch in `eval/public/scoring.py`; or module logic in
   `eval/public/adapters/whole_memory_reference.py` or `eval/public/bundle.py`.
   A scorer that exists but is **not dispatched** by
   `scoring.py::score_profile` is recorded as *not routable*.
4. **Test suite** — a file under `tests/` exercising the module.
5. **Registry entry** — a key in `eval/public/registry.json`.
6. **Admission state** — the module's feasibility disposition in the standard,
   its `publishable` / `pbpp_headline_eligible` flags where a registry entry
   exists, and the governing lease-map row.

Authorities used: the capability table C01–C24 and the per-module sections of
`docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`;
the pilot plan
`docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`;
and `docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md`.

## 2. Ground-truth probes

### 2.1 Fixtures actually committed

`eval/public/fixtures/` contains exactly eleven files. The WMBS-relevant ones:

| File | Module |
|---|---|
| `wmbs-m01-development.json` | M01 |
| `wmbs-m02-retrieval-development.json` | M02 |
| `wmbs-m03-valid-time-development.json` | M03 |
| `wmbs-m04-development.json` | M04 |
| `wmbs-m05-provenance-development.json` | M05 |
| `wmbs-m10-development.json` | M10 |
| `pm-bench-development.json` | M12 |
| `triggerbench-development.json` | M12 |
| `working-memory-action-development.json` | M13 |

The last three do **not** carry a `wmbs-` prefix, which is why a
prefix-only survey undercounts M12 and M13.

### 2.2 Scorer dispatch — `eval/public/scoring.py`

`score_profile` (`eval/public/scoring.py:34`) routes exactly these profiles:

- `wmbs-m01-v1` → `_score_wmbs_m01` — `scoring.py:35-36`, definition at
  `scoring.py:94` (delegates to `eval/public/wmbs_m01.py`, imported at
  `scoring.py:97`).
- `wmbs-m03-valid-time-v1` → `_score_wmbs_m03_valid_time` —
  `scoring.py:37-38`, definition at `scoring.py:156`. **This scorer is
  implemented inline in `scoring.py`; there is no `eval/public/wmbs_m03.py`.**
  It pins `fixture_id` `wmbs-m03-valid-time-development` at `scoring.py:167`
  and emits `"profile": "wmbs-m03-valid-time-v1"` at `scoring.py:271`.
- `wmbs-m10-v1` → `_score_wmbs_m10` — `scoring.py:39-40`, definition at
  `scoring.py:281` (delegates to `eval/public/wmbs_m10.py`, `scoring.py:284`).
- `working-memory-action-v1` → `_score_working_action` — `scoring.py:43`,
  definition at `scoring.py:392` (M13).
- `pm-bench-action-v1` / `triggerbench-action-v1` → `_score_pm_action` —
  definition at `scoring.py:338`, family selected at `scoring.py:344` (M12).

Non-WMBS profiles also routed: `longmemeval-retrieval-v1` (`scoring.py:46`),
`hipporag-retrieval-v1` (`scoring.py:58`), `qa-em-f1-v1` (`scoring.py:67`).

**No branch dispatches M02, M04, or M05.** `eval/public/wmbs_m02.py:28`
defines `PROFILE = "wmbs-m02-retrieval-v1"` and stamps it into its own output
at `wmbs_m02.py:506`, but that string appears in no `score_profile` branch.
`eval/public/wmbs_m04.py` and `eval/public/wmbs_m05.py` define no `PROFILE`
constant at all. These three are development oracles, not routable scorers.

### 2.3 Module identity constants

- `eval/public/wmbs_m01.py:52` `MODULE_ID = "M01"`; `:54` `FIXTURE_ID =
  "wmbs-m01-development"`; `:55` `FIXTURE_SCHEMA_ID = "wmbs-m01-fixture-v1"`.
- `eval/public/wmbs_m02.py:21` `MODULE_ID = "M02"`; `:23` `FIXTURE_ID =
  "wmbs-m02-retrieval-development"`; `:28` `PROFILE`.
- `eval/public/wmbs_m04.py:18` `MODULE_ID = "M04"`; `:20` `FIXTURE_ID =
  "wmbs-m04-development"`.
- `eval/public/wmbs_m05.py:23` `MODULE_ID = "M05"`; `:24` `FIXTURE_ID =
  "wmbs-m05-provenance-development"`.
- `eval/public/wmbs_m10.py:61` `FIXTURE_SCHEMA_ID =
  "wmbs-m10-development/fixture/0.1"`. This file defines **no** `MODULE_ID`
  constant; its module identity is carried by the adapter and registry.
- M03 has no module file, so it has no identity constant. Its `module_id`
  `"M03"` is asserted by the adapter at
  `eval/public/adapters/whole_memory_reference.py:148` and by the fixture
  contract test at `tests/test_public_whole_memory_reference.py:3128`.

### 2.4 Adapter — `eval/public/adapters/whole_memory_reference.py`

- `:91` `run_m01_development` (M01).
- `:115` `run_m10_development` (M10).
- `:138` `run_m03_valid_time_development` (M03) — canonical timeline ids at
  `:42`, canonical seeds at `:49`, `module_id` assertion at `:148`, fixture id
  at `:145`, non-canonical-matrix rejection at `:159-163`.
- `:254` `run_m15_composed_development` (M15) — composes the M01, M03 and M10
  traces (`:265-269`) and projects the composed equality set (`:285-321`).
- **No adapter entry point exists for M02, M04, M05, or any of M06–M09, M11,
  M13, M14, M16–M20.**

### 2.5 Bundle — `eval/public/bundle.py`

- Seed pins: `:43` `wmbs-m01-development`, `:44`
  `wmbs-m03-valid-time-development`, `:45` `wmbs-m10-development`.
- M15 equality projection at `:94`; its canonical digest at `:158`.
- Profile family/label table at `:313-314` carries only `wmbs-m01-v1` and
  `wmbs-m10-v1` — M03 is absent from that table even though its profile is
  routable, so M03 is scoreable but not bundle-labelled.
- Fixture-shape dispatch at `:700` (`wmbs-m10-development/fixture/0.1`) and
  `:737` (`wmbs-m01-fixture-v1`).

### 2.6 Registry — `eval/public/registry.json`

Full key list: `hipporag-2wiki`, `hipporag-hotpot`, `hipporag-musique`,
`longmemeval-retrieval`, `pm-bench-development`, `triggerbench-development`,
`working-memory-action-development`, `qa-smoke`, `smoke`,
`wmbs-m01-development`, `wmbs-m10-development`, `_pending_qa_suites`,
`_qa_protocol`.

- `wmbs-m01-development` at `registry.json:215` — adapter
  `wmbs-m01-reference` (`:216`), fixture `fixtures/wmbs-m01-development.json`
  (`:220`), scoring profile `wmbs-m01-v1` (`:228`).
- `wmbs-m10-development` at `registry.json:234` — adapter
  `wmbs-m10-reference` (`:235`), fixture `fixtures/wmbs-m10-development.json`
  (`:239`), scoring profile `wmbs-m10-v1` (`:247`).
- `pm-bench-development` and `triggerbench-development` (M12) and
  `working-memory-action-development` (M13) are registry entries too, all with
  `publishable: false`, `pbpp_headline_eligible: false`,
  `headline_eligible: false`, `split_role: "development"`,
  `upstream_comparable: false`.
- **M03 has no registry entry** despite having a routable profile and a
  committed fixture.
- M02, M04, M05 have no registry entry, consistent with the T7 lease.

### 2.7 Tests

- M01 — `tests/test_public_wmbs_m01.py`.
- M02 — `tests/test_public_wmbs_m02.py` (fixture-byte determinism at `:52`,
  seed sensitivity at `:75`, gold observability at `:81`).
- M03 — no dedicated file; covered inside
  `tests/test_public_whole_memory_reference.py`: fixture contract `:3119`
  (`module_id == "M03"` at `:3128`), non-canonical-matrix rejection `:3176`,
  custody rejection `:3213`, adapter+scorer `:3232`, incomplete-matrix
  rejection `:3342`, reduced-matrix rejection `:3360`, replay-mismatch `:3422`.
- M04 — `tests/test_public_wmbs_m04.py` (`:63`, `:80`, `:95`).
- M05 — `tests/test_public_wmbs_m05.py` (`:64`, `:73`, `:85`).
- M10 — `tests/test_public_wmbs_m10.py`.
- M12 — `tests/test_public_pm_bench_triggerbench.py`; the README gap
  disclosure is pinned at `:581`.
- M13 — `tests/test_public_working_memory_action_probe.py`; README gap
  disclosure pinned at `:142`; `PROPOSED` status restated at `:419`.
- M15 — `tests/test_public_whole_memory_reference.py:2208` (frozen replay
  protocol), `:2228` (projection excludes only frozen volatile fields),
  `:3304` (composed cassette passes every exact rail).
- M20 — `tests/test_leaderboard_result_contract.py`,
  `tests/test_leaderboard_ledger.py`, `tests/test_leaderboard_render.py`,
  `tests/test_leaderboard_publish.py`, `tests/test_leaderboard_readiness.py`,
  `tests/test_leaderboard_governance_policy.py`.
- Cross-module ABI — `tests/test_public_wmbs_portable_event_abi.py`.
- Rejected module ids `M00`, `M21`, `M99` are parametrized at
  `tests/test_public_whole_memory_reference.py:1956`, confirming M01–M20 is
  the closed module space.

### 2.8 Plans

Per-module implementation contracts that exist:

| Module | File | Status line |
|---|---|---|
| M02 | `docs/plans/wmb-m02-retrieval-organization-implementation-plan.md` | `Status: PROPOSED (plan document only …)` — line 3 |
| M04 | `docs/plans/wmb-m04-conflict-correction-implementation-plan.md` | `Status: PROPOSED planning artifact…` — line 3 |
| M05 | `docs/plans/wmb-m05-provenance-explanation-implementation-plan.md` | `**Status:** PROPOSED — planning artifact only` — line 5 |
| M14 | `docs/plans/wmb-m14-procedural-task-utility-implementation-plan.md` | `Status: **PLANNING ARTIFACT ONLY — NOT CODE-READY.**` — line 3 |

**None of the four is frozen or approved.** All four were authored at
`origin/main@effc5e03`, and the M14 plan records unrepaired base drift to
`2091d01c` at its head. Under the `GOAL.md` ladder every one of them is at
step 1 complete / step 2 (freeze/approve) outstanding.

M03, M12, M13 and M15 have **round records** rather than module contracts:
`docs/plans/goalex-r17-…`, `goalex-r18-…`, `goalex-r23-…` (M03);
`goalex-r19-…` through `goalex-r22-…`, `goalex-r37-…` (M12/M13);
`goalex-r24-…` (M15); `goalex-r15-…`, `goalex-r16-…` (M01/M10 integration).
A round record authorizes one round; it is not a per-module implementation
contract. The umbrella authority for M01/M03/M10/M12/M13/M15/M20 is
`docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`
together with the standard's §4.1 admission at
`…whole-memory-benchmark-standard-design.md:187`.

### 2.9 Capability mapping and short names

From the capability table (`…standard-design.md:502-524`) and the per-module
headings (`:615`–`:1103`):

| Module | Short name (heading line) | Capabilities |
|---|---|---|
| M01 | Capture and durability (`:615`) | C01, C02, C24 |
| M02 | Retrieval and organization (`:643`) | C01, C03, C07, C08, C24 |
| M03 | Temporal evolution (`:673`) | C04, C24 |
| M04 | Conflict and correction (`:702`) | C05, C24 |
| M05 | Provenance and explanation (`:723`) | C06, C24 |
| M06 | Consolidation and learning (`:748`) | C08, C24 |
| M07 | Retention, rehearsal, and decay (`:776`) | C09, C24 |
| M08 | Reversible forgetting (`:801`) | C10, C24 |
| M09 | Declared-surface erasure conformance (`:822`) | C11, C24 |
| M10 | Calibration and abstention (`:851`) | C12, C24 |
| M11 | Security and isolation (`:877`) | C15, C16, C24 |
| M12 | Prospective action (`:904`) | C13, C24 |
| M13 | Working memory (`:933`) | C14, C24 |
| M14 | Procedural task utility (`:956`) | C07, C08, C23, C24 |
| M15 | Determinism and replay (`:985`) | C02, C17, C24 |
| M16 | Backend and transport parity (`:1008`) | C18, C20, C24 |
| M17 | Custody and recovery (`:1030`) | C02, C19, C24 |
| M18 | Interoperability (`:1053`) | C20, C24 |
| M19 | Multimodal memory (`:1076`) | C21 |
| M20 | Publication integrity (`:1103`) | C06, C17, C22 |

### 2.10 Admission states

`…standard-design.md:609` — "Every module below starts `PROPOSED`." The
per-module feasibility dispositions:

- `PROPOSED`: M01 (`:637`), M02 (`:667`, official adapters `DEFERRED` at
  `:664`/`:668`), M03 (`:697`, conditional; public valid-time surface
  `DEFERRED` at `:694`), M04 (`:719`, branch/merge
  `UNSUPPORTED-BY-SYSTEM` at `:720`), M05 (`:743`,
  explanation-faithfulness `DEFERRED` at `:744`), M06 (`:771`), M07
  (`:798`), M08 (`:818`), M09 (`:846`, P32 paths `DEFERRED` at `:847`),
  M10 (`:872`, numeric-confidence submetrics `UNSUPPORTED-BY-SYSTEM` at
  `:874`), M11 (`:899`, OIDC/P32 `DEFERRED` at `:901`), M12 (`:927`,
  official variants `DEFERRED` at `:930`), M13 (`:951`), M15 (`:1003`),
  M16 (`:1026`, PostgreSQL/hosted HTTP `DEFERRED`), M17 (`:1049`), M18
  (`:1071`), M20 (v2 `admission_state` `PROPOSED` at `:1127`).
- `DEFERRED`: M14 (`:979`), M19 (`:1097`).

Lease-map governance:

- `T7` — `ADMITTED`, lease-map line 183: the M02/M04/M05 Stage-A development
  gap disclosures in `eval/public/README.md`, their pinning tests, and the
  three lifecycle files. Documentation and tests only; no registry entry,
  adapter, runner routing, profile contract or scoring-profile registration;
  M02/M04/M05 stay `PROPOSED` / `publishable:false` /
  `pbpp_headline_eligible:false`; Stage B blocked on the public-harness
  integration owner's lease.
- `U-MODULES` — `SPEC UNSTABLE`, lease-map line 198: module implementation for
  M02, M04–M09, M11, M14, M16–M19, **excluding** the development-only
  M02/M04/M05 evaluation oracles delivered by PR #96. No artifact authorized,
  no lease. Each needs an approved exact plan, protocol, scorer,
  license/custody and dependency placement before code.
- `N12` — `LEASE BLOCKED`, lease-map line 190: additive result-v2 and M20
  publication-integrity dispatch.
- `P14-B` — `BLOCKED on N12`, lease-map line 191: REPRO-001, consumes M15
  replay.
- PR provenance: PR #81 M01/M10 (line 18), PR #82 M12/M13 (line 19), PR #83
  M03 (line 20), PR #84 M15 + composed slice (line 21), PR #90 stranded
  M12/M13 disclosures (line 31), PR #96 M02/M04/M05 development oracles
  (line 69).

## 3. Where `GOAL.md`'s Current Priority counts are wrong

Each item below is a recomputed contradiction of the figures at
`GOAL.md:26-29`. The corrections belong in the inventory; the operator's
directive text is not rewritten.

1. **"only five are implemented" / "implemented (`eval/public/wmbs_*.py`):
   M01, M02, M04, M05, M10 — 5 of 20"** — wrong in both directions, because
   it uses file existence as the test.
   - It **misses M03**, whose scorer is implemented inline as
     `_score_wmbs_m03_valid_time` (`eval/public/scoring.py:156`) and is
     routable via profile `wmbs-m03-valid-time-v1` (`scoring.py:37`), with a
     committed fixture and an adapter entry point
     (`adapters/whole_memory_reference.py:138`) — all without any
     `eval/public/wmbs_m03.py`.
   - It **overstates M02/M04/M05**, which have module files but **no
     `score_profile` dispatch at all** (§2.2). They are development-only
     oracles under `T7`, not scorers the harness can run.
   - It **misses M12, M13, M15 and M20**, which have substantial
     implementations under non-`wmbs_` names: M12 and M13 in
     `scoring.py:338`/`:392` with registry entries and fixtures; M15 in
     `adapters/whole_memory_reference.py:254` and `bundle.py:94`/`:158`; M20
     across `leaderboard/{validate,ledger,render,publish,readiness}.py`.
2. **"registry-admitted: M01, M10 — 2 of 20"** — true only for `wmbs-*`
   registry keys. Counting every registry entry that backs a module, M12
   (`pm-bench-development`, `triggerbench-development`) and M13
   (`working-memory-action-development`) are also registered, all at
   `publishable:false` / `pbpp_headline_eligible:false` / development split.
   Module-backing registry entries therefore cover four modules, not two.
3. **"no plan and no module: M06, M07, M08, M09, M11, M16, M17, M18, M19,
   M20"** — **M20 is misplaced.** M20 publication integrity is one of the
   more heavily implemented modules in the tree: `leaderboard/validate.py`,
   `ledger.py`, `render.py`, `publish.py`, `readiness.py`, plus six
   `tests/test_leaderboard_*.py` suites, and it is governed by an existing
   lease-map row (`N12`, line 190) rather than by `U-MODULES`. The
   genuinely-greenfield set is M06, M07, M08, M09, M11, M16, M17, M18, M19 —
   nine modules, not ten.
4. **"per-module implementation plans: M02, M04, M05, M14 — 4 of 20"** — the
   count of *existing* plans is right, but all four are `PROPOSED` planning
   artifacts (§2.8) authored at `origin/main@effc5e03`; none is frozen or
   approved, and the M14 plan carries unrepaired base drift. Under the ladder
   at `GOAL.md:39-52`, step 2 is outstanding for every one of them, so no
   module is plan-complete in the sense `U-MODULES` requires.
5. **"M03, M12, M13, M15 are candidates — verify in the inventory"** —
   verified, with the state differing per module: M03 has fixture + inline
   scorer + routable profile but **no registry entry and no bundle profile
   label** (`bundle.py:313-314`); M12 and M13 have fixture + scorer +
   registry entry and are gated on evidence rather than on code; M15 has
   adapter and bundle logic and three test rails but **no fixture of its own**
   and no registry entry, since it composes M01/M03/M10.

## 4. Cheapest next step per module (input to the inventory's ranking)

Derived from §2 against the `GOAL.md:39-52` ladder (plan → freeze →
implement → land):

- **M03** — implement: fixture, scorer and profile already exist; the missing
  artifacts are a `registry.json` entry and a `bundle.py` profile label. Blocked
  on the public valid-time surface deferral (`…standard-design.md:694`).
- **M15** — land: adapter, projection, digest and rails exist; needs its own
  fixture and registry admission. Downstream of `P14-B`.
- **M12 / M13** — land: fixture, scorer, registry entry and gap disclosures all
  exist; both stay `PROPOSED` pending real evidence, not pending code.
- **M02 / M04 / M05** — freeze: oracles and tests exist but no plan is approved
  and no scorer is routable. Stage B is leased away from this loop (`T7`).
- **M20** — implementation exists; gated by `N12` `LEASE BLOCKED`.
- **M14** — plan exists but is `DEFERRED` in the standard (`:979`); needs the
  deterministic simulator before anything else.
- **M06, M07, M08, M09, M11, M16, M17, M18, M19** — plan: greenfield, step 1 of
  the ladder, always permitted, no artifact authorized until the plan is
  approved (`U-MODULES`, lease-map line 198).

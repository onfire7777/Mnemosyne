# Benchmark implementation handoff

The primary implementation is `probes.py` (`PROBES` covers F1–F26), with the fixed scripted agent in `simulator.py`, optional command/provider agent in `model_agent.py`, and paired reporting plus exclusive sealed claims in `runner.py`. The manifest's original seed splits and checksums are unchanged. No model provider was called during implementation.

## Implemented and executable

Every family now has specialized operations instead of the generic action stream. It exercises the actual runtime and stores operation/episode/receipt evidence. Tests execute all 26 paths against the local engine with a small budget, reject missing prerequisites, check actual tool capture and held-out separation, inject wrong tool order and read-strengthening, and send all 26 guard mutations through the production writer. The model-transport test uses a local process and checks that private oracle fields are absent.

F9 creates isolated reference tenants; F22 creates an independent chunking-disabled reference tenant and changes task endings so a cached complete parent cannot solve the transfer case. F23 requires nonempty matching-source retrieval and observable standing axes. F25 requires twenty actual selections, both imports observed, equal observed confidence inputs and a prespecified one-sided exact test (alpha .01); empty posteriors cannot pass. A report includes commit, dirty state, seed split, manifest/probe/policy hashes and any sealed reservation.

## Remaining evidence, not claimed success

A 16-episode diagnostic reached missing prerequisites in F4, F8, F10–F12, F15, F19, F21–F22, F24 and F26. F25 now also refuses such a small selection sample. This does not establish that those mechanisms are missing: the actual two-example protocol produced a gate-passed class-wide probation procedure, while the default policy requires twelve tested outcomes plus eight controls for ordinary promotion. Ten-percent exploration generally needs a much larger budget than sixteen or sixty-four episodes. No active states or scores were fabricated to bypass this requirement.

No full all-arm benchmark, sealed run, external-model run, live PostgreSQL run, production longitudinal experiment, or latency acceptance result was completed. The public seeded fixture templates are not an independently authored unseen quality corpus. The README preserves that limitation.

## Concrete remaining evaluation work

- Run budgets sufficient for real probation, schema, revision and chunk prerequisites, then inspect raw failures. A missing observed activation is reported separately from a family acceptance failure.
- Add independently authored semantic corruption fixtures for the deeper family-specific paths (revision A/B, schema assimilation, chunking, extinction and calibrated ordering). The existing 26 writer fault fixtures prove guard detection/containment; they do not prove semantic mutation sensitivity in each family.
- Advanced baseline arms can legitimately stop before a learning-only prerequisite, so their executed workloads differ. The reporter refuses an AULC comparison in that case. A separate common-pretraining experiment design is needed if the scientific question requires frozen/no-memory benefit estimates after an already learned schema, revision, or chunk. Do not remove alignment checks to manufacture these comparisons.
- Non-benefit ablations now use preregistered mechanism endpoints and directions in `ablation_metrics`; they require supported matching-budget probes for every seed. Benefit comparisons still require aligned task rows and positive paired AULC lift. Run and inspect these endpoints rather than treating safety counts as success curves.
- Production UUIDs and competition can affect runtime candidate identity/order despite a fixed agent seed. The report records requested seeds and code hashes but does not claim bitwise deterministic runtime execution.

## Longer development diagnostic

On 2026-11-05, the local scripted F2 environment ran 128 task instances with development seed 17 after the final statistical-monitor fixes.

| Arm | AULC | Final-window success | Active procedures | Guard detections |
| --- | --- | --- | --- | --- |
| Learning on | 0.5288 | 0.90 | 1 | 0 |
| Memory frozen | 0.2663 | 0.20 | 0 | 0 |
| No memory | 0.2374 | 0.10 | 0 | 0 |

The learning arm's held-out ordered-step success was 0.8594. The existing F2 family verifier requires 1.0, so all three family verdicts remained unsuccessful. This single-seed diagnostic establishes that a procedure can enter active service through real outcomes. Paired multi-seed acceptance, the other families and mechanism ablations still require evaluation.

# OQ5 Suite-Ignition Curated Seed Set

**Blueprint refs:** OQ5 · FR-14 · FR-17 (§33 cold-start fix; §17 P1 decision)

This is the **completion-additive half of OQ5**: the curated regression corpus
that decides whether Mnemosyne's promotion gate runs in **SHADOW** (log-only,
never merges) or **ACTIVE** (verdicts bind, a regression blocks promotion).

It is exactly the data that `PromotionGate.ignition_status`
(`src/mnemosyne/gate.py`, to be wired by Codex — see reconciliation note below)
will consume to make that SHADOW/ACTIVE decision.

## The OQ5 rule (verbatim intent)

> Flip shadow→active at **N_active = 30 curated** cases (≥20 curated held-out,
> ≥5 genuine, all protected tiers); **synthetic never counts** (capped 2× curated).
> — `docs/decisions/SECTION-17-OPEN-QUESTIONS.md`, OQ5

- `N_active` counts **curated + genuine** only.
- **synthetic NEVER counts** toward ignition; it is bounded at **2× curated**.
- Slice floors: **≥20 curated**, **≥5 genuine**, ≥1 protected case present.

## What's here

| File | Role |
|---|---|
| `cases.json` | The seed corpus. 42 cases, each tagged `origin ∈ {curated, genuine, synthetic}`, in `RegressionCase` shape. |
| `loader.py` | Loads `cases.json` into `mnemosyne.gate.RegressionCase` objects + carries `origin`. |
| `ignition_status.py` | Computes & renders SHADOW/ACTIVE readiness vs `N_active=30`. |
| `__init__.py` | Public API re-exports. |

### Current composition

- **24 curated** trusted held-out cases (≥20 required)
- **8 genuine**-style cases modelled on real episode phrasing (≥5 required)
- **10 synthetic** = the permanent protected/attack tier (6 MINJA/AgentPoison
  poison probes + 2 permanent isolation rails + 2 self-mined probes) — **excluded
  from N_active**, within the 48-case cap.
- **N_active = 32 ≥ 30 → ACTIVE.** Tiers present: `smoke`, `core`, `archive`.
  18 protected cases (10 active + 8 synthetic).

## Usage

```python
from eval.ignition_seed import (
    load_seed_cases,        # list[LoadedCase] (RegressionCase + origin)
    regression_cases,       # list[RegressionCase] — what PromotionGate takes
    active_cases,           # curated+genuine only
    compute_ignition_status,
    N_ACTIVE,               # 30
)

status = compute_ignition_status()
assert status.mode == "ACTIVE"          # 32 >= 30
assert status.counts["synthetic"] == 10 # excluded from n_active
```

Readiness reporter (markdown / JSON; exits non-zero in SHADOW so CI can gate):

```bash
PYTHONPATH=src:. python -m eval.ignition_seed.ignition_status          # markdown
PYTHONPATH=src:. python -m eval.ignition_seed.ignition_status --json   # machine
PYTHONPATH=src:. python -m eval.ignition_seed.ignition_status --n-active 40
```

Tests: `eval/tests/test_ignition_seed.py` (run with `.venv-eval`).

## Forward-compatibility (FR-14 reconciliation)

The **current** `RegressionCase` dataclass does **not** yet accept `origin`/`mode`
(verified: `from_dict({... 'origin': 'curated'})` raises `TypeError`). The OQ5
decision requires Codex to add `origin` + `mode` to `RegressionCase` and a
`PromotionGate.ignition_status` method in `src/mnemosyne/gate.py`.

`loader.py` is written to work against **both** shapes: it introspects the
dataclass fields and only passes `origin`/`mode` into the constructor when the
dataclass declares them; otherwise it strips them and carries `origin` alongside
in `LoadedCase`. So this seed set is loadable today and stays correct after the
`src` change lands. The counting rules in `ignition_status.py` are the
spec-by-example for the method Codex will implement.

## Security note

Every string in `cases.json` is **inert regression data**. The poison cases
(e.g. "ignore all previous instructions …", "SYSTEM: developer mode …") are
adversarial **fixtures** that assert the gate *blocks* such injections — they are
loaded verbatim and never executed or obeyed.

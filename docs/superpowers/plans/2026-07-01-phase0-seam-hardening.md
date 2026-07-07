# Phase 0: Engine-Seam Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the genuinely-duplicated retrieval algorithms into one engine-agnostic module, add the CID journal + projection registry + honeytokens + benchmark harness, and parametrize the parity suite — so Phases 1–4 (Rust kernels, SqliteEngine, providers, front-end) plug into hardened seams with zero behavior change.

**Architecture:** Pure-Python phase, no new runtime dependencies. New modules `algorithms.py`, `journal.py`, `projections.py`, `honeytokens.py` under `src/mnemosyne/`. Both engines (`LocalMemoryEngine`, `PostgresEngine`) delegate to shared pure functions; behavior is pinned by characterization tests written BEFORE each extraction and by the existing 900+-test suite.

**Tech Stack:** Python 3.12 (stdlib only for runtime code), pytest 9.1.1, `hypothesis` + `pytest-benchmark` (dev group only), uv.

## Global Constraints

- Runtime dependency set stays exactly `["cryptography>=42"]` — new runtime modules are stdlib-only; `hypothesis` and `pytest-benchmark` go in `[dependency-groups] dev` only.
- **Zero behavior change:** every extraction preserves byte-identical outputs; the full suite (`uv run --locked python -m pytest`) must pass after every task; no live-Postgres tests may regress when `MNEMOSYNE_POSTGRES_DSN` is set.
- **Gate-name stability (spec §4.0):** the strings `postgres-fts`, `postgres-recursive-ppr`, `local-bm25-lite`, `local-ppr` must survive unchanged (`retrieval.py:1354-1355,1401-1402`, `postgres_engine.py:121-122`).
- PPR constants are load-bearing: 12 iterations, 0.85 share, 0.15 teleport (`engine.py:1369-1377`).
- Journal ordering (spec §4.0): engine commit FIRST, journal append+fsync SECOND; engine ledger authoritative on divergence; journal-only CIDs raise an alarm, never auto-repair.
- All commands run from `/Users/admin/Mnemosyne`; test invocation form: `uv run --locked python -m pytest <path> -v`.
- Commit style: `type(scope): summary` (repo convention), one commit per task minimum.
- Do NOT touch: gates/rails logic, `sql/schema.sql`, `infra/`, CID computation, `mcp_tools.py`.

---

### Task 1: `algorithms.py` — RRF fusion extraction

**Files:**
- Create: `src/mnemosyne/algorithms.py`
- Modify: `src/mnemosyne/engine.py:2753-2769` (`LocalMemoryEngine._rrf`)
- Modify: `src/mnemosyne/postgres_engine.py:4165-4197` (`PostgresEngine._rrf`)
- Test: `tests/test_algorithms.py` (new)

**Interfaces:**
- Consumes: `Hit` dataclass from `mnemosyne.retrieval` (fields used: `kind: str`, `id: str`, `score: float`, `channel: str`).
- Produces: `rrf_fuse(ranked_lists: list[list[Hit]], k: int, *, rrf_k: float) -> list[Hit]` — later tasks and Phase-1 kernels call exactly this.

- [ ] **Step 1: Write the characterization test (pins current behavior before any move)**

```python
# tests/test_algorithms.py
"""Shared retrieval-algorithm module: characterization + delegation tests."""
from __future__ import annotations

import copy

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.retrieval import Hit

def _hit(kind: str, id_: str, score: float, channel: str) -> Hit:
    return Hit(kind=kind, id=id_, text=f"text-{id_}", score=score, channel=channel)

def _sample_lists() -> list[list[Hit]]:
    dense = [_hit("evidence", "a", 0.9, "dense_hash"), _hit("evidence", "b", 0.7, "dense_hash")]
    lexical = [_hit("evidence", "b", 3.0, "lexical"), _hit("evidence", "c", 1.0, "lexical")]
    graph: list[Hit] = []
    return [dense, lexical, graph]

def test_rrf_fuse_matches_engine_private_rrf():
    from mnemosyne.algorithms import rrf_fuse

    engine = LocalMemoryEngine()
    lists = _sample_lists()
    expected = engine._rrf(copy.deepcopy(lists), k=4)
    actual = rrf_fuse(copy.deepcopy(lists), k=4, rrf_k=engine.policy.rrf_k)
    assert [(h.kind, h.id, h.score, h.channel) for h in actual] == [
        (h.kind, h.id, h.score, h.channel) for h in expected
    ]

def test_rrf_fuse_merges_channels_and_dedups_by_kind_id():
    from mnemosyne.algorithms import rrf_fuse

    fused = rrf_fuse(_sample_lists(), k=10, rrf_k=60.0)
    b = next(h for h in fused if h.id == "b")
    assert b.channel == "dense_hash+lexical"
    assert len([h for h in fused if h.id == "b"]) == 1
    # rank-1 in one list + rank-2 in another beats a single rank-1
    assert fused[0].id == "b"
```

If `Hit(...)` requires more constructor arguments than shown, open `src/mnemosyne/retrieval.py`, find `class Hit`, and pass the minimal required fields with neutral defaults (e.g. `trust_tier=3`, `metadata={}`) — do not change the assertions.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --locked python -m pytest tests/test_algorithms.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mnemosyne.algorithms'`

- [ ] **Step 3: Create `algorithms.py` with `rrf_fuse` (verbatim body from `engine.py:2753-2769`, `self.policy.rrf_k` → parameter)**

```python
# src/mnemosyne/algorithms.py
"""Engine-agnostic retrieval algorithms (blueprint §22, spec §4.0).

Single source of truth for algorithms previously duplicated across
LocalMemoryEngine and PostgresEngine. Pure functions only: no engine
state, no I/O, no policy object — every tunable is a parameter.
Phase-1 native kernels (mnemosyne._native) mirror these signatures.
"""
from __future__ import annotations

import copy
from collections import defaultdict

from mnemosyne.retrieval import Hit

def rrf_fuse(ranked_lists: list[list[Hit]], k: int, *, rrf_k: float) -> list[Hit]:
    by_id: dict[tuple[str, str], Hit] = {}
    scores: dict[tuple[str, str], float] = defaultdict(float)
    channels: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            key = (hit.kind, hit.id)
            by_id[key] = hit
            scores[key] += 1.0 / (rrf_k + rank)
            channels[key].append(hit.channel)
    fused = []
    for key, hit in by_id.items():
        item = copy.deepcopy(hit)
        item.score = scores[key]
        item.channel = "+".join(sorted(set(channels[key])))
        fused.append(item)
    return sorted(fused, key=lambda item: item.score, reverse=True)[:k]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --locked python -m pytest tests/test_algorithms.py -v`
Expected: 2 PASS

- [ ] **Step 5: Delegate both engines' `_rrf` to `rrf_fuse`**

First diff the Postgres copy against the Local copy to confirm they are identical up to `self.policy.rrf_k`:
`sed -n '2753,2769p' src/mnemosyne/engine.py > /tmp/local_rrf.txt && sed -n '4165,4197p' src/mnemosyne/postgres_engine.py > /tmp/pg_rrf.txt && diff /tmp/local_rrf.txt /tmp/pg_rrf.txt`
If the Postgres body has extra logic beyond the Local body, STOP and add that logic as a keyword parameter to `rrf_fuse` (default preserving Local behavior) instead of deleting it. Then replace both method bodies with:

```python
    def _rrf(self, ranked_lists: list[list[Hit]], k: int) -> list[Hit]:
        return rrf_fuse(ranked_lists, k, rrf_k=self.policy.rrf_k)
```

Add `from mnemosyne.algorithms import rrf_fuse` to the import block of each file.

- [ ] **Step 6: Run the full suite**

Run: `uv run --locked python -m pytest -q`
Expected: same pass count as on `main` before this task (capture it first with `git stash && uv run --locked python -m pytest -q; git stash pop` if unsure). Zero new failures.

- [ ] **Step 7: Commit**

```bash
git add src/mnemosyne/algorithms.py src/mnemosyne/engine.py src/mnemosyne/postgres_engine.py tests/test_algorithms.py
git commit -m "refactor(algorithms): extract shared RRF fusion into mnemosyne.algorithms"
```

---

### Task 2: `u_curve_order` + `fit_budget` extraction

**Files:**
- Modify: `src/mnemosyne/algorithms.py`
- Modify: `src/mnemosyne/engine.py:2801-2822` (`_u_curve_order`, `_fit_budget` statics)
- Modify: `src/mnemosyne/postgres_engine.py:4223+` (its `_u_curve_order` and, if present, `_fit_budget` — locate with `grep -n '_fit_budget' src/mnemosyne/postgres_engine.py`)
- Test: `tests/test_algorithms.py`

**Interfaces:**
- Produces: `u_curve_order(hits: list[Hit]) -> list[Hit]`; `fit_budget(hits: list[Hit], budget: int) -> tuple[list[Hit], int]` (uses `mnemosyne.text.approx_tokens`).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_algorithms.py`:

```python
def test_u_curve_order_interleaves_front_back():
    from mnemosyne.algorithms import u_curve_order

    hits = [_hit("evidence", str(i), 1.0 - i * 0.1, "lexical") for i in range(5)]
    ordered = u_curve_order(hits)
    assert [h.id for h in ordered] == ["0", "2", "4", "3", "1"]

def test_fit_budget_skips_items_over_budget_and_reports_usage():
    from mnemosyne.algorithms import fit_budget
    from mnemosyne.text import approx_tokens

    small = _hit("evidence", "s", 1.0, "lexical")
    small.text = "tiny"
    big = _hit("evidence", "b", 0.9, "lexical")
    big.text = "x" * 4000
    kept, used = fit_budget([big, small], budget=approx_tokens("tiny") + 1)
    assert [h.id for h in kept] == ["s"]
    assert used == approx_tokens("tiny")

def test_extracted_helpers_match_engine_statics():
    from mnemosyne.algorithms import fit_budget, u_curve_order

    engine = LocalMemoryEngine()
    hits = [_hit("evidence", str(i), 1.0 - i * 0.05, "lexical") for i in range(7)]
    assert [h.id for h in u_curve_order(hits)] == [h.id for h in engine._u_curve_order(hits)]
    assert fit_budget(hits, 50) == engine._fit_budget(hits, 50)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --locked python -m pytest tests/test_algorithms.py -v -k "u_curve or budget"`
Expected: FAIL with `ImportError: cannot import name 'u_curve_order'`

- [ ] **Step 3: Add both functions to `algorithms.py` (verbatim bodies from `engine.py:2801-2822`)**

```python
from mnemosyne.text import approx_tokens

def u_curve_order(hits: list[Hit]) -> list[Hit]:
    front: list[Hit] = []
    back: list[Hit] = []
    for idx, hit in enumerate(hits):
        if idx % 2 == 0:
            front.append(hit)
        else:
            back.insert(0, hit)
    return front + back

def fit_budget(hits: list[Hit], budget: int) -> tuple[list[Hit], int]:
    kept: list[Hit] = []
    used = 0
    for hit in hits:
        cost = approx_tokens(hit.text)
        if used + cost > budget:
            continue
        kept.append(hit)
        used += cost
    return kept, used
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run --locked python -m pytest tests/test_algorithms.py -v`
Expected: all PASS

- [ ] **Step 5: Delegate both engines (same diff-first discipline as Task 1 Step 5)**

```python
    @staticmethod
    def _u_curve_order(hits: list[Hit]) -> list[Hit]:
        return u_curve_order(hits)

    @staticmethod
    def _fit_budget(hits: list[Hit], budget: int) -> tuple[list[Hit], int]:
        return fit_budget(hits, budget)
```

- [ ] **Step 6: Full suite**

Run: `uv run --locked python -m pytest -q` — zero new failures.

- [ ] **Step 7: Commit**

```bash
git add -u && git add tests/test_algorithms.py
git commit -m "refactor(algorithms): extract u_curve_order and fit_budget"
```

---

### Task 3: PPR power iteration extraction

**Files:**
- Modify: `src/mnemosyne/algorithms.py`
- Modify: `src/mnemosyne/engine.py:1365-1380` (inline power iteration inside `graph_ppr`)
- Modify: `src/mnemosyne/postgres_engine.py:2040-2052` (identical inline copy)
- Test: `tests/test_algorithms.py`

**Interfaces:**
- Produces: `ppr_power_iteration(adjacency: dict[str, list[str]], matches_seed: Callable[[str], bool], *, iterations: int = 12, damping: float = 0.85) -> dict[str, float]` — Phase-1 kernel mirrors this; Phase-2 cached-PPR projection calls it.

- [ ] **Step 1: Write failing test**

```python
def test_ppr_power_iteration_constants_and_ranking():
    from mnemosyne.algorithms import ppr_power_iteration

    adjacency = {"seed": ["a", "b"], "a": ["b"], "b": [], "island": []}
    ranks = ppr_power_iteration(adjacency, lambda n: n == "seed")
    # b receives mass from both seed and a -> outranks a; island gets nothing
    assert ranks["b"] > ranks["a"] > 0.0
    assert ranks.get("island", 0.0) == 0.0
    # teleport keeps the seed's own rank anchored at >= 0.15
    assert ranks["seed"] >= 0.15

def test_ppr_power_iteration_is_deterministic():
    from mnemosyne.algorithms import ppr_power_iteration

    adjacency = {"s": ["x", "y"], "x": ["y"], "y": ["x"]}
    r1 = ppr_power_iteration(adjacency, lambda n: n == "s")
    r2 = ppr_power_iteration(adjacency, lambda n: n == "s")
    assert r1 == r2
```

- [ ] **Step 2: Run — expect ImportError failure**

Run: `uv run --locked python -m pytest tests/test_algorithms.py -v -k ppr`

- [ ] **Step 3: Implement (verbatim body from `engine.py:1369-1377`, seeds handled by caller)**

```python
from collections.abc import Callable

def ppr_power_iteration(
    adjacency: dict[str, list[str]],
    matches_seed: Callable[[str], bool],
    *,
    iterations: int = 12,
    damping: float = 0.85,
) -> dict[str, float]:
    """Personalized PageRank by power iteration (blueprint §22.2 deep mode).

    Constants 12/0.85/0.15 are load-bearing for parity with both shipped
    engines — do not change defaults without a cross-engine golden update.
    """
    teleport = 1.0 - damping
    ranks = {node: (1.0 if matches_seed(node) else 0.0) for node in adjacency}
    for _ in range(iterations):
        next_ranks = {node: teleport * (1.0 if matches_seed(node) else 0.0) for node in ranks}
        for node, neighbors in adjacency.items():
            if not neighbors:
                continue
            share = damping * ranks.get(node, 0.0) / len(neighbors)
            for neighbor in neighbors:
                next_ranks[neighbor] = next_ranks.get(neighbor, 0.0) + share
        ranks = next_ranks
    return ranks
```

Note one deliberate, behavior-preserving deviation from the inline code: the inline version seeds `ranks.setdefault(seed, 1.0)` for seeds absent from `adjacency`. Keep that in the CALLER (both engines do it before the loop today) — the pure function operates on `adjacency` keys only. When replacing the inline loops, keep each engine's `for seed in seed_set: ranks.setdefault(seed, 1.0)` line by pre-inserting missing seeds into `adjacency` as `adjacency.setdefault(seed, [])` before calling the function; verify with the existing graph tests.

- [ ] **Step 4: Run — expect PASS**, then replace both inline loops:

```python
        for seed in seed_set:
            adjacency.setdefault(seed, [])
        ranks = ppr_power_iteration(adjacency, matches_seed)
```

(the post-loop `sorted(ranks.items(), ...)` consumption code stays where it is in each engine).

- [ ] **Step 5: Full suite** — `uv run --locked python -m pytest -q`, zero new failures. If `MNEMOSYNE_POSTGRES_DSN` is available, also run `uv run --locked python -m pytest tests/test_parity_retrieval.py tests/test_shared_engine_contract.py -q`.

- [ ] **Step 6: Commit**

```bash
git add -u && git commit -m "refactor(algorithms): extract shared PPR power iteration (12/0.85/0.15 pinned)"
```

---

### Task 4: MMR extraction (parameterized per engine — NO unification of embedding sourcing)

**Files:**
- Modify: `src/mnemosyne/algorithms.py`
- Modify: `src/mnemosyne/engine.py:2771-2799` (`LocalMemoryEngine._mmr`)
- Modify: `src/mnemosyne/postgres_engine.py:4199-4220` (`PostgresEngine._mmr`)
- Test: `tests/test_algorithms.py`

**Interfaces:**
- Produces: `mmr_select(hits: list[Hit], k: int, *, query_vec: list[float], embed_hit: Callable[[Hit], list[float] | None], mmr_lambda: float) -> list[Hit]`. Spec §4.1 kernel ABI is derived from this exact signature (objective = λ·rel − (1−λ)·max_sim **+ hit.score**; missing vector ⇒ relevance 0, no diversity penalty; strict `>` argmax = first-wins tie-break on input order).

- [ ] **Step 1: Write failing tests (pin the three semantics the spec's review flagged)**

```python
def test_mmr_select_matches_local_engine_mmr():
    from mnemosyne.algorithms import mmr_select

    engine = LocalMemoryEngine()
    hits = [_hit("evidence", str(i), 0.5 + i * 0.1, "lexical") for i in range(4)]
    for h in hits:
        h.text = f"unique text {h.id}"
    expected = engine._mmr("some query", list(hits), k=3)
    query_vec = engine._embed_text("some query")
    actual = mmr_select(
        list(hits), 3,
        query_vec=query_vec,
        embed_hit=lambda h: engine._embedding_for_hit(h, allow_fallback=True),
        mmr_lambda=engine.policy.mmr_lambda,
    )
    assert [h.id for h in actual] == [h.id for h in expected]

def test_mmr_select_base_score_dominates_and_ties_are_first_wins():
    from mnemosyne.algorithms import mmr_select

    a = _hit("evidence", "a", 5.0, "lexical")
    b = _hit("evidence", "b", 5.0, "lexical")  # identical score: 'a' must win (input order)
    picked = mmr_select([a, b], 1, query_vec=[0.0], embed_hit=lambda h: None, mmr_lambda=0.7)
    assert picked[0].id == "a"

def test_mmr_select_missing_vector_means_zero_relevance_no_penalty():
    from mnemosyne.algorithms import mmr_select

    strong = _hit("evidence", "strong", 1.0, "lexical")
    weak = _hit("evidence", "weak", 0.0, "lexical")
    picked = mmr_select([weak, strong], 2, query_vec=[1.0], embed_hit=lambda h: None, mmr_lambda=0.7)
    assert {h.id for h in picked} == {"weak", "strong"}
```

- [ ] **Step 2: Run — expect ImportError**

Run: `uv run --locked python -m pytest tests/test_algorithms.py -v -k mmr`

- [ ] **Step 3: Implement (verbatim structure from `engine.py:2771-2799`)**

```python
from mnemosyne.text import cosine

def mmr_select(
    hits: list[Hit],
    k: int,
    *,
    query_vec: list[float],
    embed_hit: Callable[[Hit], list[float] | None],
    mmr_lambda: float,
) -> list[Hit]:
    selected: list[Hit] = []
    remaining = list(hits)
    while remaining and len(selected) < k:
        best: Hit | None = None
        best_score = float("-inf")
        for hit in remaining:
            hit_vec = embed_hit(hit)
            relevance = cosine(query_vec, hit_vec) if hit_vec is not None else 0.0
            diversity_penalty = 0.0
            if selected and hit_vec is not None:
                selected_vectors = [
                    selected_vec
                    for item in selected
                    if (selected_vec := embed_hit(item)) is not None
                ]
                if selected_vectors:
                    diversity_penalty = max(cosine(hit_vec, selected_vec) for selected_vec in selected_vectors)
            score = mmr_lambda * relevance - (1.0 - mmr_lambda) * diversity_penalty
            score += hit.score
            if score > best_score:
                best = hit
                best_score = score
        if best is None:
            break
        selected.append(best)
        remaining.remove(best)
    return selected
```

- [ ] **Step 4: Run — expect PASS**, then delegate both engines. Local (`engine.py:2771`):

```python
    def _mmr(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        return mmr_select(
            hits, k,
            query_vec=self._embed_text(query),
            embed_hit=lambda hit: self._embedding_for_hit(hit, allow_fallback=True),
            mmr_lambda=self.policy.mmr_lambda,
        )
```

Postgres (`postgres_engine.py:4199`) — first read its body (`sed -n '4199,4220p' src/mnemosyne/postgres_engine.py`); it uses `hashing_embedding(hit.text)` for both query and hits. Delegate preserving exactly that sourcing:

```python
    def _mmr(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        return mmr_select(
            hits, k,
            query_vec=hashing_embedding(query),
            embed_hit=lambda hit: hashing_embedding(hit.text),
            mmr_lambda=self.policy.mmr_lambda,
        )
```

If the PG body deviates from this structure (e.g., no `+ hit.score`, different lambda source), STOP and preserve its exact behavior via parameters — the two engines' MMR are documented as behaviorally divergent and must stay so (spec §4.0).

- [ ] **Step 5: Full suite + parity subset** — `uv run --locked python -m pytest -q`; with DSN: `tests/test_parity_retrieval.py -q`. Zero new failures.

- [ ] **Step 6: Commit**

```bash
git add -u && git commit -m "refactor(algorithms): extract mmr_select, embedding sourcing parameterized per engine"
```

---

### Task 5: Gate-name stability test (Phase-0 exit criterion, spec §4.0)

**Files:**
- Test: `tests/test_backend_name_stability.py` (new)

**Interfaces:**
- Consumes: `RetrievalAdapters` defaults (`retrieval.py:1354-1355`), env-driven defaults (`retrieval.py:1401-1402`), `PostgresEngine` reported names (`postgres_engine.py:121-122`).

- [ ] **Step 1: Write the test (it must pass immediately — it is a tripwire for future tasks)**

```python
# tests/test_backend_name_stability.py
"""Tier-B gate-keyed backend identifiers must never drift (spec 4.0).

forbid_local classifies locality by NAME (denylist + 'local-' prefix), and
production profiles pin the postgres-* names. Renaming any of these breaks
retrieval-ops-check semantics and pending Tier-B evidence.
"""
from __future__ import annotations

import os
from unittest import mock

from mnemosyne.retrieval import RetrievalAdapters, retrieval_adapters_from_env

def test_local_default_backend_names_are_pinned():
    adapters = RetrievalAdapters()
    assert adapters.lexical_backend == "local-bm25-lite"
    assert adapters.graph_backend == "local-ppr"

def test_env_default_backend_names_are_pinned():
    with mock.patch.dict(os.environ, {}, clear=False):
        for var in ("MNEMOSYNE_LEXICAL_BACKEND", "MNEMOSYNE_GRAPH_BACKEND"):
            os.environ.pop(var, None)
        adapters = retrieval_adapters_from_env()
    assert adapters.lexical_backend == "postgres-fts"
    assert adapters.graph_backend == "postgres-recursive-ppr"
```

If `retrieval_adapters_from_env()` requires arguments (check its signature at `retrieval.py` near line 1390), pass the minimal defaults it documents; the two name assertions are the contract.

- [ ] **Step 2: Run — expect PASS immediately**

Run: `uv run --locked python -m pytest tests/test_backend_name_stability.py -v`
Expected: 2 PASS (this test guards Tasks 1–4 retroactively and all future phases).

- [ ] **Step 3: Commit**

```bash
git add tests/test_backend_name_stability.py
git commit -m "test(gates): pin gate-keyed backend names against extraction drift"
```

---

### Task 6: `ENGINE-CONTRACT.md`

**Files:**
- Create: `docs/ENGINE-CONTRACT.md`

- [ ] **Step 1: Write the document.** Copy spec §4.0's two-layer surface verbatim as the normative core, then add the mapping table. Structure (all sections required, no TBDs):

```markdown
# MemoryEngine Storage Contract

Normative surface for any Mnemosyne storage engine (spec 2026-07-01-native-acceleration-design.md §4.0).

## Layer 1 — storage primitives (engine MUST provide)
(a) append-only ledger writes with CID verification
(b) flat scans filtered by tenant/branch/valid-window returning the full §19
    meta-envelope (status, trust_tier, fidelity, confabulation-risk flag)
(c) plain-term lexical candidate retrieval (no operator grammar)
(d) vector top-k (exact, or ANN + exact re-rank)
(e) transactional projection rebuild + per-projection watermarks
(f) embedding_partition split and never-embed rules
(g) branch create/discard and branch-scoped visibility
(h) as-of (bitemporal) reads
(i) cached graph-signal read (graph_ppr(use_cache=True) shape)
(j) durable queue lease surface

## Layer 2 — app-side compositions (engine MUST NOT reimplement)
retrieval pipeline, PPR computation (mnemosyne.algorithms.ppr_power_iteration),
merge semantics (shipped replay-upsert), RRF/MMR/U-curve/budget
(mnemosyne.algorithms), activation scoring, calibration.

## Naming rules
Engine-specific channel names are forbidden in this contract but each engine's
externally REPORTED backend identifiers are pinned verbatim
(tests/test_backend_name_stability.py): postgres-fts, postgres-recursive-ppr,
local-bm25-lite, local-ppr.

## Conformance
An engine is conformant when tests/test_shared_engine_contract.py passes with
its fixture param and the parity suites (test_parity_*) pass against the
LocalMemoryEngine oracle.

## Current implementation mapping
| Capability | LocalMemoryEngine | PostgresEngine |
|---|---|---|
| (a) ledger | engine.append_evidence | postgres_engine (evidence table) |
| (g) branch | engine.branch/discard | postgres_engine.branch (row copies) |
| (h) as-of | engine.as_of | postgres_engine as-of SQL |
| (i) cached graph | retrieval.GraphSignalCache | graph_ppr_cache table |
| (j) queue | queue.py (memory) | PostgresQueue (leases) |
```

Fill the mapping table by grepping the named symbols (`grep -n 'def branch\|def as_of\|def append_evidence' src/mnemosyne/engine.py src/mnemosyne/postgres_engine.py`) and correcting any cell that doesn't match reality — the table must cite real symbols.

- [ ] **Step 2: Commit**

```bash
git add docs/ENGINE-CONTRACT.md
git commit -m "docs(contract): normative two-layer MemoryEngine storage contract"
```

---

### Task 7: Parity-fixture isinstance triage

**Files:**
- Modify: `tests/test_shared_engine_contract.py:45, 88-92, 213, 2020, 2084, 2126`

**Interfaces:**
- Produces: `engine_bundle` fixture yielding `(engine, tenant, user)` plus a companion `engine_capabilities(engine) -> frozenset[str]` helper — Phase 2 adds `"sqlite"` as one fixture param + one capabilities entry, zero test rewrites.

- [ ] **Step 1: Audit.** Run `grep -n 'isinstance(engine' tests/test_shared_engine_contract.py`. For each hit classify: (A) engine-specific SETUP (e.g., Postgres schema reset) or (B) engine-specific CAPABILITY gate (test only applies to one engine).

- [ ] **Step 2: Add the capabilities helper at module top (after the fixture at :213):**

```python
def engine_capabilities(engine: Any) -> frozenset[str]:
    """Contract-level capability flags replacing isinstance() branching.

    A new engine adds its flags here and to the engine_bundle fixture params —
    tests must key on capabilities, never on concrete engine types.
    """
    if isinstance(engine, PostgresEngine):
        return frozenset({"sql_fts", "graph_ppr_cache_table", "rls", "live_db"})
    return frozenset({"in_memory"})
```

- [ ] **Step 3: Convert each class-(B) branch** from `if not isinstance(engine, PostgresEngine): pytest.skip(...)` to `if "live_db" not in engine_capabilities(engine): pytest.skip(...)` (match the specific capability each test actually needs). Leave class-(A) setup branches inside the fixture only — the fixture is the single place `isinstance` remains legal.

- [ ] **Step 4: Run the suite** — `uv run --locked python -m pytest tests/test_shared_engine_contract.py -q` (and with DSN if available). Same pass/skip counts as before.

- [ ] **Step 5: Commit**

```bash
git add tests/test_shared_engine_contract.py
git commit -m "test(contract): replace isinstance engine branching with capability flags"
```

---

### Task 8: CID journal (`journal.py`)

**Files:**
- Create: `src/mnemosyne/journal.py`
- Modify: `src/mnemosyne/engine.py` (wire into `append_evidence`; locate with `grep -n 'def append_evidence' src/mnemosyne/engine.py`)
- Test: `tests/test_journal.py` (new)

**Interfaces:**
- Produces:
  - `CIDJournal(path: Path)` with `append(record: dict[str, Any]) -> None` (canonical-JSON line + fsync), `records() -> Iterator[dict[str, Any]]`, `tombstone(cid: str, *, salted_hash: str, erased_at: str) -> None` (rewrite-and-swap, `tombstone_recompute` mode), `purge(cid: str) -> None` (full exclusion, `hard_delete_legal` mode), `verify_against(ledger_cids: set[str]) -> JournalDivergence`.
  - `JournalDivergence` dataclass: `missing_from_journal: list[str]`, `journal_only: list[str]` (journal-only = alarm condition, spec §4.0).
- Canonical JSON = `json.dumps(record, sort_keys=True, separators=(",", ":"))` — matches the ledger's Python-owned canonicalization; CIDs are NEVER computed here.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_journal.py
from __future__ import annotations

import json
from pathlib import Path

from mnemosyne.journal import CIDJournal

def _rec(cid: str) -> dict:
    return {"cid": cid, "tenant_id": "t-a", "content": f"payload-{cid}", "kind": "evidence"}

def test_append_writes_canonical_json_lines(tmp_path: Path):
    j = CIDJournal(tmp_path / "t-a.journal")
    j.append(_rec("cid-1"))
    j.append(_rec("cid-2"))
    lines = (tmp_path / "t-a.journal").read_text().splitlines()
    assert [json.loads(l)["cid"] for l in lines] == ["cid-1", "cid-2"]
    assert lines[0] == json.dumps(_rec("cid-1"), sort_keys=True, separators=(",", ":"))

def test_tombstone_preserves_line_with_marker_not_content(tmp_path: Path):
    j = CIDJournal(tmp_path / "t.journal")
    j.append(_rec("cid-1")); j.append(_rec("cid-2"))
    j.tombstone("cid-1", salted_hash="abc123", erased_at="2026-07-01T00:00:00Z")
    recs = list(j.records())
    assert len(recs) == 2
    tomb = next(r for r in recs if r["cid"] == "cid-1")
    assert tomb["erased"] is True and tomb["salted_hash"] == "abc123"
    assert "content" not in tomb

def test_purge_removes_line_entirely(tmp_path: Path):
    j = CIDJournal(tmp_path / "t.journal")
    j.append(_rec("cid-1")); j.append(_rec("cid-2"))
    j.purge("cid-1")
    assert [r["cid"] for r in j.records()] == ["cid-2"]

def test_verify_against_reports_both_divergence_directions(tmp_path: Path):
    j = CIDJournal(tmp_path / "t.journal")
    j.append(_rec("cid-1"))
    d = j.verify_against({"cid-1", "cid-2"})
    assert d.missing_from_journal == ["cid-2"] and d.journal_only == []
    d2 = j.verify_against(set())
    assert d2.journal_only == ["cid-1"]

def test_local_engine_appends_to_journal_when_configured(tmp_path: Path):
    from mnemosyne.engine import LocalMemoryEngine

    engine = LocalMemoryEngine(journal_dir=tmp_path)
    # Use the engine's existing capture/append path exactly as other tests do:
    # copy the canonical add-evidence call from tests/test_engine_contract.py
    # (grep 'append_evidence' there for the minimal invocation) with tenant 't-a'.
    cid = engine.append_evidence_for_test(tenant_id="t-a")  # see step 4 note
    journal = CIDJournal(tmp_path / "t-a.journal")
    assert cid in {r["cid"] for r in journal.records()}
```

- [ ] **Step 2: Run — expect `ModuleNotFoundError: mnemosyne.journal`**

Run: `uv run --locked python -m pytest tests/test_journal.py -v`

- [ ] **Step 3: Implement `src/mnemosyne/journal.py`**

```python
"""Per-tenant append-only CID journal (spec §4.0).

Dual-durability copy of the evidence ledger: engine commit happens FIRST,
journal append SECOND; on divergence the engine ledger is authoritative and
journal segments are re-derived, while journal-only CIDs are an alarm.
Erasure is mode-aware: tombstone_recompute keeps a tombstone line (salted
hash + timestamps), hard_delete_legal removes the line entirely.
Stdlib only. CIDs are never computed here.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))

@dataclass
class JournalDivergence:
    missing_from_journal: list[str] = field(default_factory=list)
    journal_only: list[str] = field(default_factory=list)

    @property
    def diverged(self) -> bool:
        return bool(self.missing_from_journal or self.journal_only)

class CIDJournal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        if "cid" not in record:
            raise ValueError("journal records must carry a cid")
        line = _canonical(record) + "\n"
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    def records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def _rewrite(self, transform) -> None:
        """Atomic rewrite-and-swap: write tmp, fsync, rename over original."""
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for record in self.records():
                out = transform(record)
                if out is not None:
                    fh.write(_canonical(out) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def tombstone(self, cid: str, *, salted_hash: str, erased_at: str) -> None:
        def transform(record: dict[str, Any]) -> dict[str, Any] | None:
            if record.get("cid") != cid:
                return record
            return {
                "cid": cid,
                "erased": True,
                "salted_hash": salted_hash,
                "erased_at": erased_at,
                "tenant_id": record.get("tenant_id"),
                "kind": record.get("kind"),
            }
        self._rewrite(transform)

    def purge(self, cid: str) -> None:
        self._rewrite(lambda r: None if r.get("cid") == cid else r)

    def verify_against(self, ledger_cids: set[str]) -> JournalDivergence:
        journal_cids = {r["cid"] for r in self.records()}
        return JournalDivergence(
            missing_from_journal=sorted(ledger_cids - journal_cids),
            journal_only=sorted(journal_cids - ledger_cids),
        )
```

- [ ] **Step 4: Wire into `LocalMemoryEngine`.** Add an optional `journal_dir: Path | None = None` keyword to `LocalMemoryEngine.__init__` (default `None` = journaling off, preserving all existing behavior). In `append_evidence`, AFTER the evidence row is committed to the in-memory store and `_persist()` has run, and only when `journal_dir` is set:

```python
        if self._journal_dir is not None:
            CIDJournal(self._journal_dir / f"{evidence.tenant_id}.journal").append(
                {"cid": evidence.cid, "tenant_id": evidence.tenant_id,
                 "kind": "evidence", "content": evidence.content,
                 "created_at": evidence.created_at.isoformat()}
            )
```

Match the actual `Evidence` field names (grep `class Evidence` in `src/mnemosyne/models.py`); adjust `content`/`created_at` accessors accordingly. For the test's `append_evidence_for_test` placeholder in Step 1: replace it with the repo's real minimal append call — copy the shortest `append_evidence(...)` invocation from `tests/test_engine_contract.py` verbatim and use its returned CID. The test must exercise the PUBLIC path, not a helper.

- [ ] **Step 5: Run — all journal tests PASS; full suite zero new failures.**

- [ ] **Step 6: Commit**

```bash
git add src/mnemosyne/journal.py src/mnemosyne/engine.py tests/test_journal.py
git commit -m "feat(journal): per-tenant CID journal with mode-aware erasure and divergence check"
```

---

### Task 9: Projection registry (`projections.py`)

**Files:**
- Create: `src/mnemosyne/projections.py`
- Test: `tests/test_projections.py` (new)

**Interfaces:**
- Produces:
  - `ProjectionSpec(name: str, version: int, fingerprint: Callable[[], str], rebuild: Callable[[], None])`
  - `ProjectionRegistry` with `register(spec: ProjectionSpec) -> None`, `check(name: str) -> bool` (True = fingerprint matches stored), `ensure(name: str) -> bool` (rebuild-on-mismatch; returns True if a rebuild ran), `status() -> dict[str, dict]`.
  - Fingerprints persist in a sidecar JSON (`<state_dir>/projections.json`).
- Phase 2 registers FTS/vector/cached-PPR projections against this exact API.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_projections.py
from __future__ import annotations

from pathlib import Path

from mnemosyne.projections import ProjectionRegistry, ProjectionSpec

def test_ensure_rebuilds_on_fingerprint_mismatch(tmp_path: Path):
    calls: list[str] = []
    state = {"fp": "v1"}
    reg = ProjectionRegistry(tmp_path)
    reg.register(ProjectionSpec(
        name="demo", version=1,
        fingerprint=lambda: state["fp"],
        rebuild=lambda: calls.append("rebuilt"),
    ))
    assert reg.ensure("demo") is True and calls == ["rebuilt"]   # first run: no stored fp
    assert reg.ensure("demo") is False and calls == ["rebuilt"]  # stable: no rebuild
    state["fp"] = "v2"
    assert reg.ensure("demo") is True and calls == ["rebuilt", "rebuilt"]

def test_version_bump_forces_rebuild(tmp_path: Path):
    calls: list[str] = []
    reg = ProjectionRegistry(tmp_path)
    spec = ProjectionSpec(name="demo", version=1, fingerprint=lambda: "same", rebuild=lambda: calls.append("r"))
    reg.register(spec)
    reg.ensure("demo")
    reg2 = ProjectionRegistry(tmp_path)
    reg2.register(ProjectionSpec(name="demo", version=2, fingerprint=lambda: "same", rebuild=lambda: calls.append("r")))
    assert reg2.ensure("demo") is True and len(calls) == 2

def test_status_reports_all_registered(tmp_path: Path):
    reg = ProjectionRegistry(tmp_path)
    reg.register(ProjectionSpec(name="a", version=1, fingerprint=lambda: "x", rebuild=lambda: None))
    assert set(reg.status()) == {"a"}
    assert reg.status()["a"]["version"] == 1
```

- [ ] **Step 2: Run — expect ModuleNotFoundError.**

- [ ] **Step 3: Implement**

```python
# src/mnemosyne/projections.py
"""Registry of named, versioned, fingerprinted rebuildable projections (spec §4.0).

Every derived index is disposable by construction: a fingerprint mismatch or
version bump triggers rebuild from the ledger. ANN/quantized tiers plug in
here in later phases. Stdlib only.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class ProjectionSpec:
    name: str
    version: int
    fingerprint: Callable[[], str]
    rebuild: Callable[[], None]

class ProjectionRegistry:
    def __init__(self, state_dir: Path) -> None:
        self._state_path = Path(state_dir) / "projections.json"
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._specs: dict[str, ProjectionSpec] = {}

    def _load(self) -> dict[str, Any]:
        if self._state_path.exists():
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        return {}

    def _save(self, state: dict[str, Any]) -> None:
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, sort_keys=True, indent=2), encoding="utf-8")
        tmp.replace(self._state_path)

    def register(self, spec: ProjectionSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"projection already registered: {spec.name}")
        self._specs[spec.name] = spec

    def check(self, name: str) -> bool:
        spec = self._specs[name]
        stored = self._load().get(name)
        return bool(stored) and stored["version"] == spec.version and stored["fingerprint"] == spec.fingerprint()

    def ensure(self, name: str) -> bool:
        spec = self._specs[name]
        if self.check(name):
            return False
        spec.rebuild()
        state = self._load()
        state[name] = {"version": spec.version, "fingerprint": spec.fingerprint()}
        self._save(state)
        return True

    def status(self) -> dict[str, dict[str, Any]]:
        stored = self._load()
        return {
            name: {"version": spec.version, "fresh": self.check(name), "stored": stored.get(name)}
            for name, spec in self._specs.items()
        }
```

- [ ] **Step 4: Run — PASS. Full suite — zero new failures.**

- [ ] **Step 5: Commit**

```bash
git add src/mnemosyne/projections.py tests/test_projections.py
git commit -m "feat(projections): versioned fingerprinted rebuild-on-mismatch registry"
```

---

### Task 10: A6 benchmark harness (Python side)

**Files:**
- Modify: `pyproject.toml` (dev group)
- Create: `tests/benchmarks/__init__.py` (empty), `tests/benchmarks/test_retrieval_baselines.py`
- Create: `tests/benchmarks/baselines.json` (generated in Step 4)

**Interfaces:**
- Consumes: `mnemosyne.algorithms` functions (Tasks 1–4), `mnemosyne.text` kernels.
- Produces: baseline capture + relative-regression gate. CI mode gates RELATIVE regression only (>1.5× baseline fails); the absolute §22.5 300–400 ms budget is asserted only when `MNEMOSYNE_BENCH_ABSOLUTE=1` (reference-Mac nightly), per spec §4.6.

- [ ] **Step 1: Add dev deps**

In `pyproject.toml` `[dependency-groups]`:

```toml
dev = [
  "pytest==9.1.1",
  "ruff==0.15.20",
  "hypothesis>=6.100",
  "pytest-benchmark>=5.1",
]
```

Run: `uv sync --locked --extra mcp --group dev` (regenerates `uv.lock`; commit it).

- [ ] **Step 2: Write the benchmark suite**

```python
# tests/benchmarks/test_retrieval_baselines.py
"""A6 harness: kernel + fast-path baselines with relative-regression gating.

CI gates RELATIVE regression vs baselines.json (shared runners are noisy);
absolute §22.5 budgets run only under MNEMOSYNE_BENCH_ABSOLUTE=1 (nightly,
reference Mac). Spec §4.6.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.text import cosine, hashing_embedding, lexical_score

BASELINES = Path(__file__).parent / "baselines.json"
RELATIVE_CEILING = 1.5  # fail if >1.5x recorded baseline
random.seed(20260701)

_WORDS = ["postgres", "memory", "belief", "evidence", "tenant", "branch", "vector", "graph"]

def _text(n: int) -> str:
    return " ".join(random.choice(_WORDS) + str(random.randint(0, 500)) for _ in range(n))

DOCS = [_text(80) for _ in range(2000)]
QUERY = _text(12)

def _gate(name: str, seconds: float) -> None:
    if not BASELINES.exists():
        pytest.skip("baselines.json not captured yet (run scripts step in plan Task 10 Step 4)")
    baseline = json.loads(BASELINES.read_text())[name]
    assert seconds <= baseline * RELATIVE_CEILING, (
        f"{name}: {seconds:.4f}s exceeds {RELATIVE_CEILING}x baseline {baseline:.4f}s"
    )

def test_bench_cosine_1024(benchmark):
    a = [random.random() for _ in range(1024)]
    b = [random.random() for _ in range(1024)]
    benchmark(cosine, a, b)
    _gate("cosine_1024", benchmark.stats.stats.mean)

def test_bench_hashing_embedding_cold(benchmark):
    docs = iter(DOCS * 50)
    benchmark(lambda: hashing_embedding(next(docs) + " salt"))
    _gate("hashing_embedding", benchmark.stats.stats.mean)

def test_bench_lexical_scan_2k(benchmark):
    benchmark(lambda: [lexical_score(QUERY, d) for d in DOCS])
    _gate("lexical_scan_2k", benchmark.stats.stats.mean)

def test_fast_path_retrieve_absolute_budget():
    if os.environ.get("MNEMOSYNE_BENCH_ABSOLUTE") != "1":
        pytest.skip("absolute §22.5 budget runs on the reference machine only")
    import time
    engine = LocalMemoryEngine()
    # Seed 1000 items through the public capture path — copy the minimal
    # capture invocation from tests/test_engine_contract.py verbatim.
    for i in range(1000):
        _seed_one(engine, f"doc {i}: " + _text(30))  # helper defined next to this test
    start = time.perf_counter()
    for _ in range(20):
        engine.retrieve(QUERY, tenant_id="bench-tenant")
    p_mean_ms = (time.perf_counter() - start) / 20 * 1000
    assert p_mean_ms <= 400, f"fast path {p_mean_ms:.0f} ms exceeds §22.5 budget"
```

Implement `_seed_one` by copying the repo's canonical capture call (grep `def test_.*capture` in `tests/test_engine_contract.py` for the minimal form) — the benchmark must use the public write path.

- [ ] **Step 3: Run benchmarks (capture mode)**

Run: `uv run --locked python -m pytest tests/benchmarks -v --benchmark-only`
Expected: benchmark tests run; `_gate` calls SKIP (no baselines.json yet).

- [ ] **Step 4: Capture baselines**

```bash
uv run --locked python - <<'EOF'
import json, subprocess, tempfile, pathlib
out = pathlib.Path("tests/benchmarks/baselines.json")
tmp = tempfile.mktemp(suffix=".json")
subprocess.run(["uv", "run", "--locked", "python", "-m", "pytest", "tests/benchmarks",
                "--benchmark-only", f"--benchmark-json={tmp}"], check=True)
data = json.loads(pathlib.Path(tmp).read_text())
names = {"test_bench_cosine_1024": "cosine_1024",
         "test_bench_hashing_embedding_cold": "hashing_embedding",
         "test_bench_lexical_scan_2k": "lexical_scan_2k"}
out.write_text(json.dumps({names[b["name"].split("[")[0]]: b["stats"]["mean"]
                           for b in data["benchmarks"] if b["name"].split("[")[0] in names},
                          indent=2, sort_keys=True))
print(out.read_text())
EOF
```

Then re-run Step 3's command: `_gate` assertions now execute and PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/benchmarks/
git commit -m "feat(bench): A6 harness — baseline capture + relative-regression gate, absolute budget behind MNEMOSYNE_BENCH_ABSOLUTE"
```

---

### Task 11: Property tests + lane invariants (hypothesis)

**Files:**
- Create: `tests/test_journal_properties.py`

**Interfaces:**
- Consumes: `CIDJournal`, `JournalDivergence` (Task 8), `LocalMemoryEngine(journal_dir=...)`.

- [ ] **Step 1: Write the property tests**

```python
# tests/test_journal_properties.py
"""Hypothesis property tests for the Phase-0 storage invariants (spec §4.0):
append-only-ness and rebuild determinism, plus cheap lane-invariant predicates.
Chaos/DST fault injection arrives in Phase 2 with SqliteEngine (spec §8)."""
from __future__ import annotations

import json
from pathlib import Path

from hypothesis import given, settings, strategies as st

from mnemosyne.journal import CIDJournal

cids = st.lists(st.uuids().map(str), min_size=1, max_size=30, unique=True)

@given(cids)
@settings(max_examples=50, deadline=None)
def test_append_only_prefix_property(tmp_path_factory=None, cid_list=None):
    # hypothesis+fixtures don't mix; build our own tmp dir per example
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        j = CIDJournal(Path(d) / "t.journal")
        seen: list[str] = []
        for cid in cid_list:
            j.append({"cid": cid, "tenant_id": "t", "kind": "evidence", "content": cid})
            current = [r["cid"] for r in j.records()]
            assert current[: len(seen)] == seen, "existing prefix mutated by append"
            seen = current

@given(cids)
@settings(max_examples=50, deadline=None)
def test_rebuild_determinism_same_records_same_bytes(cid_list):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        j1 = CIDJournal(Path(d) / "a.journal")
        j2 = CIDJournal(Path(d) / "b.journal")
        for cid in cid_list:
            record = {"cid": cid, "tenant_id": "t", "kind": "evidence", "content": cid}
            j1.append(dict(record))
            j2.append(dict(record))
        assert (Path(d) / "a.journal").read_bytes() == (Path(d) / "b.journal").read_bytes()

@given(cids, st.integers(min_value=0, max_value=29))
@settings(max_examples=50, deadline=None)
def test_tombstone_never_loses_non_target_records(cid_list, idx):
    import tempfile
    target = cid_list[idx % len(cid_list)]
    with tempfile.TemporaryDirectory() as d:
        j = CIDJournal(Path(d) / "t.journal")
        for cid in cid_list:
            j.append({"cid": cid, "tenant_id": "t", "kind": "evidence", "content": cid})
        j.tombstone(target, salted_hash="h", erased_at="2026-07-01T00:00:00Z")
        recs = {r["cid"]: r for r in j.records()}
        assert set(recs) == set(cid_list)                      # nothing lost
        assert recs[target].get("erased") is True              # target tombstoned
        assert "content" not in recs[target]                   # content shredded
        for cid in cid_list:
            if cid != target:
                assert recs[cid]["content"] == cid             # others untouched
```

Fix the first test's signature if hypothesis rejects the default-arg pattern: use only `cid_list` as parameter (`def test_append_only_prefix_property(cid_list):`).

- [ ] **Step 2: Run** — `uv run --locked python -m pytest tests/test_journal_properties.py -v` → all PASS (hypothesis will shrink and expose bugs in Task 8 if any; fix them there before proceeding).

- [ ] **Step 3: Commit**

```bash
git add tests/test_journal_properties.py
git commit -m "test(journal): hypothesis properties — append-only prefix, rebuild determinism, tombstone safety"
```

---

### Task 12: Honeytokens

**Files:**
- Create: `src/mnemosyne/honeytokens.py`
- Test: `tests/test_honeytokens.py` (new)

**Interfaces:**
- Produces: `HONEYTOKEN_PREFIX = "HTKN"`; `honeytoken(cls: str, tenant_id: str) -> str` (deterministic per (class, tenant): `HTKN-{cls}-{sha256(cls+tenant)[:16]}`); `scan_for_foreign_honeytokens(text: str, *, own_tenant_id: str) -> list[str]` returning any honeytoken markers whose tenant-hash does not match `own_tenant_id`. Phase 2/3/4 reuse this to assert cache/log/sidecar boundaries.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_honeytokens.py
from __future__ import annotations

from pathlib import Path

from mnemosyne.honeytokens import honeytoken, scan_for_foreign_honeytokens

def test_honeytoken_is_deterministic_and_class_tagged():
    t1 = honeytoken("S3", "tenant-a")
    assert t1 == honeytoken("S3", "tenant-a")
    assert t1.startswith("HTKN-S3-")
    assert honeytoken("S3", "tenant-b") != t1

def test_scan_flags_only_foreign_tokens():
    own = honeytoken("S3", "tenant-a")
    foreign = honeytoken("S3", "tenant-b")
    text = f"log line with {own} and {foreign}"
    hits = scan_for_foreign_honeytokens(text, own_tenant_id="tenant-a")
    assert hits == [foreign]

def test_cross_tenant_journal_isolation(tmp_path: Path):
    """Spec §4.0: tenant A's journal never contains tenant B's honeytokens."""
    from mnemosyne.engine import LocalMemoryEngine
    from mnemosyne.journal import CIDJournal

    engine = LocalMemoryEngine(journal_dir=tmp_path)
    _seed_with_content(engine, "tenant-a", f"note {honeytoken('S3', 'tenant-a')}")
    _seed_with_content(engine, "tenant-b", f"note {honeytoken('S3', 'tenant-b')}")
    a_text = (tmp_path / "tenant-a.journal").read_text()
    assert scan_for_foreign_honeytokens(a_text, own_tenant_id="tenant-a") == []
```

Implement `_seed_with_content` the same way as Task 8 Step 4 (the repo's real public capture call with an explicit `content=` argument).

- [ ] **Step 2: Run — expect ModuleNotFoundError.**

- [ ] **Step 3: Implement**

```python
# src/mnemosyne/honeytokens.py
"""Leak-canary honeytokens (privacy policy §10; spec §4.0).

Deterministic per (sensitivity class, tenant) marker strings seeded into
memories; their appearance beyond their boundary (another tenant's journal,
a non-embeddable cache, provider/front-end logs, benchmark artifacts) is a
leak alarm. Stdlib only.
"""
from __future__ import annotations

import hashlib
import re

HONEYTOKEN_PREFIX = "HTKN"
_TOKEN_RE = re.compile(r"HTKN-(S[0-4])-([0-9a-f]{16})")

def _tenant_hash(cls: str, tenant_id: str) -> str:
    return hashlib.sha256(f"{cls}:{tenant_id}".encode()).hexdigest()[:16]

def honeytoken(cls: str, tenant_id: str) -> str:
    if not re.fullmatch(r"S[0-4]", cls):
        raise ValueError(f"unknown sensitivity class: {cls}")
    return f"{HONEYTOKEN_PREFIX}-{cls}-{_tenant_hash(cls, tenant_id)}"

def scan_for_foreign_honeytokens(text: str, *, own_tenant_id: str) -> list[str]:
    own_hashes = {_tenant_hash(f"S{i}", own_tenant_id) for i in range(5)}
    return [m.group(0) for m in _TOKEN_RE.finditer(text) if m.group(2) not in own_hashes]
```

- [ ] **Step 4: Run — PASS. Add a benchmark-artifact guard:** append to `tests/test_honeytokens.py`:

```python
def test_benchmark_artifacts_contain_no_honeytokens():
    baselines = Path("tests/benchmarks/baselines.json")
    if baselines.exists():
        assert "HTKN-" not in baselines.read_text()
```

- [ ] **Step 5: Full suite, then commit**

```bash
git add src/mnemosyne/honeytokens.py tests/test_honeytokens.py
git commit -m "feat(honeytokens): per-class leak canaries + cross-tenant journal isolation test"
```

---

### Task 13: Phase-0 exit verification + docs

**Files:**
- Modify: `docs/superpowers/plans/2026-07-01-native-acceleration-program.md` (mark Phase 0 done)
- Modify: `CONFIG-DRIFT-CHECKS.md` — add `MNEMOSYNE_BENCH_ABSOLUTE` and `journal_dir` under "Configuration sources" (one line each, same table format as existing entries)

- [ ] **Step 1: Run the complete Phase-0 exit checklist**

```bash
uv run --locked python -m pytest -q                                   # full suite green
uv run --locked python -m pytest tests/test_backend_name_stability.py tests/test_algorithms.py tests/test_journal.py tests/test_projections.py tests/test_journal_properties.py tests/test_honeytokens.py -q
uv run --locked python -m pytest tests/benchmarks --benchmark-only -q  # gates pass vs baselines
uv run --locked ruff check .                                           # clean
```

Expected: all green. With `MNEMOSYNE_POSTGRES_DSN` set, additionally: `uv run --locked python -m pytest tests/test_parity_retrieval.py tests/test_shared_engine_contract.py -q`.

- [ ] **Step 2: Update the two docs, commit**

```bash
git add -u
git commit -m "docs(phase0): mark seam-hardening complete; register new config sources"
```

---

## Self-Review (performed at authoring time)

1. **Spec coverage (§4.0 + §4.6 Phase-0 exits):** rescoped extraction → Tasks 1–4; gate-name stability → Task 5; ENGINE-CONTRACT.md → Task 6; fixture parametrization/isinstance triage → Task 7; CID journal + authority rule → Task 8; projection registry → Task 9; A6 harness (tiered gating) → Task 10; hypothesis property tests + protected-ratchet foundation → Task 11; honeytokens → Task 12. DST/chaos + TLA+ correctly deferred to Phase 2 per spec §4.0. Journal at-rest/KMS posture is a Phase-2/ADR item (spec §4.0) — intentionally absent here.
2. **Placeholder scan:** two intentional indirections remain — `_seed_one`/`_seed_with_content` and the `Hit(...)` constructor — each carries an exact instruction to copy the repo's canonical invocation from a named test file rather than inventing call shapes; this is deliberate (the plan must not fabricate signatures it hasn't verified).
3. **Type consistency:** `rrf_fuse`/`u_curve_order`/`fit_budget`/`ppr_power_iteration`/`mmr_select` signatures are identical across task Interfaces blocks, ENGINE-CONTRACT.md Layer-2 references, and delegation call sites. `CIDJournal.append/tombstone/purge/verify_against` names match between Tasks 8, 11, and 12.

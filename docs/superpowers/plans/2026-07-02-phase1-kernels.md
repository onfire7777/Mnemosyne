# Phase 1: Native Kernels + Lazy Imports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `mnemosyne-native` — a PyO3 kernel crate with byte-parity implementations of the hot retrieval kernels (30–100× measured speedup target, ≥10× exit bar on scan benches — dense end-to-end 10× re-homed to Phase-2's packed-BLOB seam (measured vs honest MNEMOSYNE_PURE=1 baselines: list-FFI seam 4.6×, kernel prepacked ~82×, lexical ~40×)) — plus A4 lazy imports (CLI ≤100 ms), with the pure-Python path remaining a first-class automatic fallback proven identical by the parity suite under both modes.

**Architecture:** Sibling crate `rust/mnemosyne-native/` producing importable module `mnemosyne_native`, wired as an **optional path dependency** (`[project.optional-dependencies] native` + `[tool.uv.sources]`) so the main package's build backend (setuptools) and runtime dependency set are untouched — a deliberate, documented deviation from the spec's mixed-layout sketch (§4.1) in favor of zero risk to the SLO-proven packaging; runtime dispatch is `try: import mnemosyne_native` in `text.py`/`algorithms.py` exactly as the spec requires. Kernels are scalar strict-IEEE per item (bit-identical to CPython), rayon-parallel **across** items only. No quantized tier in this phase (spec allows it as a later approximate tier).

**Tech Stack:** Rust 1.95 (installed), PyO3 0.29 abi3-py312, maturin 1.14 (via uv build of the path dep), crates: `blake2` 0.10, `regex`, `rayon`. Python 3.12.13, uv 0.11.16.

## Global Constraints

- Main package runtime deps stay exactly `["cryptography>=42"]`; `mnemosyne-native` appears ONLY under a new `native` optional extra. `uv sync --locked --extra mcp --extra postgres --group dev` (no `native`) must keep working on a machine with no Rust toolchain.
- **Byte-parity:** every kernel result is bit-identical to the pure path (`struct.pack('<d', x)` equality). Kernel crate bans `mul_add` and transcendentals; allowed float ops: `+ - * / sqrt abs` (enforced by a grep lint test). Scalar sequential per-item loops; rayon across items only; results aligned to input order; ties first-wins by input index.
- **Phase-0 handoffs (binding):** PPR is NOT a Phase-1 kernel (deep-mode only). `rrf_fuse`'s `annotate_channel_scores` flag and `ppr_power_iteration`'s literal `teleport=0.15` are NOT touched. `fit_budget` stays Python (its `approx_tokens` binding is its cost model — no kernel). Bench comparisons use the salt-cold hashing semantics from `tests/benchmarks/test_retrieval_baselines.py`.
- **Zero behavior change:** full suite green in BOTH modes: default (native active once installed) and `MNEMOSYNE_PURE=1`. Suite baseline on main: 1306 passed / 116 skipped (with postgres extra installed; 35 of the skips are DSN-gated).
- Gate-name strings and do-not-touch surfaces (gates/rails, sql/schema.sql, infra/, CID computation, mcp_tools.py) unchanged. CID canonicalization stays Python-owned.
- Test invocation: `uv run --locked python -m pytest <path>` (addopts already has `-q`; never add another `-q`; never edit source while a suite runs — inspect.getsource tests).
- Commits: `type(scope): summary`, one per task minimum. Work from `/Users/admin/Mnemosyne` on branch `phase1/native-kernels`.

## Python-semantics parity notes (read before writing any Rust)

1. `text.py:68` `cosine(a, b)` = `sum(x*y for x, y in zip(a, b, strict=False))` — **CORRECTED 2026-07-02 (Task 4 finding):** CPython ≥3.12's builtin `sum()` over floats is **Neumaier compensated summation** (gh-100425), NOT naive sequential accumulation; a naive Rust loop diverges by 1 ulp (~8/300 hypothesis examples). The kernel ports CPython's compensated float fast path exactly (`dense.rs::cosine_seq`) — never "simplify" it to a plain loop. **Silent truncation** to the shorter input still applies. (Hashing's norm is exempt: integer-valued partials ≤2^53 ⇒ compensation ≡ 0.0 — do not "fix" it to compensated.)
2. `text.py:31` `lexical_score` iterates `q.items()` — **Python dict insertion order = first-occurrence order of query tokens**. Float accumulation order depends on it. The Rust side must iterate query terms in first-occurrence order (use an order-preserving map or a Vec of (term, count)).
3. `text.py:15` `tokenize`: regex `[A-Za-z0-9_][A-Za-z0-9_:+./-]*` (ASCII-only classes — Rust `regex` matches identically), then `.lower()` (ASCII-safe here), then `.strip("./:+-")` (strip from BOTH ends, all chars in that set), drop empties.
4. `text.py:46` `_hashing_embedding_cached`: per token → `blake2b(token, digest_size=8)` (digest size is IN THE PARAMETER BLOCK — use `Blake2bVar::new(8)` or `blake2::Blake2bVar`), bucket = first 4 digest bytes big-endian % dims, sign = +1.0 if `digest[4] % 2 == 0` else −1.0, `vec[bucket] += sign` in token order; norm = `sqrt(sum(x*x))` sequential over the vec; if norm == 0.0 return unnormalized; else divide each element. All f64.
5. `algorithms.py` `mmr_select`: objective = `mmr_lambda * relevance - (1.0 - mmr_lambda) * diversity_penalty` then `score += hit.score` (two statements — keep the exact expression shapes); missing vector ⇒ relevance 0.0 AND no diversity penalty; strict `>` argmax ⇒ first-wins on input order; `relevance`/`penalty` use `cosine` semantics incl. truncation.
6. Python float `==` is bitwise-safe for comparing results EXCEPT NaN and ±0.0 distinctions — bit-equality tests must compare `struct.pack('<d', x)` bytes.

---

### Task 1: Crate scaffold + optional-extra packaging

**Files:**
- Create: `rust/mnemosyne-native/Cargo.toml`, `rust/mnemosyne-native/pyproject.toml`, `rust/mnemosyne-native/src/lib.rs` (skeleton), `rust/mnemosyne-native/.gitignore` (`/target`)
- Modify: `pyproject.toml` (root: `native` extra + `[tool.uv.sources]`)
- Test: `tests/test_native_packaging.py` (new)

**Interfaces:**
- Produces: importable module `mnemosyne_native` with `__version__: str` and `parity_marker() -> str` returning `"strict-ieee-scalar-v1"`. Later tasks add kernels to this module.
- Produces: `uv sync --locked --extra mcp --extra postgres --extra native --group dev` builds and installs the crate; without `--extra native` nothing Rust-related happens.

- [ ] **Step 1: Write the failing packaging test**

```python
# tests/test_native_packaging.py
"""Native kernel crate packaging contract (spec §4.1; Phase-1 plan Task 1).

The native module is an OPTIONAL accelerator: absent => pure Python runs
(byte-identical results). These tests only run when it is installed.
"""
from __future__ import annotations

import pytest

native = pytest.importorskip("mnemosyne_native")


def test_native_module_exposes_contract_surface():
    assert isinstance(native.__version__, str) and native.__version__
    assert native.parity_marker() == "strict-ieee-scalar-v1"
```

- [ ] **Step 2: Run it — expect SKIP (module not installed yet)**

Run: `uv run --locked python -m pytest tests/test_native_packaging.py -v`
Expected: 1 skipped ("mnemosyne_native").

- [ ] **Step 3: Create the crate**

`rust/mnemosyne-native/Cargo.toml`:

```toml
[package]
name = "mnemosyne-native"
version = "0.1.0"
edition = "2021"
rust-version = "1.85"

[lib]
name = "mnemosyne_native"
crate-type = ["cdylib"]

[dependencies]
pyo3 = { version = "0.29", features = ["abi3-py312"] }
blake2 = "0.10"
regex = "1"
rayon = "1"

[profile.release]
lto = true
codegen-units = 1
```

`rust/mnemosyne-native/pyproject.toml`:

```toml
[build-system]
requires = ["maturin>=1.14,<2"]
build-backend = "maturin"

[project]
name = "mnemosyne-native"
version = "0.1.0"
description = "Byte-parity native kernels for Mnemosyne (optional accelerator)"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }

[tool.maturin]
module-name = "mnemosyne_native"
```

`rust/mnemosyne-native/src/lib.rs`:

```rust
//! Byte-parity native kernels for Mnemosyne.
//!
//! PARITY CONTRACT (plan Global Constraints): every function is bit-identical
//! to its pure-Python counterpart. Scalar sequential f64 per item; rayon only
//! ACROSS items; no mul_add, no transcendentals; allowed ops: + - * / sqrt abs.

use pyo3::prelude::*;

#[pyfunction]
fn parity_marker() -> &'static str {
    "strict-ieee-scalar-v1"
}

#[pymodule]
fn mnemosyne_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_function(wrap_pyfunction!(parity_marker, m)?)?;
    Ok(())
}
```

- [ ] **Step 4: Wire the optional extra in the root `pyproject.toml`**

Add `native = ["mnemosyne-native"]` to `[project.optional-dependencies]` (alongside `postgres`/`mcp`), and:

```toml
[tool.uv.sources]
mnemosyne-native = { path = "rust/mnemosyne-native" }
```

Then: `uv lock` (registers the path dep) followed by `uv sync --locked --extra mcp --extra postgres --extra native --group dev` (uv builds the crate via maturin; first build compiles PyO3 — expect ~1–2 min). If uv cannot build the path dep, STOP and report BLOCKED with the exact error.

- [ ] **Step 5: Verify both directions**

Run: `uv run --locked python -m pytest tests/test_native_packaging.py -v` → 1 passed.
Run: `uv run --locked python -c "import mnemosyne_native as n; print(n.__version__, n.parity_marker())"` → `0.1.0 strict-ieee-scalar-v1`.
Verify no-Rust path still resolves: `uv sync --locked --extra mcp --extra postgres --group dev` must complete (it will REMOVE mnemosyne_native — that's exact-sync semantics and it proves optionality), then re-add with `--extra native`. Document both commands in the report.

- [ ] **Step 6: Full suite (native installed), ruff, commit**

```bash
uv run --locked python -m pytest   # zero new failures vs 1306/116
uv run --locked ruff check .
git add rust/ pyproject.toml uv.lock tests/test_native_packaging.py
git commit -m "feat(native): mnemosyne-native crate scaffold as optional path-dep extra"
```

---

### Task 2: `hashing_embedding` kernel + golden bit-equality

**Files:**
- Modify: `rust/mnemosyne-native/src/lib.rs` (add `src/hashing.rs`, `mod hashing;`)
- Test: `tests/test_native_parity.py` (new)

**Interfaces:**
- Produces: `mnemosyne_native.hashing_embedding(text: str, dims: int) -> list[float]` — bit-identical to `mnemosyne.text._hashing_embedding_cached.__wrapped__(text, dims)` (the uncached pure function).
- Consumes: parity note 4 (blake2b param block, bucket/sign rules, sequential norm).

- [ ] **Step 1: Write failing bit-equality tests**

```python
# tests/test_native_parity.py
"""Bit-equality between mnemosyne_native kernels and the pure-Python path.

Every comparison is on struct.pack('<d') bytes — parity means BITS, not ==.
"""
from __future__ import annotations

import struct

import pytest
from hypothesis import given, settings, strategies as st

native = pytest.importorskip("mnemosyne_native")

from mnemosyne.text import _hashing_embedding_cached  # noqa: E402


def bits(xs: list[float]) -> bytes:
    return b"".join(struct.pack("<d", x) for x in xs)


texts = st.text(
    alphabet=st.characters(codec="utf-8", exclude_categories=("Cs",)),
    max_size=400,
)


@given(texts, st.sampled_from([16, 256, 1024]))
@settings(max_examples=200, deadline=None)
def test_hashing_embedding_bit_identical(text, dims):
    pure = _hashing_embedding_cached.__wrapped__(text, dims)
    assert bits(native.hashing_embedding(text, dims)) == bits(list(pure))


def test_hashing_embedding_golden_zero_norm():
    # No tokens => zero vector, returned UNNORMALIZED (norm==0.0 branch)
    assert native.hashing_embedding("!!! ???", 8) == [0.0] * 8
```

- [ ] **Step 2: Run — expect AttributeError (no such function).**

- [ ] **Step 3: Implement `rust/mnemosyne-native/src/hashing.rs`**

```rust
use blake2::digest::{Update, VariableOutput};
use blake2::Blake2bVar;
use pyo3::prelude::*;

use crate::tokenize::tokenize_str;

/// Bit-identical port of mnemosyne.text._hashing_embedding_cached (uncached).
#[pyfunction]
pub fn hashing_embedding(text: &str, dims: usize) -> Vec<f64> {
    let mut vec = vec![0.0f64; dims];
    for token in tokenize_str(text) {
        let mut hasher = Blake2bVar::new(8).expect("digest size 8 is valid");
        hasher.update(token.as_bytes());
        let mut digest = [0u8; 8];
        hasher.finalize_variable(&mut digest).expect("finalize");
        let bucket = (u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]) as usize) % dims;
        let sign = if digest[4] % 2 == 0 { 1.0 } else { -1.0 };
        vec[bucket] += sign;
    }
    let mut sum_sq = 0.0f64;
    for x in &vec {
        sum_sq += x * x;
    }
    let norm = sum_sq.sqrt();
    if norm == 0.0 {
        return vec;
    }
    vec.iter().map(|x| x / norm).collect()
}
```

NOTE: this depends on Task 3's `tokenize_str`. If implementing Tasks 2–3 in one commit is cleaner, say so in the report — but the tests for both must exist and pass. Otherwise temporarily inline a private tokenizer and refactor in Task 3. Rebuild with `uv sync --locked --extra mcp --extra postgres --extra native --group dev` (or `uv pip install -e rust/mnemosyne-native` for faster iteration — document which you used; final verification MUST use the uv sync form).

- [ ] **Step 4: Run tests — 200-example hypothesis + golden must PASS bit-exact.** If any example fails, do NOT loosen the test — find the semantic divergence (tokenize order, param block, norm branch) and fix the Rust.

- [ ] **Step 5: Full suite, ruff, commit** — `feat(native): hashing_embedding kernel, bit-identical to pure path`

---

### Task 3: `tokenize` + `lexical_score` kernels

**Files:**
- Modify: `rust/mnemosyne-native/src/lib.rs` (+ `src/tokenize.rs`, `src/lexical.rs`)
- Test: `tests/test_native_parity.py` (extend)

**Interfaces:**
- Produces: `mnemosyne_native.tokenize(text: str) -> list[str]`; `mnemosyne_native.lexical_score(query: str, text: str) -> float`; `mnemosyne_native.lexical_scan(query: str, texts: list[str]) -> list[float]` (rayon across texts, per-text identical to `lexical_score`); internal `tokenize_str` reused by hashing.
- Consumes: parity notes 2–3 (first-occurrence order; ASCII regex/lower/strip).

- [ ] **Step 1: Failing tests (extend test_native_parity.py)**

```python
from mnemosyne.text import lexical_score, tokenize  # noqa: E402


@given(texts)
@settings(max_examples=200, deadline=None)
def test_tokenize_identical(text):
    assert native.tokenize(text) == tokenize(text)


@given(texts, texts)
@settings(max_examples=200, deadline=None)
def test_lexical_score_bit_identical(query, text):
    assert struct.pack("<d", native.lexical_score(query, text)) == struct.pack(
        "<d", lexical_score(query, text)
    )


def test_lexical_scan_matches_loop_bitwise():
    docs = ["alpha beta beta", "beta gamma", "", "alpha alpha alpha delta"]
    q = "beta alpha beta"  # duplicate first-occurrence-order stressor
    assert bits(native.lexical_scan(q, docs)) == bits([lexical_score(q, d) for d in docs])
```

- [ ] **Step 2: Run — expect AttributeError.**

- [ ] **Step 3: Implement.** `src/tokenize.rs`:

```rust
use pyo3::prelude::*;
use regex::Regex;
use std::sync::OnceLock;

static TOKEN_RE: OnceLock<Regex> = OnceLock::new();

pub fn tokenize_str(text: &str) -> Vec<String> {
    let re = TOKEN_RE.get_or_init(|| {
        Regex::new(r"[A-Za-z0-9_][A-Za-z0-9_:+./-]*").expect("static pattern")
    });
    let mut tokens = Vec::new();
    for m in re.find_iter(text) {
        let token: String = m
            .as_str()
            .to_ascii_lowercase()
            .trim_matches(|c| matches!(c, '.' | '/' | ':' | '+' | '-'))
            .to_string();
        if !token.is_empty() {
            tokens.push(token);
        }
    }
    tokens
}

#[pyfunction]
pub fn tokenize(text: &str) -> Vec<String> {
    tokenize_str(text)
}
```

`src/lexical.rs` — first-occurrence-order accumulation and the exact formula `(1.0 + ln(tf)) * q_count`, `score / sqrt(doc_len)`. **`math.log` IS a transcendental** — the ban exception: `ln` here must match CPython's `math.log` bit-for-bit. CPython `math.log` calls platform libm `log`; Rust `f64::ln` also calls platform intrinsic/libm on aarch64-apple — VERIFY bit-equality empirically via the hypothesis test (200 examples with real tf counts); additionally add a targeted loop test over tf = 1..=10_000 comparing `math.log(tf)` to Rust. If ANY tf diverges: switch the kernel to call back into a precomputed table only if practical — otherwise STOP and report BLOCKED with the divergent values (the controller must decide: keep lexical in pure Python or accept a documented deviation). Record the outcome in your report either way.

```rust
use pyo3::prelude::*;
use rayon::prelude::*;

use crate::tokenize::tokenize_str;

fn term_counts_ordered(text: &str) -> Vec<(String, u64)> {
    let mut order: Vec<String> = Vec::new();
    let mut counts: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
    for tok in tokenize_str(text) {
        let entry = counts.entry(tok.clone()).or_insert(0);
        if *entry == 0 {
            order.push(tok);
        }
        *entry += 1;
    }
    order
        .into_iter()
        .map(|t| {
            let c = counts[&t];
            (t, c)
        })
        .collect()
}

pub fn lexical_score_str(query: &str, text: &str) -> f64 {
    let q = term_counts_ordered(query);
    if q.is_empty() {
        return 0.0;
    }
    let doc = term_counts_ordered(text);
    let doc_map: std::collections::HashMap<&str, u64> =
        doc.iter().map(|(t, c)| (t.as_str(), *c)).collect();
    let doc_len: u64 = doc.iter().map(|(_, c)| *c).sum::<u64>().max(1);
    let mut score = 0.0f64;
    for (term, q_count) in &q {
        let tf = *doc_map.get(term.as_str()).unwrap_or(&0);
        if tf != 0 {
            score += (1.0 + (tf as f64).ln()) * (*q_count as f64);
        }
    }
    score / (doc_len as f64).sqrt()
}

#[pyfunction]
pub fn lexical_score(query: &str, text: &str) -> f64 {
    lexical_score_str(query, text)
}

#[pyfunction]
pub fn lexical_scan(py: Python<'_>, query: &str, texts: Vec<String>) -> Vec<f64> {
    py.detach(|| texts.par_iter().map(|t| lexical_score_str(query, t)).collect())
}
```

(If `py.detach` doesn't exist in PyO3 0.29, use the current GIL-release API — `py.allow_threads` or its 0.29 rename; check the installed PyO3 docs and say which you used.)

- [ ] **Step 4: Run tests bit-exact PASS + the tf=1..10000 log-parity loop test. Step 5: full suite, ruff, commit** — `feat(native): tokenize + lexical kernels with first-occurrence-order parity`

---

### Task 4: `cosine` + `dense_scan` batch kernel

**Files:**
- Modify: `rust/mnemosyne-native/src/lib.rs` (+ `src/dense.rs`)
- Test: `tests/test_native_parity.py` (extend)

**Interfaces:**
- Produces: `mnemosyne_native.cosine(a: list[float], b: list[float]) -> float` (truncating zip semantics); `mnemosyne_native.dense_scan(query_vec: list[float], rows: list[list[float] | None]) -> list[float | None]` — per-row `cosine(query_vec, row)`, `None` rows pass through as `None`, results in input order, rayon across rows.

- [ ] **Step 1: Failing tests**

```python
from mnemosyne.text import cosine  # noqa: E402

floats = st.floats(allow_nan=False, allow_infinity=False, width=64)
vecs = st.lists(floats, min_size=0, max_size=64)


@given(vecs, vecs)
@settings(max_examples=300, deadline=None)
def test_cosine_bit_identical_incl_truncation(a, b):
    assert struct.pack("<d", native.cosine(a, b)) == struct.pack("<d", cosine(a, b))


@given(vecs, st.lists(st.one_of(st.none(), vecs), min_size=0, max_size=20))
@settings(max_examples=200, deadline=None)
def test_dense_scan_matches_per_row_loop(q, rows):
    expected = [None if r is None else cosine(q, r) for r in rows]
    got = native.dense_scan(q, rows)
    assert len(got) == len(expected)
    for g, e in zip(got, expected, strict=True):
        if e is None:
            assert g is None
        else:
            assert struct.pack("<d", g) == struct.pack("<d", e)
```

- [ ] **Step 2: expect AttributeError. Step 3: implement**

```rust
use pyo3::prelude::*;
use rayon::prelude::*;

pub fn cosine_seq(a: &[f64], b: &[f64]) -> f64 {
    let n = a.len().min(b.len()); // zip strict=False truncation
    let mut acc = 0.0f64;
    for i in 0..n {
        acc += a[i] * b[i];
    }
    acc
}

#[pyfunction]
pub fn cosine(a: Vec<f64>, b: Vec<f64>) -> f64 {
    cosine_seq(&a, &b)
}

#[pyfunction]
pub fn dense_scan(py: Python<'_>, query_vec: Vec<f64>, rows: Vec<Option<Vec<f64>>>) -> Vec<Option<f64>> {
    py.detach(|| {
        rows.par_iter()
            .map(|row| row.as_ref().map(|r| cosine_seq(&query_vec, r)))
            .collect()
    })
}
```

- [ ] **Step 4: PASS bit-exact. Step 5: full suite, ruff, commit** — `feat(native): cosine + rayon dense_scan with truncation parity`

---

### Task 5: `mmr_select` kernel

**Files:**
- Modify: `rust/mnemosyne-native/src/lib.rs` (+ `src/mmr.rs`)
- Test: `tests/test_native_parity.py` (extend)

**Interfaces:**
- Produces: `mnemosyne_native.mmr_select_indices(base_scores: list[float], vectors: list[list[float] | None], query_vec: list[float], k: int, mmr_lambda: float) -> list[int]` — selection-order indices, semantics exactly `algorithms.mmr_select` with vectors pre-materialized (parity note 5).
- The Python-side integration (materialization + fallback) is Task 6 — this task is kernel + reference-parity only.

- [ ] **Step 1: Failing tests** — a pure-Python REFERENCE mirroring `algorithms.mmr_select` but over (base_scores, vectors) directly (write it in the test file, ~20 lines, using `mnemosyne.text.cosine`); then:

```python
@given(
    st.lists(floats, min_size=0, max_size=12),          # base_scores
    st.data(),
)
@settings(max_examples=200, deadline=None)
def test_mmr_select_indices_matches_reference(base_scores, data):
    n = len(base_scores)
    vectors = data.draw(st.lists(st.one_of(st.none(), st.lists(floats, min_size=3, max_size=3)), min_size=n, max_size=n))
    k = data.draw(st.integers(min_value=0, max_value=n + 2))
    lam = data.draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    q = data.draw(st.lists(floats, min_size=3, max_size=3))
    assert native.mmr_select_indices(base_scores, vectors, q, k, lam) == _reference_mmr(base_scores, vectors, q, k, lam)


def test_mmr_ties_first_wins_on_input_order():
    # identical base scores, no vectors: argmax ties resolve to lowest index
    assert native.mmr_select_indices([5.0, 5.0, 5.0], [None, None, None], [1.0], 2, 0.7) == [0, 1]
```

The reference MUST reproduce the pure algorithm exactly: per-candidate objective `lam * rel - (1.0 - lam) * penalty` then `+ base`, penalty = max cosine vs already-selected non-None vectors, strict `>`, remove-selected, loop.

- [ ] **Step 2: expect AttributeError. Step 3: implement** — straight port; selected vectors looked up from the materialized `vectors` (recomputation in the pure engine path returns identical values, established in Phase 0 Task 4 review). Sequential (MMR is O(k·n) on ≤ rerank-width items — no rayon; determinism first).

- [ ] **Step 4: PASS. Step 5: full suite, ruff, commit** — `feat(native): mmr_select_indices kernel with first-wins tie parity`

---

### Task 6: Dispatch layer + `MNEMOSYNE_PURE` + parity suite both modes

**Files:**
- Modify: `src/mnemosyne/text.py`, `src/mnemosyne/algorithms.py`
- Modify: `CONFIG-DRIFT-CHECKS.md` ("Configuration sources": `MNEMOSYNE_PURE`)
- Test: `tests/test_native_dispatch.py` (new)

**Interfaces:**
- Produces: `mnemosyne.text.NATIVE` (module-level: the imported `mnemosyne_native` or `None` — `None` when absent OR `MNEMOSYNE_PURE=1` at import); `tokenize`/`lexical_score`/`hashing_embedding`/`cosine` route through it; `algorithms.mmr_select` gains a native fast path that materializes `embed_hit` results once per hit then calls `mmr_select_indices`; `algorithms` re-exports nothing new. One `logging.getLogger("mnemosyne.native").info(...)` line at import stating the active path.
- The lru_cache on `hashing_embedding` REMAINS (it caches whichever backend computed the value — byte-parity makes them interchangeable).

- [ ] **Step 1: Failing dispatch tests**

```python
# tests/test_native_dispatch.py
"""Dispatch contract: native active by default when installed; MNEMOSYNE_PURE=1
forces pure; results byte-identical either way (spot-checked here; the full
guarantee is the parity suite run in both modes, Task 6 Step 4)."""
from __future__ import annotations

import os
import struct
import subprocess
import sys

import pytest

native = pytest.importorskip("mnemosyne_native")


def _run(code: str, pure: bool) -> str:
    env = dict(os.environ)
    if pure:
        env["MNEMOSYNE_PURE"] = "1"
    else:
        env.pop("MNEMOSYNE_PURE", None)
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    ).stdout.strip()


CODE = (
    "import struct; from mnemosyne import text;"
    "v = text.hashing_embedding('alpha beta x1.2.3', 256);"
    "s = text.lexical_score('alpha beta', 'alpha gamma beta beta');"
    "print(text.NATIVE is not None, struct.pack('<d', s).hex(), ''.join(struct.pack('<d', x).hex() for x in v[:8]))"
)


def test_native_active_by_default_and_pure_forced():
    active = _run(CODE, pure=False).split()
    forced = _run(CODE, pure=True).split()
    assert active[0] == "True" and forced[0] == "False"
    assert active[1:] == forced[1:]  # byte-identical outputs
```

- [ ] **Step 2: expect failure (no NATIVE attr). Step 3: implement in text.py**

```python
import logging
import os

try:
    if os.environ.get("MNEMOSYNE_PURE") == "1":
        NATIVE = None
    else:
        import mnemosyne_native as NATIVE  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - environment-dependent
    NATIVE = None

logging.getLogger("mnemosyne.native").info(
    "kernel path: %s", "native (mnemosyne_native)" if NATIVE is not None else "pure-python"
)
```

Each function body branches once: e.g. `def tokenize(text): return NATIVE.tokenize(text) if NATIVE is not None else <existing body moved to _tokenize_pure>`. Keep the pure implementations as `_tokenize_pure`, `_lexical_score_pure`, `_cosine_pure`, `_hashing_embedding_pure` (the previous bodies, unchanged) — the parity tests in tests/test_native_parity.py import the pure forms via `_hashing_embedding_cached.__wrapped__` and the `_..._pure` names; UPDATE those imports accordingly and keep `_hashing_embedding_cached` wrapping the dispatching function's inner compute so cache behavior is identical in both modes. In `algorithms.mmr_select`: if `text.NATIVE is not None`, materialize `[embed_hit(h) for h in hits]` (list index-aligned; this preserves the one-metadata-side-effect-per-hit behavior) and `query_vec` and return `[hits[i] for i in NATIVE.mmr_select_indices(...)]`; else the existing loop unchanged.

- [ ] **Step 4: THE GATE — parity suite in both modes:**

```bash
uv run --locked python -m pytest                      # native mode: zero new failures
MNEMOSYNE_PURE=1 uv run --locked python -m pytest     # pure mode: zero new failures
```

Record both counts. Also register `MNEMOSYNE_PURE` in CONFIG-DRIFT-CHECKS.md (existing bullet format).

- [ ] **Step 5: ruff, commit** — `feat(native): dispatch layer with MNEMOSYNE_PURE override, parity-proven both modes`

---

### Task 7: Engine batch call sites (single FFI crossing on scans)

**Files:**
- Modify: `src/mnemosyne/engine.py` (`LocalMemoryEngine.vector_search` ~:1206, `lexical_search`)
- Test: `tests/test_native_dispatch.py` (extend)

**Interfaces:**
- Consumes: `dense_scan`, `lexical_scan`, `text.NATIVE`.
- `vector_search`: keep per-hit embedding acquisition in Python (security gate + metadata side effects), collect `(hit, vec_or_None)` pairs, then ONE `dense_scan` call replaces the per-hit `cosine`; identical filter (`score > 0`), channel assignment, sort, truncation. Pure path untouched when `NATIVE is None`.
- `lexical_search` (the adapterless branch only): collect candidate texts, ONE `lexical_scan` call replaces the per-hit `lexical_score`; identical downstream.

- [ ] **Step 1: Failing equivalence tests** — seed a LocalMemoryEngine with ~20 items via the canonical capture call (copy from tests/test_engine_contract.py), run `vector_search`/`lexical_search` in a subprocess under both modes (reuse `_run` helper), compare full (id, score-hex, channel) tuples byte-exact.

- [ ] **Step 2: implement the two batch branches guarded by `if NATIVE is not None:`. Step 3: both-modes equivalence tests PASS. Step 4: full suite both modes. Step 5: commit** — `perf(engine): batch native scans for local vector/lexical search`

---

### Task 8: Kernel benchmarks + ≥10× exit measurement

**Files:**
- Modify: `tests/benchmarks/test_retrieval_baselines.py` (add native benches)
- Test: same file

**Interfaces:**
- Adds `test_bench_native_lexical_scan_2k`, `test_bench_native_hashing_embedding_cold`, `test_bench_native_dense_scan_2k_256d` (mirror inputs of the pure benches EXACTLY — same `_RNG` docs, same salt-cold semantics for hashing). These do NOT gate against baselines.json (they're the comparison side); instead each asserts the native mean is ≤ 1/10 of the corresponding committed pure baseline (`_gate_speedup(name, seconds, factor=10)` helper reading baselines.json) — THE PHASE EXIT BAR. Skip (not fail) when `mnemosyne_native` is absent.

- [ ] **Step 1: add benches + `_gate_speedup`. Step 2: run** `uv run --locked python -m pytest tests/benchmarks --benchmark-only` — native benches PASS the 10× bar (expected: lexical_scan_2k 47.8ms → <4.8ms; hashing gates at ≥3×, not 10× — measured ~4.6× vs the true pure baseline (native ~15.6µs vs pure ~71µs); 10× is structurally out of reach because the pure path's blake2b is C-backed hashlib, and hashing is not in the spec's scan-bench exit bar; dense_scan vs cosine_1024-derived bound — define dense bound as 2000×cosine_256 equivalent from the committed cosine_1024 baseline scaled ×(256/1024), document the arithmetic in a comment). If a bench misses 10×, do NOT ship a weakened gate — report BLOCKED with the measured number.
- **Outcome amendment (2026-07-02, controller decision):** the dense END-TO-END ≥10× gate is re-homed to Phase 2's packed-BLOB seam (2026-07-02-phase2-sqlite-engine.md, Task 4, "PACKED-BLOB dense seam") — measured vs honest MNEMOSYNE_PURE=1 baselines: 4.6× at the shipped list-FFI seam (~93% PyFloat conversion) vs ~82× kernel-side on prepacked bytes (gated at 10× by `test_bench_native_dense_scan_prepacked`) and ~40× lexical. (The earlier quoted 1.8×/30×/33.3× were computed against a contaminated baseline capture: the capture subprocess had inherited an env without MNEMOSYNE_PURE=1 and the benches imported dispatching functions, so the committed "pure" baselines actually measured the native path — not a capture taken under machine load.)
- [ ] **Step 3: record all native means in the report + commit** — `feat(bench): native kernel benches with 10x exit gates`

---

### Task 9: A4 lazy imports (CLI ≤100 ms)

**Files:**
- Modify: `src/mnemosyne/cli.py`, `src/mnemosyne/mcp_server.py`, possibly `src/mnemosyne/__init__.py`
- Test: `tests/test_import_time.py` (new)

**Interfaces:**
- Measured reality (2026-07-02): `import mnemosyne.cli` cumulative ≈225 ms; top costs: `mnemosyne.engine` 143 ms (pulled via `mnemosyne/__init__` or cli), `mnemosyne.retrieval` 90 ms, `mnemosyne.security` 37 ms, `cryptography.hazmat.bindings._rust` 26 ms, `mnemosyne.jobs` 33 ms, `mnemosyne.eval` 23 ms, cli's own eager `from cryptography import x509` (cli.py:29).
- Approach: (1) audit `src/mnemosyne/__init__.py` — if it eagerly imports engine/retrieval, convert to lazy `__getattr__` (PEP 562) preserving `from mnemosyne import X` for every currently-exported name (enumerate them first; behavior must be import-order identical for consumers); (2) in cli.py move heavy imports (`cryptography.x509`, engine/consolidation/ingestion/media-touching modules) into the functions/subcommands that use them; (3) same audit for mcp_server.py's eager block (engine/ingestion/mcp_tools stay — the daemon needs them — but anything reachable-late goes lazy). NEVER move an import whose module has import-time side effects the program relies on (check each: grep for module-level statements beyond defs/constants).
- Exit bar: `python -X importtime -c "import mnemosyne.cli"` cumulative ≤ 100 ms on this machine, and `uv run --locked mneme --help` wall ≤ 350 ms (from ~610 ms). A committed test guards regression loosely: import of `mnemosyne.cli` must not import `cryptography.x509` or `mnemosyne.consolidation` at module level (assert via `sys.modules` in a subprocess).

- [ ] **Step 1: failing sys.modules test. Step 2: implement lazily, iterating with importtime. Step 3: full suite BOTH modes (lazy imports are behavior-sensitive — the suite is the guard). Step 4: measure + record both numbers. Step 5: commit** — `perf(cli): lazy imports — import time under 100ms`

---

### Task 10: CI wheels job (now gating) + phase exit

**Files:**
- Modify: `.github/workflows/ci.yml` (read its existing structure FIRST; add a `native-wheels` job)
- Modify: `docs/superpowers/plans/2026-07-01-native-acceleration-program.md` (Phase 1 → DONE)

**Interfaces:**
- The wheels job: PyO3/maturin-action@v1 building `rust/mnemosyne-native` for macos-14 (arm64) and ubuntu-latest x86_64, `--release`, abi3-py312, artifacts uploaded, and merge-gating for the current two-runner matrix. ALSO add to the existing test job: a step installing the native extra + running `tests/test_native_parity.py tests/test_native_dispatch.py` under both modes IF the runner has Rust (use a matrix flag or `if:` guard; keep the default lane rust-free to preserve the no-toolchain guarantee). Cannot be executed locally — validate YAML with `uv run --locked python -c "import yaml,sys;yaml.safe_load(open('.github/workflows/ci.yml'))"` and state clearly in the report that CI execution is unverified here.
- Phase exit checklist (all run locally): full suite both modes; DSN-armed parity both modes (`MNEMOSYNE_POSTGRES_DSN=postgresql://mnemosyne:mnemosyne-local-dev@127.0.0.1:54329/mnemosyne`, dev compose postgres — start it if down: `docker compose up -d postgres`); benchmarks incl. 10× gates; ruff; `cargo clippy --manifest-path rust/mnemosyne-native/Cargo.toml -- -D warnings`; the mul_add/transcendental lint (`grep -rn 'mul_add\|f64::exp\|f64::sin\|powf' rust/mnemosyne-native/src/ | grep -v ln` must be empty — `ln` is the one documented exception from Task 3). For the 10× gates, the dense end-to-end 10× is re-homed to Phase 2's packed-BLOB seam (2026-07-02-phase2-sqlite-engine.md Task 4): Phase 1 exits on 40.5× lexical and 82.5× kernel-side prepacked dense (both 10×-gated) plus hashing at 4.6× against its 3.0× floor (10× is structurally out of reach — the pure path's blake2b is already C), with the shipped list-FFI dense seam at 4.6× informational (PyFloat→f64 conversion wall; see the bench comments).

- [ ] **Step 1: CI job + YAML validation. Step 2: run the full exit checklist, record every count. Step 3: program map update. Step 4: commit** — `docs(phase1): native kernels complete; CI wheels job gated`

---

## Self-Review (performed at authoring time)

1. **Spec coverage (§4.1 + Phase-0 handoffs):** kernels (tokenize/lexical/hashing/cosine) → T2–T4; batched dense_scan/mmr_select → T4/T5/T7; byte-parity + scalar/strict-IEEE + rayon-across-items + tie discipline → parity notes + T2–T5 tests; MNEMOSYNE_PURE dispatch + startup log → T6; wheels → T10 (current two-runner builders merge-gating; broader release matrix still pending); A4 → T9; ≥10× exit → T8; quantized tier deliberately deferred (spec allows). Packaging deviation (sibling crate vs mixed layout) documented in the header with rationale — flag for the phase's final review.
2. **Known risk, made explicit:** `math.log` bit-parity (T3) is empirically probable on aarch64-apple (same libm) but not RFC-guaranteed — the plan makes it a hard verification with a BLOCKED escape hatch rather than an assumption.
3. **Type consistency:** `dense_scan(query_vec, rows) -> list[float|None]`, `mmr_select_indices(base_scores, vectors, query_vec, k, mmr_lambda) -> list[int]`, `lexical_scan(query, texts) -> list[float]` are used identically in T4/T5/T6/T7/T8 interface blocks.

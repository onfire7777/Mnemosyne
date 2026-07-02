//! Bit-identical port of `mnemosyne.text.cosine` (parity note 1) and the
//! per-row dense scan built on it.
//!
//! Pure path: `sum(x * y for x, y in zip(a, b, strict=False))`.
//!
//! CORRECTION to parity note 1 (discovered by the hypothesis suite): since
//! CPython 3.12 (gh-100425), builtin `sum()` over floats is NOT naive
//! sequential accumulation — it is Neumaier (improved Kahan–Babuška)
//! COMPENSATED summation. A naive `acc += x * y` loop diverges by 1 ulp on
//! inputs like `cosine([1.0, 10.0, 2.0], [3.0, 993440926500744.0, 1.0])`.
//! `cosine_seq` therefore ports CPython's float fast path exactly:
//!
//! * start is int 0, so the FIRST product enters via `PyNumber_Add(0, p0)`
//!   => `f = 0.0 + p0` (exact; normalizes -0.0 to +0.0), `c = 0.0`;
//! * each subsequent product `x`: `t = f + x`; `c += (f - t) + x` when
//!   `|f| >= |x|` else `c += (x - t) + f`; `f = t`;
//! * at exhaustion the compensation is folded in ONLY when nonzero and
//!   finite: `if (c && isfinite(c)) f_result += c;`.
//!
//! `zip(strict=False)` = SILENT TRUNCATION to the shorter input; Rust's
//! `zip` truncates identically. Ops used: `+ - * abs` — all inside the
//! kernel float-op allowlist (no fused multiply-add: each `x * y` is one
//! rounded multiply, exactly like the pure generator).

use pyo3::prelude::*;
use rayon::prelude::*;

/// Scalar sequential kernel shared by `cosine`, `dense_scan`, and the MMR
/// kernel (crate-internal). See module docs: exact CPython 3.12 `sum()`
/// Neumaier semantics over the truncating product stream.
pub fn cosine_seq(a: &[f64], b: &[f64]) -> f64 {
    let mut prods = a.iter().zip(b.iter()).map(|(x, y)| x * y);
    let Some(first) = prods.next() else {
        // Empty zip: pure sum() returns int 0 => the bits of +0.0.
        return 0.0;
    };
    let mut f = 0.0f64 + first; // PyNumber_Add(int 0, first): exact, -0.0 -> +0.0
    let mut c = 0.0f64;
    for x in prods {
        let t = f + x;
        if f.abs() >= x.abs() {
            c += (f - t) + x;
        } else {
            c += (x - t) + f;
        }
        f = t;
    }
    // CPython: `if (c && isfinite(c))` — skip zero (avoid losing a -0.0
    // result's sign) and non-finite compensation (avoid inf-inf => NaN).
    if c != 0.0 && c.is_finite() {
        f += c;
    }
    f
}

#[pyfunction]
pub fn cosine(a: Vec<f64>, b: Vec<f64>) -> f64 {
    cosine_seq(&a, &b)
}

/// Rayon ACROSS rows only (per plan constraints); each per-row score is the
/// scalar-sequential `cosine_seq`. `None` rows pass through as `None`, and
/// `collect` on the indexed parallel iterator keeps results aligned to input
/// order.
#[pyfunction]
pub fn dense_scan(
    py: Python<'_>,
    query_vec: Vec<f64>,
    rows: Vec<Option<Vec<f64>>>,
) -> Vec<Option<f64>> {
    py.detach(|| {
        rows.par_iter()
            .map(|row| row.as_ref().map(|r| cosine_seq(&query_vec, r)))
            .collect()
    })
}

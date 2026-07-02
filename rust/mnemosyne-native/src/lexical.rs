//! Bit-identical port of `mnemosyne.text.lexical_score` (parity note 2).
//!
//! The pure path iterates `Counter.items()` — Python dict insertion order,
//! i.e. FIRST-OCCURRENCE order of query tokens. Float accumulation order
//! depends on it, so `term_counts_ordered` preserves that order exactly.
//!
//! `ln` here is THE single documented transcendental exception to the kernel
//! float-op ban: it must match CPython `math.log` bit-for-bit (both call
//! platform libm log on aarch64-apple). Proven by the parity suite via the
//! tf=1..=10_000 loop over the test-only `_ln` helper plus the 200-example
//! hypothesis property on `lexical_score` itself.

use pyo3::prelude::*;
use rayon::prelude::*;

use crate::tokenize::for_each_token;

/// Query terms counted ONCE per call/scan: `terms` is first-occurrence-ordered
/// (term, count) pairs — Python `Counter.items()` insertion order — and
/// `index` maps each term to its position in `terms`.
struct QueryTerms {
    terms: Vec<(String, u64)>,
    index: std::collections::HashMap<String, usize>,
}

impl QueryTerms {
    fn new(query: &str) -> Self {
        let mut terms: Vec<(String, u64)> = Vec::new();
        let mut index: std::collections::HashMap<String, usize> =
            std::collections::HashMap::new();
        for_each_token(query, |tok| {
            if let Some(&i) = index.get(tok) {
                terms[i].1 += 1;
            } else {
                index.insert(tok.to_owned(), terms.len());
                terms.push((tok.to_owned(), 1));
            }
        });
        QueryTerms { terms, index }
    }
}

/// Score one text against pre-counted query terms. The pure path builds the
/// full doc Counter, but only two doc-side quantities ever reach the score:
/// each QUERY term's tf and the doc's TOTAL token count (`doc_len` = sum of
/// all counts). Accumulating exactly those (tf per query term in `tfs`, one
/// token counter) over the zero-alloc token visitor produces bit-identical
/// results: same integer tf/doc_len values, same float ops in the same
/// first-occurrence query order.
fn lexical_score_counted(q: &QueryTerms, tfs: &mut [u64], text: &str) -> f64 {
    if q.terms.is_empty() {
        return 0.0;
    }
    tfs.fill(0);
    let mut doc_len: u64 = 0;
    for_each_token(text, |tok| {
        doc_len += 1;
        if let Some(&i) = q.index.get(tok) {
            tfs[i] += 1;
        }
    });
    let doc_len = doc_len.max(1);
    let mut score = 0.0f64;
    for ((_, q_count), tf) in q.terms.iter().zip(tfs.iter()) {
        if *tf != 0 {
            score += (1.0 + (*tf as f64).ln()) * (*q_count as f64);
        }
    }
    score / (doc_len as f64).sqrt()
}

pub fn lexical_score_str(query: &str, text: &str) -> f64 {
    let q = QueryTerms::new(query);
    let mut tfs = vec![0u64; q.terms.len()];
    lexical_score_counted(&q, &mut tfs, text)
}

#[pyfunction]
pub fn lexical_score(query: &str, text: &str) -> f64 {
    lexical_score_str(query, text)
}

/// Rayon ACROSS texts only (per plan constraints); each per-text score is the
/// scalar-sequential `lexical_score_counted` over query term counts computed
/// ONCE and shared (the pure loop recomputes them per text, but they are
/// input-only — hoisting cannot change any per-text result). `map_init` gives
/// each rayon worker a reusable tf buffer; `collect` on the indexed parallel
/// iterator keeps results aligned to input order.
#[pyfunction]
pub fn lexical_scan(py: Python<'_>, query: &str, texts: Vec<String>) -> Vec<f64> {
    let q = QueryTerms::new(query);
    py.detach(|| {
        texts
            .par_iter()
            .map_init(
                || vec![0u64; q.terms.len()],
                |tfs, t| lexical_score_counted(&q, tfs, t),
            )
            .collect()
    })
}

/// TEST-ONLY: the exact `ln` used by `lexical_score`, exposed so the parity
/// suite can prove bit-equality with CPython `math.log` (the documented
/// transcendental exception). Not part of the kernel API surface.
#[pyfunction]
pub fn _ln(x: f64) -> f64 {
    x.ln()
}

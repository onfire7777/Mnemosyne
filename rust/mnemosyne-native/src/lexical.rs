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

/// Rayon ACROSS texts only (per plan constraints); each per-text score is the
/// scalar-sequential `lexical_score_str`, and `collect` on the indexed
/// parallel iterator keeps results aligned to input order.
#[pyfunction]
pub fn lexical_scan(py: Python<'_>, query: &str, texts: Vec<String>) -> Vec<f64> {
    py.detach(|| texts.par_iter().map(|t| lexical_score_str(query, t)).collect())
}

/// TEST-ONLY: the exact `ln` used by `lexical_score`, exposed so the parity
/// suite can prove bit-equality with CPython `math.log` (the documented
/// transcendental exception). Not part of the kernel API surface.
#[pyfunction]
pub fn _ln(x: f64) -> f64 {
    x.ln()
}

//! Bit-identical port of `algorithms.mmr_select` over pre-materialized
//! vectors (parity note 5), returning selection-order INDICES.
//!
//! Deliberately scalar sequential (no rayon): MMR is O(k·n) on at most
//! rerank-width items and determinism comes first. The objective keeps the
//! pure code's exact two-statement shape — no algebraic rearrangement:
//!
//! ```text
//! score = mmr_lambda * relevance - (1.0 - mmr_lambda) * diversity_penalty
//! score += base
//! ```
//!
//! Missing vector => relevance 0.0 AND no diversity penalty; the penalty's
//! max SKIPS None vectors of selected items (staying 0.0 when all of them
//! are None); strict `>` argmax => first-wins on input index; the selected
//! item is removed from `remaining`; loop until k or exhaustion.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::dense::cosine_seq;

/// Python `max()` over `cosine(hit_vec, selected_vec)` for the already-
/// selected NON-None vectors, in selection order: seed with the first value,
/// replace on strict `>`. NOT `f64::max` — its NaN handling (`max(NaN, x) ==
/// x`) differs from CPython's comparison-based max, which keeps the seed
/// when the comparison with NaN is false. `None` when every selected vector
/// is None (the pure code leaves the penalty at 0.0 in that case).
fn max_similarity(v: &[f64], selected: &[usize], vectors: &[Option<Vec<f64>>]) -> Option<f64> {
    let mut cur: Option<f64> = None;
    for &j in selected {
        if let Some(sv) = vectors[j].as_ref() {
            let c = cosine_seq(v, sv);
            cur = Some(match cur {
                None => c,
                Some(m) => {
                    if c > m {
                        c
                    } else {
                        m
                    }
                }
            });
        }
    }
    cur
}

/// `k` is `i64` (not `usize`) so non-positive values mirror the pure loop
/// guard `len(selected) < k` (=> empty selection), instead of failing
/// extraction on negative ints.
#[pyfunction]
pub fn mmr_select_indices(
    base_scores: Vec<f64>,
    vectors: Vec<Option<Vec<f64>>>,
    query_vec: Vec<f64>,
    k: i64,
    mmr_lambda: f64,
) -> PyResult<Vec<usize>> {
    if base_scores.len() != vectors.len() {
        return Err(PyValueError::new_err(format!(
            "mmr_select_indices: base_scores and vectors must be the same length \
             (got {} and {})",
            base_scores.len(),
            vectors.len()
        )));
    }
    let mut selected: Vec<usize> = Vec::new();
    let mut remaining: Vec<usize> = (0..base_scores.len()).collect();
    while !remaining.is_empty() && (selected.len() as i64) < k {
        let mut best: Option<usize> = None;
        let mut best_pos = 0usize; // position in `remaining` for removal
        let mut best_score = f64::NEG_INFINITY;
        for (pos, &i) in remaining.iter().enumerate() {
            let vec = vectors[i].as_deref();
            let relevance = match vec {
                Some(v) => cosine_seq(&query_vec, v),
                None => 0.0,
            };
            let diversity_penalty = if selected.is_empty() {
                0.0
            } else if let Some(v) = vec {
                max_similarity(v, &selected, &vectors).unwrap_or(0.0)
            } else {
                0.0
            };
            let mut score = mmr_lambda * relevance - (1.0 - mmr_lambda) * diversity_penalty;
            score += base_scores[i];
            if score > best_score {
                best = Some(i);
                best_pos = pos;
                best_score = score;
            }
        }
        match best {
            Some(i) => {
                selected.push(i);
                // Same effect as the pure `remaining.remove(best)` (remove by
                // value): indices are unique, so removing at the found
                // position preserves input order for the rest.
                remaining.remove(best_pos);
            }
            None => break, // all-NaN scores: nothing beats -inf, mirror the pure break
        }
    }
    Ok(selected)
}

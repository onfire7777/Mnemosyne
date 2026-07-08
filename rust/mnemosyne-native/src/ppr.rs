//! Bit-identical port of `algorithms._ppr_power_iteration_pure` (Wave 2)
//! over pre-indexed ORDERED structures.
//!
//! The dispatch in `algorithms.ppr_power_iteration` builds the inputs so the
//! float accumulation order is exactly the pure dict pass's insertion-order
//! iteration: `seeds[i]` / node slot `i` follow the pure result's key order —
//! adjacency keys in mapping order first (the sources, slots
//! `0..row_lens.len()`), then out-of-adjacency neighbors in first-touch
//! order of the edge sweep. Every float statement mirrors the pure line
//! shape — no algebraic rearrangement:
//!
//! ```text
//! next_ranks init: teleport * (1.0 if seed else 0.0)   (present nodes only)
//! share = damping * ranks[node] / len(neighbors)        (left-to-right)
//! next_ranks[neighbor] = next_ranks.get(neighbor, 0.0) + share
//! ```
//!
//! Plain sequential binary ops only (`+ * /`, no `sum()` => no Neumaier, no
//! FMA), matching the pure loop op-for-op. Deliberately scalar sequential
//! (no rayon): multiple sources add into the same neighbor slot, so the add
//! order IS the contract.
//!
//! FFI SEAM (same packed-buffer strategy as `dense_scan_packed`): the edge
//! structure crosses as two little-endian u64 byte buffers — the flattened
//! neighbor slots and the per-source row lengths — built Python-side with
//! `array("Q", ...)` at C speed. Boxed-int extraction of the ~E neighbor
//! slots was measured as the dominant kernel-call cost at the list seam;
//! the packed seam reads plain 8-byte loads instead.
//!
//! Python-dict-membership nuance ported via `present`: the pure `next_ranks`
//! comprehension runs over the CURRENT dict keys, so an out-of-adjacency
//! neighbor gets NO teleport term the first iteration that discovers it (it
//! starts from the `.get(neighbor, 0.0)` default) and the full
//! `teleport * seed` term every iteration after — because it joined the dict.
//! Sources (slots `< row_lens.len()`) are present from initialization,
//! exactly like the pure seed comprehension over `adjacency`.
//!
//! `iterations <= 0` mirrors `range(iterations)` (zero passes) at the kernel
//! level, but the dispatch never sends it: the pure zero-iteration result is
//! the seed dict over adjacency keys ONLY (externals never join), so that
//! edge stays on the canonical pure path.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Core loop as plain Rust (unit-testable without a Python runtime).
/// `flat_neighbors` is the concatenation of every source's neighbor slots;
/// `row_lens[i]` is source `i`'s slot count. Caller guarantees
/// `row_lens.len() <= seeds.len()`, `sum(row_lens) == flat_neighbors.len()`,
/// and every slot `< seeds.len()` (the pyfunction validates before calling).
fn ppr_iterate(
    seeds: &[bool],
    flat_neighbors: &[usize],
    row_lens: &[usize],
    iterations: i64,
    damping: f64,
    teleport: f64,
) -> Vec<f64> {
    let n_total = seeds.len();
    let n_sources = row_lens.len();
    let seed_rank: Vec<f64> = seeds.iter().map(|&s| if s { 1.0 } else { 0.0 }).collect();
    // Pure: `ranks = {node: seed for node in adjacency}` — sources only. An
    // external's slot holds a placeholder 0.0 that is never read as a source
    // (externals have no neighbor row) and never emitted while not present.
    let mut ranks: Vec<f64> = (0..n_total)
        .map(|i| if i < n_sources { seed_rank[i] } else { 0.0 })
        .collect();
    let mut present: Vec<bool> = (0..n_total).map(|i| i < n_sources).collect();
    for _ in 0..iterations {
        let mut next: Vec<f64> = (0..n_total)
            .map(|i| {
                if present[i] {
                    teleport * seed_rank[i]
                } else {
                    0.0
                }
            })
            .collect();
        let mut next_present = present.clone();
        let mut start = 0usize;
        for (source, &len) in row_lens.iter().enumerate() {
            let row = &flat_neighbors[start..start + len];
            start += len;
            if row.is_empty() {
                continue;
            }
            // `ranks.get(node, 0.0)`: sources are present from init, so the
            // default never fires — direct read, left-to-right op order.
            let share = damping * ranks[source] / (len as f64);
            for &neighbor in row {
                // f64 `+=` is the same single rounded add as `= next + share`.
                next[neighbor] += share;
                next_present[neighbor] = true;
            }
        }
        ranks = next;
        present = next_present;
    }
    ranks
}

/// Little-endian u64 buffer -> usize slots (8-byte loads on LE targets).
fn parse_le_u64(name: &str, buf: &[u8]) -> PyResult<Vec<usize>> {
    if buf.len() % 8 != 0 {
        return Err(PyValueError::new_err(format!(
            "ppr_power_iteration: {name} is {} bytes, not a multiple of 8",
            buf.len()
        )));
    }
    buf.chunks_exact(8)
        .map(|chunk| {
            let value = u64::from_le_bytes(chunk.try_into().expect("8-byte chunk"));
            usize::try_from(value).map_err(|_| {
                PyValueError::new_err(format!(
                    "ppr_power_iteration: {name} entry {value} exceeds usize"
                ))
            })
        })
        .collect()
}

/// Scores aligned 1:1 with the node universe behind `seeds` (the dispatch
/// zips them back onto its ordered node list with `strict=True`).
#[pyfunction]
pub fn ppr_power_iteration(
    py: Python<'_>,
    seeds: Vec<bool>,
    flat_neighbors_le: &[u8],
    row_lens_le: &[u8],
    iterations: i64,
    damping: f64,
    teleport: f64,
) -> PyResult<Vec<f64>> {
    let flat_neighbors = parse_le_u64("flat_neighbors_le", flat_neighbors_le)?;
    let row_lens = parse_le_u64("row_lens_le", row_lens_le)?;
    let n_total = seeds.len();
    if row_lens.len() > n_total {
        return Err(PyValueError::new_err(format!(
            "ppr_power_iteration: {} row lengths but only {n_total} seed flags \
             (sources must be the first slots of the node universe)",
            row_lens.len()
        )));
    }
    // checked sum: row lengths are caller-controlled, so the expected-length
    // arithmetic must not wrap (a wrapped total could make a malformed edge
    // buffer pass the consistency check). Overflow -> ValueError.
    let total: usize = row_lens.iter().try_fold(0usize, |acc, &len| {
        acc.checked_add(len).ok_or_else(|| {
            PyValueError::new_err("ppr_power_iteration: sum of row lengths overflows usize")
        })
    })?;
    if total != flat_neighbors.len() {
        return Err(PyValueError::new_err(format!(
            "ppr_power_iteration: row lengths sum to {total} but flat_neighbors_le \
             holds {} slots",
            flat_neighbors.len()
        )));
    }
    if let Some(&bad) = flat_neighbors.iter().find(|&&slot| slot >= n_total) {
        return Err(PyValueError::new_err(format!(
            "ppr_power_iteration: neighbor slot {bad} is out of range for a \
            {n_total}-node universe"
        )));
    }
    Ok(py.detach(move || {
        ppr_iterate(
            &seeds,
            &flat_neighbors,
            &row_lens,
            iterations,
            damping,
            teleport,
        )
    }))
}

#[cfg(test)]
mod tests {
    use super::ppr_iterate;

    #[test]
    fn empty_graph_returns_empty() {
        assert_eq!(
            ppr_iterate(&[], &[], &[], 12, 0.85, 0.15),
            Vec::<f64>::new()
        );
    }

    #[test]
    fn zero_iterations_returns_seed_init_for_sources() {
        let seeds = [true, false];
        assert_eq!(
            ppr_iterate(&seeds, &[1, 0], &[1, 1], 0, 0.85, 0.15),
            vec![1.0, 0.0]
        );
    }

    #[test]
    fn isolated_seed_node_holds_teleport_mass() {
        // One seed node with no outgoing edges: every iteration rewrites its
        // rank to teleport * 1.0 (mirrors {node: 0.15 for the seed} + no edges).
        assert_eq!(ppr_iterate(&[true], &[], &[0], 12, 0.85, 0.15), vec![0.15]);
    }

    #[test]
    fn external_neighbor_gets_no_teleport_on_first_iteration() {
        // Source 0 (seed) -> external slot 1 (also flagged seed). Iteration 1:
        // external starts from the .get default 0.0 (NOT teleport), receiving
        // only share = 0.85 * 1.0 / 1. From iteration 2 it is present and the
        // teleport * seed term applies. One iteration isolates the first case.
        let seeds = [true, true];
        let one = ppr_iterate(&seeds, &[1], &[1], 1, 0.85, 0.15);
        assert_eq!(one, vec![0.15, 0.85]);
        let two = ppr_iterate(&seeds, &[1], &[1], 2, 0.85, 0.15);
        // Source: teleport only (external has no out-edges). External:
        // teleport * 1.0 + 0.85 * ranks[0] / 1 with ranks[0] = 0.15.
        assert_eq!(two, vec![0.15, 0.15 + 0.85 * 0.15]);
    }

    #[test]
    fn duplicate_neighbors_accumulate_share_per_occurrence() {
        // Source 0 -> [1, 1]: len(neighbors) == 2, share added twice to slot 1
        // — exactly the pure loop over a list with duplicates.
        let got = ppr_iterate(&[true, false], &[1, 1], &[2, 0], 1, 0.85, 0.15);
        let share = 0.85 * 1.0 / 2.0;
        assert_eq!(got, vec![0.15, (0.0 + share) + share]);
    }

    #[test]
    fn self_loop_feeds_rank_back() {
        let got = ppr_iterate(&[true], &[0], &[1], 1, 0.85, 0.15);
        assert_eq!(got, vec![0.15 + 0.85 * 1.0 / 1.0]);
    }
}

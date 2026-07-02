//! Byte-parity native kernels for Mnemosyne.
//!
//! PARITY CONTRACT (plan Global Constraints): every function is bit-identical
//! to its pure-Python counterpart. Scalar sequential f64 per item; rayon only
//! ACROSS items; no mul_add, no transcendentals; allowed ops: + - * / sqrt abs.

use pyo3::prelude::*;

mod dense;
mod hashing;
mod lexical;
mod mmr;
mod tokenize;

#[pyfunction]
fn parity_marker() -> &'static str {
    "strict-ieee-scalar-v1"
}

#[pymodule]
fn mnemosyne_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_function(wrap_pyfunction!(parity_marker, m)?)?;
    m.add_function(wrap_pyfunction!(hashing::hashing_embedding, m)?)?;
    m.add_function(wrap_pyfunction!(tokenize::tokenize, m)?)?;
    m.add_function(wrap_pyfunction!(lexical::lexical_score, m)?)?;
    m.add_function(wrap_pyfunction!(lexical::lexical_scan, m)?)?;
    m.add_function(wrap_pyfunction!(lexical::_ln, m)?)?;
    m.add_function(wrap_pyfunction!(dense::cosine, m)?)?;
    m.add_function(wrap_pyfunction!(dense::dense_scan, m)?)?;
    m.add_function(wrap_pyfunction!(mmr::mmr_select_indices, m)?)?;
    Ok(())
}

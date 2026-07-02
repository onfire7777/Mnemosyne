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

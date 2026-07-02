//! Bit-identical port of `mnemosyne.text._hashing_embedding_cached`
//! (the uncached pure function; parity note 4).
//!
//! blake2b digest_size=8 lives IN THE PARAMETER BLOCK (`Blake2bVar::new(8)`),
//! NOT a truncation of the 64-byte digest — golden-verified against
//! `hashlib.blake2b(token, digest_size=8)`. Bucket = first 4 digest bytes
//! big-endian % dims; sign from digest[4] parity; accumulate in token order;
//! sequential sum-of-squares norm; norm == 0.0 returns the vector unnormalized.

use blake2::digest::{Update, VariableOutput};
use blake2::Blake2bVar;
use pyo3::prelude::*;

use crate::tokenize::tokenize_str;

#[pyfunction]
pub fn hashing_embedding(text: &str, dims: usize) -> Vec<f64> {
    let mut vec = vec![0.0f64; dims];
    for token in tokenize_str(text) {
        let mut hasher = Blake2bVar::new(8).expect("digest size 8 is valid");
        hasher.update(token.as_bytes());
        let mut digest = [0u8; 8];
        hasher.finalize_variable(&mut digest).expect("finalize");
        let bucket = (u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]])
            as usize)
            % dims;
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

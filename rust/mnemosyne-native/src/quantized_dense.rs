//! High-throughput SIMD/NEON quantized & f16/f32 dense vector kernels.
//!
//! Kept strictly separate from `dense.rs` (which preserves bit-identical
//! CPython-3.12 Neumaier f64 parity). These kernels power:
//! - `dense_scan_f32_packed`: NEON/SIMD f32 dot-product scan with rayon.
//! - `dense_scan_f16_packed`: IEEE-754 half-precision f16 decode + dot-product scan.
//! - `NativeQuantizedIndex`: 3-stage binary (u64 POPCNT) -> symmetric int8
//!   (NEON widening i32 MAC) -> exact f32 NEON rescoring with zero per-query
//!   buffer copies.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

// ---------------------------------------------------------------------------
// Low-level SIMD / portable dot-product kernels
// ---------------------------------------------------------------------------

#[cfg(any(not(target_arch = "aarch64"), test))]
#[inline]
fn dot_f32_scalar(a: &[f32], b: &[f32]) -> f32 {
    let n = a.len().min(b.len());
    let mut s0 = 0.0f32;
    let mut s1 = 0.0f32;
    let mut s2 = 0.0f32;
    let mut s3 = 0.0f32;
    let mut i = 0;
    while i + 4 <= n {
        s0 += a[i] * b[i];
        s1 += a[i + 1] * b[i + 1];
        s2 += a[i + 2] * b[i + 2];
        s3 += a[i + 3] * b[i + 3];
        i += 4;
    }
    let mut sum = (s0 + s1) + (s2 + s3);
    while i < n {
        sum += a[i] * b[i];
        i += 1;
    }
    sum
}

#[cfg(target_arch = "aarch64")]
#[inline]
fn dot_f32(a: &[f32], b: &[f32]) -> f32 {
    use std::arch::aarch64::*;
    let n = a.len().min(b.len());
    // SAFETY: aarch64 always supports baseline NEON; bounds checked via `i + 16 <= n` / `i + 4 <= n`.
    unsafe {
        let mut acc0 = vdupq_n_f32(0.0);
        let mut acc1 = vdupq_n_f32(0.0);
        let mut acc2 = vdupq_n_f32(0.0);
        let mut acc3 = vdupq_n_f32(0.0);
        let pa = a.as_ptr();
        let pb = b.as_ptr();
        let mut i = 0usize;
        while i + 16 <= n {
            acc0 = vfmaq_f32(acc0, vld1q_f32(pa.add(i)), vld1q_f32(pb.add(i)));
            acc1 = vfmaq_f32(acc1, vld1q_f32(pa.add(i + 4)), vld1q_f32(pb.add(i + 4)));
            acc2 = vfmaq_f32(acc2, vld1q_f32(pa.add(i + 8)), vld1q_f32(pb.add(i + 8)));
            acc3 = vfmaq_f32(acc3, vld1q_f32(pa.add(i + 12)), vld1q_f32(pb.add(i + 12)));
            i += 16;
        }
        while i + 4 <= n {
            acc0 = vfmaq_f32(acc0, vld1q_f32(pa.add(i)), vld1q_f32(pb.add(i)));
            i += 4;
        }
        let sum_vec = vaddq_f32(vaddq_f32(acc0, acc1), vaddq_f32(acc2, acc3));
        let mut sum = vaddvq_f32(sum_vec);
        while i < n {
            sum += *pa.add(i) * *pb.add(i);
            i += 1;
        }
        sum
    }
}

#[cfg(not(target_arch = "aarch64"))]
#[inline]
fn dot_f32(a: &[f32], b: &[f32]) -> f32 {
    dot_f32_scalar(a, b)
}

#[inline]
fn dot_f32_le_bytes(query: &[f32], row_bytes: &[u8]) -> f32 {
    let n = query.len();
    // On little-endian targets where row_bytes is 4-byte aligned, borrow directly as &[f32].
    #[cfg(target_endian = "little")]
    {
        if (row_bytes.as_ptr() as usize) % std::mem::align_of::<f32>() == 0 {
            // SAFETY: alignment checked, length == n * 4, little-endian f32 representation.
            let slice = unsafe { std::slice::from_raw_parts(row_bytes.as_ptr() as *const f32, n) };
            return dot_f32(query, slice);
        }
    }
    let mut s0 = 0.0f32;
    let mut s1 = 0.0f32;
    let mut s2 = 0.0f32;
    let mut s3 = 0.0f32;
    let mut i = 0usize;
    while i + 4 <= n {
        let b0 = i * 4;
        let v0 = f32::from_le_bytes([
            row_bytes[b0],
            row_bytes[b0 + 1],
            row_bytes[b0 + 2],
            row_bytes[b0 + 3],
        ]);
        let v1 = f32::from_le_bytes([
            row_bytes[b0 + 4],
            row_bytes[b0 + 5],
            row_bytes[b0 + 6],
            row_bytes[b0 + 7],
        ]);
        let v2 = f32::from_le_bytes([
            row_bytes[b0 + 8],
            row_bytes[b0 + 9],
            row_bytes[b0 + 10],
            row_bytes[b0 + 11],
        ]);
        let v3 = f32::from_le_bytes([
            row_bytes[b0 + 12],
            row_bytes[b0 + 13],
            row_bytes[b0 + 14],
            row_bytes[b0 + 15],
        ]);
        s0 += query[i] * v0;
        s1 += query[i + 1] * v1;
        s2 += query[i + 2] * v2;
        s3 += query[i + 3] * v3;
        i += 4;
    }
    let mut sum = (s0 + s1) + (s2 + s3);
    while i < n {
        let b0 = i * 4;
        let v = f32::from_le_bytes([
            row_bytes[b0],
            row_bytes[b0 + 1],
            row_bytes[b0 + 2],
            row_bytes[b0 + 3],
        ]);
        sum += query[i] * v;
        i += 1;
    }
    sum
}

/// Exact IEEE-754 binary16 (half) -> binary32 (f32) bit conversion.
#[inline]
pub(crate) fn f16_bits_to_f32(bits: u16) -> f32 {
    let sign = ((bits & 0x8000) as u32) << 16;
    let exp = ((bits >> 10) & 0x1F) as u32;
    let mant = (bits & 0x03FF) as u32;
    let out_bits = if exp == 0 {
        if mant == 0 {
            sign
        } else {
            // Subnormal half-precision value: normalize into f32.
            let mut m = mant;
            let mut e: i32 = -14;
            while (m & 0x0400) == 0 {
                m <<= 1;
                e -= 1;
            }
            m &= 0x03FF;
            sign | (((e + 127) as u32) << 23) | (m << 13)
        }
    } else if exp == 0x1F {
        // Inf or NaN.
        sign | 0x7F80_0000 | (mant << 13)
    } else {
        sign | ((exp + 112) << 23) | (mant << 13)
    };
    f32::from_bits(out_bits)
}

#[inline]
fn dot_f16_le_bytes(query: &[f32], row_f16: &[u8]) -> f32 {
    let n = query.len();
    let mut s0 = 0.0f32;
    let mut s1 = 0.0f32;
    let mut s2 = 0.0f32;
    let mut s3 = 0.0f32;
    let mut i = 0usize;
    while i + 4 <= n {
        let b = i * 2;
        let v0 = f16_bits_to_f32(u16::from_le_bytes([row_f16[b], row_f16[b + 1]]));
        let v1 = f16_bits_to_f32(u16::from_le_bytes([row_f16[b + 2], row_f16[b + 3]]));
        let v2 = f16_bits_to_f32(u16::from_le_bytes([row_f16[b + 4], row_f16[b + 5]]));
        let v3 = f16_bits_to_f32(u16::from_le_bytes([row_f16[b + 6], row_f16[b + 7]]));
        s0 += query[i] * v0;
        s1 += query[i + 1] * v1;
        s2 += query[i + 2] * v2;
        s3 += query[i + 3] * v3;
        i += 4;
    }
    let mut sum = (s0 + s1) + (s2 + s3);
    while i < n {
        let b = i * 2;
        let v = f16_bits_to_f32(u16::from_le_bytes([row_f16[b], row_f16[b + 1]]));
        sum += query[i] * v;
        i += 1;
    }
    sum
}

#[cfg(target_arch = "aarch64")]
#[inline]
fn dot_i8(a: &[i8], b: &[i8]) -> i32 {
    use std::arch::aarch64::*;
    let n = a.len().min(b.len());
    // SAFETY: baseline aarch64 NEON; loop bounds checked via `i + 16 <= n`.
    unsafe {
        let pa = a.as_ptr();
        let pb = b.as_ptr();
        let mut acc0 = vdupq_n_s32(0);
        let mut acc1 = vdupq_n_s32(0);
        let mut i = 0usize;
        while i + 16 <= n {
            let va = vld1q_s8(pa.add(i));
            let vb = vld1q_s8(pb.add(i));
            let a_lo = vmovl_s8(vget_low_s8(va));
            let b_lo = vmovl_s8(vget_low_s8(vb));
            let a_hi = vmovl_s8(vget_high_s8(va));
            let b_hi = vmovl_s8(vget_high_s8(vb));
            acc0 = vmlal_s16(acc0, vget_low_s16(a_lo), vget_low_s16(b_lo));
            acc1 = vmlal_s16(acc1, vget_high_s16(a_lo), vget_high_s16(b_lo));
            acc0 = vmlal_s16(acc0, vget_low_s16(a_hi), vget_low_s16(b_hi));
            acc1 = vmlal_s16(acc1, vget_high_s16(a_hi), vget_high_s16(b_hi));
            i += 16;
        }
        let mut sum = vaddvq_s32(vaddq_s32(acc0, acc1));
        while i < n {
            sum += (*pa.add(i) as i32) * (*pb.add(i) as i32);
            i += 1;
        }
        sum
    }
}

#[cfg(not(target_arch = "aarch64"))]
#[inline]
fn dot_i8(a: &[i8], b: &[i8]) -> i32 {
    let n = a.len().min(b.len());
    let mut s0 = 0i32;
    let mut s1 = 0i32;
    let mut s2 = 0i32;
    let mut s3 = 0i32;
    let mut i = 0usize;
    while i + 4 <= n {
        s0 += (a[i] as i32) * (b[i] as i32);
        s1 += (a[i + 1] as i32) * (b[i + 1] as i32);
        s2 += (a[i + 2] as i32) * (b[i + 2] as i32);
        s3 += (a[i + 3] as i32) * (b[i + 3] as i32);
        i += 4;
    }
    let mut sum = (s0 + s1) + (s2 + s3);
    while i < n {
        sum += (a[i] as i32) * (b[i] as i32);
        i += 1;
    }
    sum
}

#[inline]
fn hamming_u64(a: &[u64], b: &[u64]) -> u32 {
    let mut d = 0u32;
    for (&x, &y) in a.iter().zip(b.iter()) {
        d += (x ^ y).count_ones();
    }
    d
}

/// Pack MSB-first byte-packed sign bits (`np.packbits(..., axis=1)` layout) into `u64` words.
fn pack_row_bytes_to_u64(row_bytes: &[u8], out_words: &mut [u64]) {
    let mut wi = 0usize;
    let mut bi = 0usize;
    while bi + 8 <= row_bytes.len() {
        out_words[wi] = u64::from_le_bytes([
            row_bytes[bi],
            row_bytes[bi + 1],
            row_bytes[bi + 2],
            row_bytes[bi + 3],
            row_bytes[bi + 4],
            row_bytes[bi + 5],
            row_bytes[bi + 6],
            row_bytes[bi + 7],
        ]);
        wi += 1;
        bi += 8;
    }
    if bi < row_bytes.len() {
        let mut tail = [0u8; 8];
        let rem = row_bytes.len() - bi;
        tail[..rem].copy_from_slice(&row_bytes[bi..]);
        out_words[wi] = u64::from_le_bytes(tail);
    }
}

/// Pack sign bits (`v > 0.0`) of an f32 vector in `np.packbits` MSB-first layout into `u64` words.
fn pack_f32_sign_bits_u64(vec: &[f32], bin_u64_stride: usize) -> Vec<u64> {
    let byte_width = vec.len().div_ceil(8);
    let mut tmp = vec![0u8; byte_width];
    for (i, &v) in vec.iter().enumerate() {
        if v > 0.0 {
            tmp[i >> 3] |= 1u8 << (7 - (i & 7));
        }
    }
    let mut words = vec![0u64; bin_u64_stride];
    pack_row_bytes_to_u64(&tmp, &mut words);
    words
}

// ---------------------------------------------------------------------------
// Packed f32 & f16 dense scan functions
// ---------------------------------------------------------------------------

#[pyfunction]
pub fn dense_scan_f32_packed(
    py: Python<'_>,
    query: &[u8],
    rows: &[u8],
    dims: usize,
    row_mask: &[u8],
) -> PyResult<Vec<Option<f32>>> {
    let row_bytes = dims
        .checked_mul(4)
        .ok_or_else(|| PyValueError::new_err(format!("dims*4 overflows usize (dims = {dims})")))?;
    if query.len() != row_bytes {
        return Err(PyValueError::new_err(format!(
            "query is {} bytes, expected dims*4 = {row_bytes}",
            query.len()
        )));
    }
    let n = row_mask.len();
    let expected_rows_len = n.checked_mul(row_bytes).ok_or_else(|| {
        PyValueError::new_err(format!("n*dims*4 overflows usize (n = {n}, dims = {dims})"))
    })?;
    if rows.len() != expected_rows_len {
        return Err(PyValueError::new_err(format!(
            "rows is {} bytes, expected n*dims*4 = {expected_rows_len}",
            rows.len()
        )));
    }
    let query_vec: Vec<f32> = query
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes(c.try_into().expect("4-byte chunk")))
        .collect();
    Ok(py.detach(|| {
        if n >= 256 {
            (0..n)
                .into_par_iter()
                .map(|i| {
                    if row_mask[i] == 0 {
                        None
                    } else {
                        Some(dot_f32_le_bytes(
                            &query_vec,
                            &rows[i * row_bytes..(i + 1) * row_bytes],
                        ))
                    }
                })
                .collect()
        } else {
            (0..n)
                .map(|i| {
                    if row_mask[i] == 0 {
                        None
                    } else {
                        Some(dot_f32_le_bytes(
                            &query_vec,
                            &rows[i * row_bytes..(i + 1) * row_bytes],
                        ))
                    }
                })
                .collect()
        }
    }))
}

#[pyfunction]
pub fn dense_scan_f16_packed(
    py: Python<'_>,
    query_f32: &[u8],
    rows_f16: &[u8],
    dims: usize,
    row_mask: &[u8],
) -> PyResult<Vec<Option<f32>>> {
    let q_bytes = dims
        .checked_mul(4)
        .ok_or_else(|| PyValueError::new_err(format!("dims*4 overflows usize (dims = {dims})")))?;
    let row_bytes = dims
        .checked_mul(2)
        .ok_or_else(|| PyValueError::new_err(format!("dims*2 overflows usize (dims = {dims})")))?;
    if query_f32.len() != q_bytes {
        return Err(PyValueError::new_err(format!(
            "query_f32 is {} bytes, expected dims*4 = {q_bytes}",
            query_f32.len()
        )));
    }
    let n = row_mask.len();
    let expected_rows_len = n.checked_mul(row_bytes).ok_or_else(|| {
        PyValueError::new_err(format!("n*dims*2 overflows usize (n = {n}, dims = {dims})"))
    })?;
    if rows_f16.len() != expected_rows_len {
        return Err(PyValueError::new_err(format!(
            "rows_f16 is {} bytes, expected n*dims*2 = {expected_rows_len}",
            rows_f16.len()
        )));
    }
    let query_vec: Vec<f32> = query_f32
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes(c.try_into().expect("4-byte chunk")))
        .collect();
    Ok(py.detach(|| {
        if n >= 256 {
            (0..n)
                .into_par_iter()
                .map(|i| {
                    if row_mask[i] == 0 {
                        None
                    } else {
                        Some(dot_f16_le_bytes(
                            &query_vec,
                            &rows_f16[i * row_bytes..(i + 1) * row_bytes],
                        ))
                    }
                })
                .collect()
        } else {
            (0..n)
                .map(|i| {
                    if row_mask[i] == 0 {
                        None
                    } else {
                        Some(dot_f16_le_bytes(
                            &query_vec,
                            &rows_f16[i * row_bytes..(i + 1) * row_bytes],
                        ))
                    }
                })
                .collect()
        }
    }))
}

// ---------------------------------------------------------------------------
// NativeQuantizedIndex — zero-per-query-copy 3-stage binary -> int8 -> f32
// ---------------------------------------------------------------------------

#[pyclass]
pub struct NativeQuantizedIndex {
    dims: usize,
    bin_u64_stride: usize,
    n_rows: usize,
    binary_u64: Vec<u64>,
    int8_rows: Vec<i8>,
    scales: Vec<f32>,
    f32_rows: Vec<f32>,
}

#[pymethods]
impl NativeQuantizedIndex {
    #[staticmethod]
    pub fn from_packed_buffers(
        dims: usize,
        n_rows: usize,
        binary_u8: &[u8],
        int8_u8: &[u8],
        scales_f32: &[u8],
        f32_bytes: &[u8],
    ) -> PyResult<Self> {
        if dims == 0 {
            return Err(PyValueError::new_err("dims must be positive"));
        }
        let bin_byte_width = dims.div_ceil(8);
        let bin_u64_stride = dims.div_ceil(64);
        let expected_bin = n_rows
            .checked_mul(bin_byte_width)
            .ok_or_else(|| PyValueError::new_err("binary size overflow"))?;
        let expected_i8 = n_rows
            .checked_mul(dims)
            .ok_or_else(|| PyValueError::new_err("int8 size overflow"))?;
        let expected_scales = n_rows
            .checked_mul(4)
            .ok_or_else(|| PyValueError::new_err("scales size overflow"))?;
        let expected_f32 = expected_i8
            .checked_mul(4)
            .ok_or_else(|| PyValueError::new_err("f32 size overflow"))?;

        if binary_u8.len() != expected_bin {
            return Err(PyValueError::new_err(format!(
                "binary_u8 length {} != expected {}",
                binary_u8.len(),
                expected_bin
            )));
        }
        if int8_u8.len() != expected_i8 {
            return Err(PyValueError::new_err(format!(
                "int8_u8 length {} != expected {}",
                int8_u8.len(),
                expected_i8
            )));
        }
        if scales_f32.len() != expected_scales {
            return Err(PyValueError::new_err(format!(
                "scales_f32 length {} != expected {}",
                scales_f32.len(),
                expected_scales
            )));
        }
        if f32_bytes.len() != expected_f32 {
            return Err(PyValueError::new_err(format!(
                "f32_bytes length {} != expected {}",
                f32_bytes.len(),
                expected_f32
            )));
        }

        let mut binary_u64 = vec![0u64; n_rows * bin_u64_stride];
        for row in 0..n_rows {
            let src = &binary_u8[row * bin_byte_width..(row + 1) * bin_byte_width];
            let dst = &mut binary_u64[row * bin_u64_stride..(row + 1) * bin_u64_stride];
            pack_row_bytes_to_u64(src, dst);
        }

        let int8_rows: Vec<i8> = int8_u8.iter().map(|&b| b as i8).collect();
        let scales: Vec<f32> = scales_f32
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes(c.try_into().expect("4-byte chunk")))
            .collect();
        let f32_rows: Vec<f32> = f32_bytes
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes(c.try_into().expect("4-byte chunk")))
            .collect();

        Ok(Self {
            dims,
            bin_u64_stride,
            n_rows,
            binary_u64,
            int8_rows,
            scales,
            f32_rows,
        })
    }

    pub fn len(&self) -> usize {
        self.n_rows
    }

    /// Execute exact, int8_rescore, or binary_int8_rescore search returning
    /// `(row_idx, score)` sorted descending by score (ties broken by row_idx).
    #[pyo3(signature = (query_f32, k, mode, allowed_indices, min_score, binary_budget, int8_budget))]
    #[allow(clippy::too_many_arguments)]
    pub fn search(
        &self,
        py: Python<'_>,
        query_f32: &[u8],
        k: usize,
        mode: &str,
        allowed_indices: Option<Vec<usize>>,
        min_score: f32,
        binary_budget: usize,
        int8_budget: usize,
    ) -> PyResult<Vec<(usize, f32)>> {
        if k == 0 || self.n_rows == 0 {
            return Ok(Vec::new());
        }
        let expected_q = self.dims * 4;
        if query_f32.len() != expected_q {
            return Err(PyValueError::new_err(format!(
                "query_f32 length {} != expected {}",
                query_f32.len(),
                expected_q
            )));
        }
        let q: Vec<f32> = query_f32
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes(c.try_into().expect("4-byte chunk")))
            .collect();
        let dims = self.dims;
        let stride = self.bin_u64_stride;
        let n_rows = self.n_rows;

        Ok(py.detach(|| {
            // Optional restricted candidate pool
            let mut pool: Option<Vec<usize>> = allowed_indices.map(|mut idxs| {
                idxs.retain(|&i| i < n_rows);
                idxs
            });
            let mut active_n = pool.as_ref().map_or(n_rows, |p| p.len());
            if active_n == 0 {
                return Vec::new();
            }

            // Stage 1: 1-bit Binary Hamming prefilter (u64 POPCNT)
            if mode == "binary_int8_rescore" {
                let budget = binary_budget.min(active_n);
                if budget < active_n && budget > 0 {
                    let q_words = pack_f32_sign_bits_u64(&q, stride);
                    let mut dists: Vec<(u32, usize)> = match &pool {
                        None => {
                            if active_n >= 2048 {
                                (0..n_rows)
                                    .into_par_iter()
                                    .map(|i| {
                                        let row = &self.binary_u64[i * stride..(i + 1) * stride];
                                        (hamming_u64(row, &q_words), i)
                                    })
                                    .collect()
                            } else {
                                (0..n_rows)
                                    .map(|i| {
                                        let row = &self.binary_u64[i * stride..(i + 1) * stride];
                                        (hamming_u64(row, &q_words), i)
                                    })
                                    .collect()
                            }
                        }
                        Some(indices) => {
                            if active_n >= 2048 {
                                indices
                                    .par_iter()
                                    .map(|&i| {
                                        let row = &self.binary_u64[i * stride..(i + 1) * stride];
                                        (hamming_u64(row, &q_words), i)
                                    })
                                    .collect()
                            } else {
                                indices
                                    .iter()
                                    .map(|&i| {
                                        let row = &self.binary_u64[i * stride..(i + 1) * stride];
                                        (hamming_u64(row, &q_words), i)
                                    })
                                    .collect()
                            }
                        }
                    };
                    dists.select_nth_unstable_by(budget - 1, |a, b| a.0.cmp(&b.0).then(a.1.cmp(&b.1)));
                    dists.truncate(budget);
                    pool = Some(dists.into_iter().map(|(_, idx)| idx).collect());
                    active_n = budget;
                }
            }

            // Stage 2: Symmetric int8 dot-product shortlist (NEON widening i32 MAC)
            if mode == "int8_rescore" || mode == "binary_int8_rescore" {
                let budget = int8_budget.min(active_n);
                if budget < active_n && budget > 0 {
                    let q_max = q.iter().fold(0.0f32, |acc, &v| acc.max(v.abs()));
                    let q_scale = if q_max > 1e-8 {
                        q_max / 127.0
                    } else {
                        1.0 / 127.0
                    };
                    let inv_q_scale = 1.0 / q_scale;
                    let q_i8: Vec<i8> = q
                        .iter()
                        .map(|&v| (v * inv_q_scale).round().clamp(-127.0, 127.0) as i8)
                        .collect();

                    let mut approx: Vec<(f32, usize)> = match &pool {
                        None => {
                            if active_n >= 512 {
                                (0..n_rows)
                                    .into_par_iter()
                                    .map(|i| {
                                        let row = &self.int8_rows[i * dims..(i + 1) * dims];
                                        let dot = dot_i8(row, &q_i8) as f32;
                                        (dot * (self.scales[i] * q_scale), i)
                                    })
                                    .collect()
                            } else {
                                (0..n_rows)
                                    .map(|i| {
                                        let row = &self.int8_rows[i * dims..(i + 1) * dims];
                                        let dot = dot_i8(row, &q_i8) as f32;
                                        (dot * (self.scales[i] * q_scale), i)
                                    })
                                    .collect()
                            }
                        }
                        Some(indices) => {
                            if active_n >= 512 {
                                indices
                                    .par_iter()
                                    .map(|&i| {
                                        let row = &self.int8_rows[i * dims..(i + 1) * dims];
                                        let dot = dot_i8(row, &q_i8) as f32;
                                        (dot * (self.scales[i] * q_scale), i)
                                    })
                                    .collect()
                            } else {
                                indices
                                    .iter()
                                    .map(|&i| {
                                        let row = &self.int8_rows[i * dims..(i + 1) * dims];
                                        let dot = dot_i8(row, &q_i8) as f32;
                                        (dot * (self.scales[i] * q_scale), i)
                                    })
                                    .collect()
                            }
                        }
                    };
                    approx.select_nth_unstable_by(budget - 1, |a, b| {
                        b.0.total_cmp(&a.0).then(a.1.cmp(&b.1))
                    });
                    approx.truncate(budget);
                    pool = Some(approx.into_iter().map(|(_, idx)| idx).collect());
                    active_n = budget;
                }
            }

            // Stage 3: Exact f32 cosine rescoring over shortlist (NEON f32 FMA)
            let mut scored: Vec<(usize, f32)> = match &pool {
                None => {
                    if active_n >= 512 {
                        (0..n_rows)
                            .into_par_iter()
                            .filter_map(|i| {
                                let row = &self.f32_rows[i * dims..(i + 1) * dims];
                                let s = dot_f32(&q, row);
                                (s > min_score).then_some((i, s))
                            })
                            .collect()
                    } else {
                        (0..n_rows)
                            .filter_map(|i| {
                                let row = &self.f32_rows[i * dims..(i + 1) * dims];
                                let s = dot_f32(&q, row);
                                (s > min_score).then_some((i, s))
                            })
                            .collect()
                    }
                }
                Some(indices) => {
                    if active_n >= 512 {
                        indices
                            .par_iter()
                            .filter_map(|&i| {
                                let row = &self.f32_rows[i * dims..(i + 1) * dims];
                                let s = dot_f32(&q, row);
                                (s > min_score).then_some((i, s))
                            })
                            .collect()
                    } else {
                        indices
                            .iter()
                            .filter_map(|&i| {
                                let row = &self.f32_rows[i * dims..(i + 1) * dims];
                                let s = dot_f32(&q, row);
                                (s > min_score).then_some((i, s))
                            })
                            .collect()
                    }
                }
            };

            if scored.len() > k {
                scored.select_nth_unstable_by(k - 1, |a, b| {
                    b.1.total_cmp(&a.1).then(a.0.cmp(&b.0))
                });
                let cutoff = scored[k - 1].1;
                // Keep any exact-score ties at the boundary so Python can break ties by ID.
                let mut kept: Vec<(usize, f32)> = scored
                    .into_iter()
                    .filter(|&(_, s)| s >= cutoff)
                    .collect();
                kept.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
                kept
            } else {
                scored.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
                scored
            }
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn f16_roundtrip_special_and_normal_values() {
        assert_eq!(f16_bits_to_f32(0x0000), 0.0);
        assert_eq!(f16_bits_to_f32(0x3C00), 1.0);
        assert_eq!(f16_bits_to_f32(0xBC00), -1.0);
        assert_eq!(f16_bits_to_f32(0x3800), 0.5);
        assert_eq!(f16_bits_to_f32(0x3400), 0.25);
        assert!(f16_bits_to_f32(0x7C00).is_infinite());
        assert!(f16_bits_to_f32(0x7E00).is_nan());
        // Smallest positive subnormal: 2^-24
        assert!((f16_bits_to_f32(0x0001) - 2.0f32.powi(-24)).abs() < 1e-12);
    }

    #[test]
    fn dot_f32_matches_scalar() {
        let a: Vec<f32> = (0..389).map(|i| ((i as f32) * 0.013).sin()).collect();
        let b: Vec<f32> = (0..389).map(|i| ((i as f32) * 0.017).cos()).collect();
        let fast = dot_f32(&a, &b);
        let scalar = dot_f32_scalar(&a, &b);
        assert!((fast - scalar).abs() < 1e-4, "fast={fast} scalar={scalar}");
    }

    #[test]
    fn dot_i8_matches_scalar() {
        let a: Vec<i8> = (0..389).map(|i| ((i * 37) % 251) as i8).collect();
        let b: Vec<i8> = (0..389).map(|i| ((i * 53) % 251) as i8).collect();
        let expected: i32 = a.iter().zip(b.iter()).map(|(&x, &y)| (x as i32) * (y as i32)).sum();
        assert_eq!(dot_i8(&a, &b), expected);
    }
}

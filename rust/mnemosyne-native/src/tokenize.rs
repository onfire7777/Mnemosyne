//! Bit-identical port of `mnemosyne.text.tokenize` (parity note 3).
//!
//! The regex character classes are ASCII-only, so Python's `str.lower()` on a
//! matched span equals `to_ascii_lowercase()`, and the order is preserved
//! exactly as in the pure path: match -> lower -> strip("./:+-") -> drop empty.

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

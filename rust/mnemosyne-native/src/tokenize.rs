//! Bit-identical port of `mnemosyne.text.tokenize` (parity note 3).
//!
//! The pure pattern's character classes are ASCII-only, so Python's
//! `str.lower()` on a matched span equals `to_ascii_lowercase()`, and the
//! order is preserved exactly as in the pure path:
//! match -> lower -> strip("./:+-") -> drop empty. The matcher itself is a
//! hand-rolled maximal-ASCII-run scanner (see `for_each_token`) — for this
//! single-byte-class pattern it is exactly the regex's greedy leftmost
//! semantics, without per-match regex-engine overhead.

use pyo3::prelude::*;

/// `[A-Za-z0-9_]` — the token-START class of the pure pattern.
#[inline]
fn is_start(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_'
}

/// `[A-Za-z0-9_:+./-]` — the token-CONTINUATION class of the pure pattern.
#[inline]
fn is_cont(b: u8) -> bool {
    is_start(b) || matches!(b, b':' | b'+' | b'.' | b'/' | b'-')
}

/// Zero-allocation token visitor: yields each token as a `&str` view into a
/// reusable lowercase buffer. Byte-identical to the pure
/// `re.findall(r"[A-Za-z0-9_][A-Za-z0-9_:+./-]*")` stream:
///
/// * both character classes are ASCII-only, so a maximal byte run starting at
///   an `is_start` byte and continuing over `is_cont` bytes is exactly one
///   greedy leftmost match (UTF-8 continuation bytes are >= 0x80 and never in
///   either class, so bytewise scanning cannot split a multi-byte char, and a
///   byte following an ASCII byte is always a char boundary);
/// * the trim set ('.', '/', ':', '+', '-') is untouched by ASCII lowercasing
///   and the span is all-ASCII, so trimming the raw span FIRST and lowercasing
///   the trimmed span equals `lower(match).strip("./:+-")`.
///
/// Proven by the tokenize parity tests (hypothesis over full unicode text +
/// goldens), which run `tokenize_str` (built on this visitor) against the
/// pure path.
pub fn for_each_token(text: &str, mut f: impl FnMut(&str)) {
    let bytes = text.as_bytes();
    let mut buf = String::new();
    let mut i = 0;
    while i < bytes.len() {
        if !is_start(bytes[i]) {
            i += 1;
            continue;
        }
        let start = i;
        i += 1;
        while i < bytes.len() && is_cont(bytes[i]) {
            i += 1;
        }
        let trimmed = text[start..i].trim_matches(|c| matches!(c, '.' | '/' | ':' | '+' | '-'));
        if trimmed.is_empty() {
            continue;
        }
        buf.clear();
        buf.push_str(trimmed);
        buf.make_ascii_lowercase();
        f(&buf);
    }
}

pub fn tokenize_str(text: &str) -> Vec<String> {
    let mut tokens = Vec::new();
    for_each_token(text, |token| tokens.push(token.to_owned()));
    tokens
}

#[pyfunction]
pub fn tokenize(text: &str) -> Vec<String> {
    tokenize_str(text)
}

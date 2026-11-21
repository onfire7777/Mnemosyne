//! Rayon-parallel Rust `PassageIndex` (multi-granularity BM25 + binary sidecar).
//!
//! Matches `mnemosyne.passages.PassageIndex` scoring, stemming, subpassage
//! extraction (speaker rounds/turns, paragraphs, 3-sentence sliding windows),
//! and incremental `add_text` semantics while running cold builds in parallel
//! across cores and persisting a compact binary sidecar (`MNPB` v1) verified by
//! per-document `(session_id, blake2b-128)` digests on reload.

use std::collections::HashMap;
use std::io::Cursor;

use blake2::digest::consts::U16;
use blake2::{Blake2b, Digest};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use rayon::prelude::*;

use crate::tokenize::for_each_term;

type Blake2b128 = Blake2b<U16>;

const SIDECAR_MAGIC: &[u8; 4] = b"MNPB";
const SIDECAR_VERSION: u32 = 1;

// ---------------------------------------------------------------------------
// Digest & Unicode-aware tokenizer (parity with mnemosyne.text._tokenize_pure)
// ---------------------------------------------------------------------------

#[inline]
fn digest_text(text: &str) -> [u8; 16] {
    let mut hasher = Blake2b128::new();
    hasher.update(text.as_bytes());
    let res = hasher.finalize();
    let mut out = [0u8; 16];
    out.copy_from_slice(&res);
    out
}

#[inline]
fn is_cjk_char(c: char) -> bool {
    let cp = c as u32;
    matches!(
        cp,
        0x3040..=0x30FF
            | 0x3400..=0x4DBF
            | 0x4E00..=0x9FFF
            | 0xAC00..=0xD7AF
            | 0xF900..=0xFAFF
    )
}

#[inline]
fn is_word_char(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

#[inline]
fn is_cont_char(c: char) -> bool {
    (is_word_char(c) && !is_cjk_char(c)) || matches!(c, ':' | '+' | '.' | '/' | '-')
}

/// Token stream matching `mnemosyne.text.tokenize`:
/// - ASCII fast path delegates to `crate::tokenize::for_each_term`.
/// - Non-ASCII path mirrors `_UNICODE_TOKEN_RE` (expecting Latin accents to
///   already be casefolded/stripped by caller when needed).
fn for_each_term_any(text: &str, mut f: impl FnMut(&str)) {
    if text.is_ascii() {
        for_each_term(text, f);
        return;
    }
    let mut chars = text.char_indices().peekable();
    let mut buf = String::new();
    while let Some((start, ch)) = chars.next() {
        if !is_word_char(ch) {
            continue;
        }
        if is_cjk_char(ch) {
            buf.clear();
            for lc in ch.to_lowercase() {
                buf.push(lc);
            }
            if !buf.is_empty() {
                f(&buf);
            }
            continue;
        }
        let mut end = start + ch.len_utf8();
        while let Some(&(next_idx, next_ch)) = chars.peek() {
            if is_cont_char(next_ch) {
                end = next_idx + next_ch.len_utf8();
                chars.next();
            } else {
                break;
            }
        }
        let trimmed = text[start..end].trim_matches(|c| matches!(c, '.' | '/' | ':' | '+' | '-'));
        if trimmed.is_empty() {
            continue;
        }
        buf.clear();
        for c in trimmed.chars() {
            for lc in c.to_lowercase() {
                buf.push(lc);
            }
        }
        if buf.is_empty() {
            continue;
        }
        f(&buf);
        if buf.contains('-') {
            let owned = buf.clone();
            for part in owned.split('-') {
                let cleaned = part.trim_matches(|c| matches!(c, '.' | '/' | ':' | '+' | '-'));
                if !cleaned.is_empty() && cleaned != owned {
                    f(cleaned);
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Passage stemmer — exact port of normalise_query_term + _stem_passage_token
// ---------------------------------------------------------------------------

#[inline]
fn ends_with_protected_s(t: &str) -> bool {
    t.ends_with("ss")
        || t.ends_with("us")
        || t.ends_with("is")
        || t.ends_with("as")
        || t.ends_with("os")
        || t.ends_with("yes")
        || t.ends_with("was")
        || t.ends_with("has")
        || t.ends_with("his")
}

#[inline]
fn normalise_query_term_rust(tok: &str) -> String {
    match tok {
        "owned" | "owning" | "owns" => return "own".to_owned(),
        "notifications" | "notification" | "notified" | "notifies" | "notify" => {
            return "notify".to_owned()
        }
        "co2" => return "carbon".to_owned(),
        _ => {}
    }
    let char_len = tok.chars().count();
    for suffix in ["ingly", "edly", "ing", "ied", "ies", "ed", "es", "s"] {
        if char_len > suffix.len() + 3 && tok.ends_with(suffix) {
            let base = &tok[..tok.len() - suffix.len()];
            return if suffix == "ies" || suffix == "ied" {
                let mut out = String::with_capacity(base.len() + 1);
                out.push_str(base);
                out.push('y');
                out
            } else {
                base.to_owned()
            };
        }
    }
    if char_len == 4 && tok.ends_with('s') && !ends_with_protected_s(tok) {
        return tok[..tok.len() - 1].to_owned();
    }
    tok.to_owned()
}

pub(crate) fn stem_passage_token_rust(tok: &str) -> String {
    let mut t = normalise_query_term_rust(tok);
    match t.as_str() {
        "bought" => t = "buy".to_owned(),
        "went" => t = "go".to_owned(),
        "took" | "taken" => t = "take".to_owned(),
        "spent" => t = "spend".to_owned(),
        "made" => t = "make".to_owned(),
        "gave" | "given" => t = "give".to_owned(),
        "ate" | "eaten" => t = "eat".to_owned(),
        "saw" | "seen" => t = "see".to_owned(),
        "got" | "gotten" => t = "get".to_owned(),
        "sold" => t = "sell".to_owned(),
        "ran" => t = "run".to_owned(),
        "drove" | "driven" => t = "drive".to_owned(),
        "flew" | "flown" => t = "fly".to_owned(),
        "met" => t = "meet".to_owned(),
        "paid" => t = "pay".to_owned(),
        "wore" | "worn" => t = "wear".to_owned(),
        _ => {}
    }
    let mut char_len = t.chars().count();
    if char_len == 4 && t.ends_with('s') && !ends_with_protected_s(&t) {
        t.pop();
        char_len -= 1;
    }
    if char_len >= 4
        && t.ends_with('e')
        && !(t.ends_with("ee") || t.ends_with("ie") || t.ends_with("ye") || t.ends_with("oe"))
    {
        t.pop();
    }
    t
}

// ---------------------------------------------------------------------------
// Subpassage & user-line extraction — exact port of passages.py
// ---------------------------------------------------------------------------

fn match_speaker_prefix(line: &str) -> Option<(bool, &str)> {
    // Matches _SPEAKER_PREFIX_RE:
    // ^\s*(?:(?:\*{1,2}|\[)\s*(user|human|assistant|agent|ai|system)\s*:?\s*(?:\*{1,2}|\])\s*:?|(user|human|assistant|agent|ai|system)\s*[:\-])\s*(.*)$
    let s = line.trim_start();
    if s.is_empty() {
        return None;
    }
    let labels: [(&str, bool); 6] = [
        ("assistant", false),
        ("system", false),
        ("human", true),
        ("agent", false),
        ("user", true),
        ("ai", false),
    ];

    // Branch 1: wrapped in *, **, or [
    if s.starts_with("**") || s.starts_with('*') || s.starts_with('[') {
        let after_open = if let Some(rest) = s.strip_prefix("**") {
            rest
        } else if let Some(rest) = s.strip_prefix('*') {
            rest
        } else {
            &s[1..]
        };
        let after_ws = after_open.trim_start();
        for &(label, is_user) in &labels {
            if after_ws.len() >= label.len()
                && after_ws.as_bytes()[..label.len()].eq_ignore_ascii_case(label.as_bytes())
            {
                let mut rest = after_ws[label.len()..].trim_start();
                if let Some(r) = rest.strip_prefix(':') {
                    rest = r.trim_start();
                }
                let after_close = if let Some(r) = rest.strip_prefix("**") {
                    r
                } else if let Some(r) = rest.strip_prefix('*') {
                    r
                } else if let Some(r) = rest.strip_prefix(']') {
                    r
                } else {
                    continue;
                };
                let mut tail = after_close.trim_start();
                if let Some(r) = tail.strip_prefix(':') {
                    tail = r;
                }
                return Some((is_user, tail.trim_start()));
            }
        }
    }

    // Branch 2: plain label followed by : or -
    for &(label, is_user) in &labels {
        if s.len() >= label.len()
            && s.as_bytes()[..label.len()].eq_ignore_ascii_case(label.as_bytes())
        {
            let rest = s[label.len()..].trim_start();
            if let Some(tail) = rest.strip_prefix(':').or_else(|| rest.strip_prefix('-')) {
                return Some((is_user, tail.trim_start()));
            }
        }
    }
    None
}

fn extract_user_lines_rust(text: &str) -> Option<String> {
    let mut has_tags = false;
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.len() >= 5 && trimmed.as_bytes()[..5].eq_ignore_ascii_case(b"user:") {
            has_tags = true;
            break;
        }
        if trimmed.len() >= 10 && trimmed.as_bytes()[..10].eq_ignore_ascii_case(b"assistant:") {
            has_tags = true;
            break;
        }
    }
    if !has_tags {
        return None;
    }
    let mut out: Vec<&str> = Vec::new();
    let mut in_assistant = false;
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.len() >= 5 && trimmed.as_bytes()[..5].eq_ignore_ascii_case(b"user:") {
            in_assistant = false;
            out.push(line);
        } else if trimmed.len() >= 10
            && trimmed.as_bytes()[..10].eq_ignore_ascii_case(b"assistant:")
        {
            in_assistant = true;
        } else if !in_assistant {
            out.push(line);
        }
    }
    let joined = out.join("\n");
    let trimmed = joined.trim();
    if trimmed.is_empty() || trimmed == text {
        None
    } else {
        Some(trimmed.to_owned())
    }
}

/// Split non-dialogue text into paragraphs on blank lines (`\n\s*\n+`).
fn split_paragraphs(text: &str) -> Vec<&str> {
    let mut paragraphs: Vec<&str> = Vec::new();
    let mut start: Option<usize> = None;
    let mut end: usize = 0;
    let mut offset = 0usize;
    for raw_line in text.split_inclusive('\n') {
        let line_no_nl = raw_line.trim_end_matches(['\r', '\n']);
        if line_no_nl.trim().is_empty() {
            if let Some(s) = start.take() {
                let para = text[s..end].trim();
                if !para.is_empty() {
                    paragraphs.push(para);
                }
            }
        } else {
            if start.is_none() {
                start = Some(offset);
            }
            end = offset + line_no_nl.len();
        }
        offset += raw_line.len();
    }
    if let Some(s) = start {
        let para = text[s..end].trim();
        if !para.is_empty() {
            paragraphs.push(para);
        }
    }
    paragraphs
}

/// Split prose into sentences on `(?<=[.!?])\s+`.
fn split_sentences(text: &str) -> Vec<&str> {
    let bytes = text.as_bytes();
    let mut out: Vec<&str> = Vec::new();
    let mut start = 0usize;
    let mut i = 0usize;
    while i < bytes.len() {
        if matches!(bytes[i], b'.' | b'!' | b'?') && i + 1 < bytes.len() {
            let mut j = i + 1;
            let mut saw_ws = false;
            while j < bytes.len() && bytes[j].is_ascii_whitespace() {
                saw_ws = true;
                j += 1;
            }
            if saw_ws {
                let seg = text[start..=i].trim();
                if !seg.is_empty() {
                    out.push(seg);
                }
                start = j;
                i = j;
                continue;
            }
        }
        i += 1;
    }
    if start < text.len() {
        let seg = text[start..].trim();
        if !seg.is_empty() {
            out.push(seg);
        }
    }
    out
}

struct ExtractedSubpassages {
    rounds: Vec<String>,
    turns: Vec<String>,
}

fn extract_rounds_and_turns(text: &str) -> ExtractedSubpassages {
    let lines: Vec<&str> = text.lines().collect();
    let has_speaker_tags = lines.iter().any(|l| match_speaker_prefix(l).is_some());

    if has_speaker_tags {
        // (is_user, text)
        let mut raw_turns: Vec<(bool, String)> = Vec::new();
        let mut current_is_user: Option<bool> = None;
        let mut current_lines: Vec<String> = Vec::new();

        for &line in &lines {
            if let Some((is_user, content)) = match_speaker_prefix(line) {
                if let Some(prev_user) = current_is_user {
                    let t_text = current_lines.join("\n");
                    let trimmed = t_text.trim();
                    if !trimmed.is_empty() {
                        raw_turns.push((prev_user, trimmed.to_owned()));
                    }
                }
                current_is_user = Some(is_user);
                let label = if is_user { "User:" } else { "Assistant:" };
                current_lines.clear();
                if content.is_empty() {
                    current_lines.push(label.to_owned());
                } else {
                    current_lines.push(format!("{label} {content}").trim().to_owned());
                }
            } else if current_is_user.is_some() || !line.trim().is_empty() {
                current_lines.push(line.to_owned());
            }
        }
        if let Some(prev_user) = current_is_user {
            let t_text = current_lines.join("\n");
            let trimmed = t_text.trim();
            if !trimmed.is_empty() {
                raw_turns.push((prev_user, trimmed.to_owned()));
            }
        }

        let mut rounds = Vec::new();
        let mut turns = Vec::new();
        let mut i = 0usize;
        while i < raw_turns.len() {
            if raw_turns[i].0 {
                turns.push(raw_turns[i].1.clone());
                if i + 1 < raw_turns.len() && !raw_turns[i + 1].0 {
                    rounds.push(format!("{}\n{}", raw_turns[i].1, raw_turns[i + 1].1));
                    i += 2;
                } else {
                    rounds.push(raw_turns[i].1.clone());
                    i += 1;
                }
            } else {
                rounds.push(raw_turns[i].1.clone());
                i += 1;
            }
        }
        return ExtractedSubpassages { rounds, turns };
    }

    let paragraphs = split_paragraphs(text);
    if paragraphs.len() > 1 {
        let owned: Vec<String> = paragraphs.into_iter().map(|s| s.to_owned()).collect();
        return ExtractedSubpassages {
            rounds: owned.clone(),
            turns: owned,
        };
    }

    let sentences = split_sentences(text);
    if sentences.len() > 3 {
        let mut windows = Vec::new();
        let mut start = 0usize;
        while start < sentences.len() {
            let end = (start + 3).min(sentences.len());
            windows.push(sentences[start..end].join(" "));
            start += 2;
        }
        return ExtractedSubpassages {
            rounds: windows.clone(),
            turns: windows,
        };
    }

    let single = vec![text.to_owned()];
    ExtractedSubpassages {
        rounds: single.clone(),
        turns: single,
    }
}

// ---------------------------------------------------------------------------
// Per-doc counting & indexing (executed in parallel by Rayon)
// ---------------------------------------------------------------------------

struct TermBag {
    exact: HashMap<String, u32>,
    stems: HashMap<String, u32>,
    len: u32,
}

fn count_and_stem(text: &str) -> TermBag {
    let mut exact: HashMap<String, u32> = HashMap::new();
    let mut len: u32 = 0;
    for_each_term_any(text, |tok| {
        len = len.saturating_add(1);
        if let Some(c) = exact.get_mut(tok) {
            *c += 1;
        } else {
            exact.insert(tok.to_owned(), 1);
        }
    });
    let mut stems: HashMap<String, u32> = HashMap::with_capacity(exact.len());
    for (term, &cnt) in &exact {
        let st = stem_passage_token_rust(term);
        *stems.entry(st).or_insert(0) += cnt;
    }
    TermBag { exact, stems, len }
}

struct DocIndexed {
    digest: [u8; 16],
    doc_len: u32,
    user_len: u32,
    exact: HashMap<String, u32>,
    stems: HashMap<String, u32>,
    user_stems: HashMap<String, u32>,
    round_lens: Vec<u32>,
    turn_lens: Vec<u32>,
    round_exact: Vec<(String, u32, u32)>,
    round_stem: Vec<(String, u32, u32)>,
    turn_exact: Vec<(String, u32, u32)>,
    turn_stem: Vec<(String, u32, u32)>,
    total_round_len: u64,
    total_turn_len: u64,
}

fn index_one_doc(raw_text: &str, norm_text: &str) -> DocIndexed {
    let digest = digest_text(raw_text);
    let main_bag = count_and_stem(norm_text);
    let doc_len = main_bag.len;

    let (user_stems, user_len) = match extract_user_lines_rust(norm_text) {
        None => (main_bag.stems.clone(), doc_len.max(1)),
        Some(u_txt) => {
            let ub = count_and_stem(&u_txt);
            (ub.stems, ub.len.max(1))
        }
    };

    let subs = extract_rounds_and_turns(norm_text);
    // Cache tokenized subpassages by text so identical round/turn/session text is tokenized once.
    let mut bag_cache: HashMap<&str, usize> = HashMap::new();
    let mut extra_bags: Vec<TermBag> = Vec::new();
    // Sentinel usize::MAX means reuse `main_bag`.
    bag_cache.insert(norm_text, usize::MAX);

    let mut round_lens = Vec::with_capacity(subs.rounds.len());
    let mut round_exact = Vec::new();
    let mut round_stem = Vec::new();
    let mut total_round_len: u64 = 0;

    for (r_idx, r_txt) in subs.rounds.iter().enumerate() {
        let bag_id = if let Some(&id) = bag_cache.get(r_txt.as_str()) {
            id
        } else {
            let id = extra_bags.len();
            extra_bags.push(count_and_stem(r_txt));
            bag_cache.insert(r_txt.as_str(), id);
            id
        };
        let bag = if bag_id == usize::MAX {
            &main_bag
        } else {
            &extra_bags[bag_id]
        };
        let r_len = bag.len.max(1);
        round_lens.push(r_len);
        total_round_len += r_len as u64;
        let ri = r_idx as u32;
        for (term, &cnt) in &bag.exact {
            round_exact.push((term.clone(), ri, cnt));
        }
        for (st, &cnt) in &bag.stems {
            round_stem.push((st.clone(), ri, cnt));
        }
    }

    let mut turn_lens = Vec::with_capacity(subs.turns.len());
    let mut turn_exact = Vec::new();
    let mut turn_stem = Vec::new();
    let mut total_turn_len: u64 = 0;

    for (t_idx, t_txt) in subs.turns.iter().enumerate() {
        let bag_id = if let Some(&id) = bag_cache.get(t_txt.as_str()) {
            id
        } else {
            let id = extra_bags.len();
            extra_bags.push(count_and_stem(t_txt));
            bag_cache.insert(t_txt.as_str(), id);
            id
        };
        let bag = if bag_id == usize::MAX {
            &main_bag
        } else {
            &extra_bags[bag_id]
        };
        let tn_len = bag.len.max(1);
        turn_lens.push(tn_len);
        total_turn_len += tn_len as u64;
        let ti = t_idx as u32;
        for (term, &cnt) in &bag.exact {
            turn_exact.push((term.clone(), ti, cnt));
        }
        for (st, &cnt) in &bag.stems {
            turn_stem.push((st.clone(), ti, cnt));
        }
    }

    DocIndexed {
        digest,
        doc_len,
        user_len,
        exact: main_bag.exact,
        stems: main_bag.stems,
        user_stems,
        round_lens,
        turn_lens,
        round_exact,
        round_stem,
        turn_exact,
        turn_stem,
        total_round_len,
        total_turn_len,
    }
}

// ---------------------------------------------------------------------------
// Damerau-Levenshtein <= 1 for typo recovery directly over Rust vocabulary
// ---------------------------------------------------------------------------

fn damerau_levenshtein_le_one(a: &str, b: &str) -> bool {
    if a == b {
        return true;
    }
    let ab = a.as_bytes();
    let bb = b.as_bytes();
    let la = ab.len();
    let lb = bb.len();
    if la.abs_diff(lb) > 1 {
        return false;
    }
    let mut i = 0usize;
    let min_l = la.min(lb);
    while i < min_l && ab[i] == bb[i] {
        i += 1;
    }
    if la == lb {
        // Substitution or adjacent transposition
        if i + 1 < la && ab[i] == bb[i + 1] && ab[i + 1] == bb[i] {
            return ab[i + 2..] == bb[i + 2..];
        }
        return ab[i + 1..] == bb[i + 1..];
    }
    if la > lb {
        return ab[i + 1..] == bb[i..];
    }
    ab[i..] == bb[i + 1..]
}

// ---------------------------------------------------------------------------
// Compact binary sidecar codec (`MNPB` v1)
// ---------------------------------------------------------------------------

fn write_u32(buf: &mut Vec<u8>, v: u32) {
    buf.extend_from_slice(&v.to_le_bytes());
}

fn write_u64(buf: &mut Vec<u8>, v: u64) {
    buf.extend_from_slice(&v.to_le_bytes());
}

fn write_str(buf: &mut Vec<u8>, s: &str) {
    write_u32(buf, s.len() as u32);
    buf.extend_from_slice(s.as_bytes());
}

fn write_postings2(buf: &mut Vec<u8>, map: &HashMap<String, Vec<(u32, u32)>>) {
    write_u32(buf, map.len() as u32);
    for (term, list) in map {
        write_str(buf, term);
        write_u32(buf, list.len() as u32);
        for &(a, b) in list {
            write_u32(buf, a);
            write_u32(buf, b);
        }
    }
}

fn write_postings3(buf: &mut Vec<u8>, map: &HashMap<String, Vec<(u32, u32, u32)>>) {
    write_u32(buf, map.len() as u32);
    for (term, list) in map {
        write_str(buf, term);
        write_u32(buf, list.len() as u32);
        for &(a, b, c) in list {
            write_u32(buf, a);
            write_u32(buf, b);
            write_u32(buf, c);
        }
    }
}

fn read_bytes<'a>(cur: &mut Cursor<&'a [u8]>, n: usize) -> PyResult<&'a [u8]> {
    let pos = cur.position() as usize;
    let slice = *cur.get_ref();
    let end = pos
        .checked_add(n)
        .ok_or_else(|| PyValueError::new_err("sidecar read overflow"))?;
    if end > slice.len() {
        return Err(PyValueError::new_err("truncated passage sidecar"));
    }
    cur.set_position(end as u64);
    Ok(&slice[pos..end])
}

fn read_u32(cur: &mut Cursor<&[u8]>) -> PyResult<u32> {
    let b = read_bytes(cur, 4)?;
    Ok(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
}

fn read_u64(cur: &mut Cursor<&[u8]>) -> PyResult<u64> {
    let b = read_bytes(cur, 8)?;
    Ok(u64::from_le_bytes([
        b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
    ]))
}

fn read_str(cur: &mut Cursor<&[u8]>) -> PyResult<String> {
    let len = read_u32(cur)? as usize;
    let b = read_bytes(cur, len)?;
    std::str::from_utf8(b)
        .map(|s| s.to_owned())
        .map_err(|_| PyValueError::new_err("invalid utf-8 in passage sidecar"))
}

fn read_postings2(cur: &mut Cursor<&[u8]>) -> PyResult<HashMap<String, Vec<(u32, u32)>>> {
    let count = read_u32(cur)? as usize;
    let mut map = HashMap::with_capacity(count);
    for _ in 0..count {
        let term = read_str(cur)?;
        let n = read_u32(cur)? as usize;
        let mut list = Vec::with_capacity(n);
        for _ in 0..n {
            let a = read_u32(cur)?;
            let b = read_u32(cur)?;
            list.push((a, b));
        }
        map.insert(term, list);
    }
    Ok(map)
}

fn read_postings3(cur: &mut Cursor<&[u8]>) -> PyResult<HashMap<String, Vec<(u32, u32, u32)>>> {
    let count = read_u32(cur)? as usize;
    let mut map = HashMap::with_capacity(count);
    for _ in 0..count {
        let term = read_str(cur)?;
        let n = read_u32(cur)? as usize;
        let mut list = Vec::with_capacity(n);
        for _ in 0..n {
            let a = read_u32(cur)?;
            let b = read_u32(cur)?;
            let c = read_u32(cur)?;
            list.push((a, b, c));
        }
        map.insert(term, list);
    }
    Ok(map)
}

// ---------------------------------------------------------------------------
// PyClass: NativePassageIndex
// ---------------------------------------------------------------------------

#[pyclass]
pub struct NativePassageIndex {
    session_ids: Vec<String>,
    doc_digests: Vec<[u8; 16]>,
    lengths: Vec<u32>,
    user_lengths: Vec<u32>,
    round_lengths: Vec<Vec<u32>>,
    turn_lengths: Vec<Vec<u32>>,
    postings: HashMap<String, Vec<(u32, u32)>>,
    stem_postings: HashMap<String, Vec<(u32, u32)>>,
    user_stem_postings: HashMap<String, Vec<(u32, u32)>>,
    round_postings: HashMap<String, Vec<(u32, u32, u32)>>,
    round_stem_postings: HashMap<String, Vec<(u32, u32, u32)>>,
    turn_postings: HashMap<String, Vec<(u32, u32, u32)>>,
    turn_stem_postings: HashMap<String, Vec<(u32, u32, u32)>>,
    total_length: u64,
    total_user_length: u64,
    total_round_length: u64,
    total_rounds: u64,
    total_turn_length: u64,
    total_turns: u64,
}

impl NativePassageIndex {
    fn append_doc_indexed(&mut self, doc_idx: u32, session_id: String, doc: DocIndexed) {
        self.session_ids.push(session_id);
        self.doc_digests.push(doc.digest);
        self.lengths.push(doc.doc_len);
        self.user_lengths.push(doc.user_len);
        self.total_length += doc.doc_len as u64;
        self.total_user_length += doc.user_len as u64;
        self.total_round_length += doc.total_round_len;
        self.total_rounds += doc.round_lens.len() as u64;
        self.total_turn_length += doc.total_turn_len;
        self.total_turns += doc.turn_lens.len() as u64;
        self.round_lengths.push(doc.round_lens);
        self.turn_lengths.push(doc.turn_lens);

        for (term, cnt) in doc.exact {
            self.postings.entry(term).or_default().push((doc_idx, cnt));
        }
        for (st, cnt) in doc.stems {
            self.stem_postings.entry(st).or_default().push((doc_idx, cnt));
        }
        for (st, cnt) in doc.user_stems {
            self.user_stem_postings
                .entry(st)
                .or_default()
                .push((doc_idx, cnt));
        }
        for (term, r_idx, cnt) in doc.round_exact {
            self.round_postings
                .entry(term)
                .or_default()
                .push((doc_idx, r_idx, cnt));
        }
        for (st, r_idx, cnt) in doc.round_stem {
            self.round_stem_postings
                .entry(st)
                .or_default()
                .push((doc_idx, r_idx, cnt));
        }
        for (term, t_idx, cnt) in doc.turn_exact {
            self.turn_postings
                .entry(term)
                .or_default()
                .push((doc_idx, t_idx, cnt));
        }
        for (st, t_idx, cnt) in doc.turn_stem {
            self.turn_stem_postings
                .entry(st)
                .or_default()
                .push((doc_idx, t_idx, cnt));
        }
    }

    #[inline]
    fn average_length(&self) -> f64 {
        let n = self.lengths.len().max(1) as f64;
        let avg = (self.total_length as f64) / n;
        if avg == 0.0 { 1.0 } else { avg }
    }

    #[inline]
    fn average_user_length(&self) -> f64 {
        let n = self.lengths.len().max(1) as f64;
        let avg = (self.total_user_length as f64) / n;
        if avg == 0.0 { 1.0 } else { avg }
    }

    #[inline]
    fn average_round_length(&self) -> f64 {
        let n = self.total_rounds.max(1) as f64;
        let avg = (self.total_round_length as f64) / n;
        if avg == 0.0 { 60.0 } else { avg }
    }

    #[inline]
    fn average_turn_length(&self) -> f64 {
        let n = self.total_turns.max(1) as f64;
        let avg = (self.total_turn_length as f64) / n;
        if avg == 0.0 { 25.0 } else { avg }
    }

    fn compute_session_scores(
        &self,
        expanded_counts: &[(String, f64)],
        stem_expanded: &[(String, f64)],
    ) -> HashMap<usize, f64> {
        let n_texts = self.lengths.len();
        if n_texts == 0 {
            return HashMap::new();
        }
        let n_f = n_texts as f64;
        let avg_len = self.average_length();
        let avg_u_len = self.average_user_length();
        let mut scores: HashMap<usize, f64> = HashMap::new();

        for (term, query_count) in expanded_counts {
            if let Some(postings) = self.postings.get(term) {
                let df = postings.len() as f64;
                let idf = (1.0 + (n_f - df + 0.5) / (df + 0.5)).ln();
                for &(idx, count) in postings {
                    let c = count as f64;
                    let norm = 1.2 * (0.25 + 0.75 * (self.lengths[idx as usize] as f64) / avg_len);
                    *scores.entry(idx as usize).or_insert(0.0) +=
                        0.30 * query_count * idf * c * 2.2 / (c + norm);
                }
            }
        }
        for (st, query_count) in stem_expanded {
            if let Some(postings) = self.stem_postings.get(st) {
                let df = postings.len() as f64;
                let idf = (1.0 + (n_f - df + 0.5) / (df + 0.5)).ln();
                for &(idx, count) in postings {
                    let c = count as f64;
                    let norm = 1.2 * (0.25 + 0.75 * (self.lengths[idx as usize] as f64) / avg_len);
                    *scores.entry(idx as usize).or_insert(0.0) +=
                        0.20 * query_count * idf * c * 2.2 / (c + norm);
                }
            }
            if let Some(u_postings) = self.user_stem_postings.get(st) {
                let df = u_postings.len() as f64;
                let u_idf = (1.0 + (n_f - df + 0.5) / (df + 0.5)).ln();
                for &(idx, count) in u_postings {
                    let c = count as f64;
                    let u_norm =
                        1.2 * (0.25 + 0.75 * (self.user_lengths[idx as usize] as f64) / avg_u_len);
                    *scores.entry(idx as usize).or_insert(0.0) +=
                        0.75 * query_count * u_idf * c * 2.2 / (c + u_norm);
                }
            }
        }
        scores
    }
}

#[pymethods]
impl NativePassageIndex {
    #[new]
    #[pyo3(signature = (raw_texts, norm_texts, session_ids))]
    pub fn new(
        py: Python<'_>,
        raw_texts: Vec<String>,
        norm_texts: Vec<String>,
        session_ids: Vec<String>,
    ) -> PyResult<Self> {
        if raw_texts.len() != norm_texts.len() || raw_texts.len() != session_ids.len() {
            return Err(PyValueError::new_err(
                "raw_texts, norm_texts, and session_ids must have identical lengths",
            ));
        }
        let n = raw_texts.len();
        let docs: Vec<DocIndexed> = py.detach(|| {
            if n >= 16 {
                raw_texts
                    .par_iter()
                    .zip(norm_texts.par_iter())
                    .map(|(raw, norm)| index_one_doc(raw, norm))
                    .collect()
            } else {
                raw_texts
                    .iter()
                    .zip(norm_texts.iter())
                    .map(|(raw, norm)| index_one_doc(raw, norm))
                    .collect()
            }
        });

        let mut index = Self {
            session_ids: Vec::with_capacity(n),
            doc_digests: Vec::with_capacity(n),
            lengths: Vec::with_capacity(n),
            user_lengths: Vec::with_capacity(n),
            round_lengths: Vec::with_capacity(n),
            turn_lengths: Vec::with_capacity(n),
            postings: HashMap::new(),
            stem_postings: HashMap::new(),
            user_stem_postings: HashMap::new(),
            round_postings: HashMap::new(),
            round_stem_postings: HashMap::new(),
            turn_postings: HashMap::new(),
            turn_stem_postings: HashMap::new(),
            total_length: 0,
            total_user_length: 0,
            total_round_length: 0,
            total_rounds: 0,
            total_turn_length: 0,
            total_turns: 0,
        };
        for (i, (sid, doc)) in session_ids.into_iter().zip(docs.into_iter()).enumerate() {
            index.append_doc_indexed(i as u32, sid, doc);
        }
        Ok(index)
    }

    pub fn add_text(&mut self, raw_text: &str, norm_text: &str, session_id: String) -> (u32, u32) {
        let doc = index_one_doc(raw_text, norm_text);
        let t_len = doc.doc_len;
        let u_len = doc.user_len;
        let idx = self.lengths.len() as u32;
        self.append_doc_indexed(idx, session_id, doc);
        (t_len, u_len)
    }

    pub fn len(&self) -> usize {
        self.lengths.len()
    }

    pub fn stats(&self) -> (u64, u64, u64, u64, u64, u64) {
        (
            self.total_length,
            self.total_user_length,
            self.total_round_length,
            self.total_rounds,
            self.total_turn_length,
            self.total_turns,
        )
    }

    pub fn lengths(&self) -> Vec<u32> {
        self.lengths.clone()
    }

    pub fn user_lengths(&self) -> Vec<u32> {
        self.user_lengths.clone()
    }

    pub fn round_lengths(&self) -> Vec<Vec<u32>> {
        self.round_lengths.clone()
    }

    pub fn turn_lengths(&self) -> Vec<Vec<u32>> {
        self.turn_lengths.clone()
    }

    pub fn has_term(&self, term: &str) -> bool {
        self.postings.contains_key(term)
    }

    pub fn has_stem(&self, stem: &str) -> bool {
        self.stem_postings.contains_key(stem)
    }

    /// Typo-recovery lookup over the Rust vocabulary without exporting postings to Python.
    pub fn typo_candidates(&self, term: &str) -> Vec<String> {
        let bytes = term.as_bytes();
        if bytes.len() < 6 || !bytes.iter().all(|b| b.is_ascii_alphabetic()) {
            return Vec::new();
        }
        let first = bytes[0];
        let tlen = bytes.len();
        let mut matches = Vec::new();
        for vocab_term in self.postings.keys() {
            let vb = vocab_term.as_bytes();
            if vb.len() >= 6
                && vb[0] == first
                && vb.len().abs_diff(tlen) <= 1
                && vb.iter().all(|b| b.is_ascii_alphabetic())
                && damerau_levenshtein_le_one(term, vocab_term)
            {
                matches.push(vocab_term.clone());
            }
        }
        matches.sort();
        matches
    }

    /// Parallel cryptographic digest verification that `(session_ids, texts)`
    /// matches this index 1-for-1 (replaces 40 MB Python string comparison).
    pub fn verify_passages(
        &self,
        py: Python<'_>,
        session_ids: Vec<String>,
        texts: Vec<String>,
    ) -> bool {
        if session_ids.len() != self.session_ids.len() || texts.len() != self.doc_digests.len() {
            return false;
        }
        if session_ids != self.session_ids {
            return false;
        }
        let n = texts.len();
        py.detach(|| {
            if n >= 32 {
                texts
                    .par_iter()
                    .zip(self.doc_digests.par_iter())
                    .all(|(t, d)| digest_text(t) == *d)
            } else {
                texts
                    .iter()
                    .zip(self.doc_digests.iter())
                    .all(|(t, d)| digest_text(t) == *d)
            }
        })
    }

    /// Parallel check that `self` is an exact prefix of `(session_ids, texts)` for incremental append.
    pub fn verify_prefix(
        &self,
        py: Python<'_>,
        session_ids: Vec<String>,
        texts: Vec<String>,
    ) -> bool {
        let n = self.session_ids.len();
        if n == 0 || session_ids.len() <= n || texts.len() <= n {
            return false;
        }
        if session_ids[..n] != self.session_ids[..] {
            return false;
        }
        py.detach(|| {
            if n >= 32 {
                texts[..n]
                    .par_iter()
                    .zip(self.doc_digests.par_iter())
                    .all(|(t, d)| digest_text(t) == *d)
            } else {
                texts[..n]
                    .iter()
                    .zip(self.doc_digests.iter())
                    .all(|(t, d)| digest_text(t) == *d)
            }
        })
    }

    pub fn score_docs(
        &self,
        py: Python<'_>,
        expanded_counts: Vec<(String, f64)>,
        stem_expanded: Vec<(String, f64)>,
    ) -> HashMap<usize, f64> {
        py.detach(|| self.compute_session_scores(&expanded_counts, &stem_expanded))
    }

    /// Return `(doc_idx, fused_score, session_score, max_round_score, best_round_idx, max_turn_score, best_turn_idx)`
    /// for every document with non-zero score at session, round, or turn granularity.
    pub fn score_multi_granularity(
        &self,
        py: Python<'_>,
        expanded_counts: Vec<(String, f64)>,
        stem_expanded: Vec<(String, f64)>,
        alpha: f64,
        beta: f64,
    ) -> Vec<(usize, f64, f64, f64, usize, f64, usize)> {
        py.detach(|| {
            let n_texts = self.lengths.len();
            if n_texts == 0 {
                return Vec::new();
            }
            let n_f = n_texts as f64;
            let session_scores = self.compute_session_scores(&expanded_counts, &stem_expanded);

            let avg_round_len = self.average_round_length();
            let avg_turn_len = self.average_turn_length();

            let mut round_scores: HashMap<usize, HashMap<usize, f64>> = HashMap::new();
            let mut turn_scores: HashMap<usize, HashMap<usize, f64>> = HashMap::new();

            for (term, query_count) in &expanded_counts {
                let doc_df = self.postings.get(term).map_or(0, |v| v.len()) as f64;
                let idf = (1.0 + (n_f - doc_df + 0.5) / (doc_df + 0.5)).ln();
                if let Some(postings) = self.round_postings.get(term) {
                    for &(sess_idx, r_idx, count) in postings {
                        let si = sess_idx as usize;
                        let ri = r_idx as usize;
                        let r_len = self
                            .round_lengths
                            .get(si)
                            .and_then(|v| v.get(ri))
                            .map_or(avg_round_len, |&l| l as f64);
                        let norm = 1.2 * (0.25 + 0.75 * r_len / avg_round_len);
                        let c = count as f64;
                        *round_scores.entry(si).or_default().entry(ri).or_insert(0.0) +=
                            0.35 * query_count * idf * c * 2.2 / (c + norm);
                    }
                }
                if let Some(postings) = self.turn_postings.get(term) {
                    for &(sess_idx, t_idx, count) in postings {
                        let si = sess_idx as usize;
                        let ti = t_idx as usize;
                        let tn_len = self
                            .turn_lengths
                            .get(si)
                            .and_then(|v| v.get(ti))
                            .map_or(avg_turn_len, |&l| l as f64);
                        let norm = 1.2 * (0.25 + 0.75 * tn_len / avg_turn_len);
                        let c = count as f64;
                        *turn_scores.entry(si).or_default().entry(ti).or_insert(0.0) +=
                            0.35 * query_count * idf * c * 2.2 / (c + norm);
                    }
                }
            }

            for (st, query_count) in &stem_expanded {
                let doc_df = self.stem_postings.get(st).map_or(0, |v| v.len()) as f64;
                let idf = (1.0 + (n_f - doc_df + 0.5) / (doc_df + 0.5)).ln();
                if let Some(s_postings) = self.round_stem_postings.get(st) {
                    for &(sess_idx, r_idx, count) in s_postings {
                        let si = sess_idx as usize;
                        let ri = r_idx as usize;
                        let r_len = self
                            .round_lengths
                            .get(si)
                            .and_then(|v| v.get(ri))
                            .map_or(avg_round_len, |&l| l as f64);
                        let norm = 1.2 * (0.25 + 0.75 * r_len / avg_round_len);
                        let c = count as f64;
                        *round_scores.entry(si).or_default().entry(ri).or_insert(0.0) +=
                            0.65 * query_count * idf * c * 2.2 / (c + norm);
                    }
                }
                if let Some(s_postings) = self.turn_stem_postings.get(st) {
                    for &(sess_idx, t_idx, count) in s_postings {
                        let si = sess_idx as usize;
                        let ti = t_idx as usize;
                        let tn_len = self
                            .turn_lengths
                            .get(si)
                            .and_then(|v| v.get(ti))
                            .map_or(avg_turn_len, |&l| l as f64);
                        let norm = 1.2 * (0.25 + 0.75 * tn_len / avg_turn_len);
                        let c = count as f64;
                        *turn_scores.entry(si).or_default().entry(ti).or_insert(0.0) +=
                            0.65 * query_count * idf * c * 2.2 / (c + norm);
                    }
                }
            }

            // Collect union of touched doc indices deterministically.
            let mut active: Vec<usize> = session_scores
                .keys()
                .chain(round_scores.keys())
                .chain(turn_scores.keys())
                .copied()
                .collect();
            active.sort_unstable();
            active.dedup();

            let mut out = Vec::with_capacity(active.len());
            for si in active {
                let sess_sc = session_scores.get(&si).copied().unwrap_or(0.0);
                let (max_r_sc, best_r_idx) = match round_scores.get(&si) {
                    Some(rmap) if !rmap.is_empty() => {
                        let mut best_i = 0usize;
                        let mut best_v = f64::NEG_INFINITY;
                        for (&ri, &v) in rmap {
                            if v > best_v || (v == best_v && ri < best_i) {
                                best_v = v;
                                best_i = ri;
                            }
                        }
                        (best_v, best_i)
                    }
                    _ => (0.0, 0),
                };
                let (max_t_sc, best_t_idx) = match turn_scores.get(&si) {
                    Some(tmap) if !tmap.is_empty() => {
                        let mut best_i = 0usize;
                        let mut best_v = f64::NEG_INFINITY;
                        for (&ti, &v) in tmap {
                            if v > best_v || (v == best_v && ti < best_i) {
                                best_v = v;
                                best_i = ti;
                            }
                        }
                        (best_v, best_i)
                    }
                    _ => (0.0, 0),
                };
                let fused = sess_sc + alpha * max_r_sc + beta * max_t_sc;
                out.push((si, fused, sess_sc, max_r_sc, best_r_idx, max_t_sc, best_t_idx));
            }
            out
        })
    }

    // Lazy Python-compatibility exports (only invoked when callers explicitly read
    // `.postings` / `.round_postings` / `.turn_postings` attributes).
    pub fn export_postings(&self) -> HashMap<String, Vec<(u32, u32)>> {
        self.postings.clone()
    }
    pub fn export_stem_postings(&self) -> HashMap<String, Vec<(u32, u32)>> {
        self.stem_postings.clone()
    }
    pub fn export_user_stem_postings(&self) -> HashMap<String, Vec<(u32, u32)>> {
        self.user_stem_postings.clone()
    }
    pub fn export_round_postings(&self) -> HashMap<String, Vec<(u32, u32, u32)>> {
        self.round_postings.clone()
    }
    pub fn export_round_stem_postings(&self) -> HashMap<String, Vec<(u32, u32, u32)>> {
        self.round_stem_postings.clone()
    }
    pub fn export_turn_postings(&self) -> HashMap<String, Vec<(u32, u32, u32)>> {
        self.turn_postings.clone()
    }
    pub fn export_turn_stem_postings(&self) -> HashMap<String, Vec<(u32, u32, u32)>> {
        self.turn_stem_postings.clone()
    }

    /// Serialize to compact binary sidecar bytes (`MNPB` v1). Stores NO raw passage text.
    pub fn to_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        let bytes = py.detach(|| {
            let mut buf: Vec<u8> = Vec::with_capacity(65_536);
            buf.extend_from_slice(SIDECAR_MAGIC);
            write_u32(&mut buf, SIDECAR_VERSION);
            let n = self.lengths.len() as u32;
            write_u32(&mut buf, n);
            write_u64(&mut buf, self.total_length);
            write_u64(&mut buf, self.total_user_length);
            write_u64(&mut buf, self.total_round_length);
            write_u64(&mut buf, self.total_rounds);
            write_u64(&mut buf, self.total_turn_length);
            write_u64(&mut buf, self.total_turns);

            for sid in &self.session_ids {
                write_str(&mut buf, sid);
            }
            for dig in &self.doc_digests {
                buf.extend_from_slice(dig);
            }
            for &l in &self.lengths {
                write_u32(&mut buf, l);
            }
            for &l in &self.user_lengths {
                write_u32(&mut buf, l);
            }
            for rl in &self.round_lengths {
                write_u32(&mut buf, rl.len() as u32);
                for &l in rl {
                    write_u32(&mut buf, l);
                }
            }
            for tl in &self.turn_lengths {
                write_u32(&mut buf, tl.len() as u32);
                for &l in tl {
                    write_u32(&mut buf, l);
                }
            }
            write_postings2(&mut buf, &self.postings);
            write_postings2(&mut buf, &self.stem_postings);
            write_postings2(&mut buf, &self.user_stem_postings);
            write_postings3(&mut buf, &self.round_postings);
            write_postings3(&mut buf, &self.round_stem_postings);
            write_postings3(&mut buf, &self.turn_postings);
            write_postings3(&mut buf, &self.turn_stem_postings);
            buf
        });
        PyBytes::new(py, &bytes)
    }

    /// Deserialize from `to_bytes()` payload (strictly bounds-checked).
    #[staticmethod]
    pub fn from_bytes(py: Python<'_>, payload: &[u8]) -> PyResult<Self> {
        py.detach(|| {
            let mut cur = Cursor::new(payload);
            let magic = read_bytes(&mut cur, 4)?;
            if magic != SIDECAR_MAGIC {
                return Err(PyValueError::new_err("invalid passage sidecar magic"));
            }
            let version = read_u32(&mut cur)?;
            if version != SIDECAR_VERSION {
                return Err(PyValueError::new_err(format!(
                    "unsupported passage sidecar version: {version}"
                )));
            }
            let n = read_u32(&mut cur)? as usize;
            let total_length = read_u64(&mut cur)?;
            let total_user_length = read_u64(&mut cur)?;
            let total_round_length = read_u64(&mut cur)?;
            let total_rounds = read_u64(&mut cur)?;
            let total_turn_length = read_u64(&mut cur)?;
            let total_turns = read_u64(&mut cur)?;

            let mut session_ids = Vec::with_capacity(n);
            for _ in 0..n {
                session_ids.push(read_str(&mut cur)?);
            }
            let mut doc_digests = Vec::with_capacity(n);
            for _ in 0..n {
                let b = read_bytes(&mut cur, 16)?;
                let mut d = [0u8; 16];
                d.copy_from_slice(b);
                doc_digests.push(d);
            }
            let mut lengths = Vec::with_capacity(n);
            for _ in 0..n {
                lengths.push(read_u32(&mut cur)?);
            }
            let mut user_lengths = Vec::with_capacity(n);
            for _ in 0..n {
                user_lengths.push(read_u32(&mut cur)?);
            }
            let mut round_lengths = Vec::with_capacity(n);
            for _ in 0..n {
                let m = read_u32(&mut cur)? as usize;
                let mut v = Vec::with_capacity(m);
                for _ in 0..m {
                    v.push(read_u32(&mut cur)?);
                }
                round_lengths.push(v);
            }
            let mut turn_lengths = Vec::with_capacity(n);
            for _ in 0..n {
                let m = read_u32(&mut cur)? as usize;
                let mut v = Vec::with_capacity(m);
                for _ in 0..m {
                    v.push(read_u32(&mut cur)?);
                }
                turn_lengths.push(v);
            }
            let postings = read_postings2(&mut cur)?;
            let stem_postings = read_postings2(&mut cur)?;
            let user_stem_postings = read_postings2(&mut cur)?;
            let round_postings = read_postings3(&mut cur)?;
            let round_stem_postings = read_postings3(&mut cur)?;
            let turn_postings = read_postings3(&mut cur)?;
            let turn_stem_postings = read_postings3(&mut cur)?;

            if (cur.position() as usize) != payload.len() {
                return Err(PyValueError::new_err("trailing bytes in passage sidecar"));
            }

            Ok(Self {
                session_ids,
                doc_digests,
                lengths,
                user_lengths,
                round_lengths,
                turn_lengths,
                postings,
                stem_postings,
                user_stem_postings,
                round_postings,
                round_stem_postings,
                turn_postings,
                turn_stem_postings,
                total_length,
                total_user_length,
                total_round_length,
                total_rounds,
                total_turn_length,
                total_turns,
            })
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stemmer_matches_python_rules() {
        assert_eq!(stem_passage_token_rust("owned"), "own");
        assert_eq!(stem_passage_token_rust("notifications"), "notify");
        assert_eq!(stem_passage_token_rust("co2"), "carbon");
        assert_eq!(stem_passage_token_rust("bought"), "buy");
        assert_eq!(stem_passage_token_rust("taken"), "tak");
        assert_eq!(stem_passage_token_rust("cats"), "cat");
        assert_eq!(stem_passage_token_rust("baking"), "baking");
        assert_eq!(stem_passage_token_rust("playing"), "play");
        assert_eq!(stem_passage_token_rust("cities"), "citi");
        assert_eq!(stem_passage_token_rust("stories"), "story");
    }

    #[test]
    fn speaker_prefix_matches_dialogue() {
        assert_eq!(match_speaker_prefix("User: Hello world"), Some((true, "Hello world")));
        assert_eq!(match_speaker_prefix("**Assistant**: Reply"), Some((false, "Reply")));
        assert_eq!(match_speaker_prefix("[Human]: Hi"), Some((true, "Hi")));
        assert_eq!(match_speaker_prefix("Plain prose line"), None);
    }
}

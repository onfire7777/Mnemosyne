//! Versioned, fail-closed extractive reader ABI.
//!
//! This module is intentionally independent from the sidecar transport and
//! model loader.  It validates the boundary between an eventual model adapter
//! and the host: only bounded 512-token windows with a 128-token stride are
//! admitted, answers are one of span/yes/no/null, and span text is always
//! reconstructed from the original UTF-8 source bytes.

use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::HashSet;
use std::fmt;
use std::time::{Duration, Instant};

pub const ABI_SCHEMA: &str = "mnemosyne.compact-answering-reader.v1";
pub const READER_ABI: &str = ABI_SCHEMA;
pub const WINDOW_TOKENS: usize = 512;
pub const WINDOW_STRIDE: usize = 128;
pub const MAX_WINDOWS: usize = 64;
pub const MAX_FACTS: usize = 20;
pub const MAX_SUPPORTING_FACTS: usize = 20;
pub const MAX_REQUEST_BYTES: usize = 64 * 1024;
pub const MAX_QUERY_CHARS: usize = 2_000;
pub const MAX_CONTEXT_CHARS: usize = 24_000;
pub const MAX_CONTEXT_BYTES: usize = 64 * 1024;
pub const MAX_ID_CHARS: usize = 256;
pub const MAX_TOKEN_COUNT: usize = WINDOW_TOKENS + WINDOW_STRIDE * (MAX_WINDOWS - 1);
pub const REQUEST_DEADLINE: Duration = Duration::from_secs(30);

const DIGEST_CHARS: usize = 64;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReaderError {
    MalformedPayload,
    RequestTooLarge,
    UnsupportedSchema,
    InvalidIdentity,
    IdentityMismatch,
    InvalidShape,
    InvalidWindow,
    InvalidOffset,
    InvalidUtf8,
    UnsupportedAnswerType,
    UnknownWindow,
    UnknownSupportingFact,
    DuplicateId,
    NonFinite,
    NullDecisionMismatch,
    TimedOut,
}

impl fmt::Display for ReaderError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::MalformedPayload => "malformed reader payload",
            Self::RequestTooLarge => "reader request is too large",
            Self::UnsupportedSchema => "unsupported reader ABI schema",
            Self::InvalidIdentity => "invalid reader identity",
            Self::IdentityMismatch => "reader identity mismatch",
            Self::InvalidShape => "invalid reader tensor or object shape",
            Self::InvalidWindow => "invalid reader window",
            Self::InvalidOffset => "invalid UTF-8 source offset",
            Self::InvalidUtf8 => "source context is not valid UTF-8",
            Self::UnsupportedAnswerType => "unsupported reader answer type",
            Self::UnknownWindow => "reader answer references an unknown window",
            Self::UnknownSupportingFact => "reader answer references an unknown supporting fact",
            Self::DuplicateId => "reader identifiers must be unique",
            Self::NonFinite => "reader score must be finite",
            Self::NullDecisionMismatch => "null margin and answer type disagree",
            Self::TimedOut => "reader validation timed out",
        };
        formatter.write_str(message)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReaderIdentity {
    pub model_id: String,
    pub artifact_id: String,
    pub artifact_sha256: String,
    pub preprocessing_id: String,
    pub preprocessing_sha256: String,
}

impl ReaderIdentity {
    pub fn validate(&self) -> Result<(), ReaderError> {
        validate_id(&self.model_id)?;
        validate_id(&self.artifact_id)?;
        validate_id(&self.preprocessing_id)?;
        validate_digest(&self.artifact_sha256)?;
        validate_digest(&self.preprocessing_sha256)
    }

    pub fn require_match(&self, expected: &Self) -> Result<(), ReaderError> {
        self.validate()?;
        expected.validate()?;
        if self == expected {
            Ok(())
        } else {
            Err(ReaderError::IdentityMismatch)
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TokenSpan {
    pub token: String,
    pub raw_start: usize,
    pub raw_end: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReaderWindow {
    pub window_id: String,
    pub token_start: usize,
    pub token_end: usize,
    pub raw_start: usize,
    pub raw_end: usize,
    pub tokens: Vec<TokenSpan>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SupportingFact {
    pub fact_id: String,
    pub raw_start: usize,
    pub raw_end: usize,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReaderRequest {
    pub schema: String,
    pub identity: ReaderIdentity,
    pub query: String,
    pub context: String,
    pub facts: Vec<SupportingFact>,
    pub windows: Vec<ReaderWindow>,
    pub null_threshold: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReaderPrediction {
    pub schema: String,
    pub identity: ReaderIdentity,
    pub window_id: String,
    pub answer_type: String,
    pub start_token: Option<usize>,
    pub end_token: Option<usize>,
    pub raw_start: Option<usize>,
    pub raw_end: Option<usize>,
    pub supporting_facts: Vec<String>,
    pub null_margin: f32,
    pub score: f32,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ReaderAnswer {
    pub answer_type: String,
    pub answer: Option<String>,
    pub raw_start: Option<usize>,
    pub raw_end: Option<usize>,
    pub supporting_facts: Vec<String>,
    pub null_margin: f32,
    pub window_id: String,
    pub abstained: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AnswerTypeLogits {
    pub span: f32,
    pub yes: f32,
    pub no: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReaderLogits {
    pub schema: String,
    pub identity: ReaderIdentity,
    pub window_id: String,
    pub start_logits: Vec<f32>,
    pub end_logits: Vec<f32>,
    pub answer_type_logits: AnswerTypeLogits,
    pub supporting_fact_logits: Vec<f32>,
    pub null_logit: f32,
}

pub fn parse_request(payload: &[u8]) -> Result<ReaderRequest, ReaderError> {
    if payload.len() > MAX_REQUEST_BYTES {
        return Err(ReaderError::RequestTooLarge);
    }
    let request = serde_json::from_slice(payload).map_err(|_| ReaderError::MalformedPayload)?;
    validate_request(&request)?;
    Ok(request)
}

pub fn parse_prediction(payload: &[u8]) -> Result<ReaderPrediction, ReaderError> {
    if payload.len() > MAX_REQUEST_BYTES {
        return Err(ReaderError::RequestTooLarge);
    }
    let prediction = serde_json::from_slice(payload).map_err(|_| ReaderError::MalformedPayload)?;
    if prediction.schema != ABI_SCHEMA {
        return Err(ReaderError::UnsupportedSchema);
    }
    validate_prediction_shape(&prediction)?;
    Ok(prediction)
}

pub fn validate_request(request: &ReaderRequest) -> Result<(), ReaderError> {
    if request.schema != ABI_SCHEMA {
        return Err(ReaderError::UnsupportedSchema);
    }
    request.identity.validate()?;
    if request.query.is_empty()
        || request.query.trim() != request.query
        || request.query.chars().count() > MAX_QUERY_CHARS
        || request.query.chars().any(char::is_control)
    {
        return Err(ReaderError::InvalidShape);
    }
    if request.context.is_empty()
        || request.context.chars().count() > MAX_CONTEXT_CHARS
        || request.context.as_bytes().len() > MAX_CONTEXT_BYTES
    {
        return Err(ReaderError::InvalidShape);
    }
    if std::str::from_utf8(request.context.as_bytes()).is_err() {
        return Err(ReaderError::InvalidUtf8);
    }
    if !request.null_threshold.is_finite() {
        return Err(ReaderError::NonFinite);
    }
    if request.facts.len() > MAX_FACTS
        || request.windows.is_empty()
        || request.windows.len() > MAX_WINDOWS
    {
        return Err(ReaderError::InvalidShape);
    }

    let mut fact_ids = HashSet::with_capacity(request.facts.len());
    let evidence_chars = request.facts.iter().fold(0usize, |total, fact| {
        total.saturating_add(fact.text.chars().count())
    });
    if evidence_chars > MAX_CONTEXT_CHARS {
        return Err(ReaderError::InvalidShape);
    }
    for fact in &request.facts {
        validate_id(&fact.fact_id)?;
        if !fact_ids.insert(fact.fact_id.as_str()) {
            return Err(ReaderError::DuplicateId);
        }
        validate_source_range(&request.context, fact.raw_start, fact.raw_end)?;
        if source_slice(&request.context, fact.raw_start, fact.raw_end)? != fact.text {
            return Err(ReaderError::InvalidOffset);
        }
    }

    let mut window_ids = HashSet::with_capacity(request.windows.len());
    let first_source_byte = request.context.len() - request.context.trim_start().len();
    let last_source_byte = request.context.trim_end().len();
    if request.windows[0].raw_start != first_source_byte
        || request
            .windows
            .last()
            .expect("windows are non-empty")
            .raw_end
            != last_source_byte
    {
        return Err(ReaderError::InvalidOffset);
    }
    let token_count = request
        .windows
        .last()
        .map(|window| window.token_end)
        .unwrap_or(0);
    let expected_starts = expected_window_starts(token_count)?;
    if expected_starts.len() != request.windows.len() {
        return Err(ReaderError::InvalidWindow);
    }
    for (index, window) in request.windows.iter().enumerate() {
        validate_window(&request.context, window)?;
        if !window_ids.insert(window.window_id.as_str()) {
            return Err(ReaderError::DuplicateId);
        }
        let expected_start = expected_starts[index];
        let expected_end = expected_start
            .saturating_add(WINDOW_TOKENS)
            .min(token_count);
        if window.token_start != expected_start
            || window.token_end != expected_end
            || window.tokens.len() != expected_end - expected_start
        {
            return Err(ReaderError::InvalidWindow);
        }
        if index > 0 {
            let previous = &request.windows[index - 1];
            let overlap_start = window
                .token_start
                .checked_sub(previous.token_start)
                .ok_or(ReaderError::InvalidWindow)?;
            let overlap_tokens = previous
                .token_end
                .checked_sub(window.token_start)
                .ok_or(ReaderError::InvalidWindow)?;
            if overlap_tokens == 0
                || overlap_start >= previous.tokens.len()
                || overlap_tokens != previous.tokens.len() - overlap_start
                || overlap_tokens > window.tokens.len()
                || previous.tokens[overlap_start..] != window.tokens[..overlap_tokens]
            {
                return Err(ReaderError::InvalidOffset);
            }
        }
    }
    Ok(())
}

fn expected_window_starts(token_count: usize) -> Result<Vec<usize>, ReaderError> {
    if token_count == 0 || token_count > MAX_TOKEN_COUNT {
        return Err(ReaderError::InvalidWindow);
    }
    let regular_limit = token_count
        .saturating_sub(WINDOW_TOKENS)
        .saturating_add(1)
        .max(1);
    let mut starts: Vec<usize> = (0..regular_limit).step_by(WINDOW_STRIDE).collect();
    let final_start = token_count.saturating_sub(WINDOW_TOKENS);
    if starts.last().copied() != Some(final_start) {
        starts.push(final_start);
    }
    if starts.len() > MAX_WINDOWS {
        return Err(ReaderError::InvalidWindow);
    }
    Ok(starts)
}

fn validate_window(context: &str, window: &ReaderWindow) -> Result<(), ReaderError> {
    validate_id(&window.window_id)?;
    if window.tokens.is_empty()
        || window.tokens.len() > WINDOW_TOKENS
        || window.token_end <= window.token_start
        || window.token_end - window.token_start != window.tokens.len()
        || window.raw_end <= window.raw_start
    {
        return Err(ReaderError::InvalidWindow);
    }
    validate_source_range(context, window.raw_start, window.raw_end)?;
    if window.raw_start != window.tokens[0].raw_start
        || window.raw_end != window.tokens.last().expect("tokens are non-empty").raw_end
    {
        return Err(ReaderError::InvalidOffset);
    }
    for (index, token) in window.tokens.iter().enumerate() {
        if token.token.is_empty() || token.raw_end <= token.raw_start {
            return Err(ReaderError::InvalidWindow);
        }
        validate_source_range(context, token.raw_start, token.raw_end)?;
        if source_slice(context, token.raw_start, token.raw_end)? != token.token {
            return Err(ReaderError::InvalidOffset);
        }
        if index > 0 && token.raw_start < window.tokens[index - 1].raw_end {
            return Err(ReaderError::InvalidOffset);
        }
    }
    Ok(())
}

fn validate_prediction_shape(prediction: &ReaderPrediction) -> Result<(), ReaderError> {
    if prediction.schema != ABI_SCHEMA {
        return Err(ReaderError::UnsupportedSchema);
    }
    prediction.identity.validate()?;
    validate_id(&prediction.window_id)?;
    if !matches!(
        prediction.answer_type.as_str(),
        "span" | "yes" | "no" | "null"
    ) {
        return Err(ReaderError::UnsupportedAnswerType);
    }
    if prediction.supporting_facts.len() > MAX_SUPPORTING_FACTS {
        return Err(ReaderError::InvalidShape);
    }
    let mut seen = HashSet::with_capacity(prediction.supporting_facts.len());
    for fact_id in &prediction.supporting_facts {
        validate_id(fact_id)?;
        if !seen.insert(fact_id.as_str()) {
            return Err(ReaderError::DuplicateId);
        }
    }
    if !prediction.null_margin.is_finite() || !prediction.score.is_finite() {
        return Err(ReaderError::NonFinite);
    }
    Ok(())
}

pub fn validate_prediction(
    request: &ReaderRequest,
    prediction: &ReaderPrediction,
) -> Result<(), ReaderError> {
    validate_prediction_with_deadline(request, prediction, Instant::now() + REQUEST_DEADLINE)
}

pub fn validate_prediction_with_deadline(
    request: &ReaderRequest,
    prediction: &ReaderPrediction,
    deadline: Instant,
) -> Result<(), ReaderError> {
    if Instant::now() >= deadline {
        return Err(ReaderError::TimedOut);
    }
    validate_request(request)?;
    if Instant::now() >= deadline {
        return Err(ReaderError::TimedOut);
    }
    validate_prediction_shape(prediction)?;
    request.identity.require_match(&prediction.identity)?;
    let window = request
        .windows
        .iter()
        .find(|window| window.window_id == prediction.window_id)
        .ok_or(ReaderError::UnknownWindow)?;
    let fact_ids: HashSet<&str> = request
        .facts
        .iter()
        .map(|fact| fact.fact_id.as_str())
        .collect();
    if prediction
        .supporting_facts
        .iter()
        .any(|fact_id| !fact_ids.contains(fact_id.as_str()))
    {
        return Err(ReaderError::UnknownSupportingFact);
    }

    let is_null = prediction.answer_type == "null";
    if is_null != (prediction.null_margin >= request.null_threshold) {
        return Err(ReaderError::NullDecisionMismatch);
    }
    if !is_null && prediction.supporting_facts.is_empty() {
        return Err(ReaderError::InvalidShape);
    }
    if is_null || matches!(prediction.answer_type.as_str(), "yes" | "no") {
        if prediction.start_token.is_some()
            || prediction.end_token.is_some()
            || prediction.raw_start.is_some()
            || prediction.raw_end.is_some()
        {
            return Err(ReaderError::InvalidShape);
        }
        return Ok(());
    }

    let (Some(start), Some(end), Some(raw_start), Some(raw_end)) = (
        prediction.start_token,
        prediction.end_token,
        prediction.raw_start,
        prediction.raw_end,
    ) else {
        return Err(ReaderError::InvalidShape);
    };
    if start >= end || end > window.tokens.len() {
        return Err(ReaderError::InvalidShape);
    }
    if raw_start != window.tokens[start].raw_start || raw_end != window.tokens[end - 1].raw_end {
        return Err(ReaderError::InvalidOffset);
    }
    validate_source_range(&request.context, raw_start, raw_end)?;
    if !request.facts.iter().any(|fact| {
        prediction
            .supporting_facts
            .iter()
            .any(|fact_id| fact_id == &fact.fact_id)
            && fact.raw_start <= raw_start
            && raw_end <= fact.raw_end
    }) {
        return Err(ReaderError::InvalidOffset);
    }
    Ok(())
}

pub fn decode_prediction(
    request: &ReaderRequest,
    prediction: &ReaderPrediction,
) -> Result<ReaderAnswer, ReaderError> {
    validate_prediction(request, prediction)?;
    if prediction.answer_type == "null" {
        return Ok(ReaderAnswer {
            answer_type: "null".into(),
            answer: None,
            raw_start: None,
            raw_end: None,
            supporting_facts: prediction.supporting_facts.clone(),
            null_margin: prediction.null_margin,
            window_id: prediction.window_id.clone(),
            abstained: true,
        });
    }
    if matches!(prediction.answer_type.as_str(), "yes" | "no") {
        return Ok(ReaderAnswer {
            answer_type: prediction.answer_type.clone(),
            answer: Some(prediction.answer_type.clone()),
            raw_start: None,
            raw_end: None,
            supporting_facts: prediction.supporting_facts.clone(),
            null_margin: prediction.null_margin,
            window_id: prediction.window_id.clone(),
            abstained: false,
        });
    }
    let start = prediction.raw_start.expect("validated span start");
    let end = prediction.raw_end.expect("validated span end");
    Ok(ReaderAnswer {
        answer_type: "span".into(),
        answer: Some(source_slice(&request.context, start, end)?.to_owned()),
        raw_start: Some(start),
        raw_end: Some(end),
        supporting_facts: prediction.supporting_facts.clone(),
        null_margin: prediction.null_margin,
        window_id: prediction.window_id.clone(),
        abstained: false,
    })
}

pub fn select_prediction(
    request: &ReaderRequest,
    predictions: &[ReaderPrediction],
) -> Result<ReaderAnswer, ReaderError> {
    if predictions.is_empty() {
        return Err(ReaderError::InvalidShape);
    }
    validate_request(request)?;
    if predictions.len() != request.windows.len() {
        return Err(ReaderError::InvalidShape);
    }
    let mut window_ids = HashSet::with_capacity(predictions.len());
    for prediction in predictions {
        validate_prediction(request, prediction)?;
        if !window_ids.insert(prediction.window_id.as_str()) {
            return Err(ReaderError::DuplicateId);
        }
    }
    let selected = predictions
        .iter()
        .max_by(|left, right| {
            left.score
                .partial_cmp(&right.score)
                .unwrap_or(Ordering::Equal)
                .then_with(|| (left.answer_type != "null").cmp(&(right.answer_type != "null")))
                .then_with(|| {
                    right
                        .null_margin
                        .partial_cmp(&left.null_margin)
                        .unwrap_or(Ordering::Equal)
                })
                .then_with(|| left.window_id.cmp(&right.window_id))
        })
        .expect("predictions are non-empty");
    decode_prediction(request, selected)
}

pub fn validate_logits(request: &ReaderRequest, logits: &ReaderLogits) -> Result<(), ReaderError> {
    validate_request(request)?;
    if logits.schema != ABI_SCHEMA {
        return Err(ReaderError::UnsupportedSchema);
    }
    request.identity.require_match(&logits.identity)?;
    let window = request
        .windows
        .iter()
        .find(|window| window.window_id == logits.window_id)
        .ok_or(ReaderError::UnknownWindow)?;
    if logits.start_logits.len() != window.tokens.len()
        || logits.end_logits.len() != window.tokens.len()
        || logits.supporting_fact_logits.len() != request.facts.len()
    {
        return Err(ReaderError::InvalidShape);
    }
    if logits
        .start_logits
        .iter()
        .chain(&logits.end_logits)
        .chain(&logits.supporting_fact_logits)
        .chain(
            [
                logits.answer_type_logits.span,
                logits.answer_type_logits.yes,
                logits.answer_type_logits.no,
                logits.null_logit,
            ]
            .iter(),
        )
        .any(|score| !score.is_finite())
    {
        return Err(ReaderError::NonFinite);
    }
    Ok(())
}

pub fn decode_logits(
    request: &ReaderRequest,
    logits: &ReaderLogits,
) -> Result<ReaderPrediction, ReaderError> {
    validate_logits(request, logits)?;
    let window = request
        .windows
        .iter()
        .find(|window| window.window_id == logits.window_id)
        .expect("validated window");
    let mut best_pair = (0usize, 0usize, f32::NEG_INFINITY);
    for (start, start_score) in logits.start_logits.iter().enumerate() {
        for (end, end_score) in logits.end_logits.iter().enumerate().skip(start) {
            let score = *start_score + *end_score;
            if !score.is_finite() {
                return Err(ReaderError::NonFinite);
            }
            if score > best_pair.2
                || (score == best_pair.2 && (start, end) < (best_pair.0, best_pair.1))
            {
                best_pair = (start, end, score);
            }
        }
    }
    let span_score = logits.answer_type_logits.span + best_pair.2;
    if !span_score.is_finite() {
        return Err(ReaderError::NonFinite);
    }
    let type_scores = [
        ("span", span_score),
        ("yes", logits.answer_type_logits.yes),
        ("no", logits.answer_type_logits.no),
    ];
    let best_type = type_scores.iter().fold(&type_scores[0], |best, candidate| {
        if candidate.1 > best.1 {
            candidate
        } else {
            best
        }
    });
    let best_non_null = *best_type.1;
    let null_margin = logits.null_logit - best_non_null;
    if !null_margin.is_finite() {
        return Err(ReaderError::NonFinite);
    }
    let answer_type = if null_margin >= request.null_threshold {
        "null"
    } else {
        best_type.0
    };
    let (start_token, end_token, raw_start, raw_end) = if answer_type == "span" {
        (
            Some(best_pair.0),
            Some(best_pair.1 + 1),
            Some(window.tokens[best_pair.0].raw_start),
            Some(window.tokens[best_pair.1].raw_end),
        )
    } else {
        (None, None, None, None)
    };
    let supporting_facts: Vec<String> = logits
        .supporting_fact_logits
        .iter()
        .enumerate()
        .filter_map(|(index, score)| (*score > 0.0).then(|| request.facts[index].fact_id.clone()))
        .collect();
    if supporting_facts.len() > MAX_SUPPORTING_FACTS {
        return Err(ReaderError::InvalidShape);
    }
    let prediction = ReaderPrediction {
        schema: ABI_SCHEMA.into(),
        identity: request.identity.clone(),
        window_id: logits.window_id.clone(),
        answer_type: answer_type.into(),
        start_token,
        end_token,
        raw_start,
        raw_end,
        supporting_facts,
        null_margin,
        score: best_non_null,
    };
    validate_prediction(request, &prediction)?;
    Ok(prediction)
}

fn validate_id(value: &str) -> Result<(), ReaderError> {
    if value.is_empty()
        || value.trim() != value
        || value.chars().count() > MAX_ID_CHARS
        || value.chars().any(char::is_control)
    {
        return Err(ReaderError::InvalidIdentity);
    }
    Ok(())
}

fn validate_digest(value: &str) -> Result<(), ReaderError> {
    if value.chars().count() != DIGEST_CHARS
        || value
            .bytes()
            .any(|byte| !byte.is_ascii_hexdigit() || byte.is_ascii_uppercase())
    {
        return Err(ReaderError::InvalidIdentity);
    }
    Ok(())
}

fn validate_source_range(context: &str, start: usize, end: usize) -> Result<(), ReaderError> {
    if start >= end || end > context.as_bytes().len() {
        return Err(ReaderError::InvalidOffset);
    }
    if !context.is_char_boundary(start) || !context.is_char_boundary(end) {
        return Err(ReaderError::InvalidOffset);
    }
    Ok(())
}

fn source_slice(context: &str, start: usize, end: usize) -> Result<&str, ReaderError> {
    validate_source_range(context, start, end)?;
    context.get(start..end).ok_or(ReaderError::InvalidOffset)
}

#[cfg(test)]
mod tests {
    use super::*;

    const DIGEST: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    fn identity() -> ReaderIdentity {
        ReaderIdentity {
            model_id: "model:reader-dev-v1".into(),
            artifact_id: "artifact:reader-dev".into(),
            artifact_sha256: DIGEST.into(),
            preprocessing_id: "preprocess:unicode-v1".into(),
            preprocessing_sha256: DIGEST.into(),
        }
    }

    fn request() -> ReaderRequest {
        ReaderRequest {
            schema: ABI_SCHEMA.into(),
            identity: identity(),
            query: "which city?".into(),
            context: "The answer is Paris.".into(),
            facts: vec![SupportingFact {
                fact_id: "fact-1".into(),
                raw_start: 0,
                raw_end: 20,
                text: "The answer is Paris.".into(),
            }],
            windows: vec![ReaderWindow {
                window_id: "window-000".into(),
                token_start: 0,
                token_end: 4,
                raw_start: 0,
                raw_end: 20,
                tokens: vec![
                    TokenSpan {
                        token: "The".into(),
                        raw_start: 0,
                        raw_end: 3,
                    },
                    TokenSpan {
                        token: "answer".into(),
                        raw_start: 4,
                        raw_end: 10,
                    },
                    TokenSpan {
                        token: "is".into(),
                        raw_start: 11,
                        raw_end: 13,
                    },
                    TokenSpan {
                        token: "Paris.".into(),
                        raw_start: 14,
                        raw_end: 20,
                    },
                ],
            }],
            null_threshold: 0.5,
        }
    }

    #[test]
    fn span_reconstructs_exact_source_bytes() {
        let request = request();
        validate_request(&request).unwrap();
        let prediction = ReaderPrediction {
            schema: ABI_SCHEMA.into(),
            identity: identity(),
            window_id: "window-000".into(),
            answer_type: "span".into(),
            start_token: Some(3),
            end_token: Some(4),
            raw_start: Some(14),
            raw_end: Some(20),
            supporting_facts: vec!["fact-1".into()],
            null_margin: 0.0,
            score: 1.0,
        };
        let answer = decode_prediction(&request, &prediction).unwrap();
        assert_eq!(answer.answer.as_deref(), Some("Paris."));
        assert_eq!(answer.raw_start, Some(14));
    }

    #[test]
    fn null_yes_no_and_unsupported_types_are_bounded() {
        let request = request();
        let mut yes = ReaderPrediction {
            schema: ABI_SCHEMA.into(),
            identity: identity(),
            window_id: "window-000".into(),
            answer_type: "yes".into(),
            start_token: None,
            end_token: None,
            raw_start: None,
            raw_end: None,
            supporting_facts: vec!["fact-1".into()],
            null_margin: 0.0,
            score: 1.0,
        };
        assert_eq!(
            decode_prediction(&request, &yes).unwrap().answer.as_deref(),
            Some("yes")
        );
        yes.answer_type = "null".into();
        yes.null_margin = 1.0;
        assert!(decode_prediction(&request, &yes).unwrap().abstained);
        yes.answer_type = "long_form".into();
        assert_eq!(
            validate_prediction(&request, &yes),
            Err(ReaderError::UnsupportedAnswerType)
        );
    }

    #[test]
    fn rejects_drifted_identity_nonfinite_and_bad_utf8_offsets() {
        let request = request();
        let mut prediction = ReaderPrediction {
            schema: ABI_SCHEMA.into(),
            identity: identity(),
            window_id: "window-000".into(),
            answer_type: "span".into(),
            start_token: Some(3),
            end_token: Some(4),
            raw_start: Some(13),
            raw_end: Some(20),
            supporting_facts: vec!["fact-1".into()],
            null_margin: 0.0,
            score: 1.0,
        };
        assert_eq!(
            validate_prediction(&request, &prediction),
            Err(ReaderError::InvalidOffset)
        );
        prediction.raw_start = Some(14);
        prediction.identity.model_id.push_str("-drift");
        assert_eq!(
            validate_prediction(&request, &prediction),
            Err(ReaderError::IdentityMismatch)
        );
        prediction.identity = identity();
        prediction.score = f32::NAN;
        assert_eq!(
            validate_prediction(&request, &prediction),
            Err(ReaderError::NonFinite)
        );
    }

    #[test]
    fn expired_deadline_is_fail_closed_by_caller() {
        let request = request();
        let prediction = ReaderPrediction {
            schema: ABI_SCHEMA.into(),
            identity: identity(),
            window_id: "window-000".into(),
            answer_type: "yes".into(),
            start_token: None,
            end_token: None,
            raw_start: None,
            raw_end: None,
            supporting_facts: vec![],
            null_margin: 0.0,
            score: 1.0,
        };
        let deadline = Instant::now() - Duration::from_millis(1);
        assert_eq!(
            validate_prediction_with_deadline(&request, &prediction, deadline),
            Err(ReaderError::TimedOut)
        );
    }

    #[test]
    fn logits_are_validated_before_return() {
        let request = request();
        let logits = ReaderLogits {
            schema: ABI_SCHEMA.into(),
            identity: identity(),
            window_id: "window-000".into(),
            start_logits: vec![0.0; 4],
            end_logits: vec![0.0; 4],
            answer_type_logits: AnswerTypeLogits {
                span: 0.0,
                yes: 1.0,
                no: 0.0,
            },
            supporting_fact_logits: vec![-1.0],
            null_logit: -1.0,
        };
        assert_eq!(
            decode_logits(&request, &logits),
            Err(ReaderError::InvalidShape)
        );
    }

    #[test]
    fn windows_must_cover_the_full_source_context() {
        let mut request = request();
        request.windows[0].tokens.truncate(1);
        request.windows[0].token_end = 1;
        request.windows[0].raw_end = 3;
        assert_eq!(validate_request(&request), Err(ReaderError::InvalidOffset));
    }

    #[test]
    fn spans_must_be_grounded_in_supporting_facts() {
        let mut request = request();
        request.facts[0].raw_end = 3;
        request.facts[0].text = "The".into();
        let prediction = ReaderPrediction {
            schema: ABI_SCHEMA.into(),
            identity: identity(),
            window_id: "window-000".into(),
            answer_type: "span".into(),
            start_token: Some(3),
            end_token: Some(4),
            raw_start: Some(14),
            raw_end: Some(20),
            supporting_facts: vec!["fact-1".into()],
            null_margin: 0.0,
            score: 1.0,
        };
        assert_eq!(
            validate_prediction(&request, &prediction),
            Err(ReaderError::InvalidOffset)
        );
    }
}

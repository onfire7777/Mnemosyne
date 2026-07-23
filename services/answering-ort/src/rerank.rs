//! Strict, model-agnostic reranker ABI.
//!
//! This module is intentionally standalone.  The transport/runtime wiring is
//! leased to another lane; this file defines the contract that a future model
//! adapter must satisfy before its scores can be admitted to the answering
//! path.  It does not load a model, make network requests, or provide a
//! fallback scorer.

use serde::de::{self, MapAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use std::cmp::Ordering;
use std::collections::HashSet;
use std::fmt;
use std::time::{Duration, Instant};

pub const ABI_SCHEMA: &str = "mnemosyne.compact-answering-reranker.v1";
pub const MAX_REQUEST_BYTES: usize = 64 * 1024;
pub const MAX_QUERY_CHARS: usize = 2_000;
pub const MAX_CANDIDATES: usize = 20;
pub const MAX_CANDIDATE_CHARS: usize = 24_000;
pub const MAX_ID_CHARS: usize = 256;
pub const MAX_RANK_WIDTH: usize = 8;
pub const REQUEST_DEADLINE: Duration = Duration::from_secs(30);

const DIGEST_CHARS: usize = 64;

/// A digest-bound model/artifact/preprocessing identity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RerankIdentity {
    pub model_id: String,
    pub artifact_id: String,
    pub artifact_sha256: String,
    pub preprocessing_id: String,
    pub preprocessing_sha256: String,
}

/// One source-owned evidence row presented to the reranker.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RerankCandidate {
    pub evidence_id: String,
    pub text: String,
}

/// One finite scalar score returned for an evidence row.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RerankScore {
    pub evidence_id: String,
    pub score: f32,
}

/// Versioned request sent to a reranker adapter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RerankRequest {
    pub schema: String,
    pub identity: RerankIdentity,
    pub query: String,
    pub candidates: Vec<RerankCandidate>,
    pub rank_width: usize,
}

/// Versioned response returned by a reranker adapter.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RerankResponse {
    pub schema: String,
    pub identity: RerankIdentity,
    pub scores: Vec<RerankScore>,
}

/// A fail-closed ABI validation error.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RerankError {
    MalformedPayload,
    RequestTooLarge,
    LimitExceeded,
    InvalidIdentity,
    IdentityMismatch,
    NonFiniteScore,
    UnknownEvidenceId,
    DuplicateEvidenceId,
    IncompleteScores,
    TimedOut,
}

impl RerankRequest {
    /// Construct a request with the only supported ABI schema version.
    pub fn new(
        identity: RerankIdentity,
        query: String,
        candidates: Vec<RerankCandidate>,
        rank_width: usize,
    ) -> Result<Self, RerankError> {
        let request = Self {
            schema: ABI_SCHEMA.to_owned(),
            identity,
            query,
            candidates,
            rank_width,
        };
        validate_request(&request)?;
        Ok(request)
    }
}

impl RerankResponse {
    /// Construct a response with the only supported ABI schema version.
    pub fn new(identity: RerankIdentity, scores: Vec<RerankScore>) -> Self {
        Self {
            schema: ABI_SCHEMA.to_owned(),
            identity,
            scores,
        }
    }
}

/// Parse and validate one bounded request payload.
pub fn parse_request(payload: &[u8]) -> Result<RerankRequest, RerankError> {
    if payload.len() > MAX_REQUEST_BYTES {
        return Err(RerankError::RequestTooLarge);
    }
    let request = serde_json::from_slice(payload).map_err(|_| RerankError::MalformedPayload)?;
    validate_request(&request)?;
    Ok(request)
}

/// Parse one bounded response payload.  Identity and candidate binding are
/// checked separately by [`validate_response`], because they require the
/// request that produced the response.
pub fn parse_response(payload: &[u8]) -> Result<RerankResponse, RerankError> {
    if payload.len() > MAX_REQUEST_BYTES {
        return Err(RerankError::RequestTooLarge);
    }
    serde_json::from_slice(payload).map_err(|_| RerankError::MalformedPayload)
}

/// Validate a response and return its deterministic top-k ordering.
pub fn validate_response(
    request: &RerankRequest,
    response: &RerankResponse,
) -> Result<Vec<RerankScore>, RerankError> {
    validate_response_with_deadline(request, response, Instant::now() + REQUEST_DEADLINE)
}

/// Validate a response against the request identity and candidate set, while
/// honoring the caller's hard deadline.  A timeout is checked before any
/// response data is admitted.
pub fn validate_response_with_deadline(
    request: &RerankRequest,
    response: &RerankResponse,
    deadline: Instant,
) -> Result<Vec<RerankScore>, RerankError> {
    if Instant::now() >= deadline {
        return Err(RerankError::TimedOut);
    }
    validate_request(request)?;
    if response.schema != ABI_SCHEMA {
        return Err(RerankError::MalformedPayload);
    }
    if response.identity != request.identity {
        return Err(RerankError::IdentityMismatch);
    }
    if response.scores.len() > MAX_CANDIDATES {
        return Err(RerankError::LimitExceeded);
    }
    if response.scores.len() != request.candidates.len() {
        return Err(RerankError::IncompleteScores);
    }

    let known_ids: HashSet<&str> = request
        .candidates
        .iter()
        .map(|candidate| candidate.evidence_id.as_str())
        .collect();
    let mut seen = HashSet::with_capacity(response.scores.len());
    for row in &response.scores {
        if !seen.insert(row.evidence_id.as_str()) {
            return Err(RerankError::DuplicateEvidenceId);
        }
        if !known_ids.contains(row.evidence_id.as_str()) {
            return Err(RerankError::UnknownEvidenceId);
        }
        if !row.score.is_finite() {
            return Err(RerankError::NonFiniteScore);
        }
        if Instant::now() >= deadline {
            return Err(RerankError::TimedOut);
        }
    }

    let mut ordered = response.scores.clone();
    ordered.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(Ordering::Equal)
            .then_with(|| left.evidence_id.cmp(&right.evidence_id))
    });
    ordered.truncate(request.rank_width);
    Ok(ordered)
}

/// Parse, validate, and rank a response payload in one fail-closed call.
pub fn rank_payload(
    request: &RerankRequest,
    payload: &[u8],
) -> Result<Vec<RerankScore>, RerankError> {
    let response = parse_response(payload)?;
    validate_response(request, &response)
}

fn validate_request(request: &RerankRequest) -> Result<(), RerankError> {
    if request.schema != ABI_SCHEMA {
        return Err(RerankError::MalformedPayload);
    }
    validate_identity(&request.identity)?;
    if request.query.chars().count() > MAX_QUERY_CHARS {
        return Err(RerankError::LimitExceeded);
    }
    if request.candidates.len() > MAX_CANDIDATES {
        return Err(RerankError::LimitExceeded);
    }
    if request.rank_width == 0 || request.rank_width > MAX_RANK_WIDTH {
        return Err(RerankError::LimitExceeded);
    }

    let mut total_chars = 0usize;
    let mut ids = HashSet::with_capacity(request.candidates.len());
    for candidate in &request.candidates {
        validate_bounded_id(&candidate.evidence_id)?;
        if !ids.insert(candidate.evidence_id.as_str()) {
            return Err(RerankError::DuplicateEvidenceId);
        }
        total_chars = total_chars.saturating_add(candidate.text.chars().count());
        if total_chars > MAX_CANDIDATE_CHARS {
            return Err(RerankError::LimitExceeded);
        }
    }
    Ok(())
}

fn validate_identity(identity: &RerankIdentity) -> Result<(), RerankError> {
    validate_bounded_id(&identity.model_id)?;
    validate_bounded_id(&identity.artifact_id)?;
    validate_bounded_id(&identity.preprocessing_id)?;
    validate_digest(&identity.artifact_sha256)?;
    validate_digest(&identity.preprocessing_sha256)
}

fn validate_bounded_id(value: &str) -> Result<(), RerankError> {
    if value.is_empty() || value != value.trim() || value.chars().count() > MAX_ID_CHARS {
        return Err(RerankError::InvalidIdentity);
    }
    Ok(())
}

fn validate_digest(value: &str) -> Result<(), RerankError> {
    if value.chars().count() != DIGEST_CHARS
        || value
            .bytes()
            .any(|byte| !byte.is_ascii_hexdigit() || byte.is_ascii_uppercase())
    {
        return Err(RerankError::InvalidIdentity);
    }
    Ok(())
}

const IDENTITY_FIELDS: &[&str] = &[
    "model_id",
    "artifact_id",
    "artifact_sha256",
    "preprocessing_id",
    "preprocessing_sha256",
];

const CANDIDATE_FIELDS: &[&str] = &["evidence_id", "text"];
const SCORE_FIELDS: &[&str] = &["evidence_id", "score"];
const REQUEST_FIELDS: &[&str] = &["schema", "identity", "query", "candidates", "rank_width"];
const RESPONSE_FIELDS: &[&str] = &["schema", "identity", "scores"];

impl<'de> Deserialize<'de> for RerankIdentity {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct IdentityVisitor;

        impl<'de> Visitor<'de> for IdentityVisitor {
            type Value = RerankIdentity;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a strict reranker identity object")
            }

            fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                let mut model_id = None;
                let mut artifact_id = None;
                let mut artifact_sha256 = None;
                let mut preprocessing_id = None;
                let mut preprocessing_sha256 = None;
                while let Some(key) = map.next_key::<String>()? {
                    match key.as_str() {
                        "model_id" => set_once(&mut model_id, &mut map, "model_id")?,
                        "artifact_id" => set_once(&mut artifact_id, &mut map, "artifact_id")?,
                        "artifact_sha256" => {
                            set_once(&mut artifact_sha256, &mut map, "artifact_sha256")?
                        }
                        "preprocessing_id" => {
                            set_once(&mut preprocessing_id, &mut map, "preprocessing_id")?
                        }
                        "preprocessing_sha256" => {
                            set_once(&mut preprocessing_sha256, &mut map, "preprocessing_sha256")?
                        }
                        _ => return Err(de::Error::unknown_field(&key, IDENTITY_FIELDS)),
                    }
                }
                Ok(RerankIdentity {
                    model_id: required(model_id, "model_id")?,
                    artifact_id: required(artifact_id, "artifact_id")?,
                    artifact_sha256: required(artifact_sha256, "artifact_sha256")?,
                    preprocessing_id: required(preprocessing_id, "preprocessing_id")?,
                    preprocessing_sha256: required(preprocessing_sha256, "preprocessing_sha256")?,
                })
            }
        }

        deserializer.deserialize_map(IdentityVisitor)
    }
}

impl<'de> Deserialize<'de> for RerankCandidate {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct CandidateVisitor;

        impl<'de> Visitor<'de> for CandidateVisitor {
            type Value = RerankCandidate;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a strict reranker candidate object")
            }

            fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                let mut evidence_id = None;
                let mut text = None;
                while let Some(key) = map.next_key::<String>()? {
                    match key.as_str() {
                        "evidence_id" => set_once(&mut evidence_id, &mut map, "evidence_id")?,
                        "text" => set_once(&mut text, &mut map, "text")?,
                        _ => return Err(de::Error::unknown_field(&key, CANDIDATE_FIELDS)),
                    }
                }
                Ok(RerankCandidate {
                    evidence_id: required(evidence_id, "evidence_id")?,
                    text: required(text, "text")?,
                })
            }
        }

        deserializer.deserialize_map(CandidateVisitor)
    }
}

impl<'de> Deserialize<'de> for RerankScore {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct ScoreVisitor;

        impl<'de> Visitor<'de> for ScoreVisitor {
            type Value = RerankScore;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a strict reranker score object")
            }

            fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                let mut evidence_id = None;
                let mut score = None;
                while let Some(key) = map.next_key::<String>()? {
                    match key.as_str() {
                        "evidence_id" => set_once(&mut evidence_id, &mut map, "evidence_id")?,
                        "score" => set_once(&mut score, &mut map, "score")?,
                        _ => return Err(de::Error::unknown_field(&key, SCORE_FIELDS)),
                    }
                }
                Ok(RerankScore {
                    evidence_id: required(evidence_id, "evidence_id")?,
                    score: required(score, "score")?,
                })
            }
        }

        deserializer.deserialize_map(ScoreVisitor)
    }
}

impl<'de> Deserialize<'de> for RerankRequest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct RequestVisitor;

        impl<'de> Visitor<'de> for RequestVisitor {
            type Value = RerankRequest;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a strict versioned reranker request object")
            }

            fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                let mut schema = None;
                let mut identity = None;
                let mut query = None;
                let mut candidates = None;
                let mut rank_width = None;
                while let Some(key) = map.next_key::<String>()? {
                    match key.as_str() {
                        "schema" => set_once(&mut schema, &mut map, "schema")?,
                        "identity" => set_once(&mut identity, &mut map, "identity")?,
                        "query" => set_once(&mut query, &mut map, "query")?,
                        "candidates" => set_once(&mut candidates, &mut map, "candidates")?,
                        "rank_width" => set_once(&mut rank_width, &mut map, "rank_width")?,
                        _ => return Err(de::Error::unknown_field(&key, REQUEST_FIELDS)),
                    }
                }
                Ok(RerankRequest {
                    schema: required(schema, "schema")?,
                    identity: required(identity, "identity")?,
                    query: required(query, "query")?,
                    candidates: required(candidates, "candidates")?,
                    rank_width: required(rank_width, "rank_width")?,
                })
            }
        }

        deserializer.deserialize_map(RequestVisitor)
    }
}

impl<'de> Deserialize<'de> for RerankResponse {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct ResponseVisitor;

        impl<'de> Visitor<'de> for ResponseVisitor {
            type Value = RerankResponse;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a strict versioned reranker response object")
            }

            fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                let mut schema = None;
                let mut identity = None;
                let mut scores = None;
                while let Some(key) = map.next_key::<String>()? {
                    match key.as_str() {
                        "schema" => set_once(&mut schema, &mut map, "schema")?,
                        "identity" => set_once(&mut identity, &mut map, "identity")?,
                        "scores" => set_once(&mut scores, &mut map, "scores")?,
                        _ => return Err(de::Error::unknown_field(&key, RESPONSE_FIELDS)),
                    }
                }
                Ok(RerankResponse {
                    schema: required(schema, "schema")?,
                    identity: required(identity, "identity")?,
                    scores: required(scores, "scores")?,
                })
            }
        }

        deserializer.deserialize_map(ResponseVisitor)
    }
}

fn set_once<'de, A, T>(
    slot: &mut Option<T>,
    map: &mut A,
    field: &'static str,
) -> Result<(), A::Error>
where
    A: MapAccess<'de>,
    T: Deserialize<'de>,
{
    if slot.is_some() {
        return Err(de::Error::duplicate_field(field));
    }
    *slot = Some(map.next_value()?);
    Ok(())
}

fn required<T, E>(value: Option<T>, field: &'static str) -> Result<T, E>
where
    E: de::Error,
{
    value.ok_or_else(|| de::Error::missing_field(field))
}

#[cfg(test)]
mod tests {
    use super::*;

    const DIGEST: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    fn identity() -> RerankIdentity {
        RerankIdentity {
            model_id: "model:ettin-reranker-dev-v1".into(),
            artifact_id: "artifact:reranker-dev".into(),
            artifact_sha256: DIGEST.into(),
            preprocessing_id: "preprocess:unicode-lower-v1".into(),
            preprocessing_sha256: DIGEST.into(),
        }
    }

    fn request() -> RerankRequest {
        RerankRequest::new(
            identity(),
            "which city?".into(),
            vec![
                RerankCandidate {
                    evidence_id: "evidence-b".into(),
                    text: "Berlin".into(),
                },
                RerankCandidate {
                    evidence_id: "evidence-a".into(),
                    text: "Paris".into(),
                },
            ],
            2,
        )
        .unwrap()
    }

    fn response(scores: Vec<RerankScore>) -> RerankResponse {
        RerankResponse::new(identity(), scores)
    }

    #[test]
    fn parses_exact_versioned_request_and_response() {
        let request = request();
        let request_json = serde_json::to_vec(&request).unwrap();
        let parsed_request = parse_request(&request_json).unwrap();
        assert_eq!(parsed_request, request);

        let response = response(vec![
            RerankScore {
                evidence_id: "evidence-a".into(),
                score: 0.5,
            },
            RerankScore {
                evidence_id: "evidence-b".into(),
                score: 0.5,
            },
        ]);
        let parsed_response = parse_response(&serde_json::to_vec(&response).unwrap()).unwrap();
        assert_eq!(parsed_response, response);
    }

    #[test]
    fn orders_scores_descending_then_by_evidence_id_and_caps_width() {
        let mut request = request();
        request.candidates.push(RerankCandidate {
            evidence_id: "evidence-c".into(),
            text: "Rome".into(),
        });
        request.rank_width = 2;
        let ranked = validate_response(
            &request,
            &response(vec![
                RerankScore {
                    evidence_id: "evidence-b".into(),
                    score: 0.5,
                },
                RerankScore {
                    evidence_id: "evidence-c".into(),
                    score: 0.9,
                },
                RerankScore {
                    evidence_id: "evidence-a".into(),
                    score: 0.5,
                },
            ]),
        )
        .unwrap();
        assert_eq!(
            ranked
                .iter()
                .map(|row| row.evidence_id.as_str())
                .collect::<Vec<_>>(),
            ["evidence-c", "evidence-a"]
        );
    }

    #[test]
    fn rejects_duplicate_and_unknown_json_fields() {
        let request = serde_json::to_string(&request()).unwrap();
        let duplicate = request.replacen(
            "\"schema\":\"mnemosyne.compact-answering-reranker.v1\",",
            "\"schema\":\"mnemosyne.compact-answering-reranker.v1\",\"schema\":\"mnemosyne.compact-answering-reranker.v1\",",
            1,
        );
        assert_eq!(
            parse_request(duplicate.as_bytes()),
            Err(RerankError::MalformedPayload)
        );

        let unknown = request.replacen("{\"schema\":", "{\"unexpected\":true,\"schema\":", 1);
        assert_eq!(
            parse_request(unknown.as_bytes()),
            Err(RerankError::MalformedPayload)
        );
    }

    #[test]
    fn rejects_limits_identity_drift_and_nonfinite_scores() {
        let mut oversized_query = request();
        oversized_query.query = "q".repeat(MAX_QUERY_CHARS + 1);
        assert_eq!(
            validate_request(&oversized_query),
            Err(RerankError::LimitExceeded)
        );

        let mut bad_width = request();
        bad_width.rank_width = MAX_RANK_WIDTH + 1;
        assert_eq!(
            validate_request(&bad_width),
            Err(RerankError::LimitExceeded)
        );

        let mut drifted = response(vec![
            RerankScore {
                evidence_id: "evidence-a".into(),
                score: 1.0,
            },
            RerankScore {
                evidence_id: "evidence-b".into(),
                score: 0.0,
            },
        ]);
        drifted.identity.preprocessing_id.push_str("-drift");
        assert_eq!(
            validate_response(&request(), &drifted),
            Err(RerankError::IdentityMismatch)
        );

        let nonfinite = response(vec![
            RerankScore {
                evidence_id: "evidence-a".into(),
                score: f32::NAN,
            },
            RerankScore {
                evidence_id: "evidence-b".into(),
                score: 0.0,
            },
        ]);
        assert_eq!(
            validate_response(&request(), &nonfinite),
            Err(RerankError::NonFiniteScore)
        );
    }

    #[test]
    fn rejects_unknown_duplicate_and_incomplete_scores() {
        let unknown = response(vec![
            RerankScore {
                evidence_id: "evidence-a".into(),
                score: 1.0,
            },
            RerankScore {
                evidence_id: "unknown".into(),
                score: 0.0,
            },
        ]);
        assert_eq!(
            validate_response(&request(), &unknown),
            Err(RerankError::UnknownEvidenceId)
        );

        let duplicate = response(vec![
            RerankScore {
                evidence_id: "evidence-a".into(),
                score: 1.0,
            },
            RerankScore {
                evidence_id: "evidence-a".into(),
                score: 0.0,
            },
        ]);
        assert_eq!(
            validate_response(&request(), &duplicate),
            Err(RerankError::DuplicateEvidenceId)
        );

        let incomplete = response(vec![RerankScore {
            evidence_id: "evidence-a".into(),
            score: 1.0,
        }]);
        assert_eq!(
            validate_response(&request(), &incomplete),
            Err(RerankError::IncompleteScores)
        );
    }

    #[test]
    fn rejects_expired_deadline_before_admitting_scores() {
        let deadline = Instant::now() - Duration::from_millis(1);
        let result = validate_response_with_deadline(
            &request(),
            &response(vec![
                RerankScore {
                    evidence_id: "evidence-a".into(),
                    score: 1.0,
                },
                RerankScore {
                    evidence_id: "evidence-b".into(),
                    score: 0.0,
                },
            ]),
            deadline,
        );
        assert_eq!(result, Err(RerankError::TimedOut));
    }
}

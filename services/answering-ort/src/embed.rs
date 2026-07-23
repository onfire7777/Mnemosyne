//! Versioned, fail-closed embedder contract.
//!
//! This module deliberately owns the ABI boundary instead of model loading. A
//! later sidecar integration can attach an inference implementation without
//! changing identity, dimension, or ranking semantics.

use std::cmp::Ordering;
use std::fmt;

pub const EMBEDDER_ABI: &str = "mnemosyne.embedder.v1";
pub const EMBEDDER_ABI_VERSION: u16 = 1;
pub const NATIVE_DIMENSIONS: usize = 768;
pub const PADDED_DIMENSIONS: usize = 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IdentityField {
    Artifact,
    Tokenizer,
    Preprocessing,
    ModelSpace,
}

impl fmt::Display for IdentityField {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let name = match self {
            Self::Artifact => "artifact",
            Self::Tokenizer => "tokenizer",
            Self::Preprocessing => "preprocessing",
            Self::ModelSpace => "model_space",
        };
        formatter.write_str(name)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EmbedError {
    InvalidAbiVersion { expected: u16, actual: u16 },
    InvalidIdentity { field: IdentityField },
    IdentityMismatch { field: IdentityField },
    EmptyInputBatch,
    InvalidInput { index: usize },
    InvalidVectorCount { expected: usize, actual: usize },
    InvalidDimensions { expected: usize, actual: usize },
    NonFiniteVector { index: usize },
    ZeroVector { index: usize },
    InvalidPadding { index: usize },
    DuplicateCandidateId,
    EmptyCandidateId,
    InvalidRankLimit,
}

impl fmt::Display for EmbedError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidAbiVersion { expected, actual } => {
                write!(
                    formatter,
                    "unsupported ABI version {actual}; expected {expected}"
                )
            }
            Self::InvalidIdentity { field } => write!(formatter, "invalid {field} identity"),
            Self::IdentityMismatch { field } => write!(formatter, "{field} identity mismatch"),
            Self::EmptyInputBatch => formatter.write_str("embed request must contain input"),
            Self::InvalidInput { index } => write!(formatter, "invalid input at index {index}"),
            Self::InvalidVectorCount { expected, actual } => {
                write!(formatter, "expected {expected} vectors, received {actual}")
            }
            Self::InvalidDimensions { expected, actual } => {
                write!(
                    formatter,
                    "expected {expected} dimensions, received {actual}"
                )
            }
            Self::NonFiniteVector { index } => write!(formatter, "vector {index} is non-finite"),
            Self::ZeroVector { index } => write!(formatter, "vector {index} is zero"),
            Self::InvalidPadding { index } => {
                write!(formatter, "vector {index} is not zero-padded")
            }
            Self::DuplicateCandidateId => formatter.write_str("candidate IDs must be unique"),
            Self::EmptyCandidateId => formatter.write_str("candidate IDs must be non-empty"),
            Self::InvalidRankLimit => formatter.write_str("rank limit must be greater than zero"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmbedderIdentity {
    pub artifact: String,
    pub tokenizer: String,
    pub preprocessing: String,
    pub model_space: String,
}

impl EmbedderIdentity {
    pub fn validate(&self) -> Result<(), EmbedError> {
        validate_identity_value(IdentityField::Artifact, &self.artifact)?;
        validate_identity_value(IdentityField::Tokenizer, &self.tokenizer)?;
        validate_identity_value(IdentityField::Preprocessing, &self.preprocessing)?;
        validate_identity_value(IdentityField::ModelSpace, &self.model_space)
    }

    pub fn matches(&self, expected: &Self) -> Result<(), EmbedError> {
        self.validate()?;
        expected.validate()?;
        for (field, actual, expected_value) in [
            (IdentityField::Artifact, &self.artifact, &expected.artifact),
            (
                IdentityField::Tokenizer,
                &self.tokenizer,
                &expected.tokenizer,
            ),
            (
                IdentityField::Preprocessing,
                &self.preprocessing,
                &expected.preprocessing,
            ),
            (
                IdentityField::ModelSpace,
                &self.model_space,
                &expected.model_space,
            ),
        ] {
            if actual != expected_value {
                return Err(EmbedError::IdentityMismatch { field });
            }
        }
        Ok(())
    }
}

fn validate_identity_value(field: IdentityField, value: &str) -> Result<(), EmbedError> {
    if value.is_empty() || value.trim() != value || value.chars().any(char::is_control) {
        return Err(EmbedError::InvalidIdentity { field });
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EmbedSpace {
    Native768,
    Padded1024,
}

impl EmbedSpace {
    pub const fn dimensions(self) -> usize {
        match self {
            Self::Native768 => NATIVE_DIMENSIONS,
            Self::Padded1024 => PADDED_DIMENSIONS,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmbedRequest {
    pub abi_version: u16,
    pub identity: EmbedderIdentity,
    pub inputs: Vec<String>,
    pub space: EmbedSpace,
}

impl EmbedRequest {
    pub fn validate(&self, expected_identity: &EmbedderIdentity) -> Result<(), EmbedError> {
        validate_abi_version(self.abi_version)?;
        self.identity.matches(expected_identity)?;
        if self.inputs.is_empty() {
            return Err(EmbedError::EmptyInputBatch);
        }
        for (index, input) in self.inputs.iter().enumerate() {
            if input.chars().any(char::is_control) {
                return Err(EmbedError::InvalidInput { index });
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct EmbedResponse {
    pub abi_version: u16,
    pub identity: EmbedderIdentity,
    pub space: EmbedSpace,
    pub vectors: Vec<Vec<f32>>,
}

impl EmbedResponse {
    pub fn validate(
        &self,
        request: &EmbedRequest,
        expected_identity: &EmbedderIdentity,
    ) -> Result<(), EmbedError> {
        request.validate(expected_identity)?;
        validate_abi_version(self.abi_version)?;
        self.identity.matches(expected_identity)?;
        if self.space != request.space {
            return Err(EmbedError::IdentityMismatch {
                field: IdentityField::ModelSpace,
            });
        }
        if self.vectors.len() != request.inputs.len() {
            return Err(EmbedError::InvalidVectorCount {
                expected: request.inputs.len(),
                actual: self.vectors.len(),
            });
        }
        for (index, vector) in self.vectors.iter().enumerate() {
            validate_vector(vector, self.space, index)?;
        }
        Ok(())
    }
}

fn validate_abi_version(actual: u16) -> Result<(), EmbedError> {
    if actual != EMBEDDER_ABI_VERSION {
        return Err(EmbedError::InvalidAbiVersion {
            expected: EMBEDDER_ABI_VERSION,
            actual,
        });
    }
    Ok(())
}

pub fn validate_vector(vector: &[f32], space: EmbedSpace, index: usize) -> Result<(), EmbedError> {
    let expected = space.dimensions();
    if vector.len() != expected {
        return Err(EmbedError::InvalidDimensions {
            expected,
            actual: vector.len(),
        });
    }
    if vector.iter().any(|value| !value.is_finite()) {
        return Err(EmbedError::NonFiniteVector { index });
    }
    if vector.iter().all(|value| *value == 0.0) {
        return Err(EmbedError::ZeroVector { index });
    }
    if matches!(space, EmbedSpace::Padded1024)
        && vector[NATIVE_DIMENSIONS..]
            .iter()
            .any(|value| *value != 0.0)
    {
        return Err(EmbedError::InvalidPadding { index });
    }
    Ok(())
}

pub fn pad_native_to_1024(vector: &[f32]) -> Result<Vec<f32>, EmbedError> {
    validate_vector(vector, EmbedSpace::Native768, 0)?;
    let mut padded = Vec::with_capacity(PADDED_DIMENSIONS);
    padded.extend_from_slice(vector);
    padded.resize(PADDED_DIMENSIONS, 0.0);
    Ok(padded)
}

pub fn cosine_similarity(left: &[f32], right: &[f32]) -> Result<f32, EmbedError> {
    if left.len() != right.len() {
        return Err(EmbedError::InvalidDimensions {
            expected: left.len(),
            actual: right.len(),
        });
    }
    let space = match left.len() {
        NATIVE_DIMENSIONS => EmbedSpace::Native768,
        PADDED_DIMENSIONS => EmbedSpace::Padded1024,
        actual => {
            return Err(EmbedError::InvalidDimensions {
                expected: NATIVE_DIMENSIONS,
                actual,
            })
        }
    };
    validate_vector(left, space, 0)?;
    validate_vector(right, space, 1)?;
    Ok(cosine_validated(left, right))
}

pub fn cosine_native_padded(native: &[f32], padded: &[f32]) -> Result<f32, EmbedError> {
    validate_vector(native, EmbedSpace::Native768, 0)?;
    validate_vector(padded, EmbedSpace::Padded1024, 1)?;
    let native_norm = native
        .iter()
        .map(|value| f64::from(*value) * f64::from(*value))
        .sum::<f64>()
        .sqrt();
    let padded_norm = padded
        .iter()
        .map(|value| f64::from(*value) * f64::from(*value))
        .sum::<f64>()
        .sqrt();
    let dot = native
        .iter()
        .zip(&padded[..NATIVE_DIMENSIONS])
        .map(|(left, right)| f64::from(*left) * f64::from(*right))
        .sum::<f64>();
    Ok((dot / (native_norm * padded_norm)) as f32)
}

fn cosine_validated(left: &[f32], right: &[f32]) -> f32 {
    let dot = left
        .iter()
        .zip(right)
        .map(|(left, right)| f64::from(*left) * f64::from(*right))
        .sum::<f64>();
    let left_norm = left
        .iter()
        .map(|value| f64::from(*value) * f64::from(*value))
        .sum::<f64>()
        .sqrt();
    let right_norm = right
        .iter()
        .map(|value| f64::from(*value) * f64::from(*value))
        .sum::<f64>()
        .sqrt();
    (dot / (left_norm * right_norm)) as f32
}

#[derive(Debug, Clone, PartialEq)]
pub struct RankedVector {
    pub id: String,
    pub vector: Vec<f32>,
}

pub fn rank_by_cosine(
    query: &[f32],
    candidates: &[RankedVector],
) -> Result<Vec<String>, EmbedError> {
    if candidates.is_empty() {
        let space = match query.len() {
            NATIVE_DIMENSIONS => EmbedSpace::Native768,
            PADDED_DIMENSIONS => EmbedSpace::Padded1024,
            actual => {
                return Err(EmbedError::InvalidDimensions {
                    expected: NATIVE_DIMENSIONS,
                    actual,
                })
            }
        };
        validate_vector(query, space, 0)?;
        return Ok(Vec::new());
    }
    rank_by_cosine_with_limit(query, candidates, candidates.len())
}

pub fn rank_by_cosine_with_limit(
    query: &[f32],
    candidates: &[RankedVector],
    limit: usize,
) -> Result<Vec<String>, EmbedError> {
    if limit == 0 {
        return Err(EmbedError::InvalidRankLimit);
    }
    let space = match query.len() {
        NATIVE_DIMENSIONS => EmbedSpace::Native768,
        PADDED_DIMENSIONS => EmbedSpace::Padded1024,
        actual => {
            return Err(EmbedError::InvalidDimensions {
                expected: NATIVE_DIMENSIONS,
                actual,
            })
        }
    };
    validate_vector(query, space, 0)?;

    let mut seen_ids = Vec::with_capacity(candidates.len());
    let mut scored = Vec::with_capacity(candidates.len());
    for candidate in candidates {
        if candidate.id.is_empty() {
            return Err(EmbedError::EmptyCandidateId);
        }
        if seen_ids.iter().any(|id| id == &candidate.id) {
            return Err(EmbedError::DuplicateCandidateId);
        }
        seen_ids.push(candidate.id.clone());
        validate_vector(&candidate.vector, space, 1)?;
        scored.push((
            candidate.id.as_str(),
            cosine_validated(query, &candidate.vector),
        ));
    }

    scored.sort_by(|(left_id, left_score), (right_id, right_score)| {
        right_score
            .partial_cmp(left_score)
            .unwrap_or(Ordering::Equal)
            .then_with(|| left_id.cmp(right_id))
    });
    Ok(scored
        .into_iter()
        .take(limit.min(candidates.len()))
        .map(|(id, _)| id.to_owned())
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity() -> EmbedderIdentity {
        EmbedderIdentity {
            artifact: "granite-r2@dev".into(),
            tokenizer: "tokenizer@dev".into(),
            preprocessing: "unicode-nfkc-lower-v1".into(),
            model_space: "native-768-zero-pad-1024-v1".into(),
        }
    }

    fn native(first: f32, second: f32) -> Vec<f32> {
        let mut vector = vec![0.0; NATIVE_DIMENSIONS];
        vector[0] = first;
        vector[1] = second;
        vector
    }

    #[test]
    fn request_and_response_require_version_and_all_identities() {
        let expected = identity();
        let request = EmbedRequest {
            abi_version: EMBEDDER_ABI_VERSION,
            identity: expected.clone(),
            inputs: vec!["query".into()],
            space: EmbedSpace::Native768,
        };
        let response = EmbedResponse {
            abi_version: EMBEDDER_ABI_VERSION,
            identity: expected.clone(),
            space: EmbedSpace::Native768,
            vectors: vec![native(1.0, 0.0)],
        };
        assert!(response.validate(&request, &expected).is_ok());

        let mut drifted = expected.clone();
        drifted.tokenizer.push_str("-drift");
        let drifted_request = EmbedRequest {
            identity: drifted,
            ..request.clone()
        };
        assert!(matches!(
            drifted_request.validate(&expected),
            Err(EmbedError::IdentityMismatch {
                field: IdentityField::Tokenizer
            })
        ));
        let bad_version = EmbedRequest {
            abi_version: EMBEDDER_ABI_VERSION + 1,
            ..request
        };
        assert!(matches!(
            bad_version.validate(&expected),
            Err(EmbedError::InvalidAbiVersion { .. })
        ));
    }

    #[test]
    fn vectors_must_be_finite_nonzero_and_exactly_padded() {
        let mut zero = vec![0.0; NATIVE_DIMENSIONS];
        assert!(matches!(
            validate_vector(&zero, EmbedSpace::Native768, 0),
            Err(EmbedError::ZeroVector { .. })
        ));
        zero[0] = f32::NAN;
        assert!(matches!(
            validate_vector(&zero, EmbedSpace::Native768, 0),
            Err(EmbedError::NonFiniteVector { .. })
        ));

        let native = native(1.0, 2.0);
        let padded = pad_native_to_1024(&native).expect("native vector should pad");
        assert!(validate_vector(&padded, EmbedSpace::Padded1024, 0).is_ok());
        let mut corrupt = padded;
        corrupt[PADDING_START] = 1.0;
        assert!(matches!(
            validate_vector(&corrupt, EmbedSpace::Padded1024, 0),
            Err(EmbedError::InvalidPadding { .. })
        ));
    }

    const PADDING_START: usize = NATIVE_DIMENSIONS;

    #[test]
    fn native_and_zero_padded_cosine_have_the_same_result() {
        let native_query = native(1.0, 2.0);
        let native_candidate = native(2.0, 1.0);
        let padded_query = pad_native_to_1024(&native_query).unwrap();
        let padded_candidate = pad_native_to_1024(&native_candidate).unwrap();
        let native_score = cosine_similarity(&native_query, &native_candidate).unwrap();
        let padded_score = cosine_similarity(&padded_query, &padded_candidate).unwrap();
        let cross_score = cosine_native_padded(&native_query, &padded_candidate).unwrap();
        assert_eq!(native_score, padded_score);
        assert_eq!(native_score, cross_score);
    }

    #[test]
    fn ranking_ties_are_broken_by_candidate_id() {
        let query = native(1.0, 0.0);
        let candidates = vec![
            RankedVector {
                id: "b".into(),
                vector: native(1.0, 0.0),
            },
            RankedVector {
                id: "a".into(),
                vector: native(1.0, 0.0),
            },
        ];
        assert_eq!(rank_by_cosine(&query, &candidates).unwrap(), vec!["a", "b"]);
    }

    #[test]
    fn ranking_empty_candidates_returns_empty() {
        let query = native(1.0, 0.0);

        assert_eq!(rank_by_cosine(&query, &[]).unwrap(), Vec::<String>::new());
    }
}

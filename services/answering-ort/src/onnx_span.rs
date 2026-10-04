//! Optional CPU tensor execution for a digest-bound, local extractive QA graph.
//!
//! This is not a tokenizer, promoted reader, or resource-admission receipt.
//! Callers own tokenizer/offset custody and the outer Runtime deadline boundary.
use crate::protocol::ApiError;
use crate::runtime::{Deadline, RuntimeConfig};
use ort::ep::CPU;
use ort::session::Session;
use ort::value::TensorElementType;
use ort::value::{Tensor, ValueType};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const MAX_TOKENS: usize = 512;
const MAX_MODEL_BYTES: usize = 1024 * 1024 * 1024;

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TokenInputs {
    pub input_ids: Vec<i64>,
    pub attention_mask: Vec<i64>,
    pub token_type_ids: Option<Vec<i64>>,
}

impl TokenInputs {
    pub fn validate(&self) -> Result<(), ApiError> {
        let count = self.input_ids.len();
        if !(1..=MAX_TOKENS).contains(&count)
            || self.attention_mask.len() != count
            || self.input_ids.iter().any(|id| *id < 0)
            || self
                .attention_mask
                .iter()
                .any(|value| !matches!(value, 0 | 1))
            || self.attention_mask.iter().all(|value| *value == 0)
            || self.token_type_ids.as_ref().is_some_and(|ids| {
                ids.len() != count || ids.iter().any(|value| !matches!(value, 0 | 1))
            })
        {
            return Err(ApiError::inference_failed());
        }
        Ok(())
    }
}

#[derive(Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SpanLogits {
    pub start_logits: Vec<f32>,
    pub end_logits: Vec<f32>,
}

pub struct OnnxSpanSession {
    session: Session,
    has_token_types: bool,
}

fn tensor_type(value: &ValueType, expected: TensorElementType) -> bool {
    matches!(value, ValueType::Tensor { ty, shape, .. }
        if *ty == expected && shape.len() == 2 && matches!(shape[0], -1 | 1)
            && (shape[1] == -1 || (1..=MAX_TOKENS as i64).contains(&shape[1])))
}

impl OnnxSpanSession {
    /// Load already-read model bytes; no model fetching or Python invocation.
    /// Runtime library selection is external and must also be custody-bound
    /// before promotion. In-memory loading does not establish mmap residency.
    pub fn from_bytes(bytes: &[u8], sha256: &str, threads: usize) -> Result<Self, ApiError> {
        if bytes.is_empty() || bytes.len() > MAX_MODEL_BYTES {
            return Err(ApiError::limit_exceeded());
        }
        if sha256.len() != 64 || format!("{:x}", Sha256::digest(bytes)) != sha256 {
            return Err(ApiError::identity_mismatch());
        }
        let config = RuntimeConfig::new(None, threads);
        let build = || -> ort::Result<Session> {
            Session::builder()?
                .with_execution_providers([CPU::default()
                    .with_arena_allocator(false)
                    .build()
                    .error_on_failure()])?
                .with_intra_threads(config.intra_op_threads)?
                .with_inter_threads(1)?
                .with_parallel_execution(false)?
                .with_memory_pattern(false)?
                .commit_from_memory(bytes)
        };
        let session = build().map_err(|_| ApiError::unavailable())?;
        let names: std::collections::BTreeSet<_> =
            session.inputs().iter().map(|i| i.name()).collect();
        let has_token_types = names.contains("token_type_ids");
        let expected = if has_token_types {
            vec!["attention_mask", "input_ids", "token_type_ids"]
        } else {
            vec!["attention_mask", "input_ids"]
        };
        if names.into_iter().collect::<Vec<_>>() != expected
            || session.inputs().len() != expected.len()
            || session
                .inputs()
                .iter()
                .any(|i| !tensor_type(i.dtype(), TensorElementType::Int64))
            || session.outputs().len() != 2
            || !["start_logits", "end_logits"]
                .iter()
                .all(|name| session.outputs().iter().any(|o| o.name() == *name))
            || session
                .outputs()
                .iter()
                .any(|o| !tensor_type(o.dtype(), TensorElementType::Float32))
        {
            return Err(ApiError::inference_failed());
        }
        Ok(Self {
            session,
            has_token_types,
        })
    }

    pub fn run(
        &mut self,
        inputs: &TokenInputs,
        deadline: Deadline,
    ) -> Result<SpanLogits, ApiError> {
        inputs.validate()?;
        if deadline.is_expired() {
            return Err(ApiError::timed_out());
        }
        if inputs.token_type_ids.is_some() != self.has_token_types {
            return Err(ApiError::inference_failed());
        }
        let count = inputs.input_ids.len();
        let tensor = |values: &[i64]| {
            Tensor::from_array(([1, count], values.to_vec()))
                .map_err(|_| ApiError::inference_failed())
        };
        let mut values = ort::inputs![
            "input_ids" => tensor(&inputs.input_ids)?,
            "attention_mask" => tensor(&inputs.attention_mask)?,
        ];
        if let Some(ids) = &inputs.token_type_ids {
            values.push(("token_type_ids".into(), tensor(ids)?.into()));
        }
        let outputs = self
            .session
            .run(values)
            .map_err(|_| ApiError::inference_failed())?;
        if deadline.is_expired() {
            return Err(ApiError::timed_out());
        }
        let extract = |name: &str| -> Result<Vec<f32>, ApiError> {
            let (shape, values) = outputs
                .get(name)
                .ok_or_else(ApiError::inference_failed)?
                .try_extract_tensor::<f32>()
                .map_err(|_| ApiError::inference_failed())?;
            if shape.as_ref() != [1, count as i64] || values.iter().any(|v| !v.is_finite()) {
                return Err(ApiError::inference_failed());
            }
            Ok(values.to_vec())
        };
        Ok(SpanLogits {
            start_logits: extract("start_logits")?,
            end_logits: extract("end_logits")?,
        })
    }
}

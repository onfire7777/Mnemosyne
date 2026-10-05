//! Experimental span/no-answer baseline; not a promoted multi-task reader.
//! The policy is `window-null-margin-v1`: compare each span to that window's
//! CLS score, then select the largest margin with source-order/offset ties.
use crate::onnx_span::{OnnxSpanSession, SpanLogits, TokenInputs};
use crate::protocol::{self, ApiError, ErrorCode, Output, ReadPrediction, Request};
use crate::runtime::{Deadline, InferenceSession};
use sha2::{Digest, Sha256};
use std::sync::Mutex;
use tokenizers::{Encoding, PostProcessor, Tokenizer, TruncationParams, TruncationStrategy};

const WINDOW: usize = 512;
const WINDOW_STEP: usize = 128;
const MAX_WINDOWS: usize = 128;

#[derive(Clone, Copy, Debug)]
pub struct SpanReaderConfig {
    pub null_token_id: u32,
    pub null_threshold: f32,
    pub max_answer_tokens: usize,
}

struct Window {
    inputs: TokenInputs,
    offsets: Vec<Option<(usize, usize)>>,
    null_index: usize,
}

struct SpanTokenizer {
    tokenizer: Tokenizer,
    null_token_id: u32,
}

fn signature(encoding: &Encoding, sequence: usize) -> Vec<(u32, usize, usize)> {
    encoding
        .get_sequence_ids()
        .iter()
        .enumerate()
        .filter(|(_, seq)| **seq == Some(sequence))
        .map(|(i, _)| {
            let (start, end) = encoding.get_offsets()[i];
            (encoding.get_ids()[i], start, end)
        })
        .collect()
}

impl SpanTokenizer {
    fn new(bytes: &[u8], sha256: &str, null_token_id: u32) -> Result<Self, ApiError> {
        if bytes.is_empty() || bytes.len() > 16 * 1024 * 1024 {
            return Err(ApiError::limit_exceeded());
        }
        if format!("{:x}", Sha256::digest(bytes)) != sha256 {
            return Err(ApiError::identity_mismatch());
        }
        let mut tokenizer =
            Tokenizer::from_bytes(bytes).map_err(|_| ApiError::inference_failed())?;
        if matches!(tokenizer.get_model(), tokenizers::models::ModelWrapper::BPE(bpe)
            if bpe.dropout.is_some_and(|p| p != 0.0))
        {
            return Err(ApiError::inference_failed());
        }
        let processor = tokenizer
            .get_post_processor()
            .ok_or_else(ApiError::inference_failed)?;
        if processor.added_tokens(false) > 16
            || processor.added_tokens(true) > 16
            || tokenizer.id_to_token(null_token_id).is_none()
        {
            return Err(ApiError::inference_failed());
        }
        // Serialized padding/truncation cannot silently discard source text.
        tokenizer
            .with_truncation(None)
            .map_err(|_| ApiError::inference_failed())?;
        tokenizer.with_padding(None);
        Ok(Self {
            tokenizer,
            null_token_id,
        })
    }

    fn windows(
        &self,
        query: &str,
        context: &str,
        token_types: bool,
    ) -> Result<Vec<Window>, ApiError> {
        let full = self
            .tokenizer
            .encode((query, context), true)
            .map_err(|_| ApiError::inference_failed())?;
        let question = signature(&full, 0);
        let source = signature(&full, 1);
        if question.is_empty() || question.len() > 256 {
            return Err(ApiError::limit_exceeded());
        }
        if source.is_empty() {
            return Ok(Vec::new());
        }
        let overhead = full
            .len()
            .checked_sub(source.len())
            .ok_or_else(ApiError::inference_failed)?;
        if overhead >= WINDOW - WINDOW_STEP {
            return Err(ApiError::limit_exceeded());
        }
        let overlap = WINDOW - overhead - WINDOW_STEP;
        let mut tokenizer = self.tokenizer.clone();
        tokenizer
            .with_truncation(Some(TruncationParams {
                max_length: WINDOW,
                stride: overlap,
                strategy: TruncationStrategy::OnlySecond,
                ..Default::default()
            }))
            .map_err(|_| ApiError::inference_failed())?;
        let encoded = tokenizer
            .encode((query, context), true)
            .map_err(|_| ApiError::inference_failed())?;
        let all: Vec<_> = std::iter::once(&encoded)
            .chain(encoded.get_overflowing())
            .collect();
        if all.len() > MAX_WINDOWS {
            return Err(ApiError::limit_exceeded());
        }
        let mut next_start = 0;
        let mut result = Vec::with_capacity(all.len());
        for (index, encoding) in all.iter().enumerate() {
            let current = signature(encoding, 1);
            let end = next_start + current.len();
            if current.is_empty()
                || source.get(next_start..end) != Some(current.as_slice())
                || signature(encoding, 0) != question
                || encoding.len() > WINDOW
            {
                return Err(ApiError::inference_failed());
            }
            if index + 1 == all.len() {
                if end != source.len() {
                    return Err(ApiError::inference_failed());
                }
            } else {
                let after_overlap = end
                    .checked_sub(overlap)
                    .ok_or_else(ApiError::inference_failed)?;
                if after_overlap <= next_start || end >= source.len() {
                    return Err(ApiError::inference_failed());
                }
                next_start = after_overlap;
            }
            let sequences = encoding.get_sequence_ids();
            let mut nulls = Vec::new();
            let mut previous_offset = (0, 0);
            let mut offsets = Vec::with_capacity(encoding.len());
            for (i, seq) in sequences.iter().enumerate() {
                if seq.is_none()
                    && encoding.get_special_tokens_mask()[i] == 1
                    && encoding.get_attention_mask()[i] == 1
                    && encoding.get_ids()[i] == self.null_token_id
                {
                    nulls.push(i);
                }
                if *seq == Some(1)
                    && encoding.get_special_tokens_mask()[i] == 0
                    && encoding.get_attention_mask()[i] == 1
                {
                    let (start, end) = encoding.get_offsets()[i];
                    if start >= end
                        || start < previous_offset.0
                        || end < previous_offset.1
                        || end > context.len()
                        || !context.is_char_boundary(start)
                        || !context.is_char_boundary(end)
                    {
                        return Err(ApiError::inference_failed());
                    }
                    previous_offset = (start, end);
                    offsets.push(Some((start, end)));
                } else {
                    offsets.push(None);
                }
            }
            if nulls.len() != 1 {
                return Err(ApiError::inference_failed());
            }
            let inputs = TokenInputs {
                input_ids: encoding.get_ids().iter().map(|v| i64::from(*v)).collect(),
                attention_mask: encoding
                    .get_attention_mask()
                    .iter()
                    .map(|v| i64::from(*v))
                    .collect(),
                token_type_ids: token_types.then(|| {
                    encoding
                        .get_type_ids()
                        .iter()
                        .map(|v| i64::from(*v))
                        .collect()
                }),
            };
            inputs.validate()?;
            result.push(Window {
                inputs,
                offsets,
                null_index: nulls[0],
            });
        }
        Ok(result)
    }
}

#[derive(Debug)]
struct Candidate {
    margin: f32,
    start: usize,
    end: usize,
}

fn candidate(
    window: &Window,
    logits: &SpanLogits,
    config: SpanReaderConfig,
) -> Result<Option<Candidate>, ApiError> {
    if logits.start_logits.len() != window.offsets.len()
        || logits.end_logits.len() != window.offsets.len()
        || logits
            .start_logits
            .iter()
            .chain(&logits.end_logits)
            .any(|v| !v.is_finite())
    {
        return Err(ApiError::inference_failed());
    }
    let null = logits.start_logits[window.null_index] + logits.end_logits[window.null_index];
    if !null.is_finite() {
        return Err(ApiError::inference_failed());
    }
    let mut best: Option<Candidate> = None;
    for (first, offset) in window.offsets.iter().enumerate() {
        let Some((start, _)) = offset else {
            continue;
        };
        for last in first..window.offsets.len().min(first + config.max_answer_tokens) {
            let Some((_, end)) = window.offsets[last] else {
                break;
            };
            if end <= *start {
                continue;
            }
            let margin = logits.start_logits[first] + logits.end_logits[last] - null;
            if !margin.is_finite() {
                return Err(ApiError::inference_failed());
            }
            if margin > config.null_threshold
                && best.as_ref().is_none_or(|b| {
                    margin > b.margin || (margin == b.margin && (*start, end) < (b.start, b.end))
                })
            {
                best = Some(Candidate {
                    margin,
                    start: *start,
                    end,
                });
            }
        }
    }
    Ok(best)
}

pub struct OnnxSpanReader {
    session: Mutex<OnnxSpanSession>,
    tokenizer: SpanTokenizer,
    config: SpanReaderConfig,
}

impl OnnxSpanReader {
    pub fn new(
        session: OnnxSpanSession,
        tokenizer: &[u8],
        tokenizer_sha256: &str,
        config: SpanReaderConfig,
    ) -> Result<Self, ApiError> {
        if !config.null_threshold.is_finite() || !(1..=WINDOW).contains(&config.max_answer_tokens) {
            return Err(ApiError::inference_failed());
        }
        Ok(Self {
            session: Mutex::new(session),
            tokenizer: SpanTokenizer::new(tokenizer, tokenizer_sha256, config.null_token_id)?,
            config,
        })
    }
}

impl InferenceSession for OnnxSpanReader {
    fn infer(&self, request: &Request, deadline: Deadline) -> Result<Output, ApiError> {
        protocol::validate_request(request)?;
        if deadline.is_expired() {
            return Err(ApiError::timed_out());
        }
        let Request::Read {
            query, evidence, ..
        } = request
        else {
            return Err(ApiError::new(
                ErrorCode::UnsupportedOperation,
                "span reader supports read only",
            ));
        };
        let mut session = self.session.try_lock().map_err(|_| ApiError::busy())?;
        let mut best: Option<(usize, Candidate)> = None;
        let mut window_count = 0;
        for (index, row) in evidence.iter().enumerate() {
            if deadline.is_expired() {
                return Err(ApiError::timed_out());
            }
            let windows = self
                .tokenizer
                .windows(query, &row.text, session.uses_token_types())?;
            window_count += windows.len();
            if window_count > MAX_WINDOWS {
                return Err(ApiError::limit_exceeded());
            }
            for window in windows {
                let logits = session.run(&window.inputs, deadline)?;
                if let Some(value) = candidate(&window, &logits, self.config)? {
                    if best.as_ref().is_none_or(|(previous, b)| {
                        value.margin > b.margin
                            || (value.margin == b.margin
                                && (index, value.start, value.end) < (*previous, b.start, b.end))
                    }) {
                        best = Some((index, value));
                    }
                }
            }
        }
        if deadline.is_expired() {
            return Err(ApiError::timed_out());
        }
        let prediction = match best {
            Some((index, value)) => ReadPrediction::Span {
                evidence_id: evidence[index].id.clone(),
                start: value.start,
                end: value.end,
                supporting_ids: vec![evidence[index].id.clone()],
            },
            None => ReadPrediction::Null {
                supporting_ids: Vec::new(),
            },
        };
        Ok(Output::Read { prediction })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokenizer_rejects_stochastic_or_ambiguous_inputs_and_keeps_all_windows() {
        use tokenizers::{models::bpe::BPE, processors::template::TemplateProcessing};
        let vocab: tokenizers::models::bpe::Vocab =
            [("[UNK]", 0), ("[CLS]", 1), ("[SEP]", 2), ("a", 3), ("b", 4)]
                .into_iter()
                .map(|(s, i)| (s.to_string(), i))
                .collect();
        let bpe = BPE::builder()
            .vocab_and_merges(vocab, vec![])
            .unk_token("[UNK]".into())
            .build()
            .unwrap();
        let mut tokenizer = Tokenizer::new(bpe);
        tokenizer.with_post_processor(Some(
            TemplateProcessing::builder()
                .try_single("[CLS] $A [SEP]")
                .unwrap()
                .try_pair("[CLS] $A [SEP] $B:1 [SEP]:1")
                .unwrap()
                .special_tokens(vec![("[CLS]", 1), ("[SEP]", 2)])
                .build()
                .unwrap(),
        ));
        let raw = tokenizer.to_string(false).unwrap().into_bytes();
        let hash = format!("{:x}", Sha256::digest(&raw));
        assert!(SpanTokenizer::new(&raw, &"0".repeat(64), 1).is_err());
        let fixed = SpanTokenizer::new(&raw, &hash, 1).unwrap();
        let windows = fixed.windows("a", &"b".repeat(900), false).unwrap();
        assert!(windows.len() > 1);
        assert_eq!(windows[1].offsets.iter().flatten().next().unwrap().0, 128);
        assert_eq!(
            windows
                .last()
                .unwrap()
                .offsets
                .iter()
                .flatten()
                .last()
                .unwrap()
                .1,
            900
        );
        assert!(fixed.windows(&"a".repeat(257), "b", false).is_err());
        assert!(fixed.windows("a", &"b".repeat(24000), false).is_err());
        assert!(SpanTokenizer::new(&raw, &hash, 2)
            .unwrap()
            .windows("a", "b", false)
            .is_err());
        let mut model = tokenizer.get_model().clone();
        if let tokenizers::models::ModelWrapper::BPE(bpe) = &mut model {
            bpe.dropout = Some(0.5);
        }
        tokenizer.with_model(model);
        let stochastic = tokenizer.to_string(false).unwrap().into_bytes();
        assert!(SpanTokenizer::new(
            &stochastic,
            &format!("{:x}", Sha256::digest(&stochastic)),
            1
        )
        .is_err());
    }

    #[test]
    fn span_selection_masks_question_and_gaps_and_abstains_at_threshold() {
        let window = Window {
            inputs: TokenInputs {
                input_ids: vec![1; 5],
                attention_mask: vec![1; 5],
                token_type_ids: None,
            },
            offsets: vec![None, Some((0, 2)), Some((3, 5)), None, Some((8, 9))],
            null_index: 0,
        };
        let mut logits = SpanLogits {
            start_logits: vec![1.0, 5.0, 0.0, 999.0, 0.0],
            end_logits: vec![1.0, 0.0, 5.0, 999.0, 0.0],
        };
        let config = SpanReaderConfig {
            null_token_id: 1,
            null_threshold: 0.0,
            max_answer_tokens: 5,
        };
        let selected = candidate(&window, &logits, config).unwrap().unwrap();
        assert_eq!((selected.start, selected.end, selected.margin), (0, 5, 8.0));
        assert!(candidate(
            &window,
            &logits,
            SpanReaderConfig {
                null_threshold: 8.0,
                ..config
            }
        )
        .unwrap()
        .is_none());
        logits.start_logits[1] = f32::NAN;
        assert!(candidate(&window, &logits, config).is_err());
        logits.start_logits.pop();
        assert!(candidate(&window, &logits, config).is_err());
    }
}

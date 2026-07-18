use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};

use crate::embed::{EmbedRequest, EmbedResponse, EmbedSpace, EmbedderIdentity};
use crate::protocol::{ApiError, Evidence, Output, ReadPrediction, Request, Response};
use crate::reader::{ReaderAnswer, ReaderIdentity, ReaderPrediction, ReaderRequest};
use crate::rerank::{RerankIdentity, RerankRequest, RerankResponse};

pub const MAX_IN_FLIGHT: usize = 1;
pub const REQUEST_DEADLINE: Duration = Duration::from_secs(30);
pub const MAX_EMBEDDING_DIMENSIONS: usize = 4_096;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeConfig {
    pub model_path: Option<PathBuf>,
    pub cpu_arena_enabled: bool,
    pub memory_map_model: bool,
    pub intra_op_threads: usize,
    pub inter_op_threads: usize,
}

impl RuntimeConfig {
    pub fn new(model_path: Option<PathBuf>, requested_intra_op_threads: usize) -> Self {
        Self {
            model_path,
            cpu_arena_enabled: false,
            memory_map_model: true,
            intra_op_threads: clamp_intra_op_threads(
                requested_intra_op_threads,
                num_cpus::get_physical(),
            ),
            inter_op_threads: 1,
        }
    }

    pub fn from_env() -> Self {
        let model_path = std::env::var_os("ANSWERING_ORT_MODEL_PATH").map(PathBuf::from);
        let requested_threads = std::env::var("ANSWERING_ORT_INTRA_OP_THREADS")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(2);
        Self::new(model_path, requested_threads)
    }
}

fn clamp_intra_op_threads(requested: usize, physical_cores: usize) -> usize {
    requested.clamp(1, physical_cores.clamp(1, 2))
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self::new(None, 2)
    }
}

pub trait InferenceSession: Send + Sync {
    fn infer(&self, request: &Request, deadline: Deadline) -> Result<Output, ApiError>;
}

/// The three model adapters share one serialized runtime session.
///
/// Implementations own model loading and tensor execution. They receive the
/// versioned component requests after the sidecar has attached the configured
/// identity, and must return the corresponding versioned response. The
/// runtime validates every response again before it becomes protocol output.
pub trait ComponentBackend: Send + Sync {
    fn embed(
        &self,
        request: &EmbedRequest,
        deadline: Deadline,
    ) -> Result<EmbedResponse, crate::embed::EmbedError>;

    fn rerank(
        &self,
        request: &RerankRequest,
        deadline: Deadline,
    ) -> Result<RerankResponse, crate::rerank::RerankError>;

    fn read(
        &self,
        request: &ReaderRequest,
        deadline: Deadline,
    ) -> Result<Vec<ReaderPrediction>, crate::reader::ReaderError>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ComponentIdentities {
    pub embedder: EmbedderIdentity,
    pub reranker: RerankIdentity,
    pub reader: ReaderIdentity,
}

/// Adapts the component ABIs to the single protocol-facing inference session.
pub struct ComponentSession {
    identities: ComponentIdentities,
    backend: Arc<dyn ComponentBackend>,
    embed_space: EmbedSpace,
    null_threshold: f32,
}

impl ComponentSession {
    pub fn new(identities: ComponentIdentities, backend: Arc<dyn ComponentBackend>) -> Self {
        Self {
            identities,
            backend,
            embed_space: EmbedSpace::Native768,
            null_threshold: 0.0,
        }
    }

    pub fn with_options(
        identities: ComponentIdentities,
        backend: Arc<dyn ComponentBackend>,
        embed_space: EmbedSpace,
        null_threshold: f32,
    ) -> Result<Self, ApiError> {
        if !null_threshold.is_finite() {
            return Err(ApiError::inference_failed());
        }
        Ok(Self {
            identities,
            backend,
            embed_space,
            null_threshold,
        })
    }

    pub fn identities(&self) -> &ComponentIdentities {
        &self.identities
    }

    fn infer_embed(&self, query: &str, deadline: Deadline) -> Result<Output, ApiError> {
        let request = EmbedRequest {
            abi_version: crate::embed::EMBEDDER_ABI_VERSION,
            identity: self.identities.embedder.clone(),
            inputs: vec![query.to_owned()],
            space: self.embed_space,
        };
        request
            .validate(&self.identities.embedder)
            .map_err(map_embed_error)?;
        let response = self
            .backend
            .embed(&request, deadline)
            .map_err(map_embed_error)?;
        if deadline.is_expired() {
            return Err(ApiError::timed_out());
        }
        response
            .validate(&request, &self.identities.embedder)
            .map_err(map_embed_error)?;
        let embedding = response
            .vectors
            .into_iter()
            .next()
            .ok_or_else(ApiError::inference_failed)?;
        Ok(Output::Embed { embedding })
    }

    fn infer_rerank(
        &self,
        query: &str,
        evidence: &[Evidence],
        rank_width: usize,
        deadline: Deadline,
    ) -> Result<Output, ApiError> {
        let candidates = evidence
            .iter()
            .map(|row| crate::rerank::RerankCandidate {
                evidence_id: row.id.clone(),
                text: row.text.clone(),
            })
            .collect();
        let request = RerankRequest::new(
            self.identities.reranker.clone(),
            query.to_owned(),
            candidates,
            rank_width,
        )
        .map_err(map_rerank_error)?;
        let response = self
            .backend
            .rerank(&request, deadline)
            .map_err(map_rerank_error)?;
        let ranked = crate::rerank::validate_response_with_deadline(
            &request,
            &response,
            deadline.expires_at(),
        )
        .map_err(map_rerank_error)?;
        Ok(Output::Rerank {
            ranked_ids: ranked.into_iter().map(|score| score.evidence_id).collect(),
        })
    }

    fn infer_read(
        &self,
        query: &str,
        evidence: &[Evidence],
        deadline: Deadline,
    ) -> Result<Output, ApiError> {
        let Some(request) = build_reader_request(
            &self.identities.reader,
            query,
            evidence,
            self.null_threshold,
        )?
        else {
            return Ok(Output::Read {
                prediction: ReadPrediction::Null {
                    supporting_ids: Vec::new(),
                },
            });
        };

        let predictions = self
            .backend
            .read(&request, deadline)
            .map_err(map_reader_error)?;
        let mut window_ids = std::collections::HashSet::with_capacity(predictions.len());
        if predictions.len() != request.windows.len()
            || predictions
                .iter()
                .any(|prediction| !window_ids.insert(prediction.window_id.as_str()))
        {
            return Err(ApiError::inference_failed());
        }
        for prediction in &predictions {
            crate::reader::validate_prediction_with_deadline(
                &request,
                prediction,
                deadline.expires_at(),
            )
            .map_err(map_reader_error)?;
        }
        let selected = predictions
            .iter()
            .max_by(|left, right| {
                left.score
                    .partial_cmp(&right.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| (left.answer_type != "null").cmp(&(right.answer_type != "null")))
                    .then_with(|| {
                        right
                            .null_margin
                            .partial_cmp(&left.null_margin)
                            .unwrap_or(std::cmp::Ordering::Equal)
                    })
                    .then_with(|| left.window_id.cmp(&right.window_id))
            })
            .ok_or_else(ApiError::inference_failed)?;
        if deadline.is_expired() {
            return Err(ApiError::timed_out());
        }
        let answer =
            crate::reader::decode_prediction(&request, selected).map_err(map_reader_error)?;
        protocol_prediction(&request, answer)
    }
}

impl InferenceSession for ComponentSession {
    fn infer(&self, request: &Request, deadline: Deadline) -> Result<Output, ApiError> {
        if deadline.is_expired() {
            return Err(ApiError::timed_out());
        }
        match request {
            Request::Embed { query } => self.infer_embed(query, deadline),
            Request::Rerank {
                query,
                evidence,
                rank_width,
            } => self.infer_rerank(query, evidence, *rank_width, deadline),
            Request::Read { query, evidence } => self.infer_read(query, evidence, deadline),
        }
    }
}

fn map_embed_error(error: crate::embed::EmbedError) -> ApiError {
    match error {
        crate::embed::EmbedError::InvalidIdentity { .. }
        | crate::embed::EmbedError::IdentityMismatch { .. } => ApiError::identity_mismatch(),
        crate::embed::EmbedError::EmptyInputBatch
        | crate::embed::EmbedError::InvalidInput { .. }
        | crate::embed::EmbedError::InvalidRankLimit => ApiError::limit_exceeded(),
        _ => ApiError::inference_failed(),
    }
}

fn map_rerank_error(error: crate::rerank::RerankError) -> ApiError {
    match error {
        crate::rerank::RerankError::InvalidIdentity
        | crate::rerank::RerankError::IdentityMismatch => ApiError::identity_mismatch(),
        crate::rerank::RerankError::RequestTooLarge => ApiError::request_too_large(),
        crate::rerank::RerankError::LimitExceeded => ApiError::limit_exceeded(),
        crate::rerank::RerankError::TimedOut => ApiError::timed_out(),
        _ => ApiError::inference_failed(),
    }
}

fn map_reader_error(error: crate::reader::ReaderError) -> ApiError {
    match error {
        crate::reader::ReaderError::InvalidIdentity
        | crate::reader::ReaderError::IdentityMismatch => ApiError::identity_mismatch(),
        crate::reader::ReaderError::RequestTooLarge => ApiError::request_too_large(),
        crate::reader::ReaderError::TimedOut => ApiError::timed_out(),
        _ => ApiError::inference_failed(),
    }
}

fn build_reader_request(
    identity: &ReaderIdentity,
    query: &str,
    evidence: &[Evidence],
    null_threshold: f32,
) -> Result<Option<ReaderRequest>, ApiError> {
    let mut context = String::new();
    let mut facts = Vec::with_capacity(evidence.len());
    for row in evidence.iter().filter(|row| !row.text.is_empty()) {
        if !context.is_empty() {
            context.push('\n');
        }
        let raw_start = context.len();
        context.push_str(&row.text);
        let raw_end = context.len();
        facts.push(crate::reader::SupportingFact {
            fact_id: row.id.clone(),
            raw_start,
            raw_end,
            text: row.text.clone(),
        });
    }
    if facts.is_empty() {
        return Ok(None);
    }
    if context.chars().count() > crate::reader::MAX_CONTEXT_CHARS
        || context.len() > crate::reader::MAX_CONTEXT_BYTES
    {
        return Err(ApiError::limit_exceeded());
    }

    let tokens = tokenize_context(&context);
    if tokens.is_empty() || tokens.len() > crate::reader::MAX_TOKEN_COUNT {
        return Err(ApiError::limit_exceeded());
    }
    let starts = reader_window_starts(tokens.len());
    if starts.len() > crate::reader::MAX_WINDOWS {
        return Err(ApiError::limit_exceeded());
    }
    let windows = starts
        .into_iter()
        .enumerate()
        .map(|(index, token_start)| {
            let token_end = token_start
                .saturating_add(crate::reader::WINDOW_TOKENS)
                .min(tokens.len());
            let window_tokens = tokens[token_start..token_end].to_vec();
            crate::reader::ReaderWindow {
                window_id: format!("window-{index:03}"),
                token_start,
                token_end,
                raw_start: window_tokens[0].raw_start,
                raw_end: window_tokens
                    .last()
                    .expect("reader window has a token")
                    .raw_end,
                tokens: window_tokens,
            }
        })
        .collect();
    let request = ReaderRequest {
        schema: crate::reader::ABI_SCHEMA.to_owned(),
        identity: identity.clone(),
        query: query.to_owned(),
        context,
        facts,
        windows,
        null_threshold,
    };
    crate::reader::validate_request(&request).map_err(map_reader_error)?;
    Ok(Some(request))
}

fn tokenize_context(context: &str) -> Vec<crate::reader::TokenSpan> {
    let mut tokens = Vec::new();
    let mut start = None;
    for (offset, character) in context.char_indices() {
        if character.is_whitespace() {
            if let Some(raw_start) = start.take() {
                tokens.push(crate::reader::TokenSpan {
                    token: context[raw_start..offset].to_owned(),
                    raw_start,
                    raw_end: offset,
                });
            }
        } else if start.is_none() {
            start = Some(offset);
        }
    }
    if let Some(raw_start) = start {
        tokens.push(crate::reader::TokenSpan {
            token: context[raw_start..].to_owned(),
            raw_start,
            raw_end: context.len(),
        });
    }
    tokens
}

fn reader_window_starts(token_count: usize) -> Vec<usize> {
    let regular_limit = token_count
        .saturating_sub(crate::reader::WINDOW_TOKENS)
        .saturating_add(1)
        .max(1);
    let mut starts: Vec<usize> = (0..regular_limit)
        .step_by(crate::reader::WINDOW_STRIDE)
        .collect();
    let final_start = token_count.saturating_sub(crate::reader::WINDOW_TOKENS);
    if starts.last().copied() != Some(final_start) {
        starts.push(final_start);
    }
    starts
}

fn protocol_prediction(request: &ReaderRequest, answer: ReaderAnswer) -> Result<Output, ApiError> {
    let supporting_ids = answer.supporting_facts;
    let prediction = match answer.answer_type.as_str() {
        "null" => ReadPrediction::Null { supporting_ids },
        "yes" => ReadPrediction::Yes { supporting_ids },
        "no" => ReadPrediction::No { supporting_ids },
        "span" => {
            let start = answer.raw_start.ok_or_else(ApiError::inference_failed)?;
            let end = answer.raw_end.ok_or_else(ApiError::inference_failed)?;
            let fact = request
                .facts
                .iter()
                .find(|fact| fact.raw_start <= start && end <= fact.raw_end)
                .ok_or_else(ApiError::inference_failed)?;
            ReadPrediction::Span {
                evidence_id: fact.fact_id.clone(),
                start: start - fact.raw_start,
                end: end - fact.raw_start,
                supporting_ids,
            }
        }
        _ => return Err(ApiError::inference_failed()),
    };
    Ok(Output::Read { prediction })
}

pub struct Runtime {
    config: RuntimeConfig,
    session: Option<Arc<dyn InferenceSession>>,
    in_flight: Arc<AtomicBool>,
}

impl Runtime {
    pub fn unavailable(config: RuntimeConfig) -> Self {
        Self {
            config,
            session: None,
            in_flight: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn with_session(config: RuntimeConfig, session: Arc<dyn InferenceSession>) -> Self {
        Self {
            config,
            session: Some(session),
            in_flight: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn with_components(
        config: RuntimeConfig,
        identities: ComponentIdentities,
        backend: Arc<dyn ComponentBackend>,
    ) -> Self {
        Self::with_session(config, Arc::new(ComponentSession::new(identities, backend)))
    }

    pub fn with_component_options(
        config: RuntimeConfig,
        identities: ComponentIdentities,
        backend: Arc<dyn ComponentBackend>,
        embed_space: EmbedSpace,
        null_threshold: f32,
    ) -> Result<Self, ApiError> {
        let session =
            ComponentSession::with_options(identities, backend, embed_space, null_threshold)?;
        Ok(Self::with_session(config, Arc::new(session)))
    }

    pub fn config(&self) -> &RuntimeConfig {
        &self.config
    }

    pub fn execute(&self, request: Request, deadline: Deadline) -> Response {
        if deadline.is_expired() {
            return Response::failure(ApiError::timed_out());
        }

        let permit = match InFlightPermit::acquire(&self.in_flight) {
            Some(permit) => permit,
            None => return Response::failure(ApiError::busy()),
        };

        let Some(session) = &self.session else {
            return Response::failure(ApiError::unavailable());
        };

        let Some(remaining) = deadline.remaining() else {
            return Response::failure(ApiError::timed_out());
        };
        let session = Arc::clone(session);
        let worker_request = request.clone();
        let (sender, receiver) = mpsc::sync_channel(1);
        if std::thread::Builder::new()
            .name("answering-ort-inference".into())
            .spawn(move || {
                let _permit = permit;
                let _ = sender.send(session.infer(&worker_request, deadline));
            })
            .is_err()
        {
            return Response::failure(ApiError::inference_failed());
        }

        match receiver.recv_timeout(remaining) {
            Ok(_) if deadline.is_expired() => Response::failure(ApiError::timed_out()),
            Ok(Ok(output)) => match validate_output(&request, &output) {
                Ok(()) => Response::success(output),
                Err(error) => Response::failure(error),
            },
            Ok(Err(error)) => Response::failure(error),
            Err(RecvTimeoutError::Timeout) => Response::failure(ApiError::timed_out()),
            Err(RecvTimeoutError::Disconnected) => Response::failure(ApiError::inference_failed()),
        }
    }
}

fn validate_output(request: &Request, output: &Output) -> Result<(), ApiError> {
    match (request, output) {
        (Request::Embed { .. }, Output::Embed { embedding }) => {
            if embedding.is_empty()
                || embedding.len() > MAX_EMBEDDING_DIMENSIONS
                || embedding.iter().any(|value| !value.is_finite())
            {
                return Err(ApiError::inference_failed());
            }
        }
        (
            Request::Rerank {
                evidence,
                rank_width,
                ..
            },
            Output::Rerank { ranked_ids },
        ) => {
            let mut seen = std::collections::HashSet::with_capacity(ranked_ids.len());
            if ranked_ids.len() > (*rank_width).min(evidence.len())
                || ranked_ids
                    .iter()
                    .any(|id| !seen.insert(id) || !has_evidence_id(evidence, id))
            {
                return Err(ApiError::inference_failed());
            }
        }
        (Request::Read { evidence, .. }, Output::Read { prediction }) => {
            validate_read_prediction(evidence, prediction)?;
        }
        _ => return Err(ApiError::inference_failed()),
    }
    Ok(())
}

fn validate_read_prediction(
    evidence: &[Evidence],
    prediction: &ReadPrediction,
) -> Result<(), ApiError> {
    let supporting_ids = match prediction {
        ReadPrediction::Span {
            evidence_id,
            start,
            end,
            supporting_ids,
        } => {
            let Some(row) = evidence.iter().find(|row| row.id == *evidence_id) else {
                return Err(ApiError::inference_failed());
            };
            if start >= end
                || *end > row.text.len()
                || !row.text.is_char_boundary(*start)
                || !row.text.is_char_boundary(*end)
            {
                return Err(ApiError::inference_failed());
            }
            supporting_ids
        }
        ReadPrediction::Yes { supporting_ids }
        | ReadPrediction::No { supporting_ids }
        | ReadPrediction::Null { supporting_ids } => supporting_ids,
    };

    let mut seen = std::collections::HashSet::with_capacity(supporting_ids.len());
    if supporting_ids.len() > evidence.len()
        || supporting_ids
            .iter()
            .any(|id| !seen.insert(id) || !has_evidence_id(evidence, id))
    {
        return Err(ApiError::inference_failed());
    }
    Ok(())
}

fn has_evidence_id(evidence: &[Evidence], id: &str) -> bool {
    evidence.iter().any(|row| row.id == id)
}

struct InFlightPermit(Arc<AtomicBool>);

impl InFlightPermit {
    fn acquire(flag: &Arc<AtomicBool>) -> Option<Self> {
        flag.compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
            .ok()
            .map(|_| Self(Arc::clone(flag)))
    }
}

impl Drop for InFlightPermit {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

#[derive(Debug, Clone, Copy)]
pub struct Deadline(Instant);

impl Deadline {
    pub fn from_start(started_at: Instant) -> Self {
        Self(started_at + REQUEST_DEADLINE)
    }

    pub fn after(duration: Duration) -> Self {
        Self(Instant::now() + duration.min(REQUEST_DEADLINE))
    }

    pub fn is_expired(self) -> bool {
        Instant::now() >= self.0
    }

    pub fn remaining(self) -> Option<Duration> {
        self.0.checked_duration_since(Instant::now())
    }

    pub fn expires_at(self) -> Instant {
        self.0
    }
}

impl Default for Deadline {
    fn default() -> Self {
        Self::from_start(Instant::now())
    }
}

static SHARED_RUNTIME: OnceLock<Runtime> = OnceLock::new();

pub fn shared_runtime() -> &'static Runtime {
    SHARED_RUNTIME.get_or_init(|| Runtime::unavailable(RuntimeConfig::from_env()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::embed::{EmbedRequest, EmbedResponse, EmbedderIdentity};
    use crate::protocol::{handle_json, ErrorCode, Output};
    use crate::reader::{ReaderIdentity, ReaderPrediction, ReaderRequest};
    use crate::rerank::{RerankIdentity, RerankRequest, RerankResponse, RerankScore};
    use std::sync::Barrier;
    use std::sync::Mutex;
    use std::thread;

    struct FixedSession(Result<Output, ApiError>);

    impl InferenceSession for FixedSession {
        fn infer(&self, _request: &Request, _deadline: Deadline) -> Result<Output, ApiError> {
            self.0.clone()
        }
    }

    struct BlockingSession {
        started: Arc<Barrier>,
        release: Arc<Barrier>,
        block_once: AtomicBool,
    }

    impl InferenceSession for BlockingSession {
        fn infer(&self, _request: &Request, deadline: Deadline) -> Result<Output, ApiError> {
            if self.block_once.swap(false, Ordering::Relaxed) {
                self.started.wait();
                self.release.wait();
            }
            if deadline.is_expired() {
                return Err(ApiError::timed_out());
            }
            Ok(Output::Embed {
                embedding: vec![1.0],
            })
        }
    }

    fn synthetic_identities() -> ComponentIdentities {
        ComponentIdentities {
            embedder: EmbedderIdentity {
                artifact: "embedder-artifact@dev".into(),
                tokenizer: "embedder-tokenizer@dev".into(),
                preprocessing: "embedder-preprocessing@dev".into(),
                model_space: "native-768-zero-pad-1024-v1".into(),
            },
            reranker: RerankIdentity {
                model_id: "reranker@dev".into(),
                artifact_id: "reranker-artifact@dev".into(),
                artifact_sha256: "a".repeat(64),
                preprocessing_id: "reranker-preprocessing@dev".into(),
                preprocessing_sha256: "b".repeat(64),
            },
            reader: ReaderIdentity {
                model_id: "reader@dev".into(),
                artifact_id: "reader-artifact@dev".into(),
                artifact_sha256: "c".repeat(64),
                preprocessing_id: "reader-preprocessing@dev".into(),
                preprocessing_sha256: "d".repeat(64),
            },
        }
    }

    struct SyntheticComponentBackend {
        calls: Mutex<Vec<String>>,
        corrupt_embed_identity: bool,
    }

    impl SyntheticComponentBackend {
        fn record(&self, component: &str, identity: &str) {
            self.calls
                .lock()
                .expect("synthetic call log is not poisoned")
                .push(format!("{component}:{identity}"));
        }
    }

    impl ComponentBackend for SyntheticComponentBackend {
        fn embed(
            &self,
            request: &EmbedRequest,
            _deadline: Deadline,
        ) -> Result<EmbedResponse, crate::embed::EmbedError> {
            self.record("embed", &request.identity.artifact);
            let mut identity = request.identity.clone();
            if self.corrupt_embed_identity {
                identity.artifact.push_str("-drift");
            }
            let mut vector = vec![0.0; request.space.dimensions()];
            vector[0] = 1.0;
            Ok(EmbedResponse {
                abi_version: crate::embed::EMBEDDER_ABI_VERSION,
                identity,
                space: request.space,
                vectors: vec![vector],
            })
        }

        fn rerank(
            &self,
            request: &RerankRequest,
            _deadline: Deadline,
        ) -> Result<RerankResponse, crate::rerank::RerankError> {
            self.record("rerank", &request.identity.model_id);
            let scores = request
                .candidates
                .iter()
                .enumerate()
                .map(|(index, candidate)| RerankScore {
                    evidence_id: candidate.evidence_id.clone(),
                    score: (request.candidates.len() - index) as f32,
                })
                .collect();
            Ok(RerankResponse::new(request.identity.clone(), scores))
        }

        fn read(
            &self,
            request: &ReaderRequest,
            _deadline: Deadline,
        ) -> Result<Vec<ReaderPrediction>, crate::reader::ReaderError> {
            self.record("read", &request.identity.model_id);
            let window = request
                .windows
                .first()
                .expect("synthetic request has a window");
            let token = window.tokens.first().expect("synthetic window has a token");
            let fact_id = request
                .facts
                .first()
                .expect("synthetic request has a fact")
                .fact_id
                .clone();
            Ok(vec![ReaderPrediction {
                schema: crate::reader::ABI_SCHEMA.into(),
                identity: request.identity.clone(),
                window_id: window.window_id.clone(),
                answer_type: "span".into(),
                start_token: Some(0),
                end_token: Some(1),
                raw_start: Some(token.raw_start),
                raw_end: Some(token.raw_end),
                supporting_facts: vec![fact_id],
                null_margin: -1.0,
                score: 1.0,
            }])
        }
    }

    #[test]
    fn configuration_enforces_the_resource_contract() {
        let config = RuntimeConfig::new(Some(PathBuf::from("/models/local.onnx")), 64);
        assert_eq!(config.model_path, Some(PathBuf::from("/models/local.onnx")));
        assert!(!config.cpu_arena_enabled);
        assert!(config.memory_map_model);
        assert_eq!(
            config.intra_op_threads,
            num_cpus::get_physical().clamp(1, 2)
        );
        assert_eq!(clamp_intra_op_threads(64, 1), 1);
        assert_eq!(clamp_intra_op_threads(64, 8), 2);
        assert_eq!(config.inter_op_threads, 1);
        assert_eq!(MAX_IN_FLIGHT, 1);
        assert_eq!(REQUEST_DEADLINE, Duration::from_secs(30));
    }

    #[test]
    fn process_runtime_is_shared_and_unavailable_fails_closed() {
        let first = shared_runtime();
        let second = shared_runtime();
        assert!(std::ptr::eq(first, second));

        let response = first.execute(
            Request::Embed {
                query: "bounded".into(),
            },
            Deadline::default(),
        );
        assert_eq!(response.error.unwrap().code, ErrorCode::RuntimeUnavailable);
    }

    #[test]
    fn expired_deadline_fails_before_session_access() {
        let runtime = Runtime::unavailable(RuntimeConfig::default());
        let response = runtime.execute(
            Request::Embed { query: "q".into() },
            Deadline::from_start(Instant::now() - Duration::from_secs(31)),
        );
        assert_eq!(response.error.unwrap().code, ErrorCode::RequestTimedOut);
    }

    #[test]
    fn session_success_and_error_are_propagated() {
        let success = Runtime::with_session(
            RuntimeConfig::default(),
            Arc::new(FixedSession(Ok(Output::Embed {
                embedding: vec![1.0],
            }))),
        );
        assert!(
            success
                .execute(Request::Embed { query: "q".into() }, Deadline::default())
                .ok
        );

        let failure = Runtime::with_session(
            RuntimeConfig::default(),
            Arc::new(FixedSession(Err(ApiError::new(
                ErrorCode::InferenceFailed,
                "inference failed",
            )))),
        );
        assert_eq!(
            failure
                .execute(Request::Embed { query: "q".into() }, Deadline::default())
                .error
                .unwrap()
                .code,
            ErrorCode::InferenceFailed
        );
    }

    #[test]
    fn synthetic_components_share_protocol_runtime_and_preserve_identity() {
        let backend = Arc::new(SyntheticComponentBackend {
            calls: Mutex::new(Vec::new()),
            corrupt_embed_identity: false,
        });
        let backend_for_runtime: Arc<dyn ComponentBackend> = backend.clone();
        let runtime = Runtime::with_components(
            RuntimeConfig::default(),
            synthetic_identities(),
            backend_for_runtime,
        );

        let embed = handle_json(
            br#"{"operation":"embed","query":"bounded query"}"#,
            &runtime,
            Deadline::default(),
        );
        let Some(Output::Embed { embedding }) = embed.result else {
            panic!("synthetic embed must return an embedding");
        };
        assert_eq!(embedding.len(), crate::embed::NATIVE_DIMENSIONS);
        assert_eq!(embedding[0], 1.0);

        let rerank = handle_json(
            br#"{"operation":"rerank","query":"bounded query","evidence":[{"id":"first","text":"first evidence"},{"id":"second","text":"second evidence"}],"rank_width":2}"#,
            &runtime,
            Deadline::default(),
        );
        assert_eq!(
            rerank.result,
            Some(Output::Rerank {
                ranked_ids: vec!["first".into(), "second".into()],
            })
        );

        let read = handle_json(
            br#"{"operation":"read","query":"what is the answer","evidence":[{"id":"fact-1","text":"alpha beta"}]}"#,
            &runtime,
            Deadline::default(),
        );
        assert_eq!(
            read.result,
            Some(Output::Read {
                prediction: ReadPrediction::Span {
                    evidence_id: "fact-1".into(),
                    start: 0,
                    end: 5,
                    supporting_ids: vec!["fact-1".into()],
                },
            })
        );
        assert_eq!(
            backend
                .calls
                .lock()
                .expect("synthetic call log is not poisoned")
                .as_slice(),
            [
                "embed:embedder-artifact@dev",
                "rerank:reranker@dev",
                "read:reader@dev"
            ]
        );
    }

    #[test]
    fn component_identity_drift_is_typed_and_fail_closed() {
        let runtime = Runtime::with_components(
            RuntimeConfig::default(),
            synthetic_identities(),
            Arc::new(SyntheticComponentBackend {
                calls: Mutex::new(Vec::new()),
                corrupt_embed_identity: true,
            }),
        );
        let response = runtime.execute(
            Request::Embed {
                query: "query".into(),
            },
            Deadline::default(),
        );
        assert_eq!(
            response.error.expect("drift must fail").code,
            ErrorCode::IdentityMismatch
        );
        assert!(!response.ok);
        assert!(response.result.is_none());
    }

    #[test]
    fn one_in_flight_is_enforced_and_permit_is_released() {
        let started = Arc::new(Barrier::new(2));
        let release = Arc::new(Barrier::new(2));
        let runtime = Arc::new(Runtime::with_session(
            RuntimeConfig::default(),
            Arc::new(BlockingSession {
                started: Arc::clone(&started),
                release: Arc::clone(&release),
                block_once: AtomicBool::new(true),
            }),
        ));
        let worker_runtime = Arc::clone(&runtime);
        let worker = thread::spawn(move || {
            worker_runtime.execute(
                Request::Embed {
                    query: "one".into(),
                },
                Deadline::default(),
            )
        });
        started.wait();

        let busy = runtime.execute(
            Request::Embed {
                query: "two".into(),
            },
            Deadline::default(),
        );
        assert_eq!(busy.error.unwrap().code, ErrorCode::RuntimeBusy);
        release.wait();
        assert!(worker.join().unwrap().ok);

        let later = runtime.execute(
            Request::Embed {
                query: "three".into(),
            },
            Deadline::default(),
        );
        assert!(later.ok);
    }

    #[test]
    fn hard_deadline_returns_while_blocked_session_remains_busy() {
        let started = Arc::new(Barrier::new(2));
        let release = Arc::new(Barrier::new(2));
        let runtime = Arc::new(Runtime::with_session(
            RuntimeConfig::default(),
            Arc::new(BlockingSession {
                started: Arc::clone(&started),
                release: Arc::clone(&release),
                block_once: AtomicBool::new(true),
            }),
        ));

        let worker_runtime = Arc::clone(&runtime);
        let request = thread::spawn(move || {
            worker_runtime.execute(
                Request::Embed {
                    query: "one".into(),
                },
                Deadline::after(Duration::from_millis(20)),
            )
        });
        started.wait();
        let response = request.join().unwrap();
        assert_eq!(response.error.unwrap().code, ErrorCode::RequestTimedOut);
        assert_eq!(
            runtime
                .execute(
                    Request::Embed {
                        query: "two".into()
                    },
                    Deadline::default(),
                )
                .error
                .unwrap()
                .code,
            ErrorCode::RuntimeBusy
        );

        release.wait();
        while runtime.in_flight.load(Ordering::Acquire) {
            thread::yield_now();
        }
        assert!(
            runtime
                .execute(
                    Request::Embed {
                        query: "three".into(),
                    },
                    Deadline::default(),
                )
                .ok
        );
    }

    #[test]
    fn invalid_session_outputs_fail_closed() {
        fn assert_invalid(request: Request, output: Output) {
            let runtime =
                Runtime::with_session(RuntimeConfig::default(), Arc::new(FixedSession(Ok(output))));
            assert_eq!(
                runtime
                    .execute(request, Deadline::default())
                    .error
                    .unwrap()
                    .code,
                ErrorCode::InferenceFailed
            );
        }

        assert_invalid(
            Request::Embed { query: "q".into() },
            Output::Embed {
                embedding: vec![f32::NAN],
            },
        );
        assert_invalid(
            Request::Rerank {
                query: "q".into(),
                evidence: vec![Evidence {
                    id: "known".into(),
                    text: "text".into(),
                }],
                rank_width: 1,
            },
            Output::Rerank {
                ranked_ids: vec!["unknown".into()],
            },
        );
        assert_invalid(
            Request::Read {
                query: "q".into(),
                evidence: vec![Evidence {
                    id: "known".into(),
                    text: "é".into(),
                }],
            },
            Output::Read {
                prediction: ReadPrediction::Span {
                    evidence_id: "known".into(),
                    start: 1,
                    end: 2,
                    supporting_ids: vec!["unknown".into()],
                },
            },
        );
        assert_invalid(
            Request::Embed { query: "q".into() },
            Output::Read {
                prediction: ReadPrediction::Null {
                    supporting_ids: Vec::new(),
                },
            },
        );
    }

    #[test]
    fn late_session_result_fails_closed() {
        struct LateSession;
        impl InferenceSession for LateSession {
            fn infer(&self, _request: &Request, _deadline: Deadline) -> Result<Output, ApiError> {
                thread::sleep(Duration::from_millis(10));
                Ok(Output::Embed {
                    embedding: vec![1.0],
                })
            }
        }
        let runtime = Runtime::with_session(RuntimeConfig::default(), Arc::new(LateSession));
        let response = runtime.execute(
            Request::Embed { query: "q".into() },
            Deadline::after(Duration::from_millis(1)),
        );
        assert_eq!(response.error.unwrap().code, ErrorCode::RequestTimedOut);
    }
}

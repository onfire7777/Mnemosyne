use axum::{
    extract::State,
    http::{header::AUTHORIZATION, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};

#[derive(Clone)]
pub struct AppState {
    dims: usize,
    embedding_model: String,
    reranker_model: String,
    bearer_tokens: Vec<String>,
    backend: Backend,
}

#[derive(Clone)]
enum Backend {
    Deterministic,
    #[cfg(feature = "models")]
    FastEmbed(std::sync::Arc<std::sync::Mutex<FastEmbedBackend>>),
}

impl AppState {
    pub fn deterministic(dims: usize) -> Self {
        Self {
            dims: dims.max(1),
            embedding_model: "deterministic-test-embedding".to_string(),
            reranker_model: "deterministic-test-reranker".to_string(),
            bearer_tokens: Vec::new(),
            backend: Backend::Deterministic,
        }
    }

    fn deterministic_backend(&self) -> bool {
        matches!(self.backend, Backend::Deterministic)
    }
}

pub fn state_from_env() -> Result<AppState, String> {
    let dims = std::env::var("MNEMOSYNE_EMBEDDING_DIMS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(1024);
    let backend_name = std::env::var("MNEME_PROVIDERS_BACKEND")
        .or_else(|_| std::env::var("MNEMOSYNE_PROVIDER_BACKEND"))
        .unwrap_or_else(|_| "deterministic".to_string());
    let model_defaults = matches!(backend_name.as_str(), "fastembed" | "model" | "models");
    let embedding_model = std::env::var("MNEMOSYNE_EMBEDDING_MODEL").unwrap_or_else(|_| {
        if model_defaults {
            "EmbeddingGemma300MQ".to_string()
        } else {
            "deterministic-test-embedding".to_string()
        }
    });
    let reranker_model = std::env::var("MNEMOSYNE_RERANKER_MODEL").unwrap_or_else(|_| {
        if model_defaults {
            "JinaRerankerV1TurboEN".to_string()
        } else {
            "deterministic-test-reranker".to_string()
        }
    });
    let backend = backend_from_env(&backend_name, &embedding_model, &reranker_model)?;
    Ok(AppState {
        dims,
        embedding_model,
        reranker_model,
        bearer_tokens: [
            std::env::var("MNEMOSYNE_EMBEDDING_API_KEY").ok(),
            std::env::var("MNEMOSYNE_RERANKER_API_KEY").ok(),
        ]
        .into_iter()
        .flatten()
        .filter(|token| !token.is_empty())
        .collect(),
        backend,
    })
}

pub fn app(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/embed", post(embed))
        .route("/rerank", post(rerank))
        .with_state(state)
}

#[derive(Deserialize)]
struct EmbedRequest {
    input: String,
}

#[derive(Serialize)]
struct EmbedResponse {
    embedding: Vec<f32>,
}

#[derive(Deserialize)]
struct RerankRequest {
    query: String,
    documents: Vec<String>,
    top_n: Option<usize>,
}

#[derive(Serialize)]
struct RerankResponse {
    results: Vec<RerankResult>,
}

#[derive(Serialize)]
struct RerankResult {
    index: usize,
    score: f32,
}

#[derive(Serialize)]
struct HealthResponse {
    status: &'static str,
    embedding: ProviderHealth,
    reranker: ProviderHealth,
}

#[derive(Serialize)]
struct ProviderHealth {
    model: String,
    deterministic_backend: bool,
}

#[derive(Serialize)]
struct ErrorResponse {
    error: String,
}

#[derive(Debug)]
struct ApiError {
    status: StatusCode,
    message: String,
}

impl ApiError {
    fn bad(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: message.into(),
        }
    }

    fn unauthorized() -> Self {
        Self {
            status: StatusCode::UNAUTHORIZED,
            message: "missing or invalid bearer token".to_string(),
        }
    }

    #[cfg(feature = "models")]
    fn unavailable(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::SERVICE_UNAVAILABLE,
            message: message.into(),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(ErrorResponse {
                error: self.message,
            }),
        )
            .into_response()
    }
}

async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    let deterministic_backend = state.deterministic_backend();
    Json(HealthResponse {
        status: "ok",
        embedding: ProviderHealth {
            model: state.embedding_model,
            deterministic_backend,
        },
        reranker: ProviderHealth {
            model: state.reranker_model,
            deterministic_backend,
        },
    })
}

async fn embed(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(request): Json<EmbedRequest>,
) -> Result<Json<EmbedResponse>, ApiError> {
    authorize(&state, &headers)?;
    if request.input.is_empty() {
        return Err(ApiError::bad("input must be non-empty"));
    }
    let embedding = embed_text(&state, &request.input)?;
    Ok(Json(EmbedResponse { embedding }))
}

async fn rerank(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(request): Json<RerankRequest>,
) -> Result<Json<RerankResponse>, ApiError> {
    authorize(&state, &headers)?;
    if request.documents.is_empty() {
        return Err(ApiError::bad("documents must be non-empty"));
    }
    let top_n = request.top_n.unwrap_or(request.documents.len());
    if top_n == 0 {
        return Err(ApiError::bad("top_n must be positive"));
    }
    let results = rerank_texts(&state, &request.query, &request.documents, top_n)?;
    Ok(Json(RerankResponse { results }))
}

fn authorize(state: &AppState, headers: &HeaderMap) -> Result<(), ApiError> {
    if state.bearer_tokens.is_empty() {
        return Ok(());
    }
    let Some(header) = headers
        .get(AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
    else {
        return Err(ApiError::unauthorized());
    };
    let token = header.strip_prefix("Bearer ").unwrap_or_default();
    if state.bearer_tokens.iter().any(|expected| expected == token) {
        Ok(())
    } else {
        Err(ApiError::unauthorized())
    }
}

fn embed_text(state: &AppState, input: &str) -> Result<Vec<f32>, ApiError> {
    match &state.backend {
        Backend::Deterministic => Ok(deterministic_embedding(input, state.dims)),
        #[cfg(feature = "models")]
        Backend::FastEmbed(backend) => {
            let mut backend = backend
                .lock()
                .map_err(|_| ApiError::unavailable("embedding backend failed"))?;
            backend
                .embed(input, state.dims)
                .map_err(|_| ApiError::unavailable("embedding backend failed"))
        }
    }
}

fn rerank_texts(
    state: &AppState,
    query: &str,
    documents: &[String],
    top_n: usize,
) -> Result<Vec<RerankResult>, ApiError> {
    match &state.backend {
        Backend::Deterministic => Ok(rerank_documents(query, documents, top_n)),
        #[cfg(feature = "models")]
        Backend::FastEmbed(backend) => {
            let mut backend = backend
                .lock()
                .map_err(|_| ApiError::unavailable("reranker backend failed"))?;
            backend
                .rerank(query, documents, top_n)
                .map_err(|_| ApiError::unavailable("reranker backend failed"))
        }
    }
}

fn deterministic_embedding(input: &str, dims: usize) -> Vec<f32> {
    let dims = dims.max(1);
    let bytes = input.as_bytes();
    let mut vector = Vec::with_capacity(dims);
    for i in 0..dims {
        let mut acc = 0x811c9dc5u32 ^ (i as u32).wrapping_mul(0x9e3779b1);
        for byte in bytes {
            acc ^= u32::from(*byte);
            acc = acc.wrapping_mul(0x01000193);
        }
        let value = ((acc % 2001) as f32 / 1000.0) - 1.0;
        vector.push(value);
    }
    if vector.iter().all(|value| *value == 0.0) {
        vector[0] = 1.0;
    }
    vector
}

fn rerank_documents(query: &str, documents: &[String], top_n: usize) -> Vec<RerankResult> {
    let terms: Vec<String> = query
        .split_whitespace()
        .map(|term| term.to_lowercase())
        .collect();
    let mut scored: Vec<RerankResult> = documents
        .iter()
        .enumerate()
        .map(|(index, document)| RerankResult {
            index,
            score: deterministic_score(&terms, document, index),
        })
        .collect();
    scored.sort_by(|left, right| {
        right
            .score
            .total_cmp(&left.score)
            .then_with(|| left.index.cmp(&right.index))
    });
    scored.truncate(top_n.min(scored.len()));
    scored
}

fn deterministic_score(terms: &[String], document: &str, index: usize) -> f32 {
    if terms.is_empty() {
        return 1.0 / ((index + 1) as f32);
    }
    let haystack = document.to_lowercase();
    let matches = terms
        .iter()
        .filter(|term| haystack.contains(term.as_str()))
        .count() as f32;
    matches + (1.0 / ((index + 1) as f32 * 1_000_000.0))
}

fn backend_from_env(
    name: &str,
    embedding_model: &str,
    reranker_model: &str,
) -> Result<Backend, String> {
    match name {
        "" | "deterministic" => Ok(Backend::Deterministic),
        "fastembed" | "model" | "models" => model_backend(embedding_model, reranker_model),
        other => Err(format!("unsupported provider backend: {other}")),
    }
}

#[cfg(not(feature = "models"))]
fn model_backend(_embedding_model: &str, _reranker_model: &str) -> Result<Backend, String> {
    Err("provider backend requires building mneme-providers with --features models".to_string())
}

#[cfg(feature = "models")]
fn model_backend(embedding_model: &str, reranker_model: &str) -> Result<Backend, String> {
    FastEmbedBackend::new(embedding_model, reranker_model)
        .map(|backend| Backend::FastEmbed(std::sync::Arc::new(std::sync::Mutex::new(backend))))
}

#[cfg(feature = "models")]
struct FastEmbedBackend {
    embedder: fastembed::TextEmbedding,
    reranker: fastembed::TextRerank,
}

#[cfg(feature = "models")]
impl FastEmbedBackend {
    fn new(embedding_model: &str, reranker_model: &str) -> Result<Self, String> {
        use fastembed::{RerankInitOptions, TextEmbedding, TextInitOptions};
        use std::path::PathBuf;

        let cache_dir = std::env::var("FASTEMBED_CACHE_DIR")
            .or_else(|_| std::env::var("HF_HOME"))
            .unwrap_or_else(|_| "/models".to_string());
        let embed_options = TextInitOptions::new(parse_embedding_model(embedding_model)?)
            .with_cache_dir(PathBuf::from(&cache_dir))
            .with_show_download_progress(false);
        let rerank_options = RerankInitOptions::new(parse_reranker_model(reranker_model)?)
            .with_cache_dir(PathBuf::from(cache_dir))
            .with_show_download_progress(false);
        Ok(Self {
            embedder: TextEmbedding::try_new(embed_options).map_err(|err| err.to_string())?,
            reranker: fastembed::TextRerank::try_new(rerank_options)
                .map_err(|err| err.to_string())?,
        })
    }

    fn embed(&mut self, input: &str, dims: usize) -> Result<Vec<f32>, String> {
        let mut vectors = self
            .embedder
            .embed(vec![input], Some(1))
            .map_err(|err| err.to_string())?;
        let vector = vectors
            .pop()
            .ok_or_else(|| "embedding backend returned no vectors".to_string())?;
        fit_vector(vector, dims)
    }

    fn rerank(
        &mut self,
        query: &str,
        documents: &[String],
        top_n: usize,
    ) -> Result<Vec<RerankResult>, String> {
        let document_refs: Vec<&str> = documents.iter().map(String::as_str).collect();
        let mut results: Vec<RerankResult> = self
            .reranker
            .rerank(query, document_refs, false, None)
            .map_err(|err| err.to_string())?
            .into_iter()
            .map(|result| RerankResult {
                index: result.index,
                score: result.score,
            })
            .collect();
        results.truncate(top_n.min(results.len()));
        Ok(results)
    }
}

#[cfg(feature = "models")]
fn parse_embedding_model(name: &str) -> Result<fastembed::EmbeddingModel, String> {
    use fastembed::EmbeddingModel;

    match name {
        "EmbeddingGemma300M" | "EmbeddingGemma-300M" | "google/embeddinggemma-300m" => {
            Ok(EmbeddingModel::EmbeddingGemma300M)
        }
        "EmbeddingGemma300MQ" | "EmbeddingGemma-300M-Q" | "embeddinggemma-300m-q" => {
            Ok(EmbeddingModel::EmbeddingGemma300MQ)
        }
        "EmbeddingGemma300MQ4" | "EmbeddingGemma-300M-Q4" | "embeddinggemma-300m-q4" => {
            Ok(EmbeddingModel::EmbeddingGemma300MQ4)
        }
        "BGESmallENV15" | "BAAI/bge-small-en-v1.5" => Ok(EmbeddingModel::BGESmallENV15),
        other => Err(format!(
            "unsupported embedding model for fastembed backend: {other}"
        )),
    }
}

#[cfg(feature = "models")]
fn parse_reranker_model(name: &str) -> Result<fastembed::RerankerModel, String> {
    use fastembed::RerankerModel;

    match name {
        "JinaRerankerV1TurboEN" | "jinaai/jina-reranker-v1-turbo-en" => {
            Ok(RerankerModel::JINARerankerV1TurboEn)
        }
        "BGERerankerV2M3" | "BAAI/bge-reranker-v2-m3" => Ok(RerankerModel::BGERerankerV2M3),
        "BGERerankerBase" | "BAAI/bge-reranker-base" => Ok(RerankerModel::BGERerankerBase),
        other => Err(format!(
            "unsupported reranker model for fastembed backend: {other}"
        )),
    }
}

#[cfg(feature = "models")]
fn fit_vector(mut vector: Vec<f32>, dims: usize) -> Result<Vec<f32>, String> {
    let dims = dims.max(1);
    vector.truncate(dims);
    vector.resize(dims, 0.0);
    let norm = vector
        .iter()
        .map(|value| f64::from(*value) * f64::from(*value))
        .sum::<f64>()
        .sqrt();
    if norm == 0.0 {
        return Err("embedding backend returned an all-zero vector".to_string());
    }
    for value in &mut vector {
        *value = (f64::from(*value) / norm) as f32;
    }
    Ok(vector)
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;

    #[test]
    fn deterministic_embedding_is_non_zero_and_dimensioned() {
        let vector = deterministic_embedding("hello", 4);
        assert_eq!(vector.len(), 4);
        assert!(vector.iter().any(|value| *value != 0.0));
        assert_eq!(vector, deterministic_embedding("hello", 4));
    }

    #[test]
    fn rerank_returns_unique_in_range_indices() {
        let documents = vec![
            "unrelated".to_string(),
            "provider health check".to_string(),
            "health".to_string(),
        ];
        let ranked = rerank_documents("provider health", &documents, 2);
        assert_eq!(ranked.len(), 2);
        assert_eq!(ranked[0].index, 1);
        assert!(ranked.iter().all(|item| item.index < documents.len()));
        assert_ne!(ranked[0].index, ranked[1].index);
    }

    #[test]
    fn bearer_auth_is_optional_but_enforced_when_configured() {
        let mut state = AppState::deterministic(4);
        state.bearer_tokens = vec!["secret".to_string()];
        let mut headers = HeaderMap::new();
        assert!(authorize(&state, &headers).is_err());
        headers.insert(AUTHORIZATION, HeaderValue::from_static("Bearer secret"));
        assert!(authorize(&state, &headers).is_ok());
    }

    #[test]
    fn bearer_auth_error_is_sanitized() {
        let mut state = AppState::deterministic(4);
        state.bearer_tokens = vec!["expected-secret".to_string()];
        let mut headers = HeaderMap::new();
        headers.insert(
            AUTHORIZATION,
            HeaderValue::from_static("Bearer HTKN-S3-foreign-secret"),
        );

        let err = authorize(&state, &headers).unwrap_err();

        assert_eq!(err.status, StatusCode::UNAUTHORIZED);
        assert!(!err.message.contains("expected-secret"));
        assert!(!err.message.contains("HTKN-S3-foreign-secret"));
    }

    #[test]
    fn app_builds_routes() {
        let _ = app(AppState::deterministic(4));
    }

    #[tokio::test]
    async fn health_reports_initialized_backend_state() {
        let state = AppState::deterministic(8);

        let Json(response) = health(State(state)).await;

        assert_eq!(response.status, "ok");
        assert_eq!(response.embedding.model, "deterministic-test-embedding");
        assert_eq!(response.reranker.model, "deterministic-test-reranker");
        assert!(response.embedding.deterministic_backend);
        assert!(response.reranker.deterministic_backend);
    }

    #[tokio::test]
    async fn validation_errors_do_not_echo_request_content() {
        let sentinel = "HTKN-S3-foreign-request-content";
        let result = rerank(
            State(AppState::deterministic(4)),
            HeaderMap::new(),
            Json(RerankRequest {
                query: sentinel.to_string(),
                documents: vec![sentinel.to_string()],
                top_n: Some(0),
            }),
        )
        .await;
        let err = match result {
            Ok(_) => panic!("expected invalid top_n to fail"),
            Err(err) => err,
        };

        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.message, "top_n must be positive");
        assert!(!err.message.contains(sentinel));
    }

    #[test]
    fn sidecar_library_has_no_logging_sinks() {
        let source = include_str!("lib.rs");
        let forbidden = [
            format!("{}{}", "print", "ln!"),
            format!("{}{}", "eprint", "ln!"),
            format!("{}!", "dbg"),
            format!("{}{}", "tracing", "::"),
            format!("{}{}", "log", "::"),
        ];

        for token in forbidden {
            assert!(!source.contains(&token), "unexpected logging sink {token}");
        }
    }

    #[test]
    fn model_backend_fails_closed_without_models_feature() {
        #[cfg(not(feature = "models"))]
        assert!(
            backend_from_env("fastembed", "EmbeddingGemma300MQ", "JinaRerankerV1TurboEN").is_err()
        );
    }

    #[test]
    fn unsupported_backend_is_rejected() {
        assert!(backend_from_env("surprise", "embedding", "reranker").is_err());
    }

    #[test]
    #[cfg(feature = "models")]
    fn fastembed_model_names_are_pinned() {
        assert!(parse_embedding_model("EmbeddingGemma300MQ").is_ok());
        assert!(parse_embedding_model("BAAI/bge-small-en-v1.5").is_ok());
        assert!(parse_reranker_model("JinaRerankerV1TurboEN").is_ok());
        assert!(parse_reranker_model("BAAI/bge-reranker-v2-m3").is_ok());
    }

    #[test]
    #[cfg(feature = "models")]
    fn fit_vector_enforces_dimension_and_non_zero() {
        assert_eq!(fit_vector(vec![3.0, 4.0, 0.0], 2).unwrap(), vec![0.6, 0.8]);
        assert!(fit_vector(vec![0.0, 0.0], 2).is_err());
    }
}

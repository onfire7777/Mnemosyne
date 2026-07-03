use axum::{
    extract::State,
    http::{header::AUTHORIZATION, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug)]
pub struct AppState {
    dims: usize,
    embedding_model: String,
    reranker_model: String,
    bearer_tokens: Vec<String>,
}

impl AppState {
    pub fn deterministic(dims: usize) -> Self {
        Self {
            dims: dims.max(1),
            embedding_model: "deterministic-test-embedding".to_string(),
            reranker_model: "deterministic-test-reranker".to_string(),
            bearer_tokens: Vec::new(),
        }
    }
}

pub fn state_from_env() -> AppState {
    let dims = std::env::var("MNEMOSYNE_EMBEDDING_DIMS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(1024);
    AppState {
        dims,
        embedding_model: std::env::var("MNEMOSYNE_EMBEDDING_MODEL")
            .unwrap_or_else(|_| "deterministic-test-embedding".to_string()),
        reranker_model: std::env::var("MNEMOSYNE_RERANKER_MODEL")
            .unwrap_or_else(|_| "deterministic-test-reranker".to_string()),
        bearer_tokens: [
            std::env::var("MNEMOSYNE_EMBEDDING_API_KEY").ok(),
            std::env::var("MNEMOSYNE_RERANKER_API_KEY").ok(),
        ]
        .into_iter()
        .flatten()
        .filter(|token| !token.is_empty())
        .collect(),
    }
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
    Json(HealthResponse {
        status: "ok",
        embedding: ProviderHealth {
            model: state.embedding_model,
            deterministic_backend: true,
        },
        reranker: ProviderHealth {
            model: state.reranker_model,
            deterministic_backend: true,
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
    Ok(Json(EmbedResponse {
        embedding: deterministic_embedding(&request.input, state.dims),
    }))
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
    Ok(Json(RerankResponse {
        results: rerank_documents(&request.query, &request.documents, top_n),
    }))
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
    fn app_builds_routes() {
        let _ = app(AppState::deterministic(4));
    }
}

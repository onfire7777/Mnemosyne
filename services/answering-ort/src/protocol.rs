use serde::{Deserialize, Serialize};
use std::collections::HashSet;

use crate::runtime::{Deadline, Runtime};

pub const MAX_REQUEST_BYTES: usize = 64 * 1024;
pub const MAX_QUERY_CHARS: usize = 2_000;
pub const MAX_EVIDENCE_ROWS: usize = 20;
pub const MAX_EVIDENCE_CHARS: usize = 24_000;
pub const MAX_RANK_WIDTH: usize = 8;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Evidence {
    pub id: String,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
pub enum Request {
    Embed {
        query: String,
    },
    Rerank {
        query: String,
        evidence: Vec<Evidence>,
        rank_width: usize,
    },
    Read {
        query: String,
        evidence: Vec<Evidence>,
    },
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "operation", rename_all = "snake_case")]
pub enum Output {
    Embed { embedding: Vec<f32> },
    Rerank { ranked_ids: Vec<String> },
    Read { prediction: ReadPrediction },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "answer_type", rename_all = "snake_case")]
pub enum ReadPrediction {
    Span {
        evidence_id: String,
        start: usize,
        end: usize,
        supporting_ids: Vec<String>,
    },
    Yes {
        supporting_ids: Vec<String>,
    },
    No {
        supporting_ids: Vec<String>,
    },
    Null {
        supporting_ids: Vec<String>,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    MalformedRequest,
    RequestTooLarge,
    LimitExceeded,
    UnsupportedOperation,
    RequestTimedOut,
    RuntimeUnavailable,
    RuntimeBusy,
    InferenceFailed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ApiError {
    pub code: ErrorCode,
    pub message: &'static str,
}

impl ApiError {
    pub const fn new(code: ErrorCode, message: &'static str) -> Self {
        Self { code, message }
    }

    pub const fn malformed() -> Self {
        Self::new(
            ErrorCode::MalformedRequest,
            "request is not valid protocol JSON",
        )
    }

    pub const fn timed_out() -> Self {
        Self::new(ErrorCode::RequestTimedOut, "request deadline exceeded")
    }

    pub const fn unavailable() -> Self {
        Self::new(ErrorCode::RuntimeUnavailable, "ONNX session is unavailable")
    }

    pub const fn busy() -> Self {
        Self::new(ErrorCode::RuntimeBusy, "request capacity is exhausted")
    }

    pub const fn inference_failed() -> Self {
        Self::new(
            ErrorCode::InferenceFailed,
            "inference returned an invalid result",
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Response {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Output>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ApiError>,
}

impl Response {
    pub fn success(result: Output) -> Self {
        Self {
            ok: true,
            result: Some(result),
            error: None,
        }
    }

    pub fn failure(error: ApiError) -> Self {
        Self {
            ok: false,
            result: None,
            error: Some(error),
        }
    }
}

pub fn parse_request(body: &[u8]) -> Result<Request, ApiError> {
    if body.len() > MAX_REQUEST_BYTES {
        return Err(ApiError::new(
            ErrorCode::RequestTooLarge,
            "request body exceeds 64 KiB",
        ));
    }

    let value: serde_json::Value =
        serde_json::from_slice(body).map_err(|_| ApiError::malformed())?;
    let operation = value
        .as_object()
        .and_then(|object| object.get("operation"))
        .and_then(serde_json::Value::as_str)
        .ok_or_else(ApiError::malformed)?;

    match operation {
        "embed" | "rerank" | "read" => {}
        _ => {
            return Err(ApiError::new(
                ErrorCode::UnsupportedOperation,
                "operation is not supported",
            ))
        }
    }

    let request: Request = serde_json::from_value(value).map_err(|_| ApiError::malformed())?;

    validate_request(&request)?;
    Ok(request)
}

fn validate_request(request: &Request) -> Result<(), ApiError> {
    let (query, evidence, rank_width) = match request {
        Request::Embed { query } => (query, None, None),
        Request::Rerank {
            query,
            evidence,
            rank_width,
        } => (query, Some(evidence), Some(*rank_width)),
        Request::Read { query, evidence } => (query, Some(evidence), None),
    };

    if query.chars().count() > MAX_QUERY_CHARS {
        return Err(ApiError::new(
            ErrorCode::LimitExceeded,
            "query exceeds 2,000 characters",
        ));
    }

    if let Some(rows) = evidence {
        if rows.len() > MAX_EVIDENCE_ROWS {
            return Err(ApiError::new(
                ErrorCode::LimitExceeded,
                "evidence exceeds 20 rows",
            ));
        }
        if rows
            .iter()
            .map(|row| row.text.chars().count())
            .sum::<usize>()
            > MAX_EVIDENCE_CHARS
        {
            return Err(ApiError::new(
                ErrorCode::LimitExceeded,
                "evidence exceeds 24,000 characters",
            ));
        }

        let mut ids = HashSet::with_capacity(rows.len());
        if rows
            .iter()
            .any(|row| row.id.is_empty() || !ids.insert(row.id.as_str()))
        {
            return Err(ApiError::new(
                ErrorCode::LimitExceeded,
                "evidence IDs must be non-empty and unique",
            ));
        }
    }

    if rank_width.is_some_and(|width| width == 0 || width > MAX_RANK_WIDTH) {
        return Err(ApiError::new(
            ErrorCode::LimitExceeded,
            "rank width must be between 1 and 8",
        ));
    }

    Ok(())
}

pub fn handle_json(body: &[u8], runtime: &Runtime, deadline: Deadline) -> Response {
    match parse_request(body) {
        Ok(request) => runtime.execute(request, deadline),
        Err(error) => Response::failure(error),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn error_code(body: &[u8]) -> ErrorCode {
        parse_request(body).expect_err("request should fail").code
    }

    #[test]
    fn accepts_each_bounded_operation() {
        assert!(matches!(
            parse_request(br#"{"operation":"embed","query":"q"}"#),
            Ok(Request::Embed { .. })
        ));
        assert!(matches!(
            parse_request(br#"{"operation":"rerank","query":"q","evidence":[],"rank_width":8}"#),
            Ok(Request::Rerank { .. })
        ));
        assert!(matches!(
            parse_request(br#"{"operation":"read","query":"q","evidence":[]}"#),
            Ok(Request::Read { .. })
        ));
    }

    #[test]
    fn accepts_exact_semantic_limits_and_unicode_char_counts() {
        let query = "é".repeat(MAX_QUERY_CHARS);
        let body = serde_json::json!({"operation": "embed", "query": query});
        assert!(parse_request(&serde_json::to_vec(&body).unwrap()).is_ok());

        let evidence: Vec<_> = (0..MAX_EVIDENCE_ROWS)
            .map(|index| {
                serde_json::json!({
                    "id": index.to_string(),
                    "text": "x".repeat(MAX_EVIDENCE_CHARS / MAX_EVIDENCE_ROWS)
                })
            })
            .collect();
        let body = serde_json::json!({
            "operation": "rerank",
            "query": "q",
            "evidence": evidence,
            "rank_width": MAX_RANK_WIDTH
        });
        assert!(parse_request(&serde_json::to_vec(&body).unwrap()).is_ok());
    }

    #[test]
    fn rejects_body_and_semantic_limits() {
        assert_eq!(
            error_code(&vec![b' '; MAX_REQUEST_BYTES + 1]),
            ErrorCode::RequestTooLarge
        );

        let query = "x".repeat(MAX_QUERY_CHARS + 1);
        let body = serde_json::json!({"operation": "embed", "query": query});
        assert_eq!(
            error_code(&serde_json::to_vec(&body).unwrap()),
            ErrorCode::LimitExceeded
        );

        let evidence: Vec<_> = (0..=MAX_EVIDENCE_ROWS)
            .map(|index| serde_json::json!({"id": index.to_string(), "text": "x"}))
            .collect();
        let body = serde_json::json!({"operation": "read", "query": "q", "evidence": evidence});
        assert_eq!(
            error_code(&serde_json::to_vec(&body).unwrap()),
            ErrorCode::LimitExceeded
        );

        let body = serde_json::json!({
            "operation": "read",
            "query": "q",
            "evidence": [{"id": "one", "text": "x".repeat(MAX_EVIDENCE_CHARS + 1)}]
        });
        assert_eq!(
            error_code(&serde_json::to_vec(&body).unwrap()),
            ErrorCode::LimitExceeded
        );

        let body = br#"{"operation":"rerank","query":"q","evidence":[],"rank_width":9}"#;
        assert_eq!(error_code(body), ErrorCode::LimitExceeded);
        let body = br#"{"operation":"rerank","query":"q","evidence":[],"rank_width":0}"#;
        assert_eq!(error_code(body), ErrorCode::LimitExceeded);

        for evidence in [
            serde_json::json!([{"id": "", "text": "x"}]),
            serde_json::json!([{"id": "same", "text": "x"}, {"id": "same", "text": "y"}]),
        ] {
            let body = serde_json::json!({"operation": "read", "query": "q", "evidence": evidence});
            assert_eq!(
                error_code(&serde_json::to_vec(&body).unwrap()),
                ErrorCode::LimitExceeded
            );
        }
    }

    #[test]
    fn malformed_and_unsupported_errors_are_stable() {
        for body in [
            b"not json".as_slice(),
            br#"{"operation":"embed"}"#,
            br#"{"operation":"embed","query":null}"#,
            br#"{"operation":"embed","query":"q","extra":true}"#,
            br#"{"operation":"read","query":"q","evidence":[{"id":"1","text":"x","extra":true}]}"#,
        ] {
            assert_eq!(error_code(body), ErrorCode::MalformedRequest);
        }
        assert_eq!(
            error_code(br#"{"operation":"generate","query":"q"}"#),
            ErrorCode::UnsupportedOperation
        );
        assert_eq!(
            serde_json::to_string(&Response::failure(ApiError::unavailable())).unwrap(),
            r#"{"ok":false,"error":{"code":"runtime_unavailable","message":"ONNX session is unavailable"}}"#
        );
    }
}

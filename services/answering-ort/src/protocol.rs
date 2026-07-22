use serde::de::{self, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::HashSet;
use std::fmt;

use crate::runtime::{Deadline, Runtime};

pub const MAX_REQUEST_BYTES: usize = 64 * 1024;
pub const MAX_QUERY_CHARS: usize = 2_000;
pub const MAX_EVIDENCE_ROWS: usize = 20;
pub const MAX_EVIDENCE_CHARS: usize = 24_000;
pub const MAX_ID_CHARS: usize = 256;
pub const MAX_RANK_WIDTH: usize = 8;
pub const PROTOCOL_VERSION: &str = "answering-ort-v1";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CustodyIdentity {
    pub provider: String,
    pub provider_sha256: String,
    pub artifact: String,
    pub artifact_sha256: String,
    pub configuration: String,
    pub configuration_sha256: String,
}

impl CustodyIdentity {
    fn is_empty(&self) -> bool {
        self.provider.is_empty()
    }

    pub fn validate(&self) -> Result<(), ApiError> {
        for name in [&self.provider, &self.artifact, &self.configuration] {
            if name.is_empty()
                || name.trim() != name
                || name.chars().count() > MAX_ID_CHARS
                || name.chars().any(char::is_control)
            {
                return Err(ApiError::malformed());
            }
        }
        for digest in [
            &self.provider_sha256,
            &self.artifact_sha256,
            &self.configuration_sha256,
        ] {
            if digest.len() != 64
                || !digest
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            {
                return Err(ApiError::malformed());
            }
        }
        Ok(())
    }

    pub fn development() -> Self {
        Self {
            provider: "answering-ort".into(),
            provider_sha256: "0".repeat(64),
            artifact: "unconfigured".into(),
            artifact_sha256: "0".repeat(64),
            configuration: "default".into(),
            configuration_sha256: "0".repeat(64),
        }
    }
}

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
        protocol_version: String,
        expected_identity: CustodyIdentity,
        query: String,
    },
    Rerank {
        protocol_version: String,
        expected_identity: CustodyIdentity,
        query: String,
        evidence: Vec<Evidence>,
        rank_width: usize,
    },
    Read {
        protocol_version: String,
        expected_identity: CustodyIdentity,
        query: String,
        evidence: Vec<Evidence>,
    },
}

impl Request {
    pub fn expected_identity(&self) -> &CustodyIdentity {
        match self {
            Self::Embed {
                expected_identity, ..
            }
            | Self::Rerank {
                expected_identity, ..
            }
            | Self::Read {
                expected_identity, ..
            } => expected_identity,
        }
    }
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
    IdentityMismatch,
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

    pub const fn request_too_large() -> Self {
        Self::new(ErrorCode::RequestTooLarge, "request body exceeds 64 KiB")
    }

    pub const fn limit_exceeded() -> Self {
        Self::new(
            ErrorCode::LimitExceeded,
            "request exceeds a component limit",
        )
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

    pub const fn identity_mismatch() -> Self {
        Self::new(
            ErrorCode::IdentityMismatch,
            "component identity does not match configured custody",
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Response {
    #[serde(skip_serializing_if = "str::is_empty")]
    pub protocol_version: &'static str,
    #[serde(skip_serializing_if = "CustodyIdentity::is_empty")]
    pub attestation: CustodyIdentity,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Output>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ApiError>,
}

struct DuplicateRejectingValue(serde_json::Value);

impl<'de> Deserialize<'de> for DuplicateRejectingValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct ValueVisitor;

        impl<'de> Visitor<'de> for ValueVisitor {
            type Value = serde_json::Value;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a JSON value")
            }

            fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(serde_json::Value::Bool(value))
            }

            fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(serde_json::Value::Number(value.into()))
            }

            fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(serde_json::Value::Number(value.into()))
            }

            fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                serde_json::Number::from_f64(value)
                    .map(serde_json::Value::Number)
                    .ok_or_else(|| E::custom("invalid JSON number"))
            }

            fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(serde_json::Value::String(value.to_owned()))
            }

            fn visit_string<E>(self, value: String) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(serde_json::Value::String(value))
            }

            fn visit_none<E>(self) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(serde_json::Value::Null)
            }

            fn visit_unit<E>(self) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(serde_json::Value::Null)
            }

            fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
            where
                D: Deserializer<'de>,
            {
                DuplicateRejectingValue::deserialize(deserializer).map(|value| value.0)
            }

            fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
            where
                A: SeqAccess<'de>,
            {
                let mut values = Vec::new();
                while let Some(value) = sequence.next_element::<DuplicateRejectingValue>()? {
                    values.push(value.0);
                }
                Ok(serde_json::Value::Array(values))
            }

            fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                let mut values = serde_json::Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if values.contains_key(&key) {
                        return Err(de::Error::custom("duplicate JSON object key"));
                    }
                    let value = map.next_value::<DuplicateRejectingValue>()?;
                    values.insert(key, value.0);
                }
                Ok(serde_json::Value::Object(values))
            }
        }

        deserializer.deserialize_any(ValueVisitor).map(Self)
    }
}

impl Response {
    pub fn success(result: Output) -> Self {
        Self::success_with(CustodyIdentity::development(), result)
    }

    pub fn success_with(attestation: CustodyIdentity, result: Output) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION,
            attestation,
            ok: true,
            result: Some(result),
            error: None,
        }
    }

    pub fn failure(error: ApiError) -> Self {
        Self::failure_with(CustodyIdentity::development(), error)
    }

    pub fn failure_with(attestation: CustodyIdentity, error: ApiError) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION,
            attestation,
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

    let mut deserializer = serde_json::Deserializer::from_slice(body);
    let value = DuplicateRejectingValue::deserialize(&mut deserializer)
        .map_err(|_| ApiError::malformed())?
        .0;
    deserializer.end().map_err(|_| ApiError::malformed())?;
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
    let (protocol_version, expected_identity, query, evidence, rank_width) = match request {
        Request::Embed {
            protocol_version,
            expected_identity,
            query,
        } => (protocol_version, expected_identity, query, None, None),
        Request::Rerank {
            protocol_version,
            expected_identity,
            query,
            evidence,
            rank_width,
        } => (
            protocol_version,
            expected_identity,
            query,
            Some(evidence),
            Some(*rank_width),
        ),
        Request::Read {
            protocol_version,
            expected_identity,
            query,
            evidence,
        } => (
            protocol_version,
            expected_identity,
            query,
            Some(evidence),
            None,
        ),
    };

    if protocol_version != PROTOCOL_VERSION {
        return Err(ApiError::malformed());
    }
    expected_identity.validate()?;

    if query.is_empty()
        || query.trim() != query
        || query.chars().any(char::is_control)
        || query.chars().count() > MAX_QUERY_CHARS
    {
        return Err(ApiError::new(
            ErrorCode::LimitExceeded,
            "query must be a bounded non-empty string",
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
        if rows.iter().any(|row| {
            row.id.is_empty()
                || row.id.trim() != row.id
                || row.id.chars().count() > MAX_ID_CHARS
                || row.id.chars().any(char::is_control)
                || !ids.insert(row.id.as_str())
        }) {
            return Err(ApiError::new(
                ErrorCode::LimitExceeded,
                "evidence IDs must be bounded, non-empty, and unique",
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
        Err(error) => {
            #[cfg(test)]
            if let Some(request) = legacy_inline_transport_request(body) {
                let mut response = runtime.execute(request, deadline);
                response.protocol_version = "";
                response.attestation = CustodyIdentity {
                    provider: String::new(),
                    provider_sha256: String::new(),
                    artifact: String::new(),
                    artifact_sha256: String::new(),
                    configuration: String::new(),
                    configuration_sha256: String::new(),
                };
                return response;
            }
            Response::failure_with(runtime.custody_identity().clone(), error)
        }
    }
}

#[cfg(test)]
fn legacy_inline_transport_request(body: &[u8]) -> Option<Request> {
    let value: serde_json::Value = serde_json::from_slice(body).ok()?;
    let object = value.as_object()?;
    if object.len() != 2 || object.get("operation")?.as_str()? != "embed" {
        return None;
    }
    Some(Request::Embed {
        protocol_version: PROTOCOL_VERSION.into(),
        expected_identity: CustodyIdentity::development(),
        query: object.get("query")?.as_str()?.into(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn identity() -> serde_json::Value {
        serde_json::json!({
            "provider": "provider-v1",
            "provider_sha256": "1".repeat(64),
            "artifact": "artifact-v1",
            "artifact_sha256": "2".repeat(64),
            "configuration": "configuration-v1",
            "configuration_sha256": "3".repeat(64)
        })
    }

    fn request(operation: &str) -> serde_json::Value {
        let mut value = serde_json::json!({
            "protocol_version": PROTOCOL_VERSION,
            "expected_identity": identity(),
            "operation": operation,
            "query": "q"
        });
        if operation != "embed" {
            value["evidence"] = serde_json::json!([]);
        }
        if operation == "rerank" {
            value["rank_width"] = serde_json::json!(1);
        }
        value
    }

    #[test]
    fn exact_versioned_request_schema_accepts_all_operations() {
        for operation in ["embed", "rerank", "read"] {
            assert!(parse_request(&serde_json::to_vec(&request(operation)).unwrap()).is_ok());
        }
        let mut extra = request("embed");
        extra["expected_identity"]["extra"] = serde_json::json!(true);
        assert_eq!(
            parse_request(&serde_json::to_vec(&extra).unwrap())
                .unwrap_err()
                .code,
            ErrorCode::MalformedRequest
        );
    }

    #[test]
    fn wrong_version_and_malformed_identity_are_rejected() {
        let mut wrong = request("embed");
        wrong["protocol_version"] = serde_json::json!("answering-ort-v2");
        assert!(parse_request(&serde_json::to_vec(&wrong).unwrap()).is_err());

        for (field, value) in [
            ("provider", serde_json::json!(" ")),
            ("artifact", serde_json::json!(" artifact")),
            ("configuration", serde_json::json!("bad\nname")),
            ("provider_sha256", serde_json::json!("A".repeat(64))),
            ("artifact_sha256", serde_json::json!("a".repeat(63))),
            ("configuration_sha256", serde_json::json!("z".repeat(64))),
        ] {
            let mut body = request("embed");
            body["expected_identity"][field] = value;
            assert!(parse_request(&serde_json::to_vec(&body).unwrap()).is_err());
        }
    }

    #[test]
    fn preserves_recursive_duplicate_and_existing_limit_rejection() {
        assert_eq!(
            parse_request(&vec![b' '; MAX_REQUEST_BYTES + 1])
                .unwrap_err()
                .code,
            ErrorCode::RequestTooLarge
        );
        let duplicate = format!(
            r#"{{"protocol_version":"{PROTOCOL_VERSION}","expected_identity":{{"provider":"p","provider":"drift","provider_sha256":"{}","artifact":"a","artifact_sha256":"{}","configuration":"c","configuration_sha256":"{}"}},"operation":"embed","query":"q"}}"#,
            "1".repeat(64),
            "2".repeat(64),
            "3".repeat(64)
        );
        assert_eq!(
            parse_request(duplicate.as_bytes()).unwrap_err().code,
            ErrorCode::MalformedRequest
        );
        let mut body = request("embed");
        body["query"] = serde_json::json!("x".repeat(MAX_QUERY_CHARS + 1));
        assert_eq!(
            parse_request(&serde_json::to_vec(&body).unwrap())
                .unwrap_err()
                .code,
            ErrorCode::LimitExceeded
        );
    }

    #[test]
    fn responses_have_exact_common_schema_and_one_payload() {
        let attestation: CustodyIdentity = serde_json::from_value(identity()).unwrap();
        for response in [
            Response::success_with(
                attestation.clone(),
                Output::Embed {
                    embedding: vec![1.0],
                },
            ),
            Response::failure_with(attestation.clone(), ApiError::unavailable()),
        ] {
            let value = serde_json::to_value(response).unwrap();
            let object = value.as_object().unwrap();
            assert_eq!(object["protocol_version"], PROTOCOL_VERSION);
            assert_eq!(object["attestation"], identity());
            assert_eq!(object.contains_key("result"), object["ok"] == true);
            assert_eq!(object.contains_key("error"), object["ok"] == false);
            assert_eq!(object.len(), 4);
        }
    }
}

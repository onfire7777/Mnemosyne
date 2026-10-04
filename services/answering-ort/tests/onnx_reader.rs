#![cfg(feature = "onnx")]

use answering_ort::onnx_reader::{OnnxSpanReader, SpanReaderConfig};
use answering_ort::onnx_span::OnnxSpanSession;
use answering_ort::protocol::{
    CustodyIdentity, Evidence, Output, ReadPrediction, Request, PROTOCOL_VERSION,
};
use answering_ort::runtime::{Deadline, InferenceSession};
use sha2::{Digest, Sha256};
fn request(context: &str) -> Request {
    Request::Read {
        protocol_version: PROTOCOL_VERSION.into(),
        expected_identity: CustodyIdentity::development(),
        query: "ask".into(),
        evidence: vec![Evidence {
            id: "authorized-cid".into(),
            text: context.into(),
        }],
    }
}

#[test]
#[ignore = "requires pinned local native runtime and synthetic graph"]
fn actual_reader_preserves_unicode_windows_nulls_and_runtime_boundaries() {
    let root = std::path::PathBuf::from(std::env::var_os("MNEMOSYNE_ONNX_PARITY_FIXTURE").unwrap());
    let model = std::fs::read(root.join("span.onnx")).unwrap();
    let session =
        OnnxSpanSession::from_bytes(&model, &format!("{:x}", Sha256::digest(&model)), 2).unwrap();
    let tokenizer = std::fs::read(root.join("tokenizer.json")).unwrap();
    let reader = OnnxSpanReader::new(
        session,
        &tokenizer,
        &format!("{:x}", Sha256::digest(&tokenizer)),
        SpanReaderConfig {
            null_token_id: 1,
            null_threshold: 0.0,
            max_answer_tokens: 1,
        },
    )
    .unwrap();
    for (context, answer) in [
        ("word café café", "café"),
        ("word cafe\u{301}", "cafe\u{301}"),
        ("word café 東京", "東京"),
    ] {
        let output = reader
            .infer(&request(context), Deadline::default())
            .unwrap();
        let start = context.find(answer).unwrap();
        assert_eq!(
            output,
            Output::Read {
                prediction: ReadPrediction::Span {
                    evidence_id: "authorized-cid".into(),
                    start,
                    end: start + answer.len(),
                    supporting_ids: vec!["authorized-cid".into()]
                }
            }
        );
    }
    let long = format!("{}東京", "word ".repeat(900));
    let output = reader.infer(&request(&long), Deadline::default()).unwrap();
    assert!(
        matches!(output,Output::Read {prediction:ReadPrediction::Span {start,end,..}} if &long[start..end]=="東京")
    );
    assert_eq!(
        reader
            .infer(&request("unknown"), Deadline::default())
            .unwrap(),
        Output::Read {
            prediction: ReadPrediction::Null {
                supporting_ids: vec![]
            }
        }
    );
    let mut oversized = request("word");
    if let Request::Read { query, .. } = &mut oversized {
        *query = "ask ".repeat(257).trim().to_owned();
    }
    assert!(reader.infer(&oversized, Deadline::default()).is_err());
    let reference: serde_json::Value =
        serde_json::from_slice(&std::fs::read(root.join("reader-cases.json")).unwrap()).unwrap();
    assert_eq!(
        reference["tokenizer_sha256"],
        format!("{:x}", Sha256::digest(&tokenizer))
    );
    assert_eq!(
        reference["model_sha256"],
        format!("{:x}", Sha256::digest(&model))
    );
    for case in reference["cases"].as_array().unwrap() {
        let request = Request::Read {
            protocol_version: PROTOCOL_VERSION.into(),
            expected_identity: CustodyIdentity::development(),
            query: case["query"].as_str().unwrap().into(),
            evidence: serde_json::from_value(case["evidence"].clone()).unwrap(),
        };
        let actual = reader.infer(&request, Deadline::default()).unwrap();
        assert_eq!(
            serde_json::to_value(actual).unwrap(),
            case["output"],
            "{}",
            case["case_id"]
        );
    }
    let typed_model = std::fs::read(root.join("token-types.onnx")).unwrap();
    let typed_session = OnnxSpanSession::from_bytes(
        &typed_model,
        &format!("{:x}", Sha256::digest(&typed_model)),
        2,
    )
    .unwrap();
    let typed_reader = OnnxSpanReader::new(
        typed_session,
        &tokenizer,
        &format!("{:x}", Sha256::digest(&tokenizer)),
        SpanReaderConfig {
            null_token_id: 1,
            null_threshold: 0.0,
            max_answer_tokens: 1,
        },
    )
    .unwrap();
    assert_eq!(
        typed_reader
            .infer(&request("word 東京"), Deadline::default())
            .unwrap(),
        reader
            .infer(&request("word 東京"), Deadline::default())
            .unwrap()
    );
    let runtime = answering_ort::Runtime::with_session(
        answering_ort::RuntimeConfig::default(),
        std::sync::Arc::new(reader),
    );
    assert!(
        runtime
            .execute(request("word 東京"), Deadline::default())
            .ok
    );
    let mut mismatch = request("word");
    if let Request::Read {
        expected_identity, ..
    } = &mut mismatch
    {
        expected_identity.artifact = "other".into();
    }
    assert!(!runtime.execute(mismatch, Deadline::default()).ok);
}

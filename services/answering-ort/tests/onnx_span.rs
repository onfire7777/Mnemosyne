#![cfg(feature = "onnx")]

use answering_ort::onnx_span::{OnnxSpanSession, TokenInputs};
use answering_ort::runtime::Deadline;
use std::time::Duration;

#[test]
fn invalid_tokens_fail_before_runtime_loading() {
    for inputs in [
        TokenInputs {
            input_ids: vec![],
            attention_mask: vec![],
            token_type_ids: None,
        },
        TokenInputs {
            input_ids: vec![1],
            attention_mask: vec![2],
            token_type_ids: None,
        },
        TokenInputs {
            input_ids: vec![-1],
            attention_mask: vec![1],
            token_type_ids: None,
        },
        TokenInputs {
            input_ids: vec![1; 513],
            attention_mask: vec![1; 513],
            token_type_ids: None,
        },
        TokenInputs {
            input_ids: vec![1],
            attention_mask: vec![1],
            token_type_ids: Some(vec![]),
        },
    ] {
        assert!(inputs.validate().is_err());
    }
}

#[test]
#[ignore = "requires pinned local ONNX Runtime and generated synthetic parity fixture"]
fn real_onnx_execution_matches_python_reference() {
    let root = std::path::PathBuf::from(
        std::env::var_os("MNEMOSYNE_ONNX_PARITY_FIXTURE").expect("fixture required"),
    );
    let fixture: serde_json::Value =
        serde_json::from_slice(&std::fs::read(root.join("fixture.json")).unwrap()).unwrap();
    let bytes = std::fs::read(root.join("span.onnx")).unwrap();
    let digest = fixture["model_sha256"].as_str().unwrap();
    assert!(OnnxSpanSession::from_bytes(&bytes, &"0".repeat(64), 2).is_err());
    let mut session = OnnxSpanSession::from_bytes(&bytes, digest, 2).unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let input: TokenInputs = serde_json::from_value(case["input"].clone()).unwrap();
        let output = session
            .run(&input, Deadline::after(Duration::from_secs(5)))
            .unwrap();
        let expected: answering_ort::onnx_span::SpanLogits =
            serde_json::from_value(case["output"].clone()).unwrap();
        assert_eq!(output, expected);
        assert_eq!(
            output
                .start_logits
                .iter()
                .map(|v| v.to_bits())
                .collect::<Vec<_>>(),
            expected
                .start_logits
                .iter()
                .map(|v| v.to_bits())
                .collect::<Vec<_>>()
        );
        assert_eq!(
            output
                .end_logits
                .iter()
                .map(|v| v.to_bits())
                .collect::<Vec<_>>(),
            expected
                .end_logits
                .iter()
                .map(|v| v.to_bits())
                .collect::<Vec<_>>()
        );
    }
    let mut representative: TokenInputs =
        serde_json::from_value(fixture["cases"][1]["input"].clone()).unwrap();
    for name in ["extra-output", "nonfinite", "short-output", "token-types"] {
        let raw = std::fs::read(root.join(format!("{name}.onnx"))).unwrap();
        let hash = fixture["variant_hashes"][name].as_str().unwrap();
        let loaded = OnnxSpanSession::from_bytes(&raw, hash, 2);
        if name == "extra-output" {
            assert!(loaded.is_err());
            continue;
        }
        let mut variant = loaded.unwrap();
        if name == "token-types" {
            assert!(variant.run(&representative, Deadline::default()).is_err());
            representative.token_type_ids = Some(vec![0; representative.input_ids.len()]);
            let output = variant.run(&representative, Deadline::default()).unwrap();
            let expected = serde_json::from_value(fixture["cases"][1]["output"].clone()).unwrap();
            assert_eq!(output, expected);
        } else {
            assert!(variant.run(&representative, Deadline::default()).is_err());
        }
    }
    let input = TokenInputs {
        input_ids: vec![1],
        attention_mask: vec![1],
        token_type_ids: None,
    };
    assert!(session
        .run(&input, Deadline::after(Duration::ZERO))
        .is_err());
}

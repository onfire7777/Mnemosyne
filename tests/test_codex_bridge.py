import json

import pytest

from eval import codex_bridge, codex_reader


def test_native_bridge_preserves_messages_schema_and_records_usage(monkeypatch, tmp_path):
    prompts = []

    def fake(prompt, **kwargs):
        prompts.append((prompt, kwargs))
        return {"answer": '{"facts":["The door is blue."]}', "usage": {"input_tokens": 9},
                "resolved_model": None}

    monkeypatch.setattr(codex_bridge, "process_with_codex", fake)
    response = codex_bridge.complete(
        [{"role": "system", "content": "Extract facts."}, {"role": "user", "content": "The door is blue."}],
        {"type": "object"}, scope="retain", requested_max_tokens=10,
        requested_temperature=0, receipt_dir=tmp_path,
    )
    assert json.loads(response["text"])["facts"] == ["The door is blue."]
    assert "Extract facts." in prompts[0][0] and '"type": "object"' in prompts[0][0]
    assert prompts[0][1]["model"] == "gpt-6-astra"
    receipt = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert receipt["requested_max_tokens"] == 10 and not receipt["generation_token_cap_enforced"]
    assert not receipt["temperature_enforced"] and receipt["cost_usd"] is None
    assert receipt["status"] == "completed" and receipt["usage"]["input_tokens"] == 9
    assert receipt["resolved_model"] is None


def test_failed_bridge_attempt_is_persisted_without_retry_or_exception_text(monkeypatch, tmp_path):
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise codex_reader.CodexReaderError("timeout", "private diagnostic")

    monkeypatch.setattr(codex_bridge, "process_with_codex", fail)
    with pytest.raises(codex_reader.CodexReaderError):
        codex_bridge.complete([{"role": "user", "content": "text"}], receipt_dir=tmp_path)
    receipt = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert len(calls) == 1 and receipt["status"] == "failed" and receipt["error_kind"] == "timeout"
    assert "private diagnostic" not in json.dumps(receipt)


@pytest.mark.parametrize("message", [
    {"role": "tool", "content": "data"}, {"role": "user", "content": []},
    {"role": "assistant", "content": "data", "tool_calls": []},
])
def test_bridge_rejects_tool_and_multimodal_messages_before_inference(message, tmp_path):
    with pytest.raises(ValueError):
        codex_bridge.complete([message], receipt_dir=tmp_path)
    assert not list(tmp_path.iterdir())


def test_native_processing_does_not_add_qa_abstention_rule(monkeypatch):
    seen = []

    def invoke(prompt, **kwargs):
        seen.append(kwargs["instruction"])
        return {"answer": "{}"}

    monkeypatch.setattr(codex_reader, "_invoke_with_codex", invoke)
    codex_reader.process_with_codex("Extract", model="gpt-6-astra")
    codex_reader.read_with_codex("Question", model="gpt-6-astra")
    assert "I do not know" not in seen[0]
    assert "I do not know" in seen[1]
    assert "Do not use tools" in seen[0]

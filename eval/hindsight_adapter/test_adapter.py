"""Contract tests; no model, network, or database calls."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pydantic import BaseModel, ValidationError

from eval.hindsight_adapter.codex_provider import CASE_RECEIPT_DIR, CodexCLIProvider
from eval.hindsight_adapter.runner import candidate_text, digest, frozen_input, native_usage, timestamp, validate_case


class Extracted(BaseModel):
    facts: list[str]


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = CodexCLIProvider(
            provider="openai", api_key="unused", base_url="", model="gpt-6-astra",
            reasoning_effort="low", receipt_dir=Path(self.temp.name),
        )

    async def test_native_schema_and_usage(self):
        response = {"text": '{"facts":["The launch is Friday."]}',
                    "usage": {"input_tokens": 100, "output_tokens": 20,
                              "cached_input_tokens": 50, "thoughts_tokens": 3}}
        messages = [{"role": "system", "content": "Extract facts."},
                    {"role": "user", "content": "The launch is Friday."}]
        with patch("eval.hindsight_adapter.codex_provider.complete", return_value=response) as bridge:
            result = await self.provider.call(messages, response_format=Extracted, max_completion_tokens=64)
        self.assertIsInstance(result.content, Extracted)
        self.assertEqual(result.content.facts, ["The launch is Friday."])
        self.assertEqual(result.usage.total_tokens, 120)
        self.assertEqual(result.usage.cached_tokens, 50)
        self.assertEqual(result.usage.thoughts_tokens, 3)
        self.assertEqual(bridge.call_args.args, (messages, Extracted.model_json_schema()))
        self.assertEqual(bridge.call_args.kwargs["requested_max_tokens"], 64)

    async def test_skip_validation_preserves_native_raw_json_contract(self):
        with patch("eval.hindsight_adapter.codex_provider.complete", return_value={"text": '{"other":1}'}):
            result = await self.provider.call([], response_format=Extracted, skip_validation=True)
        self.assertEqual(result.content, {"other": 1})

    async def test_invalid_schema_is_failure_not_empty_success(self):
        with patch("eval.hindsight_adapter.codex_provider.complete", return_value={"text": '{"other":1}'}) as bridge:
            with self.assertRaises(ValidationError):
                await self.provider.call([], response_format=Extracted)
        self.assertEqual(bridge.call_count, 1)

    async def test_invalid_json_receipt_is_marked_failed(self):
        response = {"text": "not JSON", "receipt": {"attempt_id": "example", "status": "completed"}}
        with patch("eval.hindsight_adapter.codex_provider.complete", return_value=response):
            with self.assertRaises(json.JSONDecodeError):
                await self.provider.call([], response_format=Extracted)
        saved = json.loads((Path(self.temp.name) / "example.json").read_text())
        self.assertEqual(saved["native_validation"]["status"], "failed")

    async def test_no_schema_preserves_text(self):
        with patch("eval.hindsight_adapter.codex_provider.complete", return_value={"text": "result"}):
            result = await self.provider.call([])
        self.assertEqual(result.content, "result")

    async def test_failure_has_no_hidden_retry(self):
        with patch("eval.hindsight_adapter.codex_provider.complete", side_effect=RuntimeError("offline")) as bridge:
            with self.assertRaises(RuntimeError):
                await self.provider.call([], max_retries=10)
        self.assertEqual(bridge.call_count, 1)

    async def test_opaque_cached_prefix_cannot_be_dropped(self):
        with patch("eval.hindsight_adapter.codex_provider.complete") as bridge:
            with self.assertRaises(ValueError):
                await self.provider.call([], cached_prefix="opaque")
        bridge.assert_not_called()
        self.assertFalse(self.provider.supports_prompt_caching())

    async def test_tool_calls_fail_explicitly(self):
        with self.assertRaises(RuntimeError):
            await self.provider.call_with_tools([], [])

    async def test_case_receipts_are_isolated(self):
        directory = Path(self.temp.name) / "one-case"
        token = CASE_RECEIPT_DIR.set(directory)
        try:
            with patch("eval.hindsight_adapter.codex_provider.complete", return_value={"text": "result"}) as bridge:
                await self.provider.call([])
            self.assertEqual(bridge.call_args.kwargs["receipt_dir"], directory)
        finally:
            CASE_RECEIPT_DIR.reset(token)


class InputTests(unittest.TestCase):
    def case(self):
        return {"question_id": "qid_abs", "question": "When?", "question_date": "2024/01/02 (Tue) 12:30",
                "sessions": [{"session_id": "one", "date": "2024/01/01 (Mon) 10:30",
                              "turns": [{"role": "user", "content": "Friday"}]}]}

    def test_official_naive_dates_are_utc(self):
        self.assertEqual(timestamp("2024/01/02 (Tue) 12:30").isoformat(), "2024-01-02T12:30:00+00:00")

    def test_gold_data_rejected(self):
        for key in ("answer", "has_answer", "question_type"):
            case = self.case()
            case[key] = "secret"
            with self.assertRaises(ValueError):
                validate_case(case)
        case = self.case()
        case["sessions"][0]["turns"][0]["has_answer"] = True
        with self.assertRaises(ValueError):
            validate_case(case)

    def test_valid_case(self):
        validate_case(self.case())

    def test_native_dates_preserved_for_reader(self):
        text = candidate_text(SimpleNamespace(text="Launch is next week.", occurred_start="2026-10-26",
                                             occurred_end=None, mentioned_at="2026-10-22"))
        self.assertEqual(text, "Occurred start: 2026-10-26\nMentioned at: 2026-10-22\nLaunch is next week.")

    def test_manifest_hash_excludes_own_hash_and_detects_input_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = [self.case()]
            config = {"hindsight_commit": "0691b504a88480844b2db53384b8c81971b7cf1e",
                      "input_sha256": digest(cases), "source_sha256": {}}
            manifest = {"source_config_sha256": digest(config), "question_ids": ["qid_abs"]}
            manifest["manifest_sha256"] = digest(manifest)
            for name, value in (("input.json", cases), ("configuration.json", config), ("manifest.json", manifest)):
                (root / name).write_text(json.dumps(value))
            args = SimpleNamespace(input=root / "input.json", manifest=root / "manifest.json")
            self.assertEqual(frozen_input(args), (manifest, cases))
            cases[0]["question"] = "Changed"
            args.input.write_text(json.dumps(cases))
            with self.assertRaisesRegex(ValueError, "after freezing"):
                frozen_input(args)

    def test_known_usage_survives_failed_or_interrupted_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one.json").write_text(json.dumps({"attempt_id": "one", "status": "completed",
                                                      "usage": {"input_tokens": 100, "output_tokens": 20}}))
            (root / "two.json").write_text(json.dumps({"attempt_id": "two", "status": "failed"}))
            result = native_usage(root)
            self.assertEqual(result["native_attempt_count"], 2)
            self.assertEqual(result["native_usage"], {"input_tokens": 100, "output_tokens": 20})
            self.assertTrue(result["native_usage_incomplete"])
            self.assertEqual(result["native_attempt_status_counts"], {"completed": 1, "failed": 1})
            self.assertTrue(native_usage(root / "missing", interrupted=True)["native_usage_incomplete"])


if __name__ == "__main__":
    unittest.main()

"""Synthetic native capture tests through the public subprocess boundary."""
from hashlib import sha256
import json
from pathlib import Path

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.adapters.locomo import LoCoMoError, split_samples
from eval.public.adapters.locomo_native import answer_captured_question, captured_conversations, project_native_response


def sample(identity):
    return {"sample_id": identity, "conversation": {
        "session_1_date_time": "Synthetic date", "session_1": [
            {"dia_id": "D1:1", "speaker": "A", "text": "violet synthetic kite"},
            {"dia_id": "D1:2", "speaker": "A", "text": "violet synthetic kite"}]},
        "qa": [{"question": "what?", "answer": "SECRET_LABEL", "category": 4, "evidence": ["D1:1"]}]}


def test_native_public_capture_is_isolated_verified_and_label_free(tmp_path):
    parent_store = tmp_path / "untouched.json"
    cli = MnemoCLI(store=str(parent_store), timeout_s=30)
    with captured_conversations([sample("one"), sample("two")], cli,
                                caption_policy="exclude-caption") as conversations:
        stores = [Path(row["cli"].store) for row in conversations]
        assert len(set(stores)) == 2 and all(path.exists() for path in stores)
        first, second = conversations
        assert first["tenant_id"] != second["tenant_id"]
        assert set(first["evidence"]).isdisjoint(second["evidence"])
        for row in conversations:
            assert len(row["evidence"]) == 2
            assert "SECRET_LABEL" not in json.dumps(row["evidence"])
            assert row["explicit_lifecycle_operations"] == []
            result = row["cli"].search(row["tenant_id"], "violet")
            assert {hit["id"] for hit in result["hits"]} == set(row["evidence"])
        foreign = first["cli"].search(second["tenant_id"], "violet")
        assert foreign["hits"] == []
    assert not parent_store.exists()
    assert all(not path.exists() for path in stores)


@pytest.mark.parametrize("result", [{"results": []}, {"results": [{"cid": "wrong"}, {"cid": "wrong"}]}])
def test_native_capture_rejects_invalid_receipts_before_yield(monkeypatch, result, tmp_path):
    monkeypatch.setattr(MnemoCLI, "capture_batch", lambda *args: result)
    with pytest.raises(LoCoMoError, match="capture"):
        with captured_conversations([sample("one")], MnemoCLI(store=str(tmp_path / "unused")),
                                    caption_policy="exclude-caption"):
            pytest.fail("invalid receipt must not reach caller")


def response(answer="violet", abstained=False, reader=None):
    return {"answer": answer, "abstained": abstained,
            "claims": [] if abstained or not answer else [{"text": answer, "evidence_cids": ["cid"],
                "derivation": {"schema_version": "mnemosyne.claim-derivation/v1", "kind": "quotation", "operation": None},
                "spans": [{"cid": "cid", "start": 0, "end": len(answer),
                           "slice_sha256": sha256(answer.encode()).hexdigest()}]}],
            "reader": {"grounded_reader": {"provider": "synthetic"}} if reader is None else reader,
            "hops": [{"retrieved_cids": ["cid", "cid"]}]}


def test_native_timeout_cannot_become_correct_abstention():
    raw = response(None, True, {})
    result = project_native_response(raw, sample("one")["qa"][0], {"cid": {"dialog_id": "D1:1", "capture": {"content": "violet"}}})
    assert result["status"] == "incomplete-reader-execution"
    assert result["decoded_prediction"] is None
    assert result["raw_response"] == raw
    assert result["retrieved_dialog_ids"] == ["D1:1"]


def test_native_explicit_abstention_conversion_is_disclosed_and_raw_retained():
    raw = response(None, True)
    result = project_native_response(raw, sample("one")["qa"][0], {"cid": {"dialog_id": "D1:1", "capture": {"content": "violet"}}})
    assert result["decoded_prediction"] == "No information available"
    assert result["projection_policy"] == "native-explicit-abstention-v1"
    assert not result["runtime_custody_verified"]
    raw["reader"].clear()
    assert result["raw_response"]["reader"]


def test_native_category5_uses_recorded_option_mapping():
    annotation = {"question": "Synthetic?", "answer": "distractor", "category": 5}
    result = project_native_response(response("(b)"), annotation, {"cid": {"dialog_id": "D1:1", "capture": {"content": "(b)"}}},
                                     choice_draw=0.75)
    assert result["decoded_prediction"] == "Not mentioned in the conversation"
    assert result["raw_response"]["answer"] == "(b)"


@pytest.mark.parametrize("raw", [response("contradiction", True), response("", False),
                                  {**response(), "abstained": 1},
                                  {**response(), "hops": [{"retrieved_cids": ["foreign"]}]}])
def test_native_projection_rejects_ambiguous_answers_and_foreign_evidence(raw):
    with pytest.raises(LoCoMoError):
        project_native_response(raw, sample("one")["qa"][0], {"cid": {"dialog_id": "D1:1", "capture": {"content": "violet"}}})


def test_native_question_uses_read_only_public_boundary_and_retains_request(tmp_path, monkeypatch):
    source = sample("one")
    source["qa"][0]["question"] = "café what?"
    question = split_samples([source])["questions"][0]
    observed = []
    wire_bytes = []

    def answer(cli, path, *, include_derivation=False):
        assert include_derivation is True
        assert "--evaluation-read-only" in cli.global_flags
        request = json.loads(Path(path).read_text())
        assert request["question"] == "café what?"
        actual = Path(path).read_bytes()
        assert actual == (json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        wire_bytes.append(actual)
        assert "SECRET_LABEL" not in Path(path).read_text()
        observed.append(Path(path))
        return {"results": [{**response(), "question_id": request["question_id"]}]}

    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", answer)
    store = tmp_path / "synthetic-store"
    store.write_text("synthetic transport test only")
    conversation = {"sample_id": "one", "tenant_id": "tenant-one", "cli": MnemoCLI(store=str(store)),
                    "evidence": {"cid": {"dialog_id": "D1:1", "capture": {"content": "violet"}}}}
    result = answer_captured_question(conversation, question, source["qa"][0])
    assert result["decoded_prediction"] == "violet"
    assert result["request"]["context"]["tenant_id"] == "tenant-one"
    assert result["raw_batch_response"]["results"][0]["answer"] == "violet"
    assert json.loads(result["request_jsonl"]) == result["request"]
    assert result["request_jsonl"].encode("utf-8") == wire_bytes[0]
    assert result["request_sha256"] == sha256(wire_bytes[0]).hexdigest()
    assert not observed[0].exists()
    def omit_derivation(cli, path, *, include_derivation=False):
        payload = answer(cli, path, include_derivation=include_derivation)
        payload["results"][0]["claims"][0].pop("derivation")
        return payload
    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", omit_derivation)
    with pytest.raises(LoCoMoError, match="omitted requested"):
        answer_captured_question(conversation, question, source["qa"][0])


@pytest.mark.parametrize("payload", [{}, {"results": []}, {"results": [{"question_id": "foreign"}]}])
def test_native_question_rejects_wrong_response_identity(tmp_path, monkeypatch, payload):
    source = sample("one")
    store = tmp_path / "store"
    store.write_text("synthetic transport test only")
    conversation = {"sample_id": "one", "tenant_id": "tenant", "cli": MnemoCLI(store=str(store)), "evidence": {}}
    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", lambda *args, **kwargs: payload)
    with pytest.raises(LoCoMoError, match="result"):
        answer_captured_question(conversation, split_samples([source])["questions"][0], source["qa"][0])


def test_native_question_does_not_swallow_execution_errors(tmp_path, monkeypatch):
    source = sample("one")
    store = tmp_path / "store"
    store.write_text("synthetic transport test only")
    conversation = {"sample_id": "one", "tenant_id": "tenant", "cli": MnemoCLI(store=str(store)), "evidence": {}}

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", fail)
    with pytest.raises(RuntimeError, match="provider failure"):
        answer_captured_question(conversation, split_samples([source])["questions"][0], source["qa"][0])
    foreign = split_samples([sample("two")])["questions"][0]
    with pytest.raises(LoCoMoError, match="conversation"):
        answer_captured_question(conversation, foreign, source["qa"][0])


def test_native_claim_span_is_checked_against_captured_bytes():
    from hashlib import sha256
    raw = response()
    raw["claims"] = [{"text": "violet", "evidence_cids": ["cid"], "spans": [
        {"cid": "cid", "start": 0, "end": 6, "slice_sha256": sha256(b"violet").hexdigest()}]}]
    evidence = {"cid": {"dialog_id": "D1:1", "capture": {"content": "violet kite"}}}
    assert project_native_response(raw, sample("one")["qa"][0], evidence)["status"] == "projected"
    raw["claims"][0]["spans"][0]["slice_sha256"] = "0" * 64
    with pytest.raises(LoCoMoError, match="captured content"):
        project_native_response(raw, sample("one")["qa"][0], evidence)


@pytest.mark.parametrize("claim", [
    {"text": "x", "evidence_cids": ["foreign"], "spans": []},
    {"text": "x", "evidence_cids": ["cid"], "spans": [{"cid": "foreign"}]},
    {"text": "x", "evidence_cids": "cid", "spans": []},
])
def test_native_claim_cannot_introduce_foreign_or_malformed_evidence(claim):
    raw = response()
    raw["claims"] = [claim]
    with pytest.raises(LoCoMoError):
        project_native_response(raw, sample("one")["qa"][0], {"cid": {"dialog_id": "D1:1", "capture": {"content": "violet"}}})


def test_native_claim_must_cite_an_observed_retrieval():
    raw = response()
    raw["hops"] = []
    with pytest.raises(LoCoMoError, match="retrieval trace"):
        project_native_response(raw, sample("one")["qa"][0], {"cid": {"dialog_id": "D1:1", "capture": {"content": "violet"}}})


def test_native_replay_rebuilds_capture_request_and_projection(tmp_path, monkeypatch):
    from copy import deepcopy
    from eval.public.adapters.locomo_native import verify_native_answer_record
    source = sample("one")
    with captured_conversations([source], MnemoCLI(store=str(tmp_path / "unused")),
                                caption_policy="exclude-caption") as conversations:
        conversation = conversations[0]
        cid = next(iter(conversation["evidence"]))

        def answer(cli, path, *, include_derivation=False):
            request = json.loads(Path(path).read_text())
            raw = response()
            raw["hops"] = [{"retrieved_cids": [cid]}]
            claim = raw["claims"][0]
            claim["evidence_cids"] = [cid]
            start = conversation["evidence"][cid]["capture"]["content"].index("violet")
            claim["spans"][0].update(cid=cid, start=start, end=start + 6)
            return {"results": [{**raw, "question_id": request["question_id"]}]}

        monkeypatch.setattr(MnemoCLI, "eval_answer_batch", answer)
        record = answer_captured_question(conversation, split_samples([source])["questions"][0], source["qa"][0])
    # Replay still works after the original temporary store has been removed.
    assert verify_native_answer_record(source, 0, record, caption_policy="exclude-caption") == record
    for field, value in [("decoded_prediction", "changed"), ("request_sha256", "0" * 64),
                         ("runtime_custody_verified", True), ("extra_field", "unrecognized")]:
        damaged = deepcopy(record)
        damaged[field] = value
        with pytest.raises(LoCoMoError, match="mismatch"):
            verify_native_answer_record(source, 0, damaged, caption_policy="exclude-caption")
    damaged_source = deepcopy(source)
    damaged_source["conversation"]["session_1"][0]["text"] = "changed source"
    with pytest.raises(LoCoMoError, match="evidence"):
        verify_native_answer_record(damaged_source, 0, record, caption_policy="exclude-caption")
    unobserved_source = deepcopy(source)
    unobserved_source["conversation"]["session_1"][1]["text"] = "changed unreturned evidence"
    with pytest.raises(LoCoMoError, match="mismatch"):
        verify_native_answer_record(unobserved_source, 0, record, caption_policy="exclude-caption")


def test_native_sequence_preserves_full_population_and_stops_without_retry(tmp_path, monkeypatch):
    from eval.public.adapters.locomo_native import iter_native_answers
    source = [sample("one"), sample("two")]
    source[0]["qa"].append({"question": "Synthetic?", "category": 5, "answer": "distractor", "evidence": []})
    questions = split_samples(source)["questions"]
    draws = {questions[1]["question_id"]: 0.1}
    calls = []
    stores = []
    should_fail = True

    def answer(cli, path, *, include_derivation=False):
        request = json.loads(Path(path).read_text())
        assert all(not store.exists() for store in stores if store != Path(cli.store))
        calls.append(request["question_id"])
        stores.append(Path(cli.store))
        if should_fail and len(calls) == 2:
            assert "(a) Not mentioned in the conversation" in request["question"]
            raise RuntimeError("synthetic failure after one retained record")
        return {"results": [{"question_id": request["question_id"], "answer": None,
                             "abstained": True, "claims": [], "hops": [], "reader": {}}]}

    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", answer)
    iterator = iter_native_answers(source, MnemoCLI(store=str(tmp_path / "untouched")),
                                   caption_policy="exclude-caption", choice_draws=draws)
    first = next(iterator)
    assert first["question_id"] == questions[0]["question_id"]
    assert first["status"] == "incomplete-reader-execution"
    draws[questions[1]["question_id"]] = 0.9  # Cannot mutate an already-started sequence's choices.
    with pytest.raises(RuntimeError, match="retained record"):
        next(iterator)
    assert calls == [row["question_id"] for row in questions[:2]]
    assert all(not store.exists() for store in stores)
    should_fail = False
    calls.clear()
    stores.clear()
    from copy import deepcopy
    from eval.public.adapters.locomo_native import verify_native_answer_record
    original_second = deepcopy(source[1])
    successful = iter_native_answers(source, MnemoCLI(store=str(tmp_path / "untouched")),
                                     caption_policy="exclude-caption", choice_draws=draws)
    records = [next(successful)]
    source[1]["conversation"]["session_1"][0]["text"] = "changed after startup"
    source[1]["qa"][0]["question"] = "changed question"
    records.extend(successful)
    verify_native_answer_record(original_second, 0, records[-1], caption_policy="exclude-caption")
    source[1] = original_second
    assert [row["question_id"] for row in records] == [row["question_id"] for row in questions]
    assert calls == [row["question_id"] for row in questions]
    assert all(not store.exists() for store in stores)
    calls.clear()
    stores.clear()
    interrupted = iter_native_answers(source, MnemoCLI(store=str(tmp_path / "untouched")),
                                      caption_policy="exclude-caption", choice_draws=draws)
    next(interrupted)
    assert stores and all(store.exists() for store in stores)
    interrupted.close()
    assert len(calls) == 1
    assert all(not store.exists() for store in stores)


@pytest.mark.parametrize("fault", ["missing-draw", "long-query"])
def test_native_sequence_prevalidates_before_any_capture(tmp_path, monkeypatch, fault):
    from eval.public.adapters.locomo_native import iter_native_answers
    source = [sample("one")]
    if fault == "missing-draw":
        source[0]["qa"][0]["category"] = 5
    else:
        source[0]["qa"][0]["question"] = "x" * 2001

    def forbidden(*args):
        raise AssertionError("invalid population must fail before capture")

    monkeypatch.setattr(MnemoCLI, "capture_batch", forbidden)
    with pytest.raises(LoCoMoError):
        list(iter_native_answers(source, MnemoCLI(store=str(tmp_path / "unused")),
                                 caption_policy="exclude-caption", choice_draws={}))


@pytest.mark.parametrize("fault", ["missing-claims", "answer-drift", "duplicate-citations",
                                  "overlap", "unused-citation", "too-many-claims", "empty-text"])
def test_native_claim_rendering_and_citation_structure(fault):
    raw = response()
    evidence = {cid: {"dialog_id": "D1:1", "capture": {"content": "violet"}}
                for cid in ("cid", "unused")}
    if fault == "missing-claims":
        raw["claims"] = []
    elif fault == "answer-drift":
        raw["answer"] = "invented answer"
    elif fault == "duplicate-citations":
        raw["claims"][0]["evidence_cids"].append("cid")
    elif fault == "overlap":
        raw["claims"][0]["spans"] *= 2
    elif fault == "unused-citation":
        raw["claims"][0]["evidence_cids"].append("unused")
    elif fault == "too-many-claims":
        raw["claims"] *= 21
    else:
        raw["claims"][0]["text"] = ""
    with pytest.raises(LoCoMoError):
        project_native_response(raw, sample("one")["qa"][0], evidence)


def test_native_synthesis_text_is_preserved_without_claiming_derivation_replay():
    raw = response()
    evidence = {"cid": {"dialog_id": "D1:1", "capture": {"content": "violet"}}}
    quoted = project_native_response(raw, sample("one")["qa"][0], evidence)
    assert quoted["claim_text_custody"] == ["exact-quoted-spans"]
    raw["claims"][0].pop("derivation")
    raw["claims"][0]["text"] = raw["answer"] = "A derived synthetic answer"
    derived = project_native_response(raw, sample("one")["qa"][0], evidence)
    assert derived["status"] == "projected"
    assert derived["decoded_prediction"] == "A derived synthetic answer"
    assert derived["claim_text_custody"] == ["derived-text-unverified"]
    assert not derived["runtime_custody_verified"]


def test_seeded_native_execution_preserves_option_policy(tmp_path, monkeypatch):
    from eval.public.adapters.locomo_native import iter_native_answers
    from eval.public.adapters.locomo import native_choice_policy
    source = sample("seeded")
    source["qa"] = [{"question": f"Synthetic {i}?", "answer": "distractor", "category": 5,
                     "evidence": []} for i in range(2)]
    seen = []

    def answer(cli, path, *, include_derivation=False):
        request = json.loads(Path(path).read_text())
        seen.append(request["question"])
        return {"results": [{"question_id": request["question_id"], "answer": None,
            "abstained": True, "claims": [], "hops": [], "reader": {}}]}

    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", answer)
    from eval.public.adapters.locomo_config import build_native_run_config, validate_native_run_config
    from eval.public.reader_policy import candidate_reader_policy
    from eval.public.runner import build_candidate_manifest
    from mnemosyne.providers.grounded_protocol import MODEL_CONTENT_SHA256
    cli = MnemoCLI(store=str(tmp_path / "unused"))
    policy = candidate_reader_policy(build_candidate_manifest(
        model_content_sha256=MODEL_CONTENT_SHA256, git_sha="a" * 40,
        created_at_utc="2026-10-04T00:00:00Z"))
    config = build_native_run_config([source], cli, caption_policy="exclude-caption", choice_seed=1,
                    reader_policy=policy, runtime_manifest_sha256="1" * 64, resource_manifest_sha256="2" * 64)
    records = list(iter_native_answers([source], cli, caption_policy="exclude-caption", choice_seed=1,
                                       reader_policy=policy, run_config=config))
    assert all(r["run_config_sha256"] == validate_native_run_config(config) for r in records)
    draws = native_choice_policy([source], choice_seed=1)["draws"]
    assert [r["question_transformation"]["choice_draw"] for r in records] == list(draws.values())
    assert "(a) Not mentioned in the conversation" in seen[0]
    assert "(b) Not mentioned in the conversation" in seen[1]
    assert all(r["status"] == "incomplete-reader-execution" for r in records)


@pytest.mark.parametrize("flags", [["--store", "another-store.json"], ["--store=another-store.json"],
                                    ["--backend", "postgres"], ["--backend=sqlite"]])
def test_native_cli_rejects_storage_override_before_invocation(tmp_path, monkeypatch, flags):
    store = tmp_path / "original-store.json"
    store.write_bytes(b"untouched synthetic store")
    cli = MnemoCLI(store=str(store), global_flags=flags)

    def forbidden(*args, **kwargs):
        pytest.fail("a storage override must fail before invoking the CLI")

    monkeypatch.setattr(MnemoCLI, "capture_batch", forbidden)
    monkeypatch.setattr(MnemoCLI, "eval_answer_batch", forbidden)
    source = sample("override")
    with pytest.raises(LoCoMoError, match="override isolated storage"):
        with captured_conversations([source], cli, caption_policy="exclude-caption"):
            pytest.fail("unsafe CLI reached capture context")
    conversation = {"sample_id": "override", "tenant_id": "synthetic", "cli": cli, "evidence": {}}
    with pytest.raises(LoCoMoError, match="override isolated storage"):
        answer_captured_question(conversation, split_samples([source])["questions"][0], source["qa"][0])
    assert store.read_bytes() == b"untouched synthetic store"

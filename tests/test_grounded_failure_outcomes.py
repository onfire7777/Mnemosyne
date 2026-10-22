"""Operational failures are retryable internally, without changing public answers."""

from dataclasses import replace

import pytest

from mnemosyne.answering import (
    AnswerLimits,
    AnswerReadContext,
    AnswerRequest,
    GroundedAnswerOrchestrator,
    public_grounded_answer,
)
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.providers.extractive_decomposer import ExtractiveQueryDecomposer


CONTEXT = AnswerReadContext(tenant_id="t", user_id="u", role="agent", max_sensitivity=0)
REQUEST = AnswerRequest(question="When does Project Zephyr launch?", context=CONTEXT)


@pytest.fixture
def engine():
    value = LocalMemoryEngine()
    yield value
    value.close()


def source(engine, **kwargs):
    return engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="chat",
        content="Project Zephyr launches Friday.", **kwargs,
    ))


class Reader:
    def __init__(self, callback=None, response=None):
        self.callback = callback
        self.response = response
        self.calls = 0

    def read(self, payload):
        self.calls += 1
        if self.callback:
            self.callback()
        if isinstance(self.response, BaseException):
            raise self.response
        if self.response is not None:
            return self.response
        return {"claims": [{"spans": [{"cid": payload["evidence"][0]["cid"], "quote": "Friday"}]}],
                "unresolved": False}


def orchestrator(engine, decomposer=None):
    return GroundedAnswerOrchestrator(engine, decomposer or ExtractiveQueryDecomposer())


def assert_internal_failure(result, expected):
    assert result.abstained and not result.answer and not result.claims
    assert result.failure_kind == expected
    public = public_grounded_answer(result, {}, include_derivation=True)
    assert public == public_grounded_answer(replace(result, failure_kind=None), {}, include_derivation=True)
    assert "failure_kind" not in public
    assert "sensitive diagnostic" not in repr(result)


def test_success_and_old_constructor_have_no_failure(engine):
    source(engine)
    result = orchestrator(engine).answer(REQUEST, Reader())
    assert result.answer == "Friday" and result.failure_kind is None
    assert type(result)(result.answer, result.claims, result.evidence, result.episodes,
                        result.trace, result.abstained, result.public_reason).failure_kind is None


@pytest.mark.parametrize("private_source", [False, True])
def test_no_authorized_evidence_is_cacheable_not_operational_failure(engine, private_source):
    if private_source:
        source(engine, sensitivity=3)
    reader = Reader()
    result = orchestrator(engine).answer(REQUEST, reader)
    assert result.abstained and result.failure_kind is None
    assert reader.calls == 0


def test_explicit_unresolved_answer_remains_cacheable(engine):
    source(engine)
    result = orchestrator(engine).answer(REQUEST, Reader(response={"claims": [], "unresolved": True}))
    assert result.abstained and result.failure_kind is None
    assert result.evidence


@pytest.mark.parametrize("phase", ["decomposer", "storage"])
def test_initial_assembly_exception_has_safe_internal_kind(engine, monkeypatch, phase):
    source(engine)

    def fail(*args, **kwargs):
        raise RuntimeError("sensitive diagnostic")

    decomposer = ExtractiveQueryDecomposer()
    if phase == "decomposer":
        class FailingDecomposer:
            decompose = fail
        decomposer = FailingDecomposer()
    else:
        monkeypatch.setattr(engine, "retrieve", fail)
    assert_internal_failure(orchestrator(engine, decomposer).answer(REQUEST, Reader()), "assembly_error")


def test_reader_exception_is_retryable(engine):
    source(engine)
    assert_internal_failure(orchestrator(engine).answer(
        REQUEST, Reader(response=RuntimeError("sensitive diagnostic"))), "reader_error")


@pytest.mark.parametrize("proposal", [
    {},
    {"claims": [], "unresolved": False},
    {"claims": [{"spans": [{"cid": "invented", "quote": "Friday"}]}], "unresolved": False},
])
def test_invalid_reader_output_is_not_legitimate_abstention(engine, proposal):
    source(engine)
    result = orchestrator(engine).answer(REQUEST, Reader(response=proposal))
    assert_internal_failure(result, "invalid_reader_proposal")
    assert result.evidence  # Preserve the existing safe replayed-evidence response.


@pytest.mark.parametrize("phase", ["assembly", "after_reader"])
@pytest.mark.parametrize("failure", ["drift", "exception"])
def test_replay_failure_is_distinct_from_no_evidence(engine, monkeypatch, phase, failure):
    cid = source(engine)
    original = engine.retrieve
    calls = 0

    def replay_retrieve(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if failure == "exception":
                raise RuntimeError("sensitive diagnostic")
            engine.forget("t", cid)
        return original(*args, **kwargs)

    def after_reader():
        if failure == "drift":
            engine.forget("t", cid)
        else:
            def fail(*args, **kwargs):
                raise RuntimeError("sensitive diagnostic")
            monkeypatch.setattr(engine, "retrieve", fail)

    if phase == "assembly":
        monkeypatch.setattr(engine, "retrieve", replay_retrieve)
    class OneQuery:
        def decompose(self, payload):
            return {"queries": ["Zephyr"]}

    runner = GroundedAnswerOrchestrator(engine, OneQuery(), limits=AnswerLimits(max_hops=1))
    result = runner.answer(REQUEST, Reader(callback=after_reader if phase == "after_reader" else None))
    assert_internal_failure(result, "replay_drift" if failure == "drift" else "replay_error")
    assert not result.evidence


def test_process_control_exception_still_propagates(engine):
    source(engine)
    with pytest.raises(KeyboardInterrupt):
        orchestrator(engine).answer(REQUEST, Reader(response=KeyboardInterrupt()))

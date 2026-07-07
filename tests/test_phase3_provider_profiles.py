from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROLE_LLM = REPO_ROOT / "infra" / "providers" / "role-llm.py"
ROLE_LADDER = REPO_ROOT / "infra" / "providers" / "role-ladder.py"
SELF_HOSTED_PROFILE = REPO_ROOT / "infra" / "profiles" / "self-hosted.env"
ROLE_PREFIXES = {
    "candidate_extractor": "MNEMOSYNE_CANDIDATE_EXTRACTOR",
    "evidence_summarizer": "MNEMOSYNE_SUMMARIZER",
    "entity_resolver": "MNEMOSYNE_ENTITY_RESOLVER",
    "lesson_distiller": "MNEMOSYNE_LESSON_DISTILLER",
    "skill_inducer": "MNEMOSYNE_SKILL_INDUCER",
}


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().split("  #", 1)[0].strip()
    return values


def _load_role_llm():
    spec = importlib.util.spec_from_file_location("mnemosyne_role_llm", ROLE_LLM)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_role_ladder():
    spec = importlib.util.spec_from_file_location("mnemosyne_role_ladder", ROLE_LADDER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_self_hosted_profile_activates_all_role_llm_command_providers() -> None:
    profile = _parse_env(SELF_HOSTED_PROFILE)

    assert profile["MNEMOSYNE_PROPOSAL_PROVIDER_CLASS"] == "local"
    assert profile["MNEMOSYNE_PROPOSAL_PROVIDER_RETENTION"] == "zero_retention"
    assert profile["MNEMOSYNE_PROPOSAL_PROVIDER_REGION"] == "local"
    assert profile["MNEMOSYNE_ROLE_LADDER_LOCAL_COMMAND"] == "/opt/mnemosyne/bin/role-llm"
    assert profile["MNEMOSYNE_ROLE_LADDER_FRONTIER_ROLES"] == "entity_resolver,lesson_distiller,skill_inducer"
    assert profile["MNEMOSYNE_ROLE_LADDER_ALLOW_DETERMINISTIC"] == "0"
    for prefix in ROLE_PREFIXES.values():
        assert profile[f"{prefix}_PROVIDER"] == "command"
        assert profile[f"{prefix}_COMMAND"] == "/opt/mnemosyne/bin/role-ladder"


def test_role_llm_dispatch_table_covers_all_proposal_roles(monkeypatch) -> None:
    role_llm = _load_role_llm()

    def fake_chat(_system: str, _user: str, required_key: str) -> dict:
        if required_key == "summary":
            return {"summary": "bounded summary"}
        if required_key == "candidates":
            return {
                "candidates": [
                    {
                        "subject": "Provider Health",
                        "predicate": "is",
                        "object": "configured",
                        "confidence": 0.91,
                    }
                ]
            }
        if required_key == "lessons":
            return {
                "lessons": [
                    {"content": "lesson", "failure_signature": "provider-health"}
                ]
            }
        if required_key == "procedures":
            return {
                "procedures": [
                    {"name": "provider procedure", "body": "check provider health"}
                ]
            }
        if required_key == "mapping":
            return {"mapping": {"provider-health": "Provider Health"}}
        raise AssertionError(f"unexpected required key {required_key}")

    monkeypatch.setattr(role_llm, "_chat", fake_chat)
    candidate = {
        "signature": "provider-health",
        "candidate_subject": "Provider Health",
        "candidate_predicate": "is",
        "candidate_object": "configured",
    }
    requests = {
        "candidate_extractor": {
            "payload": {},
            "evidence": [{"content": "Provider Health is configured."}],
        },
        "evidence_summarizer": {
            "evidence": [{"content": "Provider Health is configured."}]
        },
        "entity_resolver": {"candidates": [candidate]},
        "lesson_distiller": {"candidates": [candidate]},
        "skill_inducer": {"candidates": [candidate]},
    }
    expected_keys = {
        "candidate_extractor": "candidates",
        "evidence_summarizer": "summary",
        "entity_resolver": "candidates",
        "lesson_distiller": "lessons",
        "skill_inducer": "procedures",
    }

    for role, request in requests.items():
        request["prompt_boundary"] = {"role": role}
        response = role_llm.ROLES[role](request)
        assert expected_keys[role] in response
    assert role_llm.ROLES["procedure_inducer"] is role_llm.ROLES["skill_inducer"]


def test_role_llm_evidence_lines_tolerates_null_cid() -> None:
    # The provider disclosure evidence view carries an explicit ``cid: None`` for
    # unpersisted evidence (e.g. the provider-check health probe). ``dict.get``
    # returns that None rather than the default, so slicing the cid must not
    # crash the evidence-line renderer.
    role_llm = _load_role_llm()
    rendered = role_llm._evidence_lines(
        [{"cid": None, "content": "Provider Health is configured."}]
    )
    assert "Provider Health is configured." in rendered


def test_role_ladder_orders_frontier_only_for_eligible_roles(monkeypatch) -> None:
    role_ladder = _load_role_ladder()
    calls: list[str] = []

    def fake_command_for(_role: str, rung: str) -> list[str]:
        return [rung]

    def fake_run_command(_argv, _request, *, rung: str, timeout_seconds: float):
        calls.append(rung)
        key = "summary" if _request["prompt_boundary"]["role"] == "evidence_summarizer" else "lessons"
        value = "local summary" if key == "summary" else [{"content": "frontier lesson", "failure_signature": "f"}]
        return {key: value}, {"rung": rung, "status": "ok", "timeout_seconds": timeout_seconds, "duration_ms": 0.0}

    monkeypatch.setenv("MNEMOSYNE_ROLE_LADDER_FRONTIER_ROLES", "entity_resolver,lesson_distiller,skill_inducer")
    monkeypatch.setattr(role_ladder, "_command_for", fake_command_for)
    monkeypatch.setattr(role_ladder, "_run_command", fake_run_command)

    summary = role_ladder.handle({"prompt_boundary": {"role": "evidence_summarizer"}, "evidence": [{"content": "x"}]})
    lesson = role_ladder.handle({"prompt_boundary": {"role": "lesson_distiller"}, "candidates": []})

    assert summary["metadata"]["provider_ladder"]["selected"] == "local"
    assert lesson["metadata"]["provider_ladder"]["selected"] == "frontier"
    assert calls == ["local", "frontier"]


def test_role_ladder_fails_closed_unless_deterministic_fallback_is_enabled(monkeypatch) -> None:
    role_ladder = _load_role_ladder()
    monkeypatch.delenv("MNEMOSYNE_ROLE_LADDER_ALLOW_DETERMINISTIC", raising=False)
    monkeypatch.setattr(role_ladder, "_command_for", lambda _role, _rung: None)

    try:
        role_ladder.handle({"prompt_boundary": {"role": "evidence_summarizer"}, "evidence": [{"content": "Fallback summary."}]})
    except RuntimeError as exc:
        assert "failed closed" in str(exc)
    else:
        raise AssertionError("ladder must fail closed when no rung succeeds")

    monkeypatch.setenv("MNEMOSYNE_ROLE_LADDER_ALLOW_DETERMINISTIC", "1")
    response = role_ladder.handle(
        {"prompt_boundary": {"role": "evidence_summarizer"}, "evidence": [{"content": "Fallback summary. Extra."}]}
    )

    assert response["summary"] == "Fallback summary."
    assert response["metadata"]["provider_ladder"]["selected"] == "deterministic"
    assert response["metadata"]["provider_ladder"]["deterministic_fallback_enabled"] is True


def test_role_ladder_timeout_budget_caps_later_rungs(monkeypatch) -> None:
    role_ladder = _load_role_ladder()
    time_values = iter([100.0, 100.0, 100.75])
    seen_timeouts: list[float] = []

    monkeypatch.setenv("MNEMOSYNE_ROLE_LADDER_TIMEOUT", "1.0")
    monkeypatch.setenv("MNEMOSYNE_ROLE_LADDER_FRONTIER_TIMEOUT", "0.8")
    monkeypatch.setenv("MNEMOSYNE_ROLE_LADDER_LOCAL_TIMEOUT", "0.8")
    monkeypatch.setenv("MNEMOSYNE_ROLE_LADDER_ALLOW_DETERMINISTIC", "1")
    monkeypatch.setenv("MNEMOSYNE_ROLE_LADDER_FRONTIER_ROLES", "lesson_distiller")
    monkeypatch.setattr(role_ladder.time, "monotonic", lambda: next(time_values))
    monkeypatch.setattr(role_ladder, "_command_for", lambda _role, rung: [rung])

    def fake_run_command(_argv, _request, *, rung: str, timeout_seconds: float):
        seen_timeouts.append(round(timeout_seconds, 3))
        return None, {"rung": rung, "status": "failed", "timeout_seconds": timeout_seconds, "duration_ms": 0.0}

    monkeypatch.setattr(role_ladder, "_run_command", fake_run_command)

    response = role_ladder.handle({"prompt_boundary": {"role": "lesson_distiller"}, "candidates": []})

    assert response["metadata"]["provider_ladder"]["selected"] == "deterministic"
    assert seen_timeouts == [0.8, 0.25]

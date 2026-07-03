from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROLE_LLM = REPO_ROOT / "infra" / "providers" / "role-llm.py"
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


def test_self_hosted_profile_activates_all_role_llm_command_providers() -> None:
    profile = _parse_env(SELF_HOSTED_PROFILE)

    for prefix in ROLE_PREFIXES.values():
        assert profile[f"{prefix}_PROVIDER"] == "command"
        assert profile[f"{prefix}_COMMAND"] == "/opt/mnemosyne/bin/role-llm"


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

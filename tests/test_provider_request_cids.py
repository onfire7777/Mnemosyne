from __future__ import annotations

import json
import sys
from hashlib import sha256

import pytest

from mnemosyne.consolidation import (
    CommandCandidateExtractor,
    ProviderProposalLedger,
    _provider_payload_view,
)
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.mark.parametrize("sequence_type", [list, tuple])
def test_only_structural_payload_source_cids_bypass_secret_redaction(sequence_type):
    cid = sha256(b"evidence").hexdigest()
    other_secret = "abcdef0123456789" * 2
    payload = {
        "source_evidence_cids": sequence_type([cid, "sk-thisisnotacontentid", other_secret]),
        "arbitrary_cids": [cid], "request_id": cid,
        "nested": {"source_evidence_cids": [cid]},
        "metadata": {"provider_context": {"request_id": cid}},
    }
    safe = _provider_payload_view(payload)
    assert safe["source_evidence_cids"] == [cid, "[secret-omitted]", "[secret-omitted]"]
    assert safe["arbitrary_cids"] == ["[secret-omitted]"]
    assert safe["request_id"] == "[secret-omitted]"
    assert safe["nested"]["source_evidence_cids"] == ["[secret-omitted]"]
    assert safe["metadata"]["provider_context"]["request_id"] == "[secret-omitted]"
    safe["source_evidence_cids"][0] = "modified"
    assert payload["source_evidence_cids"][0] == cid


def test_source_cid_exception_does_not_accept_scalar_or_nested_values_and_keeps_bound():
    cid = sha256(b"source").hexdigest()
    assert _provider_payload_view({"source_evidence_cids": cid})["source_evidence_cids"] == "[secret-omitted]"
    assert _provider_payload_view({"source_evidence_cids": [[cid], {"cid": cid}]})["source_evidence_cids"] == [
        ["[secret-omitted]"], {"cid": "[secret-omitted]"},
    ]
    assert _provider_payload_view({"source_evidence_cids": [cid] * 40})["source_evidence_cids"] == [cid] * 32


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_command_extractor_preserves_real_cids_through_custody_and_replay(tmp_path, backend):
    engine = LocalMemoryEngine() if backend == "local" else SqliteEngine(tmp_path / "memory.db")
    tenant = "source-cid-test"
    try:
        cid = engine.append_evidence(Evidence(
            tenant_id=tenant, user_id="user", actor="user", source_type="chat",
            content="Atlas release status is green.", access_policy={"tenant": tenant},
        ))
        source = engine.get_evidence(tenant, cid)
        assert source is not None
        provider = tmp_path / "provider.py"
        received = tmp_path / "received.json"
        provider.write_text(
            "import json, pathlib, sys\n"
            "request = json.load(sys.stdin)\n"
            "path = pathlib.Path(sys.argv[1])\n"
            "assert not path.exists(), 'provider must run once before replay'\n"
            "path.write_text(json.dumps(request))\n"
            "cids = request['payload']['source_evidence_cids']\n"
            "assert cids == [row['cid'] for row in request['evidence']]\n"
            "print(json.dumps({'candidates': [{'signature': 'atlas release green', "
            "'query': 'Atlas release status', 'candidate_subject': 'Atlas', "
            "'candidate_predicate': 'release status', 'candidate_object': 'green', "
            "'source_evidence_cids': cids, 'access_policy': request['evidence'][0]['access_policy']}]}))\n",
            encoding="utf-8",
        )
        extractor = CommandCandidateExtractor([sys.executable, str(provider), str(received)])
        extractor.proposal_ledger = ProviderProposalLedger(engine)
        payload = {"source_evidence_cids": [cid], "note": "sk-arbitrarysecretvalue"}
        first = extractor.extract(tenant, payload, [source])
        replay = extractor.extract(tenant, payload, [source])
        request = json.loads(received.read_text(encoding="utf-8"))
        assert request["payload"]["source_evidence_cids"] == [cid]
        assert request["payload"]["note"] == "[secret-omitted]"
        assert first["candidates"][0]["source_evidence_cids"] == [cid]
        assert replay["candidates"][0]["source_evidence_cids"] == [cid]
        assert not first["details"]["proposal_record"]["replayed"]
        assert replay["details"]["proposal_record"]["replayed"]
        records = [row for row in engine.export_tenant(tenant)["evidence"]
                   if row["source_type"] == "provider-proposal"]
        assert len(records) == 1
        assert records[0]["metadata"]["provider_proposal"]["input_cids"] == [cid]
    finally:
        engine.close()

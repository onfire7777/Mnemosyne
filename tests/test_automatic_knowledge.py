from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest

from mnemosyne.answering import AnswerReadContext
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.knowledge_maintenance import KnowledgeMaintenanceWorker, read_knowledge_context
from mnemosyne.models import Assertion, Evidence, utc_now
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=['local', 'sqlite'])
def engine(request, tmp_path):
    return LocalMemoryEngine(store_path=tmp_path/'memory.json') if request.param == 'local' else SqliteEngine(tmp_path/'sqlite')


@pytest.fixture
def context():
    return AnswerReadContext('tenant', user_id='alice', role='agent', source_trust_tier=1)


def fact(engine, text, predicate, value, *, user='alice', entity='Atlas', cid=None, **kw):
    ev = Evidence('tenant', user, 'user', 'chat', text, trust_tier=1, cid=cid)
    cid = engine.append_evidence(ev)
    row = Assertion('tenant', entity, predicate, value, user_id=user, status='active',
        source_evidence_cids=[cid], trust_tier=1, calibration={
            'projection_kind': 'direct_user', 'epistemic_class': 'direct_user',
            'source_spans': [{'cid': cid, 'start': 0, 'end': len(text), 'quote': text}],
            **kw})
    engine.upsert_assertion(row)
    return cid, row


def seed(engine):
    a = fact(engine, 'Atlas runs Debian.', 'runs', 'Debian')
    b = fact(engine, 'Atlas hosts our deployment service.', 'hosts', 'deployment service')
    return a, b


def test_automatic_topic_is_compact_cited_current_and_quiet(engine, context):
    seed(engine)
    worker = KnowledgeMaintenanceWorker(engine, context)
    report = worker.run_once()
    assert report['created'] == 1
    pages = read_knowledge_context(engine, context, 'What do we know about Atlas?')
    assert len(pages) == 1
    assert 'Atlas runs Debian.' in pages[0]['text']
    assert len(pages[0]['claims']) == 2
    assert all(c['spans'] for c in pages[0]['claims'])
    assert worker.run_once()['unchanged'] == 1
    assert read_knowledge_context(engine, replace(context, user_id='bob'), 'Atlas') == []


def test_corrected_source_never_injected_before_or_after_refresh(engine, context):
    seed(engine)
    worker = KnowledgeMaintenanceWorker(engine, context)
    worker.run_once()
    fact(engine, 'Atlas runs Fedora.', 'runs', 'Fedora')
    assert read_knowledge_context(engine, context, 'Atlas') == []
    report = worker.run_once()
    assert report['updated'] == 1
    page = read_knowledge_context(engine, context, 'Atlas')[0]
    assert 'Fedora' in page['text'] and 'Debian' not in page['text']


def test_erasure_blocks_read_and_regeneration(engine, context):
    first, second = seed(engine)
    worker = KnowledgeMaintenanceWorker(engine, context)
    worker.run_once()
    engine.forget('tenant', first[0])
    assert read_knowledge_context(engine, context, 'Atlas') == []
    worker.run_once()
    pages = read_knowledge_context(engine, context, 'Atlas')
    assert all('Debian' not in p['text'] for p in pages)
    engine.forget('tenant', second[0])
    worker.run_once()
    assert read_knowledge_context(engine, context, 'Atlas') == []


def test_bounded_scan_resumes_without_invalidating_existing_views(engine, context):
    seed(engine)
    worker = KnowledgeMaintenanceWorker(engine, context, scan_batch=1)
    assert worker.run_once()['created'] == 0
    assert worker.run_once()['created'] == 0
    reports = [worker.run_once() for _ in range(4)]
    assert sum(r['created'] for r in reports) == 1
    assert len(read_knowledge_context(engine, context, 'Atlas')) == 1
    assert worker.run_once()['unchanged'] == 1


def test_expiry_and_forged_quote_are_not_republished(engine, context):
    seed(engine)
    worker = KnowledgeMaintenanceWorker(engine, context)
    worker.run_once()
    cids = read_knowledge_context(engine, context, 'Atlas')[0]['source_evidence_cids']
    for cid in cids:
        engine.update_evidence_metadata('tenant', cid, {'expires_at': (utc_now()-timedelta(seconds=1)).isoformat()})
    assert read_knowledge_context(engine, context, 'Atlas') == []
    worker.run_once()
    assert read_knowledge_context(engine, context, 'Atlas') == []


def test_two_workers_publish_only_one_current_topic(engine, context):
    seed(engine)
    workers = [KnowledgeMaintenanceWorker(engine, context) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda worker: worker.run_once(), workers))
    pages = engine.knowledge_page_list('tenant', tags=['automatic-knowledge'])
    assert len(pages) == 1
    assert len(read_knowledge_context(engine, context, 'Atlas')) == 1


def test_checkpoint_survives_one_shot_workers_without_caching_prose(engine, context, tmp_path):
    import json
    seed(engine)
    checkpoint = tmp_path/'maintenance.json'
    reports = [KnowledgeMaintenanceWorker(engine, context, scan_batch=1,
               checkpoint_path=checkpoint).run_once() for _ in range(7)]
    assert sum(report['created'] for report in reports) == 1
    stored = checkpoint.read_text()
    assert 'Atlas' not in stored and 'Debian' not in stored and 'alice' not in stored
    assert json.loads(stored)['schema']
    assert len(read_knowledge_context(engine, context, 'Atlas')) == 1


def test_erasure_scrubs_stored_title_body_claims_and_regeneration(engine, context):
    a, b = seed(engine)
    worker = KnowledgeMaintenanceWorker(engine, context)
    worker.run_once()
    engine.forget('tenant', a[0])
    pages = engine.knowledge_page_list('tenant', tags=['automatic-knowledge'], status='all')
    assert all('Debian' not in str(page.to_dict()) for page in pages)
    assert all('Atlas' not in str(page.to_dict()) for page in pages)
    worker.run_once()
    assert read_knowledge_context(engine, context, 'Atlas')[0]['claims'][0]['text'] == b[1].calibration['source_spans'][0]['quote']
    engine.forget('tenant', b[0])
    worker.run_once()
    assert all('Atlas' not in str(page.to_dict()) for page in engine.knowledge_page_list('tenant', status='all'))


def test_recurrent_questions_prioritize_real_facts_without_becoming_facts(engine, context):
    fact(engine, 'Atlas runs Debian.', 'runs', 'Debian')
    for question in ('What is running on Atlas?', 'Tell me more about Atlas?'):
        engine.append_evidence(Evidence('tenant', 'alice', 'user', 'chat', question, trust_tier=1))
    assert KnowledgeMaintenanceWorker(engine, context).run_once()['created'] == 1
    page = read_knowledge_context(engine, context, 'Atlas')[0]
    assert len(page['claims']) == 1 and '?' not in page['text']


def test_archived_topic_is_not_automatically_regenerated(engine, context):
    seed(engine)
    worker = KnowledgeMaintenanceWorker(engine, context)
    worker.run_once()
    page = read_knowledge_context(engine, context, 'Atlas')[0]
    engine.knowledge_page_archive('tenant', page['page_id'])
    fact(engine, 'Atlas has 32 GB RAM.', 'has_ram', '32 GB')
    assert worker.run_once()['created'] == 0
    assert not read_knowledge_context(engine, context, 'Atlas')


def test_related_topics_update_after_archive_and_duplicate_merge(engine, context):
    import copy
    fact(engine, 'Atlas deploys Borealis.', 'deploys', 'Borealis', entity_mentions=['Atlas', 'Borealis'])
    fact(engine, 'Atlas runs Debian.', 'runs', 'Debian')
    fact(engine, 'Borealis hosts the dashboard.', 'hosts', 'dashboard', entity='Borealis')
    worker = KnowledgeMaintenanceWorker(engine, context)
    worker.run_once()
    worker.run_once()
    pages = engine.knowledge_page_list('tenant', tags=['automatic-knowledge'])
    assert len(pages) == 2
    atlas = next(p for p in pages if p.title == 'Atlas')
    borealis = next(p for p in pages if p.title == 'Borealis')
    assert borealis.path in atlas.content_markdown
    duplicate = copy.deepcopy(atlas)
    duplicate.page_id = 'kp-duplicate'
    duplicate.path = 'topics/duplicate'
    engine.knowledge_page_create(duplicate)
    assert worker.run_once()['merged'] == 1
    assert len(engine.knowledge_page_list('tenant', tags=['automatic-knowledge'])) == 2
    engine.knowledge_page_archive('tenant', borealis.page_id)
    worker.run_once()
    atlas = next(p for p in engine.knowledge_page_list('tenant', tags=['automatic-knowledge']) if p.title == 'Atlas')
    assert borealis.path not in atlas.content_markdown


def test_tampered_projection_cannot_become_grounded_memory(engine, context):
    seed(engine)
    worker = KnowledgeMaintenanceWorker(engine, context)
    worker.run_once()
    page = engine.knowledge_page_list('tenant', tags=['automatic-knowledge'])[0]
    page.maintenance['claims'][0]['text'] = 'Atlas has a made-up password.'
    engine.knowledge_page_update(page, expected_version=page.version)
    assert read_knowledge_context(engine, context, 'Atlas') == []
    assert engine.knowledge_page_get('tenant', page.page_id).status == 'stale'


def test_separate_sqlite_connections_publish_atomically(tmp_path, context):
    location = tmp_path/'parallel'
    first, second = SqliteEngine(location), SqliteEngine(location)
    seed(first)
    workers = [KnowledgeMaintenanceWorker(e, context) for e in (first, second)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda worker: worker.run_once(), workers))
    assert len(read_knowledge_context(first, context, 'Atlas')) == 1
    assert len(first.knowledge_page_list('tenant', tags=['automatic-knowledge'])) == 1

"""Bounded recovery of semantic projections from retained real episodes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

from mnemosyne.experience.receipts import digest

PROJECTION_VERSION = 2


def maintenance_context(engine, tenant_id, user_id):
    """Use normal readable-source policy independently of operator authority.

    source_trust_tier=0 would restrict reads to tier-zero evidence, silently
    hiding ordinary captured user/tool sources from automatic maintenance.
    """
    from mnemosyne.answering import AnswerReadContext
    return AnswerReadContext(tenant_id=tenant_id, user_id=user_id, role='operator',
                             max_trust_tier=engine.policy.max_trust_tier)


def _retryable(value):
    if isinstance(value, dict):
        if value.get('provider_unavailable') or value.get('reason') in {
            'provider_failed', 'provider_unavailable', 'reviewer_unavailable', 'review_failed',
        }:
            return True
        return any(_retryable(item) for item in value.values())
    if isinstance(value, list):
        return any(_retryable(item) for item in value)
    return False


def _save_checkpoint(path, state):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        temporary.chmod(0o600)
        json.dump(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _next_attempt(previous, timestamp):
    attempts = previous.get('attempts', 0) + 1
    return {'attempts': attempts, 'last_attempt': timestamp,
            'next_attempt': timestamp + min(3600, 15 * 2 ** min(attempts, 8))}


def advance_project_memory(runtime, tenant_id, user_id, checkpoint_path, *, limit=4, provider_limit=2):
    """Publish deterministic knowledge first; resume model work by source.

    The queue is durable before the first provider call. Each source attempt
    is checkpointed independently, so interruption never replays an entire
    large episode's model work or prevents its ordinary facts being retained.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('projection limit must be between 1 and 100')
    if type(provider_limit) is not int or not 0 <= provider_limit <= 2:
        raise ValueError('provider limit must be between 0 and 2')
    path = Path(checkpoint_path)
    try:
        checkpoint = json.loads(path.read_text())
    except (OSError, ValueError):
        checkpoint = {}
    scope = {'tenant_id': tenant_id, 'user_id': user_id}
    compatible = (checkpoint.get('version') in {1, PROJECTION_VERSION}
                  and checkpoint.get('scope', scope) == scope)
    completed = checkpoint.get('completed', {}) if compatible else {}
    retries = checkpoint.get('retries', {}) if compatible else {}
    provider_queue = checkpoint.get('provider_queue', {}) if compatible else {}
    provider_completed = checkpoint.get('provider_completed', {}) if compatible else {}
    if compatible and checkpoint.get('version') == 1:
        # Version one completed whole episodes without a durable source queue.
        # Revisit their idempotent deterministic projection once to discover
        # pending provider sources; keep genuine failure backoff intact.
        completed = {}
    timestamp = time.time()
    state = runtime.writer.read(tenant_id)
    rows = sorted((row for row in state['episodes'].values()
                   if row.get('user_id') == user_id and row.get('status') != 'erased'),
                  key=lambda row: (row.get('created_at', ''), row['id']))
    fingerprints = {row['id']: digest([row.get('source_cids', []), row.get('tool_events', [])]) for row in rows}
    by_id = {row['id']: row for row in rows}
    completed = {key: value for key, value in completed.items() if key in by_id}
    retries = {key: value for key, value in retries.items() if key in by_id}
    def current_source(item):
        episode = by_id.get(item.get('episode_id'))
        return (episode is not None and item.get('source_cid') in episode.get('source_cids', [])
                and item.get('fingerprint') == fingerprints[episode['id']])
    provider_queue = {key: item for key, item in provider_queue.items() if current_source(item)}
    provider_completed = {key: item for key, item in provider_completed.items() if current_source(item)}
    state = {'version': PROJECTION_VERSION, 'scope': scope, 'completed': completed, 'retries': retries,
             'provider_queue': provider_queue, 'provider_completed': provider_completed}
    pending = [(row, fingerprints[row['id']]) for row in rows]
    pending = [(row, fingerprint) for row, fingerprint in pending
               if completed.get(row['id']) != fingerprint]
    report = {'processed': 0, 'created': 0, 'pending': len(pending), 'errors': [],
              'provider_processed': 0, 'provider_pending': 0, 'provider_deferred': 0}
    eligible = [(row, fingerprint) for row, fingerprint in pending
                if retries.get(row['id'], {}).get('next_attempt', 0) <= timestamp]
    # Retry failures later without allowing a few old failures to starve all
    # newer sources. The next attempt and count survive worker restarts.
    eligible.sort(key=lambda pair: (retries.get(pair[0]['id'], {}).get('last_attempt', 0),
                                    pair[0].get('created_at', ''), pair[0]['id']))
    report['deferred'] = len(pending) - len(eligible)
    for row, fingerprint in eligible[:limit]:
        success = False
        try:
            results = runtime._project_episode_memory(tenant_id, row, provider_cids=set())
            report['created'] += sum(item.get('created_count', 0) for item in results)
            for result in results:
                cid = result.get('source_cid')
                if result.get('provider_pending') is not True or cid not in row.get('source_cids', []):
                    continue
                key = digest([row['id'], cid])
                if key not in provider_completed:
                    provider_queue.setdefault(key, {'episode_id': row['id'], 'source_cid': cid,
                        'fingerprint': fingerprint, 'enqueued_at': timestamp})
            if not _retryable(results):
                completed[row['id']] = fingerprint
                success = True
            report['processed'] += 1
        except Exception as error:
            # Persist no source text or provider exception bodies.
            report['errors'].append({'episode_id': row['id'], 'type': type(error).__name__})
        if success:
            retries.pop(row['id'], None)
        else:
            retries[row['id']] = _next_attempt(retries.get(row['id'], {}), timestamp)
        _save_checkpoint(path, state)
    # This also persists pruning when there were no new deterministic episodes.
    _save_checkpoint(path, state)
    eligible_sources = [(key, item) for key, item in provider_queue.items()
                        if item.get('next_attempt', 0) <= timestamp]
    eligible_sources.sort(key=lambda pair: (pair[1].get('last_attempt', 0),
        pair[1].get('enqueued_at', 0), pair[1]['episode_id'], pair[1]['source_cid']))
    report['provider_deferred'] = len(provider_queue) - len(eligible_sources)
    for key, item in eligible_sources[:provider_limit]:
        # A killed process leaves this source retryable with backoff. Sources
        # never attempted remain first in line on the next worker run.
        item.update(_next_attempt(item, time.time()))
        _save_checkpoint(path, state)
        try:
            results = runtime._project_episode_memory(tenant_id, by_id[item['episode_id']],
                                                       provider_cids={item['source_cid']})
            report['created'] += sum(result.get('created_count', 0) for result in results)
            report['provider_processed'] += 1
            if not _retryable(results):
                provider_completed[key] = {name: item[name] for name in ('episode_id', 'source_cid', 'fingerprint')}
                provider_queue.pop(key, None)
        except Exception as error:
            report['errors'].append({'episode_id': item['episode_id'], 'source_cid': item['source_cid'],
                                     'phase': 'provider', 'type': type(error).__name__})
        _save_checkpoint(path, state)
    report['pending'] -= sum(completed.get(row['id']) == fingerprint for row, fingerprint in pending)
    report['provider_pending'] = len(provider_queue)
    return report

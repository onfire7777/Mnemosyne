"""Check applied memories against independent observations from the current turn.

These checks evaluate the remembered claim, not overall task success or causal
benefit. Promotion and utility still require their existing controlled evidence.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
import shlex
from types import SimpleNamespace

from mnemosyne.experience.receipts import digest
from mnemosyne.local_paths import normalize_workspace


def _fingerprint(projection):
    row = asdict(projection)
    return digest(json.loads(json.dumps({key: value for key, value in row.items()
                   if key not in {'last_accessed', 'access_count'}}, default=str)))


def command_argv(command):
    if isinstance(command, list) and command and all(isinstance(x, str) for x in command):
        return command
    if not isinstance(command, str) or any(x in command for x in ('\n', '$', '`')):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|<>()')
        lexer.whitespace_split = True
        lexer.commenters = ''
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens or any(token and all(c in ';&|<>()' for c in token) for token in tokens):
        return None
    return tokens


def freeze_contracts(engine, tenant, hits, pages, delivered_pages, item_sources):
    """Only canonical assertions and completely checkable delivered pages qualify."""
    frozen = {}
    for hit in hits:
        identifier = hit['id']
        if identifier not in item_sources or hit.get('kind') != 'assertion':
            continue
        projection = engine._get_projection_for_adapter(tenant, hit.get('branch', 'main'),
                                                         'assertion', identifier)
        contract = getattr(projection, 'calibration', {}).get('verification_contract')
        if isinstance(contract, dict) and contract.get('source_cid') in item_sources[identifier]:
            frozen[identifier] = [{**deepcopy(contract),
                **({'file': projection.scope['file']} if projection.scope.get('file') else {}),
                '_projection': {
                'kind': 'assertion', 'id': identifier, 'branch': hit.get('branch', 'main'),
                'fingerprint': _fingerprint(projection)}}]
    for page in pages:
        identifier = page.get('page_id', page.get('id'))
        delivered = delivered_pages.get(identifier)
        if not delivered:
            continue
        text = delivered.get('text', delivered.get('content', ''))
        claims = [claim for claim in page.get('claims', [])
                  if claim.get('text') and claim['text'] in text]
        contracts = [claim.get('verification_contract') for claim in claims]
        if (claims and len(claims) == len(page.get('claims', []))
                and not delivered.get('omitted_claims')
                and all(isinstance(contract, dict)
                           and contract.get('source_cid') in item_sources.get(identifier, [])
                           for contract in contracts)):
            projection = engine.knowledge_page_get(tenant, page_id=identifier)
            if projection is not None:
                frozen[identifier] = [{**deepcopy(contract), '_projection': {
                    'kind': 'page', 'id': identifier, 'branch': projection.branch,
                    'fingerprint': _fingerprint(projection)}} for contract in contracts]
    return frozen


def contracts_current(engine, tenant, user, identifier, contracts):
    """Source existence alone cannot validate a superseded or expired claim."""
    from mnemosyne.access_policy import may_read_item
    from mnemosyne.answering import AnswerReadContext
    from mnemosyne.knowledge_maintenance import automatic_page_current
    from mnemosyne.models import utc_now

    identities = [contract.get('_projection') for contract in contracts]
    if not identities or not all(identity == identities[0] for identity in identities):
        return False
    identity = identities[0]
    if not isinstance(identity, dict) or identity.get('id') != identifier:
        return False
    branch = identity.get('branch', 'main')
    if identity.get('kind') == 'assertion':
        projection = engine._get_projection_for_adapter(tenant, branch, 'assertion', identifier)
    elif identity.get('kind') == 'page':
        projection = engine.knowledge_page_get(tenant, branch=branch, page_id=identifier)
    else:
        return False
    if (projection is None or projection.user_id != user or projection.status != 'active'
            or _fingerprint(projection) != identity.get('fingerprint')):
        return False
    if (getattr(projection, 'superseded_by', None) or getattr(projection, 'expired_at', None)
            or (getattr(projection, 'valid_to', None) is not None and projection.valid_to <= utc_now())
            or (getattr(projection, 'valid_from', None) is not None and projection.valid_from > utc_now())):
        return False
    context = AnswerReadContext(tenant_id=tenant, user_id=user, branch=branch)
    decision = may_read_item(item_tenant_id=tenant, sensitivity=projection.sensitivity,
        access_policy=projection.access_policy, context=context.to_filter(),
        policy_max_sensitivity=engine.policy.max_sensitivity, status=projection.status)
    if not decision.allowed or decision.redacted:
        return False
    return identity['kind'] != 'page' or automatic_page_current(engine, projection, context)


def _same_workspace(actual, expected):
    actual, expected = normalize_workspace(actual), normalize_workspace(expected)
    return actual is not None and actual == expected


def _read_observation(contract, event):
    """Use the same deterministic parser as capture, with actual tool bytes only.

    A reread is independent evidence of a stored claim, not a task-success
    label. File custody is mandatory so equal keys from other files cannot
    confirm a memory. No model or assistant-generated statement is a checker.
    """
    from mnemosyne.project_observations import extract_observed_claims, _complete_config_snapshot

    output = event.get('output') or event.get('stdout')
    if not contract.get('file') or not isinstance(output, str) or not output:
        return None
    source = SimpleNamespace(actor='tool', cid='current-tool-' + event['call_id'],
                             content=output, metadata={})
    claims = [claim for claim in extract_observed_claims(source, event=event)
              if claim.subject == contract.get('subject')
              and claim.predicate == contract.get('predicate')
              and claim.scope.get('file') == contract['file']]
    if claims:
        values = {claim.object for claim in claims}
        return next(iter(values)) == contract.get('object') if len(values) == 1 else None
    snapshot = _complete_config_snapshot(source, event, None)
    if (snapshot is not None and snapshot['scope'].get('file') == contract['file']
            and str(contract.get('predicate', '')).startswith('configuration.')
            and contract['predicate'] not in snapshot['keys']):
        return False
    return None


def _check(contract, event):
    if (event.get('source') != 'tool' or event.get('evidence_rejected')
            or not event.get('call_id') or not event.get('check_id')
            or event.get('status') not in {None, 'completed', 'complete', 'success', 'succeeded', 'failed', 'failure'}):
        return None
    if contract.get('kind') == 'command_observation':
        if (type(contract.get('expected_exit_code')) is not int
                or type(event.get('exit_code')) is not int
                or not _same_workspace(event.get('cwd'), contract.get('cwd'))
                or command_argv(event.get('command')) != contract.get('argv')):
            return None
        return event['exit_code'] == contract['expected_exit_code']
    if contract.get('kind') == 'structured_observation':
        if not _same_workspace(event.get('cwd'), contract.get('workspace')):
            return None
        matches = [row for row in event.get('observations', []) if isinstance(row, dict)
                   and row.get('subject') == contract.get('subject')
                   and row.get('predicate') == contract.get('predicate')]
        # Contradictory results from one observation are ambiguous.
        if len(matches) == 1 and 'object' in matches[0]:
            return matches[0]['object'] == contract.get('object')
        if not matches:
            return _read_observation(contract, event)
    return None


def observed_memory_checks(receipt, used_items, events, source_is_live, *, target_is_current=None):
    """Produce target checks only for explicitly applied, source-live memories."""
    generated = []
    served = {item['item_id'] for item in receipt.get('items', []) if item.get('kind') == 'item'}
    for identifier in sorted(set(used_items) & served):
        sources = receipt.get('item_sources', {}).get(identifier, [])
        contracts = receipt.get('item_verification_contracts', {}).get(identifier, [])
        if (not contracts or not sources or not source_is_live(sources)
                or target_is_current is None or not target_is_current(identifier, contracts)):
            continue
        checked = []
        for contract in contracts:
            matches = [(event, verdict) for event in events
                       if (verdict := _check(contract, event)) is not None]
            if not matches or len({verdict for _, verdict in matches}) != 1:
                break
            checked.append(matches[-1])
        if len(checked) != len(contracts):
            continue
        # All claims must be independently checked before grading a whole page.
        event = checked[-1][0]
        generated.append({
            'name': 'memory_observation_verifier', 'source': 'tool',
            'call_id': event['call_id'], 'check_id': event['check_id'],
            'checked_call_ids': list(dict.fromkeys(row['call_id'] for row, _ in checked)),
            'receipt_id': receipt['id'], 'target_ids': [identifier],
            'verdict': all(verdict for _, verdict in checked), 'outcome_scope': 'diagnostic',
            'evidence': 'Observed current execution against the frozen memory claim contract.',
        })
    return generated

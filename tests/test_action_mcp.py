from dataclasses import replace

import pytest

from eval.public.action_cli import ActionCLI, mint_session_token, SESSION_SECRET
from eval.public.action_mcp import PersistentActionCommands, translate


def test_translation_preserves_types_multiplicity_and_rejects_unknown_options():
    name, args = translate('intention-schedule', ('--tenant','t','--dependency','a','--dependency','b',
        '--trigger-expression','{"at":"x"}','--action','{"ref":"r"}','--evidence-cid','c'))
    assert name == 'schedule_intention'
    assert args == {'tenant_id':'t','dependencies':['a','b'],'trigger_expression':{'at':'x'},
                    'action':{'ref':'r'},'evidence_ids':['c']}
    assert translate('intention-list', ('--tenant','t','--include-revision'))[1]['include_revision'] is True
    for command, flags in [('unknown',()), ('intention-list',('--tenant','t','--tenant','other')),
                           ('intention-list',('--not-real','x')), ('intention-list',('--tenant',))]:
        with pytest.raises(ValueError):
            translate(command, flags)


def test_persistent_public_action_roundtrip_and_authentication(tmp_path):
    commands = PersistentActionCommands(store=str(tmp_path/'unused.json'), timeout_s=10)
    scope = {'store':str(tmp_path/'memory.json'),'tenant_id':'tenant','session_id':'session'}
    adapter = ActionCLI(commands)
    try:
        adapter.run('clock.inject',scope,{'now':'2030-01-01T00:00:00Z'})
        adapter.run('task.create',scope,{'task_id':'keep','action_id':'keep','idempotency_key':'key',
            'trigger':{'type':'exact_time','payload':{'at':'2030-01-01T01:00:00Z'}}})
        inspected = adapter.run('task.inspect',scope,{'task_id':'keep','include_schedule':True})
        assert inspected['status']=='scheduled'
        pid = commands.children[scope['store']][0].process.pid
        adapter.run('task.create',scope,{'task_id':'cancel','action_id':'cancel',
            'trigger':{'type':'exact_time','payload':{'at':'2030-01-01T01:00:00Z'}}})
        adapter.run('task.update',scope,{'type':'cancel','task_id':'cancel'})
        adapter.run('clock.inject',scope,{'now':'2030-01-01T01:00:00Z'})
        result = adapter.run('intention.observe',scope)
        assert result['action_ids']==['keep']
        assert result['evaluation_wall_ms']>=0
        assert adapter.run('intention.observe',scope)['action_ids']==[]
        assert commands.children[scope['store']][0].process.pid==pid
        token = mint_session_token(tenant_id='other',user_id='owner',role='operator',secret=SESSION_SECRET)
        child = commands.children[scope['store']][0]
        hostile = replace(commands,store=scope['store'],global_flags=['--session-token',token],
                          env={'MNEMOSYNE_SESSION_SECRET':SESSION_SECRET})
        with pytest.raises(RuntimeError):
            hostile.run('intention-list','--tenant','tenant')
        assert child.process.poll() is not None
    finally:
        children = [entry[0] for entry in commands.children.values()]
        commands.close()
    assert not commands.children
    assert all(child.process.poll() is not None for child in children)


def test_oversized_request_is_rejected_before_starting_a_child(tmp_path):
    commands = PersistentActionCommands(store=str(tmp_path/'store.json'),
        global_flags=['--session-token','test-token'],env={'MNEMOSYNE_SESSION_SECRET':SESSION_SECRET})
    try:
        with pytest.raises(ValueError, match='request exceeds'):
            commands.run('capture','--content','x'*(1024*1024))
        assert not commands.children
    finally:
        commands.close()

"""Development bridge from actual formation responses to public action calls.

No evaluator label is sent to the provider. This is not an admitted benchmark,
a model implementation, or a sandbox for untrusted provider executables.
"""

import base64
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import time

from mnemosyne.providers.bounded_command import run_bounded_command

from eval.public.action_implicit_plan import public_turn
from eval.public.bundle import _canonical, _parse_json


MAX_INPUT_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 128 * 1024
MAX_OPERATIONS = 16
MAX_TASKS = 128


@dataclass(frozen=True)
class CommandFormationProvider:
    """Explicitly configured executable; JSON stdin, bounded UTF-8 JSON stdout."""

    argv: tuple[str, ...]
    identity: str
    timeout_seconds: float = 30.0

    def __post_init__(self):
        if (not isinstance(self.argv, tuple) or not self.argv
                or any(not isinstance(arg, str) or not arg for arg in self.argv)
                or not isinstance(self.identity, str) or not self.identity.strip()
                or type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds)
                or self.timeout_seconds <= 0):
            raise ValueError('invalid formation provider configuration')

    def complete(self, request):
        raw = json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError('formation input exceeds limit')
        result = run_bounded_command(self.argv, raw, timeout_seconds=self.timeout_seconds,
                                     max_stdout_bytes=MAX_OUTPUT_BYTES)
        # Return the status and raw bytes even on nonzero exit. The bridge records
        # stdout before failing, without publishing possibly sensitive stderr.
        return result.returncode, result.stdout


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError('invalid formation identifier')
    return value


def validate_response(raw, *, allowed_actions, existing_tasks):
    """Validate batch envelopes before writes; CLI validates payload semantics.

    This does not make multiple public mutations atomic. Later CLI rejection
    can follow an earlier successful mutation; the bridge retains both events.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_OUTPUT_BYTES:
        raise ValueError('formation output exceeds limit or is not bytes')
    value = _parse_json(raw.decode('utf-8'), 'formation response')
    if not isinstance(value, dict) or set(value) != {'operations', 'clarification'}:
        raise ValueError('invalid formation response envelope')
    question = value['clarification']
    if question is not None and (not isinstance(question, str) or not question.strip() or len(question) > 4096):
        raise ValueError('invalid clarification')
    operations = value['operations']
    if not isinstance(operations, list) or len(operations) > MAX_OPERATIONS:
        raise ValueError('invalid formation operation count')
    if question is not None and operations:
        raise ValueError('clarification cannot also perform writes')
    known = set(existing_tasks)
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != {'command', 'payload'}:
            raise ValueError('invalid formation operation')
        command, payload = operation['command'], operation['payload']
        if command not in ('task.create', 'task.update') or not isinstance(payload, dict):
            raise ValueError('unsupported formation operation')
        task = _name(payload.get('task_id'))
        if command == 'task.create':
            required = {'task_id', 'action_id', 'trigger'}
            optional = {'dependency_ids', 'recurrence_policy', 'idempotency_key'}
            if not required <= payload.keys() or payload.keys() - required - optional:
                raise ValueError('invalid create fields')
            trigger = payload['trigger']
            if not isinstance(trigger, dict) or set(trigger) != {'type', 'payload'}:
                raise ValueError('invalid trigger envelope')
            if trigger['type'] not in ('exact_time', 'time_window', 'event', 'condition', 'dependency_completion'):
                raise ValueError('unsupported trigger type')
            if not isinstance(trigger['payload'], dict):
                raise ValueError('invalid trigger payload')
            dependencies = payload.get('dependency_ids', [])
            if (not isinstance(dependencies, list) or len(dependencies) > MAX_TASKS
                    or any(_name(dependency) not in known for dependency in dependencies)):
                raise ValueError('unknown formation dependency')
            known.add(task)
        else:
            allowed = {'task_id', 'type', 'action_id', 'due_at', 'recurrence_policy',
                       'expected_revision', 'idempotency_key'}
            if payload.keys() - allowed or task not in known:
                raise ValueError('unknown update task or fields')
            kind = payload.get('type')
            if kind not in ('cancel', 'override', 'reschedule'):
                raise ValueError('unsupported update type')
            if kind == 'cancel' and {'action_id', 'due_at', 'recurrence_policy'} & payload.keys():
                raise ValueError('cancel cannot carry replacement fields')
            if kind != 'reschedule' and 'due_at' in payload:
                raise ValueError('only reschedule accepts due_at')
            if kind != 'cancel' and 'action_id' not in payload:
                raise ValueError('update needs an action identifier')
            if kind == 'reschedule' and 'due_at' not in payload:
                raise ValueError('reschedule needs due_at')
        if 'action_id' in payload and _name(payload['action_id']) not in allowed_actions:
            raise ValueError('action is outside the offered inert actions')
        if 'idempotency_key' in payload:
            _name(payload['idempotency_key'])
        if command == 'task.update' and (('idempotency_key' in payload) != ('expected_revision' in payload)):
            raise ValueError('keyed updates require their original revision')
        if len(known) > MAX_TASKS:
            raise ValueError('formation task limit exceeded')
    return value


def run_case(case, *, provider, actions, scope, emit):
    """Drive one isolated case, recording every attempted public operation.

    ``provider.complete`` returns (exit code, raw stdout bytes). ``actions`` is
    the public ActionCLI seam. Emit must persist records before returning; a
    failed emit stops execution. Provider/runtime failures are not scored as
    successes and are never retried automatically.
    """
    tasks, prior_responses = set(), []
    case_id = case['public']['case_id']
    offered = {row['action_id'] for row in case['public']['actions']}

    def call(command, payload, turn):
        emit({'stage': 'action_request', 'case_id': case_id, 'turn': turn,
              'command': command, 'payload': deepcopy(payload)})
        started = time.perf_counter()
        try:
            response = actions.run(command, scope, deepcopy(payload))
        except Exception as error:
            emit({'stage': 'action_error', 'case_id': case_id, 'turn': turn,
                  'command': command, 'error_type': type(error).__name__})
            raise
        emit({'stage': 'action_response', 'case_id': case_id, 'turn': turn,
              'command': command, 'response': deepcopy(response),
              'wall_ms': (time.perf_counter() - started) * 1000})
        return response

    for index in range(len(case['public']['turns'])):
        prefix = public_turn(case, index)
        call('clock.inject', {'now': prefix['turns'][-1]['now']}, index)
        call('evidence.capture', {'content': _canonical(prefix).decode('utf-8')}, index)
        current = [call('task.inspect', {'task_id': task, 'include_schedule': True}, index) for task in sorted(tasks)]
        request = {'schema': 'm12-formation-request/v1', 'conversation': prefix,
                   'current_tasks': current, 'prior_responses': deepcopy(prior_responses),
                   'response_contract': {'fields': ['operations', 'clarification'],
                                         'commands': ['task.create', 'task.update'],
                                         'maximum_operations': MAX_OPERATIONS}}
        if len(json.dumps(request, allow_nan=False).encode()) > MAX_INPUT_BYTES:
            raise ValueError('formation input exceeds limit')
        emit({'stage': 'formation_request', 'case_id': case_id, 'turn': index,
              'provider_identity': provider.identity, 'request': deepcopy(request)})
        started = time.perf_counter()
        try:
            code, raw = provider.complete(deepcopy(request))
            if not isinstance(raw, bytes) or len(raw) > MAX_OUTPUT_BYTES:
                raise ValueError('formation output exceeds limit or is not bytes')
            emit({'stage': 'formation_response', 'case_id': case_id, 'turn': index,
                  'returncode': code, 'stdout_base64': base64.b64encode(raw).decode('ascii'),
                  'wall_ms': (time.perf_counter() - started) * 1000})
            if type(code) is not int or code != 0:
                raise ValueError('formation provider exited unsuccessfully')
            response = validate_response(raw, allowed_actions=offered, existing_tasks=tasks)
        except Exception as error:
            emit({'stage': 'formation_error', 'case_id': case_id, 'turn': index,
                  'error_type': type(error).__name__})
            raise
        for operation in response['operations']:
            call(operation['command'], operation['payload'], index)
            if operation['command'] == 'task.create':
                tasks.add(operation['payload']['task_id'])
        prior_responses.append(response)
        snapshot = [call('task.inspect', {'task_id': task, 'include_schedule': True}, index) for task in sorted(tasks)]
        emit({'stage': 'turn_completed', 'case_id': case_id, 'turn': index,
              'tasks': deepcopy(snapshot), 'clarification': response['clarification']})
    return {'case_id': case_id, 'status': 'completed', 'turns': len(prior_responses),
            'publishable': False, 'scored': False}

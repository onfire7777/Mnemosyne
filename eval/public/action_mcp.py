"""Persistent public MCP equivalent of the command subset used by ActionCLI.

The symbolic adapter remains shared. This translates only its documented CLI
arguments, then sends signed JSON-RPC calls to a separate production process.
No engine imports or gold schedules enter this transport.
"""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import time

from eval.harness.cli_driver import CLIResult, MnemoCLI
from eval.public.adapters.backend_transport_parity import BoundedChild, TransportError
from eval.public.bundle import _parse_json

COMMANDS = {
    'capture': ('capture', 'tenant user actor source-type source-identity content'),
    'intention-schedule': ('schedule_intention', 'tenant user agent trigger-type trigger-expression action due-at evidence-cid dependency recurrence-policy idempotency-key'),
    'intention-update': ('update_intention', 'tenant intention-id user agent action due-at recurrence-policy expected-revision idempotency-key'),
    'intention-cancel': ('cancel_intention', 'tenant intention-id expected-revision idempotency-key'),
    'intention-list': ('list_intentions', 'tenant include-revision'),
    'intention-evaluate': ('evaluate_intentions', 'tenant evaluated-at trigger-context operating-point'),
}
ALIASES = {'tenant':'tenant_id','user':'user_id','agent':'agent_id',
           'evidence-cid':'evidence_ids','dependency':'dependencies'}
JSON_FLAGS = {'trigger-expression','action','recurrence-policy','trigger-context','operating-point'}
REPEATED = {'evidence-cid','dependency'}


def translate(command, flags):
    """Fail closed on unsupported/duplicate flags rather than silently dropping them."""
    if command not in COMMANDS:
        raise ValueError('unsupported public action command')
    name, allowed = COMMANDS[command]
    arguments, position = {}, 0
    while position < len(flags):
        flag = flags[position]
        if not isinstance(flag,str) or not flag.startswith('--') or flag[2:] not in allowed.split():
            raise ValueError('unsupported public action flag')
        key = flag[2:]
        target = ALIASES.get(key,key.replace('-','_'))
        if target in arguments and key not in REPEATED:
            raise ValueError('duplicate public action flag')
        position += 1
        if key == 'include-revision':
            value = True
        else:
            if position >= len(flags) or not isinstance(flags[position],str):
                raise ValueError('public action flag requires a string value')
            value = flags[position]
            position += 1
            if key in JSON_FLAGS:
                value = _parse_json(value,'public action argument')
        if key in REPEATED:
            arguments.setdefault(target,[]).append(value)
        else:
            arguments[target] = value
    return name, arguments


@dataclass(slots=True)
class PersistentActionCommands(MnemoCLI):
    # dataclasses.replace (used by ActionCLI) intentionally shares this owner map.
    children: dict = field(default_factory=dict)

    def _rpc(self, entry, method, params):
        child, _, count = entry
        if count >= 8192:
            raise TransportError('persistent action request budget exhausted')
        entry[2] += 1
        child.send({'jsonrpc':'2.0','id':entry[2],'method':method,'params':params})
        try:
            response = _parse_json(child.receive(line=True),'MCP response')
        except (ValueError, UnicodeError) as error:
            raise TransportError('invalid persistent action response') from error
        if (not isinstance(response,dict) or response.get('jsonrpc')!='2.0'
                or type(response.get('id')) is not int or response['id']!=entry[2] or 'error' in response):
            raise TransportError('invalid persistent action response identity')
        return response

    def run(self, command, *args, check=True, parse_json=True):
        if self.backend!='local' or check is not True or parse_json is not True:
            raise ValueError('persistent action transport requires checked local JSON calls')
        if len(self.global_flags)!=2 or self.global_flags[0]!='--session-token':
            raise ValueError('persistent action transport requires one signed session token')
        secret = self.env.get('MNEMOSYNE_SESSION_SECRET')
        if not isinstance(secret,str) or not secret:
            raise ValueError('persistent action transport requires a session verifier secret')
        name, arguments = translate(command,args)
        request = {'name':name,'arguments':arguments,'session_token':self.global_flags[1]}
        if len(json.dumps(request).encode()) > 1024*1024-256:
            raise ValueError('persistent action request exceeds 1 MiB')
        if type(self.timeout_s) not in (int,float) or not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError('timeout must be positive and finite')
        timeout = min(30,self.timeout_s)
        entry = self.children.get(self.store)
        if entry is not None and entry[1]!=secret:
            raise ValueError('cannot change verifier identity on a live store')
        started = time.perf_counter()
        try:
            if entry is None:
                if len(self.children) >= 5:
                    raise ValueError('close an existing scope before starting a sixth child')
                environment = {k:v for k,v in self._environ().items() if not k.startswith('MNEMOSYNE_')}
                environment['MNEMOSYNE_MCP_SESSION_SECRET'] = secret
                child = BoundedChild([self.python,'-m','mnemosyne.mcp_server','--backend','local',
                    '--store',self.store,'--object-store',str(Path(self.store).with_suffix('.objects')),
                    '--require-session'],env=environment,timeout=timeout)
                entry = [child,secret,0]
                self.children[self.store] = entry
                self._rpc(entry,'initialize',{})
                child.send({'jsonrpc':'2.0','method':'notifications/initialized'})
            entry[0].timeout = timeout
            response = self._rpc(entry,'tools/call',request)
            result = response.get('result')
            if not isinstance(result,dict) or type(result.get('isError')) is not bool:
                raise TransportError('invalid persistent action tool envelope')
            if result['isError']:
                # Never surface raw provider error text: it may echo the signed token.
                raise TransportError('public action tool rejected the request')
            value = result.get('structuredContent')
            if not isinstance(value,dict):
                raise TransportError('persistent action result must be an object')
            return CLIResult(argv=[command,*args],returncode=0,stdout=json.dumps(value),stderr='',
                             wall_ms=(time.perf_counter()-started)*1000,json=value)
        except BaseException:
            if entry is not None:
                entry[0].close()
                self.children.pop(self.store,None)
            raise

    def close(self):
        for key in list(self.children):
            self.children.pop(key)[0].close()

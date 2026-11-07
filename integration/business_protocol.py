"""LONGS application envelope v1 validation (stdlib, no side effects).
Shape validation is not authorization. Receiver must check sender, expiry and durable dedup.
"""
import re, math
from datetime import datetime, timezone
KINDS={'data','event','command','result'}
NAME=re.compile(r'^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$')
OP=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')

def timestamp(value, field):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?Z',value):
        raise ValueError(field+' must be an RFC3339 UTC timestamp ending in Z')
    try:return datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError(field+' is not a valid timestamp') from None

def validate_business(body, *, sender=None, allowed_senders=None, allowed_commands=None, check_expiry=False, now=None):
    if not isinstance(body,dict):raise ValueError('body must be an object')
    allowed={'protocol','version','kind','name','operationId','issuedAt','expiresAt','payload','status','error'}
    if set(body)-allowed:raise ValueError('unknown envelope field; put business fields in payload')
    if body.get('protocol')!='longs-app' or type(body.get('version')) is not int or body['version']!=1:raise ValueError('unsupported protocol/version')
    if not isinstance(body.get('kind'),str) or body['kind'] not in KINDS:raise ValueError('invalid kind')
    if not isinstance(body.get('name'),str) or len(body['name'])>96 or not NAME.fullmatch(body['name']):raise ValueError('invalid name')
    if not isinstance(body.get('operationId'),str) or not OP.fullmatch(body['operationId']):raise ValueError('invalid operationId')
    if not isinstance(body.get('payload'),dict):raise ValueError('payload must be an object')
    issued=timestamp(body.get('issuedAt'),'issuedAt')
    expires=timestamp(body['expiresAt'],'expiresAt') if 'expiresAt' in body else None
    if body['kind']=='command' and expires is None:raise ValueError('command requires expiresAt')
    if expires is not None and expires<=issued:raise ValueError('expiresAt must be later than issuedAt')
    if body['kind']=='result':
        if body.get('status') not in ('succeeded','failed','rejected'):raise ValueError('invalid result status')
        if body['status']!='succeeded':
            error=body.get('error')
            if not isinstance(error,dict) or set(error)!={'code','message','retryable'}:raise ValueError('error requires code, message, retryable')
            if not isinstance(error['code'],str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}',error['code']):raise ValueError('invalid error code')
            if not isinstance(error['message'],str) or not 1<=len(error['message'])<=512 or type(error['retryable']) is not bool:raise ValueError('invalid error fields')
        elif 'error' in body:raise ValueError('successful result cannot contain error')
    elif 'status' in body or 'error' in body:raise ValueError('status/error only allowed for result')
    if allowed_senders is not None and sender not in allowed_senders:raise ValueError('sender not authorized')
    if body['kind']=='command' and allowed_commands is not None and body['name'] not in allowed_commands:raise ValueError('command not authorized')
    if check_expiry:
        instant=now or datetime.now(timezone.utc)
        if issued.timestamp()>instant.timestamp()+60:raise ValueError('issuedAt too far in future')
        if expires is not None and instant>=expires:raise ValueError('message expired')
    return body

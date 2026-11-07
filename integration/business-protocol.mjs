export const BUSINESS_KINDS=Object.freeze(['data','event','command','result']);
function instant(value,field){
  const match=typeof value==='string'&&value.match(/^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,3}))?Z$/);
  if(!match)throw Error(field+' must be RFC3339 UTC ending in Z');
  const normalized=match[1]+'.'+(match[2]||'').padEnd(3,'0')+'Z',n=Date.parse(normalized);
  if(!Number.isFinite(n)||new Date(n).toISOString()!==normalized)throw Error('Invalid '+field);return n;
}
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
export function validateBusiness(body,{sender,allowedSenders,allowedCommands,checkExpiry=false,now=Date.now()}={}){
  if(!object(body))throw Error('body must be an object');
  const fields=['protocol','version','kind','name','operationId','issuedAt','expiresAt','payload','status','error'];
  if(Object.keys(body).some(k=>!fields.includes(k)))throw Error('Unknown envelope field; use payload');
  if(body.protocol!=='longs-app'||body.version!==1)throw Error('Unsupported protocol/version');
  if(!BUSINESS_KINDS.includes(body.kind))throw Error('Invalid kind');
  if(typeof body.name!=='string'||body.name.length>96||!/^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/.test(body.name))throw Error('Invalid name');
  if(typeof body.operationId!=='string'||!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(body.operationId))throw Error('Invalid operationId');
  if(!object(body.payload))throw Error('payload must be an object');
  const issued=instant(body.issuedAt,'issuedAt'),expires='expiresAt' in body?instant(body.expiresAt,'expiresAt'):undefined;
  if(body.kind==='command'&&expires===undefined)throw Error('command requires expiresAt');
  if(expires!==undefined&&expires<=issued)throw Error('expiresAt must be later than issuedAt');
  if(body.kind==='result'){
    if(!['succeeded','failed','rejected'].includes(body.status))throw Error('Invalid result status');
    if(body.status==='succeeded'){if('error' in body)throw Error('Successful result cannot contain error')}
    else{const e=body.error;if(!object(e)||Object.keys(e).sort().join(',')!=='code,message,retryable'||typeof e.code!=='string'||!/^[A-Z][A-Z0-9_]{0,63}$/.test(e.code)||typeof e.message!=='string'||!e.message.length||e.message.length>512||typeof e.retryable!=='boolean')throw Error('Invalid result error')}
  }else if('status' in body||'error' in body)throw Error('status/error only allowed for result');
  if(allowedSenders&&!allowedSenders.includes(sender))throw Error('Sender not authorized');
  if(body.kind==='command'&&allowedCommands&&!allowedCommands.includes(body.name))throw Error('Command not authorized');
  if(checkExpiry){if(issued>now+60000)throw Error('issuedAt too far in future');if(expires!==undefined&&now>=expires)throw Error('Message expired')}
  return body;
}
export function createBusiness({kind,name,payload={},operationId=crypto.randomUUID(),issuedAt=new Date().toISOString(),expiresAt,status,error}){
  return validateBusiness({protocol:'longs-app',version:1,kind,name,operationId,issuedAt,payload,...(expiresAt!==undefined?{expiresAt}:{}),...(status!==undefined?{status}:{}),...(error!==undefined?{error}:{})});
}

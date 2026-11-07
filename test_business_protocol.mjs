import assert from 'node:assert/strict';
import {createBusiness,validateBusiness} from './integration/hub-sdk.mjs';
for(const kind of ['data','event','command','result']){
  const b=createBusiness({kind,name:'notes.import-image',operationId:'test-001',issuedAt:'2026-11-07T08:00:00Z',payload:{},...(kind==='command'?{expiresAt:'2026-11-07T08:05:00Z'}:{}),...(kind==='result'?{status:'succeeded'}:{})});
  assert.equal(b.kind,kind);
}
const b=createBusiness({kind:'command',name:'notes.import-image',expiresAt:new Date(Date.now()+60000).toISOString()});
assert.throws(()=>validateBusiness({...b,kind:'shell'}));
assert.throws(()=>validateBusiness({...b,issuedAt:'2026-02-30T00:00:00Z'}));
assert.throws(()=>validateBusiness(b,{sender:'evil',allowedSenders:['pc']}));
assert.throws(()=>validateBusiness(b,{allowedCommands:['other.action']}));
assert.throws(()=>validateBusiness(b,{checkExpiry:true,now:Date.now()+120000}));
console.log('Business protocol JS PASS: four kinds, schema, calendar, authorization, expiry; no network.');

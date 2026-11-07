/** Small deterministic SDK lifecycle test. No network, no load generation. */
import assert from 'node:assert/strict';
import {HubClient} from './integration/hub-sdk.mjs';
const originalWS=globalThis.WebSocket,originalFetch=globalThis.fetch;
class FakeSocket {
  static instances=[];
  constructor(){this.readyState=0;FakeSocket.instances.push(this)}
  open(){this.readyState=1;this.onopen?.()}
  send(text){this.last=JSON.parse(text)}
  receive(value){this.onmessage?.({data:JSON.stringify(value)})}
  close(code=1000){this.readyState=3;this.onclose?.({code})}
}
let client;
try{
  globalThis.WebSocket=FakeSocket;
  globalThis.fetch=async()=>({ok:true,status:200,json:async()=>({ok:true,messages:[]})});
  const processed=[];client=new HubClient({baseURL:'https://local.invalid',token:'test-only',onMessage:async m=>{processed.push(m.id)},onError:()=>{throw Error('callback failure')}});
  client.connect().connect();assert.equal(FakeSocket.instances.length,1);
  const ws=FakeSocket.instances[0];ws.open();assert.equal(ws.last.type,'auth');
  ws.receive({type:'sync',messages:[{id:'one'}]});ws.receive({type:'sync',messages:[{id:'one'}]});await client.chain;assert.deepEqual(processed,['one']);
  ws.close(4001);assert.equal(client.stopped,true);assert.equal(client.reconnect,undefined);
  client.connect();assert.equal(FakeSocket.instances.length,2);client.close();
  // HTTP errors keep status, so revoked credentials can stop retry loops.
  globalThis.fetch=async()=>({ok:false,status:401,json:async()=>({detail:'invalid'})});
  await assert.rejects(client.ack('one'),e=>e.status===401);
  await assert.rejects(client.send('recipient',{v:1},{clientMessageId:'persisted-key'}),e=>e.clientMessageId==='persisted-key');
  // Timeout really aborts, rather than just leaving an unresolved request behind.
  globalThis.fetch=(_url,{signal})=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('aborted'))));
  client.requestTimeout=10;await assert.rejects(client.software(),/aborted/);
  // A CONNECTING socket must time out even when onopen never runs.
  const stalled=new HubClient({baseURL:'https://local.invalid',token:'test-only',connectTimeout:10,onMessage:async()=>{},onError:()=>{}});
  stalled.connect();await new Promise(resolve=>setTimeout(resolve,30));assert.ok(stalled.reconnect);stalled.close();
  console.log('SDK PASS: CONNECTING timeout, idempotent connect, ordered duplicate handling, terminal close, throwing error callback isolation, status propagation, abort timeout (no network).');
}finally{client?.close();globalThis.WebSocket=originalWS;globalThis.fetch=originalFetch}

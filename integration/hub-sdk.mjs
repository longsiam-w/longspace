import {validateBusiness,createBusiness} from './business-protocol.mjs';
export {validateBusiness,createBusiness} from './business-protocol.mjs';
/** Browser / Node >=22. Tokens must remain private. */
const enc = new TextEncoder(); const dec = new TextDecoder();
const b64 = bytes => { let s=''; for(const b of bytes)s+=String.fromCharCode(b); return btoa(s); };
const unb64 = s => Uint8Array.from(atob(s), c=>c.charCodeAt(0));
export async function createE2EKey(){ return b64(crypto.getRandomValues(new Uint8Array(32))); }
async function aesKey(secret){ return crypto.subtle.importKey('raw',unb64(secret),'AES-GCM',false,['encrypt','decrypt']); }
// A distinct pairwise key per sender/recipient pair. Distribute out-of-band.
export async function seal(body, secret, sender, recipient){
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const data=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:enc.encode(JSON.stringify([sender,recipient]))},await aesKey(secret),enc.encode(JSON.stringify(body)));
  return {e2e:'A256GCM-v1',iv:b64(iv),data:b64(new Uint8Array(data))};
}
export async function open(envelope, secret, sender, recipient){
  if(envelope.e2e!=='A256GCM-v1')throw Error('Unsupported E2E envelope');
  return JSON.parse(dec.decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:unb64(envelope.iv),additionalData:enc.encode(JSON.stringify([sender,recipient]))},await aesKey(secret),unb64(envelope.data))));
}
export class HubClient {
  constructor({baseURL,token,onMessage,onError=console.error,allowInsecure=false,requestTimeout=15000,connectTimeout=15000}){
    this.baseURL=baseURL.replace(/\/$/,'');const url=new URL(this.baseURL);
    if(!allowInsecure&&url.protocol!=='https:')throw Error('HTTPS required');
    if(typeof onMessage!=='function')throw Error('onMessage callback required');
    this.token=token;this.onMessage=onMessage;this.onError=onError;this.requestTimeout=requestTimeout;this.connectTimeout=connectTimeout;
    this.seen=new Set();this.stopped=true;this.retry=500;this.chain=Promise.resolve();this.generation=0;
  }
  report(error){try{this.onError(error)}catch{/* An error callback must not break reconnection. */}}
  async request(path, options={}){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),this.requestTimeout);
    try{
      const r=await fetch(this.baseURL+'/api'+path,{...options,signal:controller.signal,headers:{'Content-Type':'application/json',Authorization:'Bearer '+this.token,...options.headers}});
      let data;try{data=await r.json()}catch{const error=Error('Invalid server response ('+r.status+')');error.status=r.status;throw error}
      if(!r.ok){const error=Error(data.detail||r.statusText);error.status=r.status;throw error}return data;
    }finally{clearTimeout(timeout)}
  }
  async me(){return this.request('/software/me')}
  async software(){return this.request('/software')}
  // No automatic send retry: an ambiguous timeout may already have committed a message.
  async send(recipient,body,{clientMessageId=crypto.randomUUID()}={}){
    // Persist the key AND body in an application outbox before calling send.
    if(body?.protocol==='longs-app')validateBusiness(body);
    try{return await this.request('/messages',{method:'POST',body:JSON.stringify({recipient,body,clientMessageId})})}
    catch(error){error.clientMessageId=clientMessageId;throw error}
  }
  async sendBusiness(recipient,body,options={}){validateBusiness(body);return this.send(recipient,body,options)}
  async ack(id){return this.request('/messages/'+encodeURIComponent(id)+'/ack',{method:'POST'})}
  async deliver(message){
    if(!this.seen.has(message.id)){
      await this.onMessage(message); // Resolve only after durable application processing.
      this.seen.add(message.id);if(this.seen.size>1000)this.seen.delete(this.seen.values().next().value);
    }
    await this.ack(message.id);
  }
  serialize(work){const next=this.chain.then(work);this.chain=next.catch(()=>{});return next}
  async pull(){return this.serialize(async()=>{const {messages}=await this.request('/messages');for(const m of messages)await this.deliver(m)})}
  connect(){if(!this.stopped)return this;this.stopped=false;this.dial();return this}
  schedule(){if(this.stopped)return;clearTimeout(this.reconnect);this.reconnect=setTimeout(()=>this.dial(),this.retry+Math.random()*300);this.retry=Math.min(30000,this.retry*2)}
  dial(){
    if(this.stopped)return;const generation=++this.generation;let ws,heartbeat;
    try{ws=new WebSocket(this.baseURL.replace(/^http/,'ws')+'/api/ws')}catch(error){this.report(error);this.schedule();return}
    this.ws=ws;let lastResponse=Date.now(),authenticated=false;
    const live=()=>!this.stopped&&generation===this.generation&&this.ws===ws;
    const disconnect=()=>{clearTimeout(handshake);clearInterval(heartbeat);try{ws.close()}catch{};if(live()){++this.generation;this.schedule()}};
    const handshake=setTimeout(()=>{if(live()&&ws.readyState!==1){this.report(Error('Connection timeout; reconnecting'));disconnect()}},this.connectTimeout);this.handshake=handshake;
    ws.onopen=()=>{
      clearTimeout(handshake);
      if(!live()){ws.close();return}
      lastResponse=Date.now();ws.send(JSON.stringify({type:'auth',token:this.token}));
      heartbeat=setInterval(()=>{
        if(!live()){clearInterval(heartbeat);return}
        // A socket can appear OPEN after a network blackhole; pong/sync proves liveness.
        if(Date.now()-lastResponse>60000){this.report(Error('Heartbeat timeout; reconnecting'));disconnect();return}
        if(ws.readyState===1)ws.send(JSON.stringify({type:'ping'}));
      },25000);this.heartbeat=heartbeat;
    };
    ws.onmessage=e=>{
      if(!live())return;let packet;try{packet=JSON.parse(e.data);if(!packet||typeof packet!=='object')throw Error('Invalid relay frame')}catch(error){this.report(error);disconnect();return}
      lastResponse=Date.now();
      if(packet.type!=='sync')return;
      if(!Array.isArray(packet.messages)){this.report(Error('Invalid sync batch'));disconnect();return}
      if(!authenticated){authenticated=true;this.retry=500}
      this.serialize(async()=>{for(const m of packet.messages){if(!live())break;await this.deliver(m)}}).catch(error=>{
        this.report(error);if(!live())return;if(error.status===401||error.status===403){this.stopped=true;clearInterval(heartbeat);ws.close();return}disconnect();
      });
    };
    ws.onerror=()=>{}; // close event triggers bounded backoff; never log tokens.
    ws.onclose=e=>{
      clearTimeout(handshake);clearInterval(heartbeat);if(!live())return;
      if([4001,4003,1008].includes(e.code)){this.stopped=true;this.report(Error('Connection replaced, revoked or unauthorized ('+e.code+')'));return}
      this.schedule();
    };
  }
  close(){this.stopped=true;++this.generation;clearTimeout(this.reconnect);clearTimeout(this.handshake);clearInterval(this.heartbeat);this.ws?.close()}
}

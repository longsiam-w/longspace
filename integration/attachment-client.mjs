/** Node.js 22+ attachment helper. Streaming file I/O; never administrator credentials.
 * Keep uploadKey and returned metadata in your durable outbox. No automatic retries.
 */
import {createReadStream,createWriteStream} from 'node:fs';
import {open,rename,stat,unlink} from 'node:fs/promises';
import {basename} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {Readable,Transform} from 'node:stream';
import {pipeline} from 'node:stream/promises';
function origin(baseURL){const u=new URL(baseURL);if(u.protocol!=='https:'||u.username||u.password||u.pathname!=='/'||u.search||u.hash)throw Error('Trusted HTTPS origin required');return u.origin}
async function checked(response){if(!response.ok){const e=Error('Attachment HTTP '+response.status);e.status=response.status;throw e}return response}
async function fileHash(path){const hash=createHash('sha256');for await(const chunk of createReadStream(path))hash.update(chunk);return hash.digest('hex')}
export async function uploadAttachment({baseURL,token,path,recipient,uploadKey,mime='application/octet-stream',signal}){
  if(!uploadKey)throw Error('Persist an uploadKey before upload');
  const sha256=await fileHash(path),before=await stat(path),query=new URLSearchParams({recipient,name:basename(path),uploadKey,sha256});
  const response=await checked(await fetch(origin(baseURL)+'/api/attachments?'+query,{method:'PUT',headers:{Authorization:'Bearer '+token,'Content-Type':mime,'Content-Length':String(before.size)},body:createReadStream(path),duplex:'half',redirect:'error',signal:signal||AbortSignal.timeout(300000)}));
  const result=await response.json();if(result.state!=='ready')throw Error('Attachment already consumed/expired; do not send a new import command');return result;
}
export async function completeAttachment({baseURL,token,asset,signal}){
  return (await checked(await fetch(origin(baseURL)+'/api/attachments/'+encodeURIComponent(asset.id)+'/complete',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({size:asset.size,sha256:asset.sha256}),redirect:'error',signal:signal||AbortSignal.timeout(15000)}))).json();
}
export async function downloadAttachmentToFile({baseURL,token,asset,path,signal}){
  if(!asset||!/^[0-9a-f]{32}$/.test(asset.id)||!Number.isSafeInteger(asset.size)||asset.size<0||!/^[0-9a-f]{64}$/.test(asset.sha256))throw Error('Invalid trusted attachment metadata');
  // Only fixed server origin, never a URL supplied in a message body.
  const temp=path+'.'+randomUUID()+'.part';let saved=false;
  try{
    const response=await checked(await fetch(origin(baseURL)+'/api/attachments/'+asset.id+'/download',{headers:{Authorization:'Bearer '+token},redirect:'error',signal:signal||AbortSignal.timeout(300000)}));
    if(!response.body)throw Error('Missing download body');
    let size=0;const hash=createHash('sha256');
    await pipeline(Readable.fromWeb(response.body),new Transform({transform(chunk,_encoding,cb){size+=chunk.length;if(size>asset.size){cb(Error('Attachment size exceeds expected'));return}hash.update(chunk);cb(null,chunk)}}),createWriteStream(temp,{flags:'wx',mode:0o600}));
    if(size!==asset.size||hash.digest('hex')!==asset.sha256)throw Error('Attachment integrity mismatch');
    const f=await open(temp,'r+');try{await f.sync()}finally{await f.close()}
    // Destination should be a private staging path chosen by the application, not message text.
    await rename(temp,path);saved=true;
    try{await completeAttachment({baseURL,token,asset,signal});return {path,confirmed:true}}
    catch(error){error.localPath=path;error.downloadSaved=true;throw error} // retry COMPLETE only, not import
  }finally{if(!saved)await unlink(temp).catch(()=>{})}
}

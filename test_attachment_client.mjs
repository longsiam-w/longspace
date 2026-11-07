import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';import {join} from 'node:path';import {createHash} from 'node:crypto';
import {uploadAttachment,downloadAttachmentToFile,completeAttachment} from './integration/attachment-client.mjs';
const dir=await mkdtemp(join(tmpdir(),'hub-attachment-client-')),original=globalThis.fetch;
const bytes=Buffer.from('tiny-client-test'),asset={id:'a'.repeat(32),size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),state:'ready'};let completed=0;
try{
 const source=join(dir,'source.png');await writeFile(source,bytes);
 globalThis.fetch=async(url,options)=>{
   if(options.method==='PUT'){const parts=[];for await(const chunk of options.body)parts.push(chunk);assert.deepEqual(Buffer.concat(parts),bytes);return new Response(JSON.stringify(asset))}
   if(url.endsWith('/download'))return new Response(bytes);
   if(url.endsWith('/complete')){completed++;assert.deepEqual(JSON.parse(options.body),{size:asset.size,sha256:asset.sha256});return new Response('{"ok":true}')}
   throw Error('unexpected request');
 };
 const metadata=await uploadAttachment({baseURL:'https://local.invalid',token:'test-only',path:source,recipient:'tablet',uploadKey:'persisted'});assert.equal(metadata.id,asset.id);
 const destination=join(dir,'saved.png');await downloadAttachmentToFile({baseURL:'https://local.invalid',token:'test-only',asset,path:destination});assert.deepEqual(await readFile(destination),bytes);assert.equal(completed,1);
 // Integrity failure must not confirm deletion.
 await assert.rejects(downloadAttachmentToFile({baseURL:'https://local.invalid',token:'test-only',asset:{...asset,sha256:'0'.repeat(64)},path:join(dir,'bad.png')}));assert.equal(completed,1);
 globalThis.fetch=async(url)=>url.endsWith('/download')?new Response(bytes):new Response('error',{status:503});
 await assert.rejects(downloadAttachmentToFile({baseURL:'https://local.invalid',token:'test-only',asset,path:join(dir,'saved-unconfirmed.png')}),e=>e.downloadSaved===true);
 assert.deepEqual(await readFile(join(dir,'saved-unconfirmed.png')),bytes);
 console.log('Attachment client PASS: stream upload/download, verified save before complete, hash failure no delete, confirmation failure retains local file. No network.');
}finally{globalThis.fetch=original;await rm(dir,{recursive:true,force:true})}

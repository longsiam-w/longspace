'use strict';
const byId=id=>document.getElementById(id);
const make=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el};
function jsonBlock(value){const pre=make('pre');pre.append(make('code',JSON.stringify(value,null,2)));return pre}
async function loadDocs(){
  byId('api-retry').hidden=true;byId('api-status').textContent='正在加载接口文档…';
  try{
    const response=await fetch('/api/openapi.json',{signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw Error('HTTP '+response.status);
    const spec=await response.json();if(!spec.paths||typeof spec.paths!=='object')throw Error('接口描述格式错误');
    const host=byId('api-endpoints');host.replaceChildren();let count=0;
    for(const [path,operations] of Object.entries(spec.paths))for(const [method,operation] of Object.entries(operations)){
      if(!['get','post','put','patch','delete','head','options'].includes(method))continue;
      const card=make('details');card.className='api-endpoint panel';
      const title=make('summary');title.append(make('code',method.toUpperCase()+' '+path),make('span',' — '+(operation.summary||operation.operationId||'')));card.append(title);
      if(operation.description)card.append(make('p',operation.description));
      if(operation.parameters?.length){card.append(make('h3','参数'));card.append(jsonBlock(operation.parameters))}
      if(operation.requestBody){card.append(make('h3','请求体'));card.append(jsonBlock(operation.requestBody))}
      card.append(make('h3','响应'),jsonBlock(operation.responses||{}));
      card.dataset.search=(method+' '+path+' '+(operation.summary||'')+' '+(operation.description||'')).toLocaleLowerCase();host.append(card);count++;
    }
    const schemas=byId('api-schemas');schemas.replaceChildren();for(const [name,value] of Object.entries(spec.components?.schemas||{})){const item=make('details');item.append(make('summary',name),jsonBlock(value));schemas.append(item)}
    byId('api-status').textContent='已加载 '+count+' 个接口 · '+(spec.info?.version||'');filterDocs();
  }catch(error){byId('api-status').textContent='加载失败：'+error.message+'。可重试或查看接入说明。';byId('api-retry').hidden=false}
}
function filterDocs(){const query=byId('api-filter').value.trim().toLocaleLowerCase();for(const card of byId('api-endpoints').children)card.hidden=!card.dataset.search.includes(query)}
byId('api-filter').addEventListener('input',filterDocs);byId('api-retry').onclick=loadDocs;loadDocs();

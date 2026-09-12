import {createProjectPicker} from './series-picker.js?v=1.3.1';
const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];
const escape = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
  stack:'<path d="m3 7 9-4 9 4-9 4Zm0 5 9 4 9-4M3 17l9 4 9-4"/>',
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  folder:'<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3Z"/>',
  star:'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9Z"/>',
  music:'<path d="M9 18V5l11-2v13M9 9l11-2"/><ellipse cx="6" cy="18" rx="3" ry="3"/><ellipse cx="17" cy="16" rx="3" ry="3"/>',
  subtitles:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 10h3m4 0h3M7 15h10"/>',
  inbox:'<path d="M4 5h16v14H4z"/><path d="M4 8h16M8 3v4m8-4v4M8 12h8m-8 4h5"/>',
  history:'<path d="M3 11a9 9 0 1 1 2.8 7M3 4v7h7m2-4v5l3 2"/>',
  settings:'<path d="M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1Z"/><circle cx="12" cy="12" r="3"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5M5.2 7a8 8 0 0 1 13.3-1L20 8M4 16l1.5 2a8 8 0 0 0 13.3-1"/>',
  video:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3Z"/>',
  image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m21 16-6-6-9 11"/>',
  arrow:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  external:'<path d="M14 3h7v7m0-7L10 14M10 3H3v18h18v-7"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  edit:'<path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-4-4L5 15Z"/>',
  play:'<path d="m8 4 12 8-12 8Z"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.folder}</svg>`;
const kindLabel = {video:'视频',audio:'音频',image:'图片'};
const state = {boot:null,view:'library',source:'',collection:'',kind:'',q:'',page:1,pages:1,stats:null,items:[],selected:null,project:'',relative:'auto',checked:new Set(),request:0,jobs:new Map(),toastTimer:null,detailRequest:0,tracks:[],stack:[],stackChecked:new Set(),stackCount:0,compact:false,issue:'',inboxSelected:new Set(),videoMode:'bv',videoStack:[],videoChecked:new Set(),librarySort:'modified-desc',stackSort:'modified-desc'};

function size(bytes) {if(bytes < 1024*1024)return `${(bytes/1024).toFixed(0)} KB`;if(bytes < 1024**3)return `${(bytes/1024**2).toFixed(1)} MB`;return `${(bytes/1024**3).toFixed(2)} GB`;}
function duration(value){if(!value)return '';const s=Math.round(value);return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;}
function wave(seed=''){return `<div class="audio-art tone-${seed.length%4}"><div class="audio-wave" aria-hidden="true">${Array.from({length:25},(_,i)=>`<i style="height:${8+((i*17+(seed.charCodeAt(i%Math.max(seed.length,1))||5))%30)}px"></i>`).join('')}</div></div>`;}
function toast(text){clearTimeout(state.toastTimer);$('#toast').textContent=text;$('#toast').hidden=false;state.toastTimer=setTimeout(()=>$('#toast').hidden=true,5500);}
async function api(path, options={}) {
  const headers = {'X-Workbench-Token':state.boot?.token || '',...options.headers};
  if(options.body && !(options.body instanceof FormData)){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);}
  const response=await fetch(path,{...options,headers});
  if(!response.ok){let value;try{value=await response.json();}catch{}throw new Error(typeof value?.detail==='string'?value.detail:`请求未完成（${response.status}）`);}
  return response.json();
}
function run(action){return Promise.resolve().then(action).catch(error=>toast(error.message));}
function enabled(id){return state.boot.modules.some(m=>m.id===id && m.enabled && m.installed);}

function nav(){
  const entries=[['library','grid','素材库','library'],['stack','stack','素材栈','stack'],['favorites','star','收藏','library'],['videos','video','视频下载','videos'],['music','music','音乐','music'],['subtitles','subtitles','字幕','subtitles'],['inbox','inbox','文件接收','inbox'],['history','history','记录',null]];
  $('#main-nav').innerHTML=entries.filter(e=>!e[3]||enabled(e[3])).map(([id,glyph,label])=>`<button class="nav-item ${state.view===id?'active':''}" data-view="${id}" title="${label}" aria-label="${label}" ${state.view===id?'aria-current="page"':''}>${icon(glyph)}<span class="label">${label}</span>${id==='stack'?`<span class="count">${state.stackCount||0}</span>`:''}</button>`).join('');
  $$('#main-nav button').forEach(b=>b.onclick=()=>navigate(b.dataset.view));
  $('#source-nav').innerHTML=enabled('library')?state.boot.sources.map(s=>`<div class="source-row ${state.source===s.id && state.view==='library'?'active':''}"><button class="nav-item source-item" data-source="${s.id}" title="${escape(s.path)}">${icon('folder')}<span class="label">${escape(s.name)}</span><span class="count">${state.stats?(state.stats.sources?.[s.id]??0):'—'}</span></button>${s.managed?`<button class="source-remove" data-remove-source="${s.id}" aria-label="从素材库移除 ${escape(s.name)}" title="移除来源">×</button>`:''}</div>`).join(''):'';
  $$('[data-source]').forEach(b=>b.onclick=()=>{state.source=state.source===b.dataset.source?'':b.dataset.source;state.collection='';state.page=1;navigate('library',true);});
  $$('[data-remove-source]').forEach(b=>b.onclick=()=>run(async()=>{
    const id=b.dataset.removeSource;
    await api('/api/sources/'+id,{method:'DELETE'});
    if(state.source===id){state.source='';state.collection='';}
    state.boot=await api('/api/bootstrap');state.stats=await api('/api/library/stats');
    nav();navigate('library',true);toast('已从素材库移除此来源；原始文件仍保留在磁盘');
  }));
}

function navigate(view,keepSource=false){
  const module=view==='favorites'?'library':view;
  if(module!=='history'&&!enabled(module))view='history';
  if(view==='library'&&!keepSource){state.source='';state.collection='';}
  if(state.compact)view='stack';
  closeDetail();state.view=view;document.body.classList.toggle('stack-page',view==='stack');state.page=1;state.checked.clear();selection();
  history.replaceState(null,'',`#${view}`);
  for(const id of ['library','stack','videos','music','subtitles','inbox','history'])$(`#${id}-view`).hidden=!(id===view||(id==='library'&&view==='favorites'));
  $('#page-title').textContent={library:'素材库',stack:'素材栈',favorites:'收藏',videos:'视频下载',music:'音乐',subtitles:'字幕',inbox:'文件接收',history:'记录'}[view];
  $('#results-label').textContent='';nav();
  document.querySelectorAll('audio,video').forEach(p=>p.pause());
  if(view==='library'||view==='favorites'){if(!enabled('library'))return;if(state.stats)filters();run(()=>loadAssets());}
  else {state.selected=null;renderEmptyDetail();if(view==='stack')run(()=>loadStack());if(view==='videos')run(()=>loadVideoStack());if(view==='history')run(()=>loadJobs(true));if(view==='subtitles')run(()=>loadSubtitleStatus());if(view==='inbox')run(()=>loadInbox());}
}

async function bootstrap(){
  state.boot=await api('/api/bootstrap');
  const remembered=new URLSearchParams(location.search).get('project')||localStorage.getItem('media-desk-project');
  state.project=state.boot.projects.some(p=>p.id===remembered)?remembered:state.boot.projects[0]?.id||'';
  projectPicker.render();
  await loadFolders();nav();
  if(enabled('library'))await loadStats();
  const requested=location.hash.slice(1);
  navigate(['library','stack','favorites','videos','music','subtitles','inbox','history'].includes(requested)?requested:enabled('library')?'library':'history');
  await loadJobs();await loadStack(false);
  if(window.mediaDesk)applyDesktopState(await window.mediaDesk.getState());
}

async function loadFolders(){
  const project=state.project;
  const data=project?await api(`/api/projects/${project}/folders`):{folders:[]};
  if(project!==state.project)return;
  $('#destination-select').innerHTML='<option value="auto">自动匹配</option>'+data.folders.map(f=>`<option value="${escape(f.relative)}">${escape(f.label)}</option>`).join('');
  state.relative='auto';$('#destination-select').value='auto';
}

async function loadStats(){
  const previous=JSON.stringify(state.stats);
  state.stats=await api('/api/library/stats');
  $('#indexed-count').textContent=`${state.stats.total.toLocaleString()} 份本地素材`;
  $('#footer-status').textContent=state.stats.scan.running?'正在扫描…':'';
  if(previous!==JSON.stringify(state.stats)){nav();filters();}
}
function filters(){
  $('#kind-filters').innerHTML=[['','全部'],['video','视频'],['audio','音频'],['image','图片']].map(([k,label])=>`<button class="filter-button ${state.kind===k?'active':''}" data-kind="${k}" aria-pressed="${state.kind===k}">${label}<span>${k?state.stats?.kinds?.[k]||0:state.stats?.total||0}</span></button>`).join('');
  $$('#kind-filters button').forEach(b=>b.onclick=()=>{state.kind=b.dataset.kind;state.page=1;filters();run(()=>loadAssets());});
  const collections=(state.stats?.collections||[]).filter(c=>!state.source||c.source_id===state.source);
  $('#collection-select').innerHTML='<option value="">所有文件夹</option>'+[...new Set(collections.map(c=>c.collection))].map(c=>`<option value="${escape(c)}">${escape(c==='memes_Video'?'美式鬼畜 · memes_Video':c)}</option>`).join('');
  $('#collection-select').value=state.collection;
}

async function loadAssets(){
  const request=++state.request;
  const query=new URLSearchParams({q:state.q,kind:state.kind,source:state.source,collection:state.collection,favorite:String(state.view==='favorites'),sort:state.librarySort.split('-')[0],order:state.librarySort.split('-')[1],page:state.page,limit:24});
  const data=await api('/api/library/assets?'+query);
  if(request!==state.request || !['library','favorites'].includes(state.view))return;
  state.items=data.items;state.pages=data.pages;
  $('#results-label').textContent=`${data.total.toLocaleString()} 份素材`;
  $('#page-indicator').textContent=`${data.page} / ${data.pages}`;
  $('#previous-page').disabled=state.page<=1;$('#next-page').disabled=state.page>=state.pages;
  if(!data.items.length){state.selected=null;renderEmptyDetail();$('#asset-grid').innerHTML=`<div class="empty-state">${icon('search')}<h2>${state.stats?.scan?.running?'正在整理本地素材':'这里还没有合适的素材'}</h2><p>${state.view==='favorites'?'点击素材上的收藏按钮，把常用的留下来。':'试试素材名、文件夹名，或换一个更短的关键词。'}</p></div>`;return;}
  $('#asset-grid').innerHTML=data.items.map(a=>`<article class="asset-card ${state.selected?.id===a.id?'selected':''}" data-id="${a.id}" data-drag-library="${a.id}" draggable="true"><label class="asset-check"><input type="checkbox" data-check="${a.id}" aria-label="选择 ${escape(a.title)}" ${state.checked.has(a.id)?'checked':''}></label><button class="asset-open" data-open="${a.id}" aria-label="预览 ${escape(a.title)}"><div class="asset-cover ${a.kind}">${a.kind==='audio'?wave(a.id):`<img src="/api/library/assets/${a.id}/thumb" alt="" loading="lazy" width="320" height="200">`}<span class="cover-badge">${escape(a.extension.slice(1).toUpperCase())}</span></div><div class="asset-info"><span class="asset-title" title="${escape(a.title)}">${escape(a.title)}</span><div class="asset-meta"><span>${escape(a.collection==='memes_Video'?'美式鬼畜':a.collection)}</span><span>${size(a.size)}</span></div></div></button></article>`).join('');
  $$('.asset-cover img').forEach(img=>img.onerror=()=>{img.replaceWith(Object.assign(document.createElement('span'),{className:'cover-fallback',innerHTML:icon('video')}));});
  $$('[data-open]').forEach(b=>b.onclick=()=>selectAsset(b.dataset.open));
  $$('[data-check]').forEach(c=>c.onchange=()=>{c.checked?state.checked.add(c.dataset.check):state.checked.delete(c.dataset.check);selection();});
  $$('[data-drag-library]').forEach(card=>card.addEventListener('dragstart',e=>{
    e.preventDefault();
    if(!window.mediaDesk){toast('请在素材台桌面窗口中拖出素材；浏览器页面不能跨应用拖放');return;}
    const id=card.dataset.dragLibrary;
    const ids=state.checked.has(id)?[...state.checked]:[id];
    if(ids.length>30){toast('每次最多拖出 30 项素材');return;}
    window.mediaDesk.startDrag({scope:'library',asset_ids:ids});
  }));

  if(state.selected && !data.items.some(a=>a.id===state.selected.id)){state.selected=null;renderEmptyDetail();}
}

function selection(){
  $('#selection-bar').hidden=!state.checked.size;
  $('#selection-label').textContent=`已选 ${state.checked.size} 项`;
  $('#batch-stack').hidden=state.boot&&!enabled('stack');
}
function closeDetail(){ $('#detail-panel').hidden=true;$('#detail-backdrop').hidden=true;document.querySelectorAll('#detail-panel audio,#detail-panel video').forEach(p=>p.pause()); }
function renderEmptyDetail(){closeDetail();$('#detail-panel').innerHTML='';}
function selectAsset(id){
  const asset=state.items.find(a=>a.id===id);if(!asset)return;
  state.selected={...asset,type:'local'};
  $$('.asset-card').forEach(c=>c.classList.toggle('selected',c.dataset.id===id));
  run(()=>renderDetail());
  run(async()=>{const fresh=await api(`/api/library/assets/${id}/metadata`);if(state.selected?.id!==id)return;Object.assign(state.selected,fresh);const el=$('#detail-duration');if(el)el.textContent=[duration(fresh.duration),fresh.width?`${fresh.width} × ${fresh.height}`:''].filter(Boolean).join(' · ');});
}

async function renderDetail(){
  const a=state.selected;if(!a){renderEmptyDetail();return;}
  $('#detail-panel').hidden=false;$('#detail-backdrop').hidden=false;
  const isMusic=a.type==='music';
  document.querySelectorAll('#detail-panel audio,#detail-panel video').forEach(p=>p.pause());
  const media=isMusic||a.kind==='audio'?wave(a.id):a.kind==='video'?`<video controls preload="none" playsinline poster="/api/library/assets/${a.id}/thumb" src="/api/library/assets/${a.id}/file"></video>`:`<img alt="${escape(a.title)}" src="/api/library/assets/${a.id}/file">`;
  const tags=isMusic?[a.artist,a.album].filter(Boolean):[a.collection,...a.tags.split(/[,，\s]+/).filter(Boolean)];
  $('#detail-panel').innerHTML=`<div class="detail-heading"><span>${isMusic?'音乐预览':'素材预览'}</span><button id="close-detail" class="icon-button" aria-label="关闭预览">${icon('close')}</button></div><div class="detail-media">${media}</div>${!isMusic&&a.kind==='audio'?`<audio class="audio-player" controls preload="none" src="/api/library/assets/${a.id}/file"></audio>`:''}${isMusic?'<button id="track-preview" class="quiet-button" style="margin-top:12px;width:100%">试听这首音乐</button><div id="track-player"></div>':''}<h2 class="detail-title">${escape(a.title||a.name)}</h2><div class="detail-fileinfo">${isMusic?'':`<span>${escape(a.extension.slice(1).toUpperCase())}</span><span>${size(a.size)}</span>`}</div><div class="detail-fileinfo" id="detail-duration">${isMusic?'':escape([duration(a.duration),a.width?`${a.width} × ${a.height}`:''].filter(Boolean).join(' · '))}</div><div class="detail-tags">${tags.map(t=>`<span class="tag">${escape(t)}</span>`).join('')}</div>${!isMusic?`<details class="detail-location"><summary>原文件路径</summary><span>${escape(a.path)}</span></details>`:''}<div class="detail-destination"><div class="destination-label">${icon('folder')}<span>保存到</span></div><div class="destination-path" id="destination-path">正在匹配项目位置…</div><div class="destination-reason" id="destination-reason"></div></div>${!isMusic&&enabled('stack')?'<button id="add-stack" class="primary-button">加入素材栈</button>':''}<button id="save-asset" class="quiet-button save-button" ${!state.project?'disabled':''}>${icon('arrow')}<span>${isMusic?'下载到当前项目':'保存到当前项目'}</span></button>${!isMusic?`<div class="secondary-actions"><button id="favorite-asset" class="${a.favorite?'favorite-on':''}">${icon('star')}${a.favorite?'已收藏':'收藏素材'}</button><button id="open-source">${icon('external')}原文件夹</button><button id="edit-tags" aria-label="编辑素材标签" title="编辑标签">${icon('edit')}</button></div><div id="metadata-editor" hidden class="metadata-editor"><label>显示名称<input id="edit-title" value="${escape(a.title)}"></label><label>搜索标签<input id="edit-tags-input" value="${escape(a.tags)}" placeholder="例如：震惊 回头 反转"></label><button id="save-tags" class="small-primary">保存标注</button></div>`:''}<button id="remember-destination" class="text-button" ${state.relative==='auto'?'hidden':''}>记住此项目的同类素材保存位置</button>`;
  $('#close-detail').onclick=closeDetail;
  if($('#add-stack'))$('#add-stack').onclick=()=>run(()=>addToStack([a.id]));
  $('#save-asset').onclick=()=>run(()=>isMusic?saveMusic(a):saveAssets([a.id]));
  if(!isMusic){
    $('#favorite-asset').onclick=()=>run(async()=>{const result=await api(`/api/library/assets/${a.id}`,{method:'PATCH',body:{favorite:!a.favorite}});Object.assign(a,result);await loadStats();await renderDetail();if(state.view==='favorites')await loadAssets();});
    $('#open-source').onclick=()=>run(()=>api('/api/open-folder',{method:'POST',body:{asset_id:a.id}}));
    $('#edit-tags').onclick=()=>{$('#metadata-editor').hidden=!$('#metadata-editor').hidden;if(!$('#metadata-editor').hidden)$('#edit-title').focus();};
    $('#save-tags').onclick=()=>run(async()=>{const result=await api(`/api/library/assets/${a.id}`,{method:'PATCH',body:{title:$('#edit-title').value,tags:$('#edit-tags-input').value}});Object.assign(a,result);await renderDetail();await loadAssets();toast('标注已保存，原文件名没有改变');});
    const video=$('#detail-panel video');if(video)video.addEventListener('error',()=>toast('浏览器无法播放此编码，仍可保存原文件'));const audio=$('#detail-panel audio');if(audio)audio.addEventListener('error',()=>toast('浏览器无法试听此格式，仍可保存原文件'));
  }else{
    $('#track-preview').onclick=()=>run(async()=>{const button=$('#track-preview');button.disabled=true;button.textContent='正在连接音乐来源…';try{const result=await api('/api/music/preview',{method:'POST',body:a});if(state.selected!==a)return;$('#track-player').innerHTML=`<audio class="audio-player" controls src="${escape(result.url)}"></audio>`;await $('#track-player audio').play().catch(()=>{});}finally{if(button.isConnected){button.disabled=false;button.textContent='重新获取试听';}}});
  }
  $('#remember-destination').onclick=()=>run(async()=>{await api('/api/routes',{method:'POST',body:{project_id:state.project,category:state.destinationCategory,relative:state.relative}});toast('已记住此项目的位置');});
  await updateDestination();
}

async function updateDestination(){
  const a=state.selected;if(!a||!$('#destination-path'))return;
  const request=++state.detailRequest;
  if(!state.project){$('#destination-path').textContent='先在上方选择一个视频项目';$('#destination-reason').textContent='使用你的现有文件夹';$('#save-asset').disabled=true;return;}
  const result=await api('/api/destination',{method:'POST',body:{project_id:state.project,asset_id:a.type==='local'?a.id:null,category:a.type==='music'?'music':a.kind,relative:state.relative}});
  if(request!==state.detailRequest||state.selected!==a||!$('#destination-path'))return;
  state.destinationCategory=result.category;
  $('#destination-path').textContent=a.type==='music'?result.directory:result.path;
  $('#destination-reason').textContent=result.reason;
  $('#save-asset').disabled=false;
  $('#remember-destination').hidden=state.relative==='auto';
}

async function saveAssets(ids){
  if(!state.project)throw new Error('请先选择视频项目');
  if(!ids.length)throw new Error('先选择素材');
  const button=$('#save-asset');if(button)button.disabled=true;$('#batch-save').disabled=true;
  try{for(let offset=0;offset<ids.length;offset+=30){const result=await api('/api/save',{method:'POST',body:{asset_ids:ids.slice(offset,offset+30),project_id:state.project,relative:state.relative}});state.jobs.set(result.job_id,'queued');}toast('正在保存到项目，完成后会提示');await loadJobs();}
  finally{if(button?.isConnected)button.disabled=false;$('#batch-save').disabled=false;}
}
async function saveMusic(track){
  if(!state.project)throw new Error('请先选择视频项目');
  const button=$('#save-asset');button.disabled=true;
  try{const result=await api('/api/music/save',{method:'POST',body:{...track,project_id:state.project,relative:state.relative}});state.jobs.set(result.job_id,'queued');toast('音乐获取任务已开始，可在最近保存中查看');}finally{button.disabled=false;}
}
async function searchMusic(){
  const q=$('#music-query').value.trim();if(!q)return;
  $('#music-search').disabled=true;$('#music-results').innerHTML='<p class="helper">正在搜索音乐来源…</p>';
  try{const result=await api('/api/music/search?'+new URLSearchParams({q,source:$('#music-source').value}));state.tracks=result.items;
    $('#music-results').innerHTML=result.items.length?result.items.map((a,i)=>`<button class="music-row" style="width:100%;text-align:left" data-track="${i}" aria-label="预览 ${escape(a.name)}"><span class="track-icon">${icon('music')}</span><span class="track-copy"><strong>${escape(a.name)}</strong><small>${escape(a.artist)} · ${escape(a.album)}</small></span>${icon('play')}</button>`).join(''):'<div class="empty-state">没有找到这首音乐，试试歌手或更短的名称。</div>';
    $$('[data-track]').forEach(b=>b.onclick=()=>{state.selected={...state.tracks[Number(b.dataset.track)],type:'music'};run(()=>renderDetail());});
  }catch(error){$('#music-results').innerHTML=`<div class="empty-state">${icon('music')}<h2>音乐来源暂时没有回应</h2><p>${escape(error.message)}</p><a class="text-button" href="https://music.gdstudio.org/" target="_blank" rel="noreferrer">打开原网站 ↗</a></div>`;}
  finally{$('#music-search').disabled=false;}
}
async function loadInbox(){
  const [issues,projects,data]=await Promise.all([api('/api/inbox/issues'),api('/api/inbox/projects'),api('/api/inbox/items')]);
  const remembered=localStorage.getItem('media-desk-issue');
  const active=issues.items.find(i=>i.id===remembered)||issues.active;
  state.issue=active?.id||'';
  $('#issue-select').innerHTML=issues.items.map(i=>`<option value="${i.id}" ${i.id===state.issue?'selected':''}>${escape(i.name)}</option>`).join('');
  const current=projects.items.find(p=>p.id===state.project);
  $('#workflow-state').innerHTML=projects.states.map(s=>`<option ${current?.state===s?'selected':''}>${escape(s)}</option>`).join('');
  $('#workflow-instruction').value=current?.instruction||projects.default_instruction;
  const visible=data.items.filter(item=>item.issue_id===state.issue||(!item.issue_id&&state.issue==='issue-53'&&item.state!=='sent'));
  $('#inbox-list').innerHTML=visible.length?visible.map(item=>{
    const kinds=item.files.map(f=>f.kind==='script'?'文案':'配音').join(' + ')||'等待文件';
    const paired=item.files.length===2?'已配对':item.state==='send_uncertain'?'待确认':'待配对';
    const script=item.files.some(f=>f.kind==='script');
    const sendState=item.send_request?.state||'';
    const canSend=item.srt.ready&&!['sent','running','sending'].includes(item.state)&&!['pending','sending'].includes(sendState);
    const sendButton=canSend?'<button class="text-button send" data-srt-send>发送 SRT</button>':sendState==='pending'?'<span class="send-state">等待发送</span>':'';
    const pick=state.inboxSelected.has(item.id);
    return `<article class="inbox-card compact-card ${pick?'picked':''}" data-inbox="${item.id}"><div class="inbox-head"><button class="pick-button" data-inbox-toggle="${item.id}">${pick?'已选择':'选择'}</button><strong>${escape(item.display_name)}</strong><span class="job-state ${escape(item.state)}">${paired}</span></div><div class="compact-line"><span>${escape(kinds)} · ${escape(item.srt.stage)}</span><select data-inbox-section aria-label="段落">${['开头','正文','结尾'].map(s=>`<option ${item.section===s?'selected':''}>${s}</option>`).join('')}</select><input data-inbox-name value="${escape(item.display_name)}" aria-label="显示名"><button class="text-button" data-inbox-save>保存</button>${script?'<button class="text-button" data-script-edit>编辑文案</button>':''}${sendButton}<button class="text-button danger" data-inbox-delete>删除</button></div><div class="script-editor" hidden></div></article>`;
  }).join(''):`<div class="empty-state"><h2>第 ${escape(active?.number||'')} 期还没有文件</h2><p>新收到的文案和配音会归到当前期。</p></div>`;
  $('#issue-select').onchange=()=>run(async()=>{const id=$('#issue-select').value;await api(`/api/inbox/issues/${id}/activate`,{method:'PATCH'});localStorage.setItem('media-desk-issue',id);await loadInbox();});
  $$('[data-inbox-toggle]').forEach(button=>button.onclick=()=>{const id=button.dataset.inboxToggle;state.inboxSelected.has(id)?state.inboxSelected.delete(id):state.inboxSelected.add(id);$('#pair-selected').disabled=state.inboxSelected.size!==2;loadInbox();});
  $$('[data-inbox-save]').forEach(button=>button.onclick=()=>run(async()=>{const card=button.closest('[data-inbox]');await api(`/api/inbox/items/${card.dataset.inbox}`,{method:'PATCH',body:{issue_id:state.issue,section:card.querySelector('[data-inbox-section]').value,display_name:card.querySelector('[data-inbox-name]').value}});toast('已归入本期');await loadInbox();}));
  $$('[data-script-edit]').forEach(button=>button.onclick=()=>run(async()=>{const card=button.closest('[data-inbox]'),box=card.querySelector('.script-editor');if(!box.hidden){box.hidden=true;return;}const data=await api(`/api/inbox/items/${card.dataset.inbox}/script`);box.innerHTML=`<textarea aria-label="编辑文案">${escape(data.content)}</textarea><button class="small-primary" data-script-save>保存文案</button>`;box.hidden=false;box.querySelector('[data-script-save]').onclick=()=>run(async()=>{await api(`/api/inbox/items/${card.dataset.inbox}/script`,{method:'PUT',body:{content:box.querySelector('textarea').value}});toast('文案已保存，将用于后续 SRT');});}));
  $$('[data-srt-send]').forEach(button=>button.onclick=()=>run(async()=>{const card=button.closest('[data-inbox]');await api(`/api/inbox/items/${card.dataset.inbox}/send`,{method:'POST'});toast('已交给 bot 发送到工作群');await loadInbox();}));
  $$('[data-inbox-delete]').forEach(button=>button.onclick=()=>run(async()=>{const card=button.closest('[data-inbox]');if(!window.confirm('删除此接收任务及本地下载文件？'))return;await api(`/api/inbox/items/${card.dataset.inbox}`,{method:'DELETE'});toast('已删除本地接收文件');await loadInbox();}));
}

async function loadSubtitleStatus(){const result=await api('/api/subtitles/status');$('#subtitle-status').textContent=result.available?'已就绪 · 相邻字幕间隔为 0':'本机字幕处理器未就绪，请检查 config.json 中的安装位置。';$('#subtitle-submit').disabled=!result.available;}

async function loadJobs(render=false){
  const {items}=await api('/api/jobs');
  for(const j of items){const old=state.jobs.get(j.id);if(old&&old!==j.status&&['succeeded','failed'].includes(j.status)){if(j.status==='succeeded'){const exists=j.result.every(r=>r.status==='already_exists');toast(exists?'目标位置已有相同文件，已跳过重复保存':`已保存到项目：${j.result.map(r=>r.name).join('、')}`);state.checked.clear();selection();$$('[data-check]').forEach(c=>c.checked=false);}else toast(`任务未完成：${j.error}`);}state.jobs.set(j.id,j.status);}
  const active=items.filter(j=>['queued','running'].includes(j.status));if(active.length)$('#footer-status').textContent=`${active.length} 个任务进行中 · ${active[0].title} ${active[0].progress}%`;
  else if(state.stats)$('#footer-status').textContent='';
  if(render||state.view==='history'){
    const labels={queued:'等待处理',running:'处理中',succeeded:'已保存',failed:'未完成'};
    $('#history-list').innerHTML=items.length?items.map(j=>`<article class="history-card"><div class="history-head"><strong>${escape(j.title)}</strong><span class="job-state ${j.status}">${labels[j.status]||j.status}</span></div><div class="history-time">${new Date(j.created*1000).toLocaleString('zh-CN')}</div>${['queued','running'].includes(j.status)?`<progress value="${j.progress}" max="100" aria-label="保存进度">${j.progress}%</progress>`:''}${j.result.map(r=>`<p class="history-path">${r.status==='already_exists'?'已存在 · ':''}${escape(r.path)}</p>`).join('')}${j.error?`<p class="history-error">${escape(j.error)}</p>`:''}${j.result.length?`<button class="text-button" data-job-folder="${j.id}">打开保存位置 ↗</button>`:''}</article>`).join(''):'<div class="empty-state">保存过的素材和处理结果，会出现在这里。</div>';
    $$('[data-job-folder]').forEach(b=>b.onclick=()=>run(()=>api('/api/open-folder',{method:'POST',body:{job_id:b.dataset.jobFolder}})));
  }
}

async function showSettings(){
  const layouts=await api('/api/layouts');
  const pathNames={video:'视频',audio:'音效／录音',music:'音乐',image:'图片',meme:'表情包',subtitle:'字幕'};
  $('#settings-content').innerHTML=`<div class="setting-row"><strong>视频项目位置</strong><div class="setting-path">${escape(state.boot.projects_root)}</div></div><div class="setting-row"><strong>本地素材来源</strong>${state.boot.sources.map(s=>`<p class="setting-path">${escape(s.name)}<br>${escape(s.path)}</p>`).join('')}</div><div class="setting-row"><strong>近期项目习惯</strong><p class="helper">最近 ${layouts.recent.length} 个项目</p>${Object.entries(layouts.habits).map(([k,v])=>`<div class="setting-path">${pathNames[k]||k}：${escape(v[0]?.[0]==='.'?'项目根目录':v[0]?.[0]||'未识别')}（${v[0]?.[1]||0} 个项目）</div>`).join('')}<p class="setting-path">${layouts.recent.slice(0,5).map(p=>escape(p.name)).join(' · ')}</p></div><div class="setting-row"><strong>独立功能模块</strong>${state.boot.modules.map(m=>`<label class="module-toggle">${escape(m.name)}<input type="checkbox" data-module="${m.id}" ${m.enabled?'checked':''} ${!m.installed?'disabled':''} aria-label="启用${escape(m.name)}"></label>`).join('')}</div>`;
  $$('[data-module]').forEach(c=>c.onchange=()=>run(async()=>{await api(`/api/modules/${c.dataset.module}`,{method:'PATCH',body:{enabled:c.checked}});const mod=state.boot.modules.find(m=>m.id===c.dataset.module);mod.enabled=c.checked;nav();if(!c.checked&&([state.view==='favorites'?'library':state.view].includes(c.dataset.module)))navigate('history');toast(c.checked?'模块已启用':'模块已停用，已有文件和记录保留');}));
  $('#settings-dialog').showModal();
}

$('#settings-button').innerHTML=icon('settings')+'<span class="label">设置</span>';$('#rescan-button').innerHTML=icon('refresh');$('#search-icon').innerHTML=icon('search');$('#open-project').innerHTML=icon('external');$('#close-settings').innerHTML=icon('close');$('.project-icon').innerHTML=icon('folder');$('.music-search-symbol').innerHTML=icon('search');
$('#settings-button').onclick=()=>run(showSettings);$('#close-settings').onclick=()=>$('#settings-dialog').close();
$('#root-button').onclick=()=>run(()=>api('/api/open-folder',{method:'POST',body:{}}));
$('#open-project').onclick=()=>run(()=>{if(!state.project)throw new Error('请先选择项目');return api('/api/open-folder',{method:'POST',body:{project_id:state.project}});});
async function selectProject(id){
  state.project=id;localStorage.setItem('media-desk-project',id);state.stackChecked.clear();
  projectPicker.render();nav();await loadFolders();await updateDestination();await loadStack();
  if(state.view==='videos')await loadVideoStack();
}
const projectPicker=createProjectPicker({state,api,escape,icon,selectProject,toast});
$('#new-project').onclick=projectPicker.openNewProject;
$('#destination-select').onchange=()=>run(async()=>{state.relative=$('#destination-select').value;await updateDestination();});
let searchTimer;$('#search-input').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.q=$('#search-input').value;state.page=1;run(loadAssets);},220);};
$('#collection-select').onchange=()=>{state.collection=$('#collection-select').value;state.page=1;run(loadAssets);};
$('#previous-page').onclick=()=>{state.page=Math.max(1,state.page-1);run(loadAssets);};$('#next-page').onclick=()=>{state.page=Math.min(state.pages,state.page+1);run(loadAssets);};
$('#clear-selection').onclick=()=>{state.checked.clear();$$('[data-check]').forEach(c=>c.checked=false);selection();};$('#batch-save').onclick=()=>run(()=>saveAssets([...state.checked]));
const rescan=()=>run(async()=>{await api('/api/library/scan',{method:'POST'});toast('正在更新素材索引和近期目录习惯');});$('#rescan-button').onclick=rescan;$('#refresh-layouts').onclick=rescan;
async function addSource(){
  if(!window.mediaDesk?.chooseSource)throw new Error('请从素材台桌面窗口点击 + 来选择本地文件夹');
  const path=await window.mediaDesk.chooseSource();
  if(!path)return;
  const source=await api('/api/sources',{method:'POST',body:{path}});
  state.boot.sources.push(source);state.source=source.id;state.collection='';state.page=1;
  toast('已加入 '+source.name+'，正在识别其中的素材');nav();navigate('library',true);
}
$('#add-source').onclick=()=>run(addSource);
$('#music-search').onclick=searchMusic;$('#music-query').onkeydown=e=>{if(e.key==='Enter')searchMusic();};
$('#refresh-inbox').onclick=()=>run(loadInbox);
$('#new-issue').onclick=()=>run(async()=>{const value=window.prompt('新一期名称', '烂活音游 54');if(!value?.trim())return;const issue=await api('/api/inbox/issues',{method:'POST',body:{name:value.trim()}});localStorage.setItem('media-desk-issue',issue.id);await loadInbox();});
$('#pair-selected').onclick=()=>run(async()=>{const ids=[...state.inboxSelected];if(ids.length!==2)throw new Error('请选择一份文案和一份配音');const result=await api('/api/inbox/pair',{method:'POST',body:{job_ids:ids}});state.inboxSelected.clear();toast(result.queued?'已配对，正在生成并自动发送 SRT':'已配对，等待文件下载后自动生成');await loadInbox();});
$('#save-workflow').onclick=()=>run(async()=>{if(!state.project)throw new Error('请先选择对应的视频项目');await api(`/api/inbox/projects/${state.project}`,{method:'PATCH',body:{state:$('#workflow-state').value,instruction:$('#workflow-instruction').value}});toast('项目状态和固定指令已保存');});
$('#subtitle-form').onsubmit=e=>{e.preventDefault();run(async()=>{if(!state.project)throw new Error('请先选择视频项目');const data=new FormData(e.target);data.set('project_id',state.project);data.set('relative',state.relative);const button=$('#subtitle-submit');button.disabled=true;button.textContent='正在提交音频和文案…';try{const result=await api('/api/subtitles/jobs',{method:'POST',body:data});state.jobs.set(result.job_id,'queued');toast('字幕任务已提交，完成后会保存到当前项目');navigate('history');}finally{button.disabled=false;button.textContent='生成 SRT';}});};
document.addEventListener('keydown',e=>{if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!document.querySelector('dialog[open]')&&$('#project-popover').hidden){e.preventDefault();if(!['library','favorites'].includes(state.view))navigate('library');$('#search-input').focus();}});
window.addEventListener('hashchange',()=>{if(!state.boot)return;const view=location.hash.slice(1)||'library';if(['library','stack','favorites','videos','music','subtitles','inbox','history'].includes(view))navigate(view);});
run(bootstrap);
setInterval(()=>{if(state.boot)run(()=>loadJobs());},2000);
setInterval(()=>{if(state.boot&&enabled('library'))run(async()=>{const before=state.stats?.total;const wasScanning=state.stats?.scan?.running;await loadStats();if((state.stats.total!==before||wasScanning)&&['library','favorites'].includes(state.view))await loadAssets();});},6000);

async function addToStack(ids){
  if(!state.project)throw new Error('先选择项目');
  await api(`/api/stack/${state.project}/items`,{method:'POST',body:{asset_ids:ids}});
  await loadStack(false);toast('已加入素材栈');
}

async function loadStack(render=true){
  if(!state.boot||!enabled('stack'))return;
  if(!state.project){state.stack=[];state.stackCount=0;state.stackChecked.clear();nav();renderStack();return;}
  const project=state.project;
  const data=await api(`/api/stack/${project}?sort=${state.stackSort.split('-')[0]}&order=${state.stackSort.split('-')[1]}`);
  if(project!==state.project)return;
  const changed=JSON.stringify(data.items)!==JSON.stringify(state.stack);
  state.stack=data.items;
  state.sharedProject=data.shared_project_id;
  $('#stack-share').hidden=!state.sharedProject;$('#stack-restore-shared').hidden=!state.sharedProject;
  $('#stack-share').disabled=!state.stackChecked.size;
  if(state.stackCount!==data.count){state.stackCount=data.count;nav();}
  if(state.view==='stack'&&(render||changed))renderStack();
}

function renderStack(){
  const available=new Set(state.stack.filter(a=>a.available).map(a=>a.asset_id));
  state.stackChecked=new Set([...state.stackChecked].filter(id=>available.has(id)));
  $('#stack-count').textContent=`${state.stack.length} 项`;
  $('#mini-count').textContent=String(state.stack.length);
  $('#stack-clear').disabled=!state.stack.length;
  $('#stack-save').disabled=!available.size||!enabled('library');
  $('#stack-remove').disabled=!state.stackChecked.size;$('#stack-share').disabled=!state.stackChecked.size;
  $('#stack-list').innerHTML=state.stack.length?state.stack.map(a=>`<article class="stack-card ${state.stackChecked.has(a.asset_id)?'selected':''} ${a.available?'':'missing'}" data-drag="${a.asset_id}" draggable="${a.available}" title="${escape(a.path||'原文件不存在')}"><label class="stack-check"><input type="checkbox" data-stack-check="${a.asset_id}" aria-label="选择栈中 ${escape(a.title)}" ${state.stackChecked.has(a.asset_id)?'checked':''} ${a.available?'':'disabled'}></label><div class="stack-thumb">${a.kind==='audio'?icon('music'):`<img src="/api/library/assets/${a.asset_id}/thumb" alt="" loading="lazy" draggable="false">`}</div><div class="stack-copy"><strong>${escape(a.title)}</strong><span>${a.is_shared?'<em class="shared-tag">系列共享</em>':''}${a.available?`${escape((a.extension||'').slice(1).toUpperCase())} · ${size(a.size)}`:'文件已移动'}</span></div><button class="icon-button" data-stack-open="${a.asset_id}" aria-label="定位 ${escape(a.title)}" title="打开原文件位置" ${a.available?'':'disabled'}>${icon('folder')}</button><button class="icon-button" data-stack-delete="${a.asset_id}" aria-label="移出 ${escape(a.title)}" title="移出素材栈">${icon('close')}</button></article>`).join(''):'<div class="empty-state"><h2>素材栈为空</h2><button id="stack-browse" class="quiet-button">去素材库添加</button></div>';
  $('#stack-browse')?.addEventListener('click',()=>run(async()=>{if(state.compact)applyDesktopState(await window.mediaDesk.setCompact(false));navigate('library');}));
  $$('#stack-list img').forEach(img=>img.onerror=()=>img.replaceWith(Object.assign(document.createElement('span'),{innerHTML:icon('video')})));
  $$('[data-stack-check]').forEach(c=>c.onchange=()=>{c.checked?state.stackChecked.add(c.dataset.stackCheck):state.stackChecked.delete(c.dataset.stackCheck);c.closest('.stack-card').classList.toggle('selected',c.checked);$('#stack-remove').disabled=!state.stackChecked.size;$('#stack-share').disabled=!state.stackChecked.size;});
  $$('[data-stack-delete]').forEach(b=>b.onclick=()=>run(async()=>{await api(`/api/stack/${state.project}/items/${b.dataset.stackDelete}`,{method:'DELETE'});await loadStack();}));
  $$('[data-stack-open]').forEach(b=>b.onclick=()=>run(()=>window.mediaDesk?window.mediaDesk.reveal({project_id:state.project,asset_ids:[b.dataset.stackOpen]}):api('/api/open-folder',{method:'POST',body:{asset_id:b.dataset.stackOpen}})));
  $$('[data-drag]').forEach(card=>card.ondragstart=e=>{
    e.preventDefault();
    if(!window.mediaDesk){toast('请在素材台桌面窗口中拖出素材；无需开启置顶小窗');return;}
    const id=card.dataset.drag;
    const ids=state.stackChecked.has(id)?[...state.stackChecked]:[id];
    if(ids.length>30){toast('每次最多拖出 30 项');return;}
    window.mediaDesk.startDrag({scope:'stack',project_id:state.project,asset_ids:ids});
  });
}

function applyDesktopState(value){
  document.body.classList.add('desktop');
  state.compact=!!value.compact;
  document.body.classList.toggle('compact',state.compact);
  $('#mini-toolbar').hidden=!state.compact;
  if(state.boot&&state.compact)navigate('stack');
}
if(window.mediaDesk){window.mediaDesk.onState(applyDesktopState);window.mediaDesk.onError(toast);}
$('#compact-button').onclick=()=>run(async()=>{
  if(!state.project)throw new Error('先选择项目');
  if(window.mediaDesk){applyDesktopState(await window.mediaDesk.setCompact(true));}
  else{await api('/api/desktop/open',{method:'POST',body:{project_id:state.project,compact:true}});toast('已打开置顶素材窗');}
});
$('#restore-window').onclick=()=>run(async()=>{applyDesktopState(await window.mediaDesk.setCompact(false));});
$('#close-window').onclick=()=>window.mediaDesk?.close();
$('#batch-stack').onclick=()=>run(()=>addToStack([...state.checked]));
$('#stack-remove').onclick=()=>run(async()=>{for(const id of state.stackChecked)await api(`/api/stack/${state.project}/items/${id}`,{method:'DELETE'});state.stackChecked.clear();await loadStack();});
$('#stack-clear').onclick=()=>run(async()=>{await api(`/api/stack/${state.project}/items`,{method:'DELETE'});state.stackChecked.clear();await loadStack();});
$('#stack-save').onclick=()=>run(()=>saveAssets(state.stackChecked.size?[...state.stackChecked]:state.stack.filter(a=>a.available).map(a=>a.asset_id)));
setInterval(()=>{if(state.boot&&enabled('stack'))run(()=>loadStack(false));},3000);


function videoCard(item){
  const cover=item.cover?'<img src="'+escape(item.cover)+'" alt="" loading="lazy">':icon('video');
  const meta=escape(item.owner||'未知作者')+(item.duration?' · '+duration(item.duration):'');
  return '<article class="video-card"><div class="video-cover">'+cover+'</div><div class="video-copy"><strong>'+escape(item.title)+'</strong><span>'+meta+'</span>'+(item.description?'<small>'+escape(item.description)+'</small>':'')+'</div><a class="icon-button" href="'+escape(item.url||'https://www.bilibili.com/video/'+item.bvid)+'" target="_blank" rel="noreferrer" aria-label="在 B 站打开" title="在 B 站打开">'+icon('external')+'</a><button class="small-primary" data-video-add="'+escape(item.bvid)+'">加入下载栈</button></article>';
}
function bindVideoActions(root){
  root.querySelectorAll('[data-video-add]').forEach(button=>button.onclick=()=>run(async()=>{const result=await api('/api/videos/stack',{method:'POST',body:{bvid:button.dataset.videoAdd}});toast(result.already_exists?'该视频已在下载栈中':'已加入视频下载栈');await loadVideoStack();}));
  root.querySelectorAll('[data-video-remove]').forEach(button=>button.onclick=()=>run(async()=>{await api('/api/videos/stack/'+button.dataset.videoRemove,{method:'DELETE'});state.videoChecked.delete(button.dataset.videoRemove);await loadVideoStack();}));
}
function setVideoMode(mode){state.videoMode=mode;$$('#videos-view [data-video-mode]').forEach(b=>{const current=b.dataset.videoMode===mode;b.classList.toggle('active',current);b.setAttribute('aria-selected',String(current));});$('#bv-search-panel').hidden=mode!=='bv';$('#smart-search-panel').hidden=mode!=='smart';}
async function previewBvid(){const bvid=$('#bvid-input').value.trim();if(!bvid)throw new Error('请输入 BV 号');$('#bvid-preview-result').innerHTML='<span class="subtle">正在获取视频预览…</span>';const item=await api('/api/videos/preview/'+encodeURIComponent(bvid));$('#bvid-preview-result').classList.remove('empty-state');$('#bvid-preview-result').innerHTML=videoCard(item);bindVideoActions($('#bvid-preview-result'));}
async function smartVideoSearch(){const homepage=$('#author-homepage').value.trim(),q=$('#smart-video-query').value.trim();if(!homepage||!q)throw new Error('请填写博主主页链接和要找的视频标题');$('#smart-search-results').innerHTML='<div class="empty-state">正在查找…</div>';const data=await api('/api/videos/smart-search?'+new URLSearchParams({homepage,q}));const items=data.items||[];$('#smart-search-results').innerHTML=items.length?'<div class="video-results">'+items.map(videoCard).join('')+'</div>':'<div class="empty-state">没有找到接近的标题或简介。</div>';bindVideoActions($('#smart-search-results'));}
async function loadVideoStack(){if(!enabled('videos'))return;const data=await api('/api/videos/stack');state.videoStack=data.items||[];const usable=new Set(state.videoStack.filter(i=>i.status!=='downloading').map(i=>i.id));state.videoChecked=new Set([...state.videoChecked].filter(id=>usable.has(id)));$('#video-stack-count').textContent=state.videoStack.length+' 项';$('#video-download-selected').disabled=!state.videoChecked.size||!state.project;$('#video-stack-list').innerHTML=state.videoStack.length?state.videoStack.map(item=>{const cover=item.cover?'<img src="'+escape(item.cover)+'" alt="" loading="lazy">':icon('video');const label=({ready:'待下载',queued:'已提交',downloading:'下载中',done:'已完成',failed:'失败'})[item.status]||item.status;return '<article class="video-stack-card '+(state.videoChecked.has(item.id)?'selected':'')+'"><label class="stack-check"><input type="checkbox" data-video-check="'+item.id+'" '+(state.videoChecked.has(item.id)?'checked':'')+' '+(item.status==='downloading'?'disabled':'')+'></label><div class="video-cover small">'+cover+'</div><div class="video-copy"><strong>'+escape(item.title)+'</strong><span>'+escape(item.owner||'未知作者')+' · '+escape(item.bvid)+'</span>'+(item.error?'<small class="video-error">'+escape(item.error)+'</small>':'')+'</div><span class="video-status">'+label+'</span><button class="icon-button" data-video-remove="'+item.id+'" '+(item.status==='downloading'?'disabled':'')+' aria-label="移出下载栈">'+icon('close')+'</button></article>';}).join(''):'<div class="empty-state"><h2>视频下载栈为空</h2><p>输入 BV 号，或从指定博主的视频中查找。</p></div>';$$('[data-video-check]').forEach(c=>c.onchange=()=>{c.checked?state.videoChecked.add(c.dataset.videoCheck):state.videoChecked.delete(c.dataset.videoCheck);$('#video-download-selected').disabled=!state.videoChecked.size||!state.project;c.closest('.video-stack-card').classList.toggle('selected',c.checked);});bindVideoActions($('#video-stack-list'));}
$$('#videos-view [data-video-mode]').forEach(b=>b.onclick=()=>setVideoMode(b.dataset.videoMode));
$('#bvid-preview').onclick=()=>run(previewBvid);$('#bvid-input').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();run(previewBvid);}};$('#smart-video-search').onclick=()=>run(smartVideoSearch);$('#smart-video-query').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();run(smartVideoSearch);}};$('#video-download-selected').onclick=()=>run(async()=>{if(!state.project)throw new Error('请先新建或选择视频项目');const result=await api('/api/videos/download',{method:'POST',body:{project_id:state.project,item_ids:[...state.videoChecked]}});state.jobs.set(result.job_id,'queued');toast('已开始使用 BBDown 下载到当前项目的视频文件夹');await loadVideoStack();navigate('history');});

$('#detail-backdrop').onclick=closeDetail;
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDetail();});
$('#collapse-sidebar').innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16m7-12-3 4 3 4"/></svg>';
$('#collapse-sidebar').onclick=()=>{const collapsed=document.body.classList.toggle('nav-collapsed');$('#collapse-sidebar').setAttribute('aria-label',collapsed?'展开导航':'收起导航');};
if(window.mediaDesk){$('.desktop-controls').hidden=false;$('#minimize-desktop').onclick=()=>window.mediaDesk.minimize();$('#close-desktop').onclick=()=>window.mediaDesk.close();}


$('#stack-share').onclick=()=>run(async()=>{
  if(!state.sharedProject||!state.stackChecked.size)return;
  await api(`/api/stack/${state.sharedProject}/items`,{method:'POST',body:{asset_ids:[...state.stackChecked]}});
  toast('已加入系列共享素材，同系列各期均可使用');await loadStack();
});
$('#stack-restore-shared').onclick=()=>run(async()=>{
  await api(`/api/stack/${state.project}/restore-shared`,{method:'POST'});await loadStack();toast('已恢复本期隐藏的共享素材');
});



$('#library-sort').value=state.librarySort;
$('#stack-sort').value=state.stackSort;
$('#library-sort').onchange=()=>{state.librarySort=$('#library-sort').value;state.page=1;run(loadAssets);};
$('#stack-sort').onchange=()=>{state.stackSort=$('#stack-sort').value;run(()=>loadStack());};
$('#jump-page').onchange=()=>navigate($('#jump-page').value);

export function createProjectPicker({state, api, escape, icon, selectProject, toast}) {
  const $ = q => document.querySelector(q);
  const trigger = $('#project-trigger'), panel = $('#project-popover'), tree = $('#project-tree');
  const dialog = $('#project-dialog');
  let expanded = new Set(), query = '', mode = '', saving = false;
  try { expanded = new Set(JSON.parse(localStorage.getItem('media-desk-expanded-series') || '[]')); } catch {}
  const current = () => state.boot?.projects.find(p => p.id === state.project);
  const groupOptions = (selected='') => '<option value="">独立项目</option>' + (state.boot?.series || []).map(s => `<option value="${s.id}" ${s.id===selected?'selected':''}>${escape(s.name)}</option>`).join('');
  const label = p => p.shared ? `${p.series_name} / 共享素材` : p.series_name ? `${p.series_name} / ${p.name}` : p.name;

  function close(focus=true) { panel.hidden=true; trigger.setAttribute('aria-expanded','false'); if(focus)trigger.focus(); }
  function render() {
    const project = current();
    trigger.innerHTML = `<span>${escape(project ? label(project) : '选择系列或项目')}</span><span aria-hidden="true">⌄</span>`;
    trigger.title = project?.path || '选择系列或项目';
    trigger.setAttribute('aria-label',project ? `选择系列或项目，当前 ${label(project)}` : '选择系列或项目');
    if(project?.series_id)expanded.add(project.series_id);
    renderTree();
  }
  function renderTree() {
    const projects = state.boot?.projects || [], groups = state.boot?.series || [];
    const match = p => !query || `${p.name} ${p.series_name || ''}`.toLocaleLowerCase().includes(query);
    const leaf = (p,parent) => `<li role="none"><button type="button" role="treeitem" tabindex="-1" aria-selected="${state.project===p.id}" data-project="${p.id}" data-parent="${parent}" title="${escape(p.path)}">${icon(p.shared?'stack':'folder')}<span>${escape(p.name)}</span>${p.archived?'<small>已归档</small>':''}${state.project===p.id?icon('check'):''}</button></li>`;
    const branch = (id,name,items) => {
      const visible = items.filter(match);
      if(query && !visible.length)return '';
      const open = !!query || expanded.has(id);
      return `<li role="none"><button type="button" role="treeitem" tabindex="-1" aria-expanded="${open}" data-branch="${id}"><span class="tree-chevron" aria-hidden="true">${open?'⌄':'›'}</span>${icon('folder')}<span>${escape(name)}</span><small>${items.filter(p=>!p.shared).length}</small></button><ul role="group" ${open?'':'hidden'}>${visible.map(p=>leaf(p,id)).join('')}${!visible.length?'<li role="none" class="tree-empty">暂无项目</li>':''}</ul></li>`;
    };
    tree.innerHTML = groups.map(s=>branch(s.id,s.name,projects.filter(p=>p.series_id===s.id).sort((a,b)=>Number(b.shared)-Number(a.shared)))).join('')
      + branch('standalone','独立项目',projects.filter(p=>!p.series_id&&!p.archived))
      + branch('archived','已归档项目',projects.filter(p=>!p.series_id&&p.archived));
    if(!tree.querySelector('[role=treeitem]'))tree.innerHTML='<li role="none" class="tree-empty">没有匹配的项目</li>';
    const first = tree.querySelector('[role=treeitem]'); if(first)first.tabIndex=0;
  }
  const visibleNodes = () => [...tree.querySelectorAll('[role=treeitem]')].filter(el=>!el.closest('[hidden]'));
  const focusNode = el => {if(!el)return;tree.querySelectorAll('[role=treeitem]').forEach(n=>n.tabIndex=n===el?0:-1);el.focus();};
  function toggle(branch, open) {
    const id=branch.dataset.branch;
    if(open)expanded.add(id);else expanded.delete(id);
    localStorage.setItem('media-desk-expanded-series',JSON.stringify([...expanded]));
    branch.setAttribute('aria-expanded',String(open));branch.querySelector('.tree-chevron').textContent=open?'⌄':'›';branch.nextElementSibling.hidden=!open;
  }
  trigger.onclick=()=>{if(!panel.hidden){close();return;}query='';$('#project-search').value='';renderTree();panel.hidden=false;trigger.setAttribute('aria-expanded','true');$('#project-search').focus();};
  $('#project-search').oninput=e=>{query=e.target.value.trim().toLocaleLowerCase();renderTree();};
  panel.addEventListener('keydown',e=>{
    if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();}
    if(e.target.id==='project-search'&&e.key==='ArrowDown'){e.preventDefault();focusNode(visibleNodes()[0]);}
  });
  tree.onclick=async e=>{
    const branch=e.target.closest('[data-branch]');if(branch){toggle(branch,branch.getAttribute('aria-expanded')!=='true');focusNode(branch);return;}
    const leaf=e.target.closest('[data-project]');if(!leaf)return;
    close();try{await selectProject(leaf.dataset.project);render();}catch(err){toast(err.message);}
  };
  tree.onkeydown=e=>{
    const node=e.target.closest('[role=treeitem]');if(!node)return;
    const nodes=visibleNodes(),index=nodes.indexOf(node);
    if(!['ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
    e.preventDefault();
    if(e.key==='ArrowDown')focusNode(nodes[Math.min(index+1,nodes.length-1)]);
    if(e.key==='ArrowUp')focusNode(nodes[Math.max(index-1,0)]);
    if(e.key==='Home')focusNode(nodes[0]);
    if(e.key==='End')focusNode(nodes.at(-1));
    if(e.key==='ArrowRight'&&node.dataset.branch){if(node.getAttribute('aria-expanded')==='false')toggle(node,true);else focusNode(node.nextElementSibling.querySelector('[role=treeitem]'));}
    if(e.key==='ArrowLeft'){if(node.dataset.branch&&node.getAttribute('aria-expanded')==='true')toggle(node,false);else if(node.dataset.parent)focusNode(tree.querySelector(`[data-branch="${node.dataset.parent}"]`));}
  };
  document.addEventListener('click',e=>{if(!panel.hidden&&!e.target.closest('.project-picker'))close(false);});
  panel.addEventListener('focusout',()=>setTimeout(()=>{if(!panel.hidden&&!panel.contains(document.activeElement)&&document.activeElement!==trigger)close(false);},0));

  async function refresh() {const data=await api('/api/series');state.boot.projects=data.projects;state.boot.series=data.series;if(data.sources)state.boot.sources=data.sources;render();}
  function show(modeValue) {
    mode=modeValue;close(false);$('#project-form-error').textContent='';
    $('#project-dialog-title').textContent={project:'新建项目',series:'新建系列',organize:'整理系列'}[mode];
    $('#project-name-field').hidden=mode==='organize';$('#project-name-label').textContent=mode==='series'?'系列名称':'项目名称';$('#project-name').value='';
    $('#project-series-field').hidden=mode==='series';$('#project-series-choice').innerHTML=groupOptions(current()?.series_id);
    $('#series-members-field').hidden=mode!=='organize';$('#rename-series').hidden=mode!=='organize';
    $('#series-members').innerHTML=state.boot.projects.filter(p=>!p.shared).map(p=>`<label><input type="checkbox" value="${p.id}" ${p.id===state.project?'checked':''}><span>${escape(p.name)}<small>${escape(p.series_name||'独立项目')}</small></span></label>`).join('');
    $('#project-form-submit').textContent=mode==='organize'?'应用到选中项目':'创建';
    dialog.showModal();(mode==='organize'?$('#project-series-choice'):$('#project-name')).focus();
  }
  $('#tree-new-project').onclick=()=>show('project');$('#tree-new-series').onclick=()=>show('series');$('#tree-organize').onclick=()=>show('organize');
  $('#close-project-dialog').onclick=()=>dialog.close();
  $('#project-dialog-cancel').onclick=()=>dialog.close();
  $('#rename-series').onclick=()=>{
    const sid=$('#project-series-choice').value;if(!sid){$('#project-form-error').textContent='先选择要更名的系列';return;}
    $('#project-name-field').hidden=false;$('#project-name-label').textContent='系列名称';$('#project-name').value=state.boot.series.find(s=>s.id===sid).name;$('#project-name').focus();
  };
  $('#project-series-choice').onchange=()=>{if(mode==='organize')$('#project-name-field').hidden=true;};
  $('#project-form').onsubmit=async e=>{
    e.preventDefault();if(saving)return;saving=true;$('#project-form-submit').disabled=true;$('#project-form-error').textContent='';
    try {
      let selected=state.project;
      if(!$('#project-name-field').hidden&&!$('#project-name').value.trim())throw new Error(mode==='project'?'请输入项目名称':'请输入系列名称');
      if(mode==='project'){
        const item=await api('/api/projects',{method:'POST',body:{name:$('#project-name').value.trim(),series_id:$('#project-series-choice').value}});selected=item.id;
      } else if(mode==='series'){
        const group=await api('/api/series',{method:'POST',body:{name:$('#project-name').value.trim()}});expanded.add(group.id);selected=group.shared_project_id;
      } else {
        const ids=[...$('#series-members').querySelectorAll('input:checked')].map(c=>c.value), sid=$('#project-series-choice').value;
        if(!ids.length&&$('#project-name-field').hidden)throw new Error('请选择要归入系列的项目');
        if(!$('#project-name-field').hidden)await api(`/api/series/${sid}`,{method:'PATCH',body:{name:$('#project-name').value.trim()}});
        if(ids.length)await api('/api/series/membership',{method:'POST',body:{project_ids:ids,series_id:sid}});
      }
      await refresh();await selectProject(selected);dialog.close();toast(mode==='organize'?'系列已更新':mode==='series'?'系列已创建':'项目已创建');
    } catch(err){$('#project-form-error').textContent=err.message;}
    finally{saving=false;$('#project-form-submit').disabled=false;}
  };
  dialog.addEventListener('close',()=>trigger.focus());
  return {render,refresh,openNewProject:()=>show('project')};
}

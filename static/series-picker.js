export function createProjectPicker({ state, api, escape, icon, selectProject, toast }) {
  const $ = q => document.querySelector(q);
  const trigger = $('#project-trigger'), panel = $('#project-popover'), tree = $('#project-tree');
  const dialog = $('#project-dialog');
  let expanded = new Set(), query = '', mode = '', saving = false;
  try { expanded = new Set(JSON.parse(localStorage.getItem('media-desk-expanded-series') || '[]')); } catch { }
  const current = () => state.boot?.projects.find(p => p.id === state.project);
  const groupOptions = (selected = '') => '<option value="">独立项目</option>' + (state.boot?.series || []).map(s => `<option value="${s.id}" ${s.id === selected ? 'selected' : ''}>${escape(s.name)}${s.archived ? '（已归档）' : ''}</option>`).join('');
  const label = p => p.shared ? `${p.series_name} / 共享素材` : p.series_name ? `${p.series_name} / ${p.name}` : p.name;

  function close(focus = true) { panel.hidden = true; trigger.setAttribute('aria-expanded', 'false'); if (focus) trigger.focus(); }
  function render() {
    const project = current();
    trigger.innerHTML = `<span>${escape(project ? label(project) : '选择系列或项目')}</span><span aria-hidden="true">⌄</span>`;
    trigger.title = project?.path || '选择系列或项目';
    trigger.setAttribute('aria-label', project ? `选择系列或项目，当前 ${label(project)}` : '选择系列或项目');
    if (project?.series_id) expanded.add(project.series_id);
    renderTree();
  }
  function renderTree() {
    const projects = state.boot?.projects || [], groups = state.boot?.series || [];
    const match = p => !query || `${p.name} ${p.series_name || ''}`.toLocaleLowerCase().includes(query);
    const leaf = (p, parent) => {
      const hint = p.archived ? `<small>${parent === 'archived' && p.series_name ? escape(p.series_name) + ' · ' : ''}已归档</small>` : '';
      return `<li role="none"><button type="button" role="treeitem" tabindex="-1" aria-selected="${state.project === p.id}" data-project="${p.id}" data-parent="${parent}" title="${escape(p.path)}">${icon(p.shared ? 'stack' : 'folder')}<span>${escape(p.name)}</span>${hint}${state.project === p.id ? icon('check') : ''}</button></li>`;
    };
    const branch = (id, name, items, archived = false) => {
      const visible = items.filter(match);
      if (query && !visible.length) return '';
      const open = !!query || expanded.has(id);
      return `<li role="none"><button type="button" role="treeitem" tabindex="-1" aria-expanded="${open}" data-branch="${id}"><span class="tree-chevron" aria-hidden="true">${open ? '⌄' : '›'}</span>${icon('folder')}<span>${escape(name)}</span>${archived ? '<small>已归档</small>' : ''}<small>${items.filter(p => !p.shared).length}</small></button><ul role="group" ${open ? '' : 'hidden'}>${visible.map(p => leaf(p, id)).join('')}${!visible.length ? '<li role="none" class="tree-empty">暂无项目</li>' : ''}</ul></li>`;
    };
    const seriesBranch = (s, archived = false) => branch(s.id, s.name, projects.filter(p => p.series_id === s.id && !p.archived).sort((a, b) => Number(b.shared) - Number(a.shared)), archived);
    tree.innerHTML = groups.filter(s => !s.archived).map(s => seriesBranch(s)).join('')
      + branch('standalone', '独立项目', projects.filter(p => !p.series_id && !p.archived))
      + branch('archived', '已归档项目', projects.filter(p => p.archived))
      + groups.filter(s => s.archived).map(s => seriesBranch(s, true)).join('');
    if (!tree.querySelector('[role=treeitem]')) tree.innerHTML = '<li role="none" class="tree-empty">没有匹配的项目</li>';
    const first = tree.querySelector('[role=treeitem]'); if (first) first.tabIndex = 0;
  }
  const visibleNodes = () => [...tree.querySelectorAll('[role=treeitem]')].filter(el => !el.closest('[hidden]'));
  const focusNode = el => { if (!el) return; tree.querySelectorAll('[role=treeitem]').forEach(n => n.tabIndex = n === el ? 0 : -1); el.focus(); };
  function toggle(branch, open) {
    const id = branch.dataset.branch;
    if (open) expanded.add(id); else expanded.delete(id);
    localStorage.setItem('media-desk-expanded-series', JSON.stringify([...expanded]));
    branch.setAttribute('aria-expanded', String(open)); branch.querySelector('.tree-chevron').textContent = open ? '⌄' : '›'; branch.nextElementSibling.hidden = !open;
  }
  trigger.onclick = () => { if (!panel.hidden) { close(); return; } query = ''; $('#project-search').value = ''; renderTree(); panel.hidden = false; trigger.setAttribute('aria-expanded', 'true'); $('#project-search').focus(); };
  $('#project-search').oninput = e => { query = e.target.value.trim().toLocaleLowerCase(); renderTree(); };
  panel.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    if (e.target.id === 'project-search' && e.key === 'ArrowDown') { e.preventDefault(); focusNode(visibleNodes()[0]); }
  });
  tree.onclick = async e => {
    const branch = e.target.closest('[data-branch]'); if (branch) { toggle(branch, branch.getAttribute('aria-expanded') !== 'true'); focusNode(branch); return; }
    const leaf = e.target.closest('[data-project]'); if (!leaf) return;
    close(); try { await selectProject(leaf.dataset.project); render(); } catch (err) { toast(err.message); }
  };
  tree.onkeydown = e => {
    const node = e.target.closest('[role=treeitem]'); if (!node) return;
    const nodes = visibleNodes(), index = nodes.indexOf(node);
    if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    if (e.key === 'ArrowDown') focusNode(nodes[Math.min(index + 1, nodes.length - 1)]);
    if (e.key === 'ArrowUp') focusNode(nodes[Math.max(index - 1, 0)]);
    if (e.key === 'Home') focusNode(nodes[0]);
    if (e.key === 'End') focusNode(nodes.at(-1));
    if (e.key === 'ArrowRight' && node.dataset.branch) { if (node.getAttribute('aria-expanded') === 'false') toggle(node, true); else focusNode(node.nextElementSibling.querySelector('[role=treeitem]')); }
    if (e.key === 'ArrowLeft') { if (node.dataset.branch && node.getAttribute('aria-expanded') === 'true') toggle(node, false); else if (node.dataset.parent) focusNode(tree.querySelector(`[data-branch="${node.dataset.parent}"]`)); }
  };
  document.addEventListener('click', e => { if (!panel.hidden && !e.target.closest('.project-picker')) close(false); });
  panel.addEventListener('focusout', () => setTimeout(() => { if (!panel.hidden && !panel.contains(document.activeElement) && document.activeElement !== trigger) close(false); }, 0));

  async function refresh() { const data = await api('/api/series'); state.boot.projects = data.projects; state.boot.series = data.series; if (data.sources) state.boot.sources = data.sources; render(); }
  const selectedSeries = () => (state.boot?.series || []).find(s => s.id === $('#project-series-choice').value);
  function syncSeriesButtons() {
    const organize = mode === 'organize';
    const group = selectedSeries();
    $('#rename-series').hidden = !organize;
    $('#archive-series').hidden = !organize;
    $('#delete-series').hidden = !organize;
    $('#archive-series').textContent = group?.archived ? '取消归档' : '归档系列';
  }
  const selectedProject = () => (state.boot?.projects || []).find(p => p.id === $('#project-target-choice').value);
  function syncProjectButtons() {
    const manage = mode === 'manage';
    const project = selectedProject();
    for (const id of ['rename-project', 'archive-project', 'delete-project']) $(`#${id}`).hidden = !manage;
    if (!manage) return;
    $('#archive-project').textContent = project?.archived ? '取消归档' : '归档项目';
    const remove = $('#delete-project');
    remove.disabled = !project?.archived;   // 必须先归档才能删除
    remove.title = project?.archived ? '目录会移入回收站，可以还原' : '需要先归档才能删除';
  }
  function fillProjectTarget(selectedId) {
    const list = (state.boot?.projects || []).filter(p => !p.shared);
    $('#project-target-choice').innerHTML = list.map(p =>
      `<option value="${p.id}" ${p.id === (selectedId || state.project) ? 'selected' : ''}>${escape(p.name)}${p.archived ? '（已归档）' : ''}</option>`).join('');
    syncProjectButtons();
  }
  function show(modeValue) {
    mode = modeValue; close(false); $('#project-form-error').textContent = '';
    $('#project-dialog-title').textContent = { project: '新建项目', series: '新建系列', organize: '整理系列', manage: '管理项目' }[mode];
    $('#project-name-field').hidden = mode === 'organize' || mode === 'manage'; $('#project-name-label').textContent = mode === 'series' ? '系列名称' : '项目名称'; $('#project-name').value = '';
    $('#project-series-field').hidden = mode === 'series' || mode === 'manage'; $('#project-series-choice').innerHTML = groupOptions(current()?.series_id);
    $('#project-target-field').hidden = mode !== 'manage';
    $('#series-members-field').hidden = mode !== 'organize'; syncSeriesButtons();
    $('#series-members').innerHTML = state.boot.projects.filter(p => !p.shared).map(p => `<label><input type="checkbox" value="${p.id}" ${p.id === state.project ? 'checked' : ''}><span>${escape(p.name)}<small>${escape(p.series_name || '独立项目')}</small></span></label>`).join('');
    $('#project-form-submit').textContent = mode === 'organize' ? '应用到选中项目' : '创建';
    $('#project-form-submit').hidden = mode === 'manage';
    if (mode === 'manage') fillProjectTarget(); else syncProjectButtons();
    dialog.showModal();
    if (mode === 'manage') $('#project-target-choice').focus();
    else (mode === 'organize' ? $('#project-series-choice') : $('#project-name')).focus();
  }
  $('#tree-new-project').onclick = () => show('project'); $('#tree-new-series').onclick = () => show('series'); $('#tree-organize').onclick = () => show('organize'); $('#tree-manage').onclick = () => show('manage');
  $('#project-target-choice').onchange = () => syncProjectButtons();
  $('#rename-project').onclick = async () => {
    const project = selectedProject(); if (!project) { $('#project-form-error').textContent = '先选择项目'; return; }
    const name = window.prompt('项目新名称', project.name);
    if (name === null) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed === project.name) return;
    $('#project-form-error').textContent = '';
    try {
      const updated = await api(`/api/projects/${project.id}`, { method: 'PATCH', body: { name: trimmed } });
      await refresh(); fillProjectTarget(updated.id);
      if (project.id === state.project) await selectProject(updated.id);
      toast('项目已重命名，系列归属和素材栈都跟着保留');
    } catch (err) { $('#project-form-error').textContent = err.message; }
  };
  $('#archive-project').onclick = async () => {
    const project = selectedProject(); if (!project) { $('#project-form-error').textContent = '先选择项目'; return; }
    $('#project-form-error').textContent = '';
    try {
      const updated = await api(`/api/projects/${project.id}`, { method: 'PATCH', body: { archived: !project.archived } });
      await refresh(); fillProjectTarget(updated.id);
      if (project.id === state.project) await selectProject(updated.id);
      toast(project.archived ? '项目已取消归档' : '项目已归档，随时可以取消');
    } catch (err) { $('#project-form-error').textContent = err.message; }
  };
  $('#delete-project').onclick = async () => {
    const project = selectedProject(); if (!project) { $('#project-form-error').textContent = '先选择项目'; return; }
    if (!project.archived) { $('#project-form-error').textContent = '请先归档项目再删除'; return; }
    if (!window.confirm(`删除项目「${project.name}」？\n\n整个项目目录会移入回收站，可以从回收站还原。`)) return;
    $('#project-form-error').textContent = '';
    try {
      const result = await api(`/api/projects/${project.id}`, { method: 'DELETE' });
      await refresh();
      if (project.id === state.project) await selectProject(state.boot.projects[0]?.id || '');
      fillProjectTarget();
      dialog.close();
      toast(result.recycled ? '项目已删除，目录已移入回收站' : '项目记录已删除，但目录没能移入回收站，请手动处理');
    } catch (err) { $('#project-form-error').textContent = err.message; }
  };
  $('#close-project-dialog').onclick = () => dialog.close();
  $('#project-dialog-cancel').onclick = () => dialog.close();
  $('#rename-series').onclick = () => {
    const sid = $('#project-series-choice').value; if (!sid) { $('#project-form-error').textContent = '先选择要更名的系列'; return; }
    $('#project-name-field').hidden = false; $('#project-name-label').textContent = '系列名称'; $('#project-name').value = state.boot.series.find(s => s.id === sid).name; $('#project-name').focus();
  };
  $('#project-series-choice').onchange = () => { if (mode === 'organize') $('#project-name-field').hidden = true; syncSeriesButtons(); };
  $('#archive-series').onclick = async () => {
    const group = selectedSeries(); if (!group) { $('#project-form-error').textContent = '先选择要归档的系列'; return; }
    $('#project-form-error').textContent = '';
    try {
      await api(`/api/series/${group.id}`, { method: 'PATCH', body: { archived: !group.archived } });
      await refresh(); syncSeriesButtons();
      toast(group.archived ? '系列已取消归档' : '系列已归档，共享素材目录和项目都保留');
    } catch (err) { $('#project-form-error').textContent = err.message; }
  };
  $('#delete-series').onclick = async () => {
    const group = selectedSeries(); if (!group) { $('#project-form-error').textContent = '先选择要删除的系列'; return; }
    const members = state.boot.projects.filter(p => p.series_id === group.id && !p.shared).length;
    if (!window.confirm(`删除系列「${group.name}」？\n\n· ${members} 个项目会变成独立项目（文件不动）\n· 共享素材目录会移入回收站，可以从回收站还原`)) return;
    $('#project-form-error').textContent = '';
    try {
      const result = await api(`/api/series/${group.id}`, { method: 'DELETE' });
      const droppedShared = group.shared_project_id === state.project;
      await refresh();
      if (droppedShared) await selectProject(state.boot.projects[0]?.id || '');
      dialog.close();
      toast(result.recycled ? '系列已删除，共享素材目录已移入回收站' : '系列记录已删除，但共享目录没能移入回收站，请手动处理');
    } catch (err) { $('#project-form-error').textContent = err.message; }
  };
  $('#project-form').onsubmit = async e => {
    e.preventDefault(); if (saving) return; saving = true; $('#project-form-submit').disabled = true; $('#project-form-error').textContent = '';
    try {
      let selected = state.project;
      if (!$('#project-name-field').hidden && !$('#project-name').value.trim()) throw new Error(mode === 'project' ? '请输入项目名称' : '请输入系列名称');
      if (mode === 'project') {
        const item = await api('/api/projects', { method: 'POST', body: { name: $('#project-name').value.trim(), series_id: $('#project-series-choice').value } }); selected = item.id;
      } else if (mode === 'series') {
        const group = await api('/api/series', { method: 'POST', body: { name: $('#project-name').value.trim() } }); expanded.add(group.id); selected = group.shared_project_id;
      } else {
        const ids = [...$('#series-members').querySelectorAll('input:checked')].map(c => c.value), sid = $('#project-series-choice').value;
        if (!ids.length && $('#project-name-field').hidden) throw new Error('请选择要归入系列的项目');
        if (!$('#project-name-field').hidden) await api(`/api/series/${sid}`, { method: 'PATCH', body: { name: $('#project-name').value.trim() } });
        if (ids.length) await api('/api/series/membership', { method: 'POST', body: { project_ids: ids, series_id: sid } });
      }
      await refresh(); await selectProject(selected); dialog.close(); toast(mode === 'organize' ? '系列已更新' : mode === 'series' ? '系列已创建' : '项目已创建');
    } catch (err) { $('#project-form-error').textContent = err.message; }
    finally { saving = false; $('#project-form-submit').disabled = false; }
  };
  dialog.addEventListener('close', () => trigger.focus());
  return { render, refresh, openNewProject: () => show('project') };
}

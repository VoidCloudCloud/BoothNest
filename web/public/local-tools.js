export function initLocalTools({ api, icon, escape: esc, bytes, language, onChanged }) {
  const dialog = document.querySelector('#local-tools-dialog');
  const l = (zh, en) => language() === 'zh' ? zh : en;
  const $ = selector => dialog.querySelector(selector);
  const s = { tab: 'stats', q: '', status: 'all', sort: 'size', page: 1, selected: new Set(), stats: null, list: null, check: null, dimension: 'categories', checkPage: 1, loading: false, request: 0 };
  let poll, searchTimer;
  const labels = () => ({ all: l('全部条目', 'All entries'), matched: l('已识别', 'Matched'), unidentified: l('未识别', 'Unidentified'), ignored: l('非商品', 'Not products'), manual: l('网页已修正', 'Web corrections'), multiple: l('同商品多条目', 'Multiple entries') });
  const post = (url, body) => api(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  function params() { return new URLSearchParams({ q: s.q, status: s.status, sort: s.sort, page: s.page, pageSize: 50 }); }
  function feedback(message, error = false) { const el = $('#tools-feedback'); el.textContent = message; el.classList.toggle('error', error); }
  function tab() {
    for (const el of dialog.querySelectorAll('[data-tool-tab]')) { const active = el.dataset.toolTab === s.tab; el.classList.toggle('selected', active); el.setAttribute('aria-selected', String(active)); }
    for (const el of dialog.querySelectorAll('[data-tool-panel]')) el.hidden = el.dataset.toolPanel !== s.tab;
  }
  function shell() {
    dialog.innerHTML = `<header class="tools-heading"><div><span class="tools-eyebrow">BOOTHNEST · LOCAL LIBRARY</span><h1>${l('本地管理', 'Local management')}</h1><p>${l('统计、整理归属与核对文件，集中在这里。', 'Inventory statistics, identification and file verification.')}</p></div><button class="icon-btn" data-tool-action="close" aria-label="${l('关闭', 'Close')}">${icon('x')}</button></header>
      <nav class="tools-tabs" role="tablist"><button class="btn" role="tab" data-tool-tab="stats">${l('库存统计', 'Statistics')}</button><button class="btn" role="tab" data-tool-tab="entries">${l('条目与识别', 'Entries & matching')}</button><button class="btn" role="tab" data-tool-tab="check">${l('相同文件核对', 'Identical files')}</button><button class="text-button" data-tool-action="reload">${icon('refresh')}${l('刷新快照', 'Reload snapshot')}</button></nav>
      <div class="tools-body"><p id="tools-feedback" class="tools-feedback" role="status" aria-live="polite"></p><div id="tools-summary" class="tools-summary"></div>
      <section data-tool-panel="stats"><div class="tools-section-heading"><h2>${l('库存分布', 'Inventory breakdown')}</h2><select id="tools-dimension" aria-label="${l('统计维度', 'Breakdown dimension')}">${[['categories', '分类', 'Category'], ['shops', '店铺', 'Shop'], ['types', '条目类型', 'Entry type'], ['avatars', '适配角色', 'Avatar'], ['years', '商品发布年份', 'Publication year']].map(([v, zh, en]) => `<option value="${v}">${l(zh, en)}</option>`).join('')}</select></div><p class="feature-note">${l('按最近库存计算逻辑大小；多角色商品可出现在多个角色中。本地修改时间不代表购买或下载日期。', 'Logical sizes from the latest inventory. Multi-avatar products appear in each avatar group. Modified time is not a purchase or download date.')}</p><div id="tools-breakdown"></div></section>
      <section data-tool-panel="entries" hidden><div class="tools-filters"><input id="tools-query" type="search" aria-label="${l('搜索本地条目', 'Search local entries')}" placeholder="${l('搜索路径、商品名、店铺或 ID…', 'Search path, title, shop or ID…')}" value="${esc(s.q)}"><select id="tools-status" aria-label="${l('识别状态', 'Identification status')}">${Object.entries(labels()).map(([value, label]) => `<option value="${value}"${value === s.status ? ' selected' : ''}>${label}</option>`).join('')}</select><select id="tools-sort" aria-label="${l('条目排序', 'Entry sort')}"><option value="size">${l('体积最大', 'Largest size')}</option><option value="mtime">${l('最近修改', 'Recently modified')}</option><option value="name">${l('路径名称', 'Path name')}</option></select><a class="btn" id="tools-export" href="/api/local/export.csv" download>${icon('download')}CSV</a></div>
      <div class="tools-batch"><span id="tools-selected"></span><select id="tools-action" aria-label="${l('修正操作', 'Correction action')}"><option value="bind">${l('绑定商品', 'Bind product')}</option><option value="unmatch">${l('取消归属', 'Unmatch')}</option><option value="ignore">${l('标记非商品', 'Not a product')}</option><option value="reset">${l('恢复源库结果', 'Restore source result')}</option></select><input id="tools-product-id" placeholder="${l('BOOTH 商品 ID 或链接', 'BOOTH product ID or URL')}" aria-label="${l('绑定的商品', 'Product to bind')}"><button class="btn primary" id="tools-apply" data-tool-action="apply">${l('应用到所选', 'Apply to selected')}</button></div>
      <p class="feature-note">${l('修正仅在当前网页生效并单独保存；原 BoothNest 库保持原样。恢复会移除网页规则。同商品多条目可能是不同版本。', 'Web corrections are saved separately. Restore removes the web rule and returns to the BoothNest result. Multiple entries may be different versions.')}</p>
      <div class="tools-table-wrap" tabindex="0" aria-label="${l('本地条目表，可水平滚动', 'Local entries, horizontally scrollable')}"><table class="tools-table"><thead><tr><th><input id="tools-select-page" type="checkbox" aria-label="${l('选择当前页', 'Select current page')}"></th><th>${l('本地条目 / 相对路径', 'Entry / relative path')}</th><th>${l('商品 / 归属状态', 'Product / identification')}</th><th>${l('大小 / 类型', 'Size / type')}</th><th>${l('操作', 'Actions')}</th></tr></thead><tbody id="tools-rows"></tbody></table></div><div class="tools-pagination" id="tools-pages"></div><section id="tools-evidence" class="tools-evidence" hidden></section></section>
      <section data-tool-panel="check" hidden><div class="tools-section-heading"><h2>${l('SHA-256 内容核对', 'SHA-256 content verification')}</h2><div class="tools-controls"><button class="btn primary" data-tool-action="check-start">${l('开始核对', 'Start check')}</button><button class="btn" data-tool-action="check-stop">${l('取消本次', 'Cancel check')}</button><a class="btn" id="tools-check-export" href="/api/local/check.csv" download>${icon('download')}CSV</a></div></div><p class="feature-note">${l('先枚举当前库存内的文件，只读取同大小候选的内容；大库与 NAS 可能较慢，可随时取消。额外逻辑大小扣除硬链接，不代表一定可释放的磁盘空间。结果包含核对时间，请自行判断文件用途。', 'Enumerates inventory files, then hashes candidates of equal size. Large libraries and NAS checks can take time; cancellation is available. Extra logical bytes exclude hardlinks and do not promise reclaimable disk space.')}</p><div id="tools-check-state" role="status" aria-live="polite"></div><div id="tools-check-result"></div></section>
      <footer class="tools-footer">${l('依据 BoothNest 最近扫描 · 新增或移动文件后先在 BoothNest 重新扫描', 'Based on the latest BoothNest scan. Rescan in BoothNest after adding or moving files.')}<button class="text-button" data-action="data">${l('本地库连接设置', 'Library connection settings')}</button></footer></div>`;
    $('#tools-sort').value = s.sort; $('#tools-dimension').value = s.dimension; tab();
  }
  function summary() {
    const counts = s.list.counts, stats = s.stats;
    $('#tools-summary').innerHTML = [[l('本地商品', 'Products'), stats.products, 'matched'], [l('库存条目', 'Entries'), counts.all, 'all'], [l('未识别', 'Unidentified'), counts.unidentified, 'unidentified'], [l('多份条目', 'Multiple entries'), counts.multiple, 'multiple'], [l('逻辑总大小', 'Logical size'), bytes(stats.bytes), null]].map(([label, value, status]) => `<button class="tools-metric"${status ? ` data-tool-status="${status}"` : ' disabled'}><span>${label}</span><strong>${esc(value)}</strong></button>`).join('');
    if (s.list.curationError) feedback(s.list.curationError, true);
  }
  function breakdown() {
    const groups = s.stats?.[s.dimension] || [], max = Math.max(1, ...groups.map(g => g.bytes));
    $('#tools-breakdown').innerHTML = `<div class="tools-distribution">${groups.slice(0, 20).map(g => `<div class="tools-distribution-row"><span title="${esc(g.label)}">${esc(g.label)}</span><meter min="0" max="${max}" value="${g.bytes}">${g.bytes}</meter><span>${g.products} ${l('商品', 'products')} / ${g.entries} ${l('条目', 'entries')}</span><strong>${bytes(g.bytes)}</strong></div>`).join('') || `<p class="tools-empty">${l('暂无统计', 'No data')}</p>`}</div><p class="feature-note">${l('按大小排列，最多展示前 20 项。', 'Top 20 groups by logical size.')}</p>`;
  }
  function selection() {
    $('#tools-selected').textContent = `${l('已选', 'Selected')} ${s.selected.size}`;
    $('#tools-apply').disabled = !s.selected.size || s.loading || !!s.check?.running || !!s.list?.curationError;
    const selected = s.list?.rows.filter(r => s.selected.has(r.folder)).length || 0;
    $('#tools-select-page').checked = !!selected && selected === s.list.rows.length;
    $('#tools-select-page').indeterminate = selected > 0 && selected < s.list.rows.length;
  }
  function entries() {
    $('#tools-rows').innerHTML = s.list.rows.map((r, i) => `<tr><td><input type="checkbox" data-tool-row="${i}" aria-label="${esc(l('选择 ', 'Select ') + r.folder)}"${s.selected.has(r.folder) ? ' checked' : ''}></td><td><strong>${esc(r.name)}</strong><code>${esc(r.folder)}</code><small>${esc(r.how || '—')}${r.manual ? ` · ${l('网页修正', 'Web correction')}` : r.sourceManual ? ` · ${l('源库人工修正', 'Source correction')}` : ''}</small></td><td>${r.id ? `<a href="https://booth.pm/en/items/${r.id}" target="_blank" rel="noopener noreferrer">${esc(r.title || `BOOTH #${r.id}`)}</a><small>#${r.id} · ${esc(r.shop)}</small>` : `<span class="tools-badge ${r.status}">${esc(labels()[r.status])}</span>`}</td><td><strong>${bytes(r.bytes)}</strong><small>${esc(r.type === 'folder' ? l('文件夹', 'Folder') : r.type)} · ${r.files} ${l('文件', 'files')}</small></td><td><div class="tools-row-actions"><button class="text-button" data-tool-action="evidence" data-index="${i}">${l('依据 / 修正', 'Evidence / edit')}</button><button class="text-button" data-tool-action="reveal" data-index="${i}">${l('定位', 'Locate')}</button></div></td></tr>`).join('') || `<tr><td colspan="5" class="tools-empty">${l('没有符合条件的条目', 'No matching entries')}</td></tr>`;
    $('#tools-pages').innerHTML = `<span>${s.list.count} ${l('条目', 'entries')} · ${s.list.page} / ${s.list.pages}</span><button class="btn" data-tool-page="${s.list.page - 1}"${s.list.page <= 1 ? ' disabled' : ''}>${l('上一页', 'Previous')}</button><button class="btn" data-tool-page="${s.list.page + 1}"${s.list.page >= s.list.pages ? ' disabled' : ''}>${l('下一页', 'Next')}</button>`;
    $('#tools-export').href = '/api/local/export.csv?' + params(); $('#tools-evidence').hidden = true; selection();
  }
  function checkState() {
    const c = s.check; if (!c) return;
    $('[data-tool-action="check-start"]').disabled = c.running || s.loading || !s.list;
    $('[data-tool-action="check-stop"]').disabled = !c.running;
    $('#tools-check-export').hidden = !c.result;
    $('#tools-check-state').textContent = c.running ? c.phase === 'enumerating' ? `${l('枚举文件', 'Enumerating files')} · ${c.enumerated || 0}` : `${l('核对中', 'Hashing')} ${c.done || 0}/${c.total || 0} · ${bytes(c.readBytes || 0)} / ${bytes(c.totalBytes || 0)} · ${c.folder || ''}` : c.error || (c.stale ? l('库存或归属已变化，旧结果已失效，请重新核对。', 'Inventory changed; run a new check.') : c.stopped ? l('本次已取消；上次完成的结果已保留。', 'Cancelled; the last completed result is retained.') : c.result ? l('核对完成', 'Check completed') : l('尚未执行内容核对', 'No content check yet'));
    $('#tools-check-state').classList.toggle('error', !!c.error);
    if (!c.result) { $('#tools-check-result').innerHTML = ''; return; }
    const r = c.result, pages = Math.max(1, Math.ceil(r.groups.length / 20)); s.checkPage = Math.min(s.checkPage, pages);
    $('#tools-check-result').innerHTML = `<div class="tools-check-summary"><strong>${r.groups.length} ${l('组相同内容', 'identical groups')} · ${bytes(r.extraBytes)} ${l('额外逻辑大小', 'extra logical bytes')}</strong><span>${l('已枚举', 'Enumerated')} ${r.enumerated} · ${l('核对时间', 'Checked')} ${esc(new Date(r.checkedAt).toLocaleString(language() === 'zh' ? 'zh-CN' : 'en-GB', { timeZone: 'Asia/Shanghai' }))}</span></div>${r.groups.slice((s.checkPage - 1) * 20, s.checkPage * 20).map((g, index) => `<article class="tools-file-group"><div><strong>${bytes(g.bytes)} × ${g.files.length} ${l('路径', 'paths')}</strong><span>${g.distinctFiles} ${l('不同文件', 'distinct files')} · ${g.hardlinkPaths} ${l('硬链接额外路径', 'extra hardlink paths')}</span></div><code class="tools-hash">${esc(g.hash)}</code><ul>${g.files.map((f, fi) => `<li><code>${esc(f)}</code><button class="text-button" data-tool-action="check-reveal" data-group="${(s.checkPage - 1) * 20 + index}" data-index="${fi}">${l('定位', 'Locate')}</button></li>`).join('')}</ul></article>`).join('') || `<p class="tools-empty">${l('没有发现完全相同的文件内容。', 'No identical file content found.')}</p>`}<div class="tools-pagination"><span>${s.checkPage} / ${pages}</span><button class="btn" data-tool-check-page="${s.checkPage - 1}"${s.checkPage === 1 ? ' disabled' : ''}>${l('上一页', 'Previous')}</button><button class="btn" data-tool-check-page="${s.checkPage + 1}"${s.checkPage === pages ? ' disabled' : ''}>${l('下一页', 'Next')}</button></div>${r.warningCount ? `<details class="tools-warnings"><summary>${r.warningCount} ${l('条文件访问或变化提示', 'file access/change warnings')}</summary>${r.warnings.map(w => `<p><code>${esc(w.folder)}</code> · ${esc(w.message)}</p>`).join('')}</details>` : ''}`;
  }
  async function load() {
    const request = ++s.request; s.loading = true; if ($('#tools-apply')) selection(); feedback(l('正在读取库存…', 'Reading inventory…'));
    try {
      const [list, stats, check] = await Promise.all([api('/api/local/manage?' + params()), api('/api/local/stats'), api('/api/local/check')]);
      if (request !== s.request) return;
      if (list.context !== stats.context) return load();
      s.list = list; s.stats = stats; s.check = check; s.page = list.page; s.selected.clear();
      summary(); breakdown(); entries(); checkState();
      feedback(list.curationError || `${list.source.source} · ${l('快照', 'Snapshot')} ${list.source.generatedAt || '—'}`, !!list.curationError);
    } catch (error) { if (request === s.request) { s.list = null; s.stats = null; s.selected.clear(); $('#tools-summary').innerHTML = ''; $('#tools-rows').innerHTML = ''; $('#tools-breakdown').innerHTML = ''; feedback(error.message, true); } }
    finally { if (request === s.request) { s.loading = false; selection(); checkState(); } }
  }
  async function tick() {
    clearTimeout(poll); if (!dialog.open) return;
    try { s.check = await api('/api/local/check'); checkState(); selection(); } catch (error) { feedback(error.message, true); }
    if (dialog.open) poll = setTimeout(tick, s.check?.running ? 750 : 5000);
  }
  async function open(options = {}) {
    if (options.status) { s.status = options.status; s.page = 1; s.tab = 'entries'; }
    if (options.query !== undefined) { s.q = options.query; s.page = 1; s.tab = 'entries'; }
    if (!dialog.open) { shell(); dialog.showModal(); }
    await load(); tab(); tick();
  }
  dialog.addEventListener('close', () => { clearTimeout(poll); clearTimeout(searchTimer); s.request++; });
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-tools-open]');
    if (button) open({ status: button.dataset.toolsStatus, ...(button.hasAttribute('data-tools-query') ? { query: button.dataset.toolsQuery } : {}) });
  });
  dialog.addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button || button.disabled) return;
    if (button.dataset.action === 'data') { dialog.close(); return; }
    if (button.hasAttribute('data-tool-tab')) { s.tab = button.dataset.toolTab; tab(); return; }
    if (button.hasAttribute('data-tool-status')) { s.status = button.dataset.toolStatus; s.page = 1; s.tab = 'entries'; $('#tools-status').value = s.status; tab(); await load(); return; }
    if (button.hasAttribute('data-tool-page')) { s.page = Number(button.dataset.toolPage); await load(); return; }
    if (button.hasAttribute('data-tool-check-page')) { s.checkPage = Number(button.dataset.toolCheckPage); checkState(); return; }
    const action = button.dataset.toolAction, row = s.list?.rows[Number(button.dataset.index)];
    if (action === 'close') { dialog.close(); return; }
    button.disabled = true;
    try {
      if (action === 'reload') { await post('/api/local/reload', {}); await load(); await onChanged(); }
      if (action === 'apply') {
        const result = await post('/api/local/override', { context: s.list.context, folders: [...s.selected], action: $('#tools-action').value, id: $('#tools-product-id').value });
        await load(); await onChanged(); feedback(`${l('已修正', 'Updated')} ${result.changed} ${l('条目，原库保持原样。', 'entries; source data preserved.')}`);
      }
      if (action === 'evidence' && row) {
        s.selected = new Set([row.folder]); for (const el of dialog.querySelectorAll('[data-tool-row]')) el.checked = s.list.rows[Number(el.dataset.toolRow)].folder === row.folder;
        selection(); const el = $('#tools-evidence'); el.hidden = false;
        el.innerHTML = `<h2>${l('识别依据', 'Identification evidence')} · ${esc(row.name)}</h2><p>${esc(row.how || '—')} · ${esc(row.confidence || '—')}</p><pre>${esc(row.evidence)}</pre><p>${l('已选中该条目，使用上方修正栏修改归属。', 'This entry is selected. Use the correction controls above.')}</p>`;
        el.scrollIntoView({ block: 'nearest' });
      }
      if (action === 'reveal' && row) { await post('/api/local/entry-reveal', { context: s.list.context, folder: row.folder }); feedback(l('已请求资源管理器定位。', 'Requested location in Explorer.')); }
      if (action === 'check-start') { s.check = await post('/api/local/check/start', { context: s.list.context }); checkState(); tick(); }
      if (action === 'check-stop') { s.check = await post('/api/local/check/stop', {}); checkState(); tick(); }
      if (action === 'check-reveal') { const folder = s.check.result.groups[Number(button.dataset.group)].files[Number(button.dataset.index)]; await post('/api/local/check/reveal', { context: s.list.context, folder }); feedback(l('已请求资源管理器定位。', 'Requested location in Explorer.')); }
    } catch (error) { feedback(error.message, true); }
    finally { button.disabled = false; selection(); checkState(); }
  });
  dialog.addEventListener('change', async event => {
    const el = event.target;
    if (el.id === 'tools-dimension') { s.dimension = el.value; breakdown(); }
    if (el.id === 'tools-action') $('#tools-product-id').hidden = el.value !== 'bind';
    if (el.id === 'tools-select-page') { for (const row of s.list?.rows || []) el.checked ? s.selected.add(row.folder) : s.selected.delete(row.folder); for (const box of dialog.querySelectorAll('[data-tool-row]')) box.checked = el.checked; selection(); }
    if (el.hasAttribute('data-tool-row')) { const row = s.list.rows[Number(el.dataset.toolRow)]; el.checked ? s.selected.add(row.folder) : s.selected.delete(row.folder); selection(); }
    if (el.id === 'tools-status' || el.id === 'tools-sort') { s[el.id === 'tools-status' ? 'status' : 'sort'] = el.value; s.page = 1; await load(); }
  });
  dialog.addEventListener('input', event => { if (event.target.id === 'tools-query') { clearTimeout(searchTimer); s.q = event.target.value; s.page = 1; searchTimer = setTimeout(load, 220); } });
  return { open };
}

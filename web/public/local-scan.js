export function initLocalScan({ api, escape: esc, language, onChanged }) {
  const dialog = document.querySelector('#scan-dialog'), l = (zh, en) => language() === 'zh' ? zh : en;
  const $ = selector => dialog.querySelector(selector);
  const post = (url, body) => api(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  let latest, timer, seenTask, saving = false, active = true;
  function render() {
    dialog.innerHTML = `<div class="dialog-heading"><div><h1>${l('扫描下载目录', 'Scan downloads')}</h1><p>${l('直接使用 BoothNest 原识别引擎，支持压缩包线索、增量扫描与名称反查。', 'Uses the BoothNest engine for archive clues, incremental scans and name matching.')}</p></div><button class="icon-btn" data-scan-action="close" aria-label="${l('关闭', 'Close')}">×</button></div><form id="scan-form"><label class="scan-root-label">${l('下载目录', 'Download directory')}<div class="scan-root-row"><input id="scan-root" required placeholder="X:\\下载" aria-label="${l('扫描根目录', 'Scan root')}"><button type="button" class="btn" data-scan-action="pick">${l('浏览…', 'Browse…')}</button></div></label><div class="scan-options"><label class="check-label"><input id="scan-offline" type="checkbox">${l('离线模式（仅使用本地缓存）', 'Offline mode (local cache only)')}</label><label class="check-label"><input id="scan-full" type="checkbox">${l('本次全量重扫（忽略探测缓存）', 'Full rescan (ignore probe cache)')}</label></div><div class="scan-schedule"><label class="check-label"><input id="scan-enabled" type="checkbox">${l('自动增量扫描', 'Automatic incremental scans')}</label><label>${l('间隔（分钟）', 'Interval (minutes)')}<input id="scan-interval" type="number" min="5" max="1440" value="30" required></label><button class="btn" type="submit">${l('保存设置', 'Save settings')}</button></div></form><div class="data-actions"><button class="btn primary" data-scan-action="start">${l('立即扫描', 'Scan now')}</button><button class="btn" data-scan-action="cancel" disabled>${l('取消扫描', 'Cancel scan')}</button><a href="/classic" class="btn">${l('完整管理 / 表格与导出', 'Full manager / tables & exports')}</a></div><p class="feature-note">${l('首次沿用当前库存时会复制缓存到新版管理库；原库存与下载文件保留。扫描成功后自动更新网页。自动扫描需要后台服务运行。', 'The existing inventory/cache is copied into the managed library. Successful scans update the page. Scheduled scans require the service to remain running.')}</p><p id="scan-state" role="status" aria-live="polite"></p><pre id="scan-log" class="scan-log"></pre><p id="scan-feedback" class="form-feedback" role="status"></p>`;
  }
  function show(value, fill = false) {
    latest = value; if (!dialog.open) return;
    const task = value.task, busy = task.busy;
    if (fill) { $('#scan-root').value = value.state.root || value.state.dataset_root || ''; $('#scan-offline').checked = !!value.state.offline; $('#scan-enabled').checked = value.config.enabled; $('#scan-interval').value = value.config.intervalMinutes; }
    for (const el of dialog.querySelectorAll('#scan-form input, #scan-form button, [data-scan-action="start"], [data-scan-action="pick"]')) el.disabled = busy || saving;
    $('[data-scan-action="cancel"]').disabled = !busy;
    const next = value.config.nextRunAt ? new Date(value.config.nextRunAt).toLocaleString(language() === 'zh' ? 'zh-CN' : 'en-GB', { timeZone: 'Asia/Shanghai' }) : l('未启用', 'Disabled');
    $('#scan-state').textContent = busy ? `${task.phase} · ${task.done}/${task.total || '—'}` : `${task.finished ? task.result?.ok ? l('扫描完成，网页已更新。', 'Scan completed; catalogue updated.') : task.result?.cancelled ? l('扫描已取消，保留上次库存。', 'Cancelled; previous inventory retained.') : task.result?.error || l('扫描失败，保留上次库存。', 'Failed; previous inventory retained.') : l('等待扫描', 'Ready to scan')} · ${l('下次自动扫描', 'Next scan')} ${next}`;
    $('#scan-log').textContent = task.logs.slice(-100).join('\n');
    if (value.error) $('#scan-feedback').textContent = value.error;
  }
  async function poll(fill = false) {
    clearTimeout(timer);
    try {
      const value = await api('/api/scan/status'); show(value, fill);
      if (value.task.finished && value.task.result?.ok && seenTask !== value.task.task_id) { seenTask = value.task.task_id; await onChanged(); }
    } catch (error) { if (dialog.open) $('#scan-feedback').textContent = error.message; }
    if (active) timer = setTimeout(poll, latest?.task.busy ? 1000 : 10000);
  }
  const body = () => ({ root: $('#scan-root').value.trim(), offline: $('#scan-offline').checked, full: $('#scan-full').checked });
  document.addEventListener('click', async event => {
    if (event.target.closest('[data-scan-open]')) { if (!dialog.open) { render(); dialog.showModal(); } await poll(true); }
  });
  dialog.addEventListener('submit', async event => {
    event.preventDefault(); saving = true; $('#scan-feedback').textContent = '';
    try { const value = await post('/api/scan/config', { ...body(), enabled: $('#scan-enabled').checked, intervalMinutes: Number($('#scan-interval').value) }); show(value, true); $('#scan-feedback').textContent = l('设置已保存。', 'Settings saved.'); }
    catch (error) { $('#scan-feedback').textContent = error.message; }
    finally { saving = false; if (latest) show(latest); }
  });
  dialog.addEventListener('click', async event => {
    const button = event.target.closest('[data-scan-action]'); if (!button || button.disabled) return;
    const action = button.dataset.scanAction; if (action === 'close') { dialog.close(); return; }
    button.disabled = true;
    $('#scan-feedback').textContent = '';
    try {
      if (action === 'pick') { const r = await post('/api/scan/pick', {}); if (!r.ok) throw new Error(r.error); $('#scan-root').value = r.root; }
      if (action === 'start') { show(await post('/api/scan/start', body())); await poll(); }
      if (action === 'cancel') { await post('/api/scan/cancel', {}); await poll(); }
    } catch (error) { $('#scan-feedback').textContent = error.message; }
    finally { button.disabled = false; if (latest) show(latest); }
  });
  poll();
  window.addEventListener('pagehide', () => { active = false; clearTimeout(timer); });
}

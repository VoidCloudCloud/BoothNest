export function initPurchaseSync({ api, escape, language, onSynced }) {
  let state, lastSync, pendingCode = '', expires = '', busy = false;
  const zh = () => language() === 'zh';
  const text = (cn, en) => zh() ? cn : en;
  function render() {
    const panel = document.querySelector('#purchase-auto-sync'); if (!panel) return;
    const status = state || {};
    const phase = status.paired ? status.enabled ? text('每天同步一次', 'Sync once a day') : text('自动同步已暂停', 'Automatic sync paused') : text('尚未配对浏览器扩展', 'Browser extension not paired');
    panel.innerHTML = `<h3>${text('已购自动同步', 'Automatic purchase sync')}</h3><p>${text('安装浏览器扩展并配对后，每天自动读取 BOOTH 已购清单，直接更新到这里。浏览器与 GUI 均需开启。', 'Pair the browser extension to sync your BOOTH library once a day. Keep both the browser and GUI running.')}</p><p class="connection-summary" role="status">${escape(phase)}${status.phase === 'running' ? `<br>${text('正在同步', 'Syncing')} · ${Number(status.progress?.page || 0)} / ${Number(status.progress?.pages || 0)} ${text('页', 'pages')}` : ''}${status.lastSyncAt ? `<br>${text('最近成功', 'Last success')}：${escape(new Date(status.lastSyncAt).toLocaleString())}` : ''}${status.lastResult ? `<br>${text('共', 'Total')} ${Number(status.lastResult.total)} · ${text('新增', 'Added')} ${Number(status.lastResult.added)}` : ''}</p>${status.error || status.lastError ? `<p class="form-feedback error">${escape(status.error || status.lastError)}</p>` : ''}<div class="data-actions"><a class="btn" href="/api/purchases/bridge/extension.zip" download="BoothNest-PurchaseSync.zip">${text('下载同步扩展', 'Download extension')}</a><button class="btn" data-purchase-sync="pair">${text('生成配对信息', 'Generate pairing information')}</button>${status.paired ? `<button class="btn" data-purchase-sync="request">${text('请求立即同步', 'Request sync now')}</button><button class="btn" data-purchase-sync="toggle">${status.enabled ? text('暂停自动同步', 'Pause automatic sync') : text('恢复每日同步', 'Resume daily sync')}</button><button class="btn" data-purchase-sync="disconnect">${text('解除配对', 'Disconnect')}</button>` : ''}</div>${pendingCode ? `<label class="purchase-pairing-label">${text('复制到浏览器扩展中，10 分钟内有效', 'Paste into the browser extension within 10 minutes')}<input id="purchase-pairing-info" readonly value="${escape(pendingCode)}" aria-label="${text('配对信息', 'Pairing information')}"></label><p class="muted">${text('有效至', 'Valid until')} ${escape(new Date(expires).toLocaleTimeString())}</p><button class="btn" data-purchase-sync="copy">${text('复制配对信息', 'Copy pairing information')}</button>` : ''}<details><summary>${text('首次安装与使用步骤', 'Installation and usage')}</summary><ol><li>${text('下载并解压扩展 ZIP。', 'Download and extract the extension ZIP.')}</li><li>${text('在已登录 BOOTH 的普通 Edge / Chrome 打开 edge://extensions 或 chrome://extensions，开启开发者模式，点击「加载解压缩的扩展」，选择含 manifest.json 的文件夹。', 'Open edge://extensions or chrome://extensions in your BOOTH browser, enable Developer mode and load the extracted folder containing manifest.json.')}</li><li>${text('生成并复制上方配对信息，点击浏览器工具栏的 BoothNest 已购同步扩展，粘贴配对。首次会立即同步。', 'Generate and copy pairing information here, then paste it in the extension popup. The first sync starts immediately.')}</li><li>${text('以后每天同步一次；未同时开启时，下次可用会补同步。同步时会短暂打开后台下载库标签页，完成后自动关闭。登录失效时，在普通浏览器登录后点扩展的「立即同步」。', 'Syncs daily and catches up when both apps become available. A temporary background library tab closes after collection. If login expires, sign in and use Sync now in the extension.')}</li></ol></details><p id="purchase-auto-feedback" class="form-feedback" role="status"></p>`;
  }
  async function poll() {
    if (busy) return;
    try {
      state = await api('/api/purchases/bridge/status');
      const changed = lastSync !== undefined && state.lastSyncAt && lastSync !== state.lastSyncAt;
      lastSync = state.lastSyncAt;
      if (changed) { pendingCode = ''; await onSynced(); }
      // Leave selected pairing text and installation instructions stable while reading them.
      if (!document.querySelector('#purchase-pairing-info')?.matches(':focus') && !document.querySelector('#purchase-auto-sync details[open]')) render();
    } catch {}
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-purchase-sync]'); if (!button || busy) return;
    busy = true; button.disabled = true;
    const action = button.dataset.purchaseSync;
    try {
      if (action === 'copy') {
        try { await navigator.clipboard.writeText(pendingCode); document.querySelector('#purchase-auto-feedback').textContent = text('已复制，请粘贴到浏览器扩展。', 'Copied. Paste in the extension.'); }
        catch { const input = document.querySelector('#purchase-pairing-info'); input.focus(); input.select(); }
      } else if (action === 'pair') {
        const value = await api('/api/purchases/bridge/pairing-code', { method: 'POST' });
        pendingCode = location.origin + '/#boothnest-pair=' + value.code; expires = value.expiresAt; render();
      } else {
        const suffix = { request: 'request', toggle: 'config', disconnect: 'disconnect' }[action];
        state = await api('/api/purchases/bridge/' + suffix, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(action === 'toggle' ? { enabled: !state.enabled } : {}) });
        if (action === 'disconnect') pendingCode = '';
        render();
        if (action === 'request') document.querySelector('#purchase-auto-feedback').textContent = text('已发送请求，扩展开启时通常在 1 分钟内开始；也可在扩展中点「立即同步」。', 'Requested. The running extension usually starts within one minute; its Sync now button starts immediately.');
      }
    } catch (error) { const feedback = document.querySelector('#purchase-auto-feedback'); if (feedback) { feedback.textContent = error.message; feedback.classList.add('error'); } }
    finally { busy = false; if (button.isConnected) button.disabled = false; }
  });
  void poll(); setInterval(poll, 10000);
  return { mount(section) { const panel = document.createElement('div'); panel.id = 'purchase-auto-sync'; panel.className = 'purchase-auto-sync'; section.querySelector('h2').after(panel); render(); void poll(); } };
}

const field = document.querySelector('#status');
async function call(message) { const result = await chrome.runtime.sendMessage(message); if (result.error) throw new Error(result.error); return result; }
function render(data) {
  document.querySelector('#pair-form').hidden = data.paired;
  document.querySelector('#connected').hidden = !data.paired;
  document.querySelector('#sync').disabled = ['starting', 'running'].includes(data.phase);
  const labels = { starting: '正在打开下载库…', running: '正在同步…', paused: '自动同步已暂停。', idle: data.paired ? '已配对，每天同步一次。' : '请先在 GUI「数据管理 → 已购自动同步」生成配对信息。', error: '同步未完成。' };
  field.textContent = (data.lastError || labels[data.phase] || '') + (data.progress ? ` 第 ${data.progress.page} / ${data.progress.pages} 页，已找到 ${data.progress.products} 件。` : '') + (data.lastSyncAt ? '\n最近成功：' + new Date(data.lastSyncAt).toLocaleString() : '') + (data.lastResult ? `\n共 ${data.lastResult.total} 件，新增 ${data.lastResult.added} 件。` : '');
}
async function refresh() { try { render(await call({ action: 'status' })); } catch (error) { field.textContent = error.message; } }
document.querySelector('#pair-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true; field.textContent = '正在配对…';
  try { render(await call({ action: 'pair', pairing: document.querySelector('#pairing').value })); document.querySelector('#pairing').value = ''; } catch (error) { field.textContent = error.message; } finally { button.disabled = false; }
});
document.querySelector('#sync').addEventListener('click', async () => { field.textContent = '正在连接 GUI…'; try { await call({ action: 'sync' }); await refresh(); } catch (error) { field.textContent = error.message; } });
void refresh(); setInterval(refresh, 2000);

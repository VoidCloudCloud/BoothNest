const DAY = 24 * 60 * 60 * 1000;
const libraryUrl = 'https://accounts.booth.pm/library';
let starting = false;
let contentQueue = Promise.resolve();
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const status = data => ({ paired: !!data.token, phase: data.phase || 'idle', lastError: data.lastError || '', lastSyncAt: data.lastSyncAt || '', lastAttemptAt: data.lastAttemptAt || 0, lastResult: data.lastResult || null, progress: data.progress || null });
async function bridge(data, action, body = {}) {
  let response;
  try { response = await fetch(data.base + '/api/purchases/bridge/' + action, { method: 'POST', credentials: 'omit', headers: { 'content-type': 'application/json', 'X-BoothNest-Extension': chrome.runtime.id, ...(data.token ? { 'X-BoothNest-Purchase-Token': data.token } : {}) }, body: JSON.stringify(body), signal: AbortSignal.timeout(8000) }); }
  catch { throw new Error('无法连接 BoothNest GUI，请先打开 GUI。'); }
  const value = await response.json();
  if (!response.ok) { if (response.status === 401) await chrome.storage.local.remove('token'); throw new Error(value.error || '同步接口暂时不可用。'); }
  return value;
}
async function finishError(error) {
  const data = await chrome.storage.local.get(null), job = data.activeJob;
  const message = error.message || '同步未完成。';
  try { if (data.token) await bridge(data, 'report', { phase: 'error', message }); } catch {}
  await chrome.storage.local.set({ activeJob: null, phase: 'error', progress: null, lastError: message });
  await chrome.alarms.clear('job-timeout');
  if (job?.tabId != null) { try { await chrome.tabs.remove(job.tabId); } catch {} }
}
async function runSync(force = false) {
  if (starting) return { phase: 'starting' };
  starting = true;
  try {
    let data = await chrome.storage.local.get(null);
    if (!data.token || data.activeJob) return status(data);
    const remote = await bridge(data, 'poll');
    if (remote.offline || (!force && !remote.enabled)) { await chrome.storage.local.set({ phase: 'paused', lastError: remote.offline ? 'GUI 处于离线模式。' : '' }); return { phase: 'paused' }; }
    const requested = remote.requestId && remote.requestId !== data.handledRequestId;
    if (!force && !requested && Date.now() - (data.lastAttemptAt || 0) < DAY) return status(data);
    const job = { id: crypto.randomUUID(), tabId: null, startedAt: Date.now() };
    await chrome.storage.local.set({ activeJob: job, phase: 'starting', lastError: '', lastAttemptAt: Date.now(), handledRequestId: remote.requestId });
    await bridge(data, 'report', { phase: 'running', start: true });
    const tab = await chrome.tabs.create({ url: 'about:blank', active: false }); job.tabId = tab.id;
    await chrome.storage.local.set({ activeJob: job });
    await chrome.alarms.create('job-timeout', { when: Date.now() + 12 * 60 * 1000 });
    await chrome.tabs.update(tab.id, { url: libraryUrl });
    let loaded = false;
    for (let attempt = 0; attempt < 80; attempt++) {
      const current = await chrome.tabs.get(tab.id);
      if (!current.url || current.url === 'about:blank' || current.pendingUrl) { await sleep(500); continue; }
      if (current.status === 'complete') {
        const url = new URL(current.url);
        if (!url.protocol.startsWith('http')) throw new Error('BOOTH 下载库未能加载，请检查浏览器网络连接。');
        if (url.origin !== 'https://accounts.booth.pm' || !/^\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?library\/?$/i.test(url.pathname)) throw new Error('需要在普通浏览器重新登录 BOOTH，然后点击扩展的「立即同步」。');
        loaded = true; break;
      }
      await sleep(500);
    }
    if (!loaded) throw new Error('BOOTH 下载库加载超时，请检查网络或登录状态。');
    let accepted = false;
    for (let attempt = 0; attempt < 10; attempt++) {
      try { const response = await chrome.tabs.sendMessage(tab.id, { type: 'collect', jobId: job.id }); if (response?.accepted) { accepted = true; break; } } catch {}
      await sleep(500);
    }
    if (!accepted) throw new Error('采集脚本未能启动，请重新加载扩展后重试。');
    return { phase: 'running' };
  } catch (error) { await finishError(error); return { phase: 'error', lastError: error.message }; }
  finally { starting = false; }
}
async function contentMessage(message, sender) {
  const data = await chrome.storage.local.get(null), job = data.activeJob;
  if (!job || sender.id !== chrome.runtime.id || sender.tab?.id !== job.tabId || message.jobId !== job.id) throw Object.assign(new Error('同步任务不匹配。'), { unauthorized: true });
  if (message.type === 'progress') {
    const progress = message.progress;
    await chrome.storage.local.set({ phase: 'running', progress });
    if (Date.now() - (data.lastReportAt || 0) > 5000) {
      await chrome.storage.local.set({ lastReportAt: Date.now() });
      try { await bridge(data, 'report', { phase: 'running', ...progress }); } catch {}
    }
    return { ok: true };
  }
  if (message.type === 'failed') { await finishError(new Error(message.message)); return { ok: true }; }
  const result = await bridge(data, 'import', message.result);
  await chrome.storage.local.set({ activeJob: null, phase: 'idle', lastSyncAt: new Date().toISOString(), lastError: '', lastResult: result, progress: null });
  await chrome.alarms.clear('job-timeout');
  try { await chrome.tabs.remove(job.tabId); } catch {}
  return { ok: true };
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (['progress', 'complete', 'failed'].includes(message.type)) {
      const operation = contentQueue.then(() => contentMessage(message, sender)); contentQueue = operation.catch(() => {}); return operation;
    }
    if (sender.tab && !sender.url?.startsWith('chrome-extension://' + chrome.runtime.id + '/')) throw new Error('无效的扩展请求。');
    if (message.action === 'status') return status(await chrome.storage.local.get(null));
    if (message.action === 'sync') return runSync(true);
    if (message.action === 'pair') {
      const url = new URL(String(message.pairing || '').trim()), code = url.hash.replace(/^#boothnest-pair=/, '');
      if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) || url.username || url.password || url.pathname !== '/' || url.search || !/^[A-F0-9]{10}$/.test(code)) throw new Error('请完整粘贴 GUI 中生成的配对信息。');
      const result = await bridge({ base: url.origin }, 'pair', { code });
      await chrome.storage.local.set({ base: url.origin, token: result.token, lastAttemptAt: 0, activeJob: null, lastError: '', phase: 'idle' });
      await runSync(true); return status(await chrome.storage.local.get(null));
    }
    throw new Error('未知操作。');
  })().then(sendResponse).catch(async error => {
    if (['complete', 'failed'].includes(message.type) && !error.unauthorized) await finishError(error);
    sendResponse({ error: error.message });
  });
  return true;
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'daily-check') void runSync();
  if (alarm.name === 'job-timeout') void finishError(new Error('本次同步超时，请检查 BOOTH 登录状态后重试。'));
});
async function initialize(restarted = false) {
  await chrome.alarms.create('daily-check', { periodInMinutes: 1, delayInMinutes: 1 });
  if (restarted) { const data = await chrome.storage.local.get(null); if (data.activeJob) await chrome.storage.local.set({ activeJob: null, lastAttemptAt: 0, phase: 'idle' }); }
  await runSync();
}
chrome.runtime.onInstalled.addListener(() => { void initialize(true); });
chrome.runtime.onStartup.addListener(() => { void initialize(true); });

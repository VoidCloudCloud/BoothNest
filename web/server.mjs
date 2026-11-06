import http from 'node:http';
import { readFile, writeFile, mkdir, access, stat } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createHash, randomBytes } from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { CatalogStore, searchCatalog, boothId, boothToRecord, safeImage, normalizeItem, publicRecord } from './lib/catalog.mjs';
import { VRCatalogueIndex } from './lib/vrcatalogue.mjs';
import { LocalLibrary, defaultLibraryCandidates } from './lib/local-library.mjs';
import { PurchaseStore } from './lib/purchases.mjs';
import { PublicSync } from './lib/public-sync.mjs';
import { BoothRequestError, searchBooth, requestSignal, responseError } from './lib/booth.mjs';
import { LocalTools } from './lib/local-tools.mjs';
import { LocalScan } from './lib/local-scan.mjs';
import { ENGINE_METHODS } from './lib/engine-client.mjs';
import { savePrivateJson } from './lib/local-curation.mjs';
import { PurchaseBridge, purchaseExtensionOrigin } from './lib/purchase-bridge.mjs';
import { purchaseExtensionArchive } from './lib/extension-archive.mjs';
import { searchPalette } from './lib/discovery.mjs';
import { validDiscoveryPreference } from './public/discovery-state.js';
import { ImageSupplement } from './lib/image-supplement.mjs';

const root = fileURLToPath(new URL('.', import.meta.url));
const publicDir = path.join(root, 'public');
const mime = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.ico': 'image/x-icon' };

function json(res, status, value, headers = {}) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...headers });
  res.end(JSON.stringify(value));
}
async function readJson(req) {
  if (!req.headers['content-type']?.startsWith('application/json')) throw Object.assign(new Error('需要 application/json 格式。'), { status: 415 });
  let length = 0; const chunks = [];
  for await (const chunk of req) {
    length += chunk.length;
    if (length > 20000000) throw Object.assign(new Error('导入文件不能超过 20 MB。'), { status: 413 });
    chunks.push(chunk);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw Object.assign(new Error('JSON 格式无效。'), { status: 400 }); }
}

async function cacheImage(url, signal, mediaDir) {
  if (!safeImage(url) || !url.startsWith('https://')) return url;
  const extension = /\.(webp|png|jpe?g)(?:\?|$)/i.exec(url)?.[1]?.toLowerCase() || 'webp';
  const filename = createHash('sha256').update(url).digest('hex').slice(0, 32) + '.' + extension;
  const dest = path.join(mediaDir, filename);
  try { await access(dest); return '/media/' + filename; } catch {}
  try {
    const response = await fetch(url, { signal: requestSignal(signal, 12000), redirect: 'error' });
    if (!response.ok || !response.headers.get('content-type')?.startsWith('image/')) return url;
    const buffer = Buffer.from(await response.arrayBuffer());
    if (buffer.length > 12000000) return url;
    await mkdir(path.dirname(dest), { recursive: true });
    await writeFile(dest, buffer);
    return '/media/' + filename;
  } catch { return url; }
}

export async function createApp({ dataDir = process.env.BOOTH_NEST_WEB_HOME || path.join(root, 'data'), localCandidates, localReveal, syncDependencies = {}, localToolsDependencies = {}, scanDependencies = {}, engineHome = process.env.BOOTH_NEST_ENGINE_HOME, openDataFile = process.env.BOOTH_NEST_OPEN_DATA || path.join(root, 'resources', 'vrcatalogue.sqlite') } = {}) {
  const mediaDir = path.join(dataDir, 'media');
  const imageSupplement = await new ImageSupplement(path.join(dataDir, 'image-supplement')).init();
  const openData = await new VRCatalogueIndex(openDataFile).init();
  const store = await new CatalogStore(dataDir, openData).load();
  const purchases = await new PurchaseStore(dataDir).load();
  const purchaseBridge = await new PurchaseBridge(dataDir, purchases).load();
  const local = await new LocalLibrary({ settingsFile: path.join(dataDir, 'local-library.json'),
    candidates: localCandidates ?? (engineHome ? [engineHome] : path.resolve(dataDir) === path.join(root, 'data') ? defaultLibraryCandidates() : []),
    ...(localReveal ? { reveal: localReveal } : {}),
  }).init();
  let scan;
  const localTools = await new LocalTools(local, dataDir, { overrideHandler: body => scan.override(body), ...localToolsDependencies }).init();
  scan = await new LocalScan({ dataDir, local, home: engineHome, canStart: () => !localTools.busy && !localTools.task.running, ...scanDependencies }).init();
  const sessionToken = process.env.BOOTH_NEST_DESKTOP_TOKEN || randomBytes(32).toString('hex');
  const desktop = { enabled: !!process.env.BOOTH_NEST_DESKTOP_TOKEN, lastHeartbeat: 0, closeHint: 0 };
  const preferenceFile = path.join(dataDir, 'web-preferences.json');
  let preferences = {}, preferenceError = false, preferenceQueue = Promise.resolve();
  try { preferences = JSON.parse(await readFile(preferenceFile, 'utf8')); } catch (error) { preferenceError = error.code !== 'ENOENT'; }
  const validPreferences = value => value && typeof value === 'object' && !Array.isArray(value) && Object.entries(value).every(([key, entry]) => {
    if (key === 'language') return ['zh','en'].includes(entry);
    if (key === 'currency') return ['JPY','CNY','USD'].includes(entry);
    if (key === 'theme') return ['charcoal','cloud'].includes(entry);
    if (['compact','notice-dismissed'].includes(key)) return typeof entry === 'boolean';
    if (key === 'page-size') return [20,40,80].includes(entry);
    if (key === 'favourites') return Array.isArray(entry) && entry.length <= 50000 && entry.every(id => Number.isSafeInteger(id) && id > 0);
    if (key === 'saved-searches' || key === 'recent-views') return validDiscoveryPreference(key, entry);
    return false;
  });
  if (!validPreferences(preferences)) { preferenceError = true; preferences = {}; }
  let joinedCache;
  async function joinedRecords() {
    const raw = purchases.joinedItems(await local.joinedItems(store.data.items), local.status().connected);
    if (joinedCache?.raw !== raw || joinedCache?.offline !== scan.offline) joinedCache = { raw, offline: scan.offline, records: raw.map(item => {
      if (scan.offline) item = { ...item, media: (item.media || []).filter(url => url.startsWith('/')), author_icon: item.author_icon?.startsWith('/') ? item.author_icon : '' };
      item = imageSupplement.enrich(item, { offline: scan.offline });
      if (scan.offline) item = { ...item, media: item.media.filter(url => url.startsWith('/')) };
      return normalizeItem(store.enrich(item), store.categories);
    }) };
    return joinedCache.records;
  }
  let searching = false;
  async function readBoothItem(id, { signal } = {}) {
    if (scan.offline) throw new BoothRequestError('离线模式下不请求 BOOTH，请先关闭离线模式。');
    let response;
    try { response = await fetch(`https://booth.pm/en/items/${id}.json`, { signal: requestSignal(signal, 20000), headers: { accept: 'application/json', 'user-agent': 'BoothNest/2.0 (personal catalogue)' } }); }
    catch (error) { if (signal?.aborted) throw error; throw new BoothRequestError('暂时无法连接 BOOTH，请检查网络后重试。'); }
    if (!response.ok) throw responseError(response.status);
    let data;
    try { data = await response.json(); } catch { throw new BoothRequestError('BOOTH 未返回商品数据，请稍后重试。'); }
    if (Number(data.id) !== id || !data.name) throw new Error('BOOTH 返回的商品数据无效。');
    const previous = store.data.items.find(item => Number(item.id) === id);
    const knownAvatars = [...new Map([...store.avatars, ...store.data.items.flatMap(item => item.linked_avatars ?? [])].map(a => [a.slug, a])).values()];
    const record = boothToRecord(data, previous, knownAvatars);
    record.media = await Promise.all(record.media.map((src, i) => i < 2 ? cacheImage(src, signal, mediaDir) : src));
    record.author_icon = await cacheImage(record.author_icon, signal, mediaDir);
    return record;
  }
  const sync = await new PublicSync({ dataDir, store, searchPage: searchBooth, readItem: readBoothItem, canStart: () => !searching && !scan.offline, ...syncDependencies }).init();
  const server = http.createServer(async (req, res) => {
    res.setHeader('x-content-type-options', 'nosniff');
    res.setHeader('referrer-policy', 'no-referrer');
    res.setHeader('x-frame-options', 'DENY');
    res.setHeader('content-security-policy', "default-src 'self'; img-src 'self' https://cdn.vrcatalogue.com https://booth.pximg.net https://booth.p.pixiv.net https://pixiv.pximg.net; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");
    try {
      const host = req.headers.host || '';
      if (!/^(?:localhost|127\.0\.0\.1)(?::\d+)?$/.test(host)) return json(res, 403, { error: '只允许本机访问。' });
      const url = new URL(req.url, `http://${host}`);
      if (['/api/purchases/bridge/pair', '/api/purchases/bridge/import', '/api/purchases/bridge/report', '/api/purchases/bridge/poll'].includes(url.pathname)) {
        const origin = purchaseExtensionOrigin(req.headers);
        res.setHeader('access-control-allow-origin', origin); res.setHeader('vary', 'Origin');
        if (req.method === 'OPTIONS') {
          res.writeHead(204, { 'access-control-allow-methods': 'POST', 'access-control-allow-headers': 'content-type,x-boothnest-purchase-token,x-boothnest-extension', 'access-control-allow-private-network': 'true', 'access-control-max-age': '300' }); return res.end();
        }
        if (req.method !== 'POST') return json(res, 405, { error: '需要 POST。' });
        if (url.pathname.endsWith('/pair')) return json(res, 200, await purchaseBridge.pair(origin, (await readJson(req)).code));
        const identity = purchaseBridge.authorize(origin, req.headers['x-boothnest-purchase-token']);
        if (url.pathname.endsWith('/poll')) return json(res, 200, { ...purchaseBridge.status(), offline: scan.offline });
        const body = await readJson(req);
        if (scan.offline && url.pathname.endsWith('/import')) return json(res, 409, { error: 'GUI 处于离线模式，已购同步暂停。' });
        return json(res, 200, url.pathname.endsWith('/import') ? await purchaseBridge.receive(body, identity) : await purchaseBridge.report(body, identity));
      }
      if (req.method === 'POST' && req.headers.origin && req.headers.origin !== `http://${host}`) return json(res, 403, { error: '请求来源无效。' });
      if (req.headers['sec-fetch-site'] === 'cross-site') return json(res, 403, { error: '请求来源无效。' });
      if (req.method === 'GET' && url.pathname === '/api/desktop/session') return json(res, 200, { enabled: desktop.enabled, token: desktop.enabled ? sessionToken : '' });
      if (req.method === 'GET' && url.pathname === '/api/desktop/state') {
        if (req.headers['x-boothnest-token'] !== sessionToken) return json(res, 403, { error: 'Invalid session' });
        return json(res, 200, desktop);
      }
      if (req.method === 'POST' && ['/api/desktop/heartbeat','/api/desktop/closed'].includes(url.pathname)) {
        if (req.headers['x-boothnest-token'] !== sessionToken) return json(res, 403, { error: 'Invalid session' });
        if (url.pathname.endsWith('/heartbeat')) { desktop.lastHeartbeat = Date.now(); desktop.closeHint = 0; } else desktop.closeHint = Date.now();
        return json(res, 200, { ok: true });
      }
      if (req.method === 'POST' && url.pathname === '/api/desktop/shutdown') {
        if (!desktop.enabled || req.headers['x-boothnest-token'] !== sessionToken) return json(res, 403, { error: 'Invalid session' });
        await sync.stop(); await scan.dispose(); await localTools.dispose();
        json(res, 200, { ok: true });
        setTimeout(() => { server.close(); server.closeAllConnections(); }, 100); return;
      }
      if (req.method === 'GET' && url.pathname === '/classic') {
        let html = await readFile(path.join(root, 'engine', 'boothlib', 'ui.html'), 'utf8');
        html = html.replaceAll('__BOOTH_SESSION_TOKEN__', sessionToken).replaceAll('<script>', `<script nonce="${sessionToken}">`).replace('<body>', '<body><a href="/" style="display:block;padding:12px 24px;color:#ed8589">← BoothNest 素材探索 / 新版界面</a>');
        res.setHeader('content-security-policy', `default-src 'self'; script-src 'nonce-${sessionToken}'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`);
        res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' }); return res.end(html);
      }
      if (req.method === 'GET' && url.pathname === '/api/ping') return json(res, 200, { ok: true });
      if (req.method === 'GET' && url.pathname === '/api/image-supplement') return json(res, 200, imageSupplement.status());
      if (await imageSupplement.serve(req, res, url.pathname)) return;
      if (req.method === 'GET' && url.pathname === '/api/open-data') { await joinedRecords(); return json(res, 200, openData.status()); }
      const classicMethod = url.pathname.slice('/api/'.length);
      if (req.method === 'POST' && url.pathname.startsWith('/api/') && ENGINE_METHODS.has(classicMethod)) {
        if (req.headers['x-boothnest-token'] !== sessionToken) return json(res, 403, { ok: false, error: 'Invalid session' });
        const body = await readJson(req);
        if (!Array.isArray(body.args)) return json(res, 400, { ok: false, error: 'args must be an array' });
        if (classicMethod === 'set_preferences' && body.args[0]?.offline === 'true') await sync.stop();
        if (classicMethod === 'heartbeat') { desktop.lastHeartbeat = Date.now(); desktop.closeHint = 0; }
        if (classicMethod === 'window_closed' || classicMethod === 'shutdown') desktop.closeHint = Date.now();
        try { return json(res, 200, await scan.classic(classicMethod, body.args)); } catch (error) { return json(res, 400, { ok: false, error: error.message }); }
      }
      if (req.method === 'GET' && url.pathname === '/api/scan/status') {
        try { const result = await scan.status(); if (scan.managed() && local.current) local.current.managed = true; return json(res, 200, result); }
        catch (error) { return json(res, 503, { error: error.message }); }
      }
      if (req.method === 'POST' && ['/api/scan/start','/api/scan/cancel','/api/scan/config','/api/scan/pick'].includes(url.pathname)) {
        const body = await readJson(req);
        try {
          if (body.offline === true) await sync.stop();
          if (url.pathname.endsWith('/start')) return json(res, 202, await scan.start(body));
          if (url.pathname.endsWith('/config')) return json(res, 200, await scan.configure(body));
          if (url.pathname.endsWith('/pick')) return json(res, 200, await scan.classic('pick_root', []));
          await scan.engine.call('cancel'); return json(res, 200, await scan.status());
        } catch (error) { return json(res, 400, { error: error.message }); }
      }
      if (req.method === 'GET' && url.pathname === '/api/preferences') return json(res, 200, preferences);
      if (req.method === 'POST' && url.pathname === '/api/preferences') {
        const body = await readJson(req);
        if (preferenceError || !validPreferences(body) || JSON.stringify(body).length > 1000000) return json(res, 400, { error: '界面设置无效或原文件无法读取，原设置已保留。' });
        const update = preferenceQueue.then(async () => {
          const next = { ...preferences, ...body };
          if (JSON.stringify(next).length > 1000000) throw Object.assign(new Error('界面设置超过大小限制。'), { status: 400 });
          await savePrivateJson(preferenceFile, next); preferences = next;
        });
        preferenceQueue = update.catch(() => {});
        await update; return json(res, 200, { ok: true });
      }
      if (req.method === 'GET' && url.pathname === '/api/palette') {
        await local.refresh();
        return json(res, 200, searchPalette(await joinedRecords(), store.categories, url.searchParams, store.avatars));
      }
      if (req.method === 'GET' && url.pathname === '/api/status') {
        await local.refresh();
        return json(res, 200, { name: 'BoothNest', version: '2.0.0-beta.5', items: store.records.length, capturedAt: store.data.capturedAt, updatedAt: store.data.updatedAt || store.data.capturedAt, source: store.data.source, library: local.status(), purchases: purchases.status(), sync: sync.status(), offline: scan.offline, openData: openData.status() });
      }
      if (req.method === 'GET' && url.pathname === '/api/sync/status') return json(res, 200, sync.status());
      if (req.method === 'POST' && ['/api/sync/config', '/api/sync/run', '/api/sync/stop'].includes(url.pathname)) {
        const body = await readJson(req);
        try {
          if (url.pathname.endsWith('/config')) return json(res, 200, await sync.configure(body));
          if (url.pathname.endsWith('/stop')) return json(res, 200, await sync.stop());
          if (searching) return json(res, 409, { error: '关键词收录正在进行，请稍后再同步。' });
          return json(res, 202, sync.start());
        } catch (error) { return json(res, 400, { error: error.message }); }
      }
      if (req.method === 'GET' && url.pathname === '/api/purchases/status') return json(res, 200, purchases.status());
      if (req.method === 'GET' && url.pathname === '/api/purchases/bridge/status') return json(res, 200, purchaseBridge.status());
      if (req.method === 'GET' && url.pathname === '/api/purchases/bridge/extension.zip') {
        const archive = await purchaseExtensionArchive(publicDir);
        res.writeHead(200, { 'content-type': 'application/zip', 'content-disposition': 'attachment; filename="BoothNest-PurchaseSync.zip"', 'cache-control': 'no-store' }); return res.end(archive);
      }
      if (req.method === 'POST' && url.pathname === '/api/purchases/bridge/pairing-code') return json(res, 200, purchaseBridge.issueCode());
      if (req.method === 'POST' && url.pathname === '/api/purchases/bridge/config') return json(res, 200, await purchaseBridge.configure(await readJson(req)));
      if (req.method === 'POST' && url.pathname === '/api/purchases/bridge/disconnect') return json(res, 200, await purchaseBridge.disconnect());
      if (req.method === 'POST' && url.pathname === '/api/purchases/bridge/request') return json(res, 200, await purchaseBridge.request());
      if (req.method === 'POST' && url.pathname === '/api/purchases/import') {
        const body = await readJson(req);
        try { return json(res, 200, await purchases.merge(body)); }
        catch (error) { return json(res, 400, { error: error.message }); }
      }
      if (req.method === 'GET' && url.pathname === '/api/purchases/export') return json(res, 200, { ...purchases.data, type: 'vrcatalogue-booth-purchases', source: 'https://accounts.booth.pm/library', exportedAt: new Date().toISOString(), complete: false }, { 'content-disposition': 'attachment; filename="vrcatalogue-purchases.json"' });
      if (req.method === 'GET' && url.pathname === '/api/local/status') { await local.refresh(); return json(res, 200, local.status()); }
      if (req.method === 'GET' && ['/api/local/manage', '/api/local/stats', '/api/local/check', '/api/local/export.csv', '/api/local/check.csv'].includes(url.pathname)) {
        try {
          if (url.pathname === '/api/local/manage') { const { allRows, ...result } = await localTools.list(url.searchParams); return json(res, 200, result); }
          if (url.pathname === '/api/local/stats') return json(res, 200, await localTools.stats());
          if (url.pathname === '/api/local/check') { await local.refresh(); return json(res, 200, localTools.checkStatus()); }
          const body = url.pathname.endsWith('/check.csv') ? (await localTools.ready(), localTools.exportCheck()) : await localTools.exportRows(url.searchParams);
          res.writeHead(200, { 'content-type': 'text/csv; charset=utf-8', 'cache-control': 'no-store', 'content-disposition': 'attachment; filename="local-inventory.csv"' });
          return res.end(body);
        } catch (error) { return json(res, error.status || 400, { error: error.message }); }
      }
      if (req.method === 'POST' && ['/api/local/override', '/api/local/entry-reveal', '/api/local/check/start', '/api/local/check/stop', '/api/local/check/reveal'].includes(url.pathname)) {
        const body = await readJson(req);
        try {
          if (url.pathname.endsWith('/stop')) return json(res, 200, localTools.stop());
          if (typeof body?.context !== 'string' || !body.context) return json(res, 409, { error: '请先刷新本地管理面板。' });
          if (url.pathname.endsWith('/start')) return json(res, 202, await localTools.start(body));
          if (url.pathname.endsWith('/override')) return json(res, 200, await localTools.override(body));
          return json(res, 200, await (url.pathname.endsWith('/check/reveal') ? localTools.revealChecked(body) : localTools.reveal(body)));
        } catch (error) { return json(res, error.status || 400, { error: error.message }); }
      }
      if (req.method === 'POST' && ['/api/local/connect', '/api/local/disconnect', '/api/local/reload', '/api/local/reveal'].includes(url.pathname)) {
        const body = await readJson(req);
        try {
          if (url.pathname.endsWith('/connect')) return json(res, 200, await local.connect(body?.path));
          if (url.pathname.endsWith('/disconnect')) return json(res, 200, await local.disconnect());
          if (url.pathname.endsWith('/reveal')) return json(res, 200, await local.locate(body?.id, body?.folder));
          await local.refresh(true); return json(res, 200, local.status());
        } catch (error) { return json(res, 400, { error: error.message }); }
      }
      if (req.method === 'GET' && url.pathname === '/api/local/image') {
        const filename = local.imagePath(url.searchParams.get('key'));
        if (!filename) return json(res, 404, { error: '缓存图片不存在。' });
        try {
          const buffer = await readFile(filename);
          res.writeHead(200, { 'content-type': buffer.subarray(0, 4).toString() === 'RIFF' ? 'image/webp' : buffer[0] === 137 ? 'image/png' : 'image/jpeg', 'cache-control': 'private, max-age=3600' });
          return res.end(buffer);
        } catch { return json(res, 404, { error: '缓存图片不存在。' }); }
      }
      if (req.method === 'GET' && url.pathname === '/api/items') {
        const started = performance.now();
        const result = searchCatalog(await joinedRecords(), store.categories, url.searchParams, Date.now(), store.avatars);
        return json(res, 200, { ...result, discoveryRecords: store.records.length, library: local.status(), purchases: purchases.status(), elapsedMs: Math.round((performance.now() - started) * 10) / 10 });
      }
      if (req.method === 'GET' && /^\/api\/items\/\d+$/.test(url.pathname)) {
        const item = (await joinedRecords()).find(item => item.id === Number(url.pathname.split('/').pop()));
        if (!item) return json(res, 404, { error: '本地目录中没有这条商品。' });
        return json(res, 200, publicRecord(item));
      }
      if (req.method === 'GET' && url.pathname === '/api/export') {
        return json(res, 200, { ...store.data, exportedAt: new Date().toISOString() }, { 'content-disposition': 'attachment; filename="vrcatalogue-catalog.json"' });
      }
      if (req.method === 'POST' && url.pathname === '/api/import') {
        const body = await readJson(req);
        try { return json(res, 200, await store.merge(Array.isArray(body) ? body : body?.items)); }
        catch (error) { return json(res, 400, { error: error.message }); }
      }
      if (req.method === 'POST' && url.pathname === '/api/booth') {
        const body = await readJson(req);
        const id = boothId(body?.url ?? body?.id);
        if (!id) return json(res, 400, { error: '请输入有效的 BOOTH 商品链接或数字 ID。' });
        let record;
        try { record = await readBoothItem(id); } catch (error) { return json(res, 502, { error: error.message }); }
        const result = await store.merge([record]);
        return json(res, 200, { ...result, id, title: record.title });
      }
      if (req.method === 'POST' && url.pathname === '/api/booth-search') {
        if (scan.offline) return json(res, 409, { error: '离线模式下不能联网搜索 BOOTH。' });
        const body = await readJson(req);
        const query = typeof body?.q === 'string' ? body.q.trim().slice(0, 100) : '';
        if (query.length < 2) return json(res, 400, { error: '请输入至少两个字符的搜索关键词。' });
        if (searching || sync.status().running) return json(res, 409, { error: '已有收录任务进行中，请稍后重试。' });
        searching = true;
        try {
          const limit = body.limit === 12 ? 12 : 6;
          const page = Math.min(20, Math.max(1, Number(body.page) || 1));
          const { ids } = await searchBooth(query, { page, sort: 'wish_lists' });
          if (!ids.length) {
            return json(res, 200, { added: 0, updated: 0, total: store.records.length, failed: [], found: 0 });
          }
          const existing = new Set(store.records.map(item => item.id));
          const fresh = ids.filter(id => !existing.has(id));
          const batch = (fresh.length ? fresh : ids).slice(0, limit);
          const records = [], failed = [];
          let cursor = 0;
          await Promise.all(Array.from({ length: 2 }, async () => {
            while (cursor < batch.length) {
              const id = batch[cursor++];
              try { records.push(await readBoothItem(id)); }
              catch (error) { failed.push({ id, error: error.message }); }
            }
          }));
          const result = records.length ? await store.merge(records) : { added: 0, updated: 0, total: store.records.length };
          return json(res, 200, { ...result, found: ids.length, failed });
        } catch (error) { return json(res, 502, { error: error.name === 'TimeoutError' ? '连接 BOOTH 搜索超时，请稍后重试。' : error.message }); }
        finally { searching = false; }
      }
      if (url.pathname.startsWith('/api/')) return json(res, 404, { error: '接口不存在。' });
      if (!['GET', 'HEAD'].includes(req.method)) return json(res, 405, { error: '不支持的请求方法。' });
      let pathname;
      try { pathname = decodeURIComponent(url.pathname); }
      catch { return json(res, 400, { error: '路径无效。' }); }
      if (pathname.includes('\\') || pathname.includes('\0')) return json(res, 400, { error: '路径无效。' });
      let dest = path.resolve(publicDir, '.' + (pathname === '/' ? '/index.html' : pathname));
      if (!dest.startsWith(publicDir + path.sep)) return json(res, 403, { error: '路径无效。' });
      if (pathname.startsWith('/media/')) { const cached = path.resolve(mediaDir, '.' + pathname.slice('/media'.length)); if (!cached.startsWith(mediaDir + path.sep)) return json(res, 403, { error: '路径无效。' }); try { await access(cached); dest = cached; } catch {} }
      try {
        const info = await stat(dest);
        if (!info.isFile()) return json(res, 404, { error: '文件不存在。' });
        res.writeHead(200, { 'content-type': mime[path.extname(dest)] || 'application/octet-stream', 'content-length': info.size, 'cache-control': pathname.startsWith('/media/') ? 'public, max-age=31536000, immutable' : 'no-cache' });
        if (req.method === 'HEAD') res.end(); else createReadStream(dest).pipe(res);
      } catch { json(res, 404, { error: '文件不存在。' }); }
    } catch (error) {
      if (!res.headersSent) json(res, error.status || 500, { error: error.status ? error.message : '操作失败，目录文件已保留，请重试。' });
      else res.end();
      if (!error.status) console.error(error);
    }
  });
  server.keepAliveTimeout = 5000;
  server.on('close', () => { sync.dispose(); localTools.dispose(); scan.dispose(); openData.close(); imageSupplement.close(); });
  return { server, store, local, purchases, sync, localTools, scan, openData };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const port = Number(process.env.PORT || process.argv[2] || 4317);
  const { server, store } = await createApp();
  server.on('error', error => {
    console.error(error.code === 'EADDRINUSE' ? `端口 ${port} 已被占用。请打开 http://127.0.0.1:${port}，或设置 PORT 后重试。` : error.message);
    process.exitCode = 1;
  });
  server.listen(port, '127.0.0.1', () => {
    console.log(`\nBoothNest · ${store.records.length} items\nhttp://127.0.0.1:${port}\n按 Ctrl+C 停止。\n`);
  });
}

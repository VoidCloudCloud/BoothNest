import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { once } from 'node:events';
import os from 'node:os';
import path from 'node:path';
import { createApp } from '../server.mjs';

test('extension pairs, imports directly, syncs daily, catches up after restart and respects pause and revocation', async t => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'booth-addon-'));
  const { server } = await createApp({ dataDir: dir }); server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`;
  t.after(async () => { await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }); await rm(dir, { recursive: true, force: true }); });
  const local = {}, tabs = new Map(), closed = [], alarms = new Map(); let messageHandler, tabCount = 0, now = Date.now(), unavailable = false, loginRequired = false;
  const id = 'a'.repeat(32);
  const chrome = {
    runtime: { id, onMessage: { addListener: fn => { messageHandler = fn; } }, onInstalled: { addListener() {} }, onStartup: { addListener() {} } },
    storage: { local: { async get() { return structuredClone(local); }, async set(value) { Object.assign(local, structuredClone(value)); }, async remove(key) { delete local[key]; } } },
    alarms: { async create(name, value) { alarms.set(name, value); }, async clear(name) { alarms.delete(name); }, onAlarm: { addListener() {} } },
    tabs: { async create() { const tab = { id: ++tabCount, status: 'complete', url: 'about:blank' }; tabs.set(tab.id, tab); return tab; }, async update(key) { const tab = tabs.get(key); tab.url = loginRequired ? 'https://accounts.booth.pm/users/sign_in' : 'https://accounts.booth.pm/library'; return tab; }, async get(key) { return tabs.get(key); }, async sendMessage(key, value) { assert.ok(tabs.has(key)); assert.equal(value.type, 'collect'); return { accepted: true }; }, async remove(key) { assert.ok(tabs.has(key)); tabs.delete(key); closed.push(key); } },
  };
  class ClockDate extends Date { static now() { return now; } }
  const context = vm.createContext({ chrome, Date: ClockDate, crypto: webcrypto, URL, AbortSignal, setTimeout,
    fetch: async (url, options) => { assert.ok(url.startsWith(base + '/')); if (unavailable) throw new Error('offline'); return fetch(url, { ...options, headers: { ...options.headers, origin: 'chrome-extension://' + id } }); },
  });
  vm.runInContext(await readFile(new URL('../public/purchase-extension/background.js', import.meta.url), 'utf8'), context);
  const execute = code => vm.runInContext(code, context);
  const message = (value, sender = { id }) => new Promise(resolve => messageHandler(value, sender, resolve));
  const post = value => ({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(value) });
  const complete = async ids => {
    const job = local.activeJob;
    const result = await message({ type: 'complete', jobId: job.id, result: { type: 'vrcatalogue-booth-purchases', schemaVersion: 1, source: 'https://accounts.booth.pm/library', complete: true, pages: 2, products: ids.map(id => ({ id, title: 'Synthetic purchase' })) } }, { id, tab: { id: job.tabId } });
    assert.equal(result.ok, true); assert.equal(local.activeJob, null);
  };
  const pairing = await (await fetch(base + '/api/purchases/bridge/pairing-code', post({}))).json();
  assert.equal((await message({ action: 'pair', pairing: base + '/#boothnest-pair=' + pairing.code }, { id, tab: { id: 900 }, url: 'chrome-extension://' + id + '/popup.html' })).paired, true);
  assert.ok((await message({ action: 'sync' }, { id, tab: { id: 901 }, url: 'https://accounts.booth.pm/library' })).error);
  assert.equal(tabCount, 1); await complete([501]); assert.equal(local.lastResult.total, 1);
  await execute('runSync()'); assert.equal(tabCount, 1);
  await execute('initialize(true)'); assert.equal(tabCount, 1); assert.ok(alarms.has('daily-check'));
  now += 24 * 60 * 60 * 1000 + 1; await execute('runSync()'); assert.equal(tabCount, 2);
  const running = local.activeJob;
  assert.ok((await message({ type: 'complete', jobId: 'wrong', result: {} }, { id, tab: { id: running.tabId } })).error);
  assert.equal(local.activeJob.id, running.id); assert.ok(tabs.has(running.tabId));
  await complete([501, 502]); assert.equal(local.lastResult.total, 2);
  await fetch(base + '/api/purchases/bridge/request', post({})); await execute('runSync()'); assert.equal(tabCount, 3); await complete([501, 502]);
  await fetch(base + '/api/purchases/bridge/config', post({ enabled: false })); now += 24 * 60 * 60 * 1000 + 1;
  await execute('runSync()'); assert.equal(tabCount, 3); assert.equal(local.phase, 'paused');
  loginRequired = true; await execute('runSync(true)'); assert.equal(tabCount, 4); assert.equal(local.phase, 'error'); assert.match(local.lastError, /重新登录/); assert.equal(tabs.size, 0);
  unavailable = true; await execute('runSync(true)'); assert.equal(tabCount, 4); assert.match(local.lastError, /GUI/);
  unavailable = false; loginRequired = false;
  await fetch(base + '/api/purchases/bridge/disconnect', post({})); await execute('runSync(true)'); assert.equal(local.token, undefined); assert.equal(tabCount, 4);
  assert.deepEqual(closed, [1, 2, 3, 4]);
  const records = await (await fetch(base + '/api/purchases/export')).json(); assert.deepEqual(records.products.map(p => p.id), [501, 502]);
});

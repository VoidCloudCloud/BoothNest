import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { once } from 'node:events';
import os from 'node:os';
import path from 'node:path';
import { CatalogStore, boothToRecord, searchCatalog } from '../lib/catalog.mjs';
import { BoothRequestError, parseSearchPage, searchBooth, responseError } from '../lib/booth.mjs';
import { PublicSync } from '../lib/public-sync.mjs';
import { createApp } from '../server.mjs';

const fixedNow = Date.parse('2026-10-28T05:00:00Z');
const record = (id, price = 900) => ({ id, title: `BOOTH item ${id}`, category: '3D Hair', price_jpy: price, scraped_at: new Date(fixedNow).toISOString(), source: 'booth' });
async function fixture(t, overrides = {}) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'vrc-public-sync-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(path.join(dir, 'catalog.seed.json'), JSON.stringify({ categories: [], items: [{ ...record(101, 500), scraped_at: '2020-01-01', rank: 1 }] }));
  const store = await new CatalogStore(dir).load();
  const requests = [];
  const dependencies = { dataDir: dir, store, now: () => fixedNow, timer: false, pause: async () => {}, searchPage: async (q, options) => {
    requests.push([q, options.page]); return { ids: options.page === 1 ? [201, 202, 203, 201] : options.page === 2 ? [204, 205] : [206] };
  }, readItem: async id => record(id), ...overrides };
  const sync = await new PublicSync(dependencies).init();
  t.after(() => sync.dispose());
  return { dir, store, requests, dependencies, sync };
}

test('public sync checks newest results, refreshes stale items and resumes queued history after restart', async t => {
  const f = await fixture(t); await f.sync.configure({ batchSize: 3 });
  f.sync.start(); await f.sync.wait();
  assert.deepEqual(f.requests, [['VRChat', 1], ['VRChat', 2]]);
  assert.equal(f.sync.status().lastResult.added, 2); assert.equal(f.sync.status().lastResult.updated, 1);
  assert.equal(f.store.data.items.find(p => p.id === 101).price_jpy, 900);
  assert.deepEqual(f.sync.state.pending, [203, 204, 205]);
  const restarted = await new PublicSync(f.dependencies).init(); t.after(() => restarted.dispose());
  assert.equal(restarted.status().cursors.VRChat, 3);
  await restarted.configure({ batchSize: 2 }); restarted.start(); await restarted.wait();
  assert.deepEqual(f.requests.slice(-2), [['VRChat', 1], ['VRChat', 3]]);
  assert.deepEqual(restarted.state.pending, [205, 206]);
  assert.equal(new Set(f.store.data.items.map(p => p.id)).size, f.store.data.items.length);
});

test('a completed public sync changes trending order and persists observed like growth', async t => {
  const f = await fixture(t, { searchPage: async () => ({ ids: [] }) });
  const items = [
    { ...record(101), likes: 100, published_at: '2026-10-25', rank: 0 },
    { ...record(102), likes: 90, published_at: '2026-10-25', scraped_at: '2026-10-26T05:00:00Z', rank: 999999 },
  ];
  await f.store.merge(items);
  f.sync.readItem = async id => boothToRecord({ id, name: `BOOTH item ${id}`, wish_lists_count: 300, published_at: '2026-10-25', category: { name: '3D Hair' } }, f.store.data.items.find(item => item.id === id), [], fixedNow);
  assert.equal(searchCatalog(f.store.records, [], new URLSearchParams(), fixedNow).items[0].id, 101);
  f.sync.start(); await f.sync.wait();
  assert.equal(f.sync.status().lastResult.updated, 1);
  assert.equal(f.sync.status().lastResult.failed, 0);
  assert.equal(searchCatalog(f.store.records, [], new URLSearchParams(), fixedNow).items[0].id, 102);
  const restored = await new CatalogStore(f.dir).load();
  assert.deepEqual(restored.data.items.find(item => item.id === 102).like_history.map(sample => sample.likes), [90, 300]);
  assert.equal(restored.data.items.length, 2);
});

test('automatic discovery excludes unrelated categories and preserves inaccessible existing records', async t => {
  const f = await fixture(t, { readItem: async id => {
    if (id === 101) throw new BoothRequestError('Unavailable', 'unavailable');
    return { ...record(id), category: id === 201 ? 'Illustrations' : '3D Clothing' };
  } });
  await f.sync.configure({ batchSize: 3 }); f.sync.start(); await f.sync.wait();
  const result = f.sync.status().lastResult;
  assert.equal(result.failed, 1); assert.equal(result.skipped, 1); assert.equal(result.added, 1);
  assert.equal(f.store.data.items.find(p => p.id === 101).price_jpy, 500);
  assert.ok(!f.store.data.items.some(p => p.id === 201));
  assert.ok(f.store.data.items.some(p => p.id === 202));
  assert.ok(f.sync.state.skipped[201]);
});

test('stopping a batch commits completed records and keeps unfinished IDs queued', async t => {
  let reached;
  const waiting = new Promise(resolve => reached = resolve);
  const f = await fixture(t, { readItem: async (id, { signal }) => {
    if (id === 201) { reached(); await new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true })); }
    return record(id);
  } });
  f.sync.start(); await waiting;
  assert.throws(() => f.sync.start(), /正在进行/);
  await assert.rejects(f.sync.configure({ batchSize: 5 }), /先停止/);
  await f.sync.stop();
  assert.equal(f.sync.status().lastResult.stopped, true);
  assert.equal(f.sync.status().lastResult.updated, 1);
  assert.ok(f.sync.state.pending.includes(201));
  assert.equal(f.store.data.items.length, 1);
});

test('merge failure keeps the previous catalogue and the durable pending checkpoint', async t => {
  const f = await fixture(t), before = await readFile(f.store.file, 'utf8');
  f.store.merge = async () => { throw new Error('disk full'); };
  f.sync.start(); await f.sync.wait();
  assert.match(f.sync.status().error, /保存同步状态失败/);
  assert.equal(await readFile(f.store.file, 'utf8'), before);
  const saved = JSON.parse(await readFile(f.sync.file, 'utf8'));
  assert.ok(saved.state.pending.includes(201));
  assert.ok(saved.state.pending.includes(205));
});

test('rate limits pause automatic attempts until an explicit retry', async t => {
  let now = fixedNow, blocked = true, calls = 0;
  const f = await fixture(t, { now: () => now, searchPage: async () => { calls++; if (blocked) throw new BoothRequestError('BOOTH requires verification', 'blocked'); return { ids: [201] }; } });
  await f.sync.configure({ enabled: true, intervalMinutes: 15 });
  f.sync.start(); await f.sync.wait(); assert.ok(f.sync.status().pausedReason);
  now += 3600000; await f.sync.tick(); assert.equal(calls, 1);
  blocked = false; f.sync.start(); await f.sync.wait();
  assert.equal(f.sync.status().pausedReason, ''); assert.ok(f.store.data.items.some(p => p.id === 201));
});

test('scheduled runs respect due time and other ingestion tasks', async t => {
  let now = fixedNow, busy = true;
  const f = await fixture(t, { now: () => now, canStart: () => !busy });
  await f.sync.configure({ enabled: true, intervalMinutes: 15 });
  await f.sync.tick(); assert.equal(f.requests.length, 0);
  now += 15 * 60000; await f.sync.tick(); assert.equal(f.requests.length, 0);
  busy = false; await f.sync.tick(); await f.sync.wait(); assert.equal(f.requests.length, 2);
  await f.sync.configure({ enabled: false }); now += 3600000; await f.sync.tick(); assert.equal(f.requests.length, 2);
});

test('invalid and corrupt sync configurations do not overwrite valid files or start requests', async t => {
  const f = await fixture(t); await f.sync.configure({ enabled: true });
  const before = await readFile(f.sync.file, 'utf8');
  await assert.rejects(f.sync.configure({ intervalMinutes: 1 }));
  await assert.rejects(f.sync.configure({ queries: [] }));
  assert.equal(await readFile(f.sync.file, 'utf8'), before);
  await writeFile(f.sync.file, '{invalid');
  const broken = await new PublicSync(f.dependencies).init(); t.after(() => broken.dispose());
  assert.ok(broken.status().error); assert.equal(broken.status().config.enabled, false);
  assert.throws(() => broken.start()); assert.equal(await readFile(f.sync.file, 'utf8'), '{invalid');
});

test('search parsing distinguishes real cards, empty results and validation pages', async () => {
  assert.deepEqual(parseSearchPage('<li data-product-id="201"></li><script src="/challenge-platform.js"></script><a href="/items/999">recommendation</a>'), [201]);
  assert.deepEqual(parseSearchPage('<b>Results 0 件</b>'), []);
  assert.deepEqual(parseSearchPage('<b>Results 0 件</b><li data-product-id="999" data-product-list="from market_search_search via no_result_suggest_multiline to market_item"></li>'), []);
  assert.deepEqual(parseSearchPage('<li data-product-id="201" data-product-list="from market_search_search via search_result_multiline to market_item"></li><li data-product-id="999" data-product-list="recommendations"></li>'), [201]);
  assert.throws(() => parseSearchPage('<title>Just a moment...</title>'), error => error.kind === 'blocked');
  assert.throws(() => parseSearchPage('<title>Unknown structure</title>'));
  const r = await searchBooth('兔耳', { page: 2, fetcher: async url => {
    const u = new URL(url); assert.equal(decodeURIComponent(u.pathname), '/en/search/兔耳 VRChat'); assert.equal(u.searchParams.get('page'), '2');
    return { ok: true, text: async () => '<li data-product-id="201"></li>' };
  } });
  assert.deepEqual(r.ids, [201]); assert.equal(responseError(429).kind, 'blocked'); assert.equal(responseError(404).kind, 'unavailable');
  await assert.rejects(searchBooth('VRChat', { page: 2, fetcher: async () => ({ ok: true, url: 'https://booth.pm/en/search/VRChat?sort=new', text: async () => '<li data-product-id="201"></li>' }) }), /未保留页码/);
});

test('HTTP sync controls are asynchronous, validate origin and persist configuration', async t => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'vrc-sync-http-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(path.join(dir, 'catalog.seed.json'), JSON.stringify({ items: [{ ...record(101), scraped_at: '2020-01-01' }], categories: [] }));
  const { server, sync } = await createApp({ dataDir: dir, syncDependencies: { searchPage: async () => ({ ids: [201] }), readItem: async id => record(id), pause: async () => {}, timer: false } });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(async () => { await sync.dispose(); await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const post = value => ({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(value) });
  const foreign = post({ enabled: true }); foreign.headers.origin = 'https://evil.example';
  assert.equal((await fetch(base + '/api/sync/config', foreign)).status, 403);
  assert.equal((await fetch(base + '/api/sync/config', post({ batchSize: 2 }))).status, 200);
  assert.equal((await fetch(base + '/api/sync/config', post({ queries: [] }))).status, 400);
  assert.equal((await fetch(base + '/api/sync/run', post({}))).status, 202); await sync.wait();
  const status = await (await fetch(base + '/api/sync/status')).json(); assert.equal(status.lastResult.added, 1); assert.equal(status.config.batchSize, 2);
  assert.equal((await fetch(base + '/api/sync/stop', post({}))).status, 200);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { once } from 'node:events';
import os from 'node:os';
import path from 'node:path';
import { PurchaseStore } from '../lib/purchases.mjs';
import { normalizeItem, searchCatalog } from '../lib/catalog.mjs';
import { createApp } from '../server.mjs';

const purchaseFile = products => ({ type: 'vrcatalogue-booth-purchases', schemaVersion: 1, source: 'https://accounts.booth.pm/library', products });
const post = value => ({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(value) });
const temp = async t => { const dir = await mkdtemp(path.join(os.tmpdir(), 'vrc-purchases-')); t.after(() => rm(dir, { recursive: true, force: true })); return dir; };

test('purchase imports merge by item ID, preserve curated metadata and distinguish local presence', async t => {
  const dir = await temp(t), store = await new PurchaseStore(dir).load();
  await store.merge(purchaseFile([{ id: 101, title: 'Imported older title' }, { id: 301, title: 'Purchased only' }]));
  const raw = [
    { id: 101, title: 'Curated title', price_jpy: 700, _local: { known: true, copies: 2, bytes: 500, types: ['zip'], entries: [] } },
    { id: 201, title: 'No purchase record', price_jpy: 0, _local: { known: true, copies: 0, bytes: 0, types: [], entries: [] } },
  ];
  const records = store.joinedItems(raw, true).map(item => normalizeItem(item));
  const search = query => searchCatalog(records, [], new URLSearchParams(query));
  assert.deepEqual(search('view=purchased').items.map(item => item.id).sort((a, b) => a - b), [101, 301]);
  assert.equal(records[0].title, 'Curated title');
  assert.equal(records[0].local.copies, 2);
  assert.equal(records.find(item => item.id === 301).priceKnown, false);
  assert.deepEqual(search('purchase=missing-local').items.map(item => item.id), [301]);
  assert.deepEqual(search('purchase=not-recorded').items.map(item => item.id), [201]);
  assert.deepEqual(search('purchase=recorded&availability=local').items.map(item => item.id), [101]);
  const unknown = store.joinedItems([], false).map(item => normalizeItem(item));
  assert.equal(searchCatalog(unknown, [], new URLSearchParams('purchase=missing-local')).count, 0);
  const result = await store.merge(purchaseFile([{ id: 301, title: 'Updated title' }]));
  assert.equal(result.added, 0); assert.equal(result.updated, 1); assert.equal(result.total, 2);
  const restarted = await new PurchaseStore(dir).load();
  assert.equal(restarted.status().products, 2);
  assert.equal(restarted.data.products.find(p => p.id === 301).title, 'Updated title');
});

test('purchase imports discard credentials and order details; bad batches preserve existing data', async t => {
  const dir = await temp(t), store = await new PurchaseStore(dir).load();
  await store.merge({ ...purchaseFile([{ id: 101, title: 'Test item', cookie: 'SECRET_COOKIE', downloadUrl: 'https://accounts.booth.pm/downloadables/private', address: 'SECRET_ADDRESS', image: 'https://evil.example/tracker.png' }]), account: 'SECRET_ACCOUNT', order: 'SECRET_ORDER' });
  const before = await readFile(store.file, 'utf8');
  assert.ok(!before.includes('SECRET')); assert.ok(!before.includes('downloadables')); assert.ok(!before.includes('evil.example'));
  for (const value of [purchaseFile([{ id: 102 }, { id: 'bad' }]), { items: [{ id: 102 }] }, purchaseFile([]), { ...purchaseFile([{ id: 102 }]), source: 'https://evil.example/library' }]) await assert.rejects(store.merge(value));
  assert.equal(await readFile(store.file, 'utf8'), before);
  await Promise.all([store.merge(purchaseFile([{ id: 102 }])), store.merge(purchaseFile([{ id: 103 }]))]);
  assert.equal(store.status().products, 3);
  assert.ok((await readFile(store.file + '.bak', 'utf8')).includes('102'));
});

test('corrupt purchase files are preserved and never replaced by import', async t => {
  const dir = await temp(t), file = path.join(dir, 'purchases.json');
  await writeFile(file, '{bad json');
  const store = await new PurchaseStore(dir).load();
  assert.ok(store.status().error);
  await assert.rejects(store.merge(purchaseFile([{ id: 101 }])));
  assert.equal(await readFile(file, 'utf8'), '{bad json');
});

test('purchase HTTP routes keep private records out of normal catalogue exports', async t => {
  const dir = await temp(t);
  await writeFile(path.join(dir, 'catalog.seed.json'), JSON.stringify({ categories: [], items: [{ id: 101, title: 'Public discovery', price_jpy: 100 }] }));
  const { server, store } = await createApp({ dataDir: dir });
  const before = await readFile(store.file, 'utf8');
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  const base = `http://127.0.0.1:${server.address().port}`;
  const foreign = post(purchaseFile([{ id: 301 }])); foreign.headers.origin = 'https://booth.pm';
  assert.equal((await fetch(base + '/api/purchases/import', foreign)).status, 403);
  assert.equal((await fetch(base + '/api/purchases/import', post(purchaseFile([{ id: 101 }, { id: 301, title: 'Private purchase' }])))).status, 200);
  const joined = await (await fetch(base + '/api/items?view=purchased')).json();
  assert.equal(joined.count, 2); assert.equal(joined.totalRecords, 2); assert.equal(joined.discoveryRecords, 1);
  assert.ok(joined.items.every(item => item.purchase.recorded));
  assert.equal((await (await fetch(base + '/api/items/301')).json()).purchase.recorded, true);
  const exported = await (await fetch(base + '/api/export')).json();
  assert.equal(exported.items.length, 1); assert.ok(!JSON.stringify(exported).includes('Private purchase')); assert.ok(!JSON.stringify(exported).includes('_purchase'));
  const privateExport = await (await fetch(base + '/api/purchases/export')).json();
  assert.equal(privateExport.type, 'vrcatalogue-booth-purchases'); assert.equal(privateExport.products.length, 2);
  assert.equal(await readFile(store.file, 'utf8'), before);
});

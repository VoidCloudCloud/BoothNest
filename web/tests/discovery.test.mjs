import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { once } from 'node:events';
import { normalizeItem, searchCatalog } from '../lib/catalog.mjs';
import { searchPalette } from '../lib/discovery.mjs';
import { createApp } from '../server.mjs';
import { savedFilterQuery, privateFilterQuery, normalizeSavedSearches, normalizeRecentViews, recordRecentView, validDiscoveryPreference } from '../public/discovery-state.js';

const categories = [{ slug: 'hair', en: 'Hair', children: [] }, { slug: 'clothing', en: 'Clothing', children: [] }];
const mayo = { slug: 'mayo', en: 'Mayo', ja: 'まよ', aliases: ['麻尤'], verified: true };
const raw = [
  { id: 101, title: 'まよ用 Short Hair', author: 'Alice', category: '3D Hair', tags: ['VRChat', 'Hair', '短发'], linked_avatars: [mayo], price_jpy: 500, likes: 10 },
  { id: 102, title: 'まよ用 Pink Hair', author: 'Alice', category: '3D Hair', tags: ['VRChat', 'Hair', 'Pink'], linked_avatars: [mayo], price_jpy: 1000, likes: 100 },
  { id: 103, title: 'Gothic dress', author: 'Bob', category: '3D Clothing', tags: ['VRChat', 'Dress'], price_jpy: 0 },
  { id: 104, title: 'Secret item', author: 'Hidden creator', category: '3D Clothing', tags: ['Secret tag'], is_adult: true },
];
const records = raw.map(item => normalizeItem(item, categories));
const find = query => searchCatalog(records, categories, new URLSearchParams(query));

test('tag exclusions combine with required tags, Unicode folding, categories and self-excluding facets', () => {
  assert.deepEqual(find('tag=VRChat&tag=Hair&excludeTag=Pink').items.map(item => item.id), [101]);
  assert.equal(find('tag=Hair&tag=Dress').count, 0);
  assert.deepEqual(find('excludeTag=' + encodeURIComponent('ＨＡＩＲ')).items.map(item => item.id), [103]);
  assert.equal(find('excludeTag=missing-tag').count, 3);
  assert.equal(find('tag=Hair&excludeTag=hair').count, 0);
  const result = find('category=hair&excludeTag=Pink');
  assert.equal(result.count, 1);
  assert.equal(result.facets.tags.find(tag => tag.name === 'Pink').count, 1);
  assert.equal(result.facets.categories.find(category => category.slug === 'hair').count, 1);
});

test('recent results follow the supplied history, apply filters, skip missing items and support 500 IDs', () => {
  assert.deepEqual(find('view=recent&ids=103,999,101,104&sort=likes').items.map(item => item.id), [103, 101]);
  assert.deepEqual(find('view=recent&ids=103,101&tag=Hair').items.map(item => item.id), [101]);
  assert.equal(find('view=recent').count, 0);
  const many = Array.from({ length: 160 }, (_, i) => normalizeItem({ id: i + 1, title: `Item ${i}`, tags: [] }, categories));
  const ids = many.map(item => item.id).reverse().join(',');
  const result = searchCatalog(many, categories, new URLSearchParams({ view: 'recent', ids, page: '2', pageSize: '100' }));
  assert.equal(result.count, 160); assert.equal(result.items[59].id, 1);
});

test('saved filters retain usable state, drop transient or private payloads, and resolve include/exclude conflicts', () => {
  const query = savedFilterQuery('view=local&category=hair&excludeTag=hair&tag=HAIR&max=2000&page=8&ids=101&token=secret&path=F%3A%5Cprivate&setup=sync');
  const params = new URLSearchParams(query);
  assert.equal(params.get('view'), 'local'); assert.equal(params.get('max'), '2000');
  assert.equal(params.get('excludeTag'), 'hair'); assert.equal(params.has('tag'), false);
  for (const key of ['page', 'ids', 'token', 'path', 'setup']) assert.equal(params.has(key), false);
  assert.equal(savedFilterQuery(query), query);
  assert.equal(privateFilterQuery(query), true);
  assert.equal(privateFilterQuery(savedFilterQuery('q=まよ&category=hair')), false);
  assert.deepEqual(normalizeSavedSearches([{ id: 'one', name: '  发型  ', query }, { id: 'one', name: 'duplicate', query }, null]), [{ id: 'one', name: '发型', query }]);
  assert.equal(validDiscoveryPreference('saved-searches', [{ id: 'one', name: 'Hair', query }]), true);
  assert.equal(validDiscoveryPreference('saved-searches', [{ id: 'one', name: 'Hair', query: 'token=secret' }]), false);
});

test('recent preferences deduplicate by timestamp, retain a bounded history and reject malformed records', () => {
  const now = Date.now();
  const value = [{ id: 1, at: now - 10 }, { id: 2, at: now }, { id: 1, at: now - 5 }, { id: -1, at: now }, { id: 3, at: Infinity }];
  assert.deepEqual(normalizeRecentViews(value).map(entry => entry.id), [2, 1]);
  assert.deepEqual(recordRecentView(value, 1, now + 1).map(entry => entry.id), [1, 2]);
  const many = Array.from({ length: 600 }, (_, i) => ({ id: i + 1, at: now - i }));
  assert.equal(normalizeRecentViews(many).length, 500);
  assert.equal(validDiscoveryPreference('recent-views', [{ id: 2, at: now }]), true);
  assert.equal(validDiscoveryPreference('recent-views', [{ id: '2', at: now }]), false);
});

test('quick find searches all four groups, model aliases and safe-content boundaries without local paths', () => {
  const search = q => searchPalette(records, categories, new URLSearchParams({ q }), [mayo]);
  assert.equal(search('麻尤').avatars[0].slug, 'mayo');
  assert.equal(search('Alice').authors[0].name, 'Alice');
  assert.equal(search('短发').tags[0].name, '短发');
  assert.equal(search('Pink').items[0].id, 102);
  assert.deepEqual(search('Hidden creator').authors, []);
  assert.deepEqual(search('Secret').tags, []);
  assert.equal(searchPalette(records, categories, new URLSearchParams('q=Secret&adult=all')).items[0].id, 104);
  assert.deepEqual(Object.keys(search('Pink').items[0]).sort(), ['author', 'id', 'image', 'price', 'title']);
  assert.deepEqual(search(''), { items: [], avatars: [], authors: [], tags: [] });
});

test('HTTP browsing preferences persist, merge independent updates and leave catalogue and purchases unchanged', async t => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'boothnest-discovery-'));
  await writeFile(path.join(dir, 'catalog.seed.json'), JSON.stringify({ categories, items: raw }));
  let app = await createApp({ dataDir: dir, openDataFile: '', localCandidates: [] });
  const listen = async () => { app.server.listen(0, '127.0.0.1'); await once(app.server, 'listening'); return `http://127.0.0.1:${app.server.address().port}`; };
  const close = () => new Promise(resolve => { app.server.close(resolve); app.server.closeAllConnections(); });
  let base = await listen();
  t.after(async () => { await close(); await rm(dir, { recursive: true, force: true }); });
  const post = body => ({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const before = await readFile(path.join(dir, 'catalog.json'), 'utf8');
  const purchasesBefore = await readFile(path.join(dir, 'purchases.json'), 'utf8').catch(() => null);
  assert.equal((await fetch(base + '/api/preferences', post({ favourites: [101], currency: 'CNY' }))).status, 200);
  const query = savedFilterQuery('category=hair&excludeTag=Pink&max=2000');
  const saved = [{ id: 'hair', name: '发型', query }], recent = [{ id: 101, at: Date.now() }];
  const updates = await Promise.all([
    fetch(base + '/api/preferences', post({ 'saved-searches': saved })),
    fetch(base + '/api/preferences', post({ 'recent-views': recent })),
  ]);
  assert.ok(updates.every(response => response.status === 200));
  assert.equal((await fetch(base + '/api/preferences', post({ 'recent-views': [{ id: -1, at: 1 }] }))).status, 400);
  assert.equal((await fetch(base + '/api/preferences', post({ 'saved-searches': [{ id: 'bad', name: 'Bad', query: 'path=private' }] }))).status, 400);
  assert.equal((await (await fetch(base + '/api/palette?q=Pink')).json()).items[0].id, 102);
  assert.deepEqual((await (await fetch(base + '/api/items?tag=Hair&excludeTag=Pink')).json()).items.map(item => item.id), [101]);
  await close(); app = await createApp({ dataDir: dir, openDataFile: '', localCandidates: [] }); base = await listen();
  const preferences = await (await fetch(base + '/api/preferences')).json();
  assert.deepEqual(preferences.favourites, [101]); assert.equal(preferences.currency, 'CNY');
  assert.deepEqual(preferences['saved-searches'], saved); assert.deepEqual(preferences['recent-views'], recent);
  assert.equal(await readFile(path.join(dir, 'catalog.json'), 'utf8'), before);
  assert.equal(await readFile(path.join(dir, 'purchases.json'), 'utf8').catch(() => null), purchasesBefore);
  const exported = await (await fetch(base + '/api/export')).json();
  assert.equal(JSON.stringify(exported).includes('saved-searches'), false);
  assert.equal(JSON.stringify(exported).includes('recent-views'), false);
});

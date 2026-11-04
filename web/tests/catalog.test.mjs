import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, readdir, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { normalizeItem, searchCatalog, boothId, safeImage, CatalogStore, boothToRecord } from '../lib/catalog.mjs';

const categories = [
  { slug: 'hair', en: 'Hair', children: [{ slug: 'hair--long', en: 'Long' }] },
  { slug: 'clothing', en: 'Clothing', children: [] },
  { slug: '3d-characters', en: '3D Characters', mode: 'avatars', children: [] },
];
const avatar = (slug, en, ja) => ({ slug, en, ja });
const fixtures = [
  { id: 101, title: 'まよ用 Silk HＡIR', bio: 'lilToon long hair', author: 'Alice', category: '3D Hair', price_jpy: 500, likes: 40, published_at: '2026-10-01', linked_avatars: [avatar('mayo', 'Mayo', 'まよ')], tags: ['Hair', 'VRChat'], smart_category: { category: 'Hair', sub_category: 'Long' }, rank: 1 },
  { id: 102, title: 'Gothic dress', bio: 'Modular Avatar and lilToon', author: 'Bob', category: '3D Clothing', price_jpy: 0, likes: 100, published_at: '2026-10-20', linked_avatars: [avatar('manuka', 'Manuka', 'マヌカ')], tags: ['Dress', 'VRChat'], rank: 2 },
  { id: 103, title: 'Mayo avatar', bio: 'Base avatar', author: 'Alice', category: '3D Characters', price_jpy: 5500, likes: 200, published_at: '2026-10-05', rank: 3 },
  { id: 104, title: 'Adult hair', bio: 'lilToon', category: '3D Hair', price_jpy: 1000, is_adult: true, rank: 4 },
  { id: 105, title: 'Quest hair', bio: 'lilToon', category: '3D Hair', price_jpy: 300, quest_compatible: 'Yes', rank: 5 },
];
const records = fixtures.map(item => normalizeItem(item, categories));
const search = query => searchCatalog(records, categories, new URLSearchParams(query));

test('search combines Unicode-normalized text, avatar, feature and price filters', () => {
  const result = search('q=silk+hair&avatar=mayo&feature=liltoon&min=400&max=600');
  assert.deepEqual(result.items.map(item => item.id), [101]);
  assert.equal(search('q=まよ').count, 1);
  assert.equal(search('avatar=manuka&category=hair').count, 0);
  assert.equal(search('category=hair&category=clothing').count, 3);
  assert.equal(search('feature=ma&feature=liltoon').count, 1);
  assert.equal(search('tag=VRChat&tag=Hair').count, 1);
});

test('free, adult, avatar and favourites views do not leak unrelated records', () => {
  assert.deepEqual(search('free=1').items.map(item => item.id), [102]);
  assert.equal(search('category=hair').count, 2);
  assert.equal(search('category=hair&adult=all').count, 3);
  assert.deepEqual(search('adult=adult').items.map(item => item.id), [104]);
  assert.deepEqual(search('view=avatars').items.map(item => item.id), [103]);
  assert.equal(search('view=favourites').count, 0);
  assert.deepEqual(search('view=favourites&ids=101,103').items.map(item => item.id).sort(), [101, 103]);
});

test('listing categories keep misclassified clothing and tools out of avatar views and facets', () => {
  const tree = [...categories.filter(cat => cat.slug !== '3d-characters'),
    { slug: '3d-characters', en: '3D Characters', children: [{ slug: 'characters--humanoid', en: 'Humanoid' }] }];
  const mistaken = { category: '3D Characters', sub_category: 'Humanoid', is_primary: true };
  const items = [
    { id: 201, title: 'ASTRO WATCHCAT【21アバター対応】', category: '3D Clothing', smart_category: mistaken },
    { id: 202, title: 'Local outfit', category: '3D服装', smart_categories: [mistaken, { category: 'Hair', sub_category: 'Long' }] },
    { id: 203, title: 'Avatar face tracking tool', category: 'Avatar Tools', smart_categories: [mistaken] },
    { id: 204, title: 'Character with bundled clothing', category: '3D Characters', smart_categories: [mistaken, { category: 'Clothing' }] },
  ].map(item => normalizeItem({ ...item, linked_avatars: [avatar('mayo', 'Mayo', 'まよ')] }, tree));
  assert.deepEqual(items[0].categorySlugs, ['clothing']);
  assert.deepEqual(items[0].subcategories, []);
  assert.equal(items[0].category, 'Clothing');
  assert.deepEqual(items[1].categorySlugs, ['clothing', 'hair']);
  assert.deepEqual(items[1].subcategories, ['hair--long']);
  assert.deepEqual(items[2].categorySlugs, ['avatar-systems-and-tools']);
  assert.deepEqual(items[3].categorySlugs, ['3d-characters', 'clothing']);
  const find = query => searchCatalog(items, tree, new URLSearchParams(query));
  for (const query of ['view=avatars', 'category=3d-characters', 'category=characters--humanoid']) {
    assert.deepEqual(find(query).items.map(item => item.id), [204]);
  }
  assert.equal(find('').facets.categories.find(cat => cat.slug === '3d-characters').count, 1);
  assert.deepEqual(find('category=clothing&avatar=mayo').items.map(item => item.id).sort(), [201, 202, 204]);
});

test('avatar compatibility titles and secondary tags do not establish a full avatar', () => {
  const mistaken = { category: '3D Characters' };
  const inputs = [
    { id: 211, title: '【22avatars】Full pack', smart_category: mistaken },
    { id: 212, title: 'VESPERA（複数17アバター対応）', smart_category: mistaken },
    { id: 213, title: 'Tool mentioning avatars', smart_categories: [{ category: 'Hair', sub_category: 'Long', is_primary: true }, mistaken] },
    { id: 214, title: '【2 Avatars】Original characters', category: '3D Characters', smart_category: mistaken },
    { id: 215, title: 'Original character', category: '3D Models (Other)', smart_category: mistaken },
    { id: 217, title: 'Body Stockings', category: '3D Characters', smart_category: { category: 'Clothing' } },
  ];
  const items = inputs.map(item => normalizeItem(item, categories));
  assert.deepEqual(items[0].categorySlugs, []);
  assert.equal(items[0].category, '');
  assert.deepEqual(items[1].categorySlugs, []);
  assert.deepEqual(items[2].categorySlugs, ['hair']);
  assert.deepEqual(items[5].categorySlugs, ['clothing']);
  assert.deepEqual(searchCatalog(items, categories, new URLSearchParams('view=avatars')).items.map(item => item.id).sort(), [214, 215]);
  assert.deepEqual(normalizeItem({ id: 216, title: 'Avatar accessories', category: 'Avatar Accessories' }).categorySlugs, ['avatar-accessories']);
});

test('sorting, page clamping and facets reflect the actual catalogue', () => {
  assert.deepEqual(search('sort=price-asc').items.map(item => item.price), [0, 300, 500, 5500]);
  assert.equal(search('sort=newest').items[0].id, 102);
  assert.equal(search('sort=likes').items[0].id, 103);
  const result = search('category=hair&page=999');
  assert.equal(result.page, 1);
  assert.equal(result.facets.categories.find(cat => cat.slug === 'clothing').count, 1);
  assert.equal(result.facets.features.find(feature => feature.key === 'quest').count, 1);
  assert.ok(result.items.every(item => !('_search' in item)));
});

const trendNow = Date.parse('2026-11-01T12:00:00Z');
const trending = (items, query = '') => searchCatalog(items.map(item => normalizeItem(item)), [], new URLSearchParams(query), trendNow);

test('trending admits new listings, balances recency with popularity and ignores snapshot rank', () => {
  const items = [
    { id: 101, title: 'Old bestseller', rank: 0, likes: 50000, published_at: '2020-01-01' },
    { id: 102, title: 'Recent popular release', rank: 999999, likes: 1000, published_at: '2026-10-29' },
    { id: 103, title: 'Recent quiet release', rank: 1, likes: 10, published_at: '2026-10-29' },
    { id: 104, title: 'Brand new, no interest yet', likes: 0, published_at: '2026-11-01' },
  ];
  assert.equal(trending(items).items[0].id, 102);
  assert.equal(trending(items, 'sort=likes').items[0].id, 101);
  assert.equal(trending(items, 'sort=newest').items[0].id, 104);
  assert.deepEqual(trending(items.map(item => ({ ...item, rank: 0 }))).items.map(item => item.id), trending(items).items.map(item => item.id));
  assert.equal(trending(items, 'sort=unknown').items[0].id, 102);
});

test('observed growth raises trending rank and expires without a recent observation', () => {
  const steady = { id: 101, title: 'Steady listing', likes: 1000, published_at: '2026-10-01' };
  const rising = { ...steady, id: 102, title: 'Rising listing', like_history: [{ at: '2026-10-30T12:00:00Z', likes: 100 }, { at: '2026-11-01T12:00:00Z', likes: 1000 }] };
  assert.deepEqual(trending([steady, rising]).items.map(item => item.id), [102, 101]);
  const weekLater = searchCatalog([steady, rising].map(item => normalizeItem(item)), [], new URLSearchParams(), trendNow + 8 * 86400000);
  assert.deepEqual(weekLater.items.map(item => item.id), [101, 102]);
  for (const history of [
    [{ at: '2026-11-01T11:59:00Z', likes: 0 }, { at: '2026-11-01T12:00:00Z', likes: 1000 }],
    [{ at: '2026-10-30T12:00:00Z', likes: 2000 }, { at: '2026-11-01T12:00:00Z', likes: 1000 }],
    [{ at: 'invalid', likes: 0 }, { at: '2026-11-02T12:00:00Z', likes: 1000 }],
  ]) assert.deepEqual(trending([steady, { ...rising, like_history: history }]).items.map(item => item.id), [101, 102]);
});

test('undated and future-dated listings receive no artificial recency boost; ties remain stable across pages', () => {
  const items = [
    { id: 101, title: 'Known release', likes: 100, published_at: '2026-10-30' },
    { id: 102, title: 'No date', likes: 100 },
    { id: 103, title: 'Invalid date', likes: 100, published_at: 'invalid' },
    { id: 104, title: 'Future date', likes: 100, published_at: '2027-01-01' },
  ];
  assert.equal(trending(items).items[0].id, 101);
  const ties = Array.from({ length: 45 }, (_, i) => ({ id: 200 + i, title: 'Same score', likes: 100, rank: 45 - i }));
  const ids = [1, 2, 3].flatMap(page => trending(ties.toReversed(), `page=${page}`).items.map(item => item.id));
  assert.deepEqual(ids, ties.map(item => item.id));
});

test('BOOTH refreshes bootstrap and retain bounded daily like history without fabricating observations', () => {
  let current = { id: 101, title: 'Existing', likes: 100, scraped_at: '2026-10-30T12:00:00Z', rank: 1, linked_avatars: [avatar('mayo', 'Mayo', 'まよ')] };
  const data = { id: 101, name: 'Updated', wish_lists_count: 200 };
  current = boothToRecord(data, current, [], trendNow);
  assert.deepEqual(current.like_history.map(sample => sample.likes), [100, 200]);
  assert.equal(current.linked_avatars[0].slug, 'mayo');
  const missing = boothToRecord({ ...data, wish_lists_count: null }, current, [], trendNow + 3600000);
  assert.equal(missing.likes, 200);
  assert.deepEqual(missing.like_history, current.like_history);
  const afterMissing = boothToRecord({ ...data, wish_lists_count: 250 }, missing, [], trendNow + 2 * 3600000);
  assert.ok(!afterMissing.like_history.some(sample => sample.at === missing.scraped_at));
  const unknown = boothToRecord({ id: 102, name: 'Unknown count' }, {}, [], trendNow);
  assert.deepEqual(boothToRecord({ id: 102, name: 'First real observation', wish_lists_count: 30 }, unknown, [], trendNow + 86400000).like_history.map(sample => sample.likes), [30]);
  for (let i = 1; i <= 80; i++) current = boothToRecord({ ...data, wish_lists_count: 200 + i }, current, [], trendNow + i * 6 * 3600000);
  assert.ok(current.like_history.length <= 32);
  assert.ok(current.like_history.every(sample => Date.parse(sample.at) >= Date.parse(current.scraped_at) - 14 * 86400000));
  const today = current.scraped_at.slice(0, 10);
  const todaySamples = current.like_history.filter(sample => sample.at.startsWith(today));
  assert.equal(todaySamples.length, 2);
  assert.equal(todaySamples.at(-1).likes, 280);
});

test('like history and the resulting trending order survive an atomic save and restart', async t => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'boothnest-trending-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const items = [
    { id: 101, title: 'Steady', likes: 200, published_at: '2026-10-01' },
    { id: 102, title: 'Rising', likes: 100, published_at: '2026-10-01', scraped_at: '2026-10-30T12:00:00Z' },
  ];
  await writeFile(path.join(dir, 'catalog.seed.json'), JSON.stringify({ categories: [], items }));
  const store = await new CatalogStore(dir).load();
  const record = boothToRecord({ id: 102, name: 'Rising', wish_lists_count: 200, published_at: '2026-10-01' }, items[1], [], trendNow);
  await store.merge([record]);
  const restored = await new CatalogStore(dir).load();
  assert.deepEqual(restored.data.items.find(item => item.id === 102).like_history, record.like_history);
  assert.deepEqual(searchCatalog(restored.records, [], new URLSearchParams(), trendNow).items.map(item => item.id), [102, 101]);
});

test('only BOOTH product URLs and approved preview paths are accepted', () => {
  assert.equal(boothId('https://shop.booth.pm/items/7627582'), 7627582);
  assert.equal(boothId('https://booth.pm/ja/items/7627582?x=1'), 7627582);
  for (const value of ['https://booth.pm.evil.example/items/10', 'https://127.0.0.1/items/10', 'javascript:alert(1)', '../catalog.json', '0']) assert.equal(boothId(value), null);
  assert.equal(safeImage('https://evil.example/preview.png'), '');
  assert.equal(safeImage('/media/../../catalog.json'), '');
  assert.equal(safeImage('/media/' + 'a'.repeat(32) + '.webp'), '/media/' + 'a'.repeat(32) + '.webp');
});

test('a BOOTH refresh uses current variant prices and preserves curated avatar links', () => {
  const record = boothToRecord({ id: 101, name: 'Updated hair', category: { name: '3D Hair' }, variations: [{ id: 1, name: 'single', price: 900 }, { id: 2, name: 'all', price: 1500 }], shop: { name: 'Alice' }, tags: [], images: [] }, fixtures[0]);
  assert.equal(record.price_jpy, 900);
  assert.equal(record.linked_avatars[0].slug, 'mayo');
  assert.equal(record.title, 'Updated hair');
  assert.equal(record.source, 'booth');
});

test('merges survive restart, preserve unrelated data and reject invalid batches atomically', async t => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'vrcatalogue-store-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await writeFile(path.join(dir, 'catalog.seed.json'), JSON.stringify({ categories, items: fixtures }));
  const store = await new CatalogStore(dir).load();
  await Promise.all([store.merge([{ id: 201, title: 'New hair', category: '3D Hair' }]), store.merge([{ id: 202, title: 'New dress', category: '3D Clothing' }])]);
  assert.equal(store.records.length, 7);
  const before = await readFile(store.file, 'utf8');
  await assert.rejects(store.merge([{ id: 203, title: 'Would be valid' }, { id: 'bad', title: 'Invalid' }]));
  assert.equal(await readFile(store.file, 'utf8'), before);
  assert.equal((await readdir(path.join(dir, 'backups'))).length, 2);
  const restored = await new CatalogStore(dir).load();
  assert.deepEqual(restored.records.map(item => item.id).sort(), store.records.map(item => item.id).sort());
});

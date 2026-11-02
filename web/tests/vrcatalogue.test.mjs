import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { once } from 'node:events';
import os from 'node:os';
import path from 'node:path';
import { VRCatalogueIndex } from '../lib/vrcatalogue.mjs';
import { normalizeItem, searchCatalog, boothToRecord, publicRecord } from '../lib/catalog.mjs';
import { createApp } from '../server.mjs';

async function fixture(t) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'boothnest-open-data-'));
  const closers = [];
  t.after(async () => { for (const close of closers.reverse()) await close(); assert.equal(path.dirname(dir), os.tmpdir()); await rm(dir, { recursive: true, force: true }); });
  const file = path.join(dir, 'index.sqlite');
  const db = new DatabaseSync(file);
  db.exec(`
    CREATE TABLE dataset_info(key TEXT,value TEXT);
    INSERT INTO dataset_info VALUES ('source_revision','test-revision'),('snapshot_at','2026-10-31T21:02:52Z'),('license','CC-BY-4.0'),('rows.items','2'),('rows.avatar_aliases','2');
    CREATE TABLE avatars(avatar_id INTEGER,slug TEXT,name_en TEXT,name_ja TEXT,name_ko TEXT,gender TEXT,booth_item_id INTEGER);
    INSERT INTO avatars VALUES (1,'manuka','Manuka','マヌカ','마누카','female',9991),(2,'mayo','Mayo','まよ','마요','female',9992);
    CREATE TABLE avatar_aliases(avatar_id INTEGER,alias TEXT);
    INSERT INTO avatar_aliases VALUES (1,'MANU_ALIAS'),(2,'MAYO_ALIAS');
    CREATE TABLE categories(category_id INTEGER,slug TEXT,name_en TEXT,name_ja TEXT,name_ko TEXT);
    INSERT INTO categories VALUES (1,'clothing','Clothing','衣装','의상');
    CREATE TABLE subcategories(subcategory_id INTEGER,category_id INTEGER,slug TEXT,name_en TEXT,name_ja TEXT,name_ko TEXT,group_en TEXT,group_ja TEXT,group_ko TEXT);
    INSERT INTO subcategories VALUES (1,1,'clothing--outfit-other','Other','その他の服','기타','Outfits',NULL,NULL),(2,1,'clothing--other','Other','その他','기타',NULL,NULL,NULL);
    CREATE TABLE items(item_id INTEGER,content_rating TEXT,quest_compatible TEXT,uses_liltoon TEXT,uses_poiyomi TEXT,uses_vrcfury TEXT,uses_modular_avatar TEXT);
    INSERT INTO items VALUES (101,'nsfw','n/a','yes','no',NULL,'no'),(102,'sfw','yes','no','no','no','yes');
    CREATE TABLE item_avatar_compatibility(item_id INTEGER,avatar_id INTEGER,verified INTEGER);
    INSERT INTO item_avatar_compatibility VALUES (101,1,1),(101,2,0),(102,2,0);
    CREATE TABLE item_categories(item_id INTEGER,category_id INTEGER,subcategory_id INTEGER,is_primary INTEGER);
    INSERT INTO item_categories VALUES (101,1,2,1),(102,1,1,1);
    CREATE TABLE unified_tags(unified_tag_id INTEGER,slug TEXT,name_en TEXT,name_ja TEXT,name_ko TEXT);
    INSERT INTO unified_tags VALUES (10,'magic','Magic','魔法','마법');
    CREATE TABLE tags(name TEXT,unified_tag_id INTEGER);
    INSERT INTO tags VALUES ('マジック',10),('Magical',10);
  `);
  db.close();
  return { dir, file, register: close => closers.push(close) };
}

test('read-only overlay retains live fields, separates mentions, resolves duplicate labels and unifies multilingual tags', async t => {
  const { file, register } = await fixture(t);
  const metadata = await new VRCatalogueIndex(file).init();
  register(() => metadata.close());
  const raw = { id: 101, title: 'Current title', bio: 'Modular Avatar', price_jpy: 1234, likes: 99, source: 'booth', content_rating: 'SFW',
    tags: ['マジック','Custom'], media: ['/media/'+'a'.repeat(32)+'.png'], _purchase: { recorded: true },
    like_history: [{ at: '2026-11-01T00:00:00Z', likes: 99 }], linked_avatars: [{ slug: 'manuka', en: 'Manuka', image_url: '/media/'+'b'.repeat(32)+'.png' }] };
  const before = structuredClone(raw), enriched = metadata.enrich(raw), categories = metadata.categories();
  assert.deepEqual(raw, before);
  for (const key of ['title','bio','price_jpy','likes','source','media','_purchase','like_history','tags']) assert.deepEqual(enriched[key], raw[key]);
  const item = normalizeItem(enriched, categories);
  assert.equal(item.rating, 'adult');
  assert.deepEqual(item.subcategories, ['clothing--other']);
  assert.deepEqual(item.avatars.map(a => [a.slug,a.verified]), [['manuka',true]]);
  assert.deepEqual(item.avatarMentions.map(a => [a.slug,a.verified]), [['mayo',false]]);
  assert.deepEqual(item.avatars[0].aliases, ['MANU_ALIAS']);
  assert.ok(item.features.includes('liltoon'));
  assert.ok(item.features.includes('ma'), 'an automatic negative must not erase a listing-derived feature');
  const search = query => searchCatalog([item], categories, new URLSearchParams('adult=all&'+query), Date.now(), metadata.avatars());
  assert.equal(search('avatar=mayo').count, 0);
  assert.equal(search('avatar=mayo&includeMentions=1').count, 1);
  assert.equal(search('avatar=manuka').count, 1);
  for (const tag of ['Magic','Magical','魔法','마법']) assert.equal(search('tag='+encodeURIComponent(tag)).count, 1, tag);
  assert.equal(search('q=MANU_ALIAS').count, 1);
  assert.equal(search('q=마법').count, 1);
  assert.deepEqual(search('').facets.tags.map(t => t.name).sort(), ['Custom','Magic']);
  const publicItem = publicRecord(item);
  assert.ok(!('_search' in publicItem) && !('_tagTokens' in publicItem) && !('_facetTags' in publicItem));
  assert.throws(() => metadata.db.exec('DELETE FROM items'), /read.?only|query.?only/i);
});

test('manual relations and existing smart categories take precedence; legacy records are not marked confirmed', async t => {
  const { file, register } = await fixture(t);
  const metadata = await new VRCatalogueIndex(file).init();
  register(() => metadata.close());
  const raw = { id: 101, title: 'Manual', linked_avatars: [{ slug: 'manuka', en: 'Manuka', verified: false, source: 'manual' }, { slug: 'custom', en: 'Custom' }],
    smart_categories: [{ category: 'Clothing', sub_category: 'Other', category_slug: 'clothing', subcategory_slug: 'clothing--outfit-other' }] };
  const item = normalizeItem(metadata.enrich(raw), metadata.categories());
  assert.deepEqual(item.subcategories, ['clothing--outfit-other']);
  assert.equal(item.avatarMentions.find(a => a.slug === 'manuka').source, 'manual');
  assert.equal(item.avatars.find(a => a.slug === 'custom').verified, null);
  const ambiguous = normalizeItem({ id: 999, title: 'Ambiguous', smart_category: { category: 'Clothing', sub_category: 'Other' } }, metadata.categories());
  assert.deepEqual(ambiguous.subcategories, []);
  assert.deepEqual(ambiguous.categorySlugs, ['clothing']);
  const matched = boothToRecord({ id: 999, name: 'MAYO_ALIAS outfit' }, {}, metadata.avatars());
  assert.equal(matched.linked_avatars[0].verified, false);
  assert.equal(matched.linked_avatars[0].source, 'listing-text');
});

test('HTTP views apply metadata after refresh and import without rewriting raw catalogue, purchases or preferences', async t => {
  const { dir, file, register } = await fixture(t);
  const catalog = { categories: [], items: [{ id: 101, title: 'Original listing', tags: ['マジック'], likes: 5, source: 'booth' }] };
  await writeFile(path.join(dir,'catalog.json'), JSON.stringify(catalog));
  await writeFile(path.join(dir,'web-preferences.json'), JSON.stringify({ favourites: [101] }));
  const initial = await readFile(path.join(dir,'catalog.json'),'utf8');
  const preferences = await readFile(path.join(dir,'web-preferences.json'),'utf8');
  const app = await createApp({ dataDir: dir, openDataFile: file, localCandidates: [], syncDependencies: { timer: false }, scanDependencies: { timer: false } });
  app.server.listen(0,'127.0.0.1'); await once(app.server,'listening');
  register(async () => { await app.sync.dispose(); await app.scan.dispose(); await new Promise(resolve => { app.server.close(resolve); app.server.closeAllConnections(); }); });
  const base = 'http://127.0.0.1:'+app.server.address().port;
  const get = async route => (await fetch(base+route)).json();
  const status = await get('/api/open-data');
  assert.equal(status.enabled,true); assert.equal(status.matchedItems,1); assert.equal(status.avatars,2);
  assert.equal((await get('/api/items/101')).avatars[0].verified,true);
  assert.equal((await get('/api/items?avatar=mayo&adult=all')).count,0);
  assert.equal((await get('/api/items?avatar=mayo&includeMentions=1&adult=all')).count,1);
  assert.deepEqual((await get('/api/export')).items,catalog.items);
  assert.equal(await readFile(path.join(dir,'catalog.json'),'utf8'),initial);
  const refreshed = boothToRecord({ id: 101, name: 'Refreshed title', wish_lists_count: 100, tags: ['マジック'] }, app.store.data.items[0], app.store.avatars);
  await app.store.merge([refreshed]);
  let item = await get('/api/items/101');
  assert.equal(item.title,'Refreshed title'); assert.equal(item.likes,100);
  assert.deepEqual(item.subcategories,['clothing--other']);
  assert.equal(item.avatars[0].verified,true);
  assert.ok(!app.store.data.items[0]._open_data);
  const response = await fetch(base+'/api/import',{ method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({ items:[{ id:102,title:'New import' }] }) });
  assert.equal(response.status,200);
  item = await get('/api/items/102');
  assert.ok(item.features.includes('quest') && item.features.includes('ma'));
  assert.equal(item.avatarMentions[0].verified,false);
  assert.equal((await get('/api/open-data')).matchedItems,2);
  app.scan.offline = true;
  assert.equal((await get('/api/items/101')).openData.source,'VRCatalogue Open Data');
  assert.equal((await get('/api/preferences')).favourites[0],101);
  assert.equal(await readFile(path.join(dir,'web-preferences.json'),'utf8'),preferences);
});

test('missing or damaged optional index degrades to the existing catalogue', async t => {
  const { dir } = await fixture(t);
  for (const name of ['missing.sqlite','broken.sqlite']) {
    if (name === 'broken.sqlite') await writeFile(path.join(dir,name),'not sqlite');
    const metadata = await new VRCatalogueIndex(path.join(dir,name)).init();
    assert.equal(metadata.enabled,false);
    assert.ok(metadata.status().error);
    const raw = { id: 999,title:'Still works' };
    assert.equal(metadata.enrich(raw),raw);
    assert.equal(normalizeItem(metadata.enrich(raw)).title,'Still works');
    metadata.close();
  }
});

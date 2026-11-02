import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, rm, symlink } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import os from 'node:os';
import path from 'node:path';
import { LocalLibrary } from '../lib/local-library.mjs';
import { normalizeItem, searchCatalog } from '../lib/catalog.mjs';
import { createApp } from '../server.mjs';

const categories = [
  { slug: 'hair', en: 'Hair', children: [] },
  { slug: 'clothing', en: 'Clothing', children: [] },
];
const discovery = [
  { id: 101, title: 'Curated hair', category: '3D Hair', price_jpy: 500, linked_avatars: [{ slug: 'mayo', en: 'Mayo', ja: 'まよ' }] },
  { id: 201, title: 'Discovery only', category: '3D Clothing', price_jpy: 0 },
];
const post = body => ({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });

async function fixture(t) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'vrc-local-inventory-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const home = path.join(dir, 'BoothNest'), root = path.join(dir, 'downloads'), app = path.join(dir, 'app');
  await Promise.all([mkdir(path.join(home, 'data'), { recursive: true }), mkdir(path.join(home, 'cache', 'images'), { recursive: true }), mkdir(root), mkdir(app)]);
  const imageUrl = 'https://booth.pximg.net/c/72x72_a2_g5/test/image.jpg';
  const key = createHash('md5').update(imageUrl).digest('hex') + '.jpg';
  const image = path.join(home, 'cache', 'images', key);
  const filename = path.join(home, 'data', 'dataset.json'), config = path.join(home, 'config.json');
  const dataset = {
    schema: 2, generated: '2026-10-28T01:00:00Z', root,
    products: [
      { id: '101', title: 'Older title', cat_main: '3D发型' },
      { id: '102', title: 'Local dress', cat_main: '3D服装', avatars: ['Mayo まよ'], thumbnail: imageUrl, price_min: null },
      { id: '103', title: 'Metadata without entries', cat_main: '未分类' },
      { id: '105', title: 'Ignored', cat_main: '未分类' },
    ],
    items: [
      { folder: 'hair.zip', product_id: '101', size: 100, mtime: 100 },
      { folder: 'hair.v1.00', is_dir: true, product_id: '101', bytes: 200, mtime: 200 },
      { folder: 'dress.unitypackage', product_id: '102', size: 500, mtime: 300 },
      { folder: 'unknown.zip', product_id: null, size: 5 },
      { folder: 'ignored.zip', product_id: '105', ignored: true, size: 10 },
    ],
  };
  await Promise.all([writeFile(filename, JSON.stringify(dataset)), writeFile(config, JSON.stringify({ root })), writeFile(image, Buffer.from([255, 216, 255, 217])), writeFile(path.join(root, 'hair.zip'), 'file'), mkdir(path.join(root, 'hair.v1.00'))]);
  const hashes = async () => Promise.all([filename, config, image].map(async file => createHash('sha256').update(await readFile(file)).digest('hex')));
  return { dir, home, root, app, filename, config, dataset, image, key, hashes };
}

test('read-only join deduplicates by ID and uses actual non-ignored associations', async t => {
  const f = await fixture(t), before = await f.hashes();
  const local = await new LocalLibrary({ settingsFile: path.join(f.app, 'local.json'), candidates: [path.join(f.dir, 'missing'), f.home] }).init();
  assert.equal(local.status().products, 2);
  assert.equal(local.status().unidentified, 1);
  assert.equal(local.status().ignored, 1);
  const joined = await local.joinedItems(discovery);
  assert.deepEqual(joined.map(item => item.id), [101, 201, 102]);
  assert.equal(joined[0].title, 'Curated hair');
  assert.equal(joined[0]._local.copies, 2);
  assert.equal(joined[0]._local.bytes, 300);
  assert.deepEqual(joined[0]._local.types, ['zip', 'folder']);
  assert.equal(joined[1]._local.known, true);
  assert.equal(joined[1]._local.copies, 0);
  assert.equal(joined[2].linked_avatars[0].slug, 'mayo');
  assert.equal(joined[2].media[0], '/api/local/image?key=' + f.key);
  const records = joined.map(item => normalizeItem(item, categories));
  const query = params => searchCatalog(records, categories, new URLSearchParams(params));
  assert.deepEqual(query('view=local').items.map(item => item.id), [101, 102]);
  assert.deepEqual(query('availability=missing').items.map(item => item.id), [201]);
  assert.deepEqual(query('fileType=zip&duplicates=1&minBytes=250').items.map(item => item.id), [101]);
  assert.deepEqual(query('view=local&localCategory=3D服装&avatar=mayo').items.map(item => item.id), [102]);
  assert.equal(query('localCategory=未分类').count, 0);
  assert.equal(query('category=clothing&view=local').count, 1);
  assert.deepEqual(query('view=local&sort=local-size').items.map(item => item.id), [102, 101]);
  assert.deepEqual(query('view=local&sort=local-newest').items.map(item => item.id), [102, 101]);
  assert.deepEqual(query('view=local&sort=local-copies').items.map(item => item.id), [101, 102]);
  assert.equal(query('q=hair.zip').count, 1);
  assert.deepEqual(query('free=1').items.map(item => item.id), [201]);
  assert.deepEqual(query('sort=price-asc').items.map(item => item.id), [201, 101, 102]);
  assert.equal(query('max=9999&view=local').count, 1);
  await local.refresh(true);
  assert.deepEqual(await f.hashes(), before);
});

test('failed connection preserves source; disconnect and missing snapshots give unknown presence', async t => {
  const f = await fixture(t), settingsFile = path.join(f.app, 'local.json');
  const local = await new LocalLibrary({ settingsFile }).init();
  await local.connect(f.home);
  const previous = await readFile(settingsFile, 'utf8');
  const bad = path.join(f.dir, 'bad.json'); await writeFile(bad, '{}');
  await assert.rejects(local.connect(bad));
  assert.equal(local.status().connected, true);
  assert.equal(await readFile(settingsFile, 'utf8'), previous);
  await writeFile(f.filename, 'invalid'); await local.refresh(true);
  assert.equal(local.status().connected, false);
  assert.ok((await local.joinedItems(discovery)).every(item => !item._local.known));
  await writeFile(f.filename, JSON.stringify(f.dataset)); await local.refresh(true);
  assert.equal(local.status().connected, true);
  await local.disconnect();
  const unknown = (await local.joinedItems(discovery)).map(item => normalizeItem(item, categories));
  assert.ok(unknown.every(item => !item.local.known));
  assert.equal(searchCatalog(unknown, categories, new URLSearchParams('availability=missing')).count, 0);
  const restarted = await new LocalLibrary({ settingsFile, candidates: [f.home] }).init();
  assert.equal(restarted.status().connected, false);
});

test('a remote-only public cover falls back to the existing BoothNest image cache', async t => {
  const f = await fixture(t);
  const local = await new LocalLibrary({ settingsFile: path.join(f.app, 'local.json'), candidates: [f.home] }).init();
  const remote = 'https://booth.pximg.net/new-unavailable-cover.jpg';
  const joined = await local.joinedItems([{ id: 102, title: 'Refreshed dress', media: [remote] }]);
  assert.deepEqual(joined.find(item => item.id === 102).media, ['/api/local/image?key=' + f.key, remote]);
});

test('Explorer reveal only accepts associated existing entries inside the scan root', async t => {
  const f = await fixture(t), calls = [];
  const escapeFile = path.join(f.dir, 'outside.zip'); await writeFile(escapeFile, 'outside');
  const escapeFolder = path.relative(f.root, escapeFile);
  await mkdir(path.join(f.dir, 'outside-folder'));
  await symlink(path.join(f.dir, 'outside-folder'), path.join(f.root, 'linked'), process.platform === 'win32' ? 'junction' : 'dir');
  f.dataset.items.push({ folder: escapeFolder, product_id: '102' }, { folder: 'linked', product_id: '102' });
  await writeFile(f.filename, JSON.stringify(f.dataset));
  const local = await new LocalLibrary({ settingsFile: path.join(f.app, 'local.json'), candidates: [f.home], reveal: async (...args) => calls.push(args) }).init();
  await local.locate(101, 'hair.zip'); await local.locate(101, 'hair.v1.00');
  assert.deepEqual(calls, [[path.join(f.root, 'hair.zip'), false], [path.join(f.root, 'hair.v1.00'), true]]);
  await assert.rejects(local.locate(102, 'hair.zip'), /不属于/);
  await assert.rejects(local.locate(102, 'dress.unitypackage'), /已移动/);
  await assert.rejects(local.locate(102, escapeFolder), /之外/);
  await assert.rejects(local.locate(102, 'linked'), /之外/);
  assert.equal(calls.length, 2);
});

test('HTTP local routes serve cache and filters while exports omit private inventory', async t => {
  const f = await fixture(t), before = await f.hashes(), revealed = [];
  await writeFile(path.join(f.app, 'catalog.seed.json'), JSON.stringify({ categories, items: discovery }));
  const { server } = await createApp({ dataDir: f.app, localCandidates: [f.home], localReveal: async target => revealed.push(target) });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  const base = `http://127.0.0.1:${server.address().port}`;
  const result = await (await fetch(base + '/api/items?view=local')).json();
  assert.equal(result.totalRecords, 3); assert.equal(result.discoveryRecords, 2); assert.equal(result.count, 2);
  const image = await fetch(base + '/api/local/image?key=' + f.key);
  assert.equal(image.status, 200); assert.equal(image.headers.get('content-type'), 'image/jpeg');
  assert.equal((await fetch(base + '/api/local/image?key=../../config.json')).status, 404);
  assert.equal((await fetch(base + '/api/local/reveal', post({ id: 101, folder: 'hair.zip' }))).status, 200);
  assert.deepEqual(revealed, [path.join(f.root, 'hair.zip')]);
  const foreign = post({}); foreign.headers.origin = 'https://foreign.example';
  assert.equal((await fetch(base + '/api/local/disconnect', foreign)).status, 403);
  const exported = await (await fetch(base + '/api/export')).json();
  assert.deepEqual(exported.items.map(item => item.id), [101, 201]);
  assert.ok(!JSON.stringify(exported).includes('hair.zip'));
  assert.ok(!JSON.stringify(exported).includes(f.root));
  assert.equal((await fetch(base + '/api/local/disconnect', post({}))).status, 200);
  assert.equal((await (await fetch(base + '/api/items?availability=missing')).json()).count, 0);
  assert.equal((await fetch(base + '/api/local/connect', post({ path: f.home }))).status, 200);
  assert.equal((await fetch(base + '/api/local/reload', post({}))).status, 200);
  assert.deepEqual(await f.hashes(), before);
});

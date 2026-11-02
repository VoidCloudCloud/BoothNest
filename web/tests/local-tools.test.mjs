import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm, link, symlink } from 'node:fs/promises';
import { once } from 'node:events';
import { createHash } from 'node:crypto';
import path from 'node:path';
import os from 'node:os';
import { LocalLibrary } from '../lib/local-library.mjs';
import { LocalTools, csvCell } from '../lib/local-tools.mjs';
import { verifyContent } from '../lib/content-check.mjs';
import { createApp } from '../server.mjs';

export async function toolsFixture(t) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'vrc-tools-'));
  t?.after(() => rm(dir, { force: true, recursive: true }));
  const home = path.join(dir, 'source'), root = path.join(dir, 'downloads'), app = path.join(dir, 'app');
  await Promise.all([mkdir(path.join(home, 'data'), { recursive: true }), mkdir(root), mkdir(app)]);
  const filename = path.join(home, 'data', 'dataset.json');
  const dataset = { generated: '2026-10-28T00:00:00Z', root,
    products: [{ id: '101', title: 'Test hair', shop: 'Creator', cat_main: '3D发型', avatars: ['Mayo'], published_at: '2024-01-01' }],
    items: [{ folder: 'hair.zip', name: 'hair', product_id: '101', size: 100, n_files: 1, ids_strong: ['101'], how: 'name ID' },
      { folder: 'hair-old.zip', product_id: '101', size: 100, n_files: 1 },
      { folder: '=unknown.zip', product_id: null, size: 50, n_files: 1 },
      { folder: 'ignore.zip', ignored: true, product_id: null, size: 20, n_files: 1 }] };
  await writeFile(filename, JSON.stringify(dataset));
  await Promise.all(dataset.items.map((item, i) => writeFile(path.join(root, item.folder), i < 2 ? 'identical' : `file${i}`)));
  await writeFile(path.join(app, 'catalog.seed.json'), JSON.stringify({ categories: [], items: [{ id: 101, title: 'Test hair', category: '3D Hair' }] }));
  const local = await new LocalLibrary({ settingsFile: path.join(app, 'local-library.json'), candidates: [home], reveal: async () => {} }).init();
  const tools = await new LocalTools(local, app).init(); t?.after(() => tools.dispose());
  return { dir, home, root, app, filename, dataset, local, tools };
}

test('inventory management includes unrecognized/ignored entries, full filtered CSV and honest breakdowns', async t => {
  const f = await toolsFixture(t), list = await f.tools.list(new URLSearchParams('pageSize=1'));
  assert.equal(list.rows.length, 1); assert.equal(list.count, 4);
  assert.deepEqual(list.counts, { all: 4, matched: 2, unidentified: 1, ignored: 1, manual: 0, multiple: 2 });
  assert.equal((await f.tools.list(new URLSearchParams('status=unidentified'))).rows[0].folder, '=unknown.zip');
  assert.equal((await f.tools.list(new URLSearchParams('q=CREATOR'))).count, 2);
  const stats = await f.tools.stats(); assert.equal(stats.products, 1); assert.equal(stats.entries, 4); assert.equal(stats.bytes, 270);
  assert.equal(stats.categories[0].products, 1); assert.equal(stats.categories[0].entries, 2);
  const csv = await f.tools.exportRows(new URLSearchParams('pageSize=1&status=matched'));
  assert.equal(csv.trim().split('\r\n').length, 3);
  assert.equal((await f.tools.exportRows(new URLSearchParams('q=NO_MATCH'))).trim().split('\r\n').length, 1);
  assert.ok((await f.tools.exportRows(new URLSearchParams())).includes("'=unknown.zip"));
  assert.equal(csvCell('  =SUM(1)'), '"\'  =SUM(1)"'); assert.equal(csvCell('a,"b'), '"a,""b"');
});

test('single and batch web corrections survive restart and reset to source without changing source or downloads', async t => {
  const f = await toolsFixture(t), source = await readFile(f.filename), hashes = async () => Promise.all(f.dataset.items.map(async r => createHash('sha256').update(await readFile(path.join(f.root, r.folder))).digest('hex'))), before = await hashes();
  await f.tools.override({ context: f.tools.context(), folders: ['hair.zip', '=unknown.zip'], action: 'bind', id: 'https://demo.booth.pm/items/999999' });
  assert.equal(f.local.status().products, 2); assert.equal(f.local.status().unidentified, 0);
  assert.equal((await f.local.joinedItems([])).find(r => r.id === 999999)._local.copies, 2);
  const restarted = await new LocalLibrary({ settingsFile: path.join(f.app, 'local-library.json'), candidates: [f.home] }).init();
  assert.equal(restarted.current.associations.get(999999).length, 2);
  await f.tools.override({ context: f.tools.context(), folders: ['hair.zip'], action: 'unmatch' }); assert.equal(f.local.status().unidentified, 1);
  await f.tools.override({ context: f.tools.context(), folders: ['hair.zip'], action: 'ignore' }); assert.equal(f.local.status().ignored, 2);
  await f.tools.override({ context: f.tools.context(), folders: ['hair.zip', '=unknown.zip'], action: 'reset' });
  assert.deepEqual((await f.tools.list()).counts, { all: 4, matched: 2, unidentified: 1, ignored: 1, manual: 0, multiple: 2 });
  assert.deepEqual(await readFile(f.filename), source); assert.deepEqual(await hashes(), before);
  assert.ok(await readFile(path.join(f.app, 'local-overrides.json.bak')));
});

test('stale contexts and invalid batches cannot modify another library or partially change rules', async t => {
  const f = await toolsFixture(t), context = f.tools.context();
  await assert.rejects(f.tools.override({ context, folders: ['hair.zip', 'missing'], action: 'ignore' }));
  await assert.rejects(readFile(path.join(f.app, 'local-overrides.json')), { code: 'ENOENT' });
  await f.tools.override({ context, folders: ['hair.zip'], action: 'ignore' });
  const saved = await readFile(path.join(f.app, 'local-overrides.json'));
  await assert.rejects(f.tools.override({ context, folders: ['hair-old.zip'], action: 'ignore' }), /变化/);
  f.dataset.generated = 'new scan'; await writeFile(f.filename, JSON.stringify(f.dataset)); await f.local.refresh(true);
  await assert.rejects(f.tools.override({ context, folders: ['hair-old.zip'], action: 'bind', id: 'https://evil.test/items/101' }));
  assert.deepEqual(await readFile(path.join(f.app, 'local-overrides.json')), saved);
  const other = path.join(f.dir, 'other'); await mkdir(path.join(other, 'data'), { recursive: true }); await writeFile(path.join(other, 'data', 'dataset.json'), JSON.stringify({ ...f.dataset, root: f.dir }));
  await f.local.connect(other); assert.equal(f.local.status().ignored, 1);
  await f.local.connect(f.home); assert.equal(f.local.status().ignored, 2);
});

test('corrupt private correction files are preserved and edits fail closed', async t => {
  const f = await toolsFixture(t), filename = path.join(f.app, 'local-overrides.json'); await writeFile(filename, '{broken');
  const local = await new LocalLibrary({ settingsFile: path.join(f.app, 'local-library.json'), candidates: [f.home] }).init();
  const tools = await new LocalTools(local, f.app).init(); assert.ok((await tools.list()).curationError);
  await assert.rejects(tools.override({ context: tools.context(), folders: ['hair.zip'], action: 'ignore' }), /无法读取/);
  assert.equal(await readFile(filename, 'utf8'), '{broken'); assert.equal(local.status().products, 1);
});

test('content verification compares bytes, deduplicates overlapping entries, accounts for hardlinks and skips escape links', async t => {
  const f = await toolsFixture(t);
  await mkdir(path.join(f.root, 'nested')); await writeFile(path.join(f.root, 'nested', 'a.bin'), 'identical');
  await link(path.join(f.root, 'nested', 'a.bin'), path.join(f.root, 'nested', 'hard.bin'));
  const outside = path.join(f.dir, 'outside'); await mkdir(outside); await writeFile(path.join(outside, 'secret.bin'), 'identical');
  await symlink(outside, path.join(f.root, 'linked'), process.platform === 'win32' ? 'junction' : 'dir');
  const result = await verifyContent({ root: f.root, folders: ['hair.zip', 'hair-old.zip', 'nested', 'nested/a.bin', 'linked', '../outside'] });
  assert.equal(result.enumerated, 4); assert.equal(result.groups.length, 1);
  const group = result.groups[0]; assert.equal(group.files.length, 4); assert.equal(group.distinctFiles, 3); assert.equal(group.hardlinkPaths, 1); assert.equal(group.extraBytes, 18);
  assert.equal(group.hash, createHash('sha256').update('identical').digest('hex')); assert.equal(result.warningCount, 2);
  assert.ok(group.files.every(f => !f.includes('linked') && !f.includes('outside')));
});

test('content verification discards changing files and is cancellable during reads', async t => {
  const f = await toolsFixture(t); let changed = false;
  const result = await verifyContent({ root: f.root, folders: ['hair.zip', 'hair-old.zip'], checkpoint: async folder => { if (!changed) { changed = true; await writeFile(path.join(f.root, folder), 'CHANGED!!'); } } });
  assert.equal(result.groups.length, 0); assert.equal(result.warningCount, 1);
  const controller = new AbortController();
  await assert.rejects(verifyContent({ root: f.root, folders: ['hair.zip', 'hair-old.zip'], signal: controller.signal, checkpoint: async () => controller.abort() }), { name: 'AbortError' });
});

test('background check preserves last completed result on cancel, persists across restart and invalidates after rescan', async t => {
  const f = await toolsFixture(t); await f.tools.start({ context: f.tools.context() }); await f.tools.promise;
  assert.equal(f.tools.checkStatus().result.groups.length, 1);
  const saved = await readFile(f.tools.filename);
  f.tools.verifier = async ({ signal }) => { await new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true })); };
  await f.tools.start({ context: f.tools.context() }); await assert.rejects(f.tools.start({ context: f.tools.context() }), /运行中/);
  await assert.rejects(f.tools.override({ context: f.tools.context(), folders: ['hair.zip'], action: 'ignore' }), /进行中/);
  f.tools.stop(); await f.tools.promise;
  assert.equal(f.tools.checkStatus().stopped, true); assert.equal(f.tools.checkStatus().result.groups.length, 1); assert.deepEqual(await readFile(f.tools.filename), saved);
  const restarted = await new LocalTools(f.local, f.app).init(); assert.equal(restarted.checkStatus().result.groups.length, 1);
  f.dataset.items[0].size++; await writeFile(f.filename, JSON.stringify(f.dataset)); await f.local.refresh(true);
  assert.equal(restarted.checkStatus().stale, true); assert.equal(restarted.checkStatus().result, null);
  assert.throws(() => restarted.exportCheck(), /没有当前/);
});

test('HTTP local tools enforce origin, context and inventory membership; normal exports remain private', async t => {
  const f = await toolsFixture(t), reveal = [];
  const { server, localTools } = await createApp({ dataDir: f.app, localCandidates: [f.home], localReveal: async target => reveal.push(target) });
  server.listen(0, '127.0.0.1'); await once(server, 'listening'); const base = `http://127.0.0.1:${server.address().port}`;
  t.after(async () => { await localTools.dispose(); await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }); });
  const post = (body, origin) => ({ method: 'POST', headers: { 'content-type': 'application/json', ...(origin ? { origin } : {}) }, body: JSON.stringify(body) });
  const list = await (await fetch(base + '/api/local/manage')).json(); assert.equal(list.count, 4); assert.ok(!Object.hasOwn(list, 'allRows'));
  assert.equal((await fetch(base + '/api/local/override', post({}, 'https://evil.test'))).status, 403);
  assert.equal((await fetch(base + '/api/local/override', post({ action: 'ignore', folders: ['hair.zip'] }))).status, 409);
  assert.equal((await fetch(base + '/api/local/entry-reveal', post({ context: list.context, folder: '../outside' }))).status, 400);
  assert.equal((await fetch(base + '/api/local/entry-reveal', post({ context: list.context, folder: '=unknown.zip' }))).status, 200);
  assert.equal(reveal.length, 1);
  assert.equal((await fetch(base + '/api/local/check/start', post({ context: list.context }))).status, 202); await localTools.promise;
  const exported = await (await fetch(base + '/api/local/check.csv')).text(); assert.ok(exported.includes('SHA-256')); assert.ok(exported.includes('hair.zip'));
  const ordinary = await (await fetch(base + '/api/export')).text(); assert.ok(!ordinary.includes('hair.zip')); assert.ok(!ordinary.includes(f.root.replaceAll('\\', '\\\\')));
});

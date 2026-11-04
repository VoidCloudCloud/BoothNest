import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rename, rm } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { once } from 'node:events';
import { setTimeout as delay } from 'node:timers/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import os from 'node:os';
import { createApp } from '../server.mjs';
import { EngineClient, ENGINE_METHODS } from '../lib/engine-client.mjs';
const exec = promisify(execFile);
const python = process.env.BOOTH_NEST_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const post = body => ({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
async function fixture(t) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'boothnest-scan-')), root = path.join(dir, '中文 downloads'), home = path.join(dir, 'engine'), data = path.join(dir, 'web');
  await Promise.all([mkdir(root), mkdir(path.join(home, 'cache', 'items'), { recursive: true }), mkdir(data)]);
  await exec(python, ['-c', 'import sys,zipfile; z=zipfile.ZipFile(sys.argv[1],"w"); z.writestr("asset/readme.txt","test"); z.close()', path.join(root, 'Hair-1234567.zip')]);
  await writeFile(path.join(root, 'unknown.txt'), 'unknown');
  await writeFile(path.join(home, 'config.json'), JSON.stringify({ root, options: { offline: true } }));
  for (const id of [1234567,7654321]) await writeFile(path.join(home, 'cache', 'items', `${id}.json`), JSON.stringify({ id, name: `Hair ${id}`, shop: { name: 'Fixture creator', subdomain: 'fixture' }, category: { name: '3D髪型' }, variations: [{ name: 'default', price: 500 }], tags: [{ name: 'VRChat' }], images: [] }));
  let now = Date.now();
  const app = await createApp({ dataDir: data, localCandidates: [], engineHome: home, scanDependencies: { now: () => now, timer: false } });
  app.server.listen(0, '127.0.0.1'); await once(app.server, 'listening'); const base = `http://127.0.0.1:${app.server.address().port}`;
  t.after(async () => { await app.scan.dispose(); await new Promise(resolve => { app.server.close(resolve); app.server.closeAllConnections(); }); await delay(100); await rm(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); });
  return { ...app, dir, root, home, data, base, advance: ms => now += ms };
}
async function completed(scan) {
  for (let i = 0; i < 300; i++) { const result = await scan.status(); if (result.task.finished && !result.task.busy) { assert.equal(result.task.result.ok, true, JSON.stringify(result.task)); return result; } await delay(25); }
  throw new Error('Scan did not complete');
}
test('actual BoothNest incremental/full scans parse ZIP clues, preserve rules and share corrections across both interfaces', async t => {
  const f = await fixture(t);
  assert.equal((await fetch(f.base + '/api/scan/start', post({ root: f.root, offline: true }))).status, 202);
  let state = await completed(f.scan); assert.equal(state.state.offline, true); assert.equal(f.local.status().connected, true);
  assert.equal(f.local.status().entries, 2); assert.equal(f.local.status().products, 1);
  const original = await readFile(path.join(f.root, 'Hair-1234567.zip'));
  const list = await f.localTools.list(); const unknown = list.rows.find(row => !row.id);
  await f.localTools.override({ context: list.context, folders: [unknown.folder], action: 'bind', id: '7654321' });
  let engineRows = await f.scan.classic('get_items', []); assert.equal(engineRows.rows.find(r => r.folder === unknown.folder).pid, '7654321');
  await f.scan.start({ full: true }); await completed(f.scan);
  assert.equal(f.local.current.associations.get(7654321).length, 1);
  await f.scan.classic('set_item_override', [[unknown.folder], 'ignore', '']);
  assert.equal((await f.localTools.list()).counts.ignored, 1);
  await f.scan.classic('set_item_override', [[unknown.folder], 'reset', '']);
  assert.equal((await f.localTools.list()).counts.unidentified, 1);
  assert.deepEqual(await readFile(path.join(f.root, 'Hair-1234567.zip')), original);
  assert.ok(await readFile(path.join(f.home, 'data', 'dataset.json.bak')));
});
test('scheduled incremental scans trigger when due, persist settings and reject invalid configuration without losing inventory', async t => {
  const f = await fixture(t); await f.scan.start(); await completed(f.scan);
  await f.scan.configure({ enabled: true, intervalMinutes: 5 }); const before = await f.scan.engine.call('poll');
  f.advance(299999); await f.scan.tick(); assert.equal((await f.scan.engine.call('poll')).task_id, before.task_id);
  await writeFile(path.join(f.root, 'New-7654321.txt'), 'new asset'); f.advance(2); await f.scan.tick();
  await completed(f.scan); assert.equal(f.local.status().products, 2);
  const saved = await readFile(f.scan.file); await assert.rejects(f.scan.configure({ intervalMinutes: 1 })); assert.deepEqual(await readFile(f.scan.file), saved);
  const inventory = await readFile(path.join(f.home, 'data', 'dataset.json'));
  await assert.rejects(f.scan.start({ root: path.join(f.dir, 'missing') })); assert.deepEqual(await readFile(path.join(f.home, 'data', 'dataset.json')), inventory);
});
test('two nested products keep their identities and byte totals when scanning their parent directory (issue #1)', async t => {
  const f = await fixture(t), category = path.join(f.root, '化身');
  await mkdir(category);
  const alpha = path.join(category, 'Alpha-1234567.zip'), beta = path.join(category, 'Beta-7654321.zip');
  await rename(path.join(f.root, 'Hair-1234567.zip'), alpha);
  await rm(path.join(f.root, 'unknown.txt'));
  await exec(python, ['-c', 'import sys,zipfile; z=zipfile.ZipFile(sys.argv[1],"w"); z.writestr("asset/readme.txt","beta synthetic"*20); z.close()', beta]);
  const originals = new Map([[alpha, await readFile(alpha)], [beta, await readFile(beta)]]);
  await f.scan.start({ root: category, offline: true }); await completed(f.scan);
  const direct = JSON.parse(await readFile(path.join(f.home, 'data', 'dataset.json'), 'utf8'));
  await f.scan.start({ root: f.root, offline: true }); await completed(f.scan);
  const parent = JSON.parse(await readFile(path.join(f.home, 'data', 'dataset.json'), 'utf8'));
  const totals = dataset => dataset.products.map(product => [product.id, product.local_bytes]).sort();
  assert.deepEqual(totals(parent), totals(direct));
  assert.deepEqual(totals(parent), [['1234567', originals.get(alpha).length], ['7654321', originals.get(beta).length]]);
  assert.equal(parent.totProds, 2); assert.equal(parent.totItems, 2);
  assert.deepEqual(parent.items.map(item => item.folder).sort(), ['化身/Alpha-1234567.zip', '化身/Beta-7654321.zip']);
  const items = await (await fetch(f.base + '/api/items?view=local&adult=all')).json();
  assert.equal(items.count, 2); assert.deepEqual(items.items.map(item => item.id).sort(), [1234567, 7654321]);
  for (const [file, bytes] of originals) assert.deepEqual(await readFile(file), bytes);
});

test('classic management retains all original API capabilities with authenticated same-origin calls and complete exports', async t => {
  const f = await fixture(t); await f.scan.start(); await completed(f.scan);
  const html = await (await fetch(f.base + '/classic')).text(); const token = /name="booth-session" content="([^"]+)"/.exec(html)[1];
  const request = async (method, args = []) => (await fetch(f.base + '/api/' + method, { ...post({ args }), headers: { 'content-type': 'application/json', 'x-boothnest-token': token } })).json();
  assert.equal((await fetch(f.base + '/api/get_state', post({ args: [] }))).status, 403);
  const workerMethods = await exec(python, ['-c', 'from boothlib.server import ALLOWED; import json; print(json.dumps(sorted(ALLOWED)))'], { cwd: fileURLToPath(new URL('../engine', import.meta.url)) });
  assert.deepEqual([...ENGINE_METHODS].sort(), JSON.parse(workerMethods.stdout));
  for (const method of ['get_state','get_products','get_summary','get_items','get_unidentified','get_duplicates','thumb_stats','app_info','get_duplicate_check']) assert.equal((await request(method)).ok ?? true, true, method);
  for (const dim of ['category','avatar','shop','year','sub','none']) assert.equal((await request('get_groups', [dim])).ok, true);
  const exported = await request('export_excel'); assert.equal(exported.ok, true); assert.ok(exported.count >= 10);
  const filtered = await request('export_filtered', ['products', [], 'empty']); assert.equal(filtered.ok, true);
  assert.equal((await request('set_preferences', [{ bs_view: 'table', bs_sort: 'mtime_desc' }])).ok, true);
  assert.equal((await request('get_state')).preferences.bs_view, 'table');
  assert.equal((await request('clear_cache')).ok, true);
});

test('desktop startup reconnects its existing engine inventory when web connection settings are absent', async t => {
  const f = await fixture(t); await f.scan.start(); await completed(f.scan);
  const second = await createApp({ dataDir: path.join(f.dir, 'fresh-web'), engineHome: f.home, scanDependencies: { timer: false } });
  t.after(async () => { second.sync.dispose(); await second.scan.dispose(); await second.localTools.dispose(); });
  assert.equal(second.local.status().connected, true);
  assert.equal(second.local.status().products, 1);
  assert.equal(second.local.status().entries, 2);
  assert.equal(second.local.current.home, f.home);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { once } from 'node:events';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { createOnlineApp } from '../online.mjs';

async function fixture(t, prepare = async () => {}) {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'boothnest-website-'));
  const dataDir = path.join(temp, 'home', 'web'), engineHome = path.join(temp, 'home');
  await mkdir(dataDir, { recursive: true });
  await prepare({ temp, dataDir, engineHome });
  const app = await createOnlineApp({ user: 'fixture-user', password: 'fixture-pass', allowedHosts: 'website.test',
    dataDir, engineHome, syncDependencies: { timer: false }, scanDependencies: { timer: false } });
  app.server.listen(0, '127.0.0.1'); await once(app.server, 'listening');
  t.after(async () => {
    await app.sync.dispose(); await app.scan.dispose(); await app.localTools.dispose();
    await new Promise(resolve => { app.server.close(resolve); app.server.closeAllConnections(); });
    assert.equal(path.dirname(temp), os.tmpdir());
    await rm(temp, { recursive: true, force: true });
  });
  const auth = 'Basic ' + Buffer.from('fixture-user:fixture-pass').toString('base64');
  const request = (route, { authorized = true, host = 'website.test', method = 'GET', headers = {}, body } = {}) => new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: app.server.address().port, path: route, method,
      headers: { host, ...(authorized ? { authorization: auth } : {}), ...headers } }, res => {
      let text = ''; res.setEncoding('utf8'); res.on('data', value => text += value);
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text }));
    }); req.on('error', reject); req.end(body);
  });
  return { app, temp, dataDir, engineHome, request };
}

test('website authenticates content and validates the external host and origin', async t => {
  const { request } = await fixture(t);
  for (const route of ['/', '/app.js', '/online-client.js', '/api/items', '/api/export', '/classic']) {
    assert.equal((await request(route, { authorized: false })).status, 401, route);
  }
  assert.equal((await request('/healthz', { authorized: false })).status, 200);
  assert.equal((await request('/api/ping', { host: 'other.test' })).status, 403);
  assert.equal((await request('/api/ping', { headers: { authorization: 'Basic wrong' } })).status, 401);
  for (const headers of [{ origin: 'https://other.test' }, { 'sec-fetch-site': 'cross-site' }]) {
    assert.equal((await request('/api/ping', { headers })).status, 403);
  }
  assert.equal((await request('/api/ping', { headers: { origin: 'https://website.test' } })).status, 200);
  assert.match((await request('/')).text, /online-client\.js/);
  assert.match((await request('/classic')).text, /nonce="[a-f0-9]+" src="\/online-client.js"/);
  for (const route of ['/api/scan/pick', '/api/open_path', '/api/shutdown', '/api/purchases/bridge/pair']) {
    assert.equal((await request(route, { method: 'POST' })).status, 409, route);
  }
});

test('code-only website starts with an empty catalogue and no automatic data collection', async t => {
  const { app, request, dataDir } = await fixture(t);
  const items = JSON.parse((await request('/api/items?adult=all')).text);
  assert.equal(items.count, 0); assert.deepEqual(items.items, []);
  assert.equal(app.sync.status().config.enabled, false);
  assert.equal(app.sync.status().running, false);
  assert.equal(app.local.status().connected, false);
  assert.equal(JSON.parse((await request('/api/open-data')).text).enabled, false);
  assert.deepEqual(JSON.parse(await readFile(path.join(dataDir, 'catalog.json'), 'utf8')).items, []);
  assert.deepEqual(JSON.parse((await request('/api/export')).text).items, []);
});

test('website upgrade reads an existing library without replacing its catalogue, purchases, preferences or cached files', async t => {
  const before = new Map();
  const { request, dataDir } = await fixture(t, async ({ temp, dataDir, engineHome }) => {
    const files = {
      [path.join(engineHome, 'config.json')]: JSON.stringify({ root: temp, options: { offline: true } }),
      [path.join(engineHome, 'data', 'dataset.json')]: JSON.stringify({ schema: 2, root: temp,
        products: [{ id: '101', title: 'Saved item' }], items: [{ folder: 'fixture.zip', product_id: '101', size: 20 }] }),
      [path.join(dataDir, 'catalog.json')]: JSON.stringify({ source: 'existing', categories: [], items: [{ id: 101, title: 'Saved item', likes: 9 }] }),
      [path.join(dataDir, 'purchases.json')]: JSON.stringify({ schemaVersion: 1, products: [{ id: 101, title: 'Saved purchase' }] }),
      [path.join(dataDir, 'web-preferences.json')]: JSON.stringify({ language: 'en', favourites: [101] }),
      [path.join(dataDir, 'public-sync.json')]: JSON.stringify({ schemaVersion: 1, config: { enabled: false }, state: { cursorVersion: 2, pending: [202] } }),
      [path.join(dataDir, 'media', 'a'.repeat(32) + '.png')]: 'synthetic cached image bytes',
      [path.join(temp, 'fixture.zip')]: 'synthetic original download bytes',
    };
    for (const [file, text] of Object.entries(files)) {
      await mkdir(path.dirname(file), { recursive: true }); await writeFile(file, text); before.set(file, text);
    }
  });
  const items = JSON.parse((await request('/api/items?adult=all')).text);
  assert.equal(items.count, 1); assert.equal(items.items[0].title, 'Saved item');
  const local = JSON.parse((await request('/api/local/status')).text);
  assert.equal(local.connected, true); assert.equal(local.entries, 1);
  assert.deepEqual(JSON.parse((await request('/api/preferences')).text).favourites, [101]);
  assert.equal(JSON.parse((await request('/api/export')).text).items[0].title, 'Saved item');
  for (const [file, text] of before) assert.equal(await readFile(file, 'utf8'), text, file);
  assert.equal(JSON.parse(await readFile(path.join(dataDir, 'catalog.json'), 'utf8')).source, 'existing');
});

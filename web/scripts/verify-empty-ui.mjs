import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdtemp, rm, mkdir, writeFile } from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { createOnlineApp } from '../online.mjs';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = process.env.WEBSITE_UI_ARTIFACTS;
const temp = await mkdtemp(path.join(os.tmpdir(), 'boothnest-empty-ui-'));
const probe = net.createServer(); probe.listen(0, '127.0.0.1'); await once(probe, 'listening');
const port = probe.address().port; await new Promise(resolve => probe.close(resolve));
const app = await createOnlineApp({ user: 'fixture-user', password: 'fixture-pass',
  allowedHosts: `127.0.0.1:${port}`, dataDir: path.join(temp, 'web'), localCandidates: [], openDataFile: null,
  syncDependencies: { timer: false }, scanDependencies: { timer: false } });
app.server.listen(port, '127.0.0.1'); await once(app.server, 'listening');
let browser;
const errors = [], checks = [];
try {
  browser = await chromium.launch({ headless: true,
    ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : process.platform === 'win32' ? { channel: 'msedge' } : {}),
    args: ['--no-sandbox'] });
  const context = await browser.newContext({ httpCredentials: { username: 'fixture-user', password: 'fixture-pass' }, viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
  const base = `http://127.0.0.1:${port}`;
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.locator('.local-badge').filter({ hasText: 'ONLINE' }).waitFor();
  await page.waitForFunction(() => document.querySelector('#grid')?.getAttribute('aria-busy') === 'false');
  assert.equal(await page.locator('.product-card').count(), 0);
  assert.equal((await (await context.request.get(base + '/api/items')).json()).count, 0);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  checks.push('desktop empty website, online adapter and no horizontal overflow');
  if (output) { await mkdir(output, { recursive: true }); await page.screenshot({ path: path.join(output, 'desktop-empty.png'), fullPage: true }); }
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  checks.push('mobile empty website without horizontal overflow');
  if (output) await page.screenshot({ path: path.join(output, 'mobile-empty.png'), fullPage: true });
  await page.goto(base + '/classic', { waitUntil: 'domcontentloaded' });
  await page.locator('link[href="/online.css"]').waitFor({ state: 'attached' });
  checks.push('classic manager loads with the online adapter');
  assert.deepEqual(errors, []);
  if (output) await writeFile(path.join(output, 'verification.json'), JSON.stringify({ checks, pageErrors: errors, catalogueItems: 0 }, null, 2));
  console.log(JSON.stringify({ checks, pageErrors: errors, catalogueItems: 0 }));
} finally {
  await browser?.close(); await app.sync.dispose(); await app.scan.dispose(); await app.localTools.dispose();
  await new Promise(resolve => { app.server.close(resolve); app.server.closeAllConnections(); });
  assert.equal(path.dirname(temp), os.tmpdir()); await rm(temp, { recursive: true, force: true });
}

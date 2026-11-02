import { createHash, timingSafeEqual } from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { createApp } from './server.mjs';

const root = fileURLToPath(new URL('.', import.meta.url));
const version = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8')).version;
const digest = value => createHash('sha256').update(value).digest();
const reply = (res, status, value, headers = {}) => {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff', ...headers });
  res.end(JSON.stringify(value));
};

export async function createOnlineApp(options = {}) {
  const user = options.user ?? process.env.BOOTH_NEST_USER ?? process.env.BOOTH_SHELF_USER;
  const password = options.password ?? process.env.BOOTH_NEST_PASS ?? process.env.BOOTH_SHELF_PASS;
  if (!user || !password) throw new Error('Set BOOTH_NEST_USER and BOOTH_NEST_PASS before starting the online website.');
  const expected = digest('Basic ' + Buffer.from(user + ':' + password).toString('base64'));
  const allowedHosts = new Set((options.allowedHosts ?? process.env.BOOTH_NEST_ALLOWED_HOSTS ?? 'localhost:8010,127.0.0.1:8010').split(',').map(s => s.trim().toLowerCase()).filter(Boolean));
  const dataDir = options.dataDir ?? process.env.BOOTH_NEST_WEB_HOME ?? path.join(root, 'data');
  // Updates ship no seed files. Existing user data is read in place by createApp.
  const engineHome = options.engineHome ?? process.env.BOOTH_NEST_ENGINE_HOME;
  const app = await createApp({ ...options, dataDir, engineHome,
    ...(!engineHome ? { localCandidates: options.localCandidates ?? [] } : {}) });
  const handler = app.server.listeners('request')[0];
  app.server.removeAllListeners('request');
  const unavailable = new Set(['/api/scan/pick', '/api/pick_root', '/api/open_path', '/api/open_url', '/api/reveal_item', '/api/reveal_verified_file', '/api/local/reveal', '/api/local/entry-reveal', '/api/local/check/reveal', '/api/shutdown', '/api/window_closed']);
  app.server.on('request', async (req, res) => {
    try {
      const host = (req.headers.host || '').toLowerCase();
      if (!allowedHosts.has(host) || !req.url?.startsWith('/') || req.url.startsWith('//')) return reply(res, 403, { error: '请求地址无效。' });
      const url = new URL(req.url, 'http://' + host);
      if (['GET', 'HEAD'].includes(req.method) && url.pathname === '/healthz') return reply(res, 200, { ok: true, app: 'BoothNest', version });
      if (!timingSafeEqual(digest(req.headers.authorization || ''), expected)) return reply(res, 401, { error: '需要登录。' }, { 'www-authenticate': 'Basic realm="BoothNest", charset="UTF-8"' });
      if (req.headers.origin && !['http://' + host, 'https://' + host].includes(req.headers.origin)) return reply(res, 403, { error: '请求来源无效。' });
      if (req.headers['sec-fetch-site'] === 'cross-site') return reply(res, 403, { error: '请求来源无效。' });
      if (req.method === 'GET' && url.pathname === '/api/server/session') return reply(res, 200, { enabled: true, version, root: process.env.BOOTH_NEST_DOWNLOAD_ROOT || '/downloads' });
      if (unavailable.has(url.pathname) || url.pathname.startsWith('/api/purchases/bridge/')) return reply(res, 409, { ok: false, error: '请通过服务器管理下载目录；商品链接会在当前浏览器中打开。' });
      req.headers.host = 'localhost';
      if (req.headers.origin) req.headers.origin = 'http://localhost';
      if (url.pathname === '/classic' && req.method === 'GET') {
        const end = res.end;
        res.end = function(chunk, ...args) {
          if (chunk) {
            let html = chunk.toString();
            const nonce = /<script nonce="([^"]+)"/.exec(html)?.[1];
            if (nonce) html = html.replace('</head>', `<link rel="stylesheet" href="/online.css"><script nonce="${nonce}" src="/online-client.js" defer></script></head>`);
            chunk = html;
          }
          return end.call(this, chunk, ...args);
        };
      }
      return await handler(req, res);
    } catch (error) {
      console.error(error);
      if (!res.headersSent) reply(res, 500, { error: '在线服务暂时无法处理请求，请重试。' }); else res.end();
    }
  });
  return app;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const app = await createOnlineApp();
  const port = Number(process.env.PORT || 8010);
  app.server.listen(port, '0.0.0.0', () => console.log(`BoothNest ${version} website on :${port}; catalogue=${app.store.records.length}`));
  let stopping = false;
  async function stop() {
    if (stopping) return; stopping = true;
    await app.sync.stop(); await app.scan.dispose(); await app.localTools.dispose();
    app.server.close(); app.server.closeAllConnections();
    setTimeout(() => process.exit(0), 200).unref();
  }
  process.on('SIGTERM', stop); process.on('SIGINT', stop);
}

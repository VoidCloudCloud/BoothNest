import { DatabaseSync } from 'node:sqlite';
import { access, stat, mkdir, readFile, writeFile, rename, readdir } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import path from 'node:path';

const archivePattern = /^\/media\/boothdex\/([a-f0-9]{40})\.webp$/;
const legacyPattern = /^https:\/\/cdn\.vrcatalogue\.com\/booth\/([a-f0-9]{40})\.webp(?:\?.*)?$/;
const proxyPattern = /^\/media\/boothdex\/item\/([1-9]\d{0,9})\/(\d{1,2})$/;
export function validSupplementImage(value) {
  if (typeof value !== 'string') return '';
  if (archivePattern.test(value)) return value;
  try { const u = new URL(value); return u.protocol === 'https:' && ['booth.pximg.net','booth.p.pixiv.net','pixiv.pximg.net'].includes(u.hostname) && !u.username && !u.password && !u.port ? u.href : ''; } catch { return ''; }
}

// A read-only public-image overlay. Never rewrites the owner's catalogue or personal records.
export class ImageSupplement {
  constructor(folder, { cacheDir = path.join(folder,'remote'), fetcher = fetch } = {}) { this.folder = folder; this.cacheDir = cacheDir; this.fetcher = fetcher; this.enabled = false; this.cache = new Map(); this.error = ''; this.pending = new Map(); this.active = 0; this.waiters = []; this.cachedImages = new Set(); }
  async init() {
    try {
      await access(path.join(this.folder, 'index.sqlite'));
      this.db = new DatabaseSync(path.join(this.folder, 'index.sqlite'), { readOnly: true, enableExtensions: false });
      this.db.exec('PRAGMA query_only=ON; PRAGMA trusted_schema=OFF;');
      this.query = this.db.prepare('SELECT id,title,author,adult,images FROM item_images WHERE id=?');
      this.info = Object.fromEntries(this.db.prepare('SELECT key,value FROM info').all().map(row => [row.key,row.value]));
      try { this.cachedImages = new Set((await readdir(this.cacheDir)).filter(name => /^[a-f0-9]{64}\.json$/.test(name)).map(name => name.slice(0,-5))); } catch {}
      this.enabled = true;
    } catch (error) { this.close(); if (error.code !== 'ENOENT') this.error = 'Image supplement unavailable'; }
    return this;
  }
  lookup(id) {
    if (!this.enabled || !Number.isSafeInteger(Number(id)) || Number(id) <= 0) return null;
    id = Number(id);
    if (this.cache.has(id)) return this.cache.get(id);
    const row = this.query.get(id);
    let result = null;
    if (row) {
      try {
        const images = JSON.parse(row.images);
        if (Array.isArray(images)) result = { id, title: String(row.title || '').slice(0,1200), shop: String(row.author || '').slice(0,300),
          adult: !!row.adult, images: [...new Set(images.map(validSupplementImage).filter(Boolean))].slice(0,100),
          fetchedAt: this.info.snapshot_at || '', source: this.info.source || 'BoothDex public data' };
      } catch {}
    }
    if (this.cache.size >= 20000) this.cache.delete(this.cache.keys().next().value);
    this.cache.set(id,result); return result;
  }
  media(id, existing = [], { proxy = false, offline = false } = {}) {
    const next = this.lookup(id)?.images || [];
    const original = (Array.isArray(existing) ? existing : []).filter(value => typeof value === 'string');
    const converted = original.map(value => {
      const hash = legacyPattern.exec(value)?.[1];
      return hash && next.includes('/media/boothdex/' + hash + '.webp') ? '/media/boothdex/' + hash + '.webp' : value;
    });
    // Obsolete VRCatalogue links are retained only when there is no usable indexed replacement.
    const merged = [...new Set([...converted.filter(value => !next.length || !value.startsWith('https://cdn.vrcatalogue.com/')), ...next])].slice(0,100);
    if (!proxy) return merged;
    return merged.flatMap(value => {
      const index = next.indexOf(value);
      if (index < 0 || value.startsWith('/')) return [value];
      if (offline && !this.cachedImages.has(this.imageKey(value))) return [];
      return ['/media/boothdex/item/'+id+'/'+index];
    });
  }
  enrich(raw, { offline = false } = {}) { return { ...raw, ...(this.lookup(Number(raw.id))?.adult ? { is_adult: true } : {}), media: this.media(Number(raw.id), raw.media, { proxy: true, offline }) }; }
  imageKey(url) { return createHash('sha256').update(url).digest('hex'); }
  async remote(url) {
    const key = this.imageKey(url), file = path.join(this.cacheDir,key+'.bin'), meta = path.join(this.cacheDir,key+'.json');
    try { const info = JSON.parse(await readFile(meta,'utf8')); const size = (await stat(file)).size; if (size === info.size && ['image/jpeg','image/png','image/webp','image/gif','image/avif'].includes(info.type)) return {file,size,type:info.type}; } catch {}
    if (this.pending.has(key)) return this.pending.get(key);
    if (this.waiters.length >= 72) throw new Error('Preview queue full');
    const promise = (async () => {
      if (this.active >= 3) await new Promise(resolve => this.waiters.push(resolve));
      this.active++;
      try {
        const response = await this.fetcher(url,{redirect:'error',credentials:'omit',headers:{'user-agent':'BoothNest/2.0 (public preview cache)'},signal:AbortSignal.timeout(25000)});
        const type = (response.headers.get('content-type') || '').split(';')[0];
        if (!response.ok || !['image/jpeg','image/png','image/webp','image/gif','image/avif'].includes(type) || Number(response.headers.get('content-length')) > 12000000) throw new Error('Preview unavailable');
        const parts = []; let size = 0;
        for await (const chunk of response.body) { size += chunk.length; if (size > 12000000) throw new Error('Preview too large'); parts.push(chunk); }
        if (!size) throw new Error('Empty preview');
        await mkdir(this.cacheDir,{recursive:true}); const tmp=file+'.'+randomUUID()+'.tmp';
        await writeFile(tmp,Buffer.concat(parts)); await rename(tmp,file); await writeFile(meta,JSON.stringify({size,type})); this.cachedImages.add(key);
        return {file,size,type};
      } finally { this.active--; this.waiters.shift()?.(); }
    })().finally(() => this.pending.delete(key));
    this.pending.set(key,promise); return promise;
  }
  async serve(req, res, pathname) {
    const proxy = proxyPattern.exec(pathname);
    if (proxy && this.enabled && ['GET','HEAD'].includes(req.method)) {
      const value = this.lookup(Number(proxy[1]))?.images[Number(proxy[2])];
      if (!value || !value.startsWith('https://')) return false;
      try {
        const image = await this.remote(value);
        res.writeHead(200,{'content-type':image.type,'content-length':image.size,'cache-control':'public, max-age=604800'});
        if (req.method === 'HEAD') res.end();
        else { const stream=createReadStream(image.file);stream.on('error',()=>res.destroy());stream.pipe(res); }
      } catch { res.writeHead(502,{'content-type':'text/plain','cache-control':'no-store'});res.end('Preview unavailable'); }
      return true;
    }
    const match = archivePattern.exec(pathname);
    if (!match || !this.enabled || !['GET','HEAD'].includes(req.method)) return false;
    try {
      const file = path.join(this.folder,'images',match[1]+'.webp');
      const info = await stat(file);
      if (!info.isFile()) return false;
      res.writeHead(200,{'content-type':'image/webp','content-length':info.size,'cache-control':'public, max-age=31536000, immutable'});
      if (req.method === 'HEAD') res.end();
      else { const stream = createReadStream(file); stream.on('error',() => res.destroy()); stream.pipe(res); }
      return true;
    } catch { return false; }
  }
  status() { return { enabled: this.enabled, items: Number(this.info?.items || 0), archivedImages: Number(this.info?.archived_images || 0), snapshotAt: this.info?.snapshot_at || '', error: this.error }; }
  close() { this.enabled = false; try { this.db?.close(); } catch {} this.db = null; this.cache.clear(); }
}

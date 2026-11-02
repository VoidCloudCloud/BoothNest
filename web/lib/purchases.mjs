import { readFile, writeFile, mkdir, rename, copyFile } from 'node:fs/promises';
import path from 'node:path';
import { boothId, safeImage } from './catalog.mjs';

const clean = (value, limit = 500) => typeof value === 'string' ? value.trim().slice(0, limit) : '';
const sources = new Set(['https://accounts.booth.pm/library', 'https://booth.pm/library']);
export function validatePurchaseImport(body) {
  if (body?.type !== 'vrcatalogue-booth-purchases' || body.schemaVersion !== 1 || !sources.has(body.source)
      || !Array.isArray(body.products) || !body.products.length || body.products.length > 50000) {
    throw new Error('请选择 BOOTH 下载库采集工具导出的已购 JSON，或下载库保存的 HTML 网页。');
  }
  const products = new Map();
  for (const value of body.products) {
    const id = boothId(value?.id);
    if (!id) throw new Error('已购清单中包含无效商品 ID，未修改已有记录。');
    let shopUrl = '';
    try { const u = new URL(value.shopUrl); if (u.protocol === 'https:' && u.hostname.endsWith('.booth.pm') && u.hostname !== 'accounts.booth.pm') shopUrl = u.href; } catch {}
    // Only retain item metadata. Orders, credentials, account identity and download URLs are never stored.
    products.set(id, { id, title: clean(value.title) || `BOOTH #${id}`, shop: clean(value.shop), shopUrl,
      image: safeImage(value.image), isAdult: value.isAdult === true, source: body.source });
  }
  return [...products.values()];
}

export class PurchaseStore {
  constructor(dataDir) { this.file = path.join(dataDir, 'purchases.json'); this.data = { schemaVersion: 1, products: [] }; this.revision = 0; this.cache = null; this.queue = Promise.resolve(); this.error = ''; }
  async load() {
    try {
      const data = JSON.parse(await readFile(this.file, 'utf8'));
      if (data.schemaVersion !== 1 || !Array.isArray(data.products)) throw new Error('invalid');
      const products = data.products.length ? validatePurchaseImport({ ...data, type: 'vrcatalogue-booth-purchases', source: 'https://accounts.booth.pm/library' }) : [];
      const previous = new Map(data.products.map(p => [Number(p.id), p]));
      this.data = { schemaVersion: 1, updatedAt: clean(data.updatedAt, 100), products: products.map(p => ({ ...p, importedAt: clean(previous.get(p.id)?.importedAt, 100) })) };
    } catch (error) { if (error.code !== 'ENOENT') this.error = '已购记录无法读取，已保留原文件；请检查备份后重试。'; }
    this.revision++; return this;
  }
  status() { return { products: this.data.products.length, updatedAt: this.data.updatedAt || '', error: this.error, basis: 'user-library-import' }; }
  async merge(body) {
    const incoming = validatePurchaseImport(body);
    const operation = this.queue.then(async () => {
      if (this.error) throw new Error(this.error);
      const timestamp = new Date().toISOString();
      const products = new Map(this.data.products.map(p => [p.id, p]));
      let added = 0;
      for (const product of incoming) { if (!products.has(product.id)) added++; products.set(product.id, { ...product, importedAt: timestamp }); }
      const next = { schemaVersion: 1, updatedAt: timestamp, products: [...products.values()] };
      await mkdir(path.dirname(this.file), { recursive: true });
      try { await copyFile(this.file, this.file + '.bak'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
      await writeFile(this.file + '.tmp', JSON.stringify(next, null, 2)); await rename(this.file + '.tmp', this.file);
      this.data = next; this.revision++; this.cache = null;
      return { added, updated: incoming.length - added, total: products.size };
    });
    this.queue = operation.catch(() => {}); return operation;
  }
  joinedItems(items, localConnected = false) {
    if (this.cache?.items === items && this.cache.revision === this.revision && this.cache.localConnected === localConnected) return this.cache.joined;
    const purchases = new Map(this.data.products.map(p => [p.id, p]));
    const result = new Map(items.map(item => [Number(item.id), { ...item, _purchase: { recorded: purchases.has(Number(item.id)), importedAt: purchases.get(Number(item.id))?.importedAt || '' } }]));
    for (const product of purchases.values()) if (!result.has(product.id)) result.set(product.id, {
      id: product.id, title: product.title, author: product.shop, author_uri: product.shopUrl, media: product.image ? [product.image] : [],
      price_jpy: null, source: 'purchase-import', rank: 950000 + result.size, is_adult: product.isAdult,
      _local: { known: localConnected, copies: 0, bytes: 0, mtime: 0, types: [], entries: [], category: '' },
      _purchase: { recorded: true, importedAt: product.importedAt },
    });
    const joined = [...result.values()]; this.cache = { items, revision: this.revision, localConnected, joined }; return joined;
  }
}

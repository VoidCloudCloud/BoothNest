import { readFile, writeFile, rename, copyFile, access, stat, realpath } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { boothId, safeImage } from './catalog.mjs';
import { LocalCuration } from './local-curation.mjs';

const imageKey = /^[a-f0-9]{32}\.(?:jpe?g|png|webp)$/;
const fold = value => String(value ?? '').normalize('NFKC').toLowerCase();
const numeric = value => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
const text = value => typeof value === 'string' ? value : '';

export function defaultLibraryCandidates() {
  const candidates = [];
  if (process.env.BOOTH_NEST_HOME) candidates.push(process.env.BOOTH_NEST_HOME);
  if (process.env.LOCALAPPDATA) candidates.push(path.join(process.env.LOCALAPPDATA, 'BoothNest'), path.join(process.env.LOCALAPPDATA, 'BoothShelf'));
  if (process.env.USERPROFILE) candidates.push(path.join(process.env.USERPROFILE, 'BoothNest'));
  return candidates;
}

export async function resolveLibrary(input) {
  if (typeof input !== 'string' || !path.isAbsolute(input.trim())) throw new Error('请输入本地库数据目录或 dataset.json 的绝对路径。');
  const candidate = path.resolve(input.trim());
  const info = await stat(candidate).catch(() => null);
  if (!info) throw new Error('找不到这个本地库路径，请检查路径是否可访问。');
  if (info.isFile()) return candidate;
  for (const filename of [path.join(candidate, 'data', 'dataset.json'), path.join(candidate, 'dataset.json')]) {
    try { if ((await stat(filename)).isFile()) return filename; } catch {}
  }
  throw new Error('目录中没有找到 data/dataset.json 或 dataset.json。');
}

export function inspectInventory(dataset) {
  if (!dataset || !Array.isArray(dataset.products) || !Array.isArray(dataset.items) || dataset.items.length > 100000 || dataset.products.length > 50000) throw new Error('本地库不是有效的 BoothNest / BoothShelf 库存快照。');
  if (dataset.products.some(p => !p || typeof p !== 'object') || dataset.items.some(p => !p || typeof p !== 'object')) throw new Error('本地库包含无效的商品或条目。');
  const associations = new Map();
  let identified = 0, ignored = 0, totalBytes = 0;
  for (const item of dataset.items) {
    totalBytes += numeric(item.size ?? item.bytes);
    if (item.ignored) { ignored++; continue; }
    const id = boothId(item.product_id);
    const folder = text(item.folder);
    if (!id || !folder) continue;
    identified++;
    const list = associations.get(id) || [];
    list.push({ folder, bytes: numeric(item.size ?? item.bytes), files: numeric(item.n_files), mtime: numeric(item.mtime),
      type: item.is_dir === true ? 'folder' : /\.[a-z0-9]{1,12}$/i.test(folder) ? path.extname(folder).slice(1).toLowerCase() : 'folder' });
    associations.set(id, list);
  }
  const products = new Map(dataset.products.filter(p => boothId(p.id)).map(p => [Number(p.id), p]));
  // Product IDs with no current associated local entries never count as "local".
  for (const [id] of associations) if (!products.has(id)) products.set(id, { id, title: `BOOTH #${id}` });
  return { products, associations, totalBytes, identified, ignored, totalItems: dataset.items.length,
    unidentified: dataset.items.length - identified - ignored, generatedAt: text(dataset.generated) };
}

export class LocalLibrary {
  constructor({ settingsFile, candidates = [], reveal = defaultReveal } = {}) {
    this.settingsFile = settingsFile; this.candidates = candidates; this.reveal = reveal;
    this.settings = {}; this.current = null; this.revision = 0; this.lastCheck = 0; this.error = '';
    this.loading = null; this.combined = null;
    this.curation = new LocalCuration(path.join(path.dirname(settingsFile), 'local-overrides.json'));
  }
  async init() {
    await this.curation.load();
    try { this.settings = JSON.parse(await readFile(this.settingsFile, 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') { this.error = '本地库连接设置无法读取，已保留原文件。'; return this; } }
    if (this.settings.disabled) return this;
    if (this.settings.path) { await this.load(this.settings.path).catch(error => this.error = error.message); return this; }
    for (const candidate of this.candidates) {
      try { await this.load(await resolveLibrary(candidate)); break; } catch {}
    }
    return this;
  }
  async load(filename) {
    const info = await stat(filename);
    if (info.size > 32000000) throw new Error('本地库存快照超过 32 MB，暂不支持。');
    const contents = await readFile(filename, 'utf8');
    const dataset = JSON.parse(contents);
    inspectInventory(dataset);
    const home = path.basename(path.dirname(filename)).toLowerCase() === 'data' ? path.dirname(path.dirname(filename)) : path.dirname(filename);
    let config = {};
    try { config = JSON.parse(await readFile(path.join(home, 'config.json'), 'utf8')); } catch {}
    const root = text(dataset.root || config.root);
    const curationKey = this.curation.key(filename, root);
    const effective = this.curation.apply(dataset, curationKey);
    const inventory = inspectInventory(effective);
    this.current = { ...inventory, filename, home, root: path.isAbsolute(root) ? root : '',
      dataset: effective, originalDataset: dataset, curationKey,
      signature: `${info.mtimeMs}:${info.size}`, digest: createHash('sha256').update(contents).digest('hex'),
      sourceName: path.basename(home), loadedAt: new Date().toISOString(), sourceOffline: !!config.options?.offline };
    this.error = ''; this.revision++; this.combined = null;
    return this.current;
  }
  async refresh(force = false) {
    if (this.loading) return this.loading;
    if (!force && Date.now() - this.lastCheck < 1500) return;
    this.lastCheck = Date.now();
    if (!this.current && !this.settings.path) return;
    const filename = this.settings.path || this.current.filename;
    this.loading = (async () => {
      try {
        const info = await stat(filename);
        if (force || this.error || `${info.mtimeMs}:${info.size}` !== this.current?.signature) await this.load(filename);
      } catch (error) { this.error = '当前本地库快照不可读取，请重新连接或刷新。'; this.revision++; this.combined = null; }
    })().finally(() => this.loading = null);
    await this.loading;
  }
  async saveSettings(settings) {
    try { await access(this.settingsFile); await copyFile(this.settingsFile, this.settingsFile + '.bak'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    const tmp = this.settingsFile + '.tmp';
    await writeFile(tmp, JSON.stringify(settings, null, 2)); await rename(tmp, this.settingsFile); this.settings = settings;
  }
  async connect(input) {
    const filename = await resolveLibrary(input);
    // A rejected connection leaves the currently connected library in place.
    const previous = { current: this.current, error: this.error, revision: this.revision, combined: this.combined };
    try {
      await this.load(filename);
      await this.saveSettings({ path: filename, disabled: false });
    } catch (error) { Object.assign(this, previous); throw error; }
    return this.status();
  }
  async disconnect() { await this.saveSettings({ disabled: true }); this.current = null; this.error = ''; this.revision++; this.combined = null; return this.status(); }
  status() {
    const current = this.current;
    return {
      connected: !!current && !this.error, error: this.error,
      source: current?.sourceName || '', path: current?.filename || this.settings.path || '', root: current?.root || '',
      products: current && !this.error ? current.associations.size : 0,
      entries: current?.totalItems || 0, identified: current?.identified || 0,
      unidentified: current?.unidentified || 0, ignored: current?.ignored || 0,
      bytes: current?.totalBytes || 0, generatedAt: current?.generatedAt || '', loadedAt: current?.loadedAt || '',
      sourceOffline: !!current?.sourceOffline, basis: 'latest-scan',
    };
  }
  async cachedImage(url) {
    if (!url || !url.startsWith('https://booth.pximg.net/') || !this.current) return '';
    const originals = [url, url.replace(/\/c\/[^/]+\//, '/')];
    const base = originals[1];
    if (base.startsWith('https://booth.pximg.net/')) {
      originals.push(base.replace('https://booth.pximg.net/', 'https://booth.pximg.net/c/300x300_a2_g5/'));
      originals.push(base.replace('https://booth.pximg.net/', 'https://booth.pximg.net/c/72x72_a2_g5/'));
    }
    for (const candidate of new Set(originals)) {
      const key = createHash('md5').update(candidate).digest('hex') + '.jpg';
      try { await access(path.join(this.current.home, 'cache', 'images', key)); return '/api/local/image?key=' + key; } catch {}
    }
    return '';
  }
  async joinedItems(discoveryItems) {
    await this.refresh();
    if (this.combined?.source === discoveryItems && this.combined.revision === this.revision) return this.combined.items;
    const available = !!this.current && !this.error;
    const current = available ? this.current : null;
    const knownAvatars = [...new Map(discoveryItems.flatMap(item => (item.linked_avatars || []).map(a => [a.slug, a]))).values()];
    const avatarFor = label => knownAvatars.find(a => [a.en, a.ja, a.slug].filter(Boolean).some(name => {
      const n = fold(name), value = fold(label); return n.length >= 2 && (value === n || value.startsWith(n + ' ') || value.endsWith(' ' + n));
    })) || { slug: 'local-' + createHash('sha256').update(label).digest('hex').slice(0, 12), en: label };
    const localInfo = id => {
      const entries = current?.associations.get(id) || [];
      return { known: available, copies: entries.length, bytes: entries.reduce((n, e) => n + e.bytes, 0),
        mtime: Math.max(0, ...entries.map(e => e.mtime)), types: [...new Set(entries.map(e => e.type))], entries,
        category: text(current?.products.get(id)?.cat_main) || '未分类' };
    };
    const map = new Map(discoveryItems.map(item => [Number(item.id), { ...item, _local: localInfo(Number(item.id)) }]));
    if (current) {
      // A public refresh can leave a remote-only image when its CDN is unavailable.
      // Prefer an existing local cover in that case, preserving the full gallery.
      for (const [id, item] of map) {
        if (!item._local.copies || item.media?.[0]?.startsWith('/')) continue;
        const cover = await this.cachedImage(safeImage(current.products.get(id)?.thumbnail));
        if (cover) item.media = [cover, ...(item.media || [])];
      }
      let index = 0;
      for (const [id] of current.associations) {
        if (map.has(id)) continue;
        const product = current.products.get(id);
        const image = await this.cachedImage(safeImage(product.thumbnail));
        map.set(id, { id, title: text(product.title) || `BOOTH #${id}`, author: text(product.shop), author_uri: text(product.shop_url),
          category: text(product.cat_main || product.category), price_jpy: product.price_min === null || product.price_min === undefined ? null : numeric(product.price_min), likes: numeric(product.wish_lists_count),
          published_at: text(product.published_at), is_adult: !!product.is_adult, bio: '',
          tags: Array.isArray(product.tags) ? product.tags.filter(t => typeof t === 'string') : [],
          linked_avatars: (Array.isArray(product.avatars) ? product.avatars : []).filter(a => typeof a === 'string').map(avatarFor),
          media: image ? [image] : [], variations: [], source: 'local-library', rank: 1000000 + index++, _local: localInfo(id) });
      }
    }
    const items = [...map.values()];
    this.combined = { source: discoveryItems, revision: this.revision, items };
    return items;
  }
  imagePath(key) {
    if (!this.current || this.error || !imageKey.test(key || '')) return null;
    return path.join(this.current.home, 'cache', 'images', key);
  }
  async locate(id, folder) {
    await this.refresh();
    if (!this.current || this.error || !this.current.root) throw new Error('本地库未连接或没有记录有效的扫描目录。');
    const entries = this.current.associations.get(boothId(id));
    if (!entries?.some(entry => entry.folder === folder)) throw new Error('这个路径不属于当前本地库中的商品。');
    return this.locateEntry(folder);
  }
  async locateEntry(folder) {
    if (!this.current || this.error || !this.current.root) throw new Error('本地库未连接或没有记录有效的扫描目录。');
    if (!this.current.dataset.items.some(item => item.folder === folder)) throw new Error('这个路径不属于当前本地库。');
    const target = path.resolve(this.current.root, folder);
    const root = await realpath(this.current.root).catch(() => { throw new Error('扫描目录当前不可访问，请检查磁盘或网络盘连接。'); });
    const resolved = await realpath(target).catch(() => { throw new Error('该条目已移动或暂时不可访问，请在 BoothNest 重新扫描。'); });
    const relative = path.relative(root, resolved);
    if (!relative || relative.startsWith('..' + path.sep) || relative === '..' || path.isAbsolute(relative)) throw new Error('拒绝打开扫描目录之外的路径。');
    const info = await stat(resolved);
    await this.reveal(resolved, info.isDirectory());
    return { ok: true };
  }
}

function defaultReveal(filename, directory) {
  if (process.platform !== 'win32') throw new Error('本地文件定位目前仅支持 Windows。');
  return new Promise((resolve, reject) => {
    const child = spawn('explorer.exe', directory ? [filename] : ['/select,', filename], { stdio: 'ignore', shell: false });
    child.once('error', reject); child.once('spawn', resolve);
  });
}

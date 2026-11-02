import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { boothId } from './catalog.mjs';
import { savePrivateJson } from './local-curation.mjs';
import { verifyContent, inventoryPath } from './content-check.mjs';
import { stat } from 'node:fs/promises';

const fold = value => String(value ?? '').normalize('NFKC').toLowerCase();
const text = value => typeof value === 'string' ? value : '';
const number = value => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
const bad = message => Object.assign(new Error(message), { status: 409 });
export function csvCell(value) {
  let cell = String(value ?? '');
  if (/^[\s]*[=+@\-]/.test(cell) || /^[\t\r\n]/.test(cell)) cell = "'" + cell;
  return '"' + cell.replaceAll('"', '""') + '"';
}
export const csv = rows => '\ufeff' + rows.map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n';

export class LocalTools {
  constructor(local, dataDir, { verifier = verifyContent, overrideHandler } = {}) {
    this.local = local; this.filename = path.join(dataDir, 'local-content-check.json'); this.verifier = verifier;
    this.task = { running: false, phase: 'idle', error: '' }; this.result = null; this.busy = false;
    this.overrideHandler = overrideHandler;
  }
  async init() {
    try { const data = JSON.parse(await readFile(this.filename, 'utf8')); if (data.schema === 1 && Array.isArray(data.result?.groups)) this.result = data; }
    catch (error) { if (error.code !== 'ENOENT') this.task.error = '上次文件核对记录无法读取，原文件已保留。'; }
    return this;
  }
  context() {
    const c = this.local.current;
    if (!c || this.local.error) return '';
    return createHash('sha256').update(c.curationKey + ':' + c.digest + ':' + JSON.stringify(this.local.curation.rules(c.curationKey))).digest('hex');
  }
  async ready(context) {
    await this.local.refresh();
    if (!this.context()) throw bad('本地库未连接，请先在数据管理中连接。');
    if (context !== undefined && context !== this.context()) throw bad('库存或修正规则已变化，请刷新面板后重试。');
    return this.local.current;
  }
  rows() {
    const c = this.local.current;
    return c.dataset.items.map((item, index) => {
      const id = item.ignored ? null : boothId(item.product_id), p = c.products.get(id) || {};
      const original = c.originalDataset.items[index];
      return { folder: text(item.folder), name: text(item.name) || text(item.folder), id, title: text(p.title), shop: text(p.shop),
        category: text(p.cat_main || p.category) || '未分类', avatars: Array.isArray(p.avatars) ? p.avatars.filter(a => typeof a === 'string') : [],
        type: item.is_dir === true ? 'folder' : path.extname(text(item.folder)).slice(1).toLowerCase() || 'file',
        bytes: number(item.size ?? item.bytes), files: number(item.n_files), mtime: number(item.mtime),
        status: item.ignored ? 'ignored' : id ? 'matched' : 'unidentified', manual: text(item.web_manual || (c.managed ? item.manual : '')), sourceManual: text(item.manual),
        how: text(item.how), confidence: text(item.confidence), evidence: JSON.stringify({ ids: item.ids_strong, nameIds: item.ids_strong_in_name, weakIds: item.ids_weak, match: item.match_detail, original: { id: original.product_id, how: original.how, confidence: original.confidence }, webRule: item.web_manual || null }, null, 2).slice(0, 8000) };
    });
  }
  async list(params = new URLSearchParams()) {
    await this.ready(); const all = this.rows(), counts = new Map();
    for (const row of all) if (row.id) counts.set(row.id, (counts.get(row.id) || 0) + 1);
    const q = fold(params.get('q')).trim(), status = params.get('status') || 'all';
    const rows = all.filter(row => (!q || fold([row.folder, row.title, row.shop, row.id, row.how].join(' ')).includes(q)) &&
      (status === 'all' || status === row.status || status === 'manual' && !!row.manual || status === 'multiple' && counts.get(row.id) > 1));
    rows.sort(({ bytes: a, mtime: am, folder: af }, { bytes: b, mtime: bm, folder: bf }) => params.get('sort') === 'name' ? af.localeCompare(bf, 'zh-CN') : params.get('sort') === 'mtime' ? bm - am || af.localeCompare(bf) : b - a || af.localeCompare(bf));
    const pageSize = Math.min(100, Math.max(1, Math.floor(Number(params.get('pageSize')) || 50))), pages = Math.max(1, Math.ceil(rows.length / pageSize));
    const page = Math.min(pages, Math.max(1, Math.floor(Number(params.get('page')) || 1)));
    const statusCounts = { all: all.length, matched: 0, unidentified: 0, ignored: 0, manual: 0, multiple: 0 };
    for (const row of all) { statusCounts[row.status]++; if (row.manual) statusCounts.manual++; if (counts.get(row.id) > 1) statusCounts.multiple++; }
    return { context: this.context(), source: this.local.status(), curationError: this.local.curation.error, counts: statusCounts,
      rows: rows.slice((page - 1) * pageSize, page * pageSize), count: rows.length, page, pages, pageSize, allRows: rows };
  }
  async stats() {
    await this.ready(); const rows = this.rows(), products = new Set(rows.map(r => r.id).filter(Boolean));
    const group = get => {
      const groups = new Map();
      for (const row of rows) for (const label of new Set(get(row))) {
        const g = groups.get(label) || { label, entries: 0, bytes: 0, products: new Set() };
        g.entries++; g.bytes += row.bytes; if (row.id) g.products.add(row.id); groups.set(label, g);
      }
      return [...groups.values()].map(g => ({ ...g, products: g.products.size })).sort((a, b) => b.bytes - a.bytes || b.entries - a.entries);
    };
    return { context: this.context(), products: products.size, entries: rows.length, bytes: rows.reduce((n, r) => n + r.bytes, 0),
      categories: group(r => [r.category]), shops: group(r => [r.shop || '未知店铺']), types: group(r => [r.type]), avatars: group(r => r.avatars.length ? r.avatars : ['未注明']),
      years: group(r => { const date = this.local.current.products.get(r.id)?.published_at; return [/^\d{4}-/.test(date || '') ? date.slice(0, 4) : '未知']; }) };
  }
  async override(body) {
    if (this.busy || this.task.running) throw bad('文件核对或修正任务进行中，请稍后重试。');
    this.busy = true;
    try {
      const c = await this.ready(body.context);
      const result = await this.overrideHandler?.(body) ?? await this.local.curation.update(c.curationKey, c.originalDataset, body.folders, body.action, body.id);
      await this.local.load(c.filename);
      return { ...result, context: this.context(), source: this.local.status() };
    } finally { this.busy = false; }
  }
  async reveal(body) { await this.ready(body.context); return this.local.locateEntry(body.folder); }
  checkStatus() {
    const current = !!this.context() && this.result?.context === this.context();
    return { ...this.task, result: current ? this.result.result : null, stale: !!this.result && !current };
  }
  async start(body) {
    if (this.task.running || this.busy) throw bad('已有本地管理任务运行中。');
    // Reserve before refreshing, since multiple tabs can submit concurrently.
    this.busy = true;
    try {
      const c = await this.ready(body.context), context = this.context();
      if (!c.root) throw new Error('库存未记录扫描目录，无法核对文件。');
      this.controller = new AbortController();
      this.task = { running: true, phase: 'enumerating', enumerated: 0, done: 0, total: 0, readBytes: 0, totalBytes: 0, error: '', stopped: false };
      this.promise = (async () => {
        try {
          const result = await this.verifier({ root: c.root, folders: c.dataset.items.map(i => i.folder).filter(f => typeof f === 'string'), signal: this.controller.signal,
            progress: update => Object.assign(this.task, update) });
          this.controller.signal.throwIfAborted(); await this.local.refresh(true);
          if (context !== this.context()) throw new Error('库存已变化，本次结果未采用，请重新核对。');
          const next = { schema: 1, context, result };
          await savePrivateJson(this.filename, next); this.result = next;
          this.task.phase = 'done';
        } catch (error) {
          this.task.stopped = this.controller.signal.aborted;
          this.task.phase = this.task.stopped ? 'stopped' : 'error';
          this.task.error = this.task.stopped ? '' : error.message;
        } finally { this.task.running = false; }
      })();
      return this.checkStatus();
    } finally { this.busy = false; }
  }
  stop() { if (this.task.running) this.controller.abort(); return this.checkStatus(); }
  async dispose() { this.stop(); await this.promise; }
  async revealChecked(body) {
    const c = await this.ready(body.context), result = this.checkStatus().result;
    if (!result?.groups.some(g => g.files.includes(body.folder))) throw bad('该路径不在当前核对结果中。');
    const target = await inventoryPath(c.root, body.folder);
    await this.local.reveal(target, (await stat(target)).isDirectory()); return { ok: true };
  }
  async exportRows(params) {
    const { allRows } = await this.list(params);
    return csv([['相对路径', '商品 ID', '名称', '店铺', '分类', '条目类型', '字节', '文件数', '本地修改时间', '状态', '网页修正', '识别方式'], ...allRows.map(r => [r.folder, r.id, r.title, r.shop, r.category, r.type, r.bytes, r.files, r.mtime ? new Date(r.mtime * 1000).toISOString() : '', r.status, r.manual, r.how])]);
  }
  exportCheck() {
    const result = this.checkStatus().result;
    if (!result) throw bad('没有当前库存的文件核对结果。');
    return csv([['SHA-256', '单文件字节', '不同文件数', '硬链接额外路径', '额外逻辑字节', '相对路径', '核对时间'], ...result.groups.flatMap(g => g.files.map(f => [g.hash, g.bytes, g.distinctFiles, g.hardlinkPaths, g.extraBytes, f, result.checkedAt]))]);
  }
}

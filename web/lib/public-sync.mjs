import { readFile, writeFile, mkdir, copyFile, rename } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import path from 'node:path';
import { boothId } from './catalog.mjs';
import { is3dListing } from './booth.mjs';

const defaults = { enabled: false, queries: ['VRChat'], intervalMinutes: 60, batchSize: 24, refreshHours: 24 };
const integer = (value, min, max) => Number.isInteger(Number(value)) && Number(value) >= min && Number(value) <= max;
export function syncConfig(input, previous = defaults) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('同步配置格式无效。');
  const next = { ...previous };
  if ('enabled' in input) { if (typeof input.enabled !== 'boolean') throw new Error('自动同步开关格式无效。'); next.enabled = input.enabled; }
  if ('queries' in input) {
    const list = typeof input.queries === 'string' ? input.queries.split(/[\n,，]+/) : input.queries;
    if (!Array.isArray(list) || !list.length || list.length > 5 || list.some(q => typeof q !== 'string' || q.trim().length < 2 || q.trim().length > 100)) throw new Error('请填写 1–5 个关键词，每个 2–100 字。');
    next.queries = [...new Set(list.map(q => q.trim()))];
  }
  for (const [key, min, max] of [['intervalMinutes', 15, 1440], ['batchSize', 1, 60], ['refreshHours', 1, 720]]) if (key in input) {
    if (!integer(input[key], min, max)) throw new Error(`${key} 必须是 ${min}–${max} 之间的整数。`);
    next[key] = Number(input[key]);
  }
  return next;
}

export class PublicSync {
  constructor({ dataDir, store, searchPage, readItem, pause = (ms, signal) => delay(ms, undefined, { signal }), now = () => Date.now(), timer = true, canStart = () => true } = {}) {
    this.file = path.join(dataDir, 'public-sync.json'); this.store = store; this.searchPage = searchPage; this.readItem = readItem; this.pause = pause; this.now = now; this.useTimer = timer; this.canStart = canStart;
    this.config = { ...defaults }; this.state = { cursorVersion: 2, cursors: {}, pending: [], skipped: {}, queryIndex: 0, nextRunAt: '', lastResult: null, pausedReason: '' };
    this.active = null; this.phase = 'idle'; this.progress = { processed: 0, total: 0, id: null }; this.error = ''; this.queue = Promise.resolve();
  }
  async init() {
    try {
      const data = JSON.parse(await readFile(this.file, 'utf8'));
      this.config = syncConfig(data.config);
      if (data.schemaVersion !== 1 || !data.state || !Array.isArray(data.state.pending) || data.state.pending.length > 5000) throw new Error('invalid');
      this.state = { ...this.state, ...data.state, pending: [...new Set(data.state.pending.map(boothId).filter(Boolean))], cursors: data.state.cursors || {}, skipped: data.state.skipped || {} };
      if (data.state.cursorVersion !== 2) { this.state.cursors = {}; this.state.queryIndex = 0; this.state.cursorVersion = 2; }
    } catch (error) { if (error.code !== 'ENOENT') { this.error = '自动同步配置无法读取，已保留原文件。'; this.config.enabled = false; } }
    if (this.useTimer) { this.timer = setInterval(() => this.tick(), 15000); this.timer.unref(); }
    return this;
  }
  async persist() {
    const contents = JSON.stringify({ schemaVersion: 1, config: this.config, state: this.state }, null, 2);
    const operation = this.queue.then(async () => {
      await mkdir(path.dirname(this.file), { recursive: true });
      try { await copyFile(this.file, this.file + '.bak'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
      await writeFile(this.file + '.tmp', contents); await rename(this.file + '.tmp', this.file);
    });
    this.queue = operation.catch(() => {}); return operation;
  }
  status() {
    return { config: this.config, running: !!this.active, stopping: !!this.active?.controller.signal.aborted, phase: this.phase, progress: this.progress,
      pending: this.state.pending.length, cursors: this.state.cursors, nextRunAt: this.config.enabled && !this.state.pausedReason ? this.state.nextRunAt : '',
      pausedReason: this.state.pausedReason, error: this.error, lastResult: this.state.lastResult,
      scope: 'VRChat / 3D public listings', serviceRequired: true };
  }
  async configure(input) {
    if (this.error) throw new Error(this.error);
    if (this.active && Object.keys(input).some(key => key !== 'enabled')) throw new Error('请先停止当前批次，再修改同步配置。');
    const config = syncConfig(input, this.config);
    const changed = JSON.stringify(config.queries) !== JSON.stringify(this.config.queries);
    this.config = config;
    if (changed) { this.state.pending = []; this.state.cursors = {}; this.state.queryIndex = 0; this.state.skipped = {}; }
    if (!config.enabled) this.active?.controller.abort();
    this.state.nextRunAt = new Date(this.now() + config.intervalMinutes * 60000).toISOString();
    await this.persist(); return this.status();
  }
  async tick() {
    if (this.config.enabled && !this.error && !this.active && this.canStart() && !this.state.pausedReason && (!this.state.nextRunAt || Date.parse(this.state.nextRunAt) <= this.now())) {
      try { this.start(); } catch {}
    }
  }
  start() {
    if (!this.canStart()) throw new Error('其他收录任务正在进行，请稍后再试。');
    if (this.error) throw new Error(this.error);
    if (this.active) throw new Error('同步正在进行，请等待完成或停止本批。');
    const active = { controller: new AbortController(), promise: null }; this.active = active; this.phase = 'search'; this.progress = { processed: 0, total: 0, id: null };
    active.promise = this.run(active).catch(error => { this.error = '保存同步状态失败，已保留已有目录。'; }).finally(() => { this.active = null; this.phase = 'idle'; this.progress.id = null; });
    return this.status();
  }
  async stop() { this.active?.controller.abort(); await this.active?.promise; return this.status(); }
  async wait() { await this.active?.promise; return this.status(); }
  async dispose() { clearInterval(this.timer); await this.stop(); }
  async run(active) {
    const signal = active.controller.signal;
    const result = { startedAt: new Date(this.now()).toISOString(), finishedAt: '', added: 0, updated: 0, skipped: 0, failed: 0, searched: 0, stopped: false, errors: [] };
    const records = [], processed = new Set();
    const known = new Map(this.store.data.items.map(item => [Number(item.id), item]));
    const recentSkipped = id => Number(this.state.skipped[id]) > this.now() - 7 * 86400000;
    this.state.pausedReason = '';
    let failure;
    try {
      // Always inspect the newest page. Historical pages and their queue survive a restart.
      for (const query of this.config.queries) {
        if (signal.aborted) throw signal.reason;
        const response = await this.searchPage(query, { page: 1, sort: 'new', signal }); result.searched++;
        const fresh = response.ids.filter(id => !known.has(id) && !recentSkipped(id));
        const waiting = new Set(this.state.pending);
        this.state.pending = [...fresh.filter(id => !waiting.has(id)).slice(0, Math.max(0, 5000 - waiting.size)), ...waiting];
        if (!this.state.cursors[query]) this.state.cursors[query] = 2;
        await this.pause(1400, signal);
      }
      const index = this.state.queryIndex % this.config.queries.length, query = this.config.queries[index];
      const page = this.state.cursors[query] || 2;
      if (this.state.pending.length < 4500 && page <= 1000) {
        const response = await this.searchPage(query, { page, sort: 'new', signal }); result.searched++;
        this.state.pending = [...new Set([...this.state.pending, ...response.ids.filter(id => !known.has(id) && !recentSkipped(id))])];
        this.state.cursors[query] = response.ids.length ? page + 1 : 2;
      }
      this.state.queryIndex = index + 1;
      // Save the fetched IDs before fetching item details; a crash cannot silently discard a page.
      await this.persist();
      const stale = [...known.values()].filter(item => (Date.parse(item.scraped_at || item.updated_at) || 0) < this.now() - this.config.refreshHours * 3600000 && !recentSkipped(Number(item.id)))
        .sort((a, b) => (Date.parse(a.scraped_at || a.updated_at) || 0) - (Date.parse(b.scraped_at || b.updated_at) || 0))
        .slice(0, Math.max(1, Math.floor(this.config.batchSize / 4))).map(item => Number(item.id));
      const pending = this.state.pending.filter(id => !known.has(id) && !recentSkipped(id));
      this.state.pending = pending;
      const batch = [...new Set([...stale, ...pending])].slice(0, this.config.batchSize);
      this.phase = 'items'; this.progress.total = batch.length;
      for (const id of batch) {
        if (signal.aborted) throw signal.reason;
        this.progress.id = id;
        try {
          const record = await this.readItem(id, { signal });
          if (signal.aborted) throw signal.reason;
          if (is3dListing(record) || known.has(id)) records.push(record);
          else { this.state.skipped[id] = this.now(); result.skipped++; }
          processed.add(id);
        } catch (error) {
          if (signal.aborted) throw error;
          result.failed++; result.errors.push({ id, message: error.message });
          if (error.kind === 'unavailable') { this.state.skipped[id] = this.now(); processed.add(id); }
          else throw error;
        }
        this.progress.processed++; await this.pause(1400, signal);
      }
    } catch (error) {
      if (signal.aborted) result.stopped = true;
      else { failure = error; if (!result.errors.some(e => e.message === error.message)) result.errors.push({ message: error.message }); }
    }
    // Commit completed records even if the next request was stopped or failed.
    this.phase = 'saving';
    if (records.length) { const merged = await this.store.merge(records); result.added = merged.added; result.updated = merged.updated; }
    this.state.pending = this.state.pending.filter(id => !processed.has(id));
    this.state.skipped = Object.fromEntries(Object.entries(this.state.skipped).filter(([, time]) => Number(time) > this.now() - 7 * 86400000).slice(-4000));
    if (failure?.kind === 'blocked') this.state.pausedReason = failure.message;
    result.errors = result.errors.slice(0, 8); result.finishedAt = new Date(this.now()).toISOString(); this.state.lastResult = result;
    this.state.nextRunAt = new Date(this.now() + this.config.intervalMinutes * 60000).toISOString();
    await this.persist();
  }
}

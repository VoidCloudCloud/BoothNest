import { access, copyFile, cp, readFile, mkdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { EngineClient } from './engine-client.mjs';
import { savePrivateJson } from './local-curation.mjs';

const okay = value => { if (!value?.ok) throw new Error(value?.error || '引擎操作失败。'); return value; };
export class LocalScan {
  constructor({ dataDir, local, home, engine, canStart = () => true, now = () => Date.now(), timer = true }) {
    this.local = local; this.home = home || path.join(dataDir, 'engine-home'); this.engine = engine || new EngineClient(this.home);
    this.file = path.join(dataDir, 'local-scan.json'); this.canStart = canStart; this.now = now; this.useTimer = timer;
    this.config = { enabled: false, intervalMinutes: 30, nextRunAt: null }; this.error = ''; this.lastTask = null; this.adopting = null; this.lock = false; this.closed = false;
    this.offline = !!local.status().sourceOffline;
  }
  async init() {
    try { const data = JSON.parse(await readFile(this.file, 'utf8')); if (typeof data.enabled !== 'boolean' || !Number.isInteger(data.intervalMinutes) || data.intervalMinutes < 5 || data.intervalMinutes > 1440) throw new Error(); this.config = data; }
    catch (error) { if (error.code !== 'ENOENT') this.error = '本地扫描设置无法读取，已保留原文件；自动扫描未启用。'; }
    if (this.useTimer) { this.timer = setInterval(() => this.tick().catch(error => this.error = error.message), 10000); this.timer.unref(); }
    return this;
  }
  managed() { return this.local.current && path.resolve(this.local.current.home) === path.resolve(this.home); }
  async adopt() {
    if (this.adopting) return this.adopting;
    this.adopting = (async () => {
      const dest = path.join(this.home, 'data', 'dataset.json');
      try { await access(dest); return; } catch {}
      if (!this.local.current || this.local.error || this.managed()) return;
      const source = this.local.current.home;
      await mkdir(this.home, { recursive: true });
      // Only first adoption copies the existing library; the original remains intact.
      for (const name of ['data', 'cache', 'config.json']) {
        const from = path.join(source, name), to = path.join(this.home, name);
        try { await stat(from); await cp(from, to, { recursive: true, force: false, errorOnExist: false }); } catch (error) { if (error.code !== 'ENOENT') throw error; }
      }
    })().finally(() => this.adopting = null);
    return this.adopting;
  }
  async poll() {
    const task = okay(await this.engine.call('poll'));
    if (task.finished && task.result?.ok && this.lastTask !== task.task_id) {
      this.lastTask = task.task_id;
      await this.local.connect(this.home);
    }
    return task;
  }
  async status() {
    await this.adopt(); const state = await this.engine.call('get_state'), task = await this.poll(); this.offline = !!state.offline;
    return { config: this.config, state, task, error: this.error, managed: !!this.managed(), home: this.home };
  }
  async configure(body) {
    if (this.error.startsWith('本地扫描设置无法读取')) throw new Error(this.error);
    const config = { ...this.config };
    if (body.enabled !== undefined) { if (typeof body.enabled !== 'boolean') throw new Error('自动扫描开关无效。'); config.enabled = body.enabled; }
    if (body.intervalMinutes !== undefined) { if (!Number.isInteger(body.intervalMinutes) || body.intervalMinutes < 5 || body.intervalMinutes > 1440) throw new Error('扫描间隔应为 5–1440 分钟。'); config.intervalMinutes = body.intervalMinutes; }
    if (!this.canStart() || this.lock || (await this.engine.call('poll')).busy) throw new Error('请先等待当前本地任务完成。');
    await this.adopt();
    if (body.root !== undefined) { if (typeof body.root !== 'string') throw new Error('目录无效。'); okay(await this.engine.call('set_root', [body.root])); }
    if (body.offline !== undefined) { if (typeof body.offline !== 'boolean') throw new Error('离线开关无效。'); okay(await this.engine.call('set_preferences', [{ offline: String(body.offline) }])); this.offline = body.offline; }
    config.nextRunAt = config.enabled ? new Date(this.now() + config.intervalMinutes * 60000).toISOString() : null;
    await savePrivateJson(this.file, config); this.config = config; this.error = ''; return this.status();
  }
  async start(body = {}) {
    if (this.lock || !this.canStart()) throw new Error('已有扫描、修正或文件核对任务，请稍后重试。');
    this.lock = true;
    try {
      await this.adopt();
      if (body.root !== undefined) { if (typeof body.root !== 'string') throw new Error('目录无效。'); okay(await this.engine.call('set_root', [body.root])); }
      if (body.offline !== undefined) { if (typeof body.offline !== 'boolean') throw new Error('离线开关无效。'); okay(await this.engine.call('set_preferences', [{ offline: String(body.offline) }])); this.offline = body.offline; }
      const state = await this.engine.call('get_state');
      if (!state.root_ok) throw new Error(state.root_problem || '请先选择可访问的下载目录。');
      // Back up the managed snapshot before the original pipeline commits a new one.
      try { const dataset = path.join(this.home, 'data', 'dataset.json'); await copyFile(dataset, dataset + '.bak'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
      okay(await this.engine.call('refresh', [body.full === true])); this.error = '';
      return this.status();
    } finally { this.lock = false; }
  }
  async tick() {
    if (this.closed || !this.config.enabled || !this.config.nextRunAt || this.now() < Date.parse(this.config.nextRunAt) || this.lock || !this.canStart()) return;
    const task = await this.poll(); if (task.busy) return;
    try { await this.start(); } catch (error) { this.error = error.message; }
    this.config = { ...this.config, nextRunAt: new Date(this.now() + this.config.intervalMinutes * 60000).toISOString() };
    await savePrivateJson(this.file, this.config);
  }
  async classic(method, args) {
    await this.adopt();
    if (['refresh','check_duplicate_files','set_item_override','clear_cache','set_root','pick_root'].includes(method) && (!this.canStart() || this.lock)) return { ok: false, error: '请等待当前本地管理任务结束。' };
    if (method === 'refresh') { await this.start({ full: args[0] === true }); return { ok: true, started: true }; }
    const value = await this.engine.call(method, args, method === 'pick_root' ? 610000 : 30000);
    if (method === 'set_preferences' && value?.ok && args[0]?.offline !== undefined) this.offline = args[0].offline === 'true';
    if (method === 'set_item_override' && value?.ok) { await this.local.connect(this.home); }
    if (method === 'poll') await this.poll();
    return value;
  }
  async override(body) {
    if (!this.managed()) return null;
    const result = okay(await this.engine.call('set_item_override', [body.folders, body.action, String(body.id || '')]));
    // The shared engine owns rules in its managed library, including the classic view.
    await this.local.refresh(true); return { changed: result.changed ?? new Set(body.folders).size };
  }
  async dispose() { this.closed = true; clearInterval(this.timer); await this.engine.dispose(); }
}

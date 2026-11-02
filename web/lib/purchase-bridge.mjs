import { readFile, mkdir } from 'node:fs/promises';
import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import path from 'node:path';
import { savePrivateJson } from './local-curation.mjs';

const extensionOrigin = /^chrome-extension:\/\/[a-p]{32}$/;
const hash = value => createHash('sha256').update(value).digest('hex');
const failure = (message, status = 400) => Object.assign(new Error(message), { status });
export function purchaseExtensionOrigin(headers) {
  const origin = headers.origin || `chrome-extension://${headers['x-boothnest-extension'] || ''}`;
  if (!extensionOrigin.test(origin)) throw failure('仅允许已配对的浏览器扩展。', 403);
  if (headers['x-boothnest-extension'] && origin !== `chrome-extension://${headers['x-boothnest-extension']}`) throw failure('扩展身份不匹配。', 403);
  return origin;
}

export class PurchaseBridge {
  constructor(dataDir, purchases, now = () => Date.now()) {
    this.file = path.join(dataDir, 'purchase-bridge.json'); this.purchases = purchases; this.now = now;
    this.data = { schema: 1, enabled: true, device: null, lastAttemptAt: '', lastSyncAt: '', phase: 'idle', lastError: '', requestId: '', lastResult: null };
    this.queue = Promise.resolve(); this.pairing = null; this.error = '';
  }
  async load() {
    try {
      const value = JSON.parse(await readFile(this.file, 'utf8'));
      if (value.schema !== 1 || typeof value.enabled !== 'boolean' || (value.device !== null && (!extensionOrigin.test(value.device?.origin) || !/^[a-f0-9]{64}$/.test(value.device?.tokenHash)))) throw new Error('invalid');
      this.data = { ...this.data, ...value };
    } catch (error) { if (error.code !== 'ENOENT') this.error = '自动同步设置无法读取，原文件已保留。'; }
    return this;
  }
  status() {
    return { paired: !!this.data.device, enabled: this.data.enabled && !this.error, intervalHours: 24,
      lastAttemptAt: this.data.lastAttemptAt, lastSyncAt: this.data.lastSyncAt, phase: this.data.phase,
      lastError: this.data.lastError, lastResult: this.data.lastResult, progress: this.data.progress || null,
      requestId: this.data.requestId, error: this.error };
  }
  mutate(change) {
    const operation = this.queue.then(async () => {
      if (this.error) throw failure(this.error);
      const next = structuredClone(this.data); change(next);
      await mkdir(path.dirname(this.file), { recursive: true }); await savePrivateJson(this.file, next); this.data = next;
    });
    this.queue = operation.catch(() => {}); return operation;
  }
  issueCode() {
    if (this.error) throw failure(this.error);
    this.pairing = { code: randomBytes(5).toString('hex').toUpperCase(), expiresAt: this.now() + 600000, attempts: 0 };
    return { code: this.pairing.code, expiresAt: new Date(this.pairing.expiresAt).toISOString() };
  }
  async pair(origin, code) {
    const pairing = this.pairing;
    if (!extensionOrigin.test(origin) || !pairing || this.now() >= pairing.expiresAt || pairing.attempts++ >= 5 || typeof code !== 'string' || hash(code.toUpperCase()) !== hash(pairing.code)) throw failure('配对信息无效或已过期，请在 GUI 重新生成。', 403);
    // Consume before awaiting disk I/O, so the code cannot pair two clients at once.
    this.pairing = null; const token = randomBytes(32).toString('hex');
    await this.mutate(next => { next.device = { origin, tokenHash: hash(token) }; next.phase = 'idle'; next.lastError = ''; next.progress = null; });
    return { token, intervalHours: 24 };
  }
  authorize(origin, token) {
    const device = this.data.device;
    if (this.error || !device || device.origin !== origin || typeof token !== 'string' || token.length > 100 || !timingSafeEqual(Buffer.from(hash(token)), Buffer.from(device.tokenHash))) throw failure('扩展尚未配对或配对已解除。', 401);
    return device.tokenHash;
  }
  async configure(body) {
    if (typeof body.enabled !== 'boolean') throw failure('同步开关无效。');
    await this.mutate(next => { next.enabled = body.enabled; }); return this.status();
  }
  async disconnect() {
    this.pairing = null;
    await this.mutate(next => { next.device = null; next.phase = 'idle'; next.progress = null; next.lastError = ''; next.requestId = ''; }); return this.status();
  }
  async request() {
    if (!this.data.device) throw failure('请先安装并配对浏览器扩展。');
    await this.mutate(next => { next.requestId = randomBytes(12).toString('hex'); }); return this.status();
  }
  async report(body, identity) {
    if (!['running', 'error', 'paused'].includes(body.phase)) throw failure('同步状态无效。');
    await this.mutate(next => {
      if (next.device?.tokenHash !== identity) throw failure('配对已解除。', 401);
      next.phase = body.phase;
      if (body.start === true) next.lastAttemptAt = new Date(this.now()).toISOString();
      next.lastError = body.phase === 'error' ? String(body.message || '同步未完成。').replace(/\s+/g, ' ').slice(0, 500) : '';
      next.progress = body.phase === 'running' ? Object.fromEntries(['page', 'pages', 'products'].map(key => [key, Number.isSafeInteger(body[key]) && body[key] >= 0 ? Math.min(body[key], 50000) : 0])) : null;
    }); return this.status();
  }
  async receive(body, identity) {
    // Recheck authorization after queued config writes and before merging any purchase records.
    await this.queue;
    if (this.data.device?.tokenHash !== identity) throw failure('配对已解除。', 401);
    const result = await this.purchases.merge(body).catch(error => { throw failure(error.message); });
    await this.mutate(next => {
      next.lastSyncAt = new Date(this.now()).toISOString(); next.phase = 'idle'; next.lastError = ''; next.progress = null;
      next.lastResult = { ...result, pages: Number.isSafeInteger(body.pages) ? body.pages : 0, complete: body.complete === true };
    }); return result;
  }
}

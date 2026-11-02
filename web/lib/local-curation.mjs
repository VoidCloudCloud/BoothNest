import { readFile, writeFile, copyFile, rename } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { boothId } from './catalog.mjs';

export async function savePrivateJson(filename, value) {
  try { await copyFile(filename, filename + '.bak'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const temporary = filename + '.tmp';
  await writeFile(temporary, JSON.stringify(value, null, 2));
  await rename(temporary, filename);
}

export class LocalCuration {
  constructor(filename) { this.filename = filename; this.data = { schema: 1, libraries: {} }; this.error = ''; }
  async load() {
    try {
      const data = JSON.parse(await readFile(this.filename, 'utf8'));
      if (data.schema !== 1 || !data.libraries || typeof data.libraries !== 'object' || Array.isArray(data.libraries)) throw new Error();
      for (const [key, rules] of Object.entries(data.libraries)) {
        if (!/^[a-f0-9]{64}$/.test(key) || !rules || typeof rules !== 'object' || Array.isArray(rules)) throw new Error();
        for (const rule of Object.values(rules)) {
          if (!rule || !['bind', 'unmatch', 'ignore'].includes(rule.action) || (rule.action === 'bind' && !boothId(rule.id))) throw new Error();
        }
      }
      this.data = data;
    } catch (error) { if (error.code !== 'ENOENT') this.error = '网页修正规则无法读取，原文件已保留；修正功能暂不可用。'; }
    return this;
  }
  key(filename, root) {
    const canonical = value => process.platform === 'win32' ? path.resolve(value).toLowerCase() : path.resolve(value);
    return createHash('sha256').update(canonical(filename) + '\0' + canonical(root || path.dirname(filename))).digest('hex');
  }
  rules(key) { return this.data.libraries[key] || {}; }
  apply(dataset, key) {
    const rules = this.rules(key);
    return { ...dataset, items: dataset.items.map(item => {
      const rule = Object.hasOwn(rules, item.folder) ? rules[item.folder] : null;
      if (!rule) return { ...item };
      return { ...item, product_id: rule.action === 'bind' ? String(rule.id) : null, ignored: rule.action === 'ignore',
        web_manual: rule.action, confidence: '网页人工修正', how: { bind: '网页手动绑定', unmatch: '网页取消归属', ignore: '网页标记非商品' }[rule.action] };
    }) };
  }
  async update(key, dataset, folders, action, value) {
    if (this.error) throw new Error(this.error);
    if (!Array.isArray(folders) || !folders.length || folders.length > 1000 || folders.some(folder => typeof folder !== 'string')) throw new Error('请选择 1–1000 个当前库存条目。');
    if (!['bind', 'unmatch', 'ignore', 'reset'].includes(action)) throw new Error('未知的修正操作。');
    const known = new Set(dataset.items.map(item => item.folder));
    if (folders.some(folder => !known.has(folder))) throw new Error('存在不属于当前库存的条目，请刷新后重试。');
    const id = action === 'bind' ? boothId(value) : null;
    if (action === 'bind' && !id) throw new Error('请输入有效的 BOOTH 商品 ID 或链接。');
    const rules = { ...this.rules(key) };
    for (const folder of new Set(folders)) {
      if (action === 'reset') delete rules[folder];
      else Object.defineProperty(rules, folder, { value: { action, ...(id ? { id } : {}), at: new Date().toISOString() }, enumerable: true, writable: true, configurable: true });
    }
    const next = { schema: 1, libraries: { ...this.data.libraries, [key]: rules } };
    await savePrivateJson(this.filename, next); this.data = next;
    return { changed: new Set(folders).size };
  }
}

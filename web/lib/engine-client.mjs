import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
export const ENGINE_METHODS = new Set(['get_state','poll','heartbeat','load_dataset','set_root','pick_root','check_root','refresh','cancel','get_summary','get_groups','get_products','get_product_detail','get_image','prefetch_thumbs','thumb_stats','get_unidentified','get_duplicates','export_excel','export_filtered','open_path','open_url','reveal_item','clear_cache','app_info','set_preferences','shutdown','window_closed','get_items','set_item_override','check_duplicate_files','get_duplicate_check','reveal_verified_file','export_duplicate_check']);
export class EngineClient {
  constructor(home, { python, executable, script } = {}) { this.home = home; this.python = python; this.executable = executable || process.env.BOOTH_NEST_ENGINE_EXE; this.script = script || path.join(root, 'engine', 'worker.py'); this.pending = new Map(); this.nextId = 0; this.closed = false; }
  async start() {
    if (this.child) return;
    if (this.starting) return this.starting;
    this.starting = (async () => {
      await mkdir(this.home, { recursive: true });
      let command = this.executable, args = ['--worker', this.home];
      if (!command) {
        command = this.python || process.env.BOOTH_NEST_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
        args = ['-u', this.script, this.home];
      }
      if (this.closed) throw new Error('扫描引擎已停止。');
      const child = spawn(command, args, { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true, shell: false, env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' } });
      this.child = child;
      child.stdin.on('error', () => {});
      let stderr = '';
      child.stderr.on('data', chunk => { stderr = (stderr + chunk.toString('utf8')).slice(-4000); });
      createInterface({ input: child.stdout }).on('line', line => {
        try { const message = JSON.parse(line), pending = this.pending.get(message.id); if (!pending) return;
          this.pending.delete(message.id); clearTimeout(pending.timer); message.error ? pending.reject(new Error(message.error)) : pending.resolve(message.value);
        } catch {}
      });
      const fail = error => { this.child = null; for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(error); } this.pending.clear(); };
      child.once('error', () => fail(new Error('无法启动扫描引擎；请将 BOOTH_NEST_PYTHON 设置为 Python 3.12+ 解释器路径。')));
      child.once('exit', code => fail(new Error('扫描引擎已退出：' + (stderr.trim() || code))));
      await new Promise((resolve, reject) => { child.once('spawn', resolve); child.once('error', reject); });
    })().finally(() => this.starting = null);
    return this.starting;
  }
  async call(method, args = [], timeout = 30000) {
    if (this.closed) throw new Error('扫描引擎已关闭。');
    if (!ENGINE_METHODS.has(method) || !Array.isArray(args)) throw new Error('未知的引擎方法。');
    await this.start();
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('引擎操作超时，请查看当前任务状态。')); }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(JSON.stringify({ id, method, args }) + '\n', error => { if (error) { clearTimeout(timer); this.pending.delete(id); reject(error); } });
    });
  }
  async dispose() {
    if (this.closed) return;
    this.closed = true;
    if (this.child) { const child = this.child; child.stdin.end(); const timer = setTimeout(() => child.kill(), 12000); timer.unref(); child.once('exit', () => clearTimeout(timer)); }
  }
}

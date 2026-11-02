import { lstat, realpath, readdir, open } from 'node:fs/promises';
import { constants } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';

const inside = (root, target) => { const rel = path.relative(root, target); return !!rel && rel !== '..' && !rel.startsWith('..' + path.sep) && !path.isAbsolute(rel); };
const signature = s => [s.dev, s.ino, s.size, s.mtimeNs, s.ctimeNs].join(':');

// Inspect every ancestor before traversal/opening; junctions are symlinks in Node on Windows.
export async function inventoryPath(root, folder) {
  if (typeof folder !== 'string' || !folder || folder.includes('\0')) throw new Error('条目路径无效');
  const target = path.resolve(root, folder);
  if (!inside(root, target)) throw new Error('路径超出扫描目录');
  let current = root;
  for (const part of path.relative(root, target).split(path.sep)) {
    current = path.join(current, part);
    if ((await lstat(current)).isSymbolicLink()) throw new Error('跳过链接或目录联接');
  }
  if (!inside(root, await realpath(target))) throw new Error('路径超出扫描目录');
  return target;
}

export async function verifyContent({ root, folders, signal, progress = () => {}, checkpoint = async () => {} }) {
  if (!path.isAbsolute(root || '')) throw new Error('扫描目录无效，请先连接本地库。');
  if ((await lstat(root)).isSymbolicLink()) throw new Error('扫描根目录是链接或目录联接，未开始核对。');
  root = await realpath(root);
  const sizes = new Map(), seen = new Set(), warnings = [];
  let warningCount = 0, enumerated = 0;
  const warn = (folder, message) => { warningCount++; if (warnings.length < 100) warnings.push({ folder, message }); };
  const pending = folders.map(folder => path.resolve(root, folder));
  while (pending.length) {
    signal?.throwIfAborted();
    const target = pending.pop(), rel = path.relative(root, target);
    const key = process.platform === 'win32' ? target.toLowerCase() : target;
    if (seen.has(key)) continue;
    seen.add(key);
    try {
      await inventoryPath(root, rel);
      const info = await lstat(target, { bigint: true });
      if (info.isDirectory()) {
        for (const name of await readdir(target)) pending.push(path.join(target, name));
      } else if (info.isFile()) {
        const size = Number(info.size);
        if (!Number.isSafeInteger(size)) throw new Error('文件大小超过支持范围');
        const group = sizes.get(size) || []; group.push({ target, folder: rel, signature: signature(info), identity: `${info.dev}:${info.ino}` }); sizes.set(size, group);
        enumerated++;
      } else warn(rel, '跳过非普通文件');
    } catch (error) { warn(rel, error.message); }
    progress({ phase: 'enumerating', enumerated });
    if (seen.size > 500000) throw new Error('文件数超过 50 万，请缩小库存范围。');
  }
  const candidates = [...sizes].filter(([, group]) => group.length > 1);
  const totalBytes = candidates.reduce((n, [size, group]) => n + size * group.length, 0);
  const total = candidates.reduce((n, [, group]) => n + group.length, 0);
  let done = 0, readBytes = 0;
  const hashes = new Map(), identities = new Map(), buffer = Buffer.alloc(1024 * 1024);
  for (const [size, group] of candidates) for (const file of group) {
    signal?.throwIfAborted();
    let handle;
    try {
      await inventoryPath(root, file.folder);
      handle = await open(file.target, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
      const before = await handle.stat({ bigint: true });
      if (!before.isFile() || signature(before) !== file.signature) throw new Error('文件在枚举后发生变化，跳过');
      let hash = identities.get(file.signature);
      if (!hash) {
        const digest = createHash('sha256');
        let offset = 0;
        while (offset < size) {
          signal?.throwIfAborted();
          const { bytesRead } = await handle.read(buffer, 0, Math.min(buffer.length, size - offset), offset);
          if (!bytesRead) throw new Error('文件在读取中变化，跳过');
          digest.update(buffer.subarray(0, bytesRead)); offset += bytesRead; readBytes += bytesRead;
          progress({ phase: 'hashing', enumerated, done, total, readBytes, totalBytes, folder: file.folder });
          await checkpoint(file.folder, offset);
        }
        hash = digest.digest('hex');
      } else readBytes += size;
      await inventoryPath(root, file.folder);
      if (signature(await handle.stat({ bigint: true })) !== file.signature || signature(await lstat(file.target, { bigint: true })) !== file.signature) throw new Error('文件在读取中变化，结果未采用');
      identities.set(file.signature, hash);
      const key = `${size}:${hash}`, matched = hashes.get(key) || { hash, bytes: size, files: [] };
      matched.files.push({ folder: file.folder, identity: file.identity }); hashes.set(key, matched);
    } catch (error) { if (signal?.aborted) throw error; warn(file.folder, error.message); }
    finally { await handle?.close(); }
    done++; progress({ phase: 'hashing', enumerated, done, total, readBytes, totalBytes, folder: file.folder });
  }
  signal?.throwIfAborted();
  const groups = [...hashes.values()].filter(g => g.files.length > 1).map(g => {
    const distinctFiles = new Set(g.files.map(f => f.identity)).size;
    return { ...g, files: g.files.map(f => f.folder), distinctFiles, hardlinkPaths: g.files.length - distinctFiles, extraBytes: (distinctFiles - 1) * g.bytes };
  }).sort((a, b) => b.extraBytes - a.extraBytes);
  return { checkedAt: new Date().toISOString(), enumerated, candidates: total, groups,
    extraBytes: groups.reduce((n, g) => n + g.extraBytes, 0), warningCount, warnings };
}

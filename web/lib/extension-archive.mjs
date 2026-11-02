import { readFile } from 'node:fs/promises';
import path from 'node:path';

const names = ['manifest.json', 'background.js', 'content.js', 'popup.html', 'popup.js', 'popup.css', 'README.md', 'LICENSE.txt'];
function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) { crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1)); }
  return (crc ^ 0xffffffff) >>> 0;
}
export async function purchaseExtensionArchive(publicDir) {
  const entries = await Promise.all(names.map(async name => [name, await readFile(path.join(publicDir, 'purchase-extension', name))]));
  entries.push(['purchase-reader.js', await readFile(path.join(publicDir, 'purchase-reader.js'))]);
  const blocks = [], directory = []; let offset = 0;
  for (const [name, data] of entries) {
    const filename = Buffer.from(name), crc = crc32(data), local = Buffer.alloc(30), central = Buffer.alloc(46);
    local.writeUInt32LE(0x04034b50); local.writeUInt16LE(20, 4); local.writeUInt16LE(0x21, 12); local.writeUInt32LE(crc, 14); local.writeUInt32LE(data.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(filename.length, 26);
    central.writeUInt32LE(0x02014b50); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6); central.writeUInt16LE(0x21, 14); central.writeUInt32LE(crc, 16); central.writeUInt32LE(data.length, 20); central.writeUInt32LE(data.length, 24); central.writeUInt16LE(filename.length, 28); central.writeUInt32LE(offset, 42);
    blocks.push(local, filename, data); directory.push(central, filename); offset += local.length + filename.length + data.length;
  }
  const index = Buffer.concat(directory), end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(index.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...blocks, index, end]);
}

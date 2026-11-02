# SPDX-License-Identifier: GPL-3.0-only
"""扫描下载目录 + 压缩包内容探测。

扫描（scan）：
  - 每个顶层条目 = 一个「下载条目」
  - **容器感知**：若某目录的直接子项里含 >=3 个**互不相同**的 7 位 BOOTH ID，
    说明它是个收纳盒（如 apps/极空间 里躺着上百件商品），改为展开其子项。
    必须去重：单商品文件夹里每个文件都重复写着同一个 ID，去重后只有 1 个。

探测（probe）：
  - .zip        → 中央目录清单（极快）
  - .unitypackage → gzip tar，增量解压 + 手写 tar 解析，只取 pathname 条目；
                    资产路径形如 Assets/<店铺目录>/… 可与 BOOTH 店铺名交叉校验
  - .rar/.7z    → 裸字节可打印字符串（无解压库时的降级方案）
  **一律不解压到磁盘、不改动原文件。**
"""
from __future__ import annotations

import collections
import json
import os
import re
import stat
import zipfile
import zlib
from pathlib import Path

from . import fsutil as FS

ID7 = re.compile(r"(?<!\d)(\d{7})(?!\d)")
ID6 = re.compile(r"(?<!\d)(\d{6})(?!\d)")
CONTAINER_MIN = 3
MAXDEPTH = None

INTEREST = re.compile(
    r"(?i)(readme|licen[cs]e|規約|利用規約|\.txt$|\.url$|\.html?$|\.md$|"
    r"booth|discord|twitter|shop|ショップ|説明|導入|ver|version)")

ARCHIVE_EXT = {".zip", ".unitypackage", ".rar", ".7z", ".001", ".002", ".gz"}


# ---------------------------------------------------------------- 扫描
def _listdir(p: Path):
    try:
        return os.listdir(p)
    except Exception:
        return []


def _walk(base: Path, rel: str, depth: int, acc: list, maxdepth=MAXDEPTH,
          warnings=None, cancel=None):
    if cancel and cancel():
        raise InterruptedError("已取消")
    if maxdepth is not None and depth > maxdepth:
        warnings.append(f"达到扫描深度上限，跳过：{rel}")
        return
    try:
        names = os.listdir(base)
    except OSError as exc:
        warnings.append(f"无法读取目录：{rel or base}（{type(exc).__name__}）")
        return
    for n in names:
        if cancel and cancel():
            raise InterruptedError("已取消")
        fp = base / n
        try:
            lst = fp.lstat()
            if stat.S_ISLNK(lst.st_mode) or (getattr(lst, "st_file_attributes", 0) & 0x400):
                warnings.append(f"跳过链接或重解析点：{fp}")
                continue
            isd = fp.is_dir()
            if isd:
                size = 0
                # ★ 目录条目也取 mtime：渲染器**本身**也有「修改时间」，
                #   而且它往往是「最后一次往这个文件夹里加东西」的时刻。
                #   取不到就退化为文件里最大的 mtime（见 _newest_mtime）。
                mt = fp.stat().st_mtime
            else:
                st = fp.stat()
                size = st.st_size
                mt = st.st_mtime
        except OSError as exc:
            warnings.append(f"无法读取条目：{fp}（{type(exc).__name__}）")
            continue
        r = f"{rel}/{n}" if rel else n
        acc.append({"rel": r, "name": n, "dir": isd, "depth": depth,
                    "size": size, "mtime": mt})
        if isd:
            _walk(fp, r, depth + 1, acc, maxdepth, warnings, cancel)


def _unique_ids_under(acc: list, rel: str) -> int:
    prefix = rel + "/"
    ids = set()
    for e in acc:
        if e["rel"].startswith(prefix) and "/" not in e["rel"][len(prefix):]:
            ids |= set(ID7.findall(e["name"]))
    return len(ids)


def _children(acc: list, rel: str) -> list[str]:
    prefix = rel + "/"
    return [e["rel"] for e in acc
            if e["rel"].startswith(prefix) and "/" not in e["rel"][len(prefix):]]


def scan(root: str, cancel=None, maxdepth=None) -> dict:
    """扫描 root，返回 {root, entries, items, containers}。

    ★ 根目录不可访问时，`Path.is_dir()` **会抛 PermissionError** 而不是返回
      False（网络盘断开 / 无权限时实测如此）。这里统一收敛成
      FileNotFoundError，让流水线能给出「网盘断了」这种可读提示，
      而不是把 WinError 5 的 traceback 甩给用户。
    """
    base = Path(root)
    if not FS.is_dir_safe(base):
        # describe_access_error 会先查盘符是否可达 —— 对断开的网络盘
        # 报「该磁盘/网络映射未连接」比报「目录不存在」有用得多
        raise FileNotFoundError(FS.describe_access_error(root))

    acc: list = []
    warnings = []
    _walk(base, "", 1, acc, maxdepth, warnings, cancel)
    by_rel = {e["rel"]: e for e in acc}
    children = collections.defaultdict(list)
    direct_ids = collections.defaultdict(set)
    for e in acc:
        parent = e["rel"].rpartition("/")[0]
        children[parent].append(e["rel"])
        direct_ids[parent].update(ID7.findall(e["name"]))
    containers = {rel: len(ids) for rel, ids in direct_ids.items()
                  if rel and len(ids) >= CONTAINER_MIN}
    # Track descendant containers once instead of rescanning the inventory per directory.
    has_container = set(containers)
    for rel in containers:
        parent = rel.rpartition("/")[0]
        while parent:
            has_container.add(parent)
            parent = parent.rpartition("/")[0]

    def expand(rel: str) -> list[str]:
        if rel not in has_container:
            return [rel]
        out = []
        for k in children[rel]:
            out.extend(expand(k))
        return out

    tops = [e for e in acc if e["depth"] == 1]
    unit_rels: list[str] = []
    for t in tops:
        unit_rels.extend(expand(t["rel"]))
    unit_rels = list(dict.fromkeys(unit_rels))

    items = []
    for rel in unit_rels:
        t = by_rel.get(rel)
        if not t:
            continue
        if cancel and cancel():
            raise InterruptedError("已取消")
        sub = []
        pending = [rel]
        while pending:
            current = pending.pop()
            sub.append(by_rel[current])
            pending.extend(children[current])
        files = [e for e in sub if not e["dir"]]
        total = sum(f["size"] for f in files)
        exts = collections.Counter()
        for f in files:
            x = os.path.splitext(f["name"])[1].lower().lstrip(".")
            exts[x or "<none>"] += 1
        strong, weak = set(), set()
        for e in sub:
            strong |= set(ID7.findall(e["name"]))
        for e in sub:
            for m in ID6.findall(e["name"]):
                if m not in strong and 300000 <= int(m) <= 9999999:
                    weak.add(m)
        # 本地时间：取该条目下所有文件里**最新的** mtime。
        #
        # ★ 为什么不用目录自身的 mtime：Windows 上目录 mtime 只在
        #   「增删直接子项」时更新，往里覆盖写文件不会变；而用户判断
        #   「这是我最近下的那件」靠的是文件到达磁盘的时间。
        #   取 max 比取 mtime 更贴近直觉，也不会因为后面解压了几个
        #   readme 就被拉回旧时间。目录 mtime 作为兜底（空目录也能有值）。
        mtimes = [e["mtime"] for e in files if e.get("mtime")]
        newest = max(mtimes) if mtimes else (t.get("mtime") or 0)
        items.append({
            "folder": rel,
            "name": t["name"],
            "is_dir": t["dir"],
            "size": total,
            "n_files": len(files),
            "exts": dict(exts.most_common(12)),
            "ids_strong": sorted(strong),
            "ids_strong_in_name": sorted(ID7.findall(t["name"])),
            "ids_weak": sorted(weak),
            "mtime": newest,
            "mtime_min": min(mtimes) if mtimes else newest,
        })

    return {"root": root, "entries": acc, "items": items,
            "containers": containers, "warnings": warnings}


# ---------------------------------------------------------------- 探测
def _probe_zip(path: Path) -> dict:
    out = {"kind": "zip", "n": 0, "roots": [], "meta": [], "paths": []}
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except Exception as e:
        out["error"] = type(e).__name__
        return out
    out["n"] = len(names)
    roots = collections.Counter(n.split("/")[0] for n in names if n.split("/")[0])
    out["roots"] = [r for r, _ in roots.most_common(10)]
    out["meta"] = [n for n in names if INTEREST.search(n)][:10]
    out["paths"] = names[:80]
    return out


def _probe_unitypackage(path: Path, max_paths: int = 120,
                        max_decomp: int = 24_000_000) -> dict:
    out = {"kind": "unitypackage", "n": 0, "paths": [], "meta": [],
           "asset_roots": [], "truncated": False}
    try:
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        buf = b""
        got = total = 0
        chunk = 1 << 20
        with open(path, "rb") as fh:
            while total < max_decomp and got < max_paths:
                raw = fh.read(chunk)
                if not raw:
                    buf += d.flush()
                    break
                decoded = d.decompress(raw, max_decomp - total)
                total += len(decoded)
                buf += decoded
                while len(buf) >= 512:
                    header = buf[:512]
                    if header == b"\0" * 512:
                        buf = buf[512:]
                        continue
                    name = header[:100].split(b"\0")[0].decode("utf-8", "replace")
                    try:
                        size = int(header[124:136].split(b"\0")[0].strip() or b"0", 8)
                    except Exception:
                        size = 0
                    padded = (size + 511) // 512 * 512
                    if len(buf) < 512 + padded:
                        break
                    body = buf[512:512 + size]
                    buf = buf[512 + padded:]
                    if name.endswith("pathname"):
                        val = body.decode("utf-8", "replace").strip()
                        if val:
                            out["paths"].append(val)
                            got += 1
                    out["n"] += 1
        out["truncated"] = got >= max_paths or total >= max_decomp
    except Exception as e:
        out["error"] = type(e).__name__
    out["meta"] = [p for p in out["paths"] if INTEREST.search(p)][:10]
    roots = []
    for p in out["paths"]:
        parts = p.split("/")
        if len(parts) >= 2 and parts[0] == "Assets":
            roots.append(parts[1])
    out["asset_roots"] = [r for r, _ in collections.Counter(roots).most_common(6)]
    return out


def _probe_raw(path: Path, limit: int = 60) -> dict:
    out = {"kind": "raw", "strings": []}
    try:
        raw = open(path, "rb").read(2_500_000)
    except Exception as e:
        out["error"] = str(e)
        return out
    seen = []
    for b in re.findall(rb"[\x20-\x7e]{8,90}", raw):
        s = b.decode("ascii", "replace")
        if INTEREST.search(s):
            seen.append(s)
        if len(seen) >= limit:
            break
    out["strings"] = seen[:25]
    return out


def probe_file(path: Path) -> dict:
    ext = path.suffix.lower()
    if ext == ".zip":
        return _probe_zip(path)
    if ext == ".unitypackage":
        return _probe_unitypackage(path)
    if ext in (".rar", ".7z", ".001", ".002", ".gz"):
        return _probe_raw(path)
    return {"kind": ext or "none"}


def _mtime_key(path: Path) -> str:
    try:
        st = path.stat()
        return f"{int(st.st_mtime)}:{st.st_size}"
    except Exception:
        return "0:0"


def probe_items(root: str, items: list, cache: dict,
                progress=None, cancel=None) -> dict:
    """对每个条目探测最多 3 个最大压缩包。

    cache: {folder: {"key": <mtime:size>, "picks": [...]}}，命中则跳过。
    """
    base = Path(root)
    out: dict = {}
    total = len(items)
    for idx, it in enumerate(items, 1):
        if cancel and cancel():
            raise InterruptedError("已取消")
        folder = it["folder"]
        p = base / folder.replace("/", os.sep)
        cands = []
        try:
            if it["is_dir"]:
                for f in os.listdir(p):
                    fp = p / f
                    if fp.is_file() and fp.suffix.lower() in ARCHIVE_EXT:
                        cands.append((fp.stat().st_size, fp))
                key = str(p.resolve()) + "|" + "|".join(
                    f"{fp.name}:{fp.stat().st_size}:{fp.stat().st_mtime_ns}"
                    for _, fp in sorted(cands, key=lambda row: str(row[1])))
            else:
                if p.suffix.lower() in ARCHIVE_EXT:
                    cands.append((it["size"], p))
                st = p.stat()
                key = f"{p.resolve()}:{st.st_size}:{st.st_mtime_ns}"
        except Exception:
            cands, key = [], "err"

        prev = cache.get(folder)
        if prev and prev.get("key") == key:
            out[folder] = prev["picks"]
        else:
            cands.sort(reverse=True)
            picks = []
            for size, fp in cands[:3]:
                pr = probe_file(fp)
                pr["file"] = fp.name
                pr["size"] = size
                picks.append(pr)
            out[folder] = picks
            cache[folder] = {"key": key, "picks": picks}
        if progress and (idx % 25 == 0 or idx == total):
            progress(idx, total)
    return out

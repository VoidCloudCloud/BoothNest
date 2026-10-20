# SPDX-License-Identifier: GPL-3.0-only
"""Read-only, cancellable size + SHA-256 verification of inventory files."""
from __future__ import annotations

from collections import defaultdict
import datetime
import hashlib
import os
from pathlib import Path
import stat
import threading


def _signature(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _linked(st):
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _check_path(root, path):
    current = root
    for part in path.relative_to(root).parts:
        if part in {"..", "."}:
            raise ValueError("路径超出库存目录")
        current = current / part
        if _linked(current.lstat()):
            raise ValueError("跳过符号链接或重解析点")
    if not path.resolve().is_relative_to(root):
        raise ValueError("路径超出库存目录")


class DuplicateVerifier:
    def __init__(self):
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _check(self):
        if self._stop.is_set():
            raise InterruptedError("已取消文件校验")

    def run(self, dataset, log=None, progress=None):
        log = log or (lambda message: None)
        progress = progress or (lambda phase, done, total: None)
        root = Path(dataset["root"]).resolve(strict=True)
        sizes = defaultdict(list)
        seen = set()
        warnings = []
        warning_count = 0

        def warn(path, message):
            nonlocal warning_count
            warning_count += 1
            if len(warnings) < 200:
                warnings.append(f"{path}：{message}")

        # Inventory items can be directories. Discover their files without
        # following junctions/symlinks, including links in ancestor components.
        pending = []
        for item in dataset.get("items", []):
            self._check()
            path = root / item["folder"]
            try:
                _check_path(root, path)
                pending.append(path)
            except (OSError, ValueError) as exc:
                warn(item["folder"], str(exc))

        while pending:
            self._check()
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            rel = path.relative_to(root).as_posix()
            try:
                _check_path(root, path)
                st = path.lstat()
                if _linked(st):
                    warn(rel, "跳过符号链接或重解析点")
                elif stat.S_ISDIR(st.st_mode):
                    with os.scandir(path) as entries:
                        for entry in entries:
                            self._check()
                            pending.append(Path(entry.path))
                elif stat.S_ISREG(st.st_mode):
                    sizes[st.st_size].append((path, _signature(st)))
                else:
                    warn(rel, "跳过非普通文件")
            except (OSError, ValueError) as exc:
                warn(rel, str(exc))
            progress("枚举本地文件", len(seen), 0)

        candidates = [entry for group in sizes.values() if len(group) > 1 for entry in group]
        total = sum(sig[2] for _, sig in candidates)
        read_bytes = 0
        hashes = defaultdict(list)
        log(f"发现 {sum(map(len, sizes.values()))} 个文件；{len(candidates)} 个同大小候选需要校验")
        for index, (path, signature) in enumerate(candidates, 1):
            self._check()
            rel = path.relative_to(root).as_posix()
            try:
                _check_path(root, path)
                digest = hashlib.sha256()
                with path.open("rb") as f:
                    # Windows/Python versions expose different ctime semantics
                    # through stat(path) and fstat(handle). Compare the shared
                    # identity/size/mtime fields here; recheck full path stat below.
                    if _signature(os.fstat(f.fileno()))[:4] != signature[:4]:
                        raise OSError("文件已变化，请重新校验")
                    while True:
                        self._check()
                        block = f.read(4 * 1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                        read_bytes += len(block)
                        progress("读取并校验 SHA-256", read_bytes, total)
                    if _signature(os.fstat(f.fileno()))[:4] != signature[:4]:
                        raise OSError("读取期间文件变化，结果已丢弃")
                hashes[(signature[2], digest.hexdigest())].append((path, signature))
            except (OSError, ValueError) as exc:
                warn(rel, str(exc))
            progress(f"SHA-256 文件 {index}/{len(candidates)}", read_bytes, total)

        # Earlier files may change while later files are being read. Recheck
        # every candidate before accepting any group.
        groups = []
        for (size, digest), entries in hashes.items():
            self._check()
            valid = []
            for path, signature in entries:
                self._check()
                try:
                    _check_path(root, path)
                    st = path.lstat()
                    if _linked(st) or _signature(st) != signature:
                        raise OSError("校验后文件变化，结果已丢弃")
                    valid.append((path, signature))
                except (OSError, ValueError) as exc:
                    warn(path.relative_to(root).as_posix(), str(exc))
            if len(valid) > 1:
                # Hard links refer to one file: never count them as separate
                # logical copies that could free additional storage.
                identities = {(sig[0], sig[1]) if sig[1] else str(path) for path, sig in valid}
                groups.append({"sha256": digest, "size": size,
                               "paths": sorted(path.relative_to(root).as_posix() for path, _ in valid),
                               "extra_bytes": size * max(0, len(identities) - 1),
                               "hardlink_paths": len(valid) - len(identities)})
        groups.sort(key=lambda group: (-group["extra_bytes"], group["sha256"]))
        self._check()
        log(f"校验完成：{len(groups)} 组相同 SHA-256；{warning_count} 项跳过或变化")
        return {"checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "root": dataset["root"], "groups": groups,
                "files": sum(map(len, sizes.values())), "candidates": len(candidates),
                "bytes_read": read_bytes, "extra_bytes": sum(group["extra_bytes"] for group in groups),
                "warnings": warnings, "warning_count": warning_count}

# SPDX-License-Identifier: GPL-3.0-only
"""BoothNest 后端 API（与传输层解耦）。

同一套方法可以被两种传输调用：
  - 内置 HTTP 服务（boothlib/server.py）—— 打包后的主力方案
  - pywebview 的 js_api —— 源码开发时的可选方案

进度**不由 Python 主动推给前端**，而是写进 self.task 由前端轮询 poll()。
这样两种传输共用同一条代码路径，也避开了 evaluate_js 的兼容问题。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from urllib.parse import urlparse

from . import __version__

from . import analytics as A
from . import exporter
from . import fsutil as F
from . import migrate as MIG
from .booth_client import BoothClient
from .config import Config
from .curation import OverrideStore, atomic_json, product_id
from .duplicates import DuplicateVerifier
from .pipeline import Pipeline


class Api:
    def __init__(self, cfg: Config | None = None, exit_handler=None):
        self.cfg = cfg or Config().load()
        self.cfg.ensure_dirs()
        self.client = BoothClient(self.cfg)
        self.dataset: dict | None = None
        self.migration: dict | None = None      # 最近一次 schema 迁移报告
        self._pipe: Pipeline | DuplicateVerifier | None = None
        self._lock = threading.RLock()
        self.last_heartbeat: float = 0.0
        self._close_generation = 0
        self._exit_handler = exit_handler

        # 任务状态（前端轮询这个）
        self.task: dict = {
            "id": 0, "busy": False, "phase": "", "done": 0, "total": 0,
            "logs": [], "finished": False, "result": None,
        }

    # ---------------------------------------------------------- 内部
    def _log(self, msg: str) -> None:
        with self._lock:
            logs = self.task["logs"]
            logs.append(str(msg))
            if len(logs) > 800:
                del logs[:len(logs) - 800]

    def _progress(self, phase: str, done: int, total: int) -> None:
        with self._lock:
            self.task.update({"phase": phase, "done": done, "total": total})

    def _result(self, ok: bool, **kw) -> dict:
        d = {"ok": ok}
        d.update(kw)
        return d

    @property
    def busy(self) -> bool:
        return bool(self.task["busy"])

    # ---------------------------------------------------------- 状态
    def get_state(self):
        info = self.cfg.describe()
        info["busy"] = self.busy
        info["version"] = __version__
        info["preferences"] = self.cfg.get("preferences", {})
        info["offline"] = bool(self.cfg.get("offline", False))
        info["frozen"] = bool(getattr(sys, "frozen", False))
        info["root_ok"] = bool(self.cfg.root) and F.is_dir_safe(self.cfg.root)
        if not info["root_ok"]:
            info["root_problem"] = (F.describe_access_error(self.cfg.root)
                                    if self.cfg.root else "请先选择 BOOTH 下载目录")
        if self.dataset is None:
            fp = self.cfg.data("dataset.json")
            if F.exists_safe(fp):
                d, rep = MIG.load_migrated(fp)
                if d is not None:
                    self.dataset = self._curated(d)
                    self.migration = rep
                    if rep.get("changed"):
                        self._log("数据 schema 已升级：" +
                                  "；".join(rep.get("actions") or []))
        if self.dataset:
            info["scan_warnings"] = self.dataset.get("scan_warnings", [])
            info["dataset_root"] = self.dataset.get("root", "")
            s = A.summarize(self.dataset)
            # mt_new/mt_old：本地文件时间的范围（epoch 秒），供界面校验
            # 「按下载时间排序」有没有拿到真实数据。取不到就是 0。
            mts = [int(p.get("local_mtime") or 0)
                   for p in (self.dataset.get("products") or [])]
            mts = [m for m in mts if m]
            info["summary"] = {
                "generated": self.dataset.get("generated"),
                "totItems": s["totItems"], "totProds": s["totProds"],
                "identified": s["identified"], "unidentified": s["unidentified"],
                "totBytes": s["totBytes"],
                "mt_new": max(mts) if mts else 0,
                "mt_old": min(mts) if mts else 0,
                "mt_count": len(mts),
            }
        return info

    def poll(self, cursor: int = 0):
        with self._lock:
            t = self.task
            logs = t["logs"][int(cursor):] if cursor < len(t["logs"]) else []
            return {
                "ok": True,
                "busy": t["busy"], "phase": t["phase"],
                "done": t["done"], "total": t["total"],
                "logs": logs, "cursor": len(t["logs"]),
                "task_id": t["id"], "finished": t["finished"],
                "result": t["result"],
            }

    def heartbeat(self):
        import time
        with self._lock:
            self.last_heartbeat = time.monotonic()
            self._close_generation += 1
        return {"ok": True}

    def window_closed(self):
        """A close hint is confirmed only when no reloaded page sends a heartbeat."""
        if self._exit_handler is None:
            return self._result(True)
        with self._lock:
            self._close_generation += 1
            generation = self._close_generation

        def finish():
            import time
            with self._lock:
                if generation != self._close_generation:
                    return
            if self.busy:
                self.cancel()
                deadline = time.monotonic() + 45
                while self.busy and time.monotonic() < deadline:
                    time.sleep(0.2)
            with self._lock:
                if generation == self._close_generation:
                    self._exit_handler()

        timer = threading.Timer(4, finish)
        timer.daemon = True
        timer.start()
        return self._result(True)

    def load_dataset(self):
        fp = self.cfg.data("dataset.json")
        if not F.exists_safe(fp):
            return self._result(False, error="还没有数据，请先点「刷新数据」")
        d, rep = MIG.load_migrated(fp)
        if d is None:
            return self._result(False, error="读取失败：" +
                                "；".join(rep.get("actions") or []))
        self.dataset = self._curated(d)
        self.migration = rep
        if rep.get("changed"):
            self._log("数据 schema 已升级：" + "；".join(rep.get("actions") or []))
        return self._result(True, schema=rep.get("to"),
                            migrated=bool(rep.get("changed")))

    def _curated(self, dataset):
        rules = OverrideStore(self.cfg).rules(dataset["root"])
        if rules or any("manual" in item for item in dataset.get("items", [])):
            return Pipeline(self.cfg, self.client).recurate(dataset, rules)
        return dataset

    def get_items(self):
        if self.dataset is None:
            return self._result(False, error="还没有扫描数据")
        products = {str(p["id"]): p for p in self.dataset.get("products", [])}
        return self._result(True, rows=[{
            "folder": x["folder"], "name": x.get("name", x["folder"]),
            "b": x.get("size", 0), "n": x.get("n_files", 0),
            "mt": int(x.get("mtime") or 0), "pid": x.get("product_id"),
            "title": products.get(str(x.get("product_id")), {}).get("title"),
            "manual": x.get("manual"), "ignored": bool(x.get("ignored")),
            "how": x.get("how"), "confidence": x.get("confidence"),
            "automatic": x.get("auto_match") or {key: x.get(key) for key in
                                                  ("product_id", "how", "confidence", "match_detail")},
            "ids_strong": x.get("ids_strong", []), "ids_weak": x.get("ids_weak", []),
        } for x in self.dataset.get("items", [])])

    def set_item_override(self, folders: list, action: str, target: str = ""):
        with self._lock:
            if self.busy:
                return self._result(False, error="请先等待或取消当前任务")
            if self.dataset is None:
                return self._result(False, error="还没有扫描数据")
            if (not isinstance(folders, list) or not 1 <= len(folders) <= 1000
                    or any(not isinstance(f, str) for f in folders)):
                return self._result(False, error="请选择 1–1000 个本地条目")
            if action not in {"bind", "unmatch", "ignore", "reset"}:
                return self._result(False, error="未知修正操作")
            folders = list(dict.fromkeys(folders))
            known = {x["folder"] for x in self.dataset.get("items", [])}
            if not set(folders).issubset(known):
                return self._result(False, error="条目已变化，请刷新列表后重试")
            try:
                pid = product_id(target) if action == "bind" else None
                store = OverrideStore(self.cfg)
                root = self.dataset["root"]
                rules = store.rules(root)
                for folder in folders:
                    if action == "reset":
                        rules.pop(folder, None)
                    else:
                        rules[folder] = {"action": action}
                        if pid:
                            rules[folder]["product_id"] = pid
                dataset = Pipeline(self.cfg, self.client).recurate(self.dataset, rules)
                # Decisions are the source of truth. A crash between these writes
                # is recovered by _curated on next load; never lose a saved rule.
                store.save(root, rules)
                self.dataset = dataset
                warning = ""
                try:
                    atomic_json(self.cfg.data("dataset.json"), dataset)
                except OSError:
                    warning = "修正已保存，统计快照写入失败；重启后会从修正规则恢复。"
                self._log(f"已更新 {len(folders)} 个条目的人工修正")
                return self._result(True, count=len(folders), warning=warning)
            except (ValueError, OSError) as exc:
                return self._result(False, error=str(exc))

    def check_duplicate_files(self):
        with self._lock:
            if self.busy:
                return self._result(False, error="已有任务在运行")
            if self.dataset is None:
                return self._result(False, error="请先扫描本地目录")
            checker = DuplicateVerifier()
            self._pipe = checker
            snapshot = self.dataset
            self.task.update({"id": self.task["id"] + 1, "busy": True, "phase": "枚举本地文件",
                              "done": 0, "total": 0, "logs": [], "finished": False, "result": None})

        def worker():
            try:
                report = checker.run(snapshot, log=self._log, progress=self._progress)
                dataset = dict(snapshot, duplicate_check=report)
                with self._lock:
                    checker._check()
                    atomic_json(self.cfg.data("dataset.json"), dataset)
                    self.dataset = dataset
                result = self._result(True, kind="duplicates", groups=len(report["groups"]),
                                      extra_bytes=report["extra_bytes"], warnings=report["warnings"])
            except InterruptedError:
                result = self._result(False, cancelled=True)
                self._log("已取消，保留上次文件核对结果")
            except Exception as exc:
                self._log(f"文件核对失败：{exc}")
                result = self._result(False, error=str(exc))
            with self._lock:
                self.task.update(busy=False, finished=True, result=result)

        threading.Thread(target=worker, daemon=True).start()
        return self._result(True, started=True)

    def get_duplicate_check(self):
        return self._result(True, report=(self.dataset or {}).get("duplicate_check"))

    def reveal_verified_file(self, path: str):
        report = (self.dataset or {}).get("duplicate_check") or {}
        allowed = {p for group in report.get("groups", []) for p in group["paths"]}
        if path not in allowed:
            return self._result(False, error="文件不在核对结果中")
        root = Path(report["root"]).resolve()
        full = (root / path).resolve()
        if not full.is_relative_to(root) or not full.is_file():
            return self._result(False, error="文件已移动或不在原目录，请重新核对")
        subprocess.Popen(["explorer.exe", "/select,", str(full)])
        return self._result(True)

    def export_duplicate_check(self):
        if not (self.dataset or {}).get("duplicate_check"):
            return self._result(False, error="请先校验文件内容")
        path = exporter.export_verified_duplicates(self.dataset, self.cfg.export_dir)
        return self._result(True, files=[path.name], dir=str(path.parent))

    # ---------------------------------------------------------- 根目录
    def check_root(self, root: str = ""):
        """预检一个路径能不能当扫描根（供 GUI 在设置前给出可读原因）。

        只读、不落盘：设置仍由 set_root 完成。
        注意返回键叫 `usable` 而不是 `ok` —— `ok` 已被 _result() 用作
        「这次调用本身有没有成功」，两者含义不同，不能复用。
        """
        target = (root or self.cfg.root or "").strip()
        if not target:
            return self._result(True, usable=False, error="路径不能为空")
        p = Path(target)
        if not F.is_dir_safe(p):
            return self._result(True, usable=False,
                                error=F.describe_access_error(p))
        try:
            n = len(F.listdir_safe(p))
        except Exception:                                # noqa: BLE001
            n = 0
        return self._result(True, usable=True, entries=n, root=str(p))

    def set_root(self, root: str):
        if self.busy:
            return self._result(False, error="请先等待或取消当前扫描")
        root = (root or "").strip().strip('"').strip("'")
        if not root:
            return self._result(False, error="路径不能为空")
        p = Path(root)
        if not p.is_absolute():
            return self._result(False, error="请输入完整的绝对路径")
        # ★ 必须用 is_dir_safe：Path.is_dir() 在网络盘断开/无权限时**抛异常**
        #   而不是返回 False（实测 X:\、\\nas.example\... 均抛 PermissionError）。
        #   原先这里直接抛出去 → GUI 收到 500 而不是 {"ok": false}，
        #   tests/test_api.py 在 HEAD 上就已因此失败。
        if not F.is_dir_safe(p):
            return self._result(False, error=F.describe_access_error(p))
        self.cfg.root = str(p)
        self.cfg.save()
        self._log(f"扫描根目录已设为 {self.cfg.root}")
        return self._result(True, root=self.cfg.root)

    def pick_root(self):
        """Windows 原生目录选择器，不依赖发行包已排除的 tkinter。"""
        from .native_dialogs import pick_folder
        out: dict = {}

        def run():
            try:
                out["path"] = pick_folder(self.cfg.root)
            except Exception as e:                       # noqa: BLE001
                out["error"] = str(e)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout=600)
        if not out:
            return self._result(False, error="目录选择超时")
        if out.get("error"):
            return self._result(False, error=out["error"])
        p = out.get("path")
        if not p:
            return self._result(False, error="未选择目录")
        return self.set_root(p)

    # ---------------------------------------------------------- 刷新
    def refresh(self, full: bool = False):
        with self._lock:
            if self.busy:
                return self._result(False, error="已有任务在运行")
            if not self.cfg.root or not F.is_dir_safe(self.cfg.root):
                return self._result(False, error="请先选择一个可访问的下载目录")
            self._pipe = Pipeline(self.cfg, self.client)
            self.task.update({
                "id": self.task["id"] + 1, "busy": True, "phase": "准备",
                "done": 0, "total": 0, "logs": [], "finished": False,
                "result": None,
            })
        self._log("开始刷新数据" + ("（全量重建，忽略缓存）" if full else "（增量）"))

        def worker():
            try:
                ds = self._pipe.run(log=self._log, progress=self._progress,
                                    use_cache=not full,
                                    offline=bool(self.cfg.get("offline", False)))
                self.dataset = ds
                s = A.summarize(ds)
                self._progress("完成", 1, 1)
                res = {"ok": True, "totItems": s["totItems"],
                       "totProds": s["totProds"], "identified": s["identified"],
                       "totBytes": s["totBytes"],
                       "warnings": ds.get("scan_warnings", [])}
            except InterruptedError:
                self._log("任务已取消")
                res = {"ok": False, "cancelled": True}
            except Exception as e:                       # noqa: BLE001
                self._log(f"出错：{e}")
                for line in traceback.format_exc().splitlines()[-12:]:
                    self._log("  " + line)
                res = {"ok": False, "error": str(e)}
            finally:
                self.client.cancelled = lambda: False
                with self._lock:
                    self.task["busy"] = False
                    self.task["finished"] = True
                    self.task["result"] = res

        threading.Thread(target=worker, daemon=True).start()
        return self._result(True, started=True)

    def cancel(self):
        if self._pipe and self.busy:
            self._pipe.stop()
            self._log("已请求取消…")
            return self._result(True)
        return self._result(False, error="没有在跑的任务")

    # ---------------------------------------------------------- 数据
    def get_summary(self):
        if not self.dataset:
            return self._result(False, error="no dataset")
        return self._result(True, summary=A.summarize(self.dataset),
                            generated=self.dataset.get("generated"),
                            root=self.dataset.get("root"),
                            schema=self.dataset.get("schema"),
                            migration=self.migration)

    def get_groups(self, dim: str = "category"):
        if not self.dataset:
            return self._result(False, error="no dataset")
        return self._result(True, dim=dim,
                            rows=A.group(self.dataset.get("products") or [], dim),
                            dimensions=A.DIMENSIONS)

    def get_products(self):
        if not self.dataset:
            return self._result(False, error="no dataset")
        return self._result(True, rows=A.product_rows(self.dataset))

    def get_product_detail(self, pid: str):
        """商品详情：完整图集 + 描述 + 标签（网格视图点开时用）。"""
        if not self.dataset:
            return self._result(False, error="no dataset")
        if not str(pid).isdigit() or len(str(pid)) > 10:
            return self._result(False, error="无效商品 ID")
        prods = {str(p["id"]): p for p in (self.dataset.get("products") or [])}
        p = prods.get(str(pid))
        if p is None:
            return self._result(False, error="商品不在当前库存中")
        d = self.client.get_item(pid, allow_network=not self.cfg.get("offline", False))
        if not d:
            d = {"name": p.get("title") or f"BOOTH 商品 #{pid}",
                 "shop": {"name": p.get("shop")}, "url": p.get("url") or f"https://booth.pm/ja/items/{pid}",
                 "price": p.get("price_text"), "published_at": p.get("published_at"),
                 "tags": [{"name": tag} for tag in p.get("tags", [])],
                 "description": "暂无商品元数据。本地条目仍可查看和修正；联网刷新后可补全商品信息。"}
        sh = d.get("shop") or {}
        imgs = []
        for im in (d.get("images") or [])[:30]:
            orig = im.get("original") or ""
            if orig:
                imgs.append({
                    "full": orig,
                    "thumb": self.client.thumb_url(orig, 300),
                    "caption": im.get("caption") or "",
                })
        # 本地占用信息
        prods = {p["id"]: p for p in (self.dataset.get("products") or [])}
        p = prods.get(str(pid)) or {}
        return self._result(True, detail={
            "id": str(pid),
            "title": d.get("name"),
            "shop": sh.get("name"),
            "shop_url": sh.get("url"),
            "url": d.get("url"),
            "price": d.get("price"),
            "wish": d.get("wish_lists_count"),
            "published": (d.get("published_at") or "")[:10],
            "is_adult": bool(d.get("is_adult")),
            "tags": [t.get("name") for t in (d.get("tags") or [])],
            "avatars": p.get("avatars") or [],
            "category": (d.get("category") or {}).get("name"),
            "description": (d.get("description") or "")[:4000],
            "images": imgs,
            "local_folders": p.get("local_folders") or [],
            "local_bytes": p.get("local_bytes") or 0,
        })

    def get_image(self, url: str):
        """按需取商品图（带本地缓存）；返回 data URL 供前端直接显示。

        为什么走本地服务而不是让页面直连 CDN：
          - 离线/内网环境下 CDN 不通，界面会一片破图
          - 统一缓存后第二次打开是本地读取，快很多
        """
        if not url or not url.startswith("https://booth.pximg.net/"):
            return self._result(False, error="只允许 BOOTH 图床地址")
        import base64
        import hashlib
        key = hashlib.md5(url.encode("utf-8")).hexdigest() + ".jpg"
        b = self.client.fetch_image(url, key)
        if not b:
            return self._result(False, error="图片获取失败")
        b64 = base64.b64encode(b).decode("ascii")
        return self._result(True, data=f"data:image/jpeg;base64,{b64}",
                            bytes=len(b))

    def prefetch_thumbs(self, limit: int = 120):
        """后台预取网格首屏缩略图，避免滚动时才逐张加载。"""
        if not self.dataset:
            return self._result(False, error="no dataset")
        limit = max(0, min(int(limit), 120))
        if getattr(self, "_prefetching", False):
            return self._result(True, already=True)
        self._prefetching = True

        def worker():
            try:
                rows = A.product_rows(self.dataset)[:limit]
                for r in rows:
                    if not r.get("th"):
                        continue
                    url = self.client.thumb_url(r["th"], 300)
                    import hashlib
                    key = hashlib.md5(url.encode("utf-8")).hexdigest() + ".jpg"
                    if (self.cfg.cache_dir / "images" / key).exists():
                        continue
                    self.client.fetch_image(url, key)
            finally:
                self._prefetching = False

        threading.Thread(target=worker, daemon=True).start()
        return self._result(True, started=True, limit=limit)

    def thumb_stats(self):
        d = self.cfg.cache_dir / "images"
        n = len(list(d.glob("*.jpg"))) if d.exists() else 0
        size = sum(f.stat().st_size for f in d.glob("*.jpg")) if d.exists() else 0
        return self._result(True, count=n, bytes=size)

    def get_unidentified(self):
        if not self.dataset:
            return self._result(False, error="no dataset")
        return self._result(True, rows=[{
            "f": x.get("folder"), "b": x.get("size") or 0,
            "n": x.get("n_files") or 0, "how": x.get("how") or "",
            # epoch 秒，供「按下载时间」排序；0 表示取不到（老数据集）
            "mt": int(x.get("mtime") or 0),
        } for x in A.unidentified(self.dataset)])

    def get_duplicates(self):
        if not self.dataset:
            return self._result(False, error="no dataset")
        s = A.summarize(self.dataset)
        return self._result(True, rows=s["dups"], wasteTotal=s["wasteTotal"])
    # ---------------------------------------------------------- 导出
    def export_excel(self):
        """导出**全部**数据（10 个 CSV + 说明）。"""
        if not self.dataset:
            return self._result(False, error="还没有数据")
        try:
            paths = exporter.export_all(self.dataset, self.cfg.export_dir)
            self._log(f"已导出 {len(paths)} 个文件到 {self.cfg.export_dir}")
            return self._result(True, dir=str(paths[0].parent),
                                files=[p.name for p in paths],
                                count=len(paths))
        except Exception as e:                           # noqa: BLE001
            return self._result(False, error=str(e))

    def export_filtered(self, kind: str = "products",
                        product_ids: list | None = None,
                        label: str = ""):
        """导出**当前筛选结果**。

        kind: products（按商品 ID 列表）/ items（按本地条目路径列表）
              / unid（未识别全部）/ dups（重复下载全部）
        """
        if not self.dataset:
            return self._result(False, error="还没有数据")
        if kind not in ("products", "items", "unid", "dups"):
            return self._result(False, error=f"未知的导出类型：{kind}")
        try:
            ids = [str(x) for x in (product_ids or [])]
            paths = exporter.export_filtered(
                self.dataset, self.cfg.export_dir,
                product_ids=ids if product_ids is not None else None,
                label=label, kind=kind)
            self._log(f"已导出筛选结果 {len(paths)} 个文件（{label or kind}）")
            return self._result(True, dir=str(self.cfg.export_dir),
                                files=[p.name for p in paths],
                                count=len(paths))
        except Exception as e:                           # noqa: BLE001
            return self._result(False, error=str(e))

    # ---------------------------------------------------------- 系统
    def open_path(self, path: str = ""):
        target = path or str(self.cfg.export_dir)
        p = Path(target)
        if not p.resolve().is_relative_to(self.cfg.home.resolve()):
            return self._result(False, error="只允许打开应用数据目录")
        if not F.exists_safe(p):
            return self._result(False, error=f"不存在：{target}")
        try:
            if p.is_dir():
                os.startfile(str(p))                     # noqa: S606
            else:
                subprocess.Popen(["explorer", "/select,", str(p)])  # noqa: S607
            return self._result(True)
        except Exception as e:                           # noqa: BLE001
            return self._result(False, error=str(e))

    def open_url(self, url: str):
        parsed = urlparse(url or "")
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or not (host == "booth.pm" or host.endswith(".booth.pm"))):
            return self._result(False, error="无效链接")
        try:
            os.startfile(url)                            # noqa: S606
            return self._result(True)
        except Exception as e:                           # noqa: BLE001
            return self._result(False, error=str(e))

    def reveal_item(self, folder: str):
        if not folder:
            return self._result(False, error="缺少路径")
        if not self.dataset or folder not in {
                x.get("folder") for x in self.dataset.get("items", [])}:
            return self._result(False, error="条目不在当前数据集中")
        base = Path(self.dataset["root"]).resolve()
        full = (base / folder.replace("/", os.sep)).resolve()
        if not full.is_relative_to(base):
            return self._result(False, error="路径超出扫描目录")
        if not F.exists_safe(full):
            return self._result(False, error=f"不存在：{full}")
        try:
            if full.is_dir():
                os.startfile(str(full))
            else:
                subprocess.Popen(["explorer.exe", "/select,", str(full)])
            return self._result(True)
        except Exception as e:                           # noqa: BLE001
            return self._result(False, error=str(e))

    def clear_cache(self):
        """清掉商品 / 搜索 / 查证 三类缓存（不动 dataset）。"""
        if self.busy or getattr(self, "_prefetching", False):
            return self._result(False, error="请等待当前任务完成后再清理缓存")
        n = 0
        for d in (self.cfg.items_dir, self.cfg.search_dir,
                  self.cfg.cache_dir / "verify"):
            if not d.exists():
                continue
            for f in d.glob("*.json"):
                try:
                    f.unlink()
                    n += 1
                except Exception:
                    pass
        self.client._mem.clear()
        self._log(f"已清除 {n} 个缓存文件")
        return self._result(True, removed=n)

    def app_info(self):
        return self._result(True, **self.cfg.describe(),
                            version=__version__,
                            frozen=bool(getattr(sys, "frozen", False)))

    def shutdown(self):
        """前端主动退出（HTTP 模式下用来收尾）。"""
        if self.busy:
            return self._result(False, error="请先取消当前任务后再退出")
        if self._exit_handler is None:
            return self._result(False, error="此会话由宿主程序管理")
        threading.Timer(0.25, self._exit_handler).start()
        return self._result(True)

    def set_preferences(self, changes: dict):
        if not isinstance(changes, dict):
            return self._result(False, error="设置格式无效")
        with self._lock:
            if "offline" in changes and self.busy:
                return self._result(False, error="请先等待或取消当前扫描")
            prefs = dict(self.cfg.get("preferences", {}))
            for key, value in changes.items():
                if key not in {"bs_view", "bs_gsize", "bs_sort", "offline"}:
                    return self._result(False, error="未知设置")
                if value is not None and (not isinstance(value, str) or len(value) > 200):
                    return self._result(False, error="设置值无效")
                if value is None:
                    prefs.pop(key, None)
                else:
                    prefs[key] = value
            self.cfg.set("preferences", prefs)
            if "offline" in changes:
                self.cfg.set("offline", changes["offline"] == "true")
            self.cfg.save()
        return self._result(True)

# SPDX-License-Identifier: GPL-3.0-only
"""BOOTH 网络访问：商品 JSON、搜索页卡片解析、商品图。

要点（都是实测踩出来的）：
- 商品 JSON 接口 `https://booth.pm/ja/items/{id}.json` **不受 18 禁年龄墙影响**，
  HTML 页面会被年龄验证挡住，这个接口不会。
- 搜索页卡片带 `data-product-id/name/brand/price`，可直接解析，不必逐件抓 JSON；
  但**卡片标题是截断的**（`PaleNightSail…`），最终判定必须用完整标题复核。
- 必须带浏览器 UA 与 `Accept-Language: ja`，否则可能被拦。
"""
from __future__ import annotations

import gzip
import hashlib
import html as _html
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_CARD = re.compile(r'<li class="item-card[^"]*"(.*?)</li>', re.S)
_ATTR = re.compile(r'data-product-([a-z-]+)="([^"]*)"')
_TOTAL = re.compile(r"<b>対象商品 ([\d,]+) 件</b>")
_TOTAL2 = re.compile(r"人気の同人グッズ([\d,]+)点")


class BoothError(Exception):
    pass


class BoothRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or not (host == "booth.pm" or host.endswith(".booth.pm")
                        or host == "booth.pximg.net")):
            raise BoothError("拒绝非 BOOTH 地址的重定向")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class BoothClient:
    ITEM_TTL = 7 * 86400
    NEGATIVE_TTL = 3600
    SEARCH_TTL = 86400
    """带磁盘缓存 + 重试的 BOOTH 访问器（线程安全使用方式：每个线程各自调用，
    写缓存用原子替换）。"""

    def __init__(self, cfg, timeout: int = 15, budget: float = 45.0):
        self.cfg = cfg
        self.timeout = timeout
        # budget：单次 _get 的**总时限**（含所有重试）。
        # 为什么需要：实测偶发某个连接陷入 TCP SYN 重传（Get-NetTCPConnection
        # 看到状态卡在 SynSent），此时 urllib 的 timeout 对"连接建立阶段"
        # 并不总是按时生效，整个抓取线程会被拖住几分钟。
        # 有总时限就能放弃这次并继续，而不是卡死整轮刷新。
        self.budget = budget
        self.cfg.ensure_dirs()
        self._mem: dict[str, dict] = {}
        self._mem_at = {}
        self._rate_lock = threading.Lock()
        self._next_request = 0.0
        self.cancelled = lambda: False

    def _wait_turn(self):
        while True:
            if self.cancelled():
                raise InterruptedError("已取消")
            with self._rate_lock:
                left = self._next_request - time.monotonic()
                if left <= 0:
                    self._next_request = time.monotonic() + 0.3
                    return
            time.sleep(min(left, 0.1))

    # ---------------- 底层 HTTP ----------------
    def _get(self, url: str, retries: int = 3) -> str:
        last = None
        deadline = time.time() + self.budget
        for attempt in range(retries):
            self._wait_turn()
            if time.time() >= deadline:
                break
            left = deadline - time.time()
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": UA,
                    "Accept-Language": "ja,en;q=0.8",
                    "Accept": "text/html,application/json,*/*",
                })
                # 单次超时不超过剩余预算
                to = max(3.0, min(self.timeout, left))
                with urllib.request.build_opener(BoothRedirect()).open(req, timeout=to) as r:
                    raw = r.read(8 * 1024 * 1024 + 1)
                    if len(raw) > 8 * 1024 * 1024:
                        raise BoothError("商品响应过大")
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    try:
                        delay = min(300, max(5, int(e.headers.get("Retry-After", "30"))))
                    except (ValueError, TypeError):
                        delay = 30
                    with self._rate_lock:
                        self._next_request = max(self._next_request, time.monotonic() + delay)
                if e.code == 404:
                    raise
                # 4xx（403/429 限流等）重试没意义，快速失败
                if 400 <= e.code < 500:
                    raise BoothError(f"HTTP {e.code}: {url}")
                last = e
            except InterruptedError:
                raise
            except Exception as e:                      # noqa: BLE001
                last = e
            # 退避，但不越过总时限
            back = min(1.2 + attempt * 2, max(0.0, deadline - time.time()))
            if back > 0:
                time.sleep(back)
        raise BoothError(f"GET failed: {url} ({last})")

    # ---------------- 商品 JSON ----------------
    def get_item(self, item_id, allow_network: bool = True,
                 write_cache: bool = True, force: bool = False) -> dict | None:
        """取商品 JSON。命中磁盘缓存零网络。商品不存在/已下架返回 None。

        write_cache=False：只在内存里留一份，**不落盘**。
        用于「查证候选」这类一次性数据 —— 早期把它们全写进缓存，
        导致缓存从 ~430 膨胀到 1800+，下一轮离线匹配量翻 4 倍、越跑越慢。
        """
        key = str(item_id)
        if not key.isascii() or not key.isdigit() or len(key) > 10:
            raise ValueError("无效商品 ID")
        fp = self.cfg.item_file(key)
        allow_network = allow_network and not self.cfg.get("offline", False)
        mem_ttl = self.ITEM_TTL if self._mem.get(key) else self.NEGATIVE_TTL
        if key in self._mem and not force and time.time() - self._mem_at.get(key, 0) < mem_ttl:
            d = self._mem[key]
            # Promote a verified candidate into the persistent item pool.
            if d and write_cache and not fp.exists():
                self._write_json(fp, d)
            return d
        stale = None
        if fp.exists():
            try:
                d = json.loads(fp.read_text(encoding="utf-8"))
                age = time.time() - fp.stat().st_mtime
                negative = d.get("__notfound__")
                ttl = self.NEGATIVE_TTL if negative else self.ITEM_TTL
                stale = None if negative else d
                if not allow_network or (not force and age < ttl):
                    self._mem[key] = stale
                    self._mem_at[key] = time.time()
                    return stale
            except Exception:
                pass
        if not allow_network:
            return stale
        try:
            d = json.loads(self._get(f"https://booth.pm/ja/items/{key}.json"))
            if not isinstance(d, dict) or str(d.get("id")) != key:
                raise BoothError("商品响应格式不正确")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                if write_cache:
                    self._write_json(fp, {"__notfound__": True, "id": key})
                self._mem[key] = None
                self._mem_at[key] = time.time()
                return None
            return stale
        except InterruptedError:
            raise
        except Exception:
            return stale
        if write_cache:
            self._write_json(fp, d)
        self._mem[key] = d
        self._mem_at[key] = time.time()
        return d

    @staticmethod
    def _write_json(fp, obj) -> None:
        fp.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=fp.parent,
                                             prefix=fp.name + ".", suffix=".tmp", delete=False) as f:
                tmp = f.name
                json.dump(obj, f, ensure_ascii=False)
            os.replace(tmp, fp)
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    def fetch_many(self, ids: Iterable, workers: int = 6,
                   progress: Callable[[int, int], None] | None = None,
                   force: bool = False, cancel=None) -> dict:
        """并发抓取，返回 {id: 'ok'|'404'|'fail'|'cached'}。

        重试策略只在 _get 里做一层（带总预算 budget）。
        早期这里又套了一层 4 次重试 × _get 的 3 次 = 最多 12 次，
        最坏情况单个 ID 就能拖掉一分钟，把整轮刷新卡住。
        """
        ids = [str(i) for i in dict.fromkeys(ids)]
        out = {}

        def one(i):
            if cancel and cancel():
                raise InterruptedError("已取消")
            return "ok" if self.get_item(i, force=force) else "fail"

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(one, i): i for i in ids}
            for future in as_completed(futures):
                if cancel and cancel():
                    for pending in futures:
                        pending.cancel()
                    raise InterruptedError("已取消")
                out[futures[future]] = future.result()
                if progress:
                    progress(len(out), len(ids))
        return out

    # ---------------- 搜索 ----------------
    def search_cards(self, query: str, count: int = 60, force: bool = False) -> list[dict]:
        key = hashlib.md5(query.encode("utf-8")).hexdigest()
        fp = self.cfg.search_file(key)
        offline = bool(self.cfg.get("offline", False))
        if fp.exists() and (offline or (not force and time.time() - fp.stat().st_mtime < self.SEARCH_TTL)):
            try:
                return json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                pass
        if offline:
            return []
        try:
            h = self._get("https://booth.pm/ja/search/" +
                          urllib.parse.quote(query) + f"?count={count}")
        except InterruptedError:
            raise
        except Exception:
            return []
        cards = []
        for body in _CARD.findall(h):
            d = dict(_ATTR.findall(body))
            if "id" in d:
                cards.append({
                    "id": d.get("id"),
                    "name": _html.unescape(d.get("name", "")).strip(),
                    "price": d.get("price", ""),
                    "shop": d.get("brand", ""),
                    "category": d.get("category", ""),
                })
        self._write_json(fp, cards)
        return cards

    def count_products(self) -> int:
        """全量库当前有多少件（用于进度估算），失败返回 0。"""
        try:
            h = self._get("https://booth.pm/ja/items?count=1")
            m = _TOTAL.search(h) or _TOTAL2.search(h)
            return int(m.group(1).replace(",", "")) if m else 0
        except Exception:
            return 0

    # ---------------- 商品图 ----------------
    # BOOTH 的 pximg CDN 只接受**固定的几档尺寸**，路径形如
    #   /c/{W}x{H}_{滤镜}/...
    # 实测（逐个试过 72/100/150/160/180/200/220/240/260/280/300/320/400/500/600）：
    #   72  ✅ 4.2 KB
    #   300 ✅ 46.1 KB
    #   其它一律 403 Forbidden
    # 所以**不能**按用户选的显示尺寸去拼 URL —— 只能固定取 300，
    # 再在页面上用 CSS 缩放成想要的大小（显示尺寸是纯前端的事）。
    THUMB_SIZE = 300
    ALLOWED_SIZES = (72, 300)

    @classmethod
    def thumb_url(cls, original: str, size: int = THUMB_SIZE) -> str:
        """把商品图 URL 换成缩略图 URL。

        original 形如：
          https://booth.pximg.net/<uuid>/i/<id>/<file>_base_resized.jpg
        缩略图形如：
          https://booth.pximg.net/c/300x300_a2_g5/<uuid>/i/<id>/<file>_base_resized.jpg
        已经带 /c/ 前缀的会先剥掉再套新尺寸（幂等）。

        size 会被吸附到 CDN 允许的那几档，避免拼出 403 的地址。
        """
        if not original:
            return ""
        if size not in cls.ALLOWED_SIZES:
            # 吸附到 <= size 的最近一档；小于 72 就用 72
            cands = [s for s in cls.ALLOWED_SIZES if s <= size]
            size = max(cands) if cands else min(cls.ALLOWED_SIZES)
        m = re.match(r"(https://booth\.pximg\.net)(?:/c/[^/]+)?(/.+)$",
                     original)
        if not m:
            return original
        return f"{m.group(1)}/c/{size}x{size}_a2_g5{m.group(2)}"

    def fetch_image(self, url: str, key: str) -> bytes | None:
        """下载图片并落盘缓存（按 key 命名）。

        为什么要本地缓存：网格视图一次要显示几十张图，
        每次都从 CDN 拉会明显卡顿，且断网就全空。
        缓存放 cache/images/，与商品数据分开。
        """
        if not url:
            return None
        d = self.cfg.cache_dir / "images"
        d.mkdir(parents=True, exist_ok=True)
        fp = d / key
        if fp.exists():
            try:
                b = fp.read_bytes()
                if b:
                    return b
            except Exception:
                pass
        if self.cfg.get("offline", False):
            return None
        try:
            self._wait_turn()
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Referer": "https://booth.pm/",
            })
            with urllib.request.build_opener(BoothRedirect()).open(req, timeout=self.timeout) as r:
                b = r.read(20 * 1024 * 1024 + 1)
                if len(b) > 20 * 1024 * 1024 or not r.headers.get_content_type().startswith("image/"):
                    return None
        except Exception:
            return None
        try:
            tmp = fp.with_suffix(fp.suffix + ".tmp")
            tmp.write_bytes(b)
            tmp.replace(fp)
        except Exception:
            pass
        return b

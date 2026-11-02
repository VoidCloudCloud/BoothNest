# SPDX-License-Identifier: GPL-3.0-only
"""流水线：扫描 → 探测 → 抓元数据 → 匹配 → 建数据集。

设计目标是**一键增量刷新**：
  - 内容探测按「目录内容指纹」缓存，没变的条目直接复用
  - 商品 JSON 有磁盘缓存，已有的零网络
  - 搜索结果有缓存
所以第二次运行通常只需几秒，只有新增的下载条目会真正走网络。
"""
from __future__ import annotations

import collections
import datetime
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import matching as M
from . import migrate as MIG
from .curation import OverrideStore, apply_rules
from .booth_client import BoothClient
from .scanner import scan as scan_root, probe_items

ID7 = re.compile(r"(?<!\d)(\d{7})(?!\d)")

# BOOTH 官方分类 → 中文主分类
CAT_MAP = {
    "3D衣装": "3D服装", "3D髪型": "3D发型", "3Dキャラクター": "3D角色模型",
    "3Dテクスチャ": "3D贴图/材质", "3D装飾品": "3D饰品", "3D靴": "3D鞋靴",
    "3D小道具": "3D道具", "3Dツール・システム": "3D工具/系统",
    "3Dモーション・アニメーション": "3D动作/动画",
    "3D環境・ワールド": "3D场景/世界", "3Dモデル（その他）": "3D其他",
    "背景画像": "素材-背景图", "イラスト素材": "素材-插画",
    "ソフトウェア": "软件/工具", "PCゲーム": "游戏",
    "アクセサリー（その他）": "实体饰品", "ゲーム音楽": "音乐",
    "ぬいぐるみ": "实体玩偶", "フォント・書体": "字体",
    "小説・ライトノベル": "书籍",
}

# BOOTH 标签 → 规范角色名
AVATAR_TAGS = {
    "しなの": "Shinano しなの", "shinano": "Shinano しなの",
    "ミルティナ": "Milltina ミルティナ", "milltina": "Milltina ミルティナ",
    "愛莉": "Airi 愛莉", "airi": "Airi 愛莉", "アイリ": "Airi 愛莉",
    "マヌカ": "Manuka マヌカ", "manuka": "Manuka マヌカ",
    "ショコラ": "Chocolat ショコラ", "chocolat": "Chocolat ショコラ",
    "シフォン": "Chiffon シフォン", "chiffon": "Chiffon シフォン",
    "ルルネ": "Rurune ルルネ", "rurune": "Rurune ルルネ",
    "ミルフィ": "Milfy ミルフィ", "milfy": "Milfy ミルフィ",
    "ライム": "Lime ライム", "lime": "Lime ライム",
    "森羅": "Shinra 森羅", "shinra": "Shinra 森羅",
    "sio": "Sio しお", "しお": "Sio しお",
    "萌": "Moe 萌", "moe": "Moe 萌",
    "セレスティア": "Selestia セレスティア", "selestia": "Selestia セレスティア",
    "瑞希": "Mizuki 瑞希", "mizuki": "Mizuki 瑞希",
    "ルミナ": "Lumina ルミナ", "lumina": "Lumina ルミナ",
    "エク": "Eku エク", "eku": "Eku エク",
    "プラム": "Plum プラム", "plum": "Plum プラム",
    "まよ": "Mayo まよ", "mayo": "Mayo まよ",
    "クマリ": "Kumaly クマリ", "kumaly": "Kumaly クマリ",
    "ラムネ": "Ramune ラムネ", "ramune": "Ramune ラムネ",
    "イチゴ": "Ichigo いちご", "ichigo": "Ichigo いちご",
    "桔梗": "Kikyo 桔梗", "kikyo": "Kikyo 桔梗",
    "ラシューシャ": "Lasyusha ラシューシャ", "lasyusha": "Lasyusha ラシューシャ",
    "まめひなた": "Mamehinata まめひなた", "mamehinata": "Mamehinata まめひなた",
    "真央": "Mao 真央", "mao": "Mao 真央",
    "輝夜": "Kaguya 輝夜", "kaguya": "Kaguya 輝夜",
    "misaki": "Misaki", "海咲": "Misaki 海咲",
    "ラップウィング": "Lapwing", "lapwing": "Lapwing",
    "アンディ": "Andi", "andi": "Andi",
    "リリカ": "Ririka", "ririka": "Ririka",
    "mafuyu": "Mafuyu", "真冬": "Mafuyu",
    "nemesis": "Nemesis", "ネメシス": "Nemesis",
    "こまど": "Komado", "komado": "Komado",
}


def _parse_price(d: dict):
    vs = d.get("variations") or []
    prices = [v.get("price") for v in vs
              if isinstance(v.get("price"), (int, float))]
    if prices:
        return min(prices), max(prices), min(prices) != max(prices)
    nums = [int(x.replace(",", "")) for x in re.findall(r"[\d,]+", d.get("price") or "")]
    if nums:
        return min(nums), max(nums), len(set(nums)) > 1
    return None, None, False


def _classify(d: dict | None, names: list[str]) -> tuple[str, list[str]]:
    d = d or {}
    cat = d.get("category") or {}
    main = CAT_MAP.get(cat.get("name") or "")
    blob = " ".join(names) + " " + (d.get("name") or "")
    subs = []
    rules = [
        (r"(?i)psd", "含PSD源文件"),
        (r"(?i)(texture|テクスチャ|textures)", "贴图/テクスチャ"),
        (r"(?i)(material|マテリアル|mat_)", "材质/マテリアル"),
        (r"(?i)(makeup|メイク|make up)", "妆容"),
        (r"(?i)(eye|瞳|アイ|iris)", "眼/瞳"),
        (r"(?i)(skin|肌|body|ボディ)", "肌肤/身体"),
        (r"(?i)(gimmick|ギミック)", "ギミック"),
        (r"(?i)(facetracking|face ?tracking|面捕|tracker)", "面部追踪"),
        (r"(?i)(shader|シェーダ|liltoon|poiyomi)", "着色器"),
        (r"(?i)(hair|ヘア|髪|ツインテール|twintail|ponytail|bob|ボブ)", "发型"),
        (r"(?i)(dress|ドレス|衣装|sailor|セーラー|bikini|水着|swimsuit|"
         r"lingerie|ランジェリー|leotard|hoodie|skirt|スカート)", "衣装"),
    ]
    for pat, label in rules:
        if re.search(pat, blob):
            subs.append(label)
    if not main:
        if re.search(r"(?i)(face ?tracking|面捕)", blob):
            main = "面部追踪/工具"
        elif re.search(r"(?i)(shader|シェーダ)", blob):
            main = "着色器/工具"
        elif re.search(r"(?i)(psd|texture|テクスチャ|material|マテリアル)", blob):
            main = "3D贴图/材质"
        elif re.search(r"(?i)(hair|ヘア|髪)", blob):
            main = "3D发型"
        elif re.search(r"(?i)(衣装|dress|sailor|lingerie|ドレス)", blob):
            main = "3D服装"
        else:
            main = "未分类"
    return main, sorted(set(subs))


def _avatars_of(d: dict) -> list[str]:
    got = set()
    for t in (d.get("tags") or []):
        nm = (t.get("name") or "").strip()
        k = nm.lower()
        if nm in AVATAR_TAGS:
            got.add(AVATAR_TAGS[nm])
        elif k in AVATAR_TAGS:
            got.add(AVATAR_TAGS[k])
    return sorted(got)


class Pipeline:
    """可中断、可报进度的流水线。"""

    def __init__(self, cfg, client: BoothClient | None = None):
        self.cfg = cfg
        self.client = client or BoothClient(cfg)
        self._stop = threading.Event()
        # 「查证候选」的持久缓存：{id: 商品JSON 或 None}。
        #
        # ★ 必须跨轮复用，且落盘到单独目录（不是 items/）。
        #
        #   背景：名称反查时，对搜索出来的候选要用**完整标题**复核
        #   （搜索卡片标题是截断的）。实测要复核 882 个候选，其中 836 个
        #   首次运行时未缓存 —— 每个 ~1.5s 网络，合计 1254 秒，
        #   正是整轮刷新 1217s 的瓶颈所在。
        #
        #   但把这些候选写进 items/ 会污染离线候选池（池子从 430 撑到 1800+，
        #   离线匹配量翻 4 倍）。所以单独放 verify/ 目录：
        #   下轮直接命中、不再联网，又不会进入候选池。
        self._verify_cache: dict[str, dict | None] = {}
        self._verify_dir = cfg.cache_dir / "verify"
        self._verify_dir.mkdir(parents=True, exist_ok=True)
        self._verify_stat = {"hit": 0, "net": 0}
        self._force = False
        self._refreshed_ids = set()

    def _verify_get(self, cid: str) -> dict | None:
        """取「查证用」的商品 JSON：先内存、再 verify/ 目录、最后联网。"""
        if cid in self._verify_cache:
            self._verify_stat["hit"] += 1
            return self._verify_cache[cid]
        fp = self._verify_dir / f"{cid}.json"
        if fp.exists() and time.time() - fp.stat().st_mtime < self.client.ITEM_TTL:
            try:
                d = json.loads(fp.read_text(encoding="utf-8"))
                if d.get("__notfound__"):
                    raise ValueError("Legacy negative verification cache")
                self._verify_cache[cid] = d
                self._verify_stat["hit"] += 1
                return d
            except Exception:
                pass
        self._verify_stat["net"] += 1
        d = self.client.get_item(cid, write_cache=False)
        self._verify_cache[cid] = d
        try:
            # A timeout, 403 or parser failure must never become a permanent 404.
            if d:
                self.client._write_json(fp, d)
        except Exception:
            pass
        return d

    def stop(self):
        self._stop.set()

    def _stopped(self):
        return self._stop.is_set()

    # ---------------------------------------------------------- 缓存
    def _load_json(self, name: str, default):
        fp = self.cfg.data(name)
        if fp.exists():
            try:
                return json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                pass
        return default

    def _save_json(self, name: str, obj) -> None:
        fp = self.cfg.data(name)
        fp.parent.mkdir(parents=True, exist_ok=True)
        tmp = fp.with_suffix(fp.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, fp)

    # ---------------------------------------------------------- 主流程
    def run(self, log=None, progress=None, use_cache: bool = True,
            offline: bool = False) -> dict:
        """跑完整条流水线，返回 dataset dict。"""
        def L(msg):
            if log:
                log(msg)

        def P(phase, done, total):
            if progress:
                progress(phase, done, total)

        self.cfg.ensure_dirs()
        rules = OverrideStore(self.cfg).rules(self.cfg.root)
        self._force = not use_cache
        self.client.cancelled = self._stopped
        if self._force:
            self.client._mem.clear()
        if self._stopped():
            raise InterruptedError("已取消")
        timings: list[tuple[str, float]] = []

        def tick(label, t0):
            dt = time.time() - t0
            timings.append((label, dt))
            L(f"  ⏱ {label}：{dt:.1f}s")
            return time.time()

        # 1) 扫描
        L(f"扫描目录 {self.cfg.root} …")
        P("扫描", 0, 1)
        _t = time.time()
        sc = scan_root(self.cfg.root, cancel=self._stopped)
        if sc.get("warnings") and not sc["entries"]:
            raise OSError("扫描目录未能完整读取，已保留上次结果：" + sc["warnings"][0])
        for warning in sc.get("warnings", []):
            L("⚠ " + warning)
        items = sc["items"]
        L(f"  条目 {len(items)} 个，条目级文件 {len(sc['entries'])} 项")
        P("扫描", 1, 1)
        _t = tick("扫描目录", _t)
        if self._stopped():
            raise InterruptedError("已取消")

        # 2) 内容探测（带指纹缓存）
        probe_cache = self._load_json("probe_cache.json", {}) if use_cache else {}
        L("探测压缩包内容（只读目录清单，不解压）…")
        if not use_cache:
            probe_cache = {}
        probe = probe_items(self.cfg.root, items, probe_cache,
                            progress=lambda d, t: P("内容探测", d, t),
                            cancel=self._stopped)
        self._save_json("probe_cache.json", probe_cache)
        L(f"  探测完成，{len(probe)} 个条目")
        _t = tick("内容探测", _t)
        if self._stopped():
            raise InterruptedError("已取消")

        # 3) 收集 ID
        id_items = [it for it in items if it["ids_strong"] and it["folder"] not in rules]
        known_ids = set()
        for it in id_items:
            known_ids |= set(it["ids_strong"])
        scanned_folders = {it["folder"] for it in items}
        known_ids.update(rule["product_id"] for folder, rule in rules.items()
                         if rule["action"] == "bind" and folder in scanned_folders)
        L(f"文件名带 BOOTH ID 的条目 {len(id_items)} 个，唯一 ID {len(known_ids)} 个")

        # 4) 抓元数据
        if not offline:
            have = sum(1 for i in known_ids if self.cfg.item_file(i).exists())
            L(f"抓取 BOOTH 商品元数据（{len(known_ids)} 个 ID，"
              f"已有缓存 {have}，需联网 {len(known_ids) - have}）…")
            fetched = self.client.fetch_many(
                sorted(known_ids, key=int),
                progress=lambda d, t: P("抓元数据", d, t),
                force=not use_cache, cancel=self._stopped)
            failures = sum(status == "fail" for status in fetched.values())
            if failures:
                sc["warnings"].append(f"{failures} 个商品未取得元数据，可能下架或暂时无法联网；可稍后刷新。")
        L(f"  本地商品库 {len(list(self.cfg.items_dir.glob('*.json')))} 个文件")
        _t = tick("抓取商品元数据", _t)

        # 5) 名称反查
        L("对无 ID 条目做名称反查…")
        resolved = self._resolve_no_id([it for it in items if it["folder"] not in rules], probe, offline=offline,
                                       progress=P)
        if self._stopped():
            raise InterruptedError("已取消")
        n_ok = sum(1 for v in resolved.values() if v.get("match"))
        L(f"  匹配上 {n_ok} 组")
        st = self._verify_stat
        if st["net"] or st["hit"]:
            L(f"  查证候选：缓存命中 {st['hit']}，联网抓取 {st['net']}"
              f"（verify/ 共 "
              f"{len(list(self._verify_dir.glob('*.json')))} 个）")
        _t = tick("名称反查", _t)

        # 6) 组装数据集
        L("组装数据集…")
        ds = self._build(items, probe, resolved, rules=rules)
        ds["scan_warnings"] = sc.get("warnings", [])
        ds["timings"] = timings
        if self._stopped():
            raise InterruptedError("已取消")
        self._save_json("dataset.json", ds)
        _t = tick("组装数据集", _t)
        ds["timings"] = timings
        L(f"完成：{ds['totProds']} 件商品 / {ds['totItems']} 个条目")
        total = sum(d for _, d in timings)
        L(f"  ⏱ 合计 {total:.1f}s：" +
          "，".join(f"{k} {d:.0f}s" for k, d in timings))
        return ds

    # ---------------------------------------------------------- 名称反查
    def _warm_verify(self, ids: list[str]) -> None:
        """并发把 verify/ 里还没有的候选抓下来（已缓存的不发请求）。"""
        need = []
        for cid in ids:
            if cid in self._verify_cache:
                continue
            fp = self._verify_dir / f"{cid}.json"
            if fp.exists() and not self._force and time.time() - fp.stat().st_mtime < self.client.ITEM_TTL:
                try:
                    if not json.loads(fp.read_text(encoding="utf-8")).get("__notfound__"):
                        continue
                except (ValueError, OSError):
                    pass
            need.append(cid)
        if not need:
            return

        def one(cid):
            try:
                d = self.client.get_item(cid, write_cache=False)
                if self._stopped():
                    return
                if d:
                    self.client._write_json(self._verify_dir / f"{cid}.json", d)
                self._verify_stat["net"] += 1
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(one, need))

    def _resolve_no_id(self, items, probe, offline=False, progress=None) -> dict:
        noid = [it for it in items if not it["ids_strong"]]
        clusters: dict[str, list[str]] = {}
        clips: dict[str, list[str]] = {}
        for it in noid:
            sig = M.signature(it["name"]) or ("__bare__|" + it["name"])
            clusters.setdefault(sig, []).append(it["folder"])
            clips.setdefault(sig, [])
            for c in M.raw_chunks(it["name"]):
                if c not in clips[sig]:
                    clips[sig].append(c)

        # 候选池：本地已有的商品
        pool = []
        for fp in self.cfg.items_dir.glob("*.json"):
            try:
                d = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if d.get("__notfound__"):
                continue
            sh = d.get("shop") or {}
            pool.append((str(d.get("id")), d.get("name", ""),
                         sh.get("name", ""), sh.get("subdomain", "")))

        # 离线匹配 = 对候选池做一次线性扫描。
        #
        # 关于性能（曾经想在这里加倒排索引，结论是**不加**）：
        #   复杂度是 O(聚类数 × 候选池)。实测 158 聚类 × ~454 候选
        #   = 7.2 万次 evaluate() ≈ 3.6 秒，相比整轮刷新的网络耗时
        #   （几分钟）可以忽略。
        #   曾经出现"越跑越慢"，根因**不是**这里，而是查证候选被写进了
        #   磁盘缓存，把候选池从 430 撑到 1800+（见 _match_cluster 里的
        #   write_cache=False）。那已在源头修掉。
        #   加索引能把 3.6s 降到 0.03s，但要覆盖 hit_in() 的整词/前向 fuzzy/
        #   CJK 子串三种命中方式才不漏结果 —— 实测漏过一组（识别数掉 20 件）。
        #   为 3.6 秒引入这种正确性风险不划算，保持线性扫描。
        results = {}
        total = len(clusters)
        for idx, (sig, folders) in enumerate(clusters.items(), 1):
            if self._stopped():
                raise InterruptedError("已取消")
            qt = [t for t in sig.split("|") if t and not t.startswith("__bare__")]
            ch = clips.get(sig, [])
            roots: list[str] = []
            for f in folders:
                for pr in probe.get(f, []):
                    roots += pr.get("asset_roots", []) or []
            m = self._match_cluster(qt, ch, roots, pool, offline=offline)
            results[sig] = {"folders": folders, "tokens": qt, "chunks": ch,
                            "match": m}
            if progress and (idx % 20 == 0 or idx == total):
                progress("名称反查", idx, total)

        # 抓新命中的商品（补元数据，供数据集使用）
        need = [v["match"]["id"] for v in results.values() if v.get("match")]
        if need and not offline:
            self.client.fetch_many(sorted(set(need), key=int), cancel=self._stopped)
        return results

    def _match_cluster(self, qt, ch, roots, pool, offline=False) -> dict | None:
        # 离线：线性扫描候选池（池子通常几百个，一次几毫秒）
        best = None
        for (iid, nm, shp, sub) in pool:
            r = M.evaluate(qt, nm, shp, sub, ch)
            if not r["accept"]:
                continue
            if M.shop_cross_roots(roots, shp, sub):
                r["score"] += 0.35
                r["shop_cross"] = True
            else:
                r["shop_cross"] = False
            if best is None or r["score"] > best["score"]:
                r.update({"id": iid, "name": nm, "shop": shp, "how": "offline"})
                best = r
        if best:
            if not offline and best["id"] not in self._refreshed_ids:
                self.client.get_item(best["id"], force=self._force)
                self._refreshed_ids.add(best["id"])
            return best

        if offline:
            return None

        # 在线：整串优先，其次词元
        queries = []
        for c in sorted(ch, key=len, reverse=True)[:3]:
            if len(c) >= 5:
                queries.append(c)
        qs = sorted(qt, key=len, reverse=True)
        queries += [t for t in qs[:4] if len(t) >= 4]
        if len(qs) >= 2 and len(qs[0]) >= 4 and len(qs[1]) >= 4:
            queries.append(qs[0] + " " + qs[1])
        queries = list(dict.fromkeys(queries))[:6]
        if not queries:
            return None

        cands: dict[str, dict] = {}
        long_hits: list[str] = []
        for q in queries:
            is_chunk = q in ch and len(M.norm_text(q)) >= 8
            if self._stopped():
                raise InterruptedError("已取消")
            got = self.client.search_cards(q, force=self._force)
            for c in got:
                cands.setdefault(c["id"], c)
            if is_chunk:
                for c in got[:6]:
                    if c["id"] not in long_hits:
                        long_hits.append(c["id"])

        # 用完整标题复核（卡片标题是截断的）
        verify = list(long_hits)
        for cid, c in cands.items():
            if cid in verify:
                continue
            if any(M.chunk_decisive(x, c["name"]) or M.chunk_hit(x, c["name"])
                   for x in ch):
                verify.append(cid)

        # ★ 先定「哪些候选必须用完整标题复核」。
        #
        #   关键：**独特整串搜出来的候选（long_hits）一律复核，不做预筛**。
        #   因为搜索卡片里的标题是截断的（'【9アバター対応】PaleNightSail…'），
        #   截断标题上当然看不到完整证据 —— 而"截断标题没有证据"恰恰是我们
        #   要去抓完整标题的原因。早期在这里加了「截断标题必须先命中」的预筛，
        #   等于把整串这条路直接废掉（实测商品数 429 → 416）。
        #
        #   pre 预筛只对 broad 候选（普通词元搜出来的）生效，用来砍掉明显无关的。
        mandatory = list(long_hits)
        verify = list(long_hits)
        for cid, c in cands.items():
            if cid in verify:
                continue
            if any(M.chunk_decisive(x, c["name"]) or M.chunk_hit(x, c["name"])
                   for x in ch):
                verify.append(cid)
            elif M.evaluate(qt, c["name"], c.get("shop", ""), "", ch)["accept"]:
                verify.append(cid)

        # 上限只作用于"非必查"部分，保证整串候选永远进得了复核
        if len(verify) > 24:
            keep = [c for c in verify if c in mandatory][:24]
            rest = [c for c in verify if c not in mandatory]
            verify = keep + rest[:max(0, 24 - len(keep))]

        # ★ 先把本轮要复核的候选**并发**预热（未缓存的才会真正联网）。
        #
        #   早期是逐个串行 get_item()，836 个 × 1.5s = 21 分钟 ——
        #   实测这就是整轮刷新 1217 秒的来源。并发后约 6 倍提速，
        #   且第二次运行全部命中 verify/ 缓存，几乎零网络。
        self._warm_verify(verify)

        best = None
        for cid in verify:
            d = self._verify_get(cid)
            if not d:
                continue
            sh = d.get("shop") or {}
            r = M.evaluate(qt, d.get("name", ""), sh.get("name", ""),
                           sh.get("subdomain", ""), ch)
            if not r["accept"]:
                continue
            r["score"] += 0.5                 # 完整标题证据更硬
            r["shop_cross"] = False
            if best is None or r["score"] > best["score"]:
                r.update({"id": cid, "name": d.get("name", ""),
                          "shop": sh.get("name", ""), "how": "online-full"})
                best = r
        if best:
            # 命中的这个才值得进离线候选池
            self.client.get_item(best["id"])
            return best

        for cid, c in cands.items():
            r = M.evaluate(qt, c["name"], c.get("shop", ""), "", ch)
            if not r["accept"]:
                continue
            r["shop_cross"] = False
            if best is None or r["score"] > best["score"]:
                r.update({"id": cid, "name": c["name"], "shop": c.get("shop", ""),
                          "how": "online-card"})
                best = r
        return best

    # ---------------------------------------------------------- 组装
    def _build(self, items, probe, resolved, rules=None) -> dict:
        by_folder = {x["folder"]: dict(x) for x in items}
        for x in by_folder.values():
            x.update({"product_id": None, "confidence": None, "how": None,
                      "match_detail": None})

        # 1) 有 ID 的直接归属
        for x in by_folder.values():
            ids = x["ids_strong"]
            if not ids:
                continue
            pid = next((i for i in ids
                        if self.client.get_item(i, allow_network=False)), None)
            if pid:
                x["product_id"] = pid
                x["how"] = "文件名中的 BOOTH ID"
                x["confidence"] = "高"
            else:
                x["product_id"] = ids[0]
                x["how"] = "文件名中的 BOOTH ID（商品已下架/接口无数据）"
                x["confidence"] = "中"

        # 2) 名称反查结果
        for sig, v in resolved.items():
            m = v.get("match")
            if not m:
                continue
            tcov = m.get("title_cov", 0)
            fz, dec = m.get("fuzzy"), m.get("decisive")
            shop_hit, sx = m.get("shop_hit"), m.get("shop_cross")
            if dec or (tcov >= 0.99 and not fz):
                conf = "高"
            elif tcov >= 0.75 or (tcov >= 0.5 and (shop_hit or sx)):
                conf = "中" if fz else "高"
            else:
                conf = "低"
            how = "文件名搜索匹配（BOOTH 搜索）"
            if dec:
                how += " + 独特名称整串命中"
            if shop_hit:
                how += " + 店铺名佐证"
            if sx:
                how += " + 包内店铺名交叉校验"
            for f in v["folders"]:
                x = by_folder.get(f)
                if x and not x["product_id"]:
                    x["product_id"] = m["id"]
                    x["confidence"] = conf
                    x["how"] = how
                    x["match_detail"] = {k: m.get(k) for k in
                                         ("id", "title_cov", "shop_hit",
                                          "shop_cross", "fuzzy", "decisive",
                                          "how", "score")}

        return self._aggregate(apply_rules(list(by_folder.values()), rules or {}), self.cfg.root)

    def recurate(self, dataset: dict, rules: dict) -> dict:
        """Recompute products/totals from existing scan; never touch source files."""
        result = dict(dataset)
        generated = dataset.get("generated")
        result.update(self._aggregate(apply_rules(dataset.get("items", []), rules), dataset["root"],
                                      old_products=dataset.get("products", [])))
        result["generated"] = generated
        result["curated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        return result

    def _aggregate(self, items_out, root, old_products=()) -> dict:
        # 3) 汇总商品
        prods: dict[str, dict] = {}
        for x in items_out:
            pid = x["product_id"]
            if not pid:
                continue
            p = prods.setdefault(pid, {
                "id": pid, "local_bytes": 0, "local_files": 0, "local_folders": [],
                "has_metadata": False, "title": None, "shop": None,
                "shop_sub": None, "category": None, "category_parent": None,
                "tags": [], "avatars": [], "url": None, "thumbnail": None,
                "price_min": None, "price_max": None, "price_text": None,
                "wish_lists_count": None, "published_at": None,
                "is_adult": False, "is_sold_out": False,
                # 本地文件时间（epoch 秒）：一件商品可能有多份下载，
                # 取**最新**的那份代表「最近一次拿到它」的时间。
                # 排序用，不参与识别逻辑。
                "local_mtime": 0, "local_mtime_min": 0,
            })
            p["local_bytes"] += x.get("size") or 0
            p["local_files"] += x.get("n_files") or 0
            p["local_folders"].append(x["folder"])
            mt = x.get("mtime") or 0
            mn = x.get("mtime_min") or mt
            if mt > (p["local_mtime"] or 0):
                p["local_mtime"] = mt
            if mn and (not p["local_mtime_min"] or mn < p["local_mtime_min"]):
                p["local_mtime_min"] = mn

        old_by_id = {str(p["id"]): p for p in old_products}
        for pid, p in prods.items():
            d = self.client.get_item(pid, allow_network=False)
            if not d:
                # Clearing metadata cache must not erase an existing product's
                # title/tags just because another item is being corrected.
                for key, value in old_by_id.get(pid, {}).items():
                    if not key.startswith("local_") and key != "id":
                        p[key] = value
                p.setdefault("cat_main", _classify(None, p["local_folders"])[0])
                p.setdefault("cat_subs", [])
                p["url"] = p.get("url") or f"https://booth.pm/ja/items/{pid}"
                continue
            sh = d.get("shop") or {}
            mn, mx, isr = _parse_price(d)
            p.update({
                "title": d.get("name"), "shop": sh.get("name"),
                "shop_sub": sh.get("subdomain"), "shop_url": sh.get("url"),
                "category": (d.get("category") or {}).get("name"),
                "category_parent": ((d.get("category") or {}).get("parent")
                                    or {}).get("name"),
                "tags": [t.get("name") for t in (d.get("tags") or [])],
                "price_min": mn, "price_max": mx, "price_is_range": isr,
                "price_text": d.get("price"),
                "wish_lists_count": d.get("wish_lists_count"),
                "published_at": d.get("published_at"),
                "is_adult": bool(d.get("is_adult")),
                "is_sold_out": bool(d.get("is_sold_out")),
                "url": d.get("url"),
                "thumbnail": ((d.get("images") or [{}])[0].get("resized")
                              if d.get("images") else None),
                "avatars": _avatars_of(d), "has_metadata": True,
            })
            p["cat_main"], p["cat_subs"] = _classify(d, p["local_folders"])

        items_out.sort(key=lambda y: -(y.get("size") or 0))
        prods_out = sorted(prods.values(), key=lambda y: -(y["local_bytes"] or 0))

        return {
            "schema": MIG.SCHEMA_VERSION,
            "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "root": root,
            "products": prods_out,
            "items": items_out,
            "totItems": len(items_out),
            "totProds": len(prods_out),
            "totBytes": sum(x.get("size") or 0 for x in items_out),
            "totFiles": sum(x.get("n_files") or 0 for x in items_out),
            "identified": sum(1 for x in items_out if x["product_id"]),
            "ignored": sum(1 for x in items_out if x.get("ignored")),
            "containers": {},
        }

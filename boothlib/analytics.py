# SPDX-License-Identifier: GPL-3.0-only
"""统计聚合：支持多种「口径」切换。

口径（dimension）：
  category  按物品类型（3D服装 / 发型 / 贴图…）
  avatar    按适配角色（一件多角色商品会**在每个角色下各计一次**）
  shop      按店铺
  year      按上架年份
  sub       按细分标签（含PSD / 妆容 / 眼瞳…）
  none      不分口径（合计）

每个口径都同时给出「商品数」与「本地占用」两个度量。
"""
from __future__ import annotations

import collections

from . import migrate as MIG

DIMENSIONS = [
    ("category", "按物品类型"),
    ("avatar", "按适配角色"),
    ("shop", "按店铺"),
    ("year", "按上架年份"),
    ("sub", "按细分标签"),
    ("none", "合计"),
]


def _size_of(x: dict) -> int:
    """取条目字节数。

    ★ 兼容两种 schema：新的是 `size`，早期脚本版是 `bytes`。
      直接读 `x["size"]` 会让旧数据静默变成 0（实测 totBytes 显示 0.00 GB，
      而实际有 500 GB）。这里同时认两个键，多一道保险。
      版本迁移见 migrate.py —— 这里是纵深防御，不是替代。
    """
    if not isinstance(x, dict):
        return 0
    v = x.get("size")
    if v is None:
        v = x.get("bytes")
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _dim_keys(p: dict, dim: str) -> list[str]:
    if dim == "category":
        return [p.get("cat_main") or "未分类"]
    if dim == "avatar":
        av = p.get("avatars") or []
        return av if av else ["（未标注适配角色）"]
    if dim == "shop":
        return [p.get("shop") or "（未识别店铺）"]
    if dim == "year":
        pa = p.get("published_at") or ""
        return [pa[:4] if pa else "（未知年份）"]
    if dim == "sub":
        subs = p.get("cat_subs") or []
        return subs if subs else ["（无细分标签）"]
    return ["全部"]


def group(products: list[dict], dim: str = "category") -> list[dict]:
    """按口径聚合。返回按「本地占用」降序的列表。

    注意 avatar 口径：一件 19 角色适配的商品会在 19 个角色下各计一次，
    所以「商品数」列之和会大于总商品数 —— 这是该口径的预期语义（覆盖度），
    页面上会标注说明。
    """
    n = collections.Counter()
    b = collections.Counter()
    for p in products:
        for k in _dim_keys(p, dim):
            n[k] += 1
            b[k] += p.get("local_bytes") or 0
    rows = [{"key": k, "count": n[k], "bytes": b[k]} for k in n]
    rows.sort(key=lambda r: (-r["bytes"], -r["count"]))
    return rows


def summarize(dataset: dict) -> dict:
    products = dataset.get("products") or []
    items = dataset.get("items") or []
    conf = collections.Counter(x.get("confidence") or "未识别" for x in items)
    how = collections.Counter(x.get("how") or "未识别" for x in items)

    # 重复下载
    copies = collections.Counter(x["product_id"] for x in items
                                 if x.get("product_id"))
    dups = []
    for pid, c in copies.items():
        if c <= 1:
            continue
        grp = [x for x in items if x.get("product_id") == pid]
        sizes = sorted((_size_of(x) for x in grp), reverse=True)
        pr = next((p for p in products if p["id"] == pid), {})
        dups.append({"id": pid, "title": pr.get("title") or pid, "n": c,
                     "waste": sum(sizes[1:]),
                     "folders": [x["folder"] for x in grp],
                     "mt": int(pr.get("local_mtime") or 0),
                     "pa": (pr.get("published_at") or "")[:10],
                     "bytes": sum(sizes)})
    dups.sort(key=lambda d: -d["waste"])

    prices = [p["price_min"] for p in products if p.get("price_min")]
    prices_sorted = sorted(prices)
    return {
        "totItems": dataset.get("totItems", len(items)),
        "totProds": dataset.get("totProds", len(products)),
        "totBytes": dataset.get("totBytes", 0),
        "totFiles": dataset.get("totFiles", 0),
        "identified": dataset.get("identified", 0),
        "unidentified": dataset.get("totItems", len(items))
        - dataset.get("identified", 0) - sum(bool(x.get("ignored")) for x in items),
        "ignored": sum(bool(x.get("ignored")) for x in items),
        "conf": dict(conf),
        "how": dict(how),
        "dups": dups,
        "wasteTotal": sum(d["waste"] for d in dups),
        "adult": sum(1 for p in products if p.get("is_adult")),
        "priceSum": sum(prices),
        "priceMed": prices_sorted[len(prices_sorted) // 2] if prices_sorted else 0,
        "priceMax": max(prices) if prices else 0,
        "priceN": len(prices),
        "missingMeta": sum(1 for p in products if not p.get("has_metadata")),
    }


def unidentified(dataset: dict) -> list[dict]:
    return [x for x in (dataset.get("items") or []) if not x.get("product_id") and not x.get("ignored")]


def product_rows(dataset: dict) -> list[dict]:
    """给前端用的紧凑商品行。"""
    items = dataset.get("items") or []
    copies = collections.Counter(x["product_id"] for x in items
                                 if x.get("product_id"))
    out = []
    for p in dataset.get("products") or []:
        out.append({
            "id": p["id"], "t": p.get("title") or f"（无标题 #{p['id']}）",
            "s": p.get("shop") or "", "c": p.get("cat_main") or "未分类",
            "sub": p.get("cat_subs") or [], "pt": p.get("price_text") or "",
            "pm": p.get("price_min"), "w": p.get("wish_lists_count") or 0,
            "b": p.get("local_bytes") or 0, "n": copies.get(p["id"], 1),
            "av": p.get("avatars") or [], "u": p.get("url") or "",
            "f": p.get("local_folders") or [],
            "pa": (p.get("published_at") or "")[:10],
            # 本地文件时间（epoch 秒）。mt = 该商品所有下载里**最新**的那份，
            # mt0 = 最早的那份。用数值而不是字符串，前端排序才不会踩
            # 「'2026-1-9' vs '2026-10-9' 字符串比较」这种坑。
            "mt": int(p.get("local_mtime") or 0),
            "mt0": int(p.get("local_mtime_min") or p.get("local_mtime") or 0),
            "adult": bool(p.get("is_adult")),
            "hm": bool(p.get("has_metadata")),
            "th": p.get("thumbnail") or "",
        })
    return out

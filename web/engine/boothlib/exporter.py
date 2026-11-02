# SPDX-License-Identifier: GPL-3.0-only
"""导出：CSV（带 BOM，Excel 直接打开）、JSON、HTML 报表。"""
from __future__ import annotations

import csv
import datetime
import json
import uuid
from pathlib import Path

from . import analytics as A


def _csv(path: Path, header: list[str], rows: list[list]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig → Excel 双击不乱码
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        # Quoting alone does not stop spreadsheet formulas from executing.
        w.writerows([_safe_cell(cell) for cell in row] for row in rows)
    return path


def _safe_cell(value):
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _day(ts) -> str:
    """epoch 秒 → YYYY-MM-DD（本地时区）；取不到给空串。

    和界面里的 fmtDay 同一口径：本地时区，因为用户看的是文件管理器里
    显示的那个时间，不是 UTC。
    """
    try:
        n = int(ts or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return datetime.datetime.fromtimestamp(n).strftime("%Y-%m-%d")


def export_products_csv(dataset: dict, out_dir: Path,
                        products: list[dict] | None = None) -> Path:
    prods = products if products is not None else dataset.get("products") or []
    rows = A.product_rows({"products": prods, "items": dataset.get("items") or []})
    header = ["BOOTH ID", "商品名", "店铺", "主分类", "细分标签", "BOOTH分类",
              "价格", "最低价", "最高价", "收藏数", "上架时间", "下载时间",
              "适配角色", "本地占用(字节)", "本地占用", "下载份数", "文件数",
              "商品链接", "本地路径", "R18", "有元数据"]
    data = []
    by_id = {str(p["id"]): p for p in prods}
    for r in rows:
        p = by_id[str(r["id"])]
        data.append([
            r["id"], r["t"], r["s"], r["c"], "/".join(r["sub"]),
            p.get("category") or "", r["pt"], r["pm"] if r["pm"] is not None else "",
            p.get("price_max", ""), r["w"], r["pa"], _day(r.get("mt")), "/".join(r["av"]), r["b"],
            f"{r['b']/1024**3:.2f} GB", r["n"], p.get("local_files", ""), r["u"],
            " | ".join(r["f"]), "是" if r["adult"] else "", "是" if r["hm"] else "",
        ])
    return _csv(out_dir / "booth-商品清单.csv", header, data)


def export_items_csv(dataset: dict, out_dir: Path,
                     items: list[dict] | None = None) -> Path:
    its = items if items is not None else dataset.get("items") or []
    prods = {p["id"]: p for p in dataset.get("products") or []}
    header = ["本地条目", "名称", "是文件夹", "大小(字节)", "大小", "文件数",
              "下载时间", "识别到的BOOTH ID", "商品名", "店铺", "主分类",
              "置信度", "识别方式"]
    data = []
    for x in its:
        pr = prods.get(x.get("product_id") or "") or {}
        b = x.get("size") or 0
        data.append([
            x.get("folder"), x.get("name"), "是" if x.get("is_dir") else "",
            b, f"{b/1024**3:.2f} GB", x.get("n_files"), _day(x.get("mtime")),
            x.get("product_id") or "", pr.get("title") or "",
            pr.get("shop") or "", pr.get("cat_main") or "",
            x.get("confidence") or "未识别", x.get("how") or "",
        ])
    return _csv(out_dir / "booth-下载条目.csv", header, data)


def export_unidentified_csv(dataset: dict, out_dir: Path, filename="booth-未识别条目.csv") -> Path:
    un = A.unidentified(dataset)
    header = ["本地条目", "名称", "大小(字节)", "大小", "文件数", "下载时间",
              "识别方式"]
    data = [[x.get("folder"), x.get("name"), x.get("size") or 0,
             f"{(x.get('size') or 0)/1024**3:.2f} GB", x.get("n_files"),
             _day(x.get("mtime")), x.get("how") or ""] for x in un]
    return _csv(out_dir / filename, header, data)


def export_duplicates_csv(dataset: dict, out_dir: Path, filename="booth-重复下载.csv") -> Path:
    s = A.summarize(dataset)
    header = ["待核对占用(字节)", "待核对占用(未验证内容重复)", "商品名", "份数", "本地路径"]
    data = [[d["waste"], f"{d['waste']/1024**3:.2f} GB", d["title"], d["n"],
             " | ".join(d["folders"])] for d in s["dups"]]
    return _csv(out_dir / filename, header, data)


def export_groups_csv(dataset: dict, out_dir: Path, dim: str) -> Path:
    rows = A.group(dataset.get("products") or [], dim)
    label = dict(A.DIMENSIONS).get(dim, dim)
    header = [label, "商品数", "本地占用(字节)", "本地占用"]
    data = [[r["key"], r["count"], r["bytes"], f"{r['bytes']/1024**3:.2f} GB"]
            for r in rows]
    safe = {"category": "物品类型", "avatar": "适配角色", "shop": "店铺",
            "year": "上架年份", "sub": "细分标签", "none": "合计"}.get(dim, dim)
    return _csv(out_dir / f"booth-分类统计-{safe}.csv", header, data)


def export_verified_duplicates(dataset: dict, out_dir: Path) -> Path:
    report = dataset.get("duplicate_check") or {}
    rows = [[report.get("checked_at"), report.get("root"), group["sha256"],
             group["size"], len(group["paths"]), group["extra_bytes"],
             group.get("hardlink_paths", 0), path]
            for group in report.get("groups", []) for path in group["paths"]]
    name = "booth-相同内容核对-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6] + ".csv"
    return _csv(Path(out_dir) / name,
                ["校验时间", "扫描根目录", "SHA-256", "单文件大小(字节)", "相同内容路径数",
                 "额外逻辑大小(字节,不含硬链接)", "硬链接额外路径数", "相对路径"], rows)


def export_all(dataset: dict, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir) / ("全部-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                               + "-" + uuid.uuid4().hex[:6])
    paths = [
        export_products_csv(dataset, out_dir),
        export_items_csv(dataset, out_dir),
        export_unidentified_csv(dataset, out_dir),
        export_duplicates_csv(dataset, out_dir),
    ]
    if dataset.get("duplicate_check"):
        paths.append(export_verified_duplicates(dataset, out_dir))
    for dim, _ in A.DIMENSIONS:
        paths.append(export_groups_csv(dataset, out_dir, dim))
    meta = out_dir / "booth-导出信息.json"
    meta.write_text(json.dumps({
        "exported": datetime.datetime.now().isoformat(timespec="seconds"),
        "root": dataset.get("root"),
        "totItems": dataset.get("totItems"),
        "totProds": dataset.get("totProds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    paths.append(meta)
    return paths


def _safe_name(s: str, limit: int = 40) -> str:
    """把筛选描述变成安全的文件名片段。"""
    s = "".join(ch if ch.isalnum() or ch in "-_（）()" else "_" for ch in (s or ""))
    s = s.strip("_") or "筛选"
    return s[:limit]


def export_filtered(dataset: dict, out_dir: Path,
                    product_ids: list[str] | None = None,
                    label: str = "",
                    kind: str = "products") -> list[Path]:
    """导出**当前筛选结果**，而不是全量。

    - kind="products"：按 product_ids 过滤商品清单（未识别/重复表也按此过滤）
    - kind="items"   ：导出指定下载条目（folder 列表放在 product_ids 里复用）
    - kind="unid"    ：只导未识别条目
    - kind="dups"    ：只导重复下载表

    文件名带筛选标签与时间戳，避免覆盖上一次导出。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    tag = f"-{_safe_name(label)}" if label else ""
    paths: list[Path] = []

    if kind == "unid":
        if product_ids is not None:
            want = set(product_ids)
            dataset = dict(dataset, items=[x for x in dataset.get("items", []) if x.get("folder") in want])
        dst = export_unidentified_csv(dataset, out_dir, f"筛选{tag}-未识别条目-{stamp}.csv")
        paths.append(dst)
        return paths

    if kind == "dups":
        if product_ids is not None:
            want = set(product_ids)
            dataset = dict(dataset, items=[x for x in dataset.get("items", []) if x.get("product_id") in want])
        dst = export_duplicates_csv(dataset, out_dir, f"筛选{tag}-重复下载-{stamp}.csv")
        paths.append(dst)
        return paths

    products = dataset.get("products") or []
    items = dataset.get("items") or []

    if kind == "items":
        want = set(product_ids or [])
        sub_items = [x for x in items if x.get("folder") in want]
        dst = out_dir / f"筛选{tag}-下载条目-{stamp}.csv"
        _items_csv_to(dataset, dst, sub_items)
        paths.append(dst)
        # 顺带给出这些条目归属的商品
        pids = {x.get("product_id") for x in sub_items if x.get("product_id")}
        sub_prods = [p for p in products if p["id"] in pids]
        if sub_prods:
            dst2 = out_dir / f"筛选{tag}-涉及商品-{stamp}.csv"
            _products_csv_to(sub_prods, items, dst2)
            paths.append(dst2)
        return paths

    # kind == "products"
    if product_ids is None:
        sub_prods = products
    else:
        want = set(product_ids)
        sub_prods = [p for p in products if p["id"] in want]
    dst = out_dir / f"筛选{tag}-商品清单-{stamp}.csv"
    _products_csv_to(sub_prods, items, dst)
    paths.append(dst)

    # 同一筛选下的未识别条目（若该筛选是"全部"才附全量，否则不附以避免误导）
    if product_ids is None:
        dst2 = export_unidentified_csv(dataset, out_dir, f"筛选{tag}-未识别条目-{stamp}.csv")
        paths.append(dst2)
    return paths


def _products_csv_to(prods: list[dict], items: list[dict], dst: Path) -> Path:
    """把给定商品写成 CSV（复用列定义）。"""
    rows = A.product_rows({"products": prods, "items": items})
    header = ["BOOTH ID", "商品名", "店铺", "主分类", "细分标签", "价格",
              "最低价", "收藏数", "上架时间", "下载时间", "适配角色",
              "本地占用(字节)", "本地占用", "下载份数", "商品链接", "本地路径",
              "R18"]
    data = [[
        r["id"], r["t"], r["s"], r["c"], "/".join(r["sub"]), r["pt"],
        r["pm"] if r["pm"] is not None else "", r["w"], r["pa"],
        _day(r.get("mt")), "/".join(r["av"]), r["b"],
        f"{r['b']/1024**3:.2f} GB", r["n"],
        r["u"], " | ".join(r["f"]), "是" if r["adult"] else "",
    ] for r in rows]
    return _csv(dst, header, data)


def _items_csv_to(dataset: dict, dst: Path, items: list[dict]) -> Path:
    header = ["本地条目", "名称", "大小(字节)", "大小", "文件数",
              "识别到的BOOTH ID", "商品名", "店铺", "主分类", "置信度", "识别方式"]
    prods = {p["id"]: p for p in dataset.get("products") or []}
    data = []
    for x in items:
        pr = prods.get(x.get("product_id") or "") or {}
        b = x.get("size") or 0
        data.append([
            x.get("folder"), x.get("name"), b, f"{b/1024**3:.2f} GB",
            x.get("n_files"), x.get("product_id") or "", pr.get("title") or "",
            pr.get("shop") or "", pr.get("cat_main") or "",
            x.get("confidence") or "未识别", x.get("how") or "",
        ])
    return _csv(dst, header, data)

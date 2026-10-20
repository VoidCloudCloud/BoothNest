# SPDX-License-Identifier: GPL-3.0-only
"""dataset.json 的 schema 版本迁移。

★ 为什么需要（2026-10-09 实测）：

    `data/dataset.json`（早期脚本版产出）与 `seed/dataset.json`（当前流水线产出）
    **同名不同构**，而且没有任何版本标记：

        data/  旧:  item{ "bytes": ..., "ids": [...] }
        seed/  新:  item{ "size":  ..., "ids_strong": [...] }

    当前代码读 `item["size"]`，读旧文件拿到的是 None —— **不报错、静默变 0**。
    实测同一个 `A.summarize()`：

        旧 schema  →  totBytes=  0.00 GB   waste= 0.00 GB
        新 schema  →  totBytes=500.77 GB   waste=26.22 GB

    也就是说，界面会理直气壮地显示「本地总占用 0 B / 可回收 0 B」，
    而磁盘上躺着 500 GB。这类失败比崩溃更难发现，必须从数据层根治。

    本模块的做法与 KonoAsset 的 `VersionedPreferences` / `VersionedAvatars`
    思路一致：**读的时候认版本、逐级升级到当前版本**，而不是让调用方去猜字段名。

    迁移是**纯函数、幂等**的：同一份数据跑几次结果一样，且不改动入参。
"""
from __future__ import annotations

import copy

__all__ = ["SCHEMA_VERSION", "detect_version", "migrate", "load_migrated"]

# 1 = 早期脚本版（items 用 bytes/ids，无顶层汇总）
# 2 = 当前流水线版（items 用 size/ids_strong，含顶层汇总）
SCHEMA_VERSION = 2


def detect_version(dataset: dict) -> int:
    """判断 dataset 的 schema 版本。

    判据用**字段是否存在**而不是猜内容：
      - 有 items 且首个 item 带 "size"        → 2
      - 有 items 且首个 item 带 "bytes"       → 1
      - 既无 items 也无 products              → 0（空/损坏）
    """
    if not isinstance(dataset, dict):
        return 0
    items = dataset.get("items")
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            if "size" in first:
                return 2
            if "bytes" in first:
                return 1
    # items 为空时看顶层汇总键：新schema 一定有 totItems
    if "totItems" in dataset or "totBytes" in dataset:
        return 2
    if "products" in dataset:
        return 1
    return 0


def _migrate_item_v1_to_v2(item: dict) -> dict:
    """单个 item：bytes→size，ids→ids_strong，补出拆分字段。"""
    it = dict(item)
    if "size" not in it:
        it["size"] = it.get("bytes") or 0
    # 保留 bytes 作为镜像：老代码（scripts/ 下）仍在读它，删掉会让对照脚本失准
    it["bytes"] = it.get("size") or 0

    if "ids_strong" not in it:
        # 旧版只有一个 ids 列表（扫描时收集到的 7 位 ID），按强 ID 处理
        it["ids_strong"] = list(it.get("ids") or [])
    it.setdefault("ids_strong_in_name", [])
    it.setdefault("ids_weak", [])
    if "ids" not in it:
        it["ids"] = list(it["ids_strong"])
    return it


def _recompute_totals(ds: dict) -> None:
    """按 items 重算顶层汇总（就地）。

    为什么不直接信旧文件里的汇总：旧 schema 压根没有这些键；
    而万一有，也应该以明细为准 —— 明细能重算，汇总不能。
    """
    items = ds.get("items") or []
    ds["totItems"] = len(items)
    ds["totProds"] = len(ds.get("products") or [])
    ds["totBytes"] = sum((x.get("size") or 0) for x in items)
    ds["totFiles"] = sum((x.get("n_files") or 0) for x in items)
    ds["identified"] = sum(1 for x in items if x.get("product_id"))
    ds.setdefault("containers", {})


def migrate(dataset: dict, *, inplace: bool = False) -> tuple[dict, dict]:
    """把 dataset 升到 SCHEMA_VERSION，返回 (数据集, 迁移报告)。

    inplace=False（默认）不改动入参。报告形如：
        {"from": 1, "to": 2, "changed": True, "items": 828, "actions": [...]}
    """
    if not isinstance(dataset, dict):
        return dataset, {"from": 0, "to": 0, "changed": False,
                         "actions": ["输入不是 dict，原样返回"]}

    ver = detect_version(dataset)
    ds = dataset if inplace else copy.deepcopy(dataset)
    actions: list[str] = []

    if ver == 0:
        return ds, {"from": 0, "to": 0, "changed": False,
                    "actions": ["无法识别 schema，原样返回"]}

    if ver < 2:
        items = ds.get("items")
        if isinstance(items, list):
            ds["items"] = [_migrate_item_v1_to_v2(x) if isinstance(x, dict) else x
                           for x in items]
            actions.append(f"items: bytes→size / ids→ids_strong（{len(items)} 条）")
        _recompute_totals(ds)
        actions.append("按明细重算顶层汇总 totItems/totBytes/totFiles/identified")

    # 顶层汇总缺失也补，避免「版本号对但没汇总」的文件继续显示 0
    if ds.get("totBytes") in (None, 0) and (ds.get("items") or []):
        _recompute_totals(ds)
        actions.append("补齐缺失的顶层汇总")

    ds["schema"] = SCHEMA_VERSION
    changed = bool(actions)
    return ds, {"from": ver, "to": SCHEMA_VERSION, "changed": changed,
                "items": len(ds.get("items") or []), "actions": actions}


def load_migrated(path, *, encoding: str = "utf-8"):
    """读一个 dataset.json 并升级到当前 schema。读不到返回 (None, 报告)。"""
    import json
    from pathlib import Path

    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding=encoding))
    except FileNotFoundError:
        return None, {"from": -1, "to": SCHEMA_VERSION, "changed": False,
                      "actions": [f"文件不存在：{p}"]}
    except Exception as e:                               # noqa: BLE001
        return None, {"from": -1, "to": SCHEMA_VERSION, "changed": False,
                      "actions": [f"读取失败：{type(e).__name__}: {e}"]}
    if (not isinstance(raw, dict)
            or not isinstance(raw.get("items"), list)
            or not isinstance(raw.get("products"), list)
            or any(not isinstance(x, dict) for x in raw["items"] + raw["products"])
            or (isinstance(raw.get("schema"), int) and raw["schema"] > SCHEMA_VERSION)):
        return None, {"from": -1, "to": SCHEMA_VERSION, "changed": False,
                      "actions": ["库存结构无效或由更新版本生成，请保留原文件并重新扫描或升级应用"]}
    return migrate(raw)

# SPDX-License-Identifier: GPL-3.0-only
"""User decisions are independent of generated inventories and metadata caches."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse

MATCH_KEYS = ("product_id", "confidence", "how", "match_detail")


def product_id(value: str) -> str:
    value = str(value).strip()
    if re.fullmatch(r"[1-9][0-9]{0,9}", value):
        return value
    parsed = urlparse(value)
    host = parsed.hostname or ""
    match = re.fullmatch(r"/(?:[a-z]{2}/)?items/([1-9][0-9]{0,9})/?", parsed.path)
    if (parsed.scheme == "https" and not parsed.username and not parsed.password
            and parsed.port in (None, 443)
            and (host == "booth.pm" or host.endswith(".booth.pm")) and match):
        return match[1]
    raise ValueError("请输入有效的 BOOTH 商品 ID 或 HTTPS 商品链接")


def root_key(root: str) -> str:
    # Do not resolve network paths: the saved decision must also work offline.
    return os.path.normcase(os.path.abspath(os.path.normpath(root)))


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=path.stem + "-", suffix=".tmp", delete=False) as f:
            temporary = f.name
            json.dump(value, f, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class OverrideStore:
    def __init__(self, cfg):
        self.path = cfg.data("manual_overrides.json")

    def load(self):
        if not self.path.exists():
            return {"schema": 1, "roots": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema") != 1 or not isinstance(data.get("roots"), dict):
                raise ValueError("格式无效或版本不支持")
            for rules in data["roots"].values():
                if not isinstance(rules, dict):
                    raise ValueError("规则格式无效")
                for rule in rules.values():
                    if not isinstance(rule, dict) or rule.get("action") not in {"bind", "unmatch", "ignore"}:
                        raise ValueError("修正规则无效")
                    if rule["action"] == "bind" and product_id(rule.get("product_id", "")) != rule["product_id"]:
                        raise ValueError("商品 ID 无效")
            return data
        except (ValueError, TypeError, AttributeError, OSError) as exc:
            raise ValueError(f"手动修正文件无法读取，请先备份检查 {self.path}：{exc}") from exc

    def rules(self, root: str):
        return self.load()["roots"].get(root_key(root), {})

    def save(self, root: str, rules: dict):
        data = self.load()
        data["roots"][root_key(root)] = copy.deepcopy(rules)
        atomic_json(self.path, data)


def apply_rules(items: list[dict], rules: dict) -> list[dict]:
    result = copy.deepcopy(items)
    for item in result:
        baseline = item.setdefault("auto_match", {key: item.get(key) for key in MATCH_KEYS})
        item.update(copy.deepcopy(baseline))
        item.pop("manual", None)
        item.pop("ignored", None)
        rule = rules.get(item["folder"])
        if not rule:
            continue
        item["manual"] = rule["action"]
        item["product_id"] = rule.get("product_id") if rule["action"] == "bind" else None
        item["confidence"] = "人工"
        item["how"] = {"bind": "手动绑定", "unmatch": "手动取消归属", "ignore": "已标记非商品"}[rule["action"]]
        item["match_detail"] = None
        item["ignored"] = rule["action"] == "ignore"
    return result

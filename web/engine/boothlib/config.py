# SPDX-License-Identifier: GPL-3.0-only
"""配置与路径管理。

缓存/数据默认放在 %LOCALAPPDATA%\\BoothNest（可写、与程序安装位置解耦），
扫描根目录首次使用时由用户选择。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

APP_NAME = "BoothNest"

DEFAULT_ROOT = ""


def _local_appdata() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base)
    return Path.home() / "AppData" / "Local"


def _probe_writable(p: Path) -> bool:
    """目录能否**真正写入文件**（mkdir 成功不代表能写）。"""
    try:
        p.mkdir(parents=True, exist_ok=True)
        f = p / ".writable"
        f.write_text("ok", encoding="utf-8")
        f.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _pick_home() -> Path:
    """挑一个可写的数据目录。

    ★ 本机实测：当 exe 位于某些目录下（例如 DSH 工作区 / 受策略限制的路径）时，
      安全软件会拒绝该进程在 %LOCALAPPDATA% 下新建文件（mkdir 成功、写文件
      返回 WinError 5）。表现为「程序能起，但 profile 建不出来、窗口打不开」。
      所以启动时要**探测可写性**，不可写就退到别处，而不是假定能用。

    ★ 优先复用**已经有数据**的目录：否则换了落点就会显示「还没有数据」，
      用户会以为结果丢了。所以先看哪个候选目录已经有 dataset.json。

    优先级：
      1. 已有 dataset.json 且可写的目录（复用既有数据）
      2. %LOCALAPPDATA%/BoothNest   （标准位置）
      3. %USERPROFILE%/BoothNest
    需要自定义落点时，显式设置 BOOTH_NEST_HOME；不使用临时目录保存库存。
    """
    standard = _local_appdata() / APP_NAME
    userprof = Path.home() / APP_NAME

    ordered = [standard, userprof]

    # 1) 复用已有数据的目录
    for c in ordered:
        try:
            if (c / "data" / "dataset.json").exists() and _probe_writable(c):
                return c
        except Exception:
            continue

    # 2) 第一个可写的标准位置
    for c in ordered:
        if _probe_writable(c):
            return c

    return standard


class Config:
    """应用配置 + 目录布局。"""

    def __init__(self, home: Path | None = None):
        override = os.environ.get("BOOTH_NEST_HOME")
        if override and not Path(override).is_absolute():
            raise ValueError("BOOTH_NEST_HOME 必须是绝对路径")
        self.home = Path(home) if home else (Path(override) if override else _pick_home())
        self.config_file = self.home / "config.json"
        self.cache_dir = self.home / "cache"
        self.items_dir = self.cache_dir / "items"
        self.search_dir = self.cache_dir / "search"
        self.data_dir = self.home / "data"
        self.export_dir = self.home / "export"
        self.log_dir = self.home / "logs"

        self.root = DEFAULT_ROOT
        self.options = {}
        self._loaded = False

    # ---------- 目录 ----------
    def ensure_dirs(self) -> None:
        for d in (self.home, self.cache_dir, self.items_dir, self.search_dir,
                  self.data_dir, self.export_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---------- 读写 ----------
    def load(self) -> "Config":
        try:
            if self.config_file.exists():
                d = json.loads(self.config_file.read_text(encoding="utf-8"))
                if not isinstance(d, dict) or not isinstance(d.get("options", {}), dict):
                    raise ValueError("配置结构无效")
                self.root = d.get("root") or DEFAULT_ROOT
                self.options = d.get("options") or {}
        except (ValueError, OSError) as exc:
            raise RuntimeError(f"无法读取设置，请先备份并检查 {self.config_file}：{exc}") from exc
        self._loaded = True
        return self

    def save(self) -> None:
        self.ensure_dirs()
        payload = {"root": self.root, "options": self.options}
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.home,
                                             prefix="config-", suffix=".tmp", delete=False) as f:
                tmp = f.name
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.config_file)
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    # ---------- 常用数据文件 ----------
    def data(self, name: str) -> Path:
        return self.data_dir / name

    def item_file(self, item_id) -> Path:
        return self.items_dir / f"{item_id}.json"

    def search_file(self, key: str) -> Path:
        return self.search_dir / f"{key}.json"

    def get(self, key: str, default=None):
        return self.options.get(key, default)

    def set(self, key: str, value) -> None:
        self.options[key] = value

    def describe(self) -> dict:
        return {
            "home": str(self.home),
            "root": self.root,
            "cache_items": len(list(self.items_dir.glob("*.json"))),
            "cache_search": len(list(self.search_dir.glob("*.json"))),
        }

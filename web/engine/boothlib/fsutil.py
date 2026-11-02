# SPDX-License-Identifier: GPL-3.0-only
"""文件系统探测的安全封装。

★ 为什么需要这一层（2026-10-09 实测）：

    `pathlib.Path.is_dir()` / `is_file()` 在遇到**无权限**或**断开的网络盘**时
    不是返回 False，而是**抛 PermissionError**：

        >>> Path(r"X:\\").is_dir()
        PermissionError: [WinError 5] 拒绝访问。: 'X:\\'
        >>> Path(r"\\nas.example\\share").is_dir()
        PermissionError: [WinError 5] 拒绝访问。

    X:/Y:/Z: 是网络盘（\\\\nas.example、\\\\nas.example）。NAS 一断开或权限一变，
    原本「检查一下路径」的代码就会直接崩。实测后果：

      - `Api.set_root()` 抛未捕获异常 → GUI 拿不到 {"ok": false}，请求 500，
        而且 `tests/test_api.py` 在 HEAD 上就已经失败
      - `scanner.scan()` 抛 PermissionError → 整轮刷新以原始 traceback 收场，
        用户只看到「出错：拒绝访问」，不知道是网盘掉了

    所以：**凡是「探测路径是否存在」的地方，一律走这里**，
    把异常收敛成布尔值，让调用方去决定怎么提示。
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "is_dir_safe", "is_file_safe", "exists_safe", "stat_safe",
    "listdir_safe", "walk_error_free", "describe_access_error",
]


def is_dir_safe(p) -> bool:
    """p 是不是目录。无权限/盘断开 → False（不抛异常）。"""
    try:
        return os.path.isdir(p)
    except (OSError, ValueError):
        return False


def is_file_safe(p) -> bool:
    """p 是不是文件。无权限/盘断开 → False（不抛异常）。"""
    try:
        return os.path.isfile(p)
    except (OSError, ValueError):
        return False


def exists_safe(p) -> bool:
    """p 是否存在（不区分文件/目录）。无权限/盘断开 → False。"""
    try:
        return os.path.exists(p)
    except (OSError, ValueError):
        return False


def stat_safe(p):
    """取 stat 结果；失败返回 None（调用方按「取不到」处理）。"""
    try:
        return os.stat(p)
    except (OSError, ValueError):
        return None


def listdir_safe(p) -> list[str]:
    """列目录；失败返回 []（与"空目录"同义，调用方需自行区分）。"""
    try:
        return os.listdir(p)
    except (OSError, ValueError):
        return []


def walk_error_free(root):
    """os.walk 的容错版：进入不了的子目录直接跳过，而不是中断整次遍历。

    os.walk 默认 onerror=None 时**会静默吞掉**扫描错误，但那也意味着
    权限问题的目录会被无声略过、统计偏小。这里改成显式记录并继续，
    让调用方可以拿到「哪些目录没读成」。
    """
    errors: list[tuple[str, str]] = []

    def _onerr(e: OSError):
        errors.append((getattr(e, "filename", "") or "", str(e)))

    for dirpath, dirnames, filenames in os.walk(root, onerror=_onerr):
        yield dirpath, dirnames, filenames, errors


def describe_access_error(p) -> str:
    """把「路径不可用」翻译成给人看的一句话（用于 GUI 提示）。

    先查盘符本身：X:/Y:/Z: 都是网络映射（\\\\nas.example、\\\\nas.example）。
    NAS 一断，报「盘符不可访问」比报「目录不存在」有用得多 ——
    用户会去检查网盘，而不是怀疑自己路径写错了。
    """
    p = str(p)
    drive = Path(p).drive
    if drive:
        droot = drive + os.sep
        if not is_dir_safe(droot):
            return (f"无法访问 {droot} —— 该磁盘/网络映射未连接或没有权限"
                    f"（目标：{p}）")
    if not exists_safe(p):
        return f"路径不存在：{p}"
    if is_dir_safe(p):
        return f"目录没有读取权限：{p}"
    return f"不是目录：{p}"

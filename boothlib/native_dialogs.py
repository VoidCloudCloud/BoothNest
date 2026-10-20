# SPDX-License-Identifier: GPL-3.0-only
"""Windows folder picker without a bundled tkinter runtime."""
from __future__ import annotations

import os


def pick_folder(initial: str = "") -> str:
    if os.name != "nt":
        raise RuntimeError("目录选择器仅支持 Windows，请手动输入路径")
    import ctypes as C
    from ctypes import wintypes as W

    shell = C.WinDLL("shell32", use_last_error=True)
    ole = C.OleDLL("ole32")
    user = C.WinDLL("user32")
    callback_t = C.WINFUNCTYPE(C.c_int, W.HWND, W.UINT, W.LPARAM, W.LPARAM)

    class BrowseInfo(C.Structure):
        _fields_ = [("hwndOwner", W.HWND), ("pidlRoot", C.c_void_p),
                    ("pszDisplayName", W.LPWSTR), ("lpszTitle", W.LPCWSTR),
                    ("ulFlags", W.UINT), ("lpfn", callback_t),
                    ("lParam", W.LPARAM), ("iImage", C.c_int)]

    user.GetForegroundWindow.restype = W.HWND
    user.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user.SendMessageW.restype = W.LPARAM
    shell.SHBrowseForFolderW.argtypes = [C.POINTER(BrowseInfo)]
    shell.SHBrowseForFolderW.restype = C.c_void_p
    shell.SHGetPathFromIDListW.argtypes = [C.c_void_p, W.LPWSTR]
    shell.SHGetPathFromIDListW.restype = W.BOOL
    ole.CoInitializeEx.argtypes = [C.c_void_p, W.DWORD]
    ole.CoTaskMemFree.argtypes = [C.c_void_p]
    ole.CoInitializeEx(None, 2)
    try:
        init_buf = C.create_unicode_buffer(initial)

        @callback_t
        def callback(hwnd, message, _param, _data):
            if message == 1 and initial:
                user.SendMessageW(hwnd, 0x467, 1, C.addressof(init_buf))
            return 0

        display = C.create_unicode_buffer(32768)
        info = BrowseInfo(user.GetForegroundWindow(), None, C.cast(display, W.LPWSTR),
                          "选择 BOOTH 下载目录", 0x41, callback, 0, 0)
        pidl = shell.SHBrowseForFolderW(C.byref(info))
        if not pidl:
            return ""
        try:
            buf = C.create_unicode_buffer(32768)
            if not shell.SHGetPathFromIDListW(pidl, buf):
                raise RuntimeError("请选择文件系统目录")
            return buf.value
        finally:
            ole.CoTaskMemFree(pidl)
    finally:
        ole.CoUninitialize()

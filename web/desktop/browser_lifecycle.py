# SPDX-License-Identifier: GPL-3.0-only
"""Confirm native browser windows before ending a desktop session.

Chromium can suspend JavaScript in an open, minimized or occluded window.
Missing page heartbeats and pagehide events therefore cannot prove a close.
"""
import ctypes
from ctypes import wintypes
import ntpath
import os


def uses_profile(arguments, profile):
    expected = ntpath.normcase(ntpath.normpath(os.fspath(profile)))
    for index, argument in enumerate(arguments):
        value = None
        if argument == '--user-data-dir' and index + 1 < len(arguments):
            value = arguments[index + 1]
        elif argument.startswith('--user-data-dir='):
            value = argument.split('=', 1)[1]
        if value is not None and ntpath.normcase(ntpath.normpath(value)) == expected:
            return True
    return False


class BrowserWindowProbe:
    """Return True/False for this profile's visible windows, None if unknown.

    Minimized windows remain visible to IsWindowVisible. Query only native
    window ownership and the owner's command line, never page contents.
    """
    def __init__(self, profile):
        self.profile = profile

    def is_open(self):
        if os.name != 'nt':
            return None
        try:
            user = ctypes.WinDLL('user32', use_last_error=True)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            native = ctypes.WinDLL('ntdll', use_last_error=True)
            shell = ctypes.WinDLL('shell32', use_last_error=True)
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
            user.EnumWindows.restype = wintypes.BOOL
            user.IsWindowVisible.argtypes = [wintypes.HWND]
            user.IsWindowVisible.restype = wintypes.BOOL
            user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user.GetClassNameW.restype = ctypes.c_int
            user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user.GetWindowThreadProcessId.restype = wintypes.DWORD
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree.restype = ctypes.c_void_p
            native.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_uint, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
            native.NtQueryInformationProcess.restype = wintypes.LONG
            shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
            shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)

            class UnicodeString(ctypes.Structure):
                _fields_ = [('length', wintypes.USHORT), ('maximum', wintypes.USHORT), ('buffer', ctypes.c_void_p)]

            def matches_process(pid):
                handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
                if not handle:
                    return None
                try:
                    needed = wintypes.ULONG()
                    native.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(needed))
                    if needed.value < ctypes.sizeof(UnicodeString) or needed.value > 1048576:
                        return None
                    buffer = ctypes.create_string_buffer(needed.value)
                    if native.NtQueryInformationProcess(handle, 60, buffer, len(buffer), ctypes.byref(needed)) < 0:
                        return None
                    value = ctypes.cast(buffer, ctypes.POINTER(UnicodeString)).contents
                    offset = (value.buffer or 0) - ctypes.addressof(buffer)
                    if value.length % 2 or offset < ctypes.sizeof(UnicodeString) or offset + value.length > len(buffer):
                        return None
                    command = ctypes.wstring_at(value.buffer, value.length // 2)
                    count = ctypes.c_int()
                    arguments = shell.CommandLineToArgvW(command, ctypes.byref(count))
                    if not arguments:
                        return None
                    try:
                        return uses_profile([arguments[index] for index in range(count.value)], self.profile)
                    finally:
                        kernel.LocalFree(ctypes.cast(arguments, ctypes.c_void_p))
                finally:
                    kernel.CloseHandle(handle)

            results = []
            processes = {}

            @callback_type
            def visit(window, _):
                try:
                    if not user.IsWindowVisible(window):
                        return True
                    name = ctypes.create_unicode_buffer(256)
                    if not user.GetClassNameW(window, name, len(name)):
                        results.append(None)
                        return True
                    if name.value != 'Chrome_WidgetWin_1':
                        return True
                    pid = wintypes.DWORD()
                    user.GetWindowThreadProcessId(window, ctypes.byref(pid))
                    if pid.value not in processes:
                        processes[pid.value] = matches_process(pid.value)
                    results.append(processes[pid.value])
                except Exception:
                    results.append(None)
                return True

            if not user.EnumWindows(visit, 0):
                return None
            if True in results:
                return True
            return None if None in results else False
        except (OSError, AttributeError, ValueError):
            return None


class WindowLifetime:
    """Require a previously observed window to stay absent through a grace period."""
    def __init__(self, grace_seconds=5):
        self.grace_seconds = grace_seconds
        self.seen = False
        self.absent_since = None

    def should_stop(self, window_open, now):
        if window_open is True:
            self.seen = True
            self.absent_since = None
        elif window_open is None:
            # Unknown access must not turn a paused page into a false close.
            self.absent_since = None
        elif self.seen:
            if self.absent_since is None:
                self.absent_since = now
            return now - self.absent_since >= self.grace_seconds
        return False

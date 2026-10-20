# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for BoothNest desktop app.

Build (from project root):
    <python> -m PyInstaller build/booth_nest.spec --noconfirm

Output: dist/BoothNest/BoothNest.exe  (onedir)

IMPORTANT (do not "fix" these):
  * Entry script MUST be the package-external run.py. PyInstaller executes the
    entry as a top-level __main__ module, so boothlib/app.py's relative imports
    (`from .api import Api`) would fail with
    "attempted relative import with no known parent package".
  * Do NOT exclude `distutils`: setuptools vendors it, and PyInstaller's
    hook-distutils must alias it; excluding it aborts the build with
    ValueError: Target module "distutils" already imported as ExcludedModule.
  * Keep this file ASCII-only. Writing Chinese comments through PowerShell
    redirection corrupted the encoding and swallowed a code line.
  * The ui.html data dir MUST NOT be named "boothlib". PyInstaller would create
    `_internal/boothlib/` as a plain data folder, which **shadows the frozen
    boothlib package**, so `from boothlib.app import main` dies before any code
    runs (symptom: exe exits 0 instantly, no output, no traceback, no crash log
    — impossible to diagnose from inside Python). Use the "assets" folder.
"""
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent      # noqa: F821 (injected by PyInstaller)

# ui.html ships under _internal/assets (NOT boothlib/ — see note above).
# Personal inventories and caches must never be bundled.
datas = [
    (str(ROOT / "boothlib" / "ui.html"), "assets"),
]

hiddenimports = [
    "boothlib", "boothlib.app", "boothlib.api", "boothlib.analytics",
    "boothlib.booth_client", "boothlib.config", "boothlib.exporter",
    "boothlib.fsutil", "boothlib.matching", "boothlib.migrate",
    "boothlib.pipeline", "boothlib.scanner",
    "boothlib.server",
    "boothlib.native_dialogs",
    "boothlib.instance",
    "boothlib.curation", "boothlib.duplicates",
]

excludes = [
    "tkinter", "unittest", "pydoc_data", "test",
    "matplotlib", "numpy", "pandas", "scipy", "PIL",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    # webview / .NET 链路整体排除：桌面版改用「本地 HTTP + Edge --app」，
    # 不再依赖 pythonnet 与 .NET 运行时（冻结后无法解析入口点）。
    "webview", "clr", "clr_loader", "pythonnet",
]

a = Analysis(                               # noqa: F821
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)                           # noqa: F821

exe = EXE(                                  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BoothNest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                              # UPX triggers AV false positives
    console=False,                          # GUI app, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=str(ROOT / "build" / "version_info.txt"),
)

coll = COLLECT(                             # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BoothNest",
)

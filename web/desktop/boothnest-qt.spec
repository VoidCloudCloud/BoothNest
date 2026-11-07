from pathlib import Path
import os
import ssl

ROOT = Path(SPECPATH).resolve().parent
node = Path(os.environ['BOOTH_NEST_NODE'])
datas = [(str(node), 'runtime'), (str(ROOT / 'server.mjs'), 'site')]
ssl_policy = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
if ssl_policy.is_file():
    datas.append((str(ssl_policy), '.'))
for folder in ['lib', 'public', 'resources']:
    for item in (ROOT / folder).rglob('*'):
        if item.is_file() and 'media' not in item.relative_to(ROOT / folder).parts:
            datas.append((str(item), 'site/' + item.parent.relative_to(ROOT).as_posix()))
datas.append((str(ROOT / 'engine/boothlib/ui.html'), 'site/engine/boothlib'))
a = Analysis([str(ROOT / 'desktop/qt_main.py')],
    pathex=[str(ROOT / 'desktop'), str(ROOT / 'engine')], datas=datas, binaries=[],
    hiddenimports=['worker', 'boothlib.api', 'boothlib.config', 'boothlib.pipeline', 'boothlib.scanner',
        'boothlib.matching', 'boothlib.migrate', 'boothlib.booth_client', 'boothlib.analytics',
        'boothlib.exporter', 'boothlib.curation', 'boothlib.duplicates', 'boothlib.fsutil',
        'boothlib.native_dialogs', 'boothlib.instance', 'boothlib.app', 'boothlib.server',
        'qtclient.smoke'],
    excludes=['tkinter', 'numpy', 'pandas', 'scipy', 'matplotlib', 'PIL', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'PySide6.QtQuick', 'webview', 'clr', 'pythonnet'],
    noarchive=False, optimize=0)
# Qt uses Windows' unversioned ICU API. A different ICU on the build machine's
# PATH can be collected under the same name but export version-suffixed symbols.
# Keep these OS libraries on the system rather than shadowing them in _internal.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icuin.dll', 'icudt.dll'}]
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='BoothNestQt', console=False, upx=False, strip=False)
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='BoothNestQtEngine', console=True, upx=False, strip=False)
coll = COLLECT(gui, worker, a.binaries, a.datas, name='BoothNestQt', upx=False, strip=False)

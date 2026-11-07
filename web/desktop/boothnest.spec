from pathlib import Path
import os
import ssl

ROOT = Path(SPECPATH).resolve().parent
node = Path(os.environ['BOOTH_NEST_NODE'])
datas = [(str(node), 'runtime'), (str(ROOT / 'server.mjs'), 'site')]
# Some Python distributions load a certificate policy beside ssl.py. Keep
# that dependency when freezing so HTTPS still initializes with verification.
ssl_policy = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
if ssl_policy.is_file():
    datas.append((str(ssl_policy), '.'))
for folder in ['lib', 'public', 'resources']:
    for item in (ROOT / folder).rglob('*'):
        if item.is_file() and 'media' not in item.relative_to(ROOT / folder).parts:
            datas.append((str(item), 'site/' + item.parent.relative_to(ROOT).as_posix()))
datas.append((str(ROOT / 'engine/boothlib/ui.html'), 'site/engine/boothlib'))
a = Analysis([str(ROOT / 'desktop/main.py')], pathex=[str(ROOT / 'engine')], binaries=[], datas=datas,
    hiddenimports=['worker','boothlib.api','boothlib.config','boothlib.pipeline','boothlib.scanner','boothlib.matching','boothlib.migrate','boothlib.booth_client','boothlib.analytics','boothlib.exporter','boothlib.curation','boothlib.duplicates','boothlib.fsutil','boothlib.native_dialogs','boothlib.instance','boothlib.app','boothlib.server'],
    excludes=['tkinter','numpy','pandas','scipy','matplotlib','PIL','webview','clr','pythonnet','unittest','test'], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='BoothNest', console=False, upx=False, strip=False)
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='BoothNestEngine', console=True, upx=False, strip=False)
coll = COLLECT(gui, worker, a.binaries, a.datas, name='BoothNest', upx=False, strip=False)

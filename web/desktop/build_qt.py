# SPDX-License-Identifier: GPL-3.0-only
"""Build a separate native client without replacing the installed web client."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--archives-only', action='store_true', help='Archive an already completed build')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, BOOTH_NEST_NODE=str(args.node.resolve()))
    if not args.archives_only:
        subprocess.run([sys.executable, '-m', 'PyInstaller', str(source / 'desktop/boothnest-qt.spec'),
                    '--noconfirm', '--distpath', str(output / 'dist'), '--workpath', str(output / 'build')],
                   cwd=source, env=env, check=True)
    payload = output / 'dist/BoothNestQt'
    for name in ['LICENSE', 'PRIVACY.md', 'THIRD_PARTY_NOTICES.md']:
        shutil.copy2(source / name, payload / name)
    shutil.copy2(source / 'docs/QT_CLIENT.md', payload / 'README-Qt.md')
    if (source / 'licenses').is_dir():
        shutil.copytree(source / 'licenses', payload / 'licenses', dirs_exist_ok=True)
    from importlib.metadata import distribution
    for name in ['PySide6-Essentials', 'shiboken6']:
        package = distribution(name)
        for relative in package.files:
            if '/licenses/' in relative.as_posix():
                target = payload / 'licenses' / name / Path(relative).name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(package.locate_file(relative), target)
    shutil.copy2(source / 'docs/QT_THIRD_PARTY.md', payload / 'QT_THIRD_PARTY.md')
    # The build machine's private data and data-home pointer are never release inputs.
    forbidden = {'catalog.json','catalog.seed.json','dataset.json','config.json','purchases.json',
                 'desktop-session.json','data-home.json','web-preferences.json','manual_overrides.json'}
    files = [file for file in payload.rglob('*') if file.is_file()]
    for file in files:
        if file.name in forbidden:
            raise RuntimeError('Private file in native package: ' + str(file.relative_to(payload)))
    manifest = {file.relative_to(payload).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in files}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    with zipfile.ZipFile(output / 'BoothNestQt-windows-x64.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, 'BoothNestQt/' + file.relative_to(payload).as_posix())
    from build_release import web_sources, inspect_zip
    source_files = set(web_sources()) | {source / 'requirements-qt.txt'}
    source_files.update((source / 'licenses').glob('*.txt'))
    source_zip = output / 'BoothNestQt-source.zip'
    with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(source_files):
            archive.write(file, 'BoothNestQt-source/' + file.relative_to(source).as_posix())
    inspect_zip(source_zip)
    checksums = {name:hashlib.sha256((output / name).read_bytes()).hexdigest()
                 for name in ('BoothNestQt-windows-x64.zip','BoothNestQt-source.zip')}
    (output / 'SHA256SUMS.txt').write_text(''.join(f'{digest}  {name}\n' for name,digest in checksums.items()), encoding='ascii')
    print(str(payload / 'BoothNestQt.exe'))


if __name__ == '__main__':
    main()

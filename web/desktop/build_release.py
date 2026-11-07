# SPDX-License-Identifier: GPL-3.0-only
"""Build an empty, portable GUI and its complete corresponding source archive."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2.0.0-beta.5'
FORBIDDEN = {'data', 'cache', 'export', 'logs', 'browser-next', '__pycache__', 'node_modules', 'artifacts', 'reference', '.git', 'desktop-build'}
PRIVATE = {'dataset.json', 'config.json', 'web-preferences.json', 'public-sync.json', 'local-library.json', 'manual_overrides.json', 'catalog.json', 'catalog.seed.json', 'desktop-session.json', 'data-home.json', 'purchase-bridge.json', 'purchases.json'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def web_sources():
    names = ['server.mjs', 'package.json', 'Start.cmd', 'README.md', 'PRIVACY.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE', 'requirements-build.txt']
    paths = [ROOT / name for name in names]
    allowed = {'.mjs', '.js', '.cjs', '.json', '.py', '.spec', '.html', '.css', '.svg', '.md', '.txt', '.sqlite'}
    for folder in ['lib', 'public', 'engine', 'desktop', 'tests', 'scripts', 'docs', 'resources']:
        paths.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and p.suffix in allowed
                     and not any(part in FORBIDDEN | {'media'} for part in p.relative_to(ROOT).parts))
    return sorted(set(paths))


def inspect_zip(path):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            parts = Path(name).parts
            synthetic_fixture = '/tests/fixtures/' in name and Path(name).name == 'catalog.json'
            if any(p in FORBIDDEN for p in parts) or (Path(name).name in PRIVATE and not synthetic_fixture):
                raise ValueError('Private file in release: ' + name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, help='Canonical repository root to include alongside web sources')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('Build the Windows package on Windows.')
    node = os.environ.get('BOOTH_NEST_NODE') or shutil.which('node')
    if not node or not Path(node).is_file():
        raise SystemExit('Install Node.js 22.13+ or set BOOTH_NEST_NODE to node.exe.')
    version = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')
    if tuple(map(int, version[:2])) < (22, 13):
        raise SystemExit('Node.js 22.13+ is required for the read-only open-data index.')
    env = {**os.environ, 'BOOTH_NEST_NODE': str(Path(node).resolve())}
    subprocess.run([sys.executable, '-m', 'PyInstaller', str(ROOT / 'desktop/boothnest.spec'), '--noconfirm', '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'desktop-build')], cwd=ROOT, env=env, check=True)
    payload = ROOT / 'dist/BoothNest'
    for name in ['README.md', 'PRIVACY.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE']:
        shutil.copy2(ROOT / name, payload / name)
    shutil.copytree(ROOT / 'docs', payload / 'docs', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'licenses', payload / 'licenses', dirs_exist_ok=True)
    (payload / 'Install.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "" "BoothNest.exe" --install\r\n', encoding='ascii')
    for name in ['BoothNest.exe', 'BoothNestEngine.exe', '_internal/runtime/node.exe', '_internal/site/server.mjs', '_internal/site/engine/boothlib/ui.html', 'licenses/Node-LICENSE.txt', 'licenses/Python-LICENSE.txt', 'licenses/PyInstaller-COPYING.txt']:
        if not (payload / name).is_file():
            raise ValueError('Missing release file: ' + name)
    release = ROOT / 'release'
    release.mkdir(exist_ok=True)
    binary = release / f'BoothNest-{VERSION}-windows-x64.zip'
    with zipfile.ZipFile(binary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(payload.rglob('*')):
            if file.is_file():
                archive.write(file, 'BoothNest/' + file.relative_to(payload).as_posix())
    source = release / f'BoothNest-{VERSION}-source.zip'
    prefix = f'BoothNest-{VERSION}/'
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in web_sources():
            archive.write(file, prefix + ('web/' if args.source_root else '') + file.relative_to(ROOT).as_posix())
        for file in (ROOT / 'licenses').glob('*.txt'):
            archive.write(file, prefix + ('web/' if args.source_root else '') + 'licenses/' + file.name)
        if args.source_root:
            repo = args.source_root.resolve()
            for folder in ['boothlib', 'tools', 'tests', 'build', 'docs', '.github']:
                for file in sorted((repo / folder).rglob('*')):
                    if file.is_file() and not any(p in FORBIDDEN | {'work'} for p in file.relative_to(repo).parts) and file.suffix in {'.py', '.spec', '.txt', '.md', '.json', '.yml', '.html', '.png'}:
                        archive.write(file, prefix + file.relative_to(repo).as_posix())
            for name in ['run.py', 'pyproject.toml', 'requirements-build.txt', 'README.md', 'CHANGELOG.md', 'LICENSE', 'PRIVACY.md', 'THIRD_PARTY_NOTICES.md', 'SECURITY.md', 'CONTRIBUTING.md', '.gitignore', '.gitattributes']:
                file = repo / name
                if file.is_file():
                    archive.write(file, prefix + name)
    for file in [binary, source]:
        inspect_zip(file)
        file.with_suffix('.zip.sha256').write_text(digest(file) + '  ' + file.name + '\n', encoding='ascii')
    manifest = {'version': VERSION, 'program': binary.name, 'sha256': digest(binary), 'source': source.name, 'sourceSha256': digest(source), 'files': {p.relative_to(payload).as_posix(): digest(p) for p in sorted(payload.rglob('*')) if p.is_file()}}
    binary.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'program': str(binary), 'source': str(source), 'sha256': manifest['sha256'], 'files': len(manifest['files']), 'privacyCheck': 'passed'}))


if __name__ == '__main__':
    main()

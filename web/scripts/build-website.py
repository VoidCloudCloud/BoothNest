"""Build a code-only website archive without runtime data or metadata databases."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'server.mjs', 'online.mjs', 'package.json', 'Start.cmd', 'README.md',
              'PRIVACY.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE', 'CHANGELOG.md',
              'Dockerfile', 'compose.yaml', '.dockerignore', '.env.example'}
FOLDERS = {
    'lib': {'.mjs'}, 'public': {'.js', '.html', '.css', '.svg', '.json', '.md', '.txt'},
    'engine': {'.py', '.html'}, 'tests': {'.mjs', '.html'}, 'docs': {'.md'},
}
SCRIPTS = {'build-website.py', 'verify-empty-ui.mjs'}
FORBIDDEN_PARTS = {'data', 'cache', 'media', 'reference', 'artifacts', 'release',
                   'dist', '__pycache__', 'node_modules', '.git', 'online-seed'}
FORBIDDEN_NAMES = {'catalog.json', 'catalog.seed.json', 'dataset.json', 'purchases.json',
                   'config.json', 'web-preferences.json', 'public-sync.json',
                   'local-library.json', 'purchase-bridge.json', '.env'}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def source_files():
    files = [ROOT / name for name in sorted(ROOT_FILES)]
    files.extend(ROOT / 'scripts' / name for name in sorted(SCRIPTS))
    for folder, suffixes in FOLDERS.items():
        files.extend(file for file in (ROOT / folder).rglob('*') if file.is_file()
                     and file.suffix in suffixes
                     and not any(part in FORBIDDEN_PARTS for part in file.relative_to(ROOT).parts))
    for file in files:
        if not file.is_file():
            raise ValueError('Missing website source: ' + str(file))
        relative = file.relative_to(ROOT)
        if file.name in FORBIDDEN_NAMES or any(part in FORBIDDEN_PARTS for part in relative.parts):
            raise ValueError('Private data selected: ' + str(relative))
    return sorted(set(files))

def inspect(archive_path, expected):
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corrupt archive')
        actual = {name.split('/', 1)[1]: digest(archive.read(name)) for name in archive.namelist()}
        if actual != expected:
            raise ValueError('Archive source/hash mismatch')
        for name in actual:
            parts = Path(name).parts
            if any(part in FORBIDDEN_PARTS for part in parts) or Path(name).name in FORBIDDEN_NAMES:
                raise ValueError('Private data in archive: ' + name)
            if Path(name).suffix.lower() in {'.sqlite', '.db', '.parquet', '.png', '.jpg', '.jpeg', '.webp', '.zip'}:
                raise ValueError('Dataset or cached media in archive: ' + name)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'release')
    args = parser.parse_args()
    version = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = f'BoothNest-Web-{version}-source'
    archive_path = output / (name + '.zip')
    sources = {}
    for file in source_files():
        data = file.read_bytes().replace(b'\r\n', b'\n')
        if file.suffix == '.cmd':
            data = data.replace(b'\n', b'\r\n')
        sources[file.relative_to(ROOT).as_posix()] = data
    hashes = {name: digest(data) for name, data in sources.items()}
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, data in sorted(sources.items()):
            info = zipfile.ZipInfo(f'BoothNest-Web-{version}/' + relative, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    inspect(archive_path, hashes)
    archive_hash = digest(archive_path.read_bytes())
    archive_path.with_suffix('.zip.sha256').write_text(archive_hash + '  ' + archive_path.name + '\n', encoding='ascii')
    manifest = {'version': version, 'kind': 'website-code-only', 'archive': archive_path.name,
                'sha256': archive_hash, 'bundledDatasets': [], 'bundledMedia': [], 'files': hashes}
    (output / (name + '.manifest.json')).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'archive': str(archive_path), 'files': len(hashes), 'sha256': archive_hash,
                      'bundledDatasets': 0, 'bundledMedia': 0}))

if __name__ == '__main__':
    main()

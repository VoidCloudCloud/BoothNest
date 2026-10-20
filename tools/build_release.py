# SPDX-License-Identifier: GPL-3.0-only
"""Build a clean release, create the installer, inspect the payload and hash it."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from boothlib import __version__
from check_release import check_folder, check_zip, source_files
from make_installer import generate


def main():
    if sys.platform != "win32":
        raise SystemExit("Build the Windows release on Windows.")
    subprocess.run([sys.executable, "-m", "PyInstaller", "build/booth_nest.spec",
                    "--noconfirm", "--clean", "--distpath", "dist", "--workpath", "build/work"],
                   cwd=ROOT, check=True)
    payload = ROOT / "dist" / "BoothNest"
    generate(payload)
    for name in ("README.md", "PRIVACY.md", "SECURITY.md", "CONTRIBUTING.md",
                 "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "LICENSE"):
        if (ROOT / name).is_file():
            shutil.copy2(ROOT / name, payload / name)
    shutil.copytree(ROOT / "docs" / "licenses", payload / "licenses", dirs_exist_ok=True)
    shutil.copytree(ROOT / "docs", payload / "docs", dirs_exist_ok=True)
    check_folder(payload)
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    archive = release / f"BoothNest-{__version__}-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                z.write(path, "BoothNest/" + path.relative_to(payload).as_posix())
    check_zip(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    source_archive = release / f"BoothNest-{__version__}-source.zip"
    with zipfile.ZipFile(source_archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in source_files(ROOT):
            z.write(path, f"BoothNest-{__version__}/" + path.relative_to(ROOT).as_posix())
    check_zip(source_archive)
    source_digest = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    source_archive.with_suffix(".zip.sha256").write_text(
        f"{source_digest}  {source_archive.name}\n", encoding="ascii")
    manifest = {"version": __version__, "archive": archive.name, "sha256": digest,
                "source_archive": source_archive.name, "source_sha256": source_digest,
                "files": {p.relative_to(payload).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(payload.rglob("*")) if p.is_file()}}
    archive.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(archive)
    print("SHA256: " + digest)


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: GPL-3.0-only
"""Fail packaging if private inventories, logs or developer paths would ship."""
from pathlib import Path
import sys
import zipfile

FORBIDDEN_DIRS = {"seed", "data", "cache", "export", "logs", "__pycache__", ".wvdata", "wvdata"}
FORBIDDEN_FILES = {"config.json", "dataset.json", "probe_cache.json", "manual_overrides.json", "安装.cmd"}


def source_files(root: Path):
    names = {"run.py", "pyproject.toml", "requirements-build.txt", "README.md", "LICENSE",
             "CHANGELOG.md", "PRIVACY.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md",
             ".gitignore", ".gitattributes", "build/booth_nest.spec", "build/version_info.txt"}
    names.update("tools/" + n for n in ("build_release.py", "check_release.py", "make_installer.py", "test.py"))
    names.update("tests/" + n for n in ("test_public_release.py", "test_matching.py", "test_schema.py",
                                       "test_sort_time.py", "test_ui_search.py", "_check_ui_syntax.py", "test_functional_features.py"))
    names.update(p.relative_to(root).as_posix() for p in (root / "boothlib").glob("*.py"))
    names.add("boothlib/ui.html")
    for folder in ("docs", "tests/fixtures", ".github"):
        names.update(p.relative_to(root).as_posix() for p in (root / folder).rglob("*")
                     if p.is_file() and p.suffix in {".md", ".txt", ".json", ".yml"})
    names.update(p.relative_to(root).as_posix() for p in (root / "docs/images").glob("*.png"))
    paths = [root / name for name in sorted(names)]
    for path in paths:
        if not path.is_file():
            raise ValueError("Missing corresponding source: " + str(path.relative_to(root)))
    return paths


def check_folder(folder: Path):
    problems = []
    for path in folder.rglob("*"):
        rel = path.relative_to(folder)
        if (any(p in FORBIDDEN_DIRS for p in rel.parts)
                or path.name in FORBIDDEN_FILES or path.suffix in {".log", ".tmp"}):
            problems.append(str(rel))
    for required in ("BoothNest.exe", "_internal/assets/ui.html", "install.cmd", "install.ps1",
                     "LICENSE", "licenses/Python-LICENSE.txt", "licenses/PyInstaller-COPYING.txt"):
        if not (folder / required).is_file():
            problems.append("Missing: " + required)
    if problems:
        raise ValueError("Release check failed:\n" + "\n".join(problems))
    print("Release privacy and layout checks passed.")


def check_zip(path: Path):
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            parts = Path(name).parts
            if any(p in FORBIDDEN_DIRS for p in parts) or Path(name).name in FORBIDDEN_FILES:
                raise ValueError("Private file in archive: " + name)


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "dist" / "BoothNest"
    check_zip(path) if path.suffix == ".zip" else check_folder(path)

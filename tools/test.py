# SPDX-License-Identifier: GPL-3.0-only
"""Run maintained checks without private datasets or mounted drives."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    commands = [[sys.executable, "-m", "unittest", "discover", "-s", "tests",
                 "-p", "test_public_release.py", "-v"]]
    commands.append([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                     "-p", "test_functional_features.py", "-v"])
    for name in ("test_matching.py", "test_schema.py", "test_sort_time.py",
                 "test_ui_search.py", "_check_ui_syntax.py"):
        commands.append([sys.executable, str(ROOT / "tests" / name)])
    for command in commands:
        result = subprocess.run(command, cwd=ROOT,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if result.returncode:
            return result.returncode
    print("All maintained checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-License-Identifier: GPL-3.0-only
"""Run the native Qt client; the web client remains available independently."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
SOURCE = ROOT / 'site' if getattr(sys, 'frozen', False) else ROOT
sys.path.insert(0, str(SOURCE / 'engine'))

# The packaged scanner shares this entry point but does not initialize Qt.
if len(sys.argv) > 1 and sys.argv[1] == '--worker':
    from worker import run
    run(sys.argv[2])
    raise SystemExit(0)

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox
from qtclient.core import Backend
from qtclient.widgets import STYLE
from qtclient.window import Window


def data_home(override=None):
    override = override or os.environ.get('BOOTH_NEST_HOME')
    if not override and getattr(sys, 'frozen', False):
        pointer = Path(sys.executable).with_name('data-home.json')
        if pointer.is_file():
            override = json.loads(pointer.read_text(encoding='utf-8-sig')).get('home')
    if override:
        if not Path(override).is_absolute():
            raise ValueError('数据目录必须是绝对路径。')
        return Path(override)
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'BoothNest'


def main():
    parser = argparse.ArgumentParser(description='BoothNest native Qt client')
    parser.add_argument('--home', type=Path)
    parser.add_argument('--url', help='Connect to an independently managed loopback service')
    parser.add_argument('--node')
    parser.add_argument('--smoke-test', type=Path, metavar='OUTPUT', help='Test the provided isolated data directory; requires --home')
    args = parser.parse_args()
    home = data_home(args.home)
    if args.smoke_test and (not args.home or args.url):
        parser.error('--smoke-test requires an explicit isolated --home, without --url')
    if args.smoke_test and not (home / '.qt-test-home').is_file():
        parser.error('--smoke-test only accepts a disposable home marked with .qt-test-home')
    app = QApplication(sys.argv[:1])
    app.setApplicationName('BoothNest Qt')
    app.setOrganizationName('BoothNest')
    app.setStyle('Fusion')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    app.setStyleSheet(STYLE)
    def report_exception(kind, value, trace):
        details = ''.join(traceback.format_exception(kind, value, trace))
        try:
            logs = home / 'logs'; logs.mkdir(parents=True, exist_ok=True)
            (logs / 'qt-crash.log').write_text(details, encoding='utf-8')
        except OSError:
            pass
        QMessageBox.critical(None, 'BoothNest', '操作未能完成：' + str(value))
    sys.excepthook = report_exception
    backend = Backend(SOURCE, home, url=args.url, node=args.node)
    window = Window(backend)
    window.show()
    smoke = None
    if args.smoke_test:
        from qtclient.smoke import Smoke
        smoke = Smoke(window, args.smoke_test)
    QTimer.singleShot(0, backend.start)
    code = app.exec()
    if smoke:
        return 0 if smoke.passed else 1
    return code


if __name__ == '__main__':
    raise SystemExit(main())

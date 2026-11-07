# SPDX-License-Identifier: GPL-3.0-only
from .presentation import tr, appearance
from collections import OrderedDict, deque
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import unicodedata
import urllib.request
from urllib.parse import urlencode, urlsplit, quote_plus

from PySide6.QtCore import (QBuffer, QByteArray, QIODevice, QObject, QProcess, Qt,
                            QTimer, QUrl, Signal)
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


def query_string(state, preferences=None):
    """Use exactly the web API's filter names and repeated-value semantics."""
    values = []
    for key, value in state.items():
        if value is None or value == '' or value is False:
            continue
        if isinstance(value, (list, tuple)):
            values.extend((key, str(entry)) for entry in value)
        else:
            values.append((key, '1' if value is True else str(value)))
    preferences = preferences or {}
    view = state.get('view')
    if view in ('favourites', 'recent'):
        ids = preferences.get('favourites', []) if view == 'favourites' else [v['id'] for v in preferences.get('recent-views', [])]
        values.extend(('ids', str(entry)) for entry in ids)
    return urlencode(values)


def saved_query(state):
    """Match discovery-state.js canonicalization, including URLSearchParams quoting."""
    values = []
    for key in ('view','sort','adult','availability','purchase'):
        if state.get(key): values.append((key, state[key]))
    if state.get('q', '').strip(): values.append(('q', state['q'].strip()[:200]))
    excluded = {unicodedata.normalize('NFKC', value.strip()).lower() for value in state.get('excludeTag', [])}
    for key in ('category','avatar','author','tag','excludeTag','feature','fileType','localCategory'):
        seen = set()
        for value in state.get(key, []):
            value = value.strip()[:200]
            if not value or value in seen or len(seen) >= 50: continue
            if key == 'tag' and unicodedata.normalize('NFKC', value).lower() in excluded: continue
            seen.add(value); values.append((key,value))
    for key in ('free','includeMentions','duplicates'):
        if state.get(key): values.append((key,'1'))
    for key in ('min','max','minBytes'):
        if state.get(key) is not None and int(state[key]) >= 0: values.append((key,str(state[key])))
    if state.get('pageSize') in (20,40,60,100): values.append(('pageSize',str(state['pageSize'])))
    def quote(value, safe='', encoding=None, errors=None):
        return quote_plus(value, safe='*', encoding=encoding, errors=errors).replace('~','%7E')
    return urlencode(values, quote_via=quote)


def bytes_label(value):
    value = float(value or 0)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1024


def price_label(item):
    return appearance.money(item.get('price'), item.get('priceKnown', False))


class Api(QObject):
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base = ''
        self.token = ''
        self.network = QNetworkAccessManager(self)
        self.pending = set()

    def request(self, path, done=None, *, body=None, error=None, raw=False):
        request = QNetworkRequest(QUrl(self.base + path))
        request.setTransferTimeout(30000)
        request.setRawHeader(b'Accept', b'application/json')
        if self.token:
            request.setRawHeader(b'X-BoothNest-Token', self.token.encode())
        if body is None:
            reply = self.network.get(request)
        else:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
            reply = self.network.post(request, QByteArray(json.dumps(body, ensure_ascii=False).encode('utf-8')))
        self.pending.add(reply)

        def finish():
            self.pending.discard(reply)
            payload = bytes(reply.readAll())
            try:
                code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
                result = payload if raw else json.loads(payload.decode('utf-8-sig'))
                if code >= 400 or reply.error() != QNetworkReply.NetworkError.NoError:
                    raise RuntimeError(result.get('error', reply.errorString()) if isinstance(result, dict) else reply.errorString())
                if isinstance(result, dict) and result.get('ok') is False:
                    raise RuntimeError(result.get('error', tr('操作未完成')))
            except (ValueError, UnicodeError, RuntimeError) as exc:
                (error or self.failed.emit)(str(exc) if str(exc) else tr('服务连接中断，请重新启动客户端。'))
            else:
                if done:
                    done(result)
            finally:
                reply.deleteLater()
        reply.finished.connect(finish)
        return reply


class Images(QObject):
    changed = Signal()

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.network = QNetworkAccessManager(self)
        self.offline = False
        self.cache = OrderedDict()
        self.waiting = deque()
        self.requested = set()
        self.active = 0
        self.replies = set()

    def allowed(self, value):
        if not isinstance(value, str):
            return False
        if value.startswith(('/media/', '/api/local/image?')) and not value.startswith('//'):
            return True
        url = urlsplit(value)
        return (not self.offline and url.scheme == 'https' and not url.username and not url.password
                and url.hostname in ('booth.pximg.net', 'booth.p.pixiv.net', 'pixiv.pximg.net', 'cdn.vrcatalogue.com'))

    def get(self, candidates):
        key = tuple(value for value in candidates if self.allowed(value))
        if not key:
            return None
        if key in self.cache:
            result = self.cache.pop(key)
            self.cache[key] = result
            return result
        if key not in self.requested:
            self.requested.add(key)
            self.waiting.append((key, list(key), 0))
            QTimer.singleShot(0, self.pump)
        return None

    def pump(self):
        while self.active < 4 and self.waiting:
            key, candidates, redirects = self.waiting.popleft()
            if not candidates:
                self.store(key, None)
                continue
            value = candidates[0]
            if not self.allowed(value):
                self.waiting.append((key, candidates[1:], 0))
                continue
            request = QNetworkRequest(QUrl(self.api.base + value if value.startswith('/') else value))
            request.setTransferTimeout(12000)
            request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                                 QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
            reply = self.network.get(request)
            self.replies.add(reply)
            self.active += 1
            reply.downloadProgress.connect(lambda received, total, r=reply: r.abort() if received > 12_000_000 else None)
            reply.finished.connect(lambda r=reply, k=key, c=candidates, n=redirects: self.finish(r, k, c, n))

    def finish(self, reply, key, candidates, redirects):
        self.active -= 1
        self.replies.discard(reply)
        target = reply.attribute(QNetworkRequest.Attribute.RedirectionTargetAttribute)
        pixmap = None
        if target and redirects < 3:
            target = reply.url().resolved(target).toString()
            if self.allowed(target):
                self.waiting.appendleft((key, [target] + candidates[1:], redirects + 1))
                reply.deleteLater()
                self.pump()
                return
        if reply.error() == QNetworkReply.NetworkError.NoError and not target:
            data = reply.readAll()
            if data.size() <= 12_000_000:
                buffer = QBuffer()
                buffer.setData(data)
                buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                reader = QImageReader(buffer)
                size = reader.size()
                if size.isValid() and size.width() * size.height() <= 60_000_000:
                    reader.setScaledSize(size.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio))
                    image = reader.read()
                    if not image.isNull():
                        pixmap = QPixmap.fromImage(image)
        reply.deleteLater()
        if pixmap is not None or len(candidates) <= 1:
            self.store(key, pixmap)
        else:
            self.waiting.append((key, candidates[1:], 0))
        self.pump()

    def store(self, key, pixmap):
        self.cache[key] = pixmap
        while len(self.cache) > 96:
            self.cache.popitem(last=False)
        self.requested.discard(key)
        self.changed.emit()


class Backend(QObject):
    ready = Signal(str, str)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, source, home, parent=None, url=None, node=None):
        super().__init__(parent)
        self.source, self.home = Path(source), Path(home)
        self.url, self.node = url, node
        self.process = None
        self.lock = None
        self.owned = False
        self.closing = False
        self.token = ''
        self.attempts = 0
        self.probe = QNetworkAccessManager(self)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.poll)

    def start(self):
        if self.url:
            address = urlsplit(self.url)
            if address.scheme != 'http' or address.hostname != '127.0.0.1' or not address.port or address.path not in ('', '/') or address.query or address.fragment or address.username or address.password:
                self.failed.emit(tr('连接地址必须是本机 HTTP 服务地址。'))
                return
            self.url = self.url.rstrip('/')
            self.poll()
            return
        sys.path.insert(0, str(self.source / 'engine'))
        from boothlib.instance import InstanceLock
        self.lock = InstanceLock(self.home)
        if not self.lock.acquire():
            self.failed.emit(tr('这个数据目录已由另一个 BoothNest 使用。请关闭原窗口后重新打开，或使用其他数据目录。'))
            return
        self.home.mkdir(parents=True, exist_ok=True)
        node = self.node or os.environ.get('BOOTH_NEST_NODE')
        bundled = Path(getattr(sys, '_MEIPASS', self.source)) / 'runtime' / 'node.exe'
        if not node:
            node = str(bundled) if bundled.is_file() else shutil.which('node')
        if not node:
            self.failed.emit(tr('没有找到 Node.js，请设置 BOOTH_NEST_NODE。'))
            return
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', 4317))
            except OSError:
                probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        self.url = f'http://127.0.0.1:{port}'
        self.token = secrets.token_hex(32)
        env = dict(os.environ, BOOTH_NEST_WEB_HOME=str(self.home / 'web'),
                   BOOTH_NEST_ENGINE_HOME=str(self.home), BOOTH_NEST_DESKTOP_TOKEN=self.token,
                   PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        worker = Path(sys.executable).with_name('BoothNestQtEngine.exe')
        if getattr(sys, 'frozen', False):
            env['BOOTH_NEST_ENGINE_EXE'] = str(worker)
        else:
            env['BOOTH_NEST_PYTHON'] = sys.executable
        self.process = QProcess(self)
        from PySide6.QtCore import QProcessEnvironment
        environment = QProcessEnvironment()
        for key, value in env.items():
            environment.insert(key, value)
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(self.source))
        logs = self.home / 'logs'
        logs.mkdir(exist_ok=True)
        self.process.setStandardOutputFile(str(logs / 'qt-server.log'), QIODevice.OpenModeFlag.Append)
        self.process.setStandardErrorFile(str(logs / 'qt-server.log'), QIODevice.OpenModeFlag.Append)
        self.process.finished.connect(self.exited)
        self.process.errorOccurred.connect(lambda _: self.failed.emit(self.process.errorString()) if not self.closing else None)
        self.owned = True
        self.process.start(str(node), [str(self.source / 'server.mjs'), str(port)])
        self.timer.start()

    def poll(self):
        if self.closing:
            return
        self.attempts += 1
        if self.attempts > 150:
            self.timer.stop()
            self.failed.emit(tr('后台服务未能启动，请查看数据目录中的 logs/qt-server.log。'))
            return
        request = QNetworkRequest(QUrl(self.url + '/api/desktop/session'))
        request.setTransferTimeout(1000)
        reply = self.probe.get(request)

        def finish():
            if self.closing:
                reply.deleteLater()
                return
            try:
                value = json.loads(bytes(reply.readAll()))
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    raise ValueError()
            except (ValueError, UnicodeError):
                if not self.owned:
                    self.failed.emit(tr('无法连接指定的本地服务。'))
            else:
                if self.timer.isActive() or not self.owned:
                    self.timer.stop()
                    self.token = value.get('token', self.token)
                    self.ready.emit(self.url, self.token)
            finally:
                reply.deleteLater()
        reply.finished.connect(finish)

    def stop(self):
        if self.closing:
            return
        self.closing = True
        self.timer.stop()
        if not self.process or self.process.state() == QProcess.ProcessState.NotRunning:
            self.finish_stop()
            return
        request = QNetworkRequest(QUrl(self.url + '/api/desktop/shutdown'))
        request.setRawHeader(b'X-BoothNest-Token', self.token.encode())
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        request.setTransferTimeout(22000)
        reply = self.probe.post(request, QByteArray(b'{}'))
        reply.finished.connect(reply.deleteLater)
        QTimer.singleShot(25000, self.force_stop)

    def force_stop(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def exited(self, code, status):
        self.timer.stop()
        if not self.closing:
            self.failed.emit(tr('后台服务已退出（{0}），请查看 logs/qt-server.log。', code))
        else:
            self.finish_stop()

    def finish_stop(self):
        if self.lock:
            self.lock.release()
        self.stopped.emit()

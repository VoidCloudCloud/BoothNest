# SPDX-License-Identifier: GPL-3.0-only
from .presentation import tr, render, appearance, resolve, form_row, add_tab, checkbox, groupbox
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLineEdit,
                               QMessageBox, QPlainTextEdit, QProgressBar, QSpinBox,
                               QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)
from .core import bytes_label, price_label
from .widgets import ImageBox, button, combo, label, table


def open_booth(url):
    parsed = urlsplit(url)
    if parsed.scheme == 'https' and not parsed.username and not parsed.password and (parsed.hostname == 'booth.pm' or (parsed.hostname or '').endswith('.booth.pm')):
        return QDesktopServices.openUrl(QUrl(url))
    return False


class Panel(QDialog):
    def __init__(self, window, title, width=940, height=680):
        super().__init__(window)
        self.window, self.api = window, window.api
        render(self, 'setWindowTitle', title + ' — BoothNest')
        self.resize(width, height)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(22, 20, 22, 18)
        self.layout.setSpacing(12)
        self.layout.addWidget(label(title, 'Title'))
        self.feedback = label('', 'Error')
        self.feedback.hide()
        self.layout.addWidget(self.feedback)
        self.timer = QTimer(self)
        self.finished.connect(self.timer.stop)

    def error(self, text):
        render(self.feedback, 'setText', text)
        self.feedback.show()

    def request(self, path, done=None, *, body=None, raw=False):
        self.feedback.hide()
        return self.api.request(path, done, body=body, raw=raw, error=self.error)

    def post(self, path, body=None, done=None):
        # A mutation runs once; a double-click cannot launch two scans or writes.
        if getattr(self, '_posting', False):
            return
        self._posting = True

        def finish(value):
            self._posting = False
            if done:
                done(value)

        def fail(message):
            self._posting = False
            self.error(message)
        self.api.request(path, finish, body={} if body is None else body, error=fail)

    def save_download(self, endpoint, name):
        target, _ = QFileDialog.getSaveFileName(self, tr('导出文件'), name)
        if not target:
            return

        def save(data):
            try:
                Path(target).write_bytes(data)
            except OSError as exc:
                self.error(str(exc))
            else:
                self.window.statusBar().showMessage(tr('已导出到 ') + target, 8000)
        self.request(endpoint, save, raw=True)


class Detail(Panel):
    def __init__(self, window, item):
        super().__init__(window, tr('商品详情'), 1120, 810)
        self.item, self.image_index = item, 0
        self.title = label(appearance.item_text(item), 'Title')
        self.layout.addWidget(self.title)
        self.price = label('', 'Subtle')
        self.layout.addWidget(self.price)
        splitter = QSplitter()
        left = QWidget()
        image_layout = QVBoxLayout(left)
        image_layout.setContentsMargins(0, 0, 10, 0)
        self.image = ImageBox(window.images)
        image_layout.addWidget(self.image, 1)
        row = QHBoxLayout()
        row.addWidget(button(tr('‹ 上一张'), lambda: self.change_image(-1)))
        self.image_count = label('')
        row.addWidget(self.image_count, 1, Qt.AlignmentFlag.AlignCenter)
        row.addWidget(button(tr('下一张 ›'), lambda: self.change_image(1)))
        image_layout.addLayout(row)
        splitter.addWidget(left)
        tabs = QTabWidget()
        self.description = QTextBrowser()
        self.description.setOpenExternalLinks(False)
        self.description.anchorClicked.connect(lambda url: open_booth(url.toString()))
        add_tab(tabs, self.description, tr('商品说明'))
        self.variation_table, self.variation_model = table([(tr('规格'), 'name'), (tr('参考价 {0}',appearance.currency), lambda row: appearance.money(row.get('price')))])
        add_tab(tabs, self.variation_table, tr('规格'))
        self.local_table, self.local_model = table([(tr('本地相对路径'), lambda row: row.get('folder', row.get('name', ''))), (tr('大小'), lambda row: bytes_label(row.get('bytes', row.get('size'))))])
        add_tab(tabs, self.local_table, tr('本地文件'))
        splitter.addWidget(tabs)
        splitter.setSizes([460, 600])
        self.layout.addWidget(splitter, 1)
        self.meta = label('', 'Subtle')
        self.layout.addWidget(self.meta)
        actions = QHBoxLayout()
        self.favourite = button('', lambda: window.toggle_favourite(item['id']))
        actions.addWidget(self.favourite)
        actions.addWidget(button(tr('打开 BOOTH'), lambda: open_booth(item.get('url', f"https://booth.pm/ja/items/{item['id']}")), True))
        self.reveal_button = button(tr('定位本地文件'), self.reveal)
        actions.addWidget(self.reveal_button)
        actions.addStretch()
        actions.addWidget(button(tr('关闭'), self.accept))
        self.layout.addLayout(actions)
        window.preferencesChanged.connect(self.update_favourite)
        appearance.changed.connect(self.refresh_presentation)
        self.fill(item)
        self.request(f"/api/items/{item['id']}", self.fill)

    def fill(self, item):
        self.item = item
        self.variation_model.replace(item.get('variations', []))
        self.local_model.replace(item.get('local', {}).get('entries', []))
        self.local_table.setColumnWidth(0, 360)
        self.reveal_button.setEnabled(bool(item.get('local', {}).get('copies')))
        self.refresh_presentation()
        self.change_image(0)
        self.update_favourite()

    def refresh_presentation(self):
        item = self.item
        render(self.title, 'setText', appearance.item_text(item))
        render(self.price, 'setText', f"{item.get('author', '')}  ·  {price_label(item)}  ·  BOOTH ♥ {item.get('likes', 0):,}")
        self.price.setToolTip(resolve(tr('固定参考汇率：1 JPY ≈ 0.048 CNY / 0.0067 USD。实际结算以 BOOTH 日元价格为准；价格筛选始终使用 JPY。')))
        scroll = self.description.verticalScrollBar().value()
        render(self.description, 'setPlainText', appearance.item_text(item,'bio') or tr('暂无商品说明。'))
        self.description.verticalScrollBar().setValue(scroll)
        self.variation_model.columns[1] = (tr('参考价 {0}',appearance.currency),lambda row: appearance.money(row.get('price')))
        self.variation_model.refresh()
        avatars = '、'.join(appearance.facet(value) for value in item.get('avatars', []))
        render(self.meta, 'setText', (tr('适配：') + avatars if avatars else tr('未注明适配模型')) + tr('\n标签：') + ' · '.join(item.get('tags', [])[:30]))
        self.image.update()

    def update_favourite(self):
        render(self.favourite, 'setText', tr('♥ 已收藏') if self.item['id'] in self.window.favourites() else tr('♡ 收藏'))

    def change_image(self, step):
        media = self.item.get('media', [])
        self.image_index = (self.image_index + step) % max(1, len(media))
        self.image.candidates = [media[self.image_index]] + media[self.image_index + 1:] if media else []
        render(self.image_count, 'setText', f'{self.image_index + 1} / {len(media)}' if media else tr('无预览图'))
        self.image.update()

    def reveal(self):
        selected = self.local_table.selectionModel().selectedRows()
        folder = self.local_model.rows[selected[0].row()].get('folder') if selected else None
        self.post('/api/local/reveal', {'id': self.item['id'], 'folder': folder})


class Scan(Panel):
    def __init__(self, window):
        super().__init__(window, tr('扫描下载目录'), 850, 700)
        self.layout.addWidget(label(tr('选择下载文件夹，建立或更新本地库存。扫描进度与日志会自动刷新。'), 'Subtle'))
        form = QFormLayout()
        self.root = QLineEdit()
        root_row = QHBoxLayout()
        root_row.addWidget(self.root, 1)
        root_row.addWidget(button(tr('选择目录…'), self.pick))
        form_row(form, tr('下载目录'), root_row)
        self.offline = checkbox(tr('仅使用本地缓存'))
        form_row(form, tr('离线模式'), self.offline)
        self.full = checkbox(tr('忽略探测缓存，重新检查全部条目'))
        form_row(form, tr('全量重扫'), self.full)
        self.enabled = checkbox(tr('在程序运行时自动增量扫描'))
        form_row(form, tr('自动扫描'), self.enabled)
        self.interval = QSpinBox()
        self.interval.setRange(5, 1440)
        render(self.interval, 'setSuffix', tr(' 分钟'))
        form_row(form, tr('扫描间隔'), self.interval)
        self.layout.addLayout(form)
        row = QHBoxLayout()
        self.start_button = button(tr('立即扫描'), self.start_scan, True)
        self.save_button = button(tr('保存设置'), self.save)
        self.cancel_button = button(tr('取消扫描'), lambda: self.post('/api/scan/cancel', done=self.fill))
        for item in (self.start_button, self.save_button, self.cancel_button):
            row.addWidget(item)
        row.addStretch()
        self.layout.addLayout(row)
        self.progress = QProgressBar()
        self.layout.addWidget(self.progress)
        self.status = label(tr('正在读取扫描状态…'), 'Subtle')
        self.layout.addWidget(self.status)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(200)
        self.layout.addWidget(self.logs, 1)
        self.initial = True
        self.last_finished = None
        self.polling = False
        self.timer.setInterval(1600)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.poll()

    def pick(self):
        path = QFileDialog.getExistingDirectory(self, tr('选择素材下载目录'), self.root.text())
        if path:
            render(self.root, 'setText', path)

    def poll(self):
        if self.polling:
            return
        self.polling = True
        def failed(text):
            self.polling = False
            self.error(text)
        self.api.request('/api/scan/status', self.fill, error=failed)

    def fill(self, value):
        self.polling = False
        task = value.get('task', {})
        if self.initial:
            render(self.root, 'setText', value.get('state', {}).get('root') or value.get('state', {}).get('dataset_root', ''))
            self.offline.setChecked(value.get('state', {}).get('offline', False))
            self.enabled.setChecked(value.get('config', {}).get('enabled', False))
            self.interval.setValue(value.get('config', {}).get('intervalMinutes', 30))
            self.initial = False
        busy = task.get('busy', False)
        for widget in (self.root, self.offline, self.full, self.enabled, self.interval, self.start_button, self.save_button):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        total, done = task.get('total', 0), task.get('done', 0)
        self.progress.setRange(0, total if total else (0 if busy else 1))
        self.progress.setValue(done if total else (0 if busy else 1))
        result = task.get('result') or {}
        render(self.status, 'setText', f"{task.get('phase', tr('等待扫描'))}  {done}/{total or '—'}" if busy else result.get('error') or (tr('扫描完成') if task.get('finished') else tr('等待扫描')))
        lines = '\n'.join(task.get('logs', [])[-150:])
        if self.logs.toPlainText() != lines:
            render(self.logs, 'setPlainText', lines)
            self.logs.verticalScrollBar().setValue(self.logs.verticalScrollBar().maximum())
        if task.get('finished') and self.last_finished != task.get('task_id'):
            self.last_finished = task.get('task_id')
            self.window.load()
        if value.get('error'):
            self.error(value['error'])

    def settings(self):
        return {'root': self.root.text().strip(), 'offline': self.offline.isChecked(),
                'enabled': self.enabled.isChecked(), 'intervalMinutes': self.interval.value()}

    def save(self):
        self.post('/api/scan/config', self.settings(), self.fill)

    def start_scan(self):
        value = self.settings()
        value.pop('enabled')
        value.pop('intervalMinutes')
        value['full'] = self.full.isChecked()
        self.post('/api/scan/start', value, self.fill)


class LocalManager(Panel):
    def __init__(self, window):
        super().__init__(window, tr('本地库存管理'), 1190, 790)
        self.page, self.pages, self.context = 1, 1, ''
        self.generation = 0
        row = QHBoxLayout()
        self.search = QLineEdit()
        render(self.search, 'setPlaceholderText', tr('搜索文件路径、商品名或 ID'))
        self.search.setClearButtonEnabled(True)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(self.reset_page)
        self.search.textChanged.connect(lambda: self.debounce.start())
        self.status_filter = combo([(tr('全部条目'), 'all'), (tr('已识别'), 'matched'), (tr('未识别'), 'unidentified'), (tr('已忽略'), 'ignored'), (tr('手动修正'), 'manual'), (tr('同商品多份'), 'multiple')], self.reset_page)
        self.sort = combo([(tr('体积从大到小'), 'bytes'), (tr('名称'), 'name'), (tr('最近修改'), 'mtime')], self.reset_page)
        row.addWidget(self.search, 1)
        row.addWidget(self.status_filter)
        row.addWidget(self.sort)
        row.addWidget(button(tr('刷新'), self.load))
        self.layout.addLayout(row)
        self.summary = label(tr('正在读取库存…'), 'Subtle')
        self.layout.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.table, self.model = table([(tr('相对路径'), 'folder'), (tr('商品 ID'), 'id'), (tr('商品名称'), 'title'), (tr('大小'), lambda r: bytes_label(r.get('bytes'))), (tr('状态'), lambda r: {'matched':tr('已识别'),'unidentified':tr('未识别'),'ignored':tr('已忽略')}.get(r.get('status'), '')), (tr('识别方式'), 'how')])
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(2, 300)
        self.table.doubleClicked.connect(self.open_selected)
        add_tab(self.tabs, self.table, tr('库存条目'))
        self.stats_table, self.stats_model = table([(tr('分组'), 'dimension'), (tr('名称'), 'label'), (tr('条目数'), 'entries'), (tr('商品数'), 'products'), (tr('逻辑大小'), lambda r: bytes_label(r.get('bytes')))])
        self.stats_table.setColumnWidth(0, 90)
        self.stats_table.setColumnWidth(1, 400)
        add_tab(self.tabs, self.stats_table, tr('分类与统计'))
        self.check_table, self.check_model = table([('SHA-256', 'hash'), (tr('大小'), lambda r: bytes_label(r.get('bytes'))), (tr('重复路径'), 'folder')])
        self.check_table.setColumnWidth(0, 370)
        self.check_table.setColumnWidth(1, 95)
        add_tab(self.tabs, self.check_table, tr('重复文件核对'))
        self.layout.addWidget(self.tabs, 1)
        paging = QHBoxLayout()
        self.previous = button(tr('上一页'), lambda: self.turn(-1))
        self.next = button(tr('下一页'), lambda: self.turn(1))
        self.page_label = label('')
        paging.addWidget(self.previous)
        paging.addWidget(self.page_label)
        paging.addWidget(self.next)
        paging.addStretch()
        paging.addWidget(button(tr('导出筛选 CSV'), lambda: self.save_download('/api/local/export.csv?' + self.query(), tr('本地库存.csv'))))
        self.layout.addLayout(paging)
        actions = QHBoxLayout()
        actions.addWidget(button(tr('定位所选文件'), self.reveal))
        actions.addWidget(button(tr('绑定商品…'), lambda: self.override('bind')))
        actions.addWidget(button(tr('取消商品归属'), lambda: self.override('unmatch')))
        actions.addWidget(button(tr('忽略所选'), lambda: self.override('ignore')))
        actions.addWidget(button(tr('恢复自动识别'), lambda: self.override('reset')))
        actions.addStretch()
        self.layout.addLayout(actions)
        checks = QHBoxLayout()
        self.check_status = label(tr('按文件内容核对重复；只读取原文件。'), 'Subtle')
        checks.addWidget(self.check_status, 1)
        checks.addWidget(button(tr('开始 SHA-256 核对'), self.start_check))
        checks.addWidget(button(tr('取消核对'), lambda: self.post('/api/local/check/stop')))
        checks.addWidget(button(tr('导出核对'), lambda: self.save_download('/api/local/check.csv', tr('重复文件核对.csv'))))
        self.layout.addLayout(checks)
        self.check_table.doubleClicked.connect(self.reveal_checked)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.poll_check)
        self.timer.start()
        self.load()
        self.request('/api/local/stats', self.fill_stats)
        self.poll_check()

    def query(self):
        return urlencode({'q': self.search.text(), 'status': self.status_filter.currentData(), 'sort': self.sort.currentData(), 'page': self.page, 'pageSize': 50})

    def reset_page(self):
        self.page = 1
        self.load()

    def load(self):
        self.generation += 1
        generation = self.generation
        self.request('/api/local/manage?' + self.query(), lambda value: self.fill(value) if generation == self.generation else None)

    def fill(self, value):
        self.context, self.page, self.pages = value['context'], value['page'], value['pages']
        self.model.replace(value['rows'])
        counts = value['counts']
        render(self.summary, 'setText', tr('共 {0:,} 条库存 · 已识别 {1:,} · 未识别 {2:,} · 当前筛选 {3:,}', counts['all'], counts['matched'], counts['unidentified'], value['count']))
        render(self.page_label, 'setText', f'{self.page} / {self.pages}')
        self.previous.setEnabled(self.page > 1)
        self.next.setEnabled(self.page < self.pages)

    def fill_stats(self, value):
        rows = []
        for key, name in [('categories',tr('分类')), ('shops',tr('商店')), ('types',tr('文件类型')), ('avatars',tr('模型')), ('years',tr('年份'))]:
            rows.extend(dict(row, dimension=name) for row in value.get(key, []))
        self.stats_model.replace(rows)

    def turn(self, delta):
        self.page = max(1, min(self.pages, self.page + delta))
        self.load()

    def selected(self):
        return [self.model.rows[index.row()] for index in self.table.selectionModel().selectedRows()]

    def open_selected(self):
        rows = self.selected()
        if rows and rows[0].get('id'):
            self.window.open_id(rows[0]['id'])

    def reveal(self):
        rows = self.selected()
        if rows:
            self.post('/api/local/entry-reveal', {'context': self.context, 'folder': rows[0]['folder']})

    def override(self, action):
        rows = self.selected()
        if not rows:
            self.error(tr('请先选择需要修正的库存条目。'))
            return
        product_id = ''
        if action == 'bind':
            product_id, accepted = QInputDialog.getText(self, tr('绑定商品'), tr('为 {0} 个条目指定 BOOTH 商品 ID 或链接', len(rows)))
            if not accepted or not product_id.strip():
                return
        def changed(value):
            self.load()
            self.window.load()
            self.request('/api/local/stats', self.fill_stats)
        self.post('/api/local/override', {'context': self.context, 'folders': [row['folder'] for row in rows], 'action': action, 'id': product_id.strip()}, changed)

    def start_check(self):
        self.post('/api/local/check/start', {'context': self.context}, lambda _: self.tabs.setCurrentIndex(2))

    def reveal_checked(self, index):
        row = self.check_model.rows[index.row()]
        self.post('/api/local/check/reveal', {'context': self.context, 'folder': row['folder']})

    def poll_check(self):
        if getattr(self, '_check_pending', False):
            return
        self._check_pending = True
        def fill(value):
            self._check_pending = False
            render(self.check_status, 'setText', f"{value.get('phase', tr('等待核对'))}  {value.get('done', 0)}/{value.get('total', 0)}  {value.get('error', '')}")
            result = value.get('result') or {}
            self.check_model.replace([dict(group, folder=folder) for group in result.get('groups', []) for folder in group.get('files', [])])
        def fail(text):
            self._check_pending = False
            self.error(text)
        self.api.request('/api/local/check', fill, error=fail)


class Data(Panel):
    def __init__(self, window):
        super().__init__(window, tr('数据与同步'), 980, 760)
        tabs = QTabWidget()
        self.layout.addWidget(tabs, 1)
        library, layout = self.tab(tabs, tr('数据管理'))
        layout.addWidget(label(tr('库存、收藏与已购记录由现有 BoothNest 数据目录统一保存。'), 'Subtle'))
        self.library_status = label(tr('正在读取…'))
        layout.addWidget(self.library_status)
        row = QHBoxLayout()
        row.addWidget(button(tr('连接已有库存…'), self.connect_library))
        row.addWidget(button(tr('重新读取库存'), lambda: self.post('/api/local/reload', done=lambda _: window.load())))
        row.addWidget(button(tr('打开数据目录'), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(window.backend.home)))))
        layout.addLayout(row)
        imports = groupbox(tr('导入与导出'))
        imports_layout = QHBoxLayout(imports)
        imports_layout.addWidget(button(tr('导入商品 JSON…'), lambda: self.import_json('/api/import')))
        imports_layout.addWidget(button(tr('导出商品目录'), lambda: self.save_download('/api/export', tr('BoothNest商品目录.json'))))
        imports_layout.addWidget(button(tr('导入已购 JSON…'), lambda: self.import_json('/api/purchases/import')))
        imports_layout.addWidget(button(tr('导出已购记录'), lambda: self.save_download('/api/purchases/export', tr('BoothNest已购记录.json'))))
        layout.addWidget(imports)
        add = QHBoxLayout()
        self.item_url = QLineEdit()
        render(self.item_url, 'setPlaceholderText', tr('BOOTH 商品链接或 ID'))
        add.addWidget(self.item_url, 1)
        add.addWidget(button(tr('联网收录此商品'), lambda: self.post('/api/booth', {'url': self.item_url.text()}, lambda _: window.load()), True))
        layout.addLayout(add)
        self.search_booth = QLineEdit()
        render(self.search_booth, 'setPlaceholderText', tr('关键词，例如 MAYO 衣装'))
        search = QHBoxLayout()
        search.addWidget(self.search_booth, 1)
        search.addWidget(button(tr('搜索并收录公开商品'), lambda: self.post('/api/booth-search', {'q': self.search_booth.text(), 'limit': 6}, lambda _: window.load())))
        layout.addLayout(search)
        layout.addStretch()
        sync_tab, sync_layout = self.tab(tabs, tr('公开目录同步'))
        self.sync_status = label(tr('正在读取…'), 'Subtle')
        sync_layout.addWidget(self.sync_status)
        form = QFormLayout()
        self.sync_queries = QLineEdit()
        form_row(form, tr('关键词（逗号分隔）'), self.sync_queries)
        self.sync_enabled = checkbox(tr('运行时自动同步公开商品'))
        form_row(form, tr('自动同步'), self.sync_enabled)
        self.sync_interval = QSpinBox(); self.sync_interval.setRange(15,1440); render(self.sync_interval, 'setSuffix', tr(' 分钟'))
        self.sync_batch = QSpinBox(); self.sync_batch.setRange(1,60)
        self.sync_refresh = QSpinBox(); self.sync_refresh.setRange(1,720); render(self.sync_refresh, 'setSuffix', tr(' 小时'))
        form_row(form, tr('批次间隔'), self.sync_interval)
        form_row(form, tr('每批商品数'), self.sync_batch)
        form_row(form, tr('过期刷新'), self.sync_refresh)
        sync_layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(button(tr('保存同步设置'), self.save_sync))
        row.addWidget(button(tr('立即同步一批'), lambda: self.post('/api/sync/run', done=lambda _: self.poll()), True))
        row.addWidget(button(tr('停止同步'), lambda: self.post('/api/sync/stop', done=lambda _: self.poll())))
        row.addStretch(); sync_layout.addLayout(row)
        sync_layout.addWidget(label(tr('公开同步按关键词逐批收录商品信息，进度可续跑；不会下载素材包。'), 'Subtle'))
        sync_layout.addStretch()
        purchase_tab, purchase_layout = self.tab(tabs, tr('已购自动同步'))
        purchase_layout.addWidget(label(tr('在已登录 BOOTH 的普通浏览器中安装配对扩展，使用已有登录状态同步已购清单。'), 'Subtle'))
        self.purchase_status = label(tr('正在读取…'))
        purchase_layout.addWidget(self.purchase_status)
        self.pairing = QLineEdit(); self.pairing.setReadOnly(True)
        render(self.pairing, 'setPlaceholderText', tr('生成配对信息后显示在这里'))
        purchase_layout.addWidget(self.pairing)
        row = QHBoxLayout()
        row.addWidget(button(tr('下载浏览器扩展'), lambda: self.save_download('/api/purchases/bridge/extension.zip', 'BoothNest-PurchaseSync.zip')))
        row.addWidget(button(tr('生成配对信息'), lambda: self.post('/api/purchases/bridge/pairing-code', done=self.pair)))
        row.addWidget(button(tr('复制配对信息'), lambda: render(QApplication.clipboard(), 'setText', self.pairing.text())))
        purchase_layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button(tr('请求立即同步'), lambda: self.post('/api/purchases/bridge/request', done=lambda _: self.poll())))
        self.purchase_toggle = button(tr('暂停自动同步'), self.toggle_purchase)
        row.addWidget(self.purchase_toggle)
        row.addWidget(button(tr('解除配对'), self.disconnect_purchase))
        row.addStretch(); purchase_layout.addLayout(row)
        purchase_layout.addWidget(button(tr('打开 BOOTH 下载库'), lambda: open_booth('https://accounts.booth.pm/library')))
        purchase_layout.addStretch()
        maintenance_tab, maintenance_layout = self.tab(tabs, tr('缓存与导出'))
        self.cache_status = label(tr('按需统计缩略图与引擎缓存。'), 'Subtle')
        maintenance_layout.addWidget(self.cache_status)
        maintenance_layout.addWidget(button(tr('查看缩略图统计'), lambda: self.post('/api/thumb_stats', {'args': []}, self.cache_info)))
        maintenance_layout.addWidget(button(tr('清理识别缓存…'), self.clear_cache))
        maintenance_layout.addWidget(button(tr('导出全部库存与统计 CSV'), lambda: self.post('/api/export_excel', {'args': []}, self.exported)))
        maintenance_layout.addStretch()
        self.first_sync = True
        self.bridge = {}
        self.request('/api/status', self.fill_status)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.poll()

    @staticmethod
    def tab(tabs, name):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(15)
        add_tab(tabs, widget, name)
        return widget, layout

    def fill_status(self, value):
        library = value.get('library', {})
        render(self.library_status, 'setText', tr('商品目录 {0:,} 件 · 已购 {1:,} 件\n', value.get('items', 0), value.get('purchases', {}).get('products', 0)) + (library.get('path') or library.get('home') or str(self.window.backend.home)))

    def connect_library(self):
        path = QFileDialog.getExistingDirectory(self, tr('选择包含 data/dataset.json 的 BoothNest 库存目录'))
        if path:
            self.post('/api/local/connect', {'path': path}, lambda _: self.window.load())

    def import_json(self, endpoint):
        path, _ = QFileDialog.getOpenFileName(self, tr('导入 JSON'), '', 'JSON (*.json)')
        if not path:
            return
        try:
            if Path(path).stat().st_size > 100_000_000:
                raise ValueError(tr('导入文件超过 100 MB。'))
            data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as exc:
            self.error(str(exc))
            return
        self.post(endpoint, data, lambda _: self.window.load())

    def poll(self):
        self.request('/api/sync/status', self.fill_sync)
        self.request('/api/purchases/bridge/status', self.fill_bridge)

    def fill_sync(self, value):
        config = value.get('config', {})
        if self.first_sync:
            render(self.sync_queries, 'setText', ', '.join(config.get('queries', ['VRChat'])))
            self.sync_enabled.setChecked(config.get('enabled', False))
            self.sync_interval.setValue(config.get('intervalMinutes', 60))
            self.sync_batch.setValue(config.get('batchSize', 24))
            self.sync_refresh.setValue(config.get('refreshHours', 24))
            self.first_sync = False
        progress = value.get('progress', {}) or {}
        render(self.sync_status, 'setText', tr('{0} · 队列 {1:,} 件 · {2}\n{3}', tr('正在同步') if value.get('running') else tr('等待同步'), value.get('pending', 0), value.get('phase', ''), value.get('error') or value.get('pausedReason') or ''))

    def save_sync(self):
        self.post('/api/sync/config', {'queries': self.sync_queries.text(), 'enabled': self.sync_enabled.isChecked(), 'intervalMinutes': self.sync_interval.value(), 'batchSize': self.sync_batch.value(), 'refreshHours': self.sync_refresh.value()}, self.fill_sync)

    def fill_bridge(self, value):
        self.bridge = value
        render(self.purchase_status, 'setText', (tr('已配对浏览器扩展') if value.get('paired') else tr('尚未配对浏览器扩展')) + (tr(' · 自动同步已开启') if value.get('enabled') else tr(' · 自动同步已暂停')) + '\n' + (value.get('error') or ''))
        render(self.purchase_toggle, 'setText', tr('暂停自动同步') if value.get('enabled') else tr('恢复自动同步'))

    def pair(self, value):
        render(self.pairing, 'setText', self.api.base + '/#boothnest-pair=' + value['code'])
        self.pairing.selectAll()

    def toggle_purchase(self):
        self.post('/api/purchases/bridge/config', {'enabled': not self.bridge.get('enabled')}, self.fill_bridge)

    def disconnect_purchase(self):
        if QMessageBox.question(self, tr('解除配对'), tr('解除与浏览器扩展的配对？已购记录会保留。')) == QMessageBox.StandardButton.Yes:
            self.post('/api/purchases/bridge/disconnect', done=self.fill_bridge)

    def cache_info(self, value):
        render(self.cache_status, 'setText', '  ·  '.join(f'{key}: {val}' for key, val in value.items() if key != 'ok' and isinstance(val, (str, int, float))))

    def clear_cache(self):
        if QMessageBox.question(self, tr('清理识别缓存'), tr('清理商品、搜索与查证缓存？下次联网识别会重新获取资料。')) == QMessageBox.StandardButton.Yes:
            self.post('/api/clear_cache', {'args': []}, lambda _: render(self.cache_status, 'setText', tr('识别缓存已清理。')))

    def exported(self, value):
        render(self.cache_status, 'setText', tr('已导出：') + value.get('dir', ''))

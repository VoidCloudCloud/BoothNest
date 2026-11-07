# SPDX-License-Identifier: GPL-3.0-only
from .presentation import tr, render, appearance, resolve, form_row, checkbox
from copy import deepcopy
import json
from pathlib import Path
import time
from urllib.parse import parse_qs
import uuid

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QIcon, QKeySequence, QPainter, QPixmap, QColor
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QFrame, QHBoxLayout,
                               QInputDialog, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QScrollArea, QSpinBox, QSplitter,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget, QHeaderView)
from .core import Api, Images, query_string, saved_query, bytes_label, price_label
from .dialogs import Data, Detail, LocalManager, Scan
from .widgets import CardDelegate, CardView, ItemModel, button, combo, label, table


DEFAULT = {'view': 'items', 'q': '', 'sort': 'trending', 'adult': 'safe', 'page': 1, 'pageSize': 40}
VIEWS = [(tr('素材探索'), 'items'), (tr('本地素材'), 'local'), (tr('已购清单'), 'purchased'), (tr('角色模型'), 'avatars'), (tr('我的收藏'), 'favourites'), (tr('最近浏览'), 'recent')]
SORTS = [(tr('热门精选'), 'trending'), (tr('最新发布'), 'newest'), (tr('最早发布'), 'oldest'), (tr('最多喜欢'), 'likes'), (tr('价格从低到高'), 'price-asc'), (tr('价格从高到低'), 'price-desc'), (tr('商品名称'), 'title'), (tr('本地体积'), 'local-size'), (tr('本地最近修改'), 'local-newest'), (tr('本地副本数'), 'local-copies')]


class Window(QMainWindow):
    loaded = Signal(dict)
    preferencesChanged = Signal()

    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.api = Api(self)
        self.images = Images(self.api, self)
        self.state = dict(DEFAULT)
        self.preferences = {}
        self.appearance_overrides = {}
        self.data = {}
        self.all_facets = {}
        self.dialogs = []
        self.preference_queue = []
        self.preference_busy = False
        self.generation = 0
        self.connected = False
        self.preferences_ready = False
        self.shutting_down = False
        self.ready_to_close = False
        self.building = False
        render(self, 'setWindowTitle', tr('BoothNest — 素材库'))
        self.resize(1480, 950)
        self.setMinimumSize(980, 650)
        icon = QPixmap(64,64); icon.fill(QColor('#252330'))
        painter = QPainter(icon); painter.setPen(QColor('#f3a1ad')); painter.setFont(QFont('Segoe UI', 25, QFont.Weight.Bold)); painter.drawText(icon.rect(), Qt.AlignmentFlag.AlignCenter, 'B'); painter.end()
        self.setWindowIcon(QIcon(icon))
        self.setCentralWidget(self.build())
        appearance.changed.connect(self.refresh_presentation)
        self.api.failed.connect(self.error)
        self.images.changed.connect(self.cards.viewport().update)
        self.backend.ready.connect(self.connect_api)
        self.backend.failed.connect(self.error)
        self.backend.stopped.connect(self.closed_backend)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(self.search_changed)
        self.search.textChanged.connect(lambda: self.debounce.start())
        self.search.returnPressed.connect(self.search_changed)
        self.facet_search.textChanged.connect(self.build_facets)
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(10000)
        self.heartbeat.timeout.connect(lambda: self.api.request('/api/desktop/heartbeat', body={}, error=lambda _: None))
        self.watcher = QTimer(self)
        self.watcher.setInterval(15000)
        self.watcher.timeout.connect(self.check_updates)
        self.last_status = None
        for shortcut, callback in [('Ctrl+F', self.search.setFocus), ('Ctrl+K', self.quick_find), ('F5', self.load), ('Ctrl+L', lambda: self.show_panel(LocalManager)), ('Ctrl+O', lambda: self.show_panel(Scan))]:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut)); action.triggered.connect(callback); self.addAction(action)
        render(self.statusBar(),'showMessage',tr('正在启动素材库…'))

    def build(self):
        root = QWidget()
        layout = QVBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        header = QFrame(); header.setObjectName('Topbar')
        header_layout = QHBoxLayout(header); header_layout.setContentsMargins(23,15,23,15); header_layout.setSpacing(14)
        brand = label('BoothNest', 'Brand'); header_layout.addWidget(brand)
        header_layout.addSpacing(15)
        self.search = QLineEdit(); self.search.setObjectName('Search'); self.search.setMinimumHeight(29); render(self.search, 'setPlaceholderText', tr('搜索素材、模型、作者或商品 ID    Ctrl+F')); self.search.setClearButtonEnabled(True)
        header_layout.addWidget(self.search, 1)
        self.quick_button = button(tr('快捷查找    Ctrl+K'), self.quick_find)
        header_layout.addWidget(self.quick_button)
        header_layout.addWidget(button(tr('扫描目录'), lambda: self.show_panel(Scan), True))
        header_layout.addWidget(button(tr('库存管理'), lambda: self.show_panel(LocalManager)))
        header_layout.addWidget(button(tr('数据与同步'), lambda: self.show_panel(Data)))
        layout.addWidget(header)
        settings = QHBoxLayout(); settings.setContentsMargins(23,5,23,5)
        settings.addStretch()
        self.language = combo([('简体中文','zh'),('English','en')], lambda: self.change_appearance('language', self.language.currentData()))
        self.currency = combo([(name,name) for name in ('JPY','CNY','USD')], lambda: self.change_appearance('currency', self.currency.currentData()))
        self.theme = combo([(tr('深色'),'charcoal'),(tr('浅色'),'cloud')], lambda: self.change_appearance('theme', self.theme.currentData()))
        for caption, widget in [(tr('语言'),self.language),(tr('参考币种'),self.currency),(tr('主题'),self.theme)]:
            settings.addSpacing(12)
            settings.addWidget(label(caption,'Subtle')); settings.addWidget(widget)
        self.currency.setToolTip(resolve(tr('固定参考汇率：1 JPY ≈ 0.048 CNY / 0.0067 USD。实际结算以 BOOTH 日元价格为准；价格筛选始终使用 JPY。')))
        layout.addLayout(settings)
        splitter = QSplitter()
        sidebar = QFrame(); sidebar.setObjectName('Sidebar'); sidebar.setMinimumWidth(235); sidebar.setMaximumWidth(350)
        side = QVBoxLayout(sidebar); side.setContentsMargins(15,16,15,14); side.setSpacing(5)
        self.nav = QButtonGroup(self); self.nav.setExclusive(True)
        self.nav_buttons = {}
        for name, value in VIEWS:
            item = button(name, lambda checked=False, v=value: self.select_view(v))
            item.setObjectName('Nav'); item.setCheckable(True); item.setChecked(value == 'items')
            self.nav.addButton(item); side.addWidget(item); self.nav_buttons[value] = item
        side.addSpacing(12)
        side.addWidget(label(tr('筛选素材'), 'Subtle'))
        self.facet_search = QLineEdit(); render(self.facet_search, 'setPlaceholderText', tr('查找分类、模型或标签')); self.facet_search.setClearButtonEnabled(True)
        side.addWidget(self.facet_search)
        self.facets = QTreeWidget(); self.facets.setColumnCount(2); self.facets.setHeaderHidden(True); self.facets.setColumnWidth(0,170); self.facets.setIndentation(13); self.facets.setAnimated(False)
        self.facets.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.facets.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.facets.header().setStretchLastSection(False)
        self.facets.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.facets.itemChanged.connect(self.facet_changed)
        side.addWidget(self.facets, 1)
        side.addWidget(button(tr('更多筛选…'), self.advanced))
        side.addWidget(button(tr('清除筛选条件'), self.reset))
        splitter.addWidget(sidebar)
        content = QWidget()
        body = QVBoxLayout(content); body.setContentsMargins(22,20,18,14); body.setSpacing(13)
        heading = QHBoxLayout()
        self.heading = label(tr('素材探索'), 'Title'); heading.addWidget(self.heading)
        heading.addStretch()
        self.sort = combo(SORTS, self.sort_changed)
        heading.addWidget(self.sort)
        self.display = combo([(tr('图库'), 'cards'), (tr('表格'), 'table')], lambda: self.stack.setCurrentIndex(self.display.currentIndex()))
        heading.addWidget(self.display)
        body.addLayout(heading)
        self.error_label = label('', 'Error'); self.error_label.hide(); body.addWidget(self.error_label)
        controls = QHBoxLayout()
        self.summary = label(tr('正在读取商品目录…'), 'Subtle'); controls.addWidget(self.summary, 1)
        controls.addWidget(button(tr('保存筛选'), self.save_filter))
        controls.addWidget(button(tr('分享筛选…'), self.share_filters))
        self.saved_button = button(tr('已保存 ▾'), self.show_saved); controls.addWidget(self.saved_button)
        controls.addWidget(button(tr('刷新'), self.load))
        body.addLayout(controls)
        self.filter_summary = label('', 'Subtle'); self.filter_summary.hide(); body.addWidget(self.filter_summary)
        self.stack = QStackedWidget()
        self.cards = CardView()
        self.item_model = ItemModel(self.cards); self.cards.setModel(self.item_model)
        self.cards.setItemDelegate(CardDelegate(self.images, self.favourites, self.cards))
        self.cards.clicked.connect(lambda index: self.open_item(index.data(Qt.ItemDataRole.UserRole)))
        self.cards.activated.connect(lambda index: self.open_item(index.data(Qt.ItemDataRole.UserRole)))
        self.cards.favouriteClicked.connect(self.toggle_favourite)
        self.stack.addWidget(self.cards)
        self.item_table, self.table_model = table([(tr('商品名称'), appearance.item_text), (tr('作者'), 'author'), (tr('价格 {0}', appearance.currency), price_label), (tr('本地副本'), lambda r: r.get('local', {}).get('copies', 0)), (tr('已购'), lambda r: tr('是') if r.get('purchase', {}).get('recorded') else ''), (tr('BOOTH 喜欢'), 'likes')])
        self.item_table.setColumnWidth(0, 380); self.item_table.setColumnWidth(1, 170)
        self.item_table.doubleClicked.connect(lambda index: self.open_item(self.table_model.rows[index.row()]))
        self.stack.addWidget(self.item_table)
        self.empty = label(tr('当前筛选没有匹配的商品。\n可以清除筛选条件，或扫描下载目录。'), 'Subtle'); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter); self.stack.addWidget(self.empty)
        body.addWidget(self.stack, 1)
        paging = QHBoxLayout()
        self.previous = button(tr('‹ 上一页'), lambda: self.turn(-1)); paging.addWidget(self.previous)
        self.page_spin = QSpinBox(); self.page_spin.setRange(1,1); render(self.page_spin, 'setPrefix', tr('第 ')); render(self.page_spin, 'setSuffix', tr(' 页')); self.page_spin.editingFinished.connect(self.go_to_page); paging.addWidget(self.page_spin)
        self.page_label = label('/ 1'); paging.addWidget(self.page_label)
        self.next = button(tr('下一页 ›'), lambda: self.turn(1)); paging.addWidget(self.next)
        paging.addStretch()
        paging.addWidget(label(tr('每页'), 'Subtle'))
        self.page_size = combo([(str(n), n) for n in (20,40,60,100)], self.size_changed); self.page_size.setCurrentIndex(1); paging.addWidget(self.page_size)
        body.addLayout(paging)
        splitter.addWidget(content); splitter.setSizes([265,1215]); splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        return root

    def connect_api(self, url, token):
        self.api.base, self.api.token = url, token
        self.connected = True
        self.heartbeat.start()
        self.watcher.start()
        self.api.request('/api/preferences', self.initial_preferences)

    def check_updates(self):
        def receive(status):
            stamp = (status.get('updatedAt'), status.get('items'), status.get('library', {}).get('loadedAt'))
            if self.last_status is not None and self.last_status != stamp:
                self.load()
            self.last_status = stamp
        self.api.request('/api/status', receive, error=lambda _: None)

    def initial_preferences(self, preferences):
        self.preferences = preferences
        self.preferences_ready = True
        appearance.apply(dict(preferences,**self.appearance_overrides))
        self.refresh_presentation()
        self.preferencesChanged.emit()
        for key,value in self.appearance_overrides.copy().items():
            self.save_appearance(key,value)
        self.load()

    def change_appearance(self, key, value):
        if self.building or value is None:
            return
        self.appearance_overrides[key] = value
        appearance.apply({key:value})
        if self.preferences_ready:
            self.save_appearance(key,value)

    def save_appearance(self, key, value):
        def failed(_):
            if self.appearance_overrides.get(key) == value:
                self.appearance_overrides.pop(key,None)
                defaults = {'language':'zh','currency':'JPY','theme':'charcoal'}
                appearance.apply({key:self.preferences.get(key,defaults[key])})
        self.queue_preference(lambda _: {key:value},failed)

    def refresh_presentation(self):
        for key in ('language','currency','theme'):
            widget = getattr(self, key)
            widget.blockSignals(True)
            widget.setCurrentIndex(max(0,widget.findData(getattr(appearance,key))))
            widget.blockSignals(False)
        render(self.heading, 'setText', next(title for title,value in VIEWS if value == self.state['view']))
        self.table_model.columns[2] = (tr('价格 {0}',appearance.currency), price_label)
        self.table_model.refresh()
        self.currency.setToolTip(resolve(tr('固定参考汇率：1 JPY ≈ 0.048 CNY / 0.0067 USD。实际结算以 BOOTH 日元价格为准；价格筛选始终使用 JPY。')))
        self.build_facets()
        self.render_filter_summary()
        self.cards.viewport().update()

    def quick_find(self):
        from .discovery import QuickFind
        if not self.connected:
            self.error(tr('请等待素材库启动完成。')); return
        for panel in self.dialogs:
            if isinstance(panel, QuickFind) and panel.isVisible():
                panel.close(); return
        self.show_panel(QuickFind)

    def select_group(self, group, value):
        key = {'avatars':'avatar','authors':'author','tags':'tag','query':'q'}[group]
        state = dict(DEFAULT, adult=self.state.get('adult','safe'))
        state[key] = value if key == 'q' else [value]
        self.apply_filter_state(state)

    def share_filters(self):
        from .discovery import ShareFilters
        self.show_panel(ShareFilters)

    def error(self, message):
        render(self.error_label, 'setText', message)
        self.error_label.show()
        render(self.statusBar(),'showMessage',tr('操作未完成'))

    def load(self):
        if not self.connected or self.shutting_down:
            return
        self.generation += 1
        generation = self.generation
        query = query_string(self.state, self.preferences)
        self.error_label.hide()
        render(self.summary, 'setText', tr('正在查找素材…'))
        started = time.perf_counter()
        def receive(value):
            if generation != self.generation or self.shutting_down:
                return
            self.data = value
            self.state['page'] = value['page']
            self.images.offline = value.get('library', {}).get('sourceOffline', False)
            self.item_model.replace(value['items']); self.table_model.replace(value['items'])
            self.stack.setCurrentIndex(self.display.currentIndex() if value['items'] else 2)
            render(self.summary, 'setText', tr('{0:,} 件匹配素材  /  目录 {1:,} 件', value['count'], value['totalRecords']))
            render(self.statusBar(),'showMessage',tr('目录已更新  ·  查询 {0} ms  ·  含界面更新 {1} ms', value.get('elapsedMs', 0), int((time.perf_counter() - started) * 1000)))
            self.previous.setEnabled(value['page'] > 1); self.next.setEnabled(value['page'] < value['totalPages'])
            self.page_spin.setMaximum(value['totalPages']); self.page_spin.setValue(value['page']); render(self.page_label, 'setText', f"/ {value['totalPages']}")
            self.build_facets()
            self.render_filter_summary()
            self.loaded.emit(value)
        self.api.request('/api/items?' + query, receive, error=lambda message: self.error(message) if generation == self.generation else None)

    def render_filter_summary(self):
        pieces = []
        for key, title in [('category',tr('分类')),('avatar',tr('模型')),('tag',tr('包含标签')),('excludeTag',tr('排除标签')),('author',tr('作者')),('feature',tr('功能')),('fileType',tr('文件类型')),('localCategory',tr('本地分类'))]:
            if self.state.get(key):
                pieces.append(title + '：' + '、'.join(self.state[key]))
        if self.state.get('free'): pieces.append(tr('仅免费'))
        if self.state.get('min') or self.state.get('max') is not None:
            pieces.append(tr('价格 ¥{0}–{1}', self.state.get('min', 0), self.state.get('max', tr('不限'))))
        if self.state.get('availability', 'all') != 'all': pieces.append(tr('库存：') + self.state['availability'])
        if self.state.get('purchase', 'all') != 'all': pieces.append(tr('已购条件：') + self.state['purchase'])
        if self.state.get('minBytes'): pieces.append(tr('本地 ≥ ') + bytes_label(self.state['minBytes']))
        if self.state.get('duplicates'): pieces.append(tr('同商品多份'))
        if self.state.get('includeMentions'): pieces.append(tr('包含未确认适配'))
        render(self.filter_summary, 'setText', '  ·  '.join(pieces))
        self.filter_summary.setVisible(bool(pieces))

    def build_facets(self):
        if not self.data:
            return
        self.building = True
        expanded = {self.facets.topLevelItem(i).data(0,Qt.ItemDataRole.UserRole) for i in range(self.facets.topLevelItemCount()) if self.facets.topLevelItem(i).isExpanded()}
        first = not self.all_facets
        scroll = self.facets.verticalScrollBar().value()
        self.facets.clear()
        search = self.facet_search.text().casefold().strip()
        definitions = [('categories','category',tr('素材分类'),'slug'),('avatars','avatar',tr('适配模型'),'slug'),('authors','author',tr('创作者'),'name'),('tags','tag',tr('标签（√ 包含 / − 排除）'),'name'),('features','feature',tr('功能支持'),'key'),('fileTypes','fileType',tr('本地文件类型'),'name'),('localCategories','localCategory',tr('本地分类'),'name')]
        for plural, key, title, identity in definitions:
            current = self.data.get('facets', {}).get(plural, [])
            known = self.all_facets.setdefault(plural, {})
            for entry in current:
                known[entry[identity]] = entry
            active = {entry[identity]: entry for entry in current}
            values = sorted(known.values(), key=lambda e: (e[identity] not in self.state.get(key, []), -(active.get(e[identity], {}).get('count', 0))))
            group = QTreeWidgetItem(self.facets, [title])
            group.setData(0,Qt.ItemDataRole.UserRole,key)
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            count = 0
            for entry in values:
                value = entry[identity]
                caption = appearance.facet(entry) or value
                selected = value in self.state.get(key, []) or key == 'tag' and value in self.state.get('excludeTag', [])
                aliases = ' '.join(str(entry.get(field) or '') for field in ('en','ja','ko','aliases'))
                if search and search not in (caption + ' ' + value + ' ' + aliases).casefold() and not selected:
                    continue
                number = active.get(value, {}).get('count', 0)
                if not number and not selected and key not in ('category', 'avatar'):
                    continue
                if count >= 70 and not selected:
                    continue
                node = QTreeWidgetItem(group, [caption, str(number)])
                node.setData(0, Qt.ItemDataRole.UserRole, (key, value))
                node.setToolTip(0, caption + '\n' + value)
                node.setFlags(node.flags() | Qt.ItemFlag.ItemIsUserCheckable | (Qt.ItemFlag.ItemIsUserTristate if key == 'tag' else Qt.ItemFlag.NoItemFlags))
                check = Qt.CheckState.PartiallyChecked if key == 'tag' and value in self.state.get('excludeTag', []) else Qt.CheckState.Checked if value in self.state.get(key, []) else Qt.CheckState.Unchecked
                node.setCheckState(0, check)
                count += 1
                for child in entry.get('children', []):
                    child_value = child['slug']
                    child_node = QTreeWidgetItem(node, [appearance.facet(child) or child_value, str(child.get('count', 0))])
                    child_node.setData(0, Qt.ItemDataRole.UserRole, (key, child_value))
                    child_node.setFlags(child_node.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    child_node.setCheckState(0, Qt.CheckState.Checked if child_value in self.state.get(key, []) else Qt.CheckState.Unchecked)
                    if child_value in self.state.get(key, []): node.setExpanded(True)
            group.setExpanded(bool(search) or key in expanded or first and key in ('category','avatar'))
        self.facets.verticalScrollBar().setValue(scroll)
        self.building = False

    def facet_changed(self, node, column):
        if self.building:
            return
        payload = node.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        key, value = payload
        self.state[key] = [v for v in self.state.get(key, []) if v != value]
        if key == 'tag': self.state['excludeTag'] = [v for v in self.state.get('excludeTag', []) if v != value]
        checked = node.checkState(0)
        if checked == Qt.CheckState.Checked:
            self.state[key].append(value)
        elif checked == Qt.CheckState.PartiallyChecked and key == 'tag':
            self.state['excludeTag'].append(value)
        self.state['page'] = 1
        self.load()

    def select_view(self, view):
        self.state['view'] = view; self.state['page'] = 1
        self.nav_buttons[view].setChecked(True)
        render(self.heading, 'setText', dict((value, title) for title,value in VIEWS)[view])
        self.load()

    def search_changed(self):
        self.debounce.stop()
        self.state['q'] = self.search.text().strip(); self.state['page'] = 1
        self.load()

    def sort_changed(self):
        if hasattr(self, 'sort'):
            self.state['sort'] = self.sort.currentData(); self.state['page'] = 1
            self.load()

    def size_changed(self):
        if hasattr(self, 'page_size'):
            self.state['pageSize'] = self.page_size.currentData(); self.state['page'] = 1
            self.load()

    def turn(self, amount):
        self.state['page'] = max(1, min(self.data.get('totalPages',1), self.state['page'] + amount))
        self.load()

    def go_to_page(self):
        if self.state['page'] != self.page_spin.value():
            self.state['page'] = self.page_spin.value(); self.load()

    def reset(self):
        self.state = dict(DEFAULT, view=self.state['view'], sort=self.sort.currentData(), pageSize=self.page_size.currentData())
        self.search.blockSignals(True); self.search.clear(); self.search.blockSignals(False)
        self.facet_search.clear()
        self.debounce.stop(); self.load()

    def favourites(self):
        return set(self.preferences.get('favourites', []))

    def toggle_favourite(self, item_id):
        def change(preferences):
            ids = list(preferences.get('favourites', []))
            return {'favourites': [value for value in ids if value != item_id] if item_id in ids else ids + [item_id]}
        self.queue_preference(change)

    def queue_preference(self, mutation, failure=None):
        self.preference_queue.append((mutation,failure))
        self.flush_preferences()

    def flush_preferences(self):
        if self.preference_busy or not self.preference_queue:
            return
        self.preference_busy = True
        mutation, failure = self.preference_queue.pop(0)
        def current(preferences):
            patch = mutation(preferences)
            def saved(_):
                self.preferences = dict(preferences, **patch)
                appearance.apply(dict(self.preferences, **self.appearance_overrides))
                self.preference_busy = False
                self.preferencesChanged.emit(); self.cards.viewport().update()
                if self.state['view'] in ('favourites','recent'): self.load()
                self.flush_preferences()
            self.api.request('/api/preferences', saved, body=patch, error=failed)
        def failed(message):
            self.preference_busy = False
            if failure:
                failure(message)
            self.error(message)
            self.flush_preferences()
        self.api.request('/api/preferences', current, error=failed)

    def open_id(self, item_id):
        self.api.request(f'/api/items/{item_id}', self.open_item)

    def open_item(self, item):
        if not item:
            return
        for panel in self.dialogs:
            if isinstance(panel, Detail) and panel.isVisible() and panel.item['id'] == item['id']:
                panel.raise_(); panel.activateWindow(); return
        panel = Detail(self, item); self.dialogs.append(panel); panel.show()
        def recent(preferences):
            entries = [{'id':item['id'], 'at':int(time.time()*1000)}] + [value for value in preferences.get('recent-views', []) if value['id'] != item['id']]
            entries.sort(key=lambda value: value['at'], reverse=True)
            return {'recent-views':entries[:500]}
        self.queue_preference(recent)

    def show_panel(self, kind):
        if not self.connected:
            self.error(tr('请等待素材库启动完成。')); return
        for panel in self.dialogs:
            if type(panel) is kind and panel.isVisible():
                panel.raise_(); panel.activateWindow(); return
        panel = kind(self); self.dialogs.append(panel); panel.show()

    def advanced(self):
        from PySide6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox
        dialog = QDialog(self); render(dialog, 'setWindowTitle', tr('更多筛选')); dialog.resize(480,560)
        layout = QVBoxLayout(dialog); form = QFormLayout(); layout.addLayout(form)
        adult = combo([(tr('安全内容'),'safe'),(tr('全部内容'),'all'),(tr('仅暗示性'),'suggestive'),(tr('仅成人内容'),'adult')]); adult.setCurrentIndex(max(0,adult.findData(self.state.get('adult','safe')))); form_row(form, tr('内容分级'), adult)
        availability = combo([(tr('全部商品'),'all'),(tr('本地已收录'),'local'),(tr('扫描未收录'),'missing')]); availability.setCurrentIndex(max(0,availability.findData(self.state.get('availability','all')))); form_row(form, tr('商品范围'), availability)
        purchase = combo([(tr('不限'),'all'),(tr('已同步已购'),'recorded'),(tr('已购但本地未收录'),'missing-local'),(tr('未同步已购'),'not-recorded')]); purchase.setCurrentIndex(max(0,purchase.findData(self.state.get('purchase','all')))); form_row(form, tr('已购记录'), purchase)
        minimum = QSpinBox(); minimum.setRange(0,1000000); minimum.setValue(self.state.get('min') or 0); form_row(form, tr('最低价格 JPY'), minimum)
        maximum = QSpinBox(); maximum.setRange(-1,1000000); render(maximum, 'setSpecialValueText', tr('不限')); maximum.setValue(self.state.get('max') if self.state.get('max') is not None else -1); form_row(form, tr('最高价格 JPY'), maximum)
        free = checkbox(tr('仅免费')); free.setChecked(bool(self.state.get('free'))); form.addRow('',free)
        size = combo([(tr('不限'),0),('≥ 100 MiB',104857600),('≥ 1 GiB',1073741824),('≥ 5 GiB',5368709120),('≥ 10 GiB',10737418240)]); size.setCurrentIndex(max(0,size.findData(self.state.get('minBytes',0)))); form_row(form, tr('本地体积'), size)
        duplicates = checkbox(tr('仅同商品有多个本地副本')); duplicates.setChecked(bool(self.state.get('duplicates'))); form.addRow('',duplicates)
        mentions = checkbox(tr('包含未确认的适配提及')); mentions.setChecked(bool(self.state.get('includeMentions'))); form.addRow('',mentions)
        layout.addStretch(); buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        render(buttons.button(QDialogButtonBox.StandardButton.Ok),'setText',tr('应用'))
        render(buttons.button(QDialogButtonBox.StandardButton.Cancel),'setText',tr('取消'))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.state.update(adult=adult.currentData(),availability=availability.currentData(),purchase=purchase.currentData(),min=minimum.value(),max=maximum.value() if maximum.value() >= 0 else None,free=free.isChecked(),minBytes=size.currentData(),duplicates=duplicates.isChecked(),includeMentions=mentions.isChecked(),page=1)
            self.load()

    def save_filter(self):
        name, accepted = QInputDialog.getText(self, tr('保存筛选'), tr('筛选名称'))
        if not accepted or not name.strip(): return
        state = {key:value for key,value in self.state.items() if key not in ('page','ids')}
        query = saved_query(state)
        self.queue_preference(lambda preferences: {'saved-searches':(preferences.get('saved-searches', []) + [{'id':uuid.uuid4().hex,'name':name.strip()[:80],'query':query}])[-50:]})

    def show_saved(self):
        menu = QMenu(self)
        for entry in self.preferences.get('saved-searches', []):
            item = menu.addMenu(entry['name'])
            item.addAction(tr('恢复筛选'), lambda checked=False, e=entry: self.restore_filter(e))
            item.addAction(tr('删除'), lambda checked=False, e=entry: self.queue_preference(lambda p: {'saved-searches':[v for v in p.get('saved-searches',[]) if v['id'] != e['id']]}))
        if not self.preferences.get('saved-searches'): menu.addAction(tr('还没有保存的筛选')).setEnabled(False)
        menu.exec(self.saved_button.mapToGlobal(self.saved_button.rect().bottomLeft()))

    def restore_filter(self, entry):
        parsed = parse_qs(entry['query'])
        state = dict(DEFAULT)
        arrays = ('category','avatar','author','tag','excludeTag','feature','fileType','localCategory')
        for key, values in parsed.items():
            if key in arrays: state[key] = [part for value in values for part in value.split(',') if part]
            elif key in ('min','max','minBytes','pageSize'): state[key] = int(values[0])
            elif key in ('free','duplicates','includeMentions'): state[key] = values[0] == '1'
            elif key in ('view','sort','adult','availability','purchase','q'): state[key] = values[0]
        self.apply_filter_state(state)

    def apply_filter_state(self, state):
        self.debounce.stop()
        self.state = state
        self.search.blockSignals(True); render(self.search, 'setText', state.get('q','')); self.search.blockSignals(False)
        self.sort.blockSignals(True); self.sort.setCurrentIndex(max(0,self.sort.findData(state['sort']))); self.sort.blockSignals(False)
        self.page_size.blockSignals(True); self.page_size.setCurrentIndex(max(0,self.page_size.findData(state['pageSize']))); self.page_size.blockSignals(False)
        self.select_view(state['view'])

    def closeEvent(self, event):
        if self.ready_to_close:
            event.accept(); return
        event.ignore()
        if self.shutting_down:
            return
        if self.preference_busy or self.preference_queue:
            render(self.statusBar(),'showMessage',tr('正在保存收藏与浏览记录…'))
            QTimer.singleShot(150, self.close)
            return
        self.shutting_down = True
        self.heartbeat.stop()
        self.watcher.stop()
        for panel in self.dialogs: panel.close()
        self.centralWidget().setEnabled(False)
        render(self.statusBar(),'showMessage',tr('正在保存进度并关闭素材库…'))
        self.backend.stop()

    def closed_backend(self):
        self.ready_to_close = True
        self.close()

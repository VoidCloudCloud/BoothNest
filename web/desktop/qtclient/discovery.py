# SPDX-License-Identifier: GPL-3.0-only
"""Native quick find and portable public filters. No external link is fetched."""
import re
from urllib.parse import parse_qs, urlsplit, urlencode

from PySide6.QtCore import QEvent, QTimer, Qt, Signal, QSize
from PySide6.QtGui import QAction, QKeySequence, QFont, QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit)
from .core import saved_query
from .dialogs import Panel
from .presentation import tr, render, resolve, appearance
from .widgets import button, label


PUBLIC_ENUMS = {
    'view': ('items','avatars'),
    'sort': ('trending','newest','oldest','likes','price-asc','price-desc','title'),
    'adult': ('safe','all','suggestive','adult'),
}
PUBLIC_ARRAYS = ('category','avatar','author','tag','excludeTag','feature')
SHARE_PREFIX = 'BoothNest filters v1\n?'


def public_value(value):
    # A local-search query or pasted pairing code must not become portable text.
    return not (re.search(r'[a-zA-Z]:[\\/]|\\\\|file://|(?:^|\s)/', value)
                or re.search(r'boothnest-pair=|(?:token|password|secret)=', value, re.I))


def public_state(state):
    clean = {'view':'items','sort':'trending','adult':'safe'}
    for key, allowed in PUBLIC_ENUMS.items():
        if state.get(key) in allowed:
            clean[key] = state[key]
    text = str(state.get('q') or '').strip()[:200]
    if text and public_value(text):
        clean['q'] = text
    for key in PUBLIC_ARRAYS:
        values = state.get(key, [])
        if isinstance(values, str):
            values = values.split(',')
        clean[key] = list(dict.fromkeys(value.strip()[:200] for value in values if isinstance(value,str) and value.strip() and public_value(value)))[:50]
    for key in ('free','includeMentions'):
        if state.get(key): clean[key] = True
    for key in ('min','max'):
        value = state.get(key)
        if isinstance(value,int) and not isinstance(value,bool) and 0 <= value <= 9007199254740991:
            clean[key] = value
    if state.get('pageSize') in (20,40,60,100):
        clean['pageSize'] = state['pageSize']
    return clean


def share_text(state):
    return SHARE_PREFIX + saved_query(public_state(state))


def import_filter(text):
    text = text.strip()
    if not text or len(text) > 16000:
        raise ValueError(tr('无效的筛选文本。'))
    if text.startswith(SHARE_PREFIX):
        query = text[len(SHARE_PREFIX):]
    elif text.startswith(('https://','http://')):
        query = urlsplit(text).query
    elif text.startswith('?'):
        query = text[1:]
    elif re.match(r'^[a-zA-Z][a-zA-Z0-9]*=',text):
        query = text
    else:
        raise ValueError(tr('无效的筛选文本。'))
    try:
        parsed = parse_qs(query, max_num_fields=500)
    except ValueError:
        raise ValueError(tr('无效的筛选文本。')) from None
    state, found = {}, False
    for key, values in parsed.items():
        if key in PUBLIC_ENUMS and values[0] in PUBLIC_ENUMS[key]:
            state[key] = values[0]; found = True
        elif key in PUBLIC_ARRAYS or key == 'q':
            state[key] = [part for value in values for part in value.split(',')] if key in PUBLIC_ARRAYS else values[0]
            found = True
        elif key in ('min','max','pageSize') and re.fullmatch(r'\d{1,16}',values[0]):
            state[key] = int(values[0]); found = True
        elif key in ('free','includeMentions') and values[0] == '1':
            state[key] = True; found = True
    if not found:
        raise ValueError(tr('未找到可导入的公开筛选条件。'))
    return public_state(state)


class QuickFind(Panel):
    resultsReady = Signal()

    def __init__(self, window):
        super().__init__(window, tr('快捷查找'), 760, 600)
        self.generation, self.composing = 0, False
        self.results, self.query = {}, ''
        self.input = QLineEdit()
        render(self.input,'setPlaceholderText',tr('输入商品、模型、作者或标签'))
        self.input.setClearButtonEnabled(True)
        self.layout.addWidget(self.input)
        self.list = QListWidget()
        self.list.setObjectName('QuickFindResults')
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setSpacing(2)
        self.layout.addWidget(self.list,1)
        self.layout.addWidget(label(tr('↑↓ 选择 · Enter 打开 · Esc 关闭'),'Subtle'))
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(150)
        self.debounce.timeout.connect(self.search)
        self.input.textChanged.connect(self.changed)
        self.input.installEventFilter(self)
        self.list.installEventFilter(self)
        self.list.itemClicked.connect(self.choose)
        action = QAction(self)
        action.setShortcut(QKeySequence('Ctrl+K'))
        action.triggered.connect(self.close)
        self.addAction(action)
        self.finished.connect(self.cancel)
        appearance.changed.connect(self.render_results)
        QTimer.singleShot(0, self.input.setFocus)
        self.search()

    def cancel(self):
        self.generation += 1
        self.debounce.stop()

    def changed(self):
        self.generation += 1
        self.results = {}
        self.query = self.input.text().strip()[:200]
        self.render_results()
        if not self.composing:
            self.debounce.start()

    def search(self):
        self.debounce.stop()
        if self.composing:
            return
        self.generation += 1
        generation = self.generation
        query = self.input.text().strip()[:200]
        def receive(value):
            if generation != self.generation:
                return
            self.results, self.query = value, query
            self.render_results()
            self.resultsReady.emit()
        self.api.request('/api/palette?' + urlencode({'q':query,'adult':self.window.state.get('adult','safe')}), receive,
                         error=lambda message: self.error(message) if generation == self.generation else None)

    def render_results(self):
        selected = self.list.currentItem()
        payload = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self.list.clear()
        if self.query:
            self.add(resolve(tr('搜索全部“{0}”', self.query)), ('query',self.query))
        for group, title in [('items',tr('商品')),('avatars',tr('模型')),('authors',tr('作者')),('tags',tr('标签'))]:
            entries = self.results.get(group, [])
            if not entries: continue
            heading = QListWidgetItem(resolve(title), self.list)
            heading.setFlags(Qt.ItemFlag.ItemIsEnabled)
            heading.setSizeHint(QSize(0,28))
            heading.setForeground(QColor(appearance.color('secondary')))
            font = heading.font(); font.setWeight(QFont.Weight.DemiBold); heading.setFont(font)
            for entry in entries:
                if group == 'items':
                    price = appearance.money(entry.get('price'), entry.get('priceKnown',entry.get('price') is not None))
                    text = f"{appearance.item_text(entry)} · {entry.get('author','')} · {price}"
                    value = entry['id']
                else:
                    text = f"{appearance.facet(entry)} ({entry.get('count',0):,})"
                    value = entry['slug'] if group == 'avatars' else entry['name']
                self.add(text, (group,value))
        selectable = [self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(Qt.ItemDataRole.UserRole)]
        if selectable:
            self.list.setCurrentItem(next((item for item in selectable if item.data(Qt.ItemDataRole.UserRole) == payload),selectable[0]))

    def add(self, text, payload):
        entry = QListWidgetItem(text,self.list)
        entry.setData(Qt.ItemDataRole.UserRole,payload)
        entry.setSizeHint(QSize(0,34))
        entry.setToolTip(text)

    def choose(self, item=None):
        item = item or self.list.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not payload: return
        group, value = payload
        self.accept()
        if group == 'items':
            self.window.open_id(value)
        else:
            self.window.select_group(group,value)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.Type.InputMethod:
            self.composing = bool(event.preeditString())
            if self.composing:
                self.debounce.stop()
            else:
                self.debounce.start()
        if event.type() == QEvent.Type.KeyPress:
            if self.composing:
                return False
            key = event.key()
            if key in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
                self.choose(); return True
            if key in (Qt.Key.Key_Up,Qt.Key.Key_Down):
                direction = 1 if key == Qt.Key.Key_Down else -1
                current = self.list.currentRow()
                for _ in range(self.list.count()):
                    current = (current+direction) % self.list.count()
                    entry = self.list.item(current)
                    if entry.data(Qt.ItemDataRole.UserRole):
                        self.list.setCurrentRow(current); break
                return True
        return super().eventFilter(obj,event)


class ShareFilters(Panel):
    def __init__(self, window):
        super().__init__(window,tr('分享与导入筛选'),790,600)
        self.layout.addWidget(label(tr('只分享公开筛选条件；本地库存、已购、收藏、历史、文件类型与本地排序会自动省略。可检查下方文本后复制。'),'Subtle'))
        self.export = QPlainTextEdit(share_text(window.state))
        self.export.setReadOnly(True)
        self.layout.addWidget(self.export,1)
        self.copy = button(tr('复制筛选'),self.copy_filters)
        self.layout.addWidget(self.copy)
        self.layout.addWidget(label(tr('粘贴筛选文本或网页链接'),'Subtle'))
        self.input = QPlainTextEdit()
        self.layout.addWidget(self.input,1)
        actions = QHBoxLayout()
        actions.addWidget(button(tr('导入筛选'),self.apply_filters,True))
        actions.addStretch()
        actions.addWidget(button(tr('关闭'),self.accept))
        self.layout.addLayout(actions)

    def copy_filters(self):
        QApplication.clipboard().setText(self.export.toPlainText())
        render(self.copy,'setText',tr('已复制筛选'))

    def apply_filters(self):
        try:
            state = import_filter(self.input.toPlainText())
        except ValueError as exc:
            self.error(str(exc)); return
        from .window import DEFAULT
        self.window.apply_filter_state(dict(DEFAULT, **state))
        self.accept()

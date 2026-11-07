# SPDX-License-Identifier: GPL-3.0-only
from .presentation import tr, render, appearance, resolve
from PySide6.QtCore import QAbstractListModel, QAbstractTableModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout,
                               QLabel, QListView, QPushButton, QStyledItemDelegate,
                               QStyle, QTableView, QVBoxLayout, QWidget)
from .core import bytes_label, price_label


STYLE = '''
QWidget { background:#15161c; color:#e9e9ef; font-family:"Microsoft YaHei UI","Segoe UI"; font-size:13px; }
QMainWindow, QDialog { background:#15161c; }
QLabel { background:transparent; }
QLabel#Brand { font-size:25px; font-weight:700; }
QLabel#Title { font-size:24px; font-weight:700; }
QLabel#Subtle { color:#9b9da9; }
QLabel#Error { color:#ffb1b6; background:#35232b; padding:10px; border-radius:6px; }
QFrame#Topbar { background:#1b1c24; border-bottom:1px solid #30313b; }
QFrame#Sidebar { background:#1b1c24; border-right:1px solid #30313b; }
QFrame#Panel, QGroupBox { background:#1c1d26; border:1px solid #30323e; border-radius:8px; }
QGroupBox { margin-top:14px; padding:14px 10px 8px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; color:#aeb0bd; }
QPushButton, QToolButton { background:#262834; border:1px solid #383a48; border-radius:6px; padding:8px 14px; }
QPushButton:hover, QToolButton:hover { background:#333644; border-color:#72778d; }
QPushButton:pressed { background:#414452; }
QPushButton:disabled { color:#686b78; background:#20212a; border-color:#2d2f39; }
QPushButton#Primary { background:#ee919b; color:#23171d; border-color:#ee919b; font-weight:600; }
QPushButton#Primary:hover { background:#ffadb5; }
QPushButton#Nav { text-align:left; padding:11px 15px; background:transparent; border:0; }
QPushButton#Nav:checked { background:#3b2b35; color:#ffc0c6; border-left:3px solid #ed919b; border-radius:4px; }
QLineEdit, QSpinBox, QComboBox { background:#20222d; border:1px solid #3a3d4b; border-radius:6px; padding:7px 9px; min-height:20px; selection-background-color:#665060; }
QLineEdit:focus, QComboBox:focus { border-color:#ee919b; }
QComboBox::drop-down { border:0; width:22px; }
QComboBox QAbstractItemView { background:#252733; selection-background-color:#4a3542; padding:4px; }
QListView, QTreeWidget, QTableView, QTextEdit, QTextBrowser, QPlainTextEdit { background:#191b23; border:1px solid #313440; border-radius:7px; outline:0; selection-background-color:#49313f; selection-color:#e9e9ef; }
QListView#Cards { background:transparent; border:0; }
QListView#QuickFindResults::item { padding:4px 10px; border-radius:4px; }
QTreeWidget::item { padding:5px 2px; }
QTreeWidget::item:selected { background:#42303b; }
QHeaderView::section { background:#272936; color:#b6b8c5; padding:9px; border:0; border-bottom:1px solid #393c49; }
QTableView { gridline-color:#2c2e3b; alternate-background-color:#1e202a; }
QTableView::item { padding:5px; }
QScrollArea { border:0; background:transparent; }
QScrollBar:vertical { background:transparent; width:10px; margin:1px; }
QScrollBar::handle:vertical { background:#454958; border-radius:4px; min-height:30px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { height:10px; background:transparent; }
QScrollBar::handle:horizontal { background:#454958; min-width:30px; border-radius:4px; }
QCheckBox { spacing:7px; background:transparent; padding:3px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #666a7c; border-radius:3px; background:#22242f; }
QCheckBox::indicator:checked { background:#eb929e; border-color:#eb929e; image:none; }
QTabWidget::pane { border:1px solid #353846; border-radius:6px; }
QTabBar::tab { padding:10px 18px; background:#242631; border:0; }
QTabBar::tab:selected { color:#ffb7c1; border-bottom:2px solid #ed919b; }
QProgressBar { border:1px solid #383b49; border-radius:5px; text-align:center; background:#20222d; min-height:16px; }
QProgressBar::chunk { background:#ba7e92; border-radius:4px; }
QStatusBar { background:#1b1c24; color:#989dac; border-top:1px solid #30313b; }
QMenu { background:#242631; border:1px solid #434654; padding:5px; }
QMenu::item { padding:8px 24px; }
QMenu::item:selected { background:#49313f; }
QToolTip { background:#303340; color:#eee; border:1px solid #5e6275; padding:6px; }
'''


def stylesheet():
    if appearance.theme != 'cloud':
        return STYLE
    colors = {
        '#15161c':'#f4f5f8','#e9e9ef':'#252938','#9b9da9':'#626b80',
        '#ffb1b6':'#9c304d','#35232b':'#ffe8ec','#1b1c24':'#ffffff',
        '#30313b':'#dcdfe8','#1c1d26':'#ffffff','#30323e':'#d9dde6',
        '#aeb0bd':'#697287','#262834':'#f0f1f6','#383a48':'#ccd1de',
        '#333644':'#e4e7f0','#72778d':'#8b93a9','#414452':'#d9deeb',
        '#686b78':'#979cad','#20212a':'#eceef3','#2d2f39':'#dfe2ea',
        '#ee919b':'#a33e5b','#23171d':'#ffffff','#ffadb5':'#b8506d',
        '#3b2b35':'#f5e4ea','#ffc0c6':'#94374f','#ed919b':'#aa4c68',
        '#20222d':'#ffffff','#3a3d4b':'#ccd1df','#665060':'#e2c9d4',
        '#252733':'#ffffff','#4a3542':'#ecd9e2','#191b23':'#ffffff',
        '#313440':'#d8dce7','#49313f':'#ead6df','#42303b':'#eee0e7',
        '#272936':'#e9ecf3','#b6b8c5':'#505a71','#393c49':'#cdd3df',
        '#2c2e3b':'#e0e4ed','#1e202a':'#f7f8fb','#454958':'#b3baca',
        '#666a7c':'#929bb0','#22242f':'#ffffff','#eb929e':'#ad526d',
        '#353846':'#d7dce7','#242631':'#edf0f6','#ffb7c1':'#993951',
        '#383b49':'#d4d9e4','#ba7e92':'#b45c78','#989dac':'#657087',
        '#434654':'#cdd3df','#303340':'#fffafd','#eee':'#292c3b',
        '#5e6275':'#aeb6c9',
    }
    import re
    return re.sub(r'#[0-9a-fA-F]{3,6}\b', lambda match: colors.get(match[0], match[0]), STYLE)


def button(text, callback=None, primary=False):
    result = render(QPushButton(), 'setText', text)
    if primary:
        result.setObjectName('Primary')
    if callback:
        result.clicked.connect(callback)
    return result


def label(text, kind=None):
    result = render(QLabel(), 'setText', text)
    if kind:
        result.setObjectName(kind)
    result.setWordWrap(True)
    return result


def combo(entries, callback=None):
    result = QComboBox()
    for text, value in entries:
        result.addItem(resolve(text), value)
        render(result, 'setItemText', text, result.count() - 1)
    if callback:
        result.currentIndexChanged.connect(callback)
    return result


class ItemModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        appearance.changed.connect(self.refresh)

    def refresh(self):
        if self.items:
            self.dataChanged.emit(self.index(0), self.index(len(self.items)-1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        item = self.items[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return item
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.AccessibleTextRole):
            return f"{appearance.item_text(item)} · {item.get('author', '')} · {price_label(item)}"

    def replace(self, items):
        self.beginResetModel()
        self.items = items
        self.endResetModel()


class CardDelegate(QStyledItemDelegate):
    def __init__(self, images, favourites, parent=None):
        super().__init__(parent)
        self.images, self.favourites = images, favourites

    def paint(self, painter, option, index):
        item = index.data(Qt.ItemDataRole.UserRole)
        if not item:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(2, 2, -7, -7)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setBrush(QColor(appearance.color('selected' if selected else 'card')))
        painter.setPen(QPen(QColor(appearance.color('accent' if selected else 'border')), 1))
        painter.drawRoundedRect(rect, 10, 10)
        image_rect = QRect(rect.x() + 1, rect.y() + 1, rect.width() - 2, rect.width() - 32)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.setClipPath(path)
        painter.fillRect(image_rect, QColor(appearance.color('image')))
        pixmap = self.images.get(item.get('media', []))
        if pixmap:
            scaled = pixmap.scaled(image_rect.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(image_rect.center().x() - scaled.width() // 2, image_rect.center().y() - scaled.height() // 2, scaled)
        else:
            painter.setPen(QColor(appearance.color('muted')))
            painter.setFont(QFont('Segoe UI', 26))
            painter.drawText(image_rect, Qt.AlignmentFlag.AlignCenter, 'BN')
        painter.setClipping(False)
        price = price_label(item)
        painter.setFont(QFont('Microsoft YaHei UI', 10, QFont.Weight.DemiBold))
        badge = QRect(image_rect.x() + 10, image_rect.bottom() - 31, min(image_rect.width()-20,max(92,painter.fontMetrics().horizontalAdvance(price)+20)), 24)
        painter.setPen(Qt.PenStyle.NoPen)
        badge_color = QColor(appearance.color('badge')); badge_color.setAlpha(240)
        painter.setBrush(badge_color)
        painter.drawRoundedRect(badge, 5, 5)
        painter.setPen(QColor(appearance.color('price')))
        painter.setFont(QFont('Microsoft YaHei UI', 10, QFont.Weight.DemiBold))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, price)
        heart = QRect(rect.right() - 36, rect.y() + 10, 27, 27)
        painter.setBrush(QColor(appearance.color('heart')))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(heart)
        painter.setPen(QColor(appearance.color('favourite' if item['id'] in self.favourites() else 'icon')))
        painter.setFont(QFont('Segoe UI Symbol', 15))
        painter.drawText(heart, Qt.AlignmentFlag.AlignCenter, '♥' if item['id'] in self.favourites() else '♡')
        text_rect = QRect(rect.x() + 12, image_rect.bottom() + 11, rect.width() - 24, 43)
        painter.setPen(QColor(appearance.color('text')))
        painter.setFont(QFont('Microsoft YaHei UI', 10, QFont.Weight.DemiBold))
        layout = QTextLayout(appearance.item_text(item), painter.font())
        options = QTextOption()
        options.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(options)
        layout.beginLayout()
        y = text_rect.y()
        for _ in range(2):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(text_rect.width())
            from PySide6.QtCore import QPointF
            line.setPosition(QPointF(text_rect.x(), y))
            y += line.height()
        layout.endLayout()
        from PySide6.QtCore import QPointF
        painter.save()
        painter.setClipRect(text_rect)
        layout.draw(painter, QPointF(0, 0))
        painter.restore()
        painter.setFont(QFont('Microsoft YaHei UI', 9))
        painter.setPen(QColor(appearance.color('secondary')))
        author = painter.fontMetrics().elidedText(item.get('author', tr('未知作者')), Qt.TextElideMode.ElideRight, rect.width() - 24)
        painter.drawText(QRect(rect.x() + 12, text_rect.bottom() + 5, rect.width() - 24, 23), author)
        local = item.get('local', {})
        status = tr('本地 {0} 份 · {1}', local['copies'], bytes_label(local.get('bytes'))) if local.get('copies') else tr('本地未收录') if local.get('known') else tr('未连接本地库')
        if item.get('purchase', {}).get('recorded'):
            status = tr('已购  ·  ') + status
        painter.setPen(QColor(appearance.color('local' if local.get('copies') else 'missing')))
        painter.drawText(QRect(rect.x() + 12, rect.bottom() - 30, rect.width() - 24, 22), status)
        painter.restore()

    def sizeHint(self, option, index):
        return self.parent().gridSize()


class CardView(QListView):
    favouriteClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Cards')
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setUniformItemSizes(True)
        self.setWrapping(True)
        self.setSpacing(0)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setGridSize(QSize(235, 330))
        render(self, 'setAccessibleName', tr('商品图库；选择商品后按 Enter 查看详情'))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        available = max(200, self.viewport().width() - 6)
        columns = max(1, available // 226)
        width = available // columns
        size = QSize(width, width + 99)
        if size != self.gridSize():
            self.setGridSize(size)

    def mouseReleaseEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and event.button() == Qt.MouseButton.LeftButton:
            rect = self.visualRect(index).adjusted(2, 2, -7, -7)
            if QRect(rect.right() - 36, rect.y() + 10, 27, 27).contains(event.position().toPoint()):
                self.favouriteClicked.emit(index.data(Qt.ItemDataRole.UserRole)['id'])
                return
        super().mouseReleaseEvent(event)


class TableModel(QAbstractTableModel):
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns, self.rows = columns, []
        appearance.changed.connect(self.refresh)

    def refresh(self):
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.columns) - 1)
        if self.rows:
            self.dataChanged.emit(self.index(0,0), self.index(len(self.rows)-1,len(self.columns)-1))

    def replace(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return resolve(self.columns[section][0]) if orientation == Qt.Orientation.Horizontal else section + 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            key = self.columns[index.column()][1]
            value = key(row) if callable(key) else row.get(key, '')
            return ', '.join(map(resolve, value)) if isinstance(value, list) else resolve(value if value is not None else '')


def table(columns, parent=None):
    view = QTableView(parent)
    model = TableModel(columns, view)
    view.setModel(model)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setAlternatingRowColors(True)
    view.verticalHeader().hide()
    view.horizontalHeader().setStretchLastSection(True)
    view.verticalHeader().setDefaultSectionSize(36)
    return view, model


class ImageBox(QWidget):
    def __init__(self, images, parent=None):
        super().__init__(parent)
        self.images, self.candidates = images, []
        self.setMinimumSize(220, 180)
        images.changed.connect(self.update)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(appearance.color('image')))
        pixmap = self.images.get(self.candidates)
        if pixmap:
            scaled = pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        else:
            painter.setPen(QColor(appearance.color('missing')))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr('暂无预览图'))

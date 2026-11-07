# SPDX-License-Identifier: GPL-3.0-only
"""Presentation preferences and explicit, live text bindings for native widgets.

Only text passed through tr/render is translated. Product names, paths, tags,
saved-search names and editable fields are never looked up in the UI dictionary.
"""
from weakref import WeakKeyDictionary

from PySide6.QtCore import QObject, Signal
from shiboken6 import isValid


EN = dict(line.split('\t', 1) for line in '''
标签：\tTags:
 · 自动同步已开启\t · Automatic sync enabled
 · 自动同步已暂停\t · Automatic sync paused
 分钟\t min
 小时\t h
 页\t
BOOTH 商品链接或 ID\tBOOTH item URL or ID
BOOTH 喜欢\tBOOTH likes
BoothNest — 素材库\tBoothNest — Asset library
BoothNest商品目录.json\tBoothNest-catalogue.json
BoothNest已购记录.json\tBoothNest-purchases.json
{0:,} 件匹配素材  /  目录 {1:,} 件\t{0:,} matching assets / {1:,} catalogue items
{0} · 队列 {1:,} 件 · {2}\\n{3}\t{0} · {1:,} queued · {2}\\n{3}
‹ 上一张\t‹ Previous image
‹ 上一页\t‹ Previous
♡ 收藏\t♡ Favourite
♥ 已收藏\t♥ Favourited
上一页\tPrevious
下一张 ›\tNext image ›
下一页\tNext
下一页 ›\tNext ›
下载浏览器扩展\tDownload browser extension
下载目录\tDownloads folder
不限\tAny
为 {0} 个条目指定 BOOTH 商品 ID 或链接\tBOOTH item ID or URL for {0} entries
仅使用本地缓存\tUse local cache only
仅免费\tFree only
仅同商品有多个本地副本\tMultiple local copies of the same item only
仅成人内容\tAdult only
仅暗示性\tSuggestive only
价格 JPY\tPrice JPY
价格 ¥{0}–{1}\tPrice JPY {0}–{1}
价格从低到高\tPrice: low to high
价格从高到低\tPrice: high to low
价格未知\tPrice unknown
体积从大到小\tSize: large to small
作者\tAuthor
保存同步设置\tSave sync settings
保存筛选\tSave filters
保存设置\tSave settings
停止同步\tStop sync
免费\tFree
全部内容\tAll content
全部商品\tAll items
全部条目\tAll entries
全量重扫\tFull rescan
公开同步按关键词逐批收录商品信息，进度可续跑；不会下载素材包。\tPublic sync collects item metadata in batches by keyword and can resume its progress. Asset packages are not downloaded.
公开目录同步\tPublic catalogue sync
共 {0:,} 条库存 · 已识别 {1:,} · 未识别 {2:,} · 当前筛选 {3:,}\t{0:,} inventory entries · {1:,} identified · {2:,} unidentified · {3:,} matching
关键词（逗号分隔）\tKeywords (comma separated)
关键词，例如 MAYO 衣装\tKeywords, e.g. MAYO outfit
关闭\tClose
内容分级\tContent rating
分类\tCategory
分类与统计\tCategories and statistics
分组\tGroup
创作者\tCreators
删除\tDelete
刷新\tRefresh
功能\tFeature
功能支持\tSupported features
包含未确认的适配提及\tInclude unconfirmed compatibility mentions
包含未确认适配\tInclude compatibility mentions
包含标签\tIncluded tags
参考价 JPY\tReference price JPY
取消商品归属\tUnmatch item
取消扫描\tCancel scan
取消核对\tCancel verification
同商品多份\tMultiple copies
名称\tName
后台服务已退出（{0}），请查看 logs/qt-server.log。\tBackend exited ({0}). See logs/qt-server.log.
后台服务未能启动，请查看数据目录中的 logs/qt-server.log。\tBackend could not start. See logs/qt-server.log in the data folder.
商品 ID\tItem ID
商品名称\tItem title
商品图库；选择商品后按 Enter 查看详情\tItem gallery; select an item and press Enter for details
商品数\tProducts
商品目录 {0:,} 件 · 已购 {1:,} 件\\n\t{0:,} catalogue items · {1:,} purchased\\n
商品范围\tItem scope
商品详情\tItem details
商品说明\tDescription
商店\tShop
图库\tGallery
在已登录 BOOTH 的普通浏览器中安装配对扩展，使用已有登录状态同步已购清单。\tInstall the pairing extension in a browser signed in to BOOTH to sync purchases using that existing session.
在程序运行时自动增量扫描\tAutomatically scan for changes while the app is running
复制配对信息\tCopy pairing information
大小\tSize
安全内容\tSafe content
定位所选文件\tReveal selected file
定位本地文件\tReveal local file
导入 JSON\tImport JSON
导入与导出\tImport and export
导入商品 JSON…\tImport catalogue JSON…
导入已购 JSON…\tImport purchases JSON…
导入文件超过 100 MB。\tThe import file exceeds 100 MB.
导出全部库存与统计 CSV\tExport all inventory and statistics as CSV
导出商品目录\tExport catalogue
导出已购记录\tExport purchases
导出文件\tExport file
导出核对\tExport verification
导出筛选 CSV\tExport filtered CSV
尚未配对浏览器扩展\tBrowser extension not paired
已保存 ▾\tSaved ▾
已同步已购\tRecorded purchases
已导出到 \tExported to\x20
已导出：\tExported:\x20
已忽略\tIgnored
已识别\tIdentified
已购\tPurchased
已购  ·  \tPurchased ·\x20
已购但本地未收录\tPurchased, missing locally
已购条件：\tPurchases:\x20
已购清单\tPurchases
已购自动同步\tAutomatic purchase sync
已购记录\tPurchase records
已配对浏览器扩展\tBrowser extension paired
年份\tYear
库存、收藏与已购记录由现有 BoothNest 数据目录统一保存。\tInventory, favourites and purchase records are saved in the existing BoothNest data folder.
库存条目\tInventory entries
库存管理\tInventory
库存：\tInventory:\x20
开始 SHA-256 核对\tVerify with SHA-256
当前筛选没有匹配的商品。\\n可以清除筛选条件，或扫描下载目录。\tNo items match these filters.\\nClear the filters or scan your downloads folder.
忽略所选\tIgnore selected
忽略探测缓存，重新检查全部条目\tIgnore detection cache and recheck all entries
恢复筛选\tRestore filters
恢复自动同步\tResume automatic sync
恢复自动识别\tRestore automatic identification
我的收藏\tFavourites
手动修正\tManually corrected
打开 BOOTH\tOpen BOOTH
打开 BOOTH 下载库\tOpen BOOTH downloads
打开数据目录\tOpen data folder
扫描下载目录\tScan downloads
扫描完成\tScan complete
扫描未收录\tMissing locally
扫描目录\tScan folder
扫描间隔\tScan interval
批次间隔\tBatch interval
按文件内容核对重复；只读取原文件。\tFind duplicates by file content. Original files are read only.
按需统计缩略图与引擎缓存。\tCalculate thumbnail and engine cache statistics on demand.
排除标签\tExcluded tags
搜索并收录公开商品\tSearch and add public items
搜索文件路径、商品名或 ID\tSearch paths, item titles or IDs
搜索素材、模型、作者或商品 ID    Ctrl+K\tSearch assets, avatars, authors or item IDs    Ctrl+F
操作未完成\tOperation incomplete
数据与同步\tData and sync
数据管理\tData management
文件类型\tFile type
无法连接指定的本地服务。\tCannot connect to the specified local service.
无预览图\tNo preview
是\tYes
暂停自动同步\tPause automatic sync
暂无商品说明。\tNo description available.
暂无预览图\tNo preview available
更多筛选\tMore filters
更多筛选…\tMore filters…
最低价格 JPY\tMinimum price JPY
最多喜欢\tMost liked
最新发布\tNewest
最早发布\tOldest
最近修改\tRecently modified
最近浏览\tRecently viewed
最高价格 JPY\tMaximum price JPY
服务连接中断，请重新启动客户端。\tService disconnected. Restart the client.
未同步已购\tNo recorded purchase
未注明适配模型\tNo avatar compatibility specified
未知作者\tUnknown author
未识别\tUnidentified
未连接本地库\tLocal library not connected
本地 {0} 份 · {1}\t{0} local copies · {1}
本地 ≥ \tLocal ≥\x20
本地体积\tLocal size
本地分类\tLocal category
本地副本\tLocal copies
本地副本数\tLocal copy count
本地已收录\tAvailable locally
本地库存.csv\tlocal-inventory.csv
本地库存管理\tLocal inventory
本地文件\tLocal files
本地文件类型\tLocal file types
本地最近修改\tRecently modified locally
本地未收录\tMissing locally
本地相对路径\tLocal relative path
本地素材\tLocal assets
条目数\tEntries
查找分类、模型或标签\tFind categories, avatars or tags
查看缩略图统计\tThumbnail statistics
标签（√ 包含 / − 排除）\tTags (√ include / − exclude)
模型\tAvatar
正在保存收藏与浏览记录…\tSaving favourites and browsing history…
正在保存进度并关闭素材库…\tSaving progress and closing the library…
正在同步\tSyncing
正在启动素材库…\tStarting the library…
正在查找素材…\tFinding assets…
正在读取…\tLoading…
正在读取商品目录…\tLoading catalogue…
正在读取库存…\tLoading inventory…
正在读取扫描状态…\tLoading scan status…
每批商品数\tItems per batch
每页\tPer page
没有找到 Node.js，请设置 BOOTH_NEST_NODE。\tNode.js was not found. Set BOOTH_NEST_NODE.
清理商品、搜索与查证缓存？下次联网识别会重新获取资料。\tClear item, search and verification caches? Metadata will be fetched again during the next online identification.
清理识别缓存\tClear identification cache
清理识别缓存…\tClear identification cache…
清除筛选条件\tClear filters
热门精选\tTrending
状态\tStatus
生成配对信息\tGenerate pairing information
生成配对信息后显示在这里\tPairing information appears here after generation
目录已更新  ·  查询 {0} ms  ·  含界面更新 {1} ms\tCatalogue updated · query {0} ms · including UI {1} ms
相对路径\tRelative path
离线模式\tOffline mode
立即同步一批\tSync one batch now
立即扫描\tScan now
第 \tPage\x20
等待同步\tWaiting to sync
等待扫描\tWaiting to scan
等待核对\tWaiting to verify
筛选名称\tFilter name
筛选素材\tFilter assets
素材分类\tAsset categories
素材探索\tExplore assets
绑定商品\tMatch item
绑定商品…\tMatch item…
缓存与导出\tCache and export
联网收录此商品\tFetch and add this item
自动同步\tAutomatic sync
自动扫描\tAutomatic scan
表格\tTable
规格\tVariations
角色模型\tAvatars
解除与浏览器扩展的配对？已购记录会保留。\tUnpair the browser extension? Purchase records will be retained.
解除配对\tUnpair
识别方式\tIdentification method
识别缓存已清理。\tIdentification cache cleared.
请先选择需要修正的库存条目。\tSelect the inventory entries to correct first.
请求立即同步\tRequest sync now
请等待素材库启动完成。\tWait for the library to finish starting.
过期刷新\tRefresh after
运行时自动同步公开商品\tAutomatically sync public items while the app is running
还没有保存的筛选\tNo saved filters yet
这个数据目录已由另一个 BoothNest 使用。请关闭原窗口后重新打开，或使用其他数据目录。\tAnother BoothNest is using this data folder. Close that window first or use a different data folder.
连接地址必须是本机 HTTP 服务地址。\tThe connection must use a loopback HTTP service address.
连接已有库存…\tConnect existing inventory…
适配模型\tCompatible avatars
适配：\tCompatible:\x20
选择下载文件夹，建立或更新本地库存。扫描进度与日志会自动刷新。\tChoose a downloads folder to create or update your local inventory. Scan progress and logs refresh automatically.
选择包含 data/dataset.json 的 BoothNest 库存目录\tChoose a BoothNest inventory folder containing data/dataset.json
选择目录…\tChoose folder…
选择素材下载目录\tChoose asset downloads folder
逻辑大小\tLogical size
重复文件核对\tDuplicate file verification
重复文件核对.csv\tduplicate-verification.csv
重复路径\tDuplicate paths
重新读取库存\tReload inventory
深色\tDark
浅色\tLight
语言\tLanguage
参考币种\tReference currency
主题\tTheme
价格 {0}\tPrice {0}
参考价 {0}\tReference price {0}
固定参考汇率：1 JPY ≈ 0.048 CNY / 0.0067 USD。实际结算以 BOOTH 日元价格为准；价格筛选始终使用 JPY。\tFixed reference rates: 1 JPY ≈ 0.048 CNY / 0.0067 USD. Check BOOTH for the actual JPY price. Price filters always use JPY.
快捷查找    Ctrl+K\tQuick find    Ctrl+K
快捷查找\tQuick find
输入商品、模型、作者或标签\tSearch items, avatars, authors or tags
搜索全部“{0}”\tSearch all for “{0}”
商品\tItems
标签\tTags
↑↓ 选择 · Enter 打开 · Esc 关闭\t↑↓ select · Enter open · Esc close
分享筛选…\tShare filters…
分享与导入筛选\tShare and import filters
只分享公开筛选条件；本地库存、已购、收藏、历史、文件类型与本地排序会自动省略。可检查下方文本后复制。\tOnly public filters are shared. Local inventory, purchases, favourites, history, file types and local sorting are omitted. Review the text below before copying.
复制筛选\tCopy filters
已复制筛选\tFilters copied
粘贴筛选文本或网页链接\tPaste filter text or a web link
导入筛选\tImport filters
无效的筛选文本。\tInvalid filter text.
未找到可导入的公开筛选条件。\tNo public filters found to import.
应用\tApply
取消\tCancel
搜索素材、模型、作者或商品 ID    Ctrl+F\tSearch assets, avatars, authors or item IDs    Ctrl+F
商品价格（参考）\tItem price (reference)
设置保存失败，请重试。\tCould not save settings. Please try again.
文件探测与扫描日志保留引擎原文。\tFile detection and scan logs retain the original engine text.
'''.strip('\n').splitlines() if '\t' in line)
# Multiline keys are explicit to keep the tab-separated dictionary readable.
EN.update({
    '\n标签：': '\nTags: ',
    '{0} · 队列 {1:,} 件 · {2}\n{3}': '{0} · {1:,} queued · {2}\n{3}',
    '商品目录 {0:,} 件 · 已购 {1:,} 件\n': '{0:,} catalogue items · {1:,} purchased\n',
    '当前筛选没有匹配的商品。\n可以清除筛选条件，或扫描下载目录。': 'No items match these filters.\nClear the filters or scan your downloads folder.',
})


class Text(str):
    def __new__(cls, key=None, args=(), parts=None):
        obj = super().__new__(cls, cls.translate(key, args, parts))
        obj.key, obj.args, obj.parts = key, args, parts
        return obj

    @staticmethod
    def translate(key, args, parts):
        if parts is not None:
            return ''.join(resolve(part) for part in parts)
        template = EN.get(key, key) if appearance.language == 'en' else key
        return template.format(*(resolve(arg) if isinstance(arg, Text) else arg for arg in args)) if args else template

    def resolve(self):
        return self.translate(self.key, self.args, self.parts)

    def __add__(self, other):
        return Text(parts=(self, other))

    def __radd__(self, other):
        return Text(parts=(other, self))


def tr(key, *args):
    return Text(key, args)


def resolve(value):
    return value.resolve() if isinstance(value, Text) else str(value)


_bindings = WeakKeyDictionary()


def render(target, method, value, *prefix):
    """Set and bind UI text explicitly, leaving all raw/user strings untouched."""
    bindings = _bindings.setdefault(target, {})
    token = (method, prefix)
    if isinstance(value, Text):
        bindings[token] = value
    else:
        bindings.pop(token, None)
    getattr(target, method)(*prefix, resolve(value))
    return target


def form_row(form, text, field):
    from PySide6.QtWidgets import QLabel
    caption = QLabel()
    render(caption, 'setText', text)
    form.addRow(caption, field)


def add_tab(tabs, widget, text):
    index = tabs.addTab(widget, resolve(text))
    render(tabs, 'setTabText', text, index)
    return index


def checkbox(text):
    from PySide6.QtWidgets import QCheckBox
    return render(QCheckBox(), 'setText', text)


def groupbox(text):
    from PySide6.QtWidgets import QGroupBox
    return render(QGroupBox(), 'setTitle', text)


class Appearance(QObject):
    changed = Signal()
    language, currency, theme = 'zh', 'JPY', 'charcoal'
    rates = {'JPY': 1, 'CNY': 0.048, 'USD': 0.0067}

    def apply(self, preferences):
        values = {
            'language': preferences.get('language', self.language),
            'currency': preferences.get('currency', self.currency),
            'theme': preferences.get('theme', self.theme),
        }
        allowed = {'language': ('zh', 'en'), 'currency': tuple(self.rates), 'theme': ('charcoal', 'cloud')}
        changed = False
        for key, value in values.items():
            if value in allowed[key] and getattr(self, key) != value:
                setattr(self, key, value)
                changed = True
        if not changed:
            return
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QColor, QPalette
        from .widgets import stylesheet
        app = QApplication.instance()
        if app:
            app.setStyleSheet(stylesheet())
            palette = app.palette()
            for role, name in [(QPalette.ColorRole.Window,'background'),(QPalette.ColorRole.Base,'card'),(QPalette.ColorRole.Text,'text'),(QPalette.ColorRole.WindowText,'text'),(QPalette.ColorRole.ButtonText,'text'),(QPalette.ColorRole.Highlight,'selection')]:
                palette.setColor(role, QColor(self.color(name)))
            app.setPalette(palette)
        for target, bindings in list(_bindings.items()):
            if isValid(target):
                for (method, prefix), value in list(bindings.items()):
                    getattr(target, method)(*prefix, resolve(value))
        self.changed.emit()

    def money(self, value=None, known=True):
        if not known or value is None:
            return resolve(tr('价格未知'))
        value = float(value)
        if value == 0:
            return resolve(tr('免费'))
        converted = value * self.rates[self.currency]
        return f'¥{converted:,.0f}' if self.currency == 'JPY' else f'{self.currency} {converted:,.2f}'

    def item_text(self, item, field='title'):
        english = (item.get('translations') or {}).get('en') or {}
        return (english.get(field) if self.language == 'en' else None) or item.get(field, '')

    def facet(self, item):
        return (item.get('en') if self.language == 'en' else item.get('label')) or item.get('name') or item.get('en') or item.get('slug') or item.get('key', '')

    def color(self, name):
        dark = {'background':'#15161c','card':'#20222c','selected':'#24232f','border':'#363946','accent':'#e598a5','image':'#292d39','muted':'#697086','badge':'#181a22','price':'#ffd3d6','heart':'#302934','favourite':'#ffb2bd','icon':'#c4c7d2','text':'#eeedf4','secondary':'#9fa5b7','local':'#9dcbb7','missing':'#848b9c','selection':'#49313f'}
        light = {'background':'#f4f5f8','card':'#ffffff','selected':'#fcecf0','border':'#d9dce5','accent':'#a54d65','image':'#eceef4','muted':'#7a8193','badge':'#fff7f9','price':'#8a314c','heart':'#f3e7ee','favourite':'#a13d59','icon':'#626a7e','text':'#242735','secondary':'#626b80','local':'#326d53','missing':'#71798d','selection':'#ead5df'}
        return (light if self.theme == 'cloud' else dark)[name]


appearance = Appearance()

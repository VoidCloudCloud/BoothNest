# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the real native client and backend in an explicit disposable home."""
import json
from pathlib import Path
import time
import traceback
import hashlib
import zipfile
from copy import deepcopy

from PySide6.QtCore import QObject, QTimer, Qt, QMimeData
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from .core import query_string, saved_query
from .dialogs import Data, Detail, LocalManager, Scan
from .discovery import QuickFind, ShareFilters, share_text, import_filter
from .presentation import appearance


class Smoke(QObject):
    def __init__(self, window, output):
        super().__init__(window)
        self.window = window
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.passed = False
        self.tests = []
        self.started = time.perf_counter()
        self.running = False
        self.clipboard_original = QMimeData()
        current = QApplication.clipboard().mimeData()
        if current:
            for format in current.formats():
                self.clipboard_original.setData(format,current.data(format))
        window.loaded.connect(self.begin)
        window.backend.failed.connect(self.fail)
        QTimer.singleShot(120000, lambda: self.fail('Native UI smoke test timed out') if not self.passed else None)

    def check(self, name, condition):
        self.tests.append({'name':name, 'passed':bool(condition)})
        if not condition:
            raise AssertionError(name)

    def safe(self, callback):
        def run(*args):
            try:
                callback(*args)
            except Exception:
                self.fail(traceback.format_exc())
        return run

    def after_load(self, action, done):
        def receive(value):
            self.window.loaded.disconnect(receive)
            self.safe(done)(value)
        self.window.loaded.connect(receive)
        action()

    def begin(self, value):
        if self.running:
            return
        self.running = True
        self.safe(self.initial)(value)

    def initial(self, value):
        self.check('real catalogue loaded into QListView model', value['count'] > 0 and self.window.item_model.rowCount() > 0)
        self.original = dict(self.window.preferences)
        self.first_item = value['items'][0]
        self.first_ids = [item['id'] for item in value['items']]
        expected = self.window.backend.home / '.qt-appearance-expected.json'
        if expected.is_file():
            settings = json.loads(expected.read_text('utf-8'))
            self.check('appearance preferences survive a real client restart', all(self.window.preferences.get(key) == setting and getattr(appearance,key) == setting for key,setting in settings.items()))
        self.check('startup controls reflect shared preferences', all(getattr(self.window,key).currentData() == self.window.preferences.get(key,default) for key,default in [('language','zh'),('currency','JPY'),('theme','charcoal')]))
        QTimer.singleShot(3000, self.safe(self.screenshot))

    def screenshot(self):
        # A hidden Windows startup does not paint until grab(); paint once to
        # queue visible thumbnails, then wait for decoding before taking evidence.
        snapshot = self.window.grab()
        decoded = sum(pixmap is not None for pixmap in self.window.images.cache.values())
        attempts = getattr(self, 'image_attempts', 0)
        if decoded < 8 and attempts < 80:
            self.image_attempts = attempts + 1
            QTimer.singleShot(200, self.safe(self.screenshot))
            return
        self.check('packaged image decoders render cached product previews', decoded >= 8)
        snapshot.save(str(self.output / 'qt-gallery.png'))
        self.presentation_state = deepcopy(self.window.state)
        self.paid_item = next((item for item in self.window.item_model.items if item.get('priceKnown') and item.get('price')),self.first_item)
        self.window.open_item(self.paid_item)
        self.wait_preferences(self.presentation_controls)

    def presentation_controls(self):
        self.window.language.setCurrentIndex(self.window.language.findData('en'))
        self.window.currency.setCurrentIndex(self.window.currency.findData('CNY'))
        self.window.theme.setCurrentIndex(self.window.theme.findData('cloud'))
        self.wait_preferences(lambda: self.window.api.request('/api/preferences',self.safe(self.presentation_saved),error=self.fail))

    def presentation_saved(self, preferences):
        self.check('native language currency and theme controls persist through real API', all(preferences.get(key) == value for key,value in [('language','en'),('currency','CNY'),('theme','cloud')]))
        self.check('appearance changes preserve unrelated favourites and saved filters', all(preferences.get(key,[]) == self.original.get(key,[]) for key in ('favourites','saved-searches')))
        self.check('appearance changes preserve active filters and catalogue records', self.window.state == self.presentation_state and self.window.item_model.items[0]['id'] == self.first_item['id'])
        panel = next(panel for panel in self.window.dialogs if isinstance(panel,Detail) and panel.isVisible())
        self.check('existing detail and main navigation switch to English', self.window.nav_buttons['purchased'].text() == 'Purchases' and panel.windowTitle() == 'Item details — BoothNest')
        amount = self.paid_item.get('price') or 0
        expected = f'CNY {amount * .048:,.2f}' if amount else 'Free'
        self.check('card model table and open detail use the selected currency', expected in self.window.item_model.data(self.window.item_model.index(self.window.item_model.items.index(self.paid_item))) and expected in panel.price.text() and self.window.table_model.headerData(2,Qt.Orientation.Horizontal) == 'Price CNY')
        self.check('reference conversion preserves original JPY amounts', self.paid_item.get('price') == amount and appearance.money(1000) == 'CNY 48.00')
        self.window.grab().save(str(self.output / 'qt-light-en-cny.png'))
        panel.grab().save(str(self.output / 'qt-detail-light-en-cny.png'))
        self.window.currency.setCurrentIndex(self.window.currency.findData('USD'))
        self.wait_preferences(self.presentation_usd)

    def presentation_usd(self):
        self.check('USD reference conversion and free unknown states', appearance.money(1000) == 'USD 6.70' and appearance.money(0) == 'Free' and appearance.money(None) == 'Price unknown')
        self.window.language.setCurrentIndex(self.window.language.findData('zh'))
        self.window.currency.setCurrentIndex(self.window.currency.findData('JPY'))
        self.window.theme.setCurrentIndex(self.window.theme.findData('charcoal'))
        self.wait_preferences(self.presentation_dark)

    def presentation_dark(self):
        self.check('language and theme round trip updates existing detail', self.window.nav_buttons['purchased'].text() == '已购清单' and self.window.theme.currentData() == 'charcoal')
        self.window.grab().save(str(self.output / 'qt-dark-zh-jpy.png'))
        for panel in self.window.dialogs:
            if isinstance(panel,Detail) and panel.isVisible(): panel.close()
        QTest.keyClick(self.window,Qt.Key.Key_K,Qt.KeyboardModifier.ControlModifier)
        self.palette_attempts = 0
        QTimer.singleShot(100,self.safe(self.palette_opened))

    def palette_opened(self):
        panels = [panel for panel in self.window.dialogs if isinstance(panel,QuickFind) and panel.isVisible()]
        self.palette_attempts += 1
        if not panels and self.palette_attempts < 20:
            self.window.activateWindow()
            QTest.keyClick(self.window,Qt.Key.Key_K,Qt.KeyboardModifier.ControlModifier)
            QTimer.singleShot(100,self.safe(self.palette_opened)); return
        self.check('Ctrl K opens native quick find', bool(panels))
        self.palette = panels[0]
        self.palette.resultsReady.connect(self.safe(self.palette_ready))
        self.palette.input.setText('MAYO')
        self.palette.search()

    def palette_ready(self):
        self.palette.resultsReady.disconnect()
        groups = {self.palette.list.item(i).data(Qt.ItemDataRole.UserRole)[0] for i in range(self.palette.list.count()) if self.palette.list.item(i).data(Qt.ItemDataRole.UserRole)}
        self.check('typed local palette query supplies item and avatar groups', {'items','avatars'}.issubset(groups))
        self.palette.grab().save(str(self.output / 'qt-quick-find.png'))
        self.palette_avatars = self.palette.results['avatars'][0]['slug']
        self.palette_authors = self.first_item['author']
        self.palette_tags = self.first_item['tags'][0]
        row = next(i for i in range(self.palette.list.count()) if self.palette.list.item(i).data(Qt.ItemDataRole.UserRole) and self.palette.list.item(i).data(Qt.ItemDataRole.UserRole)[0] == 'avatars')
        # Start immediately before the group header and navigate past it with a key.
        self.palette.list.setCurrentRow(row-2)
        QTest.keyClick(self.palette.input,Qt.Key.Key_Down)
        self.check('quick find arrows skip group headings', self.palette.list.currentItem().data(Qt.ItemDataRole.UserRole)[0] == 'avatars')
        self.after_load(lambda: QTest.keyClick(self.palette.input,Qt.Key.Key_Return),self.palette_avatar)

    def palette_avatar(self, value):
        self.check('quick find Enter selects an avatar through real API', self.window.state.get('avatar') == [self.palette_avatars] and value['count'] > 0)
        self.select_palette_group('authors',self.palette_authors,self.palette_author)

    def select_palette_group(self, group, text, done):
        self.window.quick_find()
        panel = next(panel for panel in self.window.dialogs if isinstance(panel,QuickFind) and panel.isVisible())
        def ready():
            panel.resultsReady.disconnect(connected)
            row = next(i for i in range(panel.list.count()) if panel.list.item(i).data(Qt.ItemDataRole.UserRole) == (group,text))
            panel.list.setCurrentRow(row)
            self.after_load(lambda: QTest.keyClick(panel.input,Qt.Key.Key_Return),done)
        connected = self.safe(ready)
        panel.resultsReady.connect(connected)
        panel.input.setText(text); panel.search()

    def palette_author(self, value):
        self.check('quick find author resets previous model filter', self.window.state.get('author') == [self.palette_authors] and 'avatar' not in self.window.state and value['count'] > 0)
        self.select_palette_group('tags',self.palette_tags,self.palette_tag)

    def palette_tag(self, value):
        self.check('quick find tag selects indexed results', self.window.state.get('tag') == [self.palette_tags] and value['count'] > 0)
        state = dict(self.window.state,view='favourites',purchase='recorded',availability='local',ids=[999],fileType=['zip'],localCategory=['private'],minBytes=1234,duplicates=True,token='test-secret',root=r'C:\private')
        self.share_expected = import_filter(share_text(state))
        self.window.state = state
        self.window.show_panel(ShareFilters)
        panel = next(panel for panel in self.window.dialogs if isinstance(panel,ShareFilters) and panel.isVisible())
        exported = panel.export.toPlainText()
        panel.grab().save(str(self.output / 'qt-share-filters.png'))
        self.check('sharing excludes private filters identifiers paths and tokens', all(token not in exported for token in ('ids=','purchase=','availability=','fileType=','localCategory=','minBytes=','duplicates=','test-secret','private')))
        self.check('portable filters round trip canonically', share_text(import_filter(exported)) == exported)
        panel.copy.click()
        self.check('native share copy places reviewed text on clipboard', QApplication.clipboard().text() == exported)
        panel.input.setPlainText(exported)
        self.after_load(panel.apply_filters,self.shared)

    def shared(self, value):
        self.check('pasted shared filters apply through native UI and API', self.window.state['view'] == 'items' and self.window.state.get('tag') == self.share_expected.get('tag') and value['count'] > 0)
        self.window.quick_find()
        panel = next(panel for panel in self.window.dialogs if isinstance(panel,QuickFind) and panel.isVisible())
        def ready():
            panel.resultsReady.disconnect()
            row = next(i for i in range(panel.list.count()) if panel.list.item(i).data(Qt.ItemDataRole.UserRole) == ('items',self.first_item['id']))
            panel.list.setCurrentRow(row)
            QTest.keyClick(panel.input,Qt.Key.Key_Return)
            QTimer.singleShot(600,self.safe(self.palette_item))
        panel.resultsReady.connect(self.safe(ready))
        panel.input.setText(str(self.first_item['id'])); panel.search()

    def palette_item(self):
        panels = [panel for panel in self.window.dialogs if isinstance(panel,Detail) and panel.isVisible() and panel.item['id'] == self.first_item['id']]
        self.check('quick find item Enter opens native item details',bool(panels))
        for panel in panels: panel.close()
        self.window.state = dict(self.presentation_state)
        self.window.search.setText(str(self.first_item['id']))
        self.after_load(self.window.search_changed, self.searched)

    def searched(self, value):
        self.check('search through native search field', any(item['id'] == self.first_item['id'] for item in value['items']))
        self.window.search.setText('BoothNest_no_such_item_9d9232')
        self.after_load(self.window.search_changed, self.empty)

    def empty(self, value):
        self.check('empty results native state', value['count'] == 0 and self.window.stack.currentIndex() == 2)
        self.after_load(self.window.reset, self.reset)

    def reset(self, value):
        self.check('clear filters restores results', value['count'] > 0)
        if value['totalPages'] > 1:
            self.after_load(lambda: self.window.turn(1), self.page)
        else:
            self.page(value)

    def page(self, value):
        self.check('native pagination matches API response', self.window.page_spin.value() == value['page'])
        self.window.state['sort'] = 'likes'
        self.after_load(self.window.load, self.sort)

    def sort(self, value):
        likes = [item['likes'] for item in value['items']]
        self.check('server sorting preserved', likes == sorted(likes, reverse=True))
        self.window.state.update(view='local', page=1, sort='trending')
        self.after_load(self.window.load, self.local)

    def local(self, value):
        self.check('local scope matches joined inventory', value['count'] > 0 and all(item['local']['copies'] > 0 for item in value['items']))
        self.window.state.update(view='items', page=1)
        self.window.state['category'] = ['clothing']
        self.after_load(self.window.load, self.filtered)

    def filtered(self, value):
        self.check('category filter applied through API', all('clothing' in item['categorySlugs'] for item in value['items']))
        # Test a saved search against the actual server validator, not a Python imitation.
        state = {'view':'items','sort':'trending','adult':'safe','q':'MAYO * ~','tag':['衣装'], 'excludeTag':['限定'],'free':False,'min':0,'pageSize':40}
        self.saved = {'id':'qt_smoke_filter','name':'Qt 自验筛选','query':saved_query(state)}
        self.window.api.request('/api/preferences', self.safe(self.saved_ok), body={'saved-searches':self.original.get('saved-searches', [])[:49] + [self.saved]}, error=self.fail)

    def saved_ok(self, _):
        self.check('saved filters accepted by existing server canonical validator', True)
        self.window.api.request('/api/preferences', self.safe(self.loaded_preferences), error=self.fail)

    def loaded_preferences(self, value):
        self.check('shared saved filters round trip', any(entry['id'] == self.saved['id'] for entry in value.get('saved-searches', [])))
        self.window.preferences = value
        self.test_id = self.first_item['id']
        self.was_favourite = self.test_id in self.window.favourites()
        self.window.toggle_favourite(self.test_id)
        self.wait_preferences(self.favourite)

    def wait_preferences(self, done):
        def poll():
            if self.window.preference_busy or self.window.preference_queue:
                QTimer.singleShot(50, poll)
            else:
                self.safe(done)()
        QTimer.singleShot(50, poll)

    def favourite(self):
        self.check('favourite writes shared preferences', (self.test_id in self.window.favourites()) != self.was_favourite)
        self.window.toggle_favourite(self.test_id)
        self.window.open_item(self.first_item)
        self.wait_preferences(self.details)

    def details(self):
        self.check('favourite toggle round trip', (self.test_id in self.window.favourites()) == self.was_favourite)
        panel = next(panel for panel in self.window.dialogs if isinstance(panel, Detail))
        self.check('native detail contains description and recent history', bool(panel.description.toPlainText()) and self.window.preferences['recent-views'][0]['id'] == self.test_id)
        panel.grab().save(str(self.output / 'qt-detail.png'))
        panel.close()
        self.window.show_panel(LocalManager)
        QTimer.singleShot(2200, self.safe(self.manager))

    def manager(self):
        panel = next(panel for panel in self.window.dialogs if isinstance(panel, LocalManager))
        self.check('native inventory table loaded', panel.model.rowCount() > 0 and bool(panel.context))
        self.check('native grouped statistics loaded', panel.stats_model.rowCount() > 0)
        panel.grab().save(str(self.output / 'qt-inventory.png'))
        panel.close()
        self.window.show_panel(Scan)
        QTimer.singleShot(2000, self.safe(self.scan))

    def scan(self):
        panel = next(panel for panel in self.window.dialogs if isinstance(panel, Scan))
        self.check('native scanner reads existing engine state', not panel.initial and bool(panel.root.text()))
        panel.grab().save(str(self.output / 'qt-scan.png'))
        downloads = self.output / 'test-downloads'
        downloads.mkdir(exist_ok=True)
        self.fixture_file = downloads / '8659461_QtScanFixture.zip'
        with zipfile.ZipFile(self.fixture_file, 'w') as archive:
            archive.writestr('README.txt', 'https://booth.pm/ja/items/8659461\nQt native scanner verification fixture')
        self.fixture_hash = hashlib.sha256(self.fixture_file.read_bytes()).hexdigest()
        self.scanner = panel
        panel.root.setText(str(downloads.resolve()))
        panel.offline.setChecked(True)
        panel.full.setChecked(True)
        panel.start_button.click()
        self.scan_attempts = 0
        QTimer.singleShot(600, self.scan_progress)

    def scan_progress(self):
        self.scan_attempts += 1
        if self.scan_attempts > 80:
            self.fail('Native scanner fixture timed out')
            return
        self.window.api.request('/api/scan/status', self.safe(self.scanned), error=self.fail)

    def scanned(self, value):
        task = value.get('task', {})
        if task.get('busy') or not task.get('finished'):
            QTimer.singleShot(300, self.scan_progress)
            return
        self.check('native scan button executes real engine scan', bool((task.get('result') or {}).get('ok')))
        self.check('scan leaves input archive unchanged', hashlib.sha256(self.fixture_file.read_bytes()).hexdigest() == self.fixture_hash)
        dataset = json.loads((self.window.backend.home / 'data/dataset.json').read_text('utf-8-sig'))
        self.check('scan updates only disposable inventory', len(dataset.get('items', [])) == 1 and 'test-downloads' in dataset.get('root', ''))
        self.scanner.close()
        self.window.show_panel(Data)
        QTimer.singleShot(1800, self.safe(self.data))

    def data(self):
        panel = next(panel for panel in self.window.dialogs if isinstance(panel, Data))
        self.check('native sync and purchase controls load', not panel.first_sync and bool(panel.bridge))
        panel.grab().save(str(self.output / 'qt-data.png'))
        self.window.language.setCurrentIndex(self.window.language.findData('en'))
        self.window.currency.setCurrentIndex(self.window.currency.findData('CNY'))
        self.window.theme.setCurrentIndex(self.window.theme.findData('cloud'))
        self.wait_preferences(self.data_appearance)

    def data_appearance(self):
        panel = next(panel for panel in self.window.dialogs if isinstance(panel, Data) and panel.isVisible())
        self.check('already open data and scanner controls retranslate without altering inputs', panel.windowTitle() == 'Data and sync — BoothNest' and panel.sync_enabled.text() == 'Automatically sync public items while the app is running' and self.scanner.offline.text() == 'Use local cache only')
        panel.grab().save(str(self.output / 'qt-data-light-en.png'))
        panel.close()
        # Keep these settings on the disposable home for the next real-process
        # startup check; original personal preferences are never changed.
        settings = {'language':'en','currency':'CNY','theme':'cloud'}
        (self.window.backend.home / '.qt-appearance-expected.json').write_text(json.dumps(settings),encoding='utf-8')
        self.window.api.request('/api/preferences', self.safe(self.restore), body=dict(settings,**{'favourites':self.original.get('favourites',[]),'recent-views':self.original.get('recent-views',[]),'saved-searches':self.original.get('saved-searches',[])}), error=self.fail)

    def restore(self, _):
        self.check('isolated preferences restored after exercise', True)
        self.window.state = dict(view='items',q='',sort='trending',adult='safe',page=1,pageSize=40)
        self.after_load(self.window.load, lambda _: self.finish())

    def finish(self):
        self.passed = True
        self.report()
        self.restore_clipboard()
        self.window.close()

    def fail(self, message):
        if getattr(self, 'failing', False):
            return
        self.failing = True
        self.tests.append({'name':'exception','passed':False,'error':str(message)})
        self.report()
        self.restore_clipboard()
        self.window.close()

    def restore_clipboard(self):
        if self.clipboard_original is not None:
            QApplication.clipboard().setMimeData(self.clipboard_original)
            self.clipboard_original = None

    def report(self):
        (self.output / 'smoke.json').write_text(json.dumps({'passed':self.passed,'seconds':round(time.perf_counter()-self.started,2),'tests':self.tests}, ensure_ascii=False, indent=2), encoding='utf-8')
